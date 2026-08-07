"""자막(SRT)을 '한 컷 = 최대 N자'로 기계적으로 강제 분할한다.

왜 스크립트인가:
  자막 텍스트를 N자 이하로 묶는 것은 타이포그래픽 제약(기계적 규칙)이다.
  프롬프트로 "모든 자막을 16자 이하로"라고 지시해도 LLM은 100+개 자막에서
  반드시 일부를 어긴다 — 규칙 준수는 문서가 아니라 구조가 만든다.
  그래서 AI는 의미 보정(Whisper 오인식 교정·자연스러운 구 묶기)만 하고,
  '16자 이하'라는 하드 캡은 이 스크립트가 결정론적으로 보장한다.

무엇을 하나:
  1. SRT를 파싱한다(컷별 start/end/text).
  2. 길이가 캡(기본 16자)을 넘는 컷을 어절(띄어쓰기) 경계로 그리디 분할한다.
     - 어절 하나가 단독으로 캡을 넘으면(긴 URL·영문 등) 글자 단위로 강제 분할.
  3. 각 분할 컷의 시간은 원래 컷 구간 [start,end] 안에서 글자수 비례로 배분한다.
     → 분할 컷은 절대 원래 구간 밖으로 나가지 않으므로 음성·슬라이드 싱크 계약 불변.
  4. 분할 후에도 캡을 넘는 컷이 있으면 예외를 던진다(조용한 실패 금지 — fail loud).

글자수 기준(--count):
  full    공백·문장부호 포함 전체 길이 len(text)         (기본, "공백 포함 라인 폭")
  nospace 공백만 제외(문장부호는 셈)
  letters 공백·문장부호 모두 제외(순수 글자/숫자만)

사용:
  python split_captions.py <input.srt>                  # 제자리 재작성(분할 직전 원본 .raw.srt 백업)
  python split_captions.py <input.srt> -o <out.srt>     # 별도 파일로
  python split_captions.py <input.srt> --check          # 검사만(초과 컷 있으면 exit 1)
  python split_captions.py <input.srt> --max 16 --count full
"""
import argparse
import pathlib
import re
import shutil
import sys

MAX_CHARS = 16
COUNT_DEFAULT = "full"

# SRT 타임코드: 00:00:01,500 --> 00:00:05,200 ( . 도 허용 )
_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def measure(text: str, mode: str = COUNT_DEFAULT) -> int:
    """글자수 기준에 따른 길이."""
    if mode == "full":
        return len(text)
    s = re.sub(r"\s", "", text)
    if mode == "nospace":
        return len(s)
    if mode == "letters":
        return sum(1 for ch in s if ch.isalnum())
    raise ValueError(f"알 수 없는 --count 모드: {mode}")


