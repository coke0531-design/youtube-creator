"""Whisper transcript.json(단어 타임스탬프)을 구(phrase) 단위 마크다운으로 압축한다 — 읽기 뷰.

  browser-use/video-use의 `pack_transcripts.py` 아이디어(MIT)를 이 파이프라인에 맞게 개작.

왜 스크립트인가:
  transcript.json은 400초 영상에서도 단어 600~1,700개짜리 배열이다. AI가 이걸 통째로
  읽으면 컨텍스트만 잡아먹고 정작 필요한 정보 — 말이 끊기는 지점(무음 갭 = 쇼츠 컷
  후보)과 구의 경계 — 는 숫자 더미에 묻힌다. "갭이 큰 곳을 찾아라"는 뺄셈이지
  판단이 아니므로 결정론적으로 계산해 한 화면에 펼치는 게 맞다.
  transcript.json은 모든 하류(자막·슬라이드·캡처)의 타임베이스 원본이므로 **절대 수정하지
  않는다** — 이 스크립트는 읽기 전용 파생물 하나만 만든다.

무엇을 하나:
  1. transcript.json의 words[]를 읽는다({word,start,end} — 이 세 키만 필수).
  2. 인접 단어 갭(next.start − prev.end) ≥ --gap 이면 구를 끊는다.
     files[]/merged_from[] 오프셋 경계(녹음 파일이 바뀌는 지점)에서도 무조건 끊고
     `— 파일 경계: <파일명> —` 줄을 남긴다.
  3. 구 사이 갭이 ≥ --cut-gap 이면 `✂`(쇼츠 컷 후보), 그 미만이면 `·`로 표기한다.
     (기본값은 gap 0.5 > cut-gap 0.4 이므로 전부 ✂ — `--gap 0.3`처럼 낮추면 구분이 생긴다.)
  4. 끝에 갭 상위 10 표를 붙인다(시각·길이 내림차순).
  5. 단어 텍스트는 원문 그대로 공백 join — 오탈자·오인식을 **교정하지 않는다**(원본 충실).
  6. fail-loud: 파일 없음·words 비어 있음·start>end 같은 깨진 단어는 exit 2로 즉시 중단.

사용:
  python pack_transcript.py <작업폴더>                    # → <작업폴더>/03_자막/transcript_packed.md
  python pack_transcript.py <.../03_자막/transcript.json> # 파일 직접 지정
  python pack_transcript.py <작업폴더> --gap 0.3 --cut-gap 0.4
  python pack_transcript.py <작업폴더> --out <path.md>    # 다른 곳에 쓰기

종료 코드:
  0  성공(멱등 — 같은 입력이면 바이트 동일한 결과를 덮어쓴다)
  2  입력 오류(경로 없음·JSON 파싱 실패·words 없음/비어 있음·깨진 타임스탬프)
"""
import argparse
import json
import pathlib
import sys

# 한국어 Windows: 파이프/콘솔이 cp949면 ✂·→ 등 출력에서 UnicodeEncodeError로 죽는다.
# 이 스크립트는 도구(Claude Code)가 UTF-8 파이프로 실행하는 게 1차 경로 — UTF-8로 고정.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GAP_DEFAULT = 0.5        # 구 분절 기준 갭(초)
CUT_GAP_DEFAULT = 0.4    # 쇼츠 컷 후보 갭(초)
TOP_GAPS = 10            # 갭 상위 표 행 수
CAPTION_DIR = "03_자막"
TRANSCRIPT_NAME = "transcript.json"
OUT_NAME = "transcript_packed.md"


class InputError(Exception):
    """입력이 계약을 어겼다 — exit 2."""


def fmt_t(sec: float) -> str:
    """003.42 형태(초, 소수 2자리, 정수부 최소 3자리)."""
    return f"{sec:06.2f}"


