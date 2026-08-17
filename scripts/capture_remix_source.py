"""쇼츠 리믹스 "재생성 소스" 캡처 — 가로로 넓은 슬라이드 HTML → 무음 mp4.

왜 별도 스크립트인가:
  capture_slides.py는 디자인 해상도가 본편 16:9(1920x1080)/쇼츠 9:16(1080x1920) 두 가지로 고정돼
  있고 출력 비율이 디자인 비율과 다르면 즉시 중단한다. 리믹스 소스는 그 어느 쪽도 아닌
  1080x700(캔버스 폭 × 영상 슬롯 높이)이라 그 계약에 넣을 수 없다. 그래서 기존 스크립트는
  전혀 건드리지 않고, 결정론 캡처 관례(BeginFrame 제어 + CDP 가상시간 + __capture.seek +
  damage 토글 + 청크 워치독)만 그대로 복제한 전용 경로를 둔다.

무엇을 하나:
  HTML을 ?capture=1로 열어 프레임마다 window.__capture.seek(t)로 덱 상태를 직접 구동하고,
  HeadlessExperimental.beginFrame으로 합성+스크린샷을 원자적으로 받아 ffmpeg에 파이프한다.
  시계와 무관하므로 SLIDE_TIMELINE이 프레임 단위로 정확히 반영된다(가상시간 = 결정론).
  레이아웃은 디자인 크기(기본 1080x700)로 계산하고 deviceScaleFactor로 픽셀만 키운다
  (기본 출력 2160x1400 = 2배). 1080x700으로의 다운스케일은 렌더 단계(remix_shorts.py)가 한다.

전제: HTML이 캡처 모드(?capture=1 → window.__capture.seek)를 지원해야 한다
      (템플릿/shorts-remix-source.html 보일러플레이트에 내장).

사용:
  python capture_remix_source.py <source.html> --duration 34.10
  python capture_remix_source.py <source.html> --duration 34.10 --out source-capture.mp4
                                 [--size 2160x1400] [--design 1080x700] [--fps 30]
"""
import argparse
import base64
import pathlib
import re
import shutil
import subprocess
import sys
import time

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

# 한국어 Windows cp949 콘솔 크래시 방지 (다른 scripts와 동일)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

DEFAULT_DESIGN = (1080, 700)     # 리믹스 영상 슬롯 = 캔버스 폭 1080 × 슬롯 높이 700
DEFAULT_SIZE = (2160, 1400)      # 2배 렌더 후 렌더 단계에서 1080x700으로 다운스케일
CHUNK_SEC = 60.0                 # beginFrame 장시간 실행 시 간헐 데드락 → 청크별 새 브라우저
PREROLL_SEC = 4.0                # 청크 시작 전 렌더만 하고 버리는 구간 (등장 트랜지션 정착용)


