# -*- coding: utf-8 -*-
"""모션 실측 게이트 — "80~90% 정지 화면" 회귀 방지 (결정론).

설계 정본: docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md §3-4.

입력
  - 04_영상소스/capture.mp4 (또는 임의의 mp4)
  - 타임라인.json (slides[].start/end/label)

방식
  ffmpeg 한 번으로 저해상(기본 320px 폭) 그레이 프레임을 10fps로 스트리밍 →
    · 0.5초 격자 차분  d5[k] = mean|f[k] - f[k-5]|   → 슬라이드별 "정지 비율"
    · 0.1초 인접 차분  d1[k] = mean|f[k] - f[k-1]|   → 컷 경계 "죽은 박자"
  numpy가 없으면 ffmpeg freezedetect(n=0.001:d=1.5) 폴백으로 정지 구간만 계산한다
  (이 경우 죽은 박자 검사는 생략).

판정
  슬라이드 길이 > 6s 이고 정지 비율 > 75%  → FAIL
                       정지 비율 50~75%   → WARN
  슬라이드 경계 t에서 t-0.1·t+0.1 양쪽 차분이 모두 정지 → WARN(죽은 박자: 양쪽 다 멈춘 채 컷)
  한쪽만 정지면 참고(half) — 나가는 쪽이 멈춘 뒤 컷되는 현행 크로스페이드 패턴

사용
  python scripts/check_motion.py "결과물/2026-08-06_풀링013_..."
  python scripts/check_motion.py <capture.mp4> --timeline <타임라인.json>
  python scripts/check_motion.py <작업폴더> --warn-only --json
  옵션: --eps 1.0 (정지 판정 임계, 0~255 평균 절대차) --fail 0.75 --warn 0.50 --width 320

종료 코드: 0 = 통과(또는 --warn-only), 1 = FAIL 존재, 2 = 입력 오류
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

FFMPEG_TIMEOUT = 600   # 프레임 추출 상한(초) — 교착·행 방지

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GRID = 0.5          # 정지 판정 격자(초)
SAMPLE_FPS = 10     # 추출 fps (0.1초 = 죽은 박자 검사 해상도)
DEAD_BEAT_DT = 0.1


def die(msg: str):
    """입력 오류 종료 — 게이트 위반(1)과 구분되는 exit 2."""
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        die("[입력 오류] ffmpeg을 찾을 수 없다 — pip install imageio-ffmpeg")
    return exe


def probe(ffmpeg: str, video: Path):
    p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        die(f"[입력 오류] 영상 길이를 읽지 못했다: {video}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    ms = re.search(r",\s*(\d+)x(\d+)", p.stderr)
    size = (int(ms.group(1)), int(ms.group(2))) if ms else (None, None)
    return dur, size


# --------------------------------------------------------------------- 프레임 차분
def diff_series(ffmpeg: str, video: Path, width: int, src_size):
    """10fps 그레이 프레임 스트림 → (d1, d5) 시계열. d?[k]는 시각 k/SAMPLE_FPS의 값."""
    import numpy as np

    sw, sh = src_size
    if sw and sh:
        height = max(2, int(round(width * sh / sw / 2)) * 2)
    else:
        height = 180
    frame_bytes = width * height
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", f"fps={SAMPLE_FPS},scale={width}:{height}",
           "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    if width < 2 or frame_bytes <= 0:
        die(f"[입력 오류] 분석 폭이 비정상이다: --width {width}")
    # stderr는 임시 파일로 받아 실패 사유를 보존한다 — DEVNULL+반환코드 미검사는 "측정 실패"를
    # "완벽히 움직였다"(정지 0%)와 같은 PASS로 만들었다 (2026-09-02 리뷰 C1).
    # PIPE는 금지: stdout 루프가 끝난 뒤에야 읽으면 ffmpeg가 stderr 버퍼를 채우는 순간 상호 대기(교착).
    ring = []          # 최근 6프레임
    d1, d5 = [], []
    k = 0
    err = b""
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf,
                                bufsize=frame_bytes * 4)
        # 워치독: stdout 읽기 루프 도중 ffmpeg가 출력도 종료도 없이 멈추면 아래 wait(timeout)에
        # 도달하지 못한다 → 타이머가 프로세스를 죽여 read()를 EOF로 풀고 rc≠0 경로로 보낸다.
        timed_out = threading.Event()

        def _watchdog():
            timed_out.set()
            try:
                proc.kill()
            except Exception:
                pass

        watchdog = threading.Timer(FFMPEG_TIMEOUT, _watchdog)
        watchdog.daemon = True
        watchdog.start()
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
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=FFMPEG_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                timed_out.set()
            finally:
                watchdog.cancel()
            if timed_out.is_set():
                die(f"[측정 실패] ffmpeg가 {FFMPEG_TIMEOUT}s 안에 끝나지 않아 강제 종료: {video}")
            try:
                errf.seek(0)
                err = errf.read() or b""
            except Exception:
                pass
    if proc.returncode != 0:
        die(f"[측정 실패] ffmpeg 프레임 추출 rc={proc.returncode}: "
            f"{err.decode('utf-8', 'replace').strip()[-600:]}")
    if k == 0:
        die(f"[측정 실패] 프레임이 한 장도 나오지 않았다: {video}")
    return d1, d5


def freeze_intervals(ffmpeg: str, video: Path):
    """numpy 폴백 — freezedetect로 정지 구간 [(start,end)] 추출."""
    try:
        p = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video),
             "-vf", "freezedetect=n=0.001:d=1.5", "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        die(f"[측정 실패] freezedetect가 {FFMPEG_TIMEOUT}s 안에 끝나지 않았다: {video}")
    if p.returncode != 0:
        die(f"[측정 실패] freezedetect rc={p.returncode}: {p.stderr.strip()[-600:]}")
    starts = [float(x) for x in re.findall(r"freeze_start:\s*(-?\d+\.?\d*)", p.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end:\s*(-?\d+\.?\d*)", p.stderr)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        out.append((s, e))
    return out


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# --------------------------------------------------------------------- 판정
def evaluate(slides, d5, d1, args, freezes=None, duration=None):
    rows = []
    for s in slides:
        start, end = float(s["start"]), float(s["end"])
        length = end - start
        # 영상 길이를 벗어난 슬라이드는 길이와 무관하게 측정 불가(부분 캡처) — 폴백 모드도 포함.
        out_of_video = duration is not None and end > duration + GRID
        if freezes is not None:
            frozen = sum(overlap(start, end, f0, f1 if f1 is not None else end) for f0, f1 in freezes)
            ratio = frozen / length if length > 0 else 0.0
            samples = -1
        else:
            vals = [v for t, v in d5 if start + GRID <= t <= end]
            samples = len(vals)
            if samples == 0:
                ratio = 0.0
            else:
                ratio = sum(1 for v in vals if v < args.eps) / samples
        # 표본 0 = 측정 불가(부분 캡처·구간 이탈). OK가 아니라 NOMEAS로 승격해 fail-loud.
        # 짧은 슬라이드(≤min_len)도 d5 표본이 하나는 나와야 할 길이(>2·GRID)면 동일 취급.
        if out_of_video or (samples == 0 and length > 2 * GRID):
            level = "NOMEAS"
        elif length > args.min_len and ratio > args.fail:
            level = "FAIL"
        elif length > args.min_len and ratio >= args.warn:
            level = "WARN"
        else:
            level = "OK"
        rows.append({
            "id": s.get("id", f"#{s.get('index', '?')}"),
            "label": s.get("label", ""),
            "start": round(start, 2), "end": round(end, 2), "len": round(length, 2),
            "still_ratio": round(ratio, 3), "samples": samples, "level": level,
        })
    return rows


def dead_beats(slides, d1, eps):
    """슬라이드 경계 t에서 t-0.1 / t+0.1 차분이 둘 다 정지면 '죽은 박자'.

    eps는 0.5s 간격 d5 기준 임계라 0.1s 간격 d1에는 구조적으로 과대하다 → d1 전용 임계 eps/4.
    """
    if not d1:
        return []
    eps = eps / 4.0
    lut = {round(t, 2): v for t, v in d1}

    def val(t):
        return lut.get(round(round(t * SAMPLE_FPS) / SAMPLE_FPS, 2))

    out = []
    for s in slides[1:]:
        t = float(s["start"])
        before, after = val(t - DEAD_BEAT_DT), val(t + DEAD_BEAT_DT)
        if before is None or after is None:
            continue
        kind = None
        if before < eps and after < eps:
            kind = "dead"        # 양쪽 다 정지 상태로 컷 = 죽은 박자
        elif before < eps or after < eps:
            kind = "half"        # 한쪽만 정지 — 벡터 법칙상 속도 불일치 컷(참고)
        if kind:
            out.append({"id": s.get("id", "?"), "t": round(t, 2), "kind": kind,
                        "before": round(before, 3), "after": round(after, 3)})
    return out


def resolve_inputs(target: Path, timeline_arg):
    if target.is_dir():
        video = target / "04_영상소스" / "capture.mp4"
        if not video.exists():
            cands = list(target.glob("**/capture.mp4"))
            if not cands:
                die(f"[입력 오류] capture.mp4를 찾지 못했다: {target}")
            video = cands[0]
        root = target
    else:
        video = target
        if not video.exists():
            die(f"[입력 오류] 파일이 없다: {video}")
        root = video.parent.parent
    tl = Path(timeline_arg) if timeline_arg else root / "타임라인.json"
    if not tl.exists():
        die(f"[입력 오류] 타임라인.json이 없다: {tl}")
    return video, tl


def main():
    ap = argparse.ArgumentParser(description="모션 실측 게이트 (정지 화면 회귀 방지)")
    ap.add_argument("target", help="작업 폴더 또는 capture.mp4 경로")
    ap.add_argument("--timeline", help="타임라인.json 경로")
    ap.add_argument("--eps", type=float, default=1.0, help="정지 판정 임계(평균 절대차 0~255, 기본 1.0)")
    ap.add_argument("--fail", type=float, default=0.75, help="FAIL 정지 비율(기본 0.75)")
    ap.add_argument("--warn", type=float, default=0.50, help="WARN 정지 비율(기본 0.50)")
    ap.add_argument("--min-len", type=float, default=6.0, help="판정 대상 최소 슬라이드 길이(기본 6s)")
    ap.add_argument("--width", type=int, default=320, help="분석 해상도 폭(기본 320)")
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    video, tl = resolve_inputs(Path(args.target), args.timeline)
    timeline = json.loads(tl.read_text(encoding="utf-8"))
    slides = timeline.get("slides") or []
    if not slides:
        die(f"[입력 오류] 타임라인에 slides가 없다: {tl}")

    ffmpeg = find_ffmpeg()
    dur, size = probe(ffmpeg, video)

    freezes = None
    d1 = d5 = []
    try:
        import numpy  # noqa: F401
        d1, d5 = diff_series(ffmpeg, video, args.width, size)
    except ImportError:
        freezes = freeze_intervals(ffmpeg, video)

    rows = evaluate(slides, d5, d1, args, freezes, duration=dur)
    beats = dead_beats(slides, d1, args.eps) if freezes is None else []

    fails = [r for r in rows if r["level"] == "FAIL"]
    warns = [r for r in rows if r["level"] == "WARN"]
    nomeas = [r for r in rows if r["level"] == "NOMEAS"]
    # 평균에는 측정된 슬라이드만 — NOMEAS를 0.0으로 넣으면 잘린 캡처가 "좋아진" 것처럼 보인다.
    judged = [r for r in rows if r["len"] > args.min_len and r["level"] != "NOMEAS"]
    avg = round(sum(r["still_ratio"] for r in judged) / len(judged), 3) if judged else 0.0

    if args.json:
        print(json.dumps({
            "video": str(video), "timeline": str(tl), "duration": round(dur, 2),
            "mode": "freezedetect" if freezes is not None else "frame-diff",
            "eps": args.eps, "slides": rows, "dead_beats": beats,
            "summary": {"fail": len(fails), "warn": len(warns), "nomeas": len(nomeas),
                        "avg_still_ratio": avg},
        }, ensure_ascii=False, indent=1))
    else:
        print(f"영상: {video}  ({dur:.2f}s, {size[0]}x{size[1]})")
        print(f"타임라인: {tl}  슬라이드 {len(slides)}개")
        print(f"방식: {'freezedetect 폴백' if freezes is not None else f'프레임 차분 {SAMPLE_FPS}fps @{args.width}px'}"
              f" / 정지 임계 eps={args.eps}")
        print("-" * 88)
        print(f"{'슬라이드':<8}{'구간':<18}{'길이':>7}{'정지비율':>10}  판정  라벨")
        for r in rows:
            span = "{:.2f}~{:.2f}".format(r["start"], r["end"])
            print(f"{r['id']:<8}{span:<18}{r['len']:>7.2f}"
                  f"{r['still_ratio'] * 100:>9.1f}%  {r['level']:<5} {r['label'][:34]}")
        print("-" * 88)
        print(f"판정 대상(>{args.min_len:.0f}s) {len(judged)}개 · 평균 정지 비율 {avg * 100:.1f}% · "
              f"FAIL {len(fails)} · WARN {len(warns)} · 측정불가 {len(nomeas)}")
        if nomeas:
            print(f"측정 불가(표본 0) {len(nomeas)}건 [FAIL] — 캡처가 타임라인보다 짧거나 구간이 영상 밖:")
            for r in nomeas:
                print(f"  - {r['id']} {r['start']:.2f}~{r['end']:.2f}s (영상 길이 {dur:.2f}s)")
        dead = [b for b in beats if b["kind"] == "dead"]
        half = [b for b in beats if b["kind"] == "half"]
        if dead:
            print(f"죽은 박자(양쪽 정지 컷) {len(dead)}건 [WARN]:")
            for b in dead:
                print(f"  - {b['id']} t={b['t']:.2f}s (before={b['before']}, after={b['after']})")
        if half:
            print(f"한쪽 정지 컷(속도 불일치, 참고) {len(half)}건: "
                  + ", ".join(f"{b['id']}@{b['t']:.1f}s" for b in half[:12])
                  + (" …" if len(half) > 12 else ""))

    if (fails or nomeas) and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