def _to_seconds(h, m, s, ms) -> float:
    ms = ms.ljust(3, "0")  # ',5' 같은 1~2자리 밀리초 보정
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _fmt(t: float) -> str:
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000))
    h, total_ms = divmod(total_ms, 3_600_000)
    m, total_ms = divmod(total_ms, 60_000)
    s, ms = divmod(total_ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(raw: str):
    """SRT 텍스트 → [(start, end, text)] (text는 공백 1개로 합친 한 줄).
    형식 깨진 블록을 조용히 버리면 그 결과가 정상 파일로 재작성되므로(무결성 위반) fail-loud."""
    raw = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    cues, dropped = [], []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.split("\n")
        idx = next((i for i, ln in enumerate(lines) if _TIME_RE.search(ln)), None)
        if idx is None:
            if block.strip():                      # 내용이 있는데 타임코드가 없다 = malformed
                dropped.append(block.strip().splitlines()[0][:40])
            continue
        m = _TIME_RE.search(lines[idx])
        start = _to_seconds(*m.group(1, 2, 3, 4))
        end = _to_seconds(*m.group(5, 6, 7, 8))
        text = " ".join(ln.strip() for ln in lines[idx + 1:] if ln.strip())
        if text:
            cues.append((start, end, text))
        else:                                      # 타임코드는 있는데 텍스트가 없음
            dropped.append(f"(빈 텍스트) {lines[idx].strip()[:40]}")
    if dropped:
        raise RuntimeError(
            f"SRT에 형식 깨진 블록 {len(dropped)}개 — 무결성 보장 불가로 중단 "
            f"(첫 건: {dropped[0]!r}). 원본 SRT를 수리 후 재실행하세요.")
    if not cues:
        raise RuntimeError("SRT에 유효한 컷이 0개 — 빈/깨진 입력")
    return cues


def _hard_split(word: str, max_chars: int, mode: str):
    """어절 하나가 캡을 넘을 때 글자 단위로 쪼갠다."""
    pieces, cur = [], ""
    for ch in word:
        if not cur or measure(cur + ch, mode) <= max_chars:
            cur += ch
        else:
            pieces.append(cur)
            cur = ch
    if cur:
        pieces.append(cur)
    return pieces


def pack_lines(text: str, max_chars: int, mode: str):
    """텍스트를 어절 경계로 그리디 패킹 → 각 줄이 max_chars 이하."""
    words = text.split()
    if not words:
        return []
    lines, cur = [], ""
    for w in words:
        if measure(w, mode) > max_chars:
            if cur:
                lines.append(cur)
                cur = ""
            lines.extend(_hard_split(w, max_chars, mode))
            continue
        cand = w if not cur else cur + " " + w
        if measure(cand, mode) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def split_cue(start: float, end: float, text: str, max_chars: int, mode: str):
    """한 컷을 max_chars 이하 여러 컷으로. 시간은 구간 내 글자수 비례 배분."""
    lines = pack_lines(text, max_chars, mode)
    if len(lines) <= 1:
        return [(start, end, lines[0] if lines else text)]
    # 시간 가중치는 발화량에 가까운 '공백 제외 글자수'로(캡 기준과 무관)
    weights = [max(measure(ln, "nospace"), 1) for ln in lines]
    total = sum(weights)
    dur = max(end - start, 0.0)
    out, t0, acc = [], start, 0
    for i, (ln, w) in enumerate(zip(lines, weights)):
        acc += w
        t1 = end if i == len(lines) - 1 else start + dur * acc / total
        out.append((t0, t1, ln))
        t0 = t1
    return out


def render_srt(cues) -> str:
    blocks = [f"{i}\n{_fmt(s)} --> {_fmt(e)}\n{t}" for i, (s, e, t) in enumerate(cues, 1)]
    return "\n\n".join(blocks) + "\n"


def enforce(raw: str, max_chars: int = MAX_CHARS, mode: str = COUNT_DEFAULT):
    """SRT 텍스트 → (재작성된 SRT, 통계)."""
    cues = parse_srt(raw)
    out_cues, split_count = [], 0
    for s, e, t in cues:
        parts = split_cue(s, e, t, max_chars, mode)
        if len(parts) > 1:
            split_count += 1
        out_cues.extend(parts)
    new_raw = render_srt(out_cues)
    stats = {"in": len(cues), "out": len(out_cues), "split": split_count}
    return new_raw, stats


def offenders(raw: str, max_chars: int, mode: str):
    """캡을 넘는 컷 목록 [(번호, 텍스트, 길이)]."""
    return [
        (i, t, measure(t, mode))
        for i, (s, e, t) in enumerate(parse_srt(raw), 1)
        if measure(t, mode) > max_chars
    ]


def enforce_file(path, max_chars: int = MAX_CHARS, mode: str = COUNT_DEFAULT,
                 backup: bool = True):
    """파일을 제자리 강제 분할. 멱등(이미 ≤max면 무변경·무백업). 통계 dict 반환.

    분할 후에도 캡 초과가 남으면 RuntimeError(fail loud)."""
    path = pathlib.Path(path)
    raw = path.read_text(encoding="utf-8-sig")  # BOM 있어도 허용
    new_raw, stats = enforce(raw, max_chars, mode)

    bad = offenders(new_raw, max_chars, mode)
    if bad:
        sample = "; ".join(f'#{i}({n}자)"{t}"' for i, t, n in bad[:5])
        raise RuntimeError(f"분할 후에도 {len(bad)}개 컷이 {max_chars}자 초과: {sample}")

    normalized = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    changed = new_raw != normalized
    backup_path = None
    if changed:
        if backup:
            bpath = path.with_suffix(".raw" + path.suffix)
            shutil.copy2(path, bpath)  # 분할 직전 원본을 바이트 그대로 보존(매 분할마다 갱신 — 재녹음 대비)
            backup_path = str(bpath)
        path.write_text(new_raw, encoding="utf-8")
    stats["changed"] = changed
    stats["backup"] = backup_path
    return stats


def main() -> None:
    try:  # 한글 콘솔 출력 보호(cp949 환경)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="SRT 자막을 한 컷 최대 N자로 강제 분할")
    ap.add_argument("srt", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path, help="출력 파일(기본: 제자리 재작성)")
    ap.add_argument("--max", type=int, default=MAX_CHARS, help=f"한 컷 최대 글자수(기본 {MAX_CHARS})")
    ap.add_argument("--count", choices=("full", "nospace", "letters"),
                    default=COUNT_DEFAULT, help="글자수 기준(기본 full=공백 포함)")
    ap.add_argument("--check", action="store_true", help="검사만 — 초과 컷 있으면 exit 1")
    ap.add_argument("--no-backup", action="store_true", help="제자리 재작성 시 .raw.srt 백업 생략")
    args = ap.parse_args()

    if not args.srt.is_file():
        sys.exit(f"[오류] SRT 없음: {args.srt}")

    if args.check:
        bad = offenders(args.srt.read_text(encoding="utf-8-sig"), args.max, args.count)
        if bad:
            print(f"[실패] {len(bad)}개 컷이 {args.max}자 초과:")
            for i, t, n in bad:
                print(f"  #{i} ({n}자) {t}")
            sys.exit(1)
        print(f"[통과] 모든 컷이 {args.max}자 이하입니다.")
        return

    if args.out:
        raw = args.srt.read_text(encoding="utf-8-sig")
        new_raw, stats = enforce(raw, args.max, args.count)
        bad = offenders(new_raw, args.max, args.count)
        if bad:
            sys.exit(f"[오류] 분할 후에도 {len(bad)}개 컷이 {args.max}자 초과 — 버그 신고 바람")
        args.out.write_text(new_raw, encoding="utf-8")
        print(f"[완료] {args.out} — {stats['in']}→{stats['out']}컷, {stats['split']}개 분할 ({args.max}자/{args.count})")
        return

    stats = enforce_file(args.srt, args.max, args.count, backup=not args.no_backup)
    if not stats["changed"]:
        print(f"[변경 없음] 이미 모든 컷이 {args.max}자 이하 ({stats['in']}컷)")
    else:
        print(f"[완료] {args.srt} — {stats['in']}→{stats['out']}컷, {stats['split']}개 분할 ({args.max}자/{args.count})")
        if stats["backup"]:
            print(f"  원본 백업: {stats['backup']}")


if __name__ == "__main__":
    main()
