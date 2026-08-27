# -*- coding: utf-8 -*-
"""STORYBOARD.md 기계 게이트 (결정론).

설계 정본: docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md §3-1 / §3-4.

입력
  - 결과물/<작업>/STORYBOARD.md          (또는 01_대본/STORYBOARD.md)
  - 결과물/<작업>/03_자막/transcript.json (Whisper 단어 타임스탬프)

검사 (A~F)
  A  모든 프레임에 지속 모션 루트(route)가 5종 중 하나로 배정됐는가        [FAIL]
  B  Scene 창들이 프레임 구간(오디오 필드 시작~끝)을 빈틈·겹침 없이 덮는가 [FAIL] (허용 오차 0.15s)
  C  프론트로딩 금지 — 마지막 리빌 Scene 시작이 프레임 길이의 25% 이전     [FAIL] (프레임 길이 > 6s일 때만)
  D  Scene 줄의 어절 큐("…" 인용)가 transcript 단어 실측 시각과 일치       [FAIL] (Scene 창 ±0.3s)
  E  vec.axis/dir 값 유효성                                               [FAIL]
     연속 프레임 같은 축 역방향(x:-1 → x:+1)                              [WARN]
  F  한 편의 전환 유형이 4종 이상(전환 예산 2~3종)                        [WARN]

사용
  python scripts/check_storyboard.py "결과물/2026-08-06_풀링013_..."
  python scripts/check_storyboard.py <STORYBOARD.md> --transcript <transcript.json>
  python scripts/check_storyboard.py <작업폴더> --warn-only      # 위반이 있어도 exit 0
  python scripts/check_storyboard.py <작업폴더> --json           # 기계 판독용 JSON

종료 코드: 0 = 통과(또는 --warn-only), 1 = FAIL 위반 존재, 2 = 입력 오류
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROUTES = {
    "staged-reveals",
    "camera-with-intent",
    "sequenced-ui-life",
    "animated-sequences",
    "carrier-led",
}
COVER_TOL = 0.15      # Scene 창 커버리지 허용 오차(초)
CUE_TOL = 0.30        # 어절 큐 허용 오차(초)
FRONTLOAD_MIN_LEN = 6.0
FRONTLOAD_FRACTION = 0.25
TRANSITION_BUDGET = 4  # 이 수 이상이면 경고

# Scene 텍스트가 "리빌"이 아니라 홀드/정지 구간임을 알리는 표식
HOLD_MARKERS = ("정지 홀드", "홀드", "정지 쉼표", "쉼표", "hold", "pause", "정지 유지")
REVEAL_HINT = ("등장", "리빌", "reveal", "드로우온", "draw-on", "나타", "스윕",
               "카운트", "하이라이트", "펼침", "출현", "표시", "진입", "점화")

FRAME_RE = re.compile(r"^##\s+Frame\s+(\d+)\s*(?:[—\-–:]\s*(.*))?$")
BULLET_RE = re.compile(r"^[-*]\s*([A-Za-z_가-힣]+)\s*:\s*(.+)$")
SCENE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?Scene\s+(\d+)\s*[\(\[]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:s|초)?\s*[~\-–—]\s*(\d+(?:\.\d+)?)\s*(?:s|초)?\s*"
    r"[\)\]]\s*:\s*(.*)$",
    re.IGNORECASE,
)
VEC_RE = re.compile(r"axis\s*:\s*([A-Za-z]+)\s*,\s*dir\s*:\s*([+-]?\d+)")
QUOTE_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{1,60})[\"“”'‘’]")
CUT_RE = re.compile(r"slide--cut|컷\s*더\s*커브|cut-the-curve", re.IGNORECASE)


# --------------------------------------------------------------------------- 파서
def parse_time(token: str):
    """`01:20.3` / `80.33` / `1:02:03.4` → 초. 실패 시 None."""
    token = token.strip()
    if not token:
        return None
    parts = token.split(":")
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    sec = 0.0
    for v in vals:
        sec = sec * 60 + v
    return sec


def die(msg: str):
    """입력 오류 종료 — 게이트 위반(1)과 구분되는 exit 2."""
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def parse_audio_range(value: str):
    m = re.match(r"\s*([\d:.]+)\s*[~\-–—]\s*([\d:.]+)", value)
    if not m:
        return None, None
    return parse_time(m.group(1)), parse_time(m.group(2))


def parse_storyboard(path: Path):
    """STORYBOARD.md → 프레임 리스트. 각 프레임 = dict(no,title,fields,scenes,line)."""
    frames = []
    cur = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        m = FRAME_RE.match(line.strip())
        if m:
            cur = {
                "no": int(m.group(1)),
                "title": (m.group(2) or "").strip(),
                "fields": {},
                "scenes": [],
                "line": lineno,
                "raw": [],
            }
            frames.append(cur)
            continue
        if cur is None:
            continue
        cur["raw"].append(line)
        ms = SCENE_RE.match(line)
        if ms:
            cur["scenes"].append({
                "n": int(ms.group(1)),
                "start": float(ms.group(2)),
                "end": float(ms.group(3)),
                "text": ms.group(4).strip(),
                "line": lineno,
            })
            continue
        mb = BULLET_RE.match(line.strip())
        if mb:
            key = mb.group(1).strip().lower()
            val = mb.group(2).split("#")[0].strip() if key != "persuasion" else mb.group(2).strip()
            cur["fields"][key] = val.strip()
    return frames


# --------------------------------------------------------------------------- transcript
def norm(text: str) -> str:
    """어절 대조용 정규화 — 공백·구두점 제거, NFC 통일."""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def load_words(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    words = data.get("words") or []
    out = []
    for w in words:
        token = norm(str(w.get("word", "")))
        if not token:
            continue
        out.append({"n": token, "start": float(w["start"]), "end": float(w["end"])})
    return out


def build_index(words):
    """정규화 문자열 + 각 문자 → 단어 인덱스 매핑."""
    buf = []
    owner = []
    for i, w in enumerate(words):
        buf.append(w["n"])
        owner.extend([i] * len(w["n"]))
    return "".join(buf), owner


def find_cue_times(cue: str, joined: str, owner, words):
    """어절 큐가 등장하는 모든 지점의 시작 시각 목록."""
    key = norm(cue)
    if len(key) < 2:
        return None  # 너무 짧으면 대조 생략
    hits = []
    idx = joined.find(key)
    while idx != -1:
        hits.append(words[owner[idx]]["start"])
        idx = joined.find(key, idx + 1)
    return hits


# --------------------------------------------------------------------------- 검사
class Report:
    def __init__(self):
        self.items = []

    def add(self, level, code, frame, msg):
        self.items.append({"level": level, "check": code, "frame": frame, "message": msg})

    def fails(self):
        return [i for i in self.items if i["level"] == "FAIL"]

    def warns(self):
        return [i for i in self.items if i["level"] == "WARN"]


def is_reveal(text: str) -> bool:
    low = text.lower()
    if any(h in low for h in HOLD_MARKERS) and not any(r in low for r in REVEAL_HINT):
        return False
    return True


def check(frames, words, rep: Report):
    joined, owner = build_index(words) if words else ("", [])
    prev_vec = None
    transitions = set()

    if not frames:
        rep.add("FAIL", "PARSE", "-", "프레임 블록(`## Frame NN — 제목`)을 하나도 찾지 못했다")
        return

    for f in frames:
        fid = f"Frame {f['no']:02d}"
        fields = f["fields"]

        # A. route
        route = fields.get("route", "").split()[0] if fields.get("route") else ""
        if route not in ROUTES:
            rep.add("FAIL", "A", fid,
                    f"route 누락/무효: {fields.get('route', '(없음)')!r} — 허용 {sorted(ROUTES)}")

        # 오디오 구간
        astart, aend = parse_audio_range(fields.get("오디오", "") or fields.get("audio", ""))
        dur = None
        if astart is None or aend is None:
            rep.add("FAIL", "B", fid, "오디오 구간(`- 오디오: mm:ss.s~mm:ss.s`)을 읽지 못했다")
        else:
            dur = aend - astart
            if dur <= 0:
                rep.add("FAIL", "B", fid, f"오디오 구간 길이가 0 이하다 ({astart}~{aend})")
                dur = None

        scenes = sorted(f["scenes"], key=lambda s: s["start"])

        # B. 커버리지
        if not scenes:
            rep.add("FAIL", "B", fid, "Scene 줄이 없다 (샷 시퀀스 미기록)")
        elif dur:
            if abs(scenes[0]["start"] - 0.0) > COVER_TOL:
                rep.add("FAIL", "B", fid,
                        f"첫 Scene이 0.0s에서 시작하지 않는다 (start={scenes[0]['start']:.2f}s)")
            if abs(scenes[-1]["end"] - dur) > COVER_TOL:
                rep.add("FAIL", "B", fid,
                        f"마지막 Scene 끝({scenes[-1]['end']:.2f}s)이 프레임 길이({dur:.2f}s)와 다르다")
            for a, b in zip(scenes, scenes[1:]):
                gap = b["start"] - a["end"]
                if gap > COVER_TOL:
                    rep.add("FAIL", "B", fid,
                            f"Scene {a['n']}→{b['n']} 사이 빈틈 {gap:.2f}s")
                elif gap < -COVER_TOL:
                    rep.add("FAIL", "B", fid,
                            f"Scene {a['n']}↔{b['n']} 겹침 {-gap:.2f}s")
            for s in scenes:
                if s["end"] - s["start"] <= 0:
                    rep.add("FAIL", "B", fid, f"Scene {s['n']} 창 길이가 0 이하다")
                if s["end"] > dur + COVER_TOL:
                    rep.add("FAIL", "B", fid,
                            f"Scene {s['n']} 끝({s['end']:.2f}s)이 프레임 길이({dur:.2f}s)를 넘는다")

        # C. 프론트로딩
        if dur and scenes and dur > FRONTLOAD_MIN_LEN:
            reveals = [s for s in scenes if is_reveal(s["text"])]
            if reveals:
                last = max(r["start"] for r in reveals)
                limit = dur * FRONTLOAD_FRACTION
                if last < limit:
                    rep.add("FAIL", "C", fid,
                            f"프론트로딩 — 마지막 리빌 Scene 시작 {last:.2f}s < "
                            f"{FRONTLOAD_FRACTION:.0%} 지점 {limit:.2f}s (프레임 {dur:.2f}s). "
                            "후반 50%에도 리빌을 배치할 것")
            else:
                rep.add("WARN", "C", fid, "리빌로 판정된 Scene이 없다 (전 구간 홀드?)")

        # D. 어절 큐 대조
        if words and astart is not None:
            for s in scenes:
                for cue in QUOTE_RE.findall(s["text"]):
                    hits = find_cue_times(cue, joined, owner, words)
                    if hits is None:
                        continue
                    if not hits:
                        rep.add("FAIL", "D", fid,
                                f"Scene {s['n']} 어절 큐 {cue!r}를 transcript에서 찾지 못했다 "
                                "(대본 표기와 실제 발화가 다르거나 추정 시각)")
                        continue
                    lo = astart + s["start"] - CUE_TOL
                    hi = astart + s["end"] + CUE_TOL
                    if not any(lo <= t <= hi for t in hits):
                        near = min(hits, key=lambda t: min(abs(t - lo), abs(t - hi)))
                        rep.add("FAIL", "D", fid,
                                f"Scene {s['n']} 어절 큐 {cue!r} 실측 {near:.2f}s가 "
                                f"창 {astart + s['start']:.2f}~{astart + s['end']:.2f}s 밖이다")

        # E. vec
        vec_raw = fields.get("vec", "")
        mv = VEC_RE.search(vec_raw)
        if not mv:
            rep.add("FAIL", "E", fid, f"vec 파싱 실패: {vec_raw!r} — `{{axis: x, dir: -1}}` 형식")
        else:
            axis = mv.group(1).lower()
            try:
                direction = int(mv.group(2))
            except ValueError:
                direction = 0
            if axis not in ("x", "y", "z") or direction not in (-1, 1):
                rep.add("FAIL", "E", fid,
                        f"vec 값 무효: axis={axis} dir={mv.group(2)} (axis∈x/y/z, dir∈-1/+1)")
            else:
                if prev_vec and prev_vec[0] == axis and prev_vec[1] == -direction:
                    rep.add("WARN", "E", fid,
                            f"연속 프레임 역방향 전환 ({axis}:{prev_vec[1]:+d} → {axis}:{direction:+d}) "
                            "— 방향 전환에는 보이는 원인이 필요하다")
                prev_vec = (axis, direction)
                cut = bool(CUT_RE.search("\n".join(f["raw"])))
                transitions.add(f"{'cut' if cut else 'xfade'}:{axis}{direction:+d}")

    # F. 전환 예산
    if len(transitions) >= TRANSITION_BUDGET:
        rep.add("WARN", "F", "-",
                f"전환 유형 {len(transitions)}종 — 한 편 예산은 2~3종 "
                f"({', '.join(sorted(transitions))})")


# --------------------------------------------------------------------------- 입력 해석
def resolve_inputs(target: Path, transcript_arg):
    if target.is_dir():
        cands = [target / "STORYBOARD.md", target / "01_대본" / "STORYBOARD.md"]
        sb = next((c for c in cands if c.exists()), None)
        if sb is None:
            die(f"[입력 오류] STORYBOARD.md를 찾지 못했다: {', '.join(str(c) for c in cands)}")
        root = target
    else:
        sb = target
        if not sb.exists():
            die(f"[입력 오류] 파일이 없다: {sb}")
        root = sb.parent if sb.parent.name != "01_대본" else sb.parent.parent
    tr = Path(transcript_arg) if transcript_arg else root / "03_자막" / "transcript.json"
    return sb, tr


def main():
    ap = argparse.ArgumentParser(description="STORYBOARD.md 기계 게이트 (결정론)")
    ap.add_argument("target", help="작업 폴더 또는 STORYBOARD.md 경로")
    ap.add_argument("--transcript", help="transcript.json 경로 (기본: <작업>/03_자막/transcript.json)")
    ap.add_argument("--warn-only", action="store_true", help="위반이 있어도 exit 0")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = ap.parse_args()

    sb, tr = resolve_inputs(Path(args.target), args.transcript)
    frames = parse_storyboard(sb)
    if tr.exists():
        words = load_words(tr)
    else:
        words = []

    rep = Report()
    if not words:
        rep.add("WARN", "D", "-", f"transcript.json이 없어 어절 큐 대조를 건너뛴다 ({tr})")
    check(frames, words, rep)

    if args.json:
        print(json.dumps({
            "storyboard": str(sb),
            "transcript": str(tr) if words else None,
            "frames": len(frames),
            "fail": len(rep.fails()),
            "warn": len(rep.warns()),
            "items": rep.items,
        }, ensure_ascii=False, indent=1))
    else:
        print(f"STORYBOARD: {sb}")
        print(f"transcript: {tr if words else '(없음)'}")
        print(f"프레임 {len(frames)}개 / FAIL {len(rep.fails())} · WARN {len(rep.warns())}")
        print("-" * 72)
        for it in rep.items:
            print(f"[{it['level']}][{it['check']}] {it['frame']}: {it['message']}")
        if not rep.items:
            print("위반 없음 — 통과")

    if rep.fails() and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
