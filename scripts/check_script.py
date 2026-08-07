"""풀링(리드젠) 대본(01_대본/script.md)의 구조·사실 게이트.

왜 스크립트인가:
  대본 작성 자체는 발산형 창작(LLM 노드)이라 프롬프트가 담당한다.
  그러나 "고정 CTA가 안 빠졌는가 · 콘텐츠 정리 꼬리가 있는가 · 분량이 미드폼인가 ·
  가짜수치/미래단정이 없는가 · 외부 통계가 무출처로 나가지 않는가"는
  검증(수렴형)이라 결정론으로 다룬다. split_captions.py와 같은 fail-loud 철학.

역할 분담(중요):
  - FAIL(exit 2): 고정 CTA의 '구독 → 로스위협(2번째 문장, verbatim-lock) → 고정댓글'
    순서·인접 3문장 블록이 없을 때. 존재 여부가 아니라 순서·인접까지 요구해,
    무관 문맥에 흩어진 단어가 우연히 앵커를 채우는 우회를 막는다(codex CASE D류).
    정상 풀링 대본은 이 블록을 verbatim 보유해 PASS(오탐 0). 다듬기는 1·3문장 연결어만
    허용되고 문장 갭 한도(160/220자) 안이라 블록 매치가 유지된다. (블록 규칙 너머의
    '문구는 맞는데 진짜 CTA인지' 의미 판정은 SKILL.md Step 7의 LLM+사람 몫.)
  - WARN/INFO(exit 0): 콘텐츠 정리 꼬리·분량 밴드·금지표현·외부주장 후보·미해결 마커.
    이건 "게이트가 판정 못 하는" 부분이라 SKILL.md Step 7의 LLM + 사람이 최종 처리한다.
    (외부 vs 1인칭 분류, 자료조사 매칭은 LLM 몫 — 여기선 후보만 뽑는다.)

사용:
  python check_script.py <script.md>
  python check_script.py <script.md> --research <자료조사.md>
  python check_script.py <script.md> --min-chars 2000 --max-chars 3200
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# 미드폼 나레이션 순수 글자수 허용 밴드(분당 300~400자 · 5~9분 → ≈1750~3200).
# 문서상 권장 스위트스팟은 6~8분이지만, 게이트는 허용 범위(5~9분) 밖일 때만 경고한다.
MIN_CHARS = 1750
MAX_CHARS = 3200
CHARS_PER_MIN = 350  # 분 환산 기준(300~400 중앙)

# 고정 CTA = 순서·인접 3문장 블록: 구독(1문장) → 로스위협(2문장, verbatim-lock) → 고정댓글(3문장).
# 존재 여부가 아니라 '순서 + 문장 간 짧은 갭'까지 요구해, 무관 문맥에 흩어진 단어가 앵커를
# 우연히 채우는 얕은-매칭 우회를 막는다(codex CASE D류). 위치 무관이라 CTA가 꼬리 어디에 있어도
# 잡히고(허위 FAIL 방지), 갭 한도가 연결어 다듬기(1·3문장)는 흡수한다.
# 로스위협은 '작아'/'찾아오'로 좁혀 "채널 자체가 작동"·"다시 찾아뵙겠습니다" 오매치 배제.
_CTA_LOSS = r"(?:채널[^\n]{0,6}작아|찾아\s*오기\s*힘|다시\s*찾아오)"
CTA_BLOCK_RE = re.compile(r"구독[\s\S]{0,160}?" + _CTA_LOSS + r"[\s\S]{0,220}?고정\s*댓글")
CTA_LOSS_RE = re.compile(_CTA_LOSS)  # 진단 메시지 구분용(로스위협만 있는지)

# 영상 요약(설명란/챕터) 꼬리 제목 — editor Step 9가 append/replace하는 '## 영상 요약' 기준.
# 레거시 대본의 다양한 이름(콘텐츠 정리 등)도 인식. 'bare 요약/챕터'는 본문 헤더 오분리라 제외.
TAIL_HEAD_RE = re.compile(
    r"^\s*#{1,4}\s*.*(영상\s*요약|콘텐츠\s*정리|영상\s*설명|설명란|영상\s*소개|유튜브\s*설명)", re.M)
TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

# 미해결 자리표시자(초안엔 의도적으로 있을 수 있음 — 기획메모 검수란에 열거돼야 함)
MARKER_RE = re.compile(r"\[N\]|\(사용자\s*입력\s*필요\)|\[빈칸\]|\[출처\s*확인[^\]]*\]|\[[^\]]*입력[^\]]*\]")

# 금지/주의 표현(하드닝 규칙) — WARN. 실제 대본이 수사적으로 쓸 수 있어 fail-loud 아님.
BANNED = [
    (re.compile(r"곧\s*[^\n]{0,12}(사라|없어지|끝나|대체)"), "미래 단정(곧 ~사라진다)"),
    (re.compile(r"머지않아|조만간\s*[^\n]{0,12}(사라|대체|없어)"), "미래 단정"),
    (re.compile(r"100\s*%\s*[^\n]{0,8}(보장|성공|됩니다|환불)"), "과장/보장 단정"),
    (re.compile(r"한\s*방에\s*(다|전부|모든|끝)"), "UI/성능 과장 소지(시연 뒷받침 필요)"),
]

# 외부 통계/수치 후보 추출(외부 vs 1인칭 판정은 LLM Step 7) — INFO
CLAIM_RES = [
    re.compile(r"\d[\d,\.]*\s*(배|%|퍼센트|명|시간|년|개월|만\s*원|만원|억|조|위)"),
    re.compile(r"1\s*/\s*\d+"),
    re.compile(r"\d*\s*(천|만|억|조)\s*(원|명|시간)"),
]

# 키_001(판매형) 전용 비트 누출 감시 — WARN(풀링에 나오면 안 됨)
SALES_LEAK = [
    (re.compile(r"얼리버드|정식\s*가격|\d+\s*만\s*원\s*(할인|→)"), "가격/오퍼(키_001 전용)"),
    (re.compile(r"(정원|모집)\s*[^\n]{0,10}(명|마감)|이번\s*(회차|기)\s*[^\n]{0,6}명"), "희소성/정원(키_001 전용)"),
    (re.compile(r"1\s*:\s*1\s*(코칭\s*)?신청|신청\s*페이지|카카오톡\s*상담|결제"), "진단/결제 CTA(키_001 전용)"),
]


def read_text(path: pathlib.Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="cp949", errors="replace")  # 한글 Windows 비UTF-8 폴백
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def split_body_tail(text: str):
    """영상 요약 꼬리 앞 = 나레이션 본문, 뒤 = 설명란 꼬리.
    꼬리는 문서 끝쪽에 오므로 '마지막' 매치를 경계로 삼아 본문 헤더 오분리를 피한다."""
    matches = list(TAIL_HEAD_RE.finditer(text))
    if matches:
        m = matches[-1]
        return text[: m.start()], text[m.start():]
    return text, ""


def narration_chars(body: str) -> int:
    """나레이션 순수 글자수 추정: 제목/헤더 줄 제거, [자리표시자]·마크다운 기호 제거 후 비공백 수."""
    lines = [ln for ln in body.split("\n") if not ln.lstrip().startswith("#")]
    s = "\n".join(lines)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)   # HTML 주석
    s = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", s)     # 마크다운 이미지/링크(URL 포함)
    s = re.sub(r"\[[^\]]*\]", "", s)                # 남은 [빈칸]·[출처확인] 자리표시자는 발화 아님
    s = re.sub(r"[*_`>~|\-]", "", s)                # 마크다운 기호
    s = re.sub(r"\s", "", s)               # 공백 제거
    return len(s)


# 대본 파트 문법(2026-07-15): 문서 상단 '## 썸네일' 파트는 나레이션이 아니다 — 분량·CTA·표현
# 검사에서 제외한다. 정식 문법은 '## 썸네일' + '## 본문' 헤딩 쌍(editor·writer와 동일 규칙).
PART_THUMB_RE = re.compile(r"^\s*#{1,4}\s*썸네일[^\n]*$", re.M)
PART_BODY_RE = re.compile(r"^\s*#{1,4}\s*본문[^\n]*$", re.M)
ANY_HEADING_RE = re.compile(r"^\s*#{1,4}\s+\S", re.M)


def strip_thumbnail_part(text: str):
    """'## 썸네일' 파트 제거 → (나머지 텍스트, 경고 목록). '## 본문' 헤딩이 정식 경계."""
    m = PART_THUMB_RE.search(text)
    if not m:
        return text, []
    body_m = PART_BODY_RE.search(text, m.end())
    if body_m:
        return text[:m.start()] + text[body_m.end():], []
    nxt = ANY_HEADING_RE.search(text, m.end())
    if nxt and (nxt.start() - m.end()) < len(text) * 0.5:
        return (text[:m.start()] + text[nxt.start():],
                ["'썸네일' 파트에 '## 본문' 짝 헤딩이 없음 — 다음 헤딩까지를 파트로 간주(정식 문법: ## 썸네일 / ## 본문)"])
    return text, ["'썸네일' 헤딩이 있으나 경계('## 본문')가 없어 분리 불가 — 썸네일 파트가 분량·표현 검사에 섞일 수 있음"]


def find_lines(text: str, pattern: re.Pattern):
    """패턴에 걸리는 (줄번호, 줄내용) 목록."""
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        if pattern.search(ln):
            out.append((i, ln.strip()))
    return out


def check(script_path: pathlib.Path, research_path: pathlib.Path | None,
          min_chars: int, max_chars: int):
    text = read_text(script_path)
    text, part_warns = strip_thumbnail_part(text)   # '## 썸네일' 파트는 나레이션 아님
    body, tail = split_body_tail(text)

    fails, warns, infos = list(), list(part_warns), []

    # ── FAIL: 고정 CTA = '구독 → 로스위협 → 고정댓글' 순서·인접 3문장 블록 ──
    if not CTA_BLOCK_RE.search(body):
        if CTA_LOSS_RE.search(body):
            fails.append("고정 CTA 블록 미형성: 로스위협 문장은 있으나 '구독 → 로스위협 → 고정댓글' "
                         "순서·인접 3문장 구조가 아님 — POOLING_PRINCIPLES.md 고정 CTA 골격 확인")
        else:
            fails.append("고정 CTA 부재: '구독 → 채널이 작아서…다시 찾아오기 힘 → 고정 댓글' "
                         "3문장 블록이 없음 — POOLING_PRINCIPLES.md 고정 CTA 필수")

    # ── WARN: 콘텐츠 정리 꼬리 ──
    if not TAIL_HEAD_RE.search(text):
        warns.append("'## 영상 요약'(설명란/챕터) 꼬리가 없음 — POOLING_STRUCTURE.md ⑧")
    elif not TIMESTAMP_RE.search(tail):
        infos.append("콘텐츠 정리에 타임스탬프가 없음(초안이면 정상 — 녹음·STT 후 확정)")

    # ── WARN: 분량 밴드 ──
    n = narration_chars(body)
    est_min = n / CHARS_PER_MIN
    if n < min_chars or n > max_chars:
        warns.append(f"나레이션 분량 {n}자(≈{est_min:.1f}분)가 미드폼 밴드({min_chars}~{max_chars}자) 밖")
    else:
        infos.append(f"나레이션 분량 {n}자 ≈ {est_min:.1f}분 (밴드 내)")

    # ── WARN: 금지/주의 표현 ──
    for pat, label in BANNED:
        for ln_no, ln in find_lines(body, pat):
            warns.append(f"[{label}] L{ln_no}: {ln[:60]}")

    # ── WARN: 키_001 판매 비트 누출 ──
    for pat, label in SALES_LEAK:
        for ln_no, ln in find_lines(body, pat):
            warns.append(f"[배제 위반? {label}] L{ln_no}: {ln[:60]}")

    # ── INFO: 미해결 마커(기획메모에 열거돼야 함) ──
    markers = find_lines(text, MARKER_RE)
    if markers:
        infos.append(f"미해결 자리표시자 {len(markers)}개 — 기획메모 검수란에 열거됐는지 확인:")
        for ln_no, ln in markers:
            infos.append(f"    L{ln_no}: {ln[:70]}")

    # ── INFO: 외부 통계/수치 후보(외부 vs 1인칭 판정은 Step 7) ──
    claim_lines = {}
    for pat in CLAIM_RES:
        for ln_no, ln in find_lines(body, pat):
            claim_lines[ln_no] = ln
    if claim_lines:
        infos.append(f"수치/통계 후보 {len(claim_lines)}개 — 각각 외부(자료조사 매칭 필요) vs 1인칭(면제) 판정:")
        for ln_no in sorted(claim_lines):
            infos.append(f"    L{ln_no}: {claim_lines[ln_no][:70]}")

    # ── INFO: 자료조사 상태 ──
    if research_path and research_path.is_file():
        rtext = read_text(research_path)
        rows = [ln for ln in rtext.split("\n") if ln.count("|") >= 3 and "http" in ln]
        infos.append(f"자료조사.md 출처 행 ~{len(rows)}개 — 외부주장을 이와 대조(Step 7)")
    else:
        infos.append("자료조사.md 미제공 — 외부 통계가 있으면 [출처확인 필요] 태그 권장")

    return fails, warns, infos


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="풀링 대본 구조·사실 게이트")
    ap.add_argument("script", type=pathlib.Path, help="01_대본/script.md")
    ap.add_argument("--research", type=pathlib.Path, default=None, help="00_리서치/자료조사.md")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    args = ap.parse_args()

    if not args.script.is_file():
        sys.exit(f"[오류] 대본 없음: {args.script}")

    fails, warns, infos = check(args.script, args.research, args.min_chars, args.max_chars)

    print(f"=== 대본 게이트: {args.script} ===")
    if fails:
        print(f"\n[FAIL] {len(fails)}건 (반드시 해소):")
        for x in fails:
            print(f"  ✗ {x}")
    if warns:
        print(f"\n[WARN] {len(warns)}건 (Step 7 검토):")
        for x in warns:
            print(f"  ⚠ {x}")
    if infos:
        print("\n[INFO]")
        for x in infos:
            print(f"  · {x}")

    if fails:
        print(f"\n결과: FAIL ({len(fails)}건) — 해소 후 재검사")
        sys.exit(2)
    print(f"\n결과: PASS (경고 {len(warns)}건은 Step 7에서 처리)")


if __name__ == "__main__":
    main()