def resolve_input(target: pathlib.Path) -> pathlib.Path:
    """작업폴더면 03_자막/transcript.json을, 파일이면 그 파일을 돌려준다."""
    if target.is_dir():
        cand = target / CAPTION_DIR / TRANSCRIPT_NAME
        if not cand.is_file():
            raise InputError(f"작업폴더에 {CAPTION_DIR}/{TRANSCRIPT_NAME}이 없다: {cand}")
        return cand
    if target.is_file():
        return target
    raise InputError(f"경로가 없다: {target}")


def load_words(path: pathlib.Path):
    """words[]를 검증하며 읽는다. 깨진 단어 하나라도 있으면 중단(조용한 스킵 금지)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"JSON 파싱 실패: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise InputError(f"최상위가 object가 아니다: {path}")

    raw = data.get("words")
    if not isinstance(raw, list) or not raw:
        raise InputError(f"words[]가 없거나 비어 있다: {path}")

    words = []
    for i, w in enumerate(raw):
        if not isinstance(w, dict):
            raise InputError(f"words[{i}]가 object가 아니다")
        if "word" not in w or "start" not in w or "end" not in w:
            raise InputError(f"words[{i}]에 word/start/end 중 빠진 키가 있다: {w}")
        try:
            start = float(w["start"])
            end = float(w["end"])
        except (TypeError, ValueError) as exc:
            raise InputError(f"words[{i}] 타임스탬프가 숫자가 아니다: {w}") from exc
        if start != start or end != end:  # NaN
            raise InputError(f"words[{i}] 타임스탬프가 NaN이다: {w}")
        if start > end:
            raise InputError(f"words[{i}] start>end (깨진 단어): {w}")
        text = str(w["word"]).strip()
        words.append({"word": text, "start": start, "end": end})
    return data, words


def load_files(data):
    """files[] 또는 merged_from[](같은 의미의 별칭)를 [(offset, name)]로 정규화."""
    raw = data.get("files")
    if not isinstance(raw, list) or not raw:
        raw = data.get("merged_from")
    if not isinstance(raw, list) or not raw:
        return []
    out = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        name = f.get("file")
        try:
            offset = float(f.get("offset"))
        except (TypeError, ValueError):
            continue
        if name is None:
            continue
        out.append((offset, str(name)))
    out.sort(key=lambda x: x[0])
    return out


def file_index(files, t: float) -> int:
    """시각 t가 몇 번째 파일에 속하는지(오프셋 이하 중 마지막). files 없으면 0."""
    idx = 0
    for i, (offset, _name) in enumerate(files):
        if t + 1e-9 >= offset:
            idx = i
        else:
            break
    return idx


def build_phrases(words, files, gap: float):
    """구 리스트와 구 사이 경계 정보를 만든다.

    반환: phrases = [{start,end,text,file_idx}],
          breaks[i] = 구 i와 i+1 사이 {gap, prev_end, next_start, boundary(파일명|None)}
    """
    phrases = []
    breaks = []
    cur = [words[0]]
    cur_fi = file_index(files, words[0]["start"])
    for prev, nxt in zip(words, words[1:]):
        g = nxt["start"] - prev["end"]
        nxt_fi = file_index(files, nxt["start"])
        boundary = files[nxt_fi][1] if (files and nxt_fi != cur_fi) else None
        if g >= gap or boundary is not None:
            phrases.append({
                "start": cur[0]["start"],
                "end": cur[-1]["end"],
                "text": " ".join(w["word"] for w in cur),
                "file_idx": cur_fi,
            })
            breaks.append({
                "gap": g,
                "prev_end": prev["end"],
                "next_start": nxt["start"],
                "boundary": boundary,
            })
            cur = [nxt]
            cur_fi = nxt_fi
        else:
            cur.append(nxt)
    phrases.append({
        "start": cur[0]["start"],
        "end": cur[-1]["end"],
        "text": " ".join(w["word"] for w in cur),
        "file_idx": cur_fi,
    })
    return phrases, breaks


def render(src_label, data, words, files, phrases, breaks, gap, cut_gap):
    duration = data.get("duration")
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        duration = words[-1]["end"]
    wpm = len(words) / (duration / 60.0) if duration > 0 else 0.0

    if files:
        offsets = " · ".join(f"{name}={fmt_t(off)}" for off, name in files)
    else:
        offsets = "단일 파일"

    lines = []
    lines.append(f"# transcript_packed — {src_label}")
    lines.append(
        f"- 길이 {duration:.2f}s · 단어 {len(words)} · 구 {len(phrases)} · "
        f"분절 기준 갭 ≥ {gap:g}s · 컷 후보 갭 ≥ {cut_gap:g}s · 분당 어절 {wpm:.1f}"
    )
    lines.append(f"- 파일 오프셋: {offsets}")
    lines.append("")
    lines.append("## 구 목록")
    for i, p in enumerate(phrases):
        lines.append(f"[{fmt_t(p['start'])}-{fmt_t(p['end'])}] {p['text']}")
        if i < len(breaks):
            b = breaks[i]
            if b["gap"] >= gap or b["gap"] >= cut_gap:
                mark = "✂" if b["gap"] >= cut_gap else "·"
                lines.append(
                    f"  {mark} 갭 {b['gap']:.2f}s "
                    f"({fmt_t(b['prev_end'])}→{fmt_t(b['next_start'])})"
                )
            if b["boundary"]:
                lines.append(f"— 파일 경계: {b['boundary']} —")

    # 갭 상위 표: 임계값과 무관하게 인접 단어 갭 전체에서 뽑는다(임계 조정 근거).
    all_gaps = [
        (nxt["start"] - prev["end"], prev["end"], nxt["start"])
        for prev, nxt in zip(words, words[1:])
    ]
    top = sorted(all_gaps, key=lambda x: (-x[0], x[1]))[:TOP_GAPS]
    lines.append("")
    lines.append(f"## 갭 상위 {TOP_GAPS}")
    lines.append("| # | 시각 | 길이 |")
    lines.append("|---|---|---|")
    for rank, (g, a, b) in enumerate(top, 1):
        lines.append(f"| {rank} | {fmt_t(a)}→{fmt_t(b)} | {g:.2f}s |")
    lines.append("")
    return "\n".join(lines)


def rel_label(path: pathlib.Path) -> str:
    """헤더에 쓸 상대 경로(cwd 기준, 안 되면 절대). 구분자는 /로 통일."""
    try:
        label = str(path.resolve().relative_to(pathlib.Path.cwd().resolve()))
    except ValueError:
        label = str(path.resolve())
    return label.replace("\\", "/")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Whisper transcript.json을 구 단위 마크다운으로 압축한다(읽기 전용 파생물).",
    )
    ap.add_argument("target", help="작업폴더 또는 transcript.json 경로")
    ap.add_argument("--gap", type=float, default=GAP_DEFAULT,
                    help=f"구 분절 기준 갭(초, 기본 {GAP_DEFAULT})")
    ap.add_argument("--cut-gap", type=float, default=CUT_GAP_DEFAULT,
                    help=f"쇼츠 컷 후보 갭(초, 기본 {CUT_GAP_DEFAULT})")
    ap.add_argument("--out", default=None, help="출력 경로(기본 03_자막/transcript_packed.md)")
    args = ap.parse_args(argv)

    if args.gap <= 0 or args.cut_gap <= 0:
        print("[pack_transcript] --gap/--cut-gap은 0보다 커야 한다", file=sys.stderr)
        return 2

    try:
        src = resolve_input(pathlib.Path(args.target))
        data, words = load_words(src)
    except InputError as exc:
        print(f"[pack_transcript] {exc}", file=sys.stderr)
        return 2

    files = load_files(data)
    phrases, breaks = build_phrases(words, files, args.gap)
    text = render(rel_label(src), data, words, files, phrases, breaks, args.gap, args.cut_gap)

    out = pathlib.Path(args.out) if args.out else src.parent / OUT_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    # LF 고정(newline="") — Windows에서도 CRLF로 부풀지 않게.
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

    print(f"[pack_transcript] {src} → {out}")
    print(f"  단어 {len(words)} · 구 {len(phrases)} · "
          f"최대 갭 {max((b['gap'] for b in breaks), default=0.0):.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
