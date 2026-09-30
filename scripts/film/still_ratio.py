# -*- coding: utf-8 -*-
"""정지 화면 비율 측정 — 정본 check_motion.py와 같은 판정식 (타임라인 없이 고정 창 단위).

판정식 (check_motion.py diff_series/evaluate 그대로):
  ffmpeg로 10fps · 320px 폭 그레이스케일 프레임을 스트리밍
  d5[k] = mean|f[k] - f[k-5]|  (0.5초 격자 차분, 0~255)   → d5 < eps 이면 그 시각은 "정지"
  창 [a, b]의 정지 비율 = (a+0.5 ≤ t ≤ b 인 d5 표본 중 정지 개수) / 표본 수
  창 길이 ≥ window 인 창만 판정:  비율 > fail(0.75) → FAIL,  ≥ warn(0.50) → WARN
  (check_motion은 슬라이드 길이 > 6s만 판정한다. 여기서는 창이 정확히 6s라 '≥ window'로 판정하고,
   영상 끝의 짧은 자투리 창은 판정 제외 = check_motion의 짧은 슬라이드와 같은 취급)
  전체 평균 = 판정된 창들의 정지 비율 평균 (check_motion avg_still_ratio와 같은 산식)
  최대 정지 연속 구간 = d5 정지 표본이 연속된 가장 긴 구간. 길이 = (표본수-1)*0.1 + 0.5초
  참고 지표 adjacent_still_ratio = 인접 프레임(0.1초) 차분 d1 < eps 비율 (판정에는 쓰지 않음)

사용:
  python still_ratio.py capture.mp4
  python still_ratio.py capture.mp4 --eps 1.0 --window 6 --json out.json

종료 코드: 0 = FAIL 없음 / 1 = FAIL 창 존재 / 2 = 입력·측정 오류
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GRID = 0.5          # check_motion.GRID
SAMPLE_FPS = 10     # check_motion.SAMPLE_FPS
FFMPEG_TIMEOUT = 600


def die(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        die("[입력 오류] ffmpeg을 찾을 수 없다")
    return exe


def probe(ff, video):
    p = subprocess.run([ff, "-hide_banner", "-i", str(video)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        die(f"[입력 오류] 영상 길이를 읽지 못했다: {video}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    ms = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", p.stderr)
    size = (int(ms.group(1)), int(ms.group(2))) if ms else (None, None)
    return dur, size


def diff_series(ff, video, width, src_size):
    """check_motion.diff_series와 같은 산식 → (d1, d5) [(t, v)]."""
    import numpy as np
    sw, sh = src_size
    height = max(2, int(round(width * sh / sw / 2)) * 2) if (sw and sh) else 180
    frame_bytes = width * height
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"fps={SAMPLE_FPS},scale={width}:{height}",
           "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    ring, d1, d5, k = [], [], [], 0
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, bufsize=frame_bytes * 4)
        try:
            while True:
                buf = proc.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                cur = np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
                if ring:
                    d1.append((k / SAMPLE_FPS, float(np.abs(cur - ring[-1]).mean())))
                if len(ring) >= 5:
                    d5.append((k / SAMPLE_FPS, float(np.abs(cur - ring[-5]).mean())))
                ring.append(cur)
                if len(ring) > 5:
                    ring.pop(0)
                k += 1
        finally:
            proc.stdout.close()
            try:
                proc.wait(timeout=FFMPEG_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                die("[측정 실패] ffmpeg 시간 초과")
            errf.seek(0)
            err = errf.read().decode("utf-8", "replace")
    if proc.returncode != 0:
        die(f"[측정 실패] ffmpeg rc={proc.returncode}: {err.strip()[-600:]}")
    if k == 0:
        die(f"[측정 실패] 프레임이 한 장도 나오지 않았다: {video}")
    return d1, d5


def parse_holds(spec):
    """"a-b,c-d" 또는 JSON 경로 → [(t0, t1, 이유)]. JSON은 {"holds":[[t0,t1,"이유"],...]} 또는 그 리스트."""
    p = Path(spec)
    items = []
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("holds", [])
        for h in data:
            if isinstance(h, dict):
                items.append((float(h["start"]), float(h["end"]), str(h.get("why", ""))))
            else:
                items.append((float(h[0]), float(h[1]), str(h[2]) if len(h) > 2 else ""))
    else:
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^([\d.]+)\s*[-~]\s*([\d.]+)$", part)
            if not m:
                die(f"[입력 오류] --holds 형식은 \"a-b,c-d\" 또는 JSON 경로: {part}")
            items.append((float(m.group(1)), float(m.group(2)), ""))
    bad = [h for h in items if h[1] <= h[0]]
    if bad:
        die(f"[입력 오류] 끝이 시작보다 작은 홀드: {bad}")
    return sorted(items)


def longest_still(d5, eps):
    best = (0, None, None)
    run, run_start = 0, None
    for t, v in d5:
        if v < eps:
            if run == 0:
                run_start = t
            run += 1
            if run > best[0]:
                best = (run, run_start, t)
        else:
            run = 0
    n, a, b = best
    if n == 0:
        return {"sec": 0.0, "start": None, "end": None}
    return {"sec": round((n - 1) / SAMPLE_FPS + GRID, 2), "start": round(a - GRID, 2), "end": round(b, 2)}


def main():
    ap = argparse.ArgumentParser(description="정지 화면 비율 측정 (check_motion.py와 같은 판정식, 고정 창 단위)")
    ap.add_argument("mp4", help="측정할 mp4")
    ap.add_argument("--eps", type=float, default=1.0, help="정지 판정 임계(0.5초 차분 평균 절대차, 기본 1.0)")
    ap.add_argument("--window", type=float, default=6.0, help="창 길이 초(기본 6)")
    ap.add_argument("--fail", type=float, default=0.75, help="FAIL 정지 비율(기본 0.75)")
    ap.add_argument("--warn", type=float, default=0.50, help="WARN 정지 비율(기본 0.50)")
    ap.add_argument("--width", type=int, default=320, help="분석 폭(기본 320)")
    ap.add_argument("--json", metavar="OUT", help="결과 JSON 저장 경로")
    ap.add_argument("--holds", metavar="SPEC",
                    help="선언한 읽기 홀드 구간. \"a-b,c-d\" 또는 JSON 경로({\"holds\":[[t0,t1,\"이유\"],...]}, "
                         "capture.py가 FILM.holds에서 만든 <out>.holds.json). 홀드 안 표본을 뺀 비율을 함께 낸다")
    ap.add_argument("--judge", choices=["raw", "excl"], default="raw",
                    help="FAIL/WARN 판정에 쓸 비율: raw(기본, 정본 check_motion과 동일) / excl(홀드 제외 비율)")
    args = ap.parse_args()

    video = Path(args.mp4)
    if not video.exists():
        die(f"[입력 오류] 파일이 없다: {video}")
    holds = parse_holds(args.holds) if args.holds else []
    in_hold = lambda t: any(h0 <= t <= h1 for h0, h1, _ in holds)
    ff = find_ffmpeg()
    dur, size = probe(ff, video)
    d1, d5 = diff_series(ff, video, args.width, size)

    rows = []
    a = 0.0
    while a < dur - 1e-6:
        b = min(a + args.window, dur)
        vals = [v for t, v in d5 if a + GRID <= t <= b]
        vals_ex = [v for t, v in d5 if a + GRID <= t <= b and not in_hold(t)]
        ratio = (sum(1 for v in vals if v < args.eps) / len(vals)) if vals else 0.0
        ratio_ex = (sum(1 for v in vals_ex if v < args.eps) / len(vals_ex)) if vals_ex else 0.0
        judged = (b - a) >= args.window - 1e-6 and len(vals) > 0
        jr = ratio_ex if args.judge == "excl" else ratio
        if not judged:
            level = "SHORT" if vals or (b - a) <= 2 * GRID else "NOMEAS"
        elif jr > args.fail:
            level = "FAIL"
        elif jr >= args.warn:
            level = "WARN"
        else:
            level = "OK"
        rows.append({"start": round(a, 2), "end": round(b, 2), "samples": len(vals),
                     "still_ratio": round(ratio, 3),
                     "samples_excl_holds": len(vals_ex), "still_ratio_excl_holds": round(ratio_ex, 3),
                     "level": level})
        a += args.window

    judged = [r for r in rows if r["level"] in ("OK", "WARN", "FAIL")]
    avg = round(sum(r["still_ratio"] for r in judged) / len(judged), 3) if judged else None
    jx = [r for r in judged if r["samples_excl_holds"] > 0]
    avg_ex = round(sum(r["still_ratio_excl_holds"] for r in jx) / len(jx), 3) if jx else None
    hold_sec = round(sum(max(0.0, min(h1, dur) - max(h0, 0.0)) for h0, h1, _ in holds), 2)
    overall = round(sum(1 for _, v in d5 if v < args.eps) / len(d5), 3) if d5 else None
    adjacent = round(sum(1 for _, v in d1 if v < args.eps) / len(d1), 3) if d1 else None
    run = longest_still(d5, args.eps)
    fails = [r for r in rows if r["level"] == "FAIL"]
    warns = [r for r in rows if r["level"] == "WARN"]

    rep = {"video": str(video.resolve()), "duration": round(dur, 2), "size": list(size),
           "method": f"d5 frame-diff {SAMPLE_FPS}fps @{args.width}px (check_motion.py 동일)",
           "eps": args.eps, "window": args.window, "fail": args.fail, "warn": args.warn,
           "holds": [[h0, h1, why] for h0, h1, why in holds], "judge": args.judge,
           "windows": rows,
           "summary": {"avg_still_ratio": avg, "avg_still_ratio_excl_holds": avg_ex,
                       "hold_seconds": hold_sec, "overall_still_ratio": overall,
                       "adjacent_still_ratio": adjacent, "longest_still": run,
                       "fail": len(fails), "warn": len(warns), "judged": len(judged)}}

    print(f"영상: {video}  ({dur:.2f}s, {size[0]}x{size[1]})  방식: {rep['method']} / eps={args.eps}"
          + (f" / 홀드 {len(holds)}구간 {hold_sec}s 제외 열 포함 (판정={args.judge})" if holds else ""))
    print(f"{'창':<16}{'표본':>6}{'정지비율':>10}{'홀드제외':>10}  판정")
    for r in rows:
        span = f"{r['start']:.1f}~{r['end']:.1f}"
        ex = f"{r['still_ratio_excl_holds'] * 100:>9.1f}%" if holds else f"{'-':>10}"
        print(f"{span:<16}{r['samples']:>6}{r['still_ratio'] * 100:>9.1f}%{ex}  {r['level']}")
    print("-" * 54)
    fmt = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"
    print(f"판정 창 {len(judged)}개 · 평균 정지 비율 {fmt(avg)}"
          + (f" · 홀드 제외 평균 {fmt(avg_ex)}" if holds else "")
          + f" · 전체 표본 정지 {fmt(overall)} · 인접 프레임 정지(참고) {fmt(adjacent)}")
    if run["start"] is None:
        print("최대 정지 연속 구간: 없음")
    else:
        print(f"최대 정지 연속 구간: {run['sec']:.2f}s ({run['start']:.2f}~{run['end']:.2f}s)")
    print(f"FAIL {len(fails)} · WARN {len(warns)}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