def record_range(html: pathlib.Path, t_a: float, t_b: float, fps: int,
                 out_w: int, out_h: int, design_w: int, design_h: int,
                 out: pathlib.Path) -> None:
    """[t_a, t_b) 구간을 프레임 단위로 캡처해 세그먼트 mp4 저장. 앞 PREROLL은 렌더만 하고 버린다."""
    if abs(out_w / out_h - design_w / design_h) > 0.01:
        sys.exit(f"[오류] 출력 비율({out_w}x{out_h})이 디자인 비율({design_w}x{design_h})과 다릅니다")
    dsf = out_w / design_w
    step_ms = 1000.0 / fps
    k_first = int(round(t_a * fps))
    k_pre = max(0, int(round((t_a - PREROLL_SEC) * fps)))
    k_end = int(round(t_b * fps))

    enc = subprocess.Popen(
        [FFMPEG, "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
         "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-r", str(fps), "-an", str(out)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--enable-begin-frame-control",
            "--run-all-compositor-stages-before-draw",
            "--disable-new-content-rendering-timeout",
            "--force-color-profile=srgb", "--hide-scrollbars",
            # beginFrame 스크린샷은 컴포지터 서피스(물리 픽셀) 기준 — 전역 DSF + 창 크기를
            # 출력 해상도에 맞춰야 고해상도가 나온다 (context DSF만으로는 CSS px에 머문다)
            f"--force-device-scale-factor={dsf:.7f}",
            f"--window-size={out_w},{out_h}",
        ])
        ctx = browser.new_context(viewport={"width": design_w, "height": design_h},
                                  device_scale_factor=dsf)
        page = ctx.new_page()
        client = ctx.new_cdp_session(page)
        page.goto(html.resolve().as_uri() + "?capture=1")
        # BeginFrame 제어 중엔 rAF가 멈춰 있으므로 rAF 폴링이 아닌 interval 폴링 필수
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=60_000, polling=100)
        page.wait_for_function("window.__capture && typeof window.__capture.seek === 'function'",
                               timeout=10_000, polling=100)
        # 무손상 프레임에서 beginFrame이 웨지되는 Chromium 데드락 회피 — 좌상단 2px를 매 프레임 토글
        page.evaluate(
            "const d = document.createElement('div'); d.id = '__capture_dmg';"
            "d.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;"
            "background:#fffffe;z-index:99999;pointer-events:none';"
            "document.body.appendChild(d);")
        for _ in range(3):  # 렌더 워밍업
            client.send("HeadlessExperimental.beginFrame", {})

        expired = {"flag": False}
        client.on("Emulation.virtualTimeBudgetExpired", lambda _: expired.__setitem__("flag", True))
        client.send("Emulation.setVirtualTimePolicy", {"policy": "pause"})

        last = None
        for k in range(k_pre, k_end):
            page.evaluate(
                f"window.__capture.seek({k / fps:.4f});"
                f"document.getElementById('__capture_dmg').style.background = "
                f"{k} % 2 ? '#fffffe' : '#ffffff'")
            r = client.send("HeadlessExperimental.beginFrame",
                            {"screenshot": {"format": "jpeg", "quality": 93}})
            data = r.get("screenshotData")
            if data:
                last = base64.b64decode(data)
            elif last is None:
                sys.exit(f"[오류] 프레임 {k}: beginFrame 스크린샷 실패 (첫 프레임)")
            if k >= k_first:
                enc.stdin.write(last)   # 변화 없으면 스크린샷이 생략될 수 있음 → 직전 프레임 재사용
            expired["flag"] = False
            client.send("Emulation.setVirtualTimePolicy", {"policy": "advance", "budget": step_ms})
            while not expired["flag"]:
                page.wait_for_timeout(2)  # 이벤트 루프 펌프
            if k % 300 == 0:
                print(f"      seg frame {k}/{k_end}", flush=True)  # 워치독 활동 신호
        browser.close()
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("[오류] ffmpeg 인코딩 실패")


