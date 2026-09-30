# -*- coding: utf-8 -*-
"""긴 녹음·transcript에서 [S, E] 구간을 잘라 실험 재료 폴더를 만든다.

입력  <src>/02_음성/narration.m4a, <src>/03_자막/transcript.json (+ 있으면 <src>/03_자막/full.srt)
출력  <out>/02_음성/narration.m4a   (aac 192k, 48kHz, 0초 = 원본 S초)
      <out>/03_자막/transcript.json (원본과 같은 키 구조 유지 — 모르는 키도 그대로 둔다)
          - 구간과 겹치는 segment·word만, start/end에서 S를 빼고 [0, E-S]로 클램프
          - 구간에 걸친 segment는 text를 구간 안 단어(중점 기준)로 다시 만든다(단어가 없으면 버림)
          - timebase(문자열 키가 있을 때만) 끝에 발췌 정보를 덧붙인다, duration = E-S,
            최상위 text(문자열이면)는 구간 안 단어로 다시 만든다
      <out>/03_자막/full.srt        한 컷 16자 초과면 단어 경계로 균등 분할, 시간은 글자 수 비례 배분
      <out>/03_자막/beats.json      [{i,start,end,text}] (i는 1부터)

비트·SRT의 원천 (위에서부터 먼저 있는 것):
  ① transcript.segments            → segment 1개 = 비트 1개, SRT도 segments 기반
  ② <src>/03_자막/full.srt          → 구간으로 잘라 재기준한 SRT 컷. 비트는 인접 컷 사이 무음 < 0.45s 이고
                                      합친 길이 ≤ 4.5s 이면 한 비트로 병합
  ③ transcript.words               → 0.45s 이상 갭에서 끊어 비트(= SRT 원천)

--beats-only: 음성·transcript·full.srt는 건드리지 않고 <out>/03_자막/beats.json만 만든다.
  --start/--end 생략 시 0 ~ transcript.duration. --src와 --out을 같은 폴더로 줘도 안전.

사용:
  python segment.py --src "결과물/2026-07-02_..." --start 30 --end 90 --out "_lab/seg_30_90"
  python segment.py --src "_lab/A" --out "_lab/A" --beats-only
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MAX_CHARS = 16
MIN_LEN = 0.05
GAP = 0.45          # 비트 경계 무음(초)
MERGE_MAX = 4.5     # SRT 컷 병합 상한(초)


def die(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        die("[입력 오류] ffmpeg을 찾을 수 없다")


def clamp_item(it, S, E, min_len=MIN_LEN):
    s, e = float(it["start"]), float(it["end"])
    if e < S or s >= E or (e == S and e > s):
        return None
    ns, ne = max(s, S) - S, min(e, E) - S
    if ne - ns < min_len:
        return None
    out = dict(it)
    out["start"], out["end"] = round(ns, 3), round(ne, 3)
    return out


def norm(text):
    return " ".join(str(text).split())


def split_text(text, max_chars=MAX_CHARS):
    """단어 경계로 균등 분할. 각 조각 ≤ max_chars가 되도록 조각 수를 늘려 간다(단어 하나가 넘으면 그대로)."""
    words = text.split()
    if len(text) <= max_chars or len(words) <= 1:
        return [text]
    n = math.ceil(len(text) / max_chars)
    while n <= len(words):
        target = len(text) / n
        chunks, cur = [], []
        for w in words:
            cand = " ".join(cur + [w])
            if cur and len(cand) > target + 2 and n - len(chunks) - 1 > 0:
                chunks.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        if cur:
            chunks.append(" ".join(cur))
        if all(len(c) <= max_chars or len(c.split()) == 1 for c in chunks):
            return chunks
        n += 1
    return words


# ---------------------------------------------------------------- SRT 입출력
def srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_sec(v):
    hms, ms = v.strip().replace(".", ",").split(",")
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms) / 1000.0


def read_srt(path):
    content = Path(path).read_text(encoding="utf-8-sig").strip()
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        a, b = lines[1].split(" --> ", 1)
        cues.append({"start": srt_sec(a), "end": srt_sec(b), "text": norm(" ".join(lines[2:]))})
    return cues


def cues_to_srt(items):
    """[{start,end,text}] → (SRT 문자열, 컷 수). 16자 초과 컷은 분할·시간 비례 배분."""
    cues = []
    for it in items:
        text = norm(it["text"])
        if not text:
            continue
        s, e = it["start"], it["end"]
        parts = split_text(text)
        total = sum(len(p) for p in parts)
        cur = s
        for j, p in enumerate(parts):
            nxt = e if j == len(parts) - 1 else cur + (e - s) * len(p) / total
            cues.append((cur, nxt, p))
            cur = nxt
    lines = []
    for k, (s, e, p) in enumerate(cues, 1):
        lines += [str(k), f"{srt_time(s)} --> {srt_time(e)}", p, ""]
    return "\n".join(lines), len(cues)


# ---------------------------------------------------------------- 비트 원천
def merge_cues(cues, gap=GAP, max_len=MERGE_MAX):
    out = []
    for c in cues:
        if out and c["start"] - out[-1]["end"] < gap and c["end"] - out[-1]["start"] <= max_len:
            out[-1]["end"] = c["end"]
            out[-1]["text"] = norm(out[-1]["text"] + " " + c["text"])
        else:
            out.append(dict(c))
    return out


def words_to_groups(words, gap=GAP):
    out = []
    for w in words:
        if out and float(w["start"]) - out[-1]["end"] < gap:
            out[-1]["end"] = float(w["end"])
            out[-1]["text"] = norm(out[-1]["text"] + " " + str(w["word"]))
        else:
            out.append({"start": float(w["start"]), "end": float(w["end"]), "text": norm(w["word"])})
    return out


def rebuild_clipped(orig, c, mids, S, E):
    """구간 경계에 걸친 항목이면 text를 구간 안 단어로 다시 만든다. 단어가 없으면 None.
    mids = [(원본 기준 단어 중점 - S, 단어)] — 클램프 전 중점으로 판정해야 경계 단어가 새지 않는다."""
    if float(orig["start"]) >= S and float(orig["end"]) <= E:
        return c
    inside = [w for m, w in mids if c["start"] <= m <= c["end"]]
    if not inside:
        return None
    c["text"] = " ".join(str(x).strip() for x in inside)
    return c


def pick_source(segs, src_srt, words, mids, S, E):
    """→ (kind, srt_items, beat_items). 모든 시각은 이미 S 기준 재기준·클램프된 값."""
    if segs:
        return "segments", segs, segs
    if src_srt.exists():
        cues = []
        for orig in read_srt(src_srt):
            c = clamp_item(orig, S, E)
            c = rebuild_clipped(orig, c, mids, S, E) if c else None
            if c:
                cues.append(c)
        if cues:
            return "full.srt(병합)", cues, merge_cues(cues)
    if words:
        groups = words_to_groups(words)
        return "words(갭 분할)", groups, groups
    return "없음", [], []


def to_beats(items):
    return [{"i": i, "start": round(float(b["start"]), 3), "end": round(float(b["end"]), 3),
             "text": norm(b["text"])} for i, b in enumerate(items, 1)]


# ---------------------------------------------------------------- 메인
def main():
    ap = argparse.ArgumentParser(description="긴 녹음·transcript에서 구간을 잘라 실험 재료 폴더를 만든다")
    ap.add_argument("--src", required=True, help="작업 폴더(02_음성/narration.m4a, 03_자막/transcript.json)")
    ap.add_argument("--start", type=float, default=None, help="시작 초 S (--beats-only면 생략 시 0)")
    ap.add_argument("--end", type=float, default=None, help="끝 초 E (--beats-only면 생략 시 transcript.duration)")
    ap.add_argument("--out", required=True, help="출력 폴더 (--beats-only면 --src와 같아도 됨)")
    ap.add_argument("--beats-only", action="store_true",
                    help="음성·transcript·full.srt는 건드리지 않고 03_자막/beats.json만 만든다")
    args = ap.parse_args()

    src = Path(args.src)
    audio, tjson = src / "02_음성" / "narration.m4a", src / "03_자막" / "transcript.json"
    src_srt = src / "03_자막" / "full.srt"
    need = [tjson] if args.beats_only else [audio, tjson]
    for f in need:
        if not f.exists():
            die(f"[입력 오류] 파일이 없다: {f}")
    if not args.beats_only and (Path(args.out) / "02_음성" / "narration.m4a").resolve() == audio.resolve():
        die("[입력 오류] --src와 --out이 같으면 --beats-only로만 실행한다(원본 덮어쓰기 방지)")
    tr = json.loads(tjson.read_text(encoding="utf-8"))
    dur_src = float(tr.get("duration") or 0)

    if args.beats_only:
        S = 0.0 if args.start is None else args.start
        E = args.end if args.end is not None else (dur_src or 1e9)
    else:
        if args.start is None or args.end is None:
            die("[입력 오류] --start와 --end가 필요하다 (--beats-only가 아니면)")
        S, E = args.start, args.end
    if E <= S or S < 0:
        die(f"[입력 오류] 구간이 잘못됐다: {S}~{E}")
    if dur_src and S >= dur_src:
        die(f"[입력 오류] start {S}가 원본 길이 {dur_src} 이상")
    if dur_src and E > dur_src:
        if not args.beats_only:
            print(f"[경고] end {E} > 원본 길이 {dur_src} → {dur_src}로 자름")
        E = dur_src

    words = [w for w in (clamp_item(w, S, E, min_len=0.0) for w in (tr.get("words") or [])) if w]
    mids = [((float(w["start"]) + float(w["end"])) / 2 - S, w["word"]) for w in (tr.get("words") or [])]
    segs, clipped = [], 0
    raw_segs = tr.get("segments") if isinstance(tr.get("segments"), list) else []
    for seg in raw_segs:
        c = clamp_item(seg, S, E)
        if not c:
            continue
        straddle = float(seg["start"]) < S or float(seg["end"]) > E
        c = rebuild_clipped(seg, c, mids, S, E)
        if not c:
            continue
        clipped += straddle
        segs.append(c)

    kind, srt_items, beat_items = pick_source(segs, src_srt, words, mids, S, E)
    beats = to_beats(beat_items)
    out = Path(args.out)
    (out / "03_자막").mkdir(parents=True, exist_ok=True)
    (out / "03_자막" / "beats.json").write_text(json.dumps(beats, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.beats_only:
        print(f"[완료·beats-only] {out / '03_자막' / 'beats.json'}  구간 {S:.3f}~{E:.3f}s · 원천 {kind} · "
              f"beats {len(beats)}개 (음성·transcript·full.srt 미변경)")
        return 0 if beats else 1

    # 오디오 — 입력 앞 -ss(디코드 후 정확 트림) + 재인코딩
    (out / "02_음성").mkdir(parents=True, exist_ok=True)
    a_out = out / "02_음성" / "narration.m4a"
    p = subprocess.run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{S:.3f}",
                        "-i", str(audio), "-t", f"{E - S:.3f}", "-vn", "-c:a", "aac", "-b:a", "192k",
                        "-ar", "48000", "-movflags", "+faststart", str(a_out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        die(f"[실패] ffmpeg 오디오 자르기 rc={p.returncode}: {p.stderr[-600:]}")

    new = dict(tr)
    note = f"segment.py 발췌: 원본 {S:.3f}~{E:.3f}s (0초 = 원본 {S:.3f}s)"
    if isinstance(tr.get("timebase"), str):          # 없는 키는 새로 만들지 않는다(키 구조 유지)
        new["timebase"] = f"{tr['timebase']} | {note}" if tr["timebase"] else note
    new["duration"] = round(E - S, 3)
    if "segments" in tr:
        new["segments"] = segs
    new["words"] = words
    if isinstance(tr.get("text"), str):
        new["text"] = " ".join(str(w["word"]).strip() for w in words)
    (out / "03_자막" / "transcript.json").write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")

    srt, ncue = cues_to_srt(srt_items)
    (out / "03_자막" / "full.srt").write_text(srt, encoding="utf-8")

    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(a_out)],
                        capture_output=True, text=True) if shutil.which("ffprobe") else None
    adur = pr.stdout.strip() if pr and pr.returncode == 0 else "?"
    print(f"[완료] {out}")
    print(f"  오디오 {a_out.name}: {adur}s (요청 {E - S:.3f}s)")
    print(f"  원천 {kind} · segments {len(segs)}개(경계 재구성 {clipped}) · words {len(words)}개 · "
          f"SRT 컷 {ncue}개 · beats {len(beats)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
