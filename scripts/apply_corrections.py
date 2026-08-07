"""자막(SRT)의 Whisper 오인식을 영구 교정 사전으로 기계 치환한다.

왜 스크립트인가:
  같은 고유명사 오인식(클러드코드→클로드 코드, 도퇴되→도태되)이 영상마다
  재발하는데, LLM의 일회성 대본 대조 보정은 100+개 자막에서 반드시 일부를
  놓친다 — 규칙 준수는 문서가 아니라 구조가 만든다(split_captions.py와 동일 철학).
  반복 오인식은 레퍼런스/교정사전.json(재사용 자산)에 쌓고 이 스크립트가
  결정론적으로 치환한다. AI는 사전 밖 오류만 대본 대조로 보정한다.

무엇을 하나:
  1. 레퍼런스/교정사전.json 의 replace(무조건 티어) + replace_watch(감시 티어)
     맵을 로드한다(replace → replace_watch 순, 각 맵의 등재 순서대로 적용).
     - 로드 시 사전 lint(fail loud): JSON 중복 키(파서가 조용히 last-wins로
       삼키기 전에 차단) / 두 맵 간 키 중복 / 맵이 아닌 값 / 키==값 / 값 안에
       키가 다시 매치되는 비멱등 조합 / 짧은 키가 그것을 포함하는 긴 키보다
       먼저 등재된 순서 오류.
  2. SRT의 텍스트 라인만 substring 치환한다 — 순번·타임코드 라인의 '내용'은
     건드리지 않으므로 타임코드·싱크 계약 불변. (단 바이트 보존은 아니다 —
     split_captions.py와 동일하게 BOM 제거·개행 LF 정규화 후 UTF-8로 재작성.)
  3. 항목별 적용 횟수 리포트를 출력한다(미출현 항목은 개수만 — 영구 사전은
     대부분의 항목이 특정 영상에 안 나오는 것이 정상).
  4. 감시 티어(replace_watch)는 예약 구조다 — 현재 미사용(등재 0건)이며 수확
     대상이 아니다(오탐 가능 항목은 사전에서 제외해 SKILL.md 주의 목록으로 —
     2026-07-06 사용자 결정, 등재하려면 사용자 승인 필요). 등재될 경우 해당
     치환 라인의 before → after 전문이 리포트에 표시된다(가시화이지 차단
     게이트는 아님 — exit 0으로 파일은 이미 저장됨).

하지 않는 것:
  - transcript.json(Whisper 원본)은 절대 건드리지 않는다 — 쇼츠 컷 계산에
    재사용되는 불변 산출물이다(SKILL.md 규약). 이 스크립트는 .json 입력을 거부한다.
  - 문맥 의존 교정은 사전에 넣지 않는다(교정사전.json _규칙 참조) —
    그런 교정은 해당 영상 한정 AI 보정 몫.

순서 계약:
  반드시 split_captions.py(16자 분할) '이전'에 실행한다 — 치환으로 컷이
  16자를 넘을 수 있고, 분할은 그 뒤 3b가 책임진다.

사용:
  python apply_corrections.py <input.srt>              # 제자리 재작성(변경 시 .precorrect.srt 백업)
  python apply_corrections.py <input.srt> --check      # 검사만(사전 매치가 남아 있으면 exit 1)
  python apply_corrections.py <input.srt> --dict <교정사전.json>
"""
import argparse
import json
import pathlib
import re
import shutil
import sys

DICT_DEFAULT = pathlib.Path(__file__).resolve().parent.parent / "레퍼런스" / "교정사전.json"

# SRT 타임코드: 00:00:01,500 --> 00:00:05,200 ( . 도 허용 ) — split_captions.py와 동일
_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _reject_dup_keys(pairs):
    """json.loads가 같은 오브젝트 내 중복 키를 조용히 last-wins로 삼키기 전에 잡는다."""
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"JSON 오브젝트에 중복 키: {k!r}")
        d[k] = v
    return d