def run_chunked(html: pathlib.Path, duration: float, fps: int, out_w: int, out_h: int,
                design_w: int, design_h: int, out: pathlib.Path) -> None:
    """청크 단위 자식 프로세스 + 워치독으로 전체를 캡처하고 무손실 concat한다."""
    segdir = out.parent / "_remix_capture_segs"
    segdir.mkdir(parents=True, exist_ok=True)
    bounds, a = [], 0.0
    while a < duration:
        bounds.append((a, min(a + CHUNK_SEC, duration)))
        a += CHUNK_SEC

    t_run, segs = time.monotonic(), []
    for n, (a, b) in enumerate(bounds, 1):
        seg = segdir / f"seg_{n:03d}.mp4"
        budget = 120 + int(round((b - a + PREROLL_SEC) * fps)) // 4   # 최소 4fps 가정한 워치독
        ok = False
        for attempt in (1, 2, 3):
            print(f"[청크 {n}/{len(bounds)}] {a:.1f}–{b:.1f}s (시도 {attempt}) — 한도 {budget}s",
                  flush=True)
            cmd = [sys.executable, "-u", str(pathlib.Path(__file__).resolve()), str(html),
                   "--_chunk", f"{a:.4f}", f"{b:.4f}", "--fps", str(fps),
                   "--size", f"{out_w}x{out_h}", "--design", f"{design_w}x{design_h}",
                   "--out", str(seg)]
            with open(seg.with_suffix(f".try{attempt}.log"), "wb") as log_f:
                proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
                try:
                    rc = proc.wait(timeout=budget)
                except subprocess.TimeoutExpired:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True)
                    print(f"      ⚠️ 청크 {n} 워치독 발동 ({budget}s 초과) — 재시도", flush=True)
                    continue
            if rc == 0 and seg.is_file() and seg.stat().st_size > 1000:
                ok = True
                break
            print(f"      ⚠️ 청크 {n} 비정상 종료 (rc={rc}) — 재시도", flush=True)
        if not ok:
            sys.exit(f"[오류] 청크 {n} 캡처가 3회 모두 실패했습니다")
        segs.append(seg)

    if len(segs) == 1:
        shutil.copyfile(segs[0], out)
    else:
        lst = segdir / "concat.txt"
        lst.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
        r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(out)], capture_output=True)
        if r.returncode != 0:
            sys.exit("[오류] 세그먼트 concat 실패:\n" + r.stderr.decode("utf-8", "replace")[-800:])
    shutil.rmtree(segdir, ignore_errors=True)
    print(f"      전체 {len(segs)}청크, {(time.monotonic() - t_run) / 60:.1f}분 소요", flush=True)


def _wh(text: str, label: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{3,5})x(\d{3,5})", (text or "").lower())
    if not m:
        sys.exit(f"[오류] --{label} 형식은 WxH (예: 2160x1400): {text}")
    return int(m.group(1)), int(m.group(2))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="쇼츠 리믹스 재생성 소스 캡처 (가로로 넓은 슬라이드 HTML → 무음 mp4)")
    ap.add_argument("html", type=pathlib.Path)
    ap.add_argument("--duration", type=float, help="캡처 길이(초) — 쇼츠 컷합과 같아야 한다")
    ap.add_argument("--out", type=pathlib.Path, help="출력 mp4 (기본: HTML 옆 source-capture.mp4)")
    ap.add_argument("--size", default=f"{DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]}",
                    help=f"출력 WxH (기본 {DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]})")
    ap.add_argument("--design", default=f"{DEFAULT_DESIGN[0]}x{DEFAULT_DESIGN[1]}",
                    help=f"CSS 레이아웃 기준 WxH (기본 {DEFAULT_DESIGN[0]}x{DEFAULT_DESIGN[1]})")
    ap.add_argument("--fps", type=int, default=30, help="프레임레이트 (기본 30)")
    ap.add_argument("--_chunk", nargs=2, type=float, metavar=("A", "B"), help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not args.html.is_file():
        sys.exit(f"[오류] HTML 없음: {args.html}")
    out_w, out_h = _wh(args.size, "size")
    design_w, design_h = _wh(args.design, "design")

    if args._chunk:                     # 내부용: 청크 자식 프로세스 모드
        record_range(args.html, args._chunk[0], args._chunk[1], args.fps,
                     out_w, out_h, design_w, design_h, args.out)
        return

    if args.duration is None or args.duration <= 0:
        sys.exit("[오류] 양수 --duration 필요 (쇼츠 컷합과 같은 길이)")
    out = args.out or args.html.parent / "source-capture.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    total = int(round(args.duration * args.fps))
    print(f"[1/2] 프레임 캡처 — {args.duration:.2f}s × {args.fps}fps = {total}프레임 "
          f"({out_w}x{out_h}, 레이아웃 {design_w}x{design_h}, {CHUNK_SEC:.0f}s 청크 + 워치독)")
    run_chunked(args.html, args.duration, args.fps, out_w, out_h, design_w, design_h, out)
    print(f"[2/2] 완료: {out} ({args.duration:.2f}s, {args.fps}fps, {out_w}x{out_h}, 무음)")


if __name__ == "__main__":
    main()
