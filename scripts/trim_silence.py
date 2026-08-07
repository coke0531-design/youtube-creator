"""녹음(m4a)의 긴 무음(기본 ≥1.0s)을 결정론적으로 압축한다 — 무음 컷 (youtube-editor Step 1.5).

왜 스크립트인가:
  "무음 ≥1.0s를 찾아 양끝 0.3s만 남기고 잘라라"는 측정 기반의 기계적 규칙이다.
  AI 귀대중이 아니라 ffmpeg silencedetect 실측으로 판정해야 재현 가능하고,
  잘못 잘리면 하류 전체(STT→자막→슬라이드→캡처)가 오염되므로 가드도 코드가 강제한다.
  반드시 Whisper 전사(Step 2) **이전**에 실행한다 — 트림본을 전사하면 자막·슬라이드·
  캡처가 전부 트림본 타임베이스에서 파생되어 동기화 후처리가 필요 없다.
  (기성 SRT/영상과 함께 쓰는 오디오에 돌리면 안 된다 — desync.)

무엇을 하나:
  1. ffmpeg silencedetect(에너지 기준)로 무음 ≥ --min-gap 구간을 검출한다.
  2. 각 무음 [s,e]에서 가운데 [s+pad, e-pad]만 제거한다(양끝 0.3s 보존 — 숨 쉴 틈).
     파일 리딩 무음은 꼬리 pad만, 트레일링 무음은 머리 pad만 남긴다
     (다중 파일 concat 경계에서 0.3+0.3=0.6s — 내부 압축 갭과 동일).
  3. atrim+concat 필터로 keep 세그먼트를 이어붙인다(경계 5ms 페이드 — 클릭 방지).
     필터는 -filter_complex_script 파일로 전달(Windows 커맨드라인 길이 한계 회피).
  4. 비파괴: 원본은 그대로 두고 <이름>.trim.m4a 생성 + silence_cut_plan.json(컷 플랜·
     src↔dst 매핑·통계) 저장. 컷 0건이면 스트림 복사(-c copy, 무손실)로 균일 출력.
  5. fail-loud: 삭감률 상한 초과·출력 길이 불일치·전체 무음·파싱 실패는 예외로 중단.

알려진 한계(설계 트레이드오프):
  - 숨소리가 --noise 문턱을 넘으면 무음 런이 쪼개져 컷이 누락된다(언더컷 방향 —
    말이 잘리는 방향이 아님). STT 후 `--verify transcript.json`으로 남은 큰 갭을
    리포트해 다음 영상의 --noise 캘리브레이션 근거로 쓴다. 문턱 선택은 --analyze.
  - 강조용 긴 뜸도 일괄 0.6s로 압축된다 — 컷 리포트의 타임스탬프로 위치를 확인하고
    필요하면 CapCut 검수에서 늘린다(원본 보존이라 복원 가능).

사용:
  python trim_silence.py <a.m4a> [b.m4a ...]        # 파일별 트림 → <이름>.trim.m4a
  python trim_silence.py <a.m4a> --analyze          # 컷 없이 문턱 스윕 리포트(캘리브레이션)
  python trim_silence.py --verify <transcript.json> # STT 후 언더컷 검증(report-only)
  옵션: --min-gap 1.0  --pad 0.3  --noise -35  --max-cut-pct 20  --force  --plan-out <path>
"""
import argparse
import json
import os
import re
import subprocess
import sys

import imageio_ffmpeg

# 한국어 Windows: 파이프/콘솔이 cp949면 →·≈ 등 출력에서 UnicodeEncodeError로 죽는다.
# 이 스크립트는 도구(Claude Code)가 UTF-8 파이프로 실행하는 게 1차 경로 — UTF-8로 고정.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FF = imageio_ffmpeg.get_ffmpeg_exe()