def load_dict(path: pathlib.Path):
    """교정사전.json → (전체 치환 맵, 감시 티어 키 집합). 결함 사전이면 fail loud.

    치환 맵은 replace(무조건) → replace_watch(감시) 순서로 합쳐진다 — 각 맵의
    등재 순서 보존. 감시 티어 키는 치환 시 라인 전문 리포트 대상."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"),
                          object_pairs_hook=_reject_dup_keys)
    except FileNotFoundError:
        sys.exit(f"[오류] 교정사전 없음: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"[오류] 교정사전 JSON 파싱 실패: {path} — {e}")
    except ValueError as e:  # _reject_dup_keys (JSONDecodeError보다 뒤에 — 서브클래스 관계)
        sys.exit(f"[오류] 교정사전 결함: {path} — {e}")
    base = data.get("replace")
    watch = data.get("replace_watch", {})  # 키 부재만 빈 맵 — falsy 비딕트([]·""·null)는 아래서 fail loud
    if not isinstance(base, dict) or not base:
        sys.exit(f"[오류] 교정사전에 replace 맵이 없거나 비어 있음: {path}")
    if not isinstance(watch, dict):
        sys.exit(f"[오류] replace_watch는 맵이어야 함(현재 {type(watch).__name__}): {path}")
    dup = set(base) & set(watch)
    if dup:
        sys.exit(f"[오류] replace와 replace_watch에 같은 키 중복: {sorted(dup)}")
    repl = {**base, **watch}
    for k, v in repl.items():
        if not k or not isinstance(v, str):
            sys.exit(f"[오류] 잘못된 항목: {k!r} → {v!r}")
        if k == v:
            sys.exit(f"[오류] 키와 값이 같음(무의미): {k!r}")
    # 멱등성 lint: 어떤 키가 어떤 값 안에 다시 매치되면, 치환 결과에 키가 남아
    # 재실행마다 또 치환된다(비멱등). 등재 시점에 시끄럽게 막는다.
    for k in repl:
        for k2, v2 in repl.items():
            if k in v2:
                sys.exit(
                    f"[오류] 비멱등 사전: '{k2}' → '{v2}' 치환 결과에 키 '{k}'가 다시 매치됨 "
                    f"— 교정사전.json 항목을 조정하라"
                )
    # 순서 lint: 짧은 키가 그것을 포함하는 긴 키보다 먼저 등재되면, 짧은 키가
    # 먼저 치환돼 긴 키는 영영 매치되지 않는다(등재 순서 의존 버그). 긴 키 먼저.
    keys = list(repl)
    for i, k in enumerate(keys):
        for k2 in keys[i + 1:]:
            if k in k2:
                sys.exit(
                    f"[오류] 키 순서: '{k}'가 뒤에 등재된 긴 키 '{k2}'에 포함됨 "
                    f"— 긴 키('{k2}')를 먼저 등재하라"
                )
    return repl, set(watch)


def apply_to_srt(raw: str, repl: dict, watch: set = frozenset()):
    """SRT 텍스트 라인만 치환 → (새 SRT, {키: 적용 횟수}, 감시 치환 라인 목록).

    순번·타임코드 라인 불변. 감시 티어(watch) 키가 치환한 라인은
    (원문, 치환 후) 쌍으로 수집해 호출자가 전문 리포트하게 한다."""
    raw = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    time_idx = {i for i, ln in enumerate(lines) if _TIME_RE.search(ln)}
    seq_idx = {i - 1 for i in time_idx if i > 0 and lines[i - 1].strip().isdigit()}
    counts = {k: 0 for k in repl}
    watch_lines = []
    out = []
    for i, ln in enumerate(lines):
        if i in time_idx or i in seq_idx:
            out.append(ln)
            continue
        before = ln
        watched = False
        for k, v in repl.items():
            n = ln.count(k)
            if n:
                counts[k] += n
                ln = ln.replace(k, v)
                if k in watch:
                    watched = True
        if watched:
            watch_lines.append((before, ln))
        out.append(ln)
    return "\n".join(out), counts, watch_lines


def report(counts: dict) -> str:
    """적용 리포트 한 덩어리 — 적용 항목은 상세, 미출현 항목은 개수만."""
    hit = {k: n for k, n in counts.items() if n}
    miss = len(counts) - len(hit)
    lines = []
    if hit:
        lines.append(f"  적용 {len(hit)}개 항목(치환 {sum(hit.values())}회):")
        for k, n in hit.items():
            lines.append(f"    '{k}' → ({n}회)")
    lines.append(f"  미출현 {miss}개 항목 (이 영상에 해당 오인식 없음 — 정상)")
    return "\n".join(lines)


def main() -> None:
    try:  # 한글 콘솔 출력 보호(cp949 환경) — sys.exit 메시지는 stderr로 나가므로 둘 다
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="SRT 자막에 영구 교정 사전을 기계 적용")
    ap.add_argument("srt", type=pathlib.Path)
    ap.add_argument("--dict", type=pathlib.Path, default=DICT_DEFAULT,
                    dest="dict_path", help=f"교정사전 경로(기본 {DICT_DEFAULT})")
    ap.add_argument("--check", action="store_true",
                    help="검사만 — 사전 매치가 남아 있으면 exit 1")
    ap.add_argument("--no-backup", action="store_true",
                    help="제자리 재작성 시 .precorrect.srt 백업 생략")
    args = ap.parse_args()

    if not args.srt.is_file():
        sys.exit(f"[오류] SRT 없음: {args.srt}")
    if args.srt.suffix.lower() == ".json":
        sys.exit("[오류] JSON 입력 거부 — transcript.json(Whisper 원본)은 불변 규약, 치환은 SRT에만")

    repl, watch = load_dict(args.dict_path)
    raw = args.srt.read_text(encoding="utf-8-sig")
    new_raw, counts, watch_lines = apply_to_srt(raw, repl, watch)
    hit_total = sum(counts.values())

    if args.check:
        if hit_total:
            print(f"[실패] 교정 사전 매치 {hit_total}회 잔존:")
            print(report(counts))
            sys.exit(1)
        print(f"[통과] 교정 사전 매치 0 (사전 {len(repl)}항목)")
        return

    normalized = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    if new_raw == normalized:
        print(f"[변경 없음] 교정 사전 매치 0 (사전 {len(repl)}항목)")
        return

    if not args.no_backup:
        bpath = args.srt.with_suffix(".precorrect" + args.srt.suffix)
        shutil.copy2(args.srt, bpath)  # 치환 직전 원본을 바이트 그대로 보존
        print(f"  원본 백업: {bpath}")
    args.srt.write_text(new_raw, encoding="utf-8")
    print(f"[완료] {args.srt}")
    print(report(counts))
    if watch_lines:
        # 감시 티어 치환은 문서 경고가 아니라 출력 구조로 가시화한다 — 오탐이 조용히 지나갈 수 없다.
        print(f"  ⚠ 감시 티어 치환 {len(watch_lines)}개 라인 — 문맥이 맞는지 눈으로 확인하라 (교정사전 _규칙 참조):")
        for before, after in watch_lines:
            print(f"    - {before}")
            print(f"    + {after}")
    # 순서 계약 안내: 치환으로 16자 초과 컷이 생길 수 있다 — 분할(3b)이 뒤따라야 한다.
    # (누락해도 assemble_capcut.py가 임포트 직전 멱등 재강제하는 2차 안전망은 있음)
    print(f"  다음 단계: python scripts/split_captions.py \"{args.srt}\"  (16자 분할 — 치환으로 초과분이 생길 수 있음)")


if __name__ == "__main__":
    main()