MIN_GAP_DEFAULT = 1.0      # 무음 판정 최소 길이(초)
PAD_DEFAULT = 0.3          # 무음 구간 양끝 보존(초)
NOISE_DEFAULT = -35.0      # silencedetect 문턱(dB) — 나레이션 실측 -17.6~-15.8 LUFS 대비 ~18dB 마진
MAX_CUT_PCT_DEFAULT = 20.0 # 파일당 삭감률 상한(%) — 초과는 문턱 오작동 신호
FADE_SEC = 0.005           # 컷 경계 페이드(클릭 방지)
EDGE_EPS = 0.05            # 리딩/트레일링 판정 여유(초)
DUR_TOL = 0.1              # 출력 길이 검증 허용 오차(초)
VERIFY_GAP_DEFAULT = 0.95  # --verify에서 언더컷 의심 갭(초)
ANALYZE_THRESHOLDS = (-30.0, -35.0, -40.0, -45.0)

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
_EVENT_RE = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


def _run_ff(args):
    """ffmpeg 실행 → stderr 반환 (한국어 Windows cp949 함정 — encoding 명시)."""
    p = subprocess.run([FF, "-hide_banner"] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stderr


def probe_duration(path: str) -> float:
    """디코드 정확 길이(초) — ffmpeg -f null 디코드의 마지막 time= 파싱(전사 스크립트들과 동일 방식)."""
    rc, stderr = _run_ff(["-i", path, "-f", "null", "-"])
    times = _TIME_RE.findall(stderr)
    if rc != 0 or not times:
        raise RuntimeError(f"길이 측정 실패: {path}\n{stderr[-800:]}")
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def detect_silences(path: str, noise_db: float, min_dur: float):
    """silencedetect 1패스로 (무음 구간 목록, 파일 길이)를 얻는다."""
    rc, stderr = _run_ff(["-i", path,
                          "-af", f"silencedetect=n={noise_db}dB:d={min_dur}",
                          "-f", "null", "-"])
    times = _TIME_RE.findall(stderr)
    if rc != 0 or not times:
        raise RuntimeError(f"silencedetect 실패: {path}\n{stderr[-800:]}")
    h, m, s = times[-1]
    duration = int(h) * 3600 + int(m) * 60 + float(s)

    silences, start = [], None
    for kind, val in _EVENT_RE.findall(stderr):
        t = max(0.0, float(val))
        if kind == "start":
            start = t
        elif start is not None:
            silences.append((start, min(t, duration)))
            start = None
    if start is not None:                       # EOF까지 무음이면 end 이벤트가 없다
        silences.append((start, duration))
    for (s0, e0), (s1, _) in zip(silences, silences[1:]):
        if s1 < e0:
            raise RuntimeError(f"silencedetect 구간이 비단조: {path} ({e0:.2f} > {s1:.2f})")
    return silences, duration


def build_cuts(silences, duration: float, pad: float):
    """무음 목록 → 제거 구간 목록 [{src_start, src_end, kind}] (pad 보존 규칙 적용)."""
    cuts = []
    for s, e in silences:
        leading = s <= EDGE_EPS
        trailing = e >= duration - EDGE_EPS
        cs = 0.0 if leading else s + pad
        ce = duration if trailing else e - pad
        if ce - cs <= 0.01:
            continue
        kind = "leading" if leading else ("trailing" if trailing else "internal")
        if leading and trailing:
            raise RuntimeError("파일 전체가 무음으로 판정됨 — 입력/문턱(--noise) 확인 필요")
        cuts.append({"src_start": round(cs, 3), "src_end": round(ce, 3),
                     "removed": round(ce - cs, 3), "kind": kind})
    return cuts


def build_keeps(cuts, duration: float):
    """제거 구간의 여집합 = keep 세그먼트 + src→dst 매핑."""
    keeps, cursor, dst = [], 0.0, 0.0
    for c in cuts:
        if c["src_start"] - cursor > 0.001:
            keeps.append({"src_start": round(cursor, 3), "src_end": c["src_start"],
                          "dst_start": round(dst, 3)})
            dst += c["src_start"] - cursor
        cursor = c["src_end"]
    if duration - cursor > 0.001:
        keeps.append({"src_start": round(cursor, 3), "src_end": round(duration, 3),
                      "dst_start": round(dst, 3)})
    if not keeps:
        raise RuntimeError("keep 세그먼트가 0개 — 파일 전체가 잘린다 (중단)")
    return keeps


def apply_cuts(path: str, keeps, out_path: str):
    """keep 세그먼트를 atrim+concat으로 이어붙여 재인코딩 1회(AAC 192k)."""
    n = len(keeps)
    lines, labels = [], []
    for i, k in enumerate(keeps):
        seg = k["src_end"] - k["src_start"]
        chain = [f"atrim=start={k['src_start']:.6f}:end={k['src_end']:.6f}",
                 "asetpts=PTS-STARTPTS"]
        if seg > 2 * FADE_SEC:                 # 초단편 세그먼트는 페이드 중첩 방지 위해 생략
            if i > 0:
                chain.append(f"afade=t=in:st=0:d={FADE_SEC}")
            if i < n - 1:
                chain.append(f"afade=t=out:st={max(seg - FADE_SEC, 0):.6f}:d={FADE_SEC}")
        lines.append(f"[0:a]{','.join(chain)}[s{i}];")
        labels.append(f"[s{i}]")
    lines.append(f"{''.join(labels)}concat=n={n}:v=0:a=1[out]")

    script_path = out_path + ".filter.txt"       # 8191자 커맨드라인 한계 회피
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        rc, stderr = _run_ff(["-y", "-i", path, "-filter_complex_script", script_path,
                              "-map", "[out]", "-c:a", "aac", "-b:a", "192k", out_path])
        if rc != 0:
            raise RuntimeError(f"트림 인코딩 실패: {path}\n{stderr[-800:]}")
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def copy_passthrough(path: str, out_path: str):
    """컷 0건 — 스트림 복사(무손실)로 .trim.m4a를 만들어 출력을 균일화."""
    rc, stderr = _run_ff(["-y", "-i", path, "-c", "copy", out_path])
    if rc != 0:
        raise RuntimeError(f"스트림 복사 실패: {path}\n{stderr[-800:]}")


def trim_file(path: str, args):
    """파일 1개 트림 → 플랜 dict 반환."""
    name = os.path.basename(path)
    if ".trim." in name:
        print(f"⚠️  {name}: 이미 트림본으로 보임 — 재트림은 no-op에 수렴하지만 원본에 돌리는 게 정석")
    silences, duration = detect_silences(path, args.noise, args.min_gap)
    cuts = build_cuts(silences, duration, args.pad)
    keeps = build_keeps(cuts, duration) if cuts else [
        {"src_start": 0.0, "src_end": round(duration, 3), "dst_start": 0.0}]
    removed = sum(c["removed"] for c in cuts)
    removed_pct = removed / duration * 100 if duration else 0.0

    if removed_pct > args.max_cut_pct and not args.force:
        raise RuntimeError(
            f"{name}: 삭감률 {removed_pct:.1f}% > 상한 {args.max_cut_pct}% — 문턱(--noise) "
            f"오작동 의심. --analyze로 확인 후 재시도하거나 --force로 강행")

    root, _ = os.path.splitext(path)
    out_path = root + ".trim.m4a"
    if cuts:
        apply_cuts(path, keeps, out_path)
    else:
        copy_passthrough(path, out_path)

    out_dur = probe_duration(out_path)
    expected = duration - removed
    if abs(out_dur - expected) > DUR_TOL:
        raise RuntimeError(
            f"{name}: 출력 길이 검증 실패 — 기대 {expected:.3f}s vs 실측 {out_dur:.3f}s "
            f"(오차 허용 {DUR_TOL}s)")

    # 리포트
    print(f"\n── {name}  ({duration:.2f}s → {out_dur:.2f}s, -{removed:.2f}s / {removed_pct:.1f}%)")
    if not cuts:
        print("   컷 0건 — 스트림 복사(무손실)")
    for i, c in enumerate(cuts, 1):
        tag = {"leading": " [리딩]", "trailing": " [트레일링]"}.get(c["kind"], "")
        print(f"   컷 {i:2d}: {c['src_start']:8.2f}s ~ {c['src_end']:8.2f}s  (-{c['removed']:.2f}s){tag}")

    return {
        "src": name, "out": os.path.basename(out_path),
        "src_duration": round(duration, 3), "out_duration": round(out_dur, 3),
        "silences": [[round(s, 3), round(e, 3)] for s, e in silences],
        "cuts": cuts, "keep_map": keeps,
        "stats": {"n_cuts": len(cuts), "removed_sec": round(removed, 3),
                  "removed_pct": round(removed_pct, 2),
                  "longest_cut": round(max((c["removed"] for c in cuts), default=0.0), 3)},
    }


def analyze_file(path: str, args):
    """문턱 스윕 — 컷 없이 문턱별 예상 수율만 리포트(캘리브레이션용)."""
    name = os.path.basename(path)
    print(f"\n── analyze: {name}  (min-gap {args.min_gap}s, pad {args.pad}s)")
    print("   문턱(dB) | 컷 후보 | 예상 삭감(s) | 최장 무음(s) | 아깝게 놓침(0.5~min-gap)")
    for db in ANALYZE_THRESHOLDS:
        silences, duration = detect_silences(path, db, 0.5)
        candidates = [(s, e) for s, e in silences if e - s >= args.min_gap]
        near_miss = sum(1 for s, e in silences if 0.5 <= e - s < args.min_gap)
        try:
            yield_sec = sum(c["removed"] for c in build_cuts(candidates, duration, args.pad))
        except RuntimeError:
            print(f"   {db:8.0f} | 파일 전체가 무음 판정 — 문턱 과공격(부적합)")
            continue
        longest = max((e - s for s, e in silences), default=0.0)
        print(f"   {db:8.0f} | {len(candidates):7d} | {yield_sec:12.2f} | {longest:12.2f} | {near_miss}")
    print("   → 문턱을 올릴수록(-30 방향) 숨소리까지 무음으로 포함(수율↑), 내릴수록(-45) 보수적.")


def verify_transcript(transcript_path: str, gap_threshold: float):
    """STT 후 언더컷 검증(report-only) — 트림이 정상이면 단어 갭은 ≈0.6s 이하여야 한다."""
    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words") or []
    if not words:
        raise RuntimeError(f"transcript에 words가 없음: {transcript_path}")
    found = []
    for w1, w2 in zip(words, words[1:]):
        gap = w2["start"] - w1["end"]
        if gap >= gap_threshold:
            found.append((w1["end"], w2["start"], gap, w1["word"], w2["word"]))
    print(f"── verify: {os.path.basename(transcript_path)} — 단어 갭 ≥{gap_threshold}s: {len(found)}건")
    for t1, t2, gap, a, b in found:
        print(f"   {t1:8.2f}s ~ {t2:8.2f}s  ({gap:.2f}s)  …{a} | {b}…")
    if found:
        print("   → 언더컷 의심(숨소리가 문턱을 넘어 무음 런이 쪼개졌을 가능성).")
        print("     다음 영상에서 --analyze로 --noise를 -30 방향으로 조정 검토. (게이트 아님 — 관측용)")
    else:
        print("   → 큰 갭 없음. 트림 정상.")


def default_plan_path(first_audio: str) -> str:
    """기본 플랜 저장 위치 — 표준 폴더 구조면 03_자막/, 아니면 오디오 옆."""
    audio_dir = os.path.dirname(os.path.abspath(first_audio))
    sub_dir = os.path.join(os.path.dirname(audio_dir), "03_자막")
    base = sub_dir if os.path.isdir(sub_dir) else audio_dir
    return os.path.join(base, "silence_cut_plan.json")


def main():
    ap = argparse.ArgumentParser(description="무음 컷 — 긴 무음(≥min-gap)을 0.3s+0.3s만 남기고 압축")
    ap.add_argument("files", nargs="*", help="입력 오디오(m4a 등, 다중 가능)")
    ap.add_argument("--min-gap", type=float, default=MIN_GAP_DEFAULT)
    ap.add_argument("--pad", type=float, default=PAD_DEFAULT)
    ap.add_argument("--noise", type=float, default=NOISE_DEFAULT, help="silencedetect 문턱(dB)")
    ap.add_argument("--max-cut-pct", type=float, default=MAX_CUT_PCT_DEFAULT)
    ap.add_argument("--force", action="store_true", help="삭감률 상한 초과 강행")
    ap.add_argument("--analyze", action="store_true", help="컷 없이 문턱 스윕 리포트만")
    ap.add_argument("--verify", metavar="TRANSCRIPT", help="STT 후 언더컷 검증(transcript.json)")
    ap.add_argument("--verify-gap", type=float, default=VERIFY_GAP_DEFAULT)
    ap.add_argument("--plan-out", help="silence_cut_plan.json 저장 경로(기본: 03_자막/ 또는 오디오 옆)")
    args = ap.parse_args()

    if args.verify:
        verify_transcript(args.verify, args.verify_gap)
        return
    if not args.files:
        ap.error("입력 오디오가 없습니다 (또는 --verify <transcript.json>)")
    if args.pad < 0 or args.min_gap <= 0:
        ap.error(f"--pad({args.pad})는 0 이상, --min-gap({args.min_gap})은 0보다 커야 함 — "
                 f"음수 pad는 컷을 무음 밖 발화까지 확장시킨다")
    if args.pad * 2 >= args.min_gap:
        ap.error(f"--pad*2({args.pad * 2})가 --min-gap({args.min_gap}) 이상 — 컷이 성립하지 않음")
    for p in args.files:
        if not os.path.isfile(p):
            ap.error(f"파일 없음: {p}")

    if args.analyze:
        for p in args.files:
            analyze_file(p, args)
        return

    plans = [trim_file(p, args) for p in args.files]

    total_src = sum(p["src_duration"] for p in plans)
    total_removed = sum(p["stats"]["removed_sec"] for p in plans)
    print(f"\n== 합계: {len(plans)}파일, {total_src:.2f}s → {total_src - total_removed:.2f}s "
          f"(-{total_removed:.2f}s / {total_removed / total_src * 100 if total_src else 0:.1f}%), "
          f"컷 {sum(p['stats']['n_cuts'] for p in plans)}건")

    plan_path = args.plan_out or default_plan_path(args.files[0])
    plan_dir = os.path.dirname(plan_path)
    if plan_dir:
        os.makedirs(plan_dir, exist_ok=True)
    tmp_path = plan_path + ".tmp"          # 원자적 쓰기 — 동시/중단 실행이 플랜을 반쯤 덮지 않게
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_by": "trim_silence.py",
            "params": {"min_gap": args.min_gap, "pad": args.pad, "noise_db": args.noise,
                       "max_cut_pct": args.max_cut_pct},
            "files": plans,
            "totals": {"src_duration": round(total_src, 3),
                       "removed_sec": round(total_removed, 3),
                       "removed_pct": round(total_removed / total_src * 100, 2) if total_src else 0.0},
        }, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, plan_path)
    print(f"컷 플랜 저장: {plan_path}")
    print("다음 단계: 트림본(.trim.m4a)으로 Step 2(Whisper 전사) 진행 — 원본을 전사하면 안 됨")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
