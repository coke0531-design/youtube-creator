"""HTML 슬라이드(동기화 오토플레이)를 헤드리스 브라우저로 녹화해 mp4를 만든다.

전제: HTML이 캡처 모드(?capture=1 → window.__capture)를 지원해야 한다 (템플릿 보일러플레이트 내장).
출력 mp4는 t=0(커버가 사라지는 프레임)부터 시작하므로 오디오·SRT와 타임베이스가 일치한다.

캡처 모드 2가지:
  frames (기본) — 결정론적 프레임 단위 캡처. BeginFrame 제어(--enable-begin-frame-control) +
    CDP 가상시간으로 시간을 1/fps씩 전진시키고, 프레임마다 ① window.__capture.seek(t)로 덱 상태를
    직접 구동(시계 무관) ② HeadlessExperimental.beginFrame이 합성+스크린샷을 한 번에 수행 →
    ffmpeg 파이프 인코딩. 고정 fps(기본 30) + 고해상도(기본 2560x1440), 프레임 드랍 없음.
    레이아웃은 디자인 기준 해상도(1920x1080)로 유지하고 deviceScaleFactor로 픽셀만 키운다(요소 비율 불변).
    t=0이 프레임 0이라 blackdetect 불필요. 소요 시간은 실시간과 무관 (6분 영상 ≈ 10~15분).
    ⚠️ HTML에 __capture.seek가 있어야 한다 (템플릿 보일러플레이트 내장 — 구버전 HTML이면 realtime 사용).
  realtime — 구 방식(Playwright record_video 스크린캐스트). VFR·저화질이라 비권장, 폴백용.

사용:
  python capture_slides.py <presentation.html> --timeline <타임라인.json>          # 권장
  python capture_slides.py <presentation.html> --duration 378.1 [--fps 30]
                           [--out capture.mp4] [--size 2560x1440] [--mode frames|realtime]
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

# 한국어 Windows: 파이프/콘솔이 cp949면 — 등 특수문자 출력에서 UnicodeEncodeError로 죽는다.
# trim_silence.py와 동일한 UTF-8 고정 (2026-07-15 백그라운드 실행에서 실증된 크래시 수리).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
COVER_SEC = 1.0  # realtime 모드: 시작 전 검정 커버 확보 시간 (blackdetect로 t=0 검출 기준)
TAIL_SEC = 1.0   # realtime 모드: 타임라인 종료 후 여유

# 디자인 기준 해상도 — CSS 레이아웃은 항상 이 크기로 계산하고 DSF로 픽셀만 키운다
DESIGN = {"main": (1920, 1080), "short": (1080, 1920)}
DEFAULT_OUT_SIZE = {"main": "2560x1440", "short": "1440x2560"}


# ---------- frames 모드 (BeginFrame 제어 + 가상시간 + seek — 기본) ----------
# 핵심 설계:
# - 덱 전환은 __capture.seek(t)로 파이썬이 직접 구동 → rAF/performance.now 시계 어긋남과 무관하게 정확
# - CSS 트랜지션/애니메이션·setTimeout은 가상시간을 따라 1/fps씩 자연스럽게 진행
# - HeadlessExperimental.beginFrame이 프레임 합성과 스크린샷을 원자적으로 수행 (프레임 드랍 없음)
# - page.screenshot()은 쓰지 않는다 — 내부 rAF 안정화 대기가 가상시간 정지와 데드락 + 강제 BeginFrame이 시계를 오염

CHUNK_SEC = 60.0    # 청크 길이 — beginFrame이 장시간 실행 중 간헐 데드락 → 청크별 새 브라우저 + 워치독
PREROLL_SEC = 4.0   # 청크 시작 전 렌더만 하고 버리는 구간 (등장 트랜지션·카운터·도넛 애니메이션 정착용)


def record_frames_range(html: pathlib.Path, t_a: float, t_b: float, fps: int,
                        out_w: int, out_h: int, design_w: int, design_h: int,
                        out: pathlib.Path) -> None:
    """[t_a, t_b) 구간을 프레임 단위로 캡처해 세그먼트 mp4 저장. 앞 PREROLL은 렌더만 하고 버린다."""
    import base64

    if abs(out_w / out_h - design_w / design_h) > 0.01:
        sys.exit(f"[오류] 출력 비율({out_w}x{out_h})이 디자인 비율({design_w}x{design_h})과 다릅니다")
    dsf = out_w / design_w
    step_ms = 1000.0 / fps
    k_first = int(round(t_a * fps))                       # 기록 시작 프레임 (전역 인덱스)
    k_pre = max(0, int(round((t_a - PREROLL_SEC) * fps)))  # 렌더 시작 프레임
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
            # beginFrame 스크린샷은 컴포지터 서피스(물리 픽셀) 기준 — 전역 DSF + 창 크기를 출력 해상도에
            # 맞춰야 고해상도가 나온다 (context의 device_scale_factor만으로는 서피스가 CSS px에 머문다)
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
        # 무손상(damage 없음) 프레임에서 beginFrame이 웨지되는 Chromium 데드락 회피:
        # 좌상단 2px 픽셀을 매 프레임 #fffffe↔#ffffff로 토글해 항상 damage를 만든다
        # (실측: 정적 구간 진입 프레임에서 행 재현 → 토글 적용 후 해소. 출력에는 식별 불가)
        page.evaluate(
            "const d = document.createElement('div'); d.id = '__capture_dmg';"
            "d.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;"
            "background:#fffffe;z-index:99999;pointer-events:none';"
            "document.body.appendChild(d);")
        for _ in range(3):  # 렌더 워밍업
            client.send("HeadlessExperimental.beginFrame", {})

        expired = {"flag": False}
        client.on("Emulation.virtualTimeBudgetExpired",
                  lambda _: expired.__setitem__("flag", True))
        client.send("Emulation.setVirtualTimePolicy", {"policy": "pause"})

        last = None
        for k in range(k_pre, k_end):
            # 덱 상태 = t (시계 무관) + damage 토글 (한 호출로 합쳐 CDP 왕복 최소화)
            page.evaluate(
                f"window.__capture.seek({k / fps:.4f});"
                f"document.getElementById('__capture_dmg').style.background = {k} % 2 ? '#fffffe' : '#ffffff'")
            r = client.send("HeadlessExperimental.beginFrame",
                            {"screenshot": {"format": "jpeg", "quality": 93}})
            data = r.get("screenshotData")
            if data:
                last = base64.b64decode(data)
            elif last is None:
                sys.exit(f"[오류] 프레임 {k}: beginFrame 스크린샷 실패 (첫 프레임)")
            # 화면 변화가 없으면 스크린샷이 생략될 수 있음 → 직전 프레임 재사용 (정적 구간)
            if k >= k_first:
                enc.stdin.write(last)
            expired["flag"] = False
            client.send("Emulation.setVirtualTimePolicy",
                        {"policy": "advance", "budget": step_ms})
            while not expired["flag"]:
                page.wait_for_timeout(2)  # 이벤트 루프 펌프
            if k % 300 == 0:
                print(f"      seg frame {k}/{k_end}", flush=True)  # 워치독 활동 신호
        browser.close()
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("[오류] ffmpeg 인코딩 실패")


def run_frames_chunked(html: pathlib.Path, duration: float, fps: int,
                       out_w: int, out_h: int, kind: str, out: pathlib.Path) -> None:
    """청크 단위 자식 프로세스 + 워치독으로 전체를 캡처하고 무손실 concat한다."""
    segdir = out.parent / "_capture_segs"
    segdir.mkdir(exist_ok=True)
    bounds = []
    a = 0.0
    while a < duration:
        bounds.append((a, min(a + CHUNK_SEC, duration)))
        a += CHUNK_SEC

    t_run = time.monotonic()
    segs = []
    for n, (a, b) in enumerate(bounds, 1):
        seg = segdir / f"seg_{n:03d}.mp4"
        frames = int(round((b - a + PREROLL_SEC) * fps))
        budget = 120 + frames // 4  # 최소 4fps 가정한 워치독 (60s 청크 ≈ 600s 한도)
        ok = False
        for attempt in (1, 2, 3):
            print(f"[청크 {n}/{len(bounds)}] {a:.1f}–{b:.1f}s (시도 {attempt}) — 한도 {budget}s", flush=True)
            cmd = [sys.executable, "-u", str(pathlib.Path(__file__).resolve()), str(html),
                   "--_chunk", f"{a:.4f}", f"{b:.4f}", "--_kind", kind,
                   "--fps", str(fps), "--size", f"{out_w}x{out_h}", "--out", str(seg)]
            # 자식 출력은 청크 로그로 보존 — 실패 시 진단 단서 (성공 시 segdir와 함께 삭제됨)
            with open(seg.with_suffix(f".try{attempt}.log"), "wb") as log_f:
                proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
                try:
                    rc = proc.wait(timeout=budget)
                except subprocess.TimeoutExpired:
                    # 자식 + 고아 브라우저까지 트리째 종료
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

    lst = segdir / "concat.txt"
    lst.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], capture_output=True)
    if r.returncode != 0:
        sys.exit("[오류] 세그먼트 concat 실패:\n" + r.stderr.decode("utf-8", "replace")[-800:])
    shutil.rmtree(segdir, ignore_errors=True)
    print(f"      전체 {len(segs)}청크, {(time.monotonic() - t_run) / 60:.1f}분 소요", flush=True)


# ---------- realtime 모드 (구 방식 — 폴백) ----------

def record_webm(html: pathlib.Path, duration: float, width: int, height: int, workdir: str) -> pathlib.Path:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=workdir,
            record_video_size={"width": width, "height": height},
        )
        page = ctx.new_page()
        page.goto(html.resolve().as_uri() + "?capture=1")
        page.wait_for_function("window.__capture && window.__capture.ready", timeout=60_000)
        page.wait_for_timeout(COVER_SEC * 1000)    # 검정 커버 프레임 녹화
        page.evaluate("window.__capture.start()")  # 이 순간 커버 제거 = t=0
        page.wait_for_timeout((duration + TAIL_SEC) * 1000)
        video = page.video
        ctx.close()  # 녹화 파일 확정
        path = pathlib.Path(video.path())
        browser.close()
    return path


def detect_t0(webm: pathlib.Path) -> float:
    """녹화 앞부분의 검정 커버 구간 끝 = 슬라이드 t=0."""
    r = subprocess.run(
        [FFMPEG, "-i", str(webm), "-vf", "blackdetect=d=0.3:pix_th=0.10", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    for m in re.finditer(r"black_start:(\d+\.?\d*).*?black_end:(\d+\.?\d*)", r.stderr):
        start, end = float(m.group(1)), float(m.group(2))
        if start < 5.0:  # 영상 앞부분의 커버 구간만 인정
            return end
    detail = "\n".join(l for l in r.stderr.splitlines() if "black" in l) or "(blackdetect 출력 없음)"
    sys.exit("[오류] 검정 커버 구간을 찾지 못했습니다 — HTML이 캡처 모드(?capture=1)를 지원하는지 확인하세요.\n" + detail)


def trim_to_mp4(webm: pathlib.Path, t0: float, duration: float, fps: int, out: pathlib.Path) -> None:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(webm), "-ss", f"{t0:.3f}", "-t", f"{duration:.3f}",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-r", str(fps), "-an", str(out)],
        check=True, capture_output=True,
    )


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="HTML 슬라이드 헤드리스 녹화 → mp4")
    ap.add_argument("html", type=pathlib.Path)
    ap.add_argument("--duration", type=float, help="녹화 길이(초). --timeline 없을 때 필수")
    ap.add_argument("--timeline", type=pathlib.Path, help="타임라인.json — duration·type(해상도)을 읽음")
    ap.add_argument("--out", type=pathlib.Path, help="출력 mp4 (기본: HTML 옆 capture.mp4)")
    ap.add_argument("--size", default=None, help="출력 WxH (기본: 본편 2560x1440, 쇼츠 1440x2560)")
    ap.add_argument("--fps", type=int, default=30, help="프레임레이트 (기본 30)")
    ap.add_argument("--mode", choices=["frames", "realtime"], default="frames",
                    help="frames=가상시간 프레임 캡처(기본·고품질), realtime=스크린캐스트(폴백)")
    ap.add_argument("--skip-layout-check", action="store_true",
                    help="레이아웃 게이트(check_layout.py: 잘림·겹침·과밀·정렬) 생략 — 진단용, 완성본 경로에서는 쓰지 않는다")
    ap.add_argument("--skip-caption-check", action="store_true",
                    help="자막 안전 영역 게이트 생략(의도적 침범 연출 등 예외 시에만)")
    ap.add_argument("--_chunk", nargs=2, type=float, metavar=("A", "B"),
                    help=argparse.SUPPRESS)  # 내부용: 청크 자식 프로세스 모드
    ap.add_argument("--_kind", choices=["main", "short"], default="main", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not args.html.is_file():
        sys.exit(f"[오류] HTML 없음: {args.html}")

    # 청크 자식 모드: [A, B) 구간만 캡처하고 종료 (run_frames_chunked가 호출)
    if args._chunk:
        m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", (args.size or "").lower())
        if not m:
            sys.exit("[오류] 청크 모드는 --size 필수")
        dw, dh = DESIGN[args._kind]
        record_frames_range(args.html, args._chunk[0], args._chunk[1], args.fps,
                            int(m.group(1)), int(m.group(2)), dw, dh, args.out)
        return

    duration, kind = args.duration, "main"
    if args.timeline:
        tl = json.loads(args.timeline.read_text(encoding="utf-8"))
        duration = duration or float(tl["duration"])
        kind = tl.get("type", "main")
        # 싱크 계약 게이트 — 캡처는 영상을 굽는 단계라 불일치를 여기서 막아야 한다 (fail-loud)
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        try:
            import validate_pipeline
        except ImportError as ex:
            sys.exit(f"[오류] validate_pipeline.py 로드 실패 — 싱크 검증 없이 캡처하지 않습니다: {ex}")
        v_errors = validate_pipeline.run(args.timeline, media=True, skip_capture=True)
        if v_errors:
            for e in v_errors:
                print(f"  ✗ {e}", file=sys.stderr)
            sys.exit(f"[중단] 싱크 계약 위반 {len(v_errors)}건 — 해소 후 재캡처 (scripts/validate_pipeline.py)")
        # 레이아웃 게이트 — 자막 안전 영역(하단 21vh) 침범을 캡처 전에 픽셀로 강제 (본편 16:9 한정).
        # 근거: 풀링_012에서 세로로 긴 슬라이드가 caption-safe 패딩을 뚫고 자막과 겹친 채 완성본까지
        # 나감(2026-07-27) — validate_pipeline은 타임코드만 보고 레이아웃은 못 본다.
        if kind == "main" and not args.skip_caption_check:
            try:
                import check_caption_safe
            except ImportError as ex:
                sys.exit(f"[오류] check_caption_safe.py 로드 실패 — 레이아웃 검증 없이 캡처하지 않습니다: {ex}")
            print("[게이트] 자막 안전 영역 검사 (check_caption_safe) …")
            c_violations = check_caption_safe.run(args.timeline, check_caption_safe.DEFAULT_THRESHOLD, None)
            if c_violations:
                for tag, t, frac, label in c_violations:
                    print(f"  ✗ {tag} (t={t:.2f}s, {frac:.3f}%) {label}", file=sys.stderr)
                sys.exit(f"[중단] 자막 안전 영역 침범 {len(c_violations)}건 — 슬라이드 축소/재배치 후 재캡처 "
                         "(scripts/check_caption_safe.py, 우회는 --skip-caption-check)")
        # 레이아웃 게이트 2 — 잘림·겹침·과밀·정렬을 DOM 실측으로 캡처 전에 강제 (본편 16:9 한정, 2026-09-14).
        # 근거: 풀링013 1분 비교에서 오너 지적 3건(겹침·과밀·정렬)을 기존 게이트가 하나도 못 봤다.
        if kind == "main" and not args.skip_layout_check:
            try:
                import check_layout
            except ImportError as ex:
                sys.exit(f"[오류] check_layout.py 로드 실패 — 레이아웃 게이트 없이 캡처하지 않습니다: {ex}")
            print("[게이트] 레이아웃 실측 검사 (check_layout: 잘림·겹침·과밀·정렬) …")
            l_found, l_counts, l_maxu, l_times, l_skipped = check_layout.run(args.html, args.timeline)
            l_text, l_verdict = check_layout.format_report(args.html, l_found, l_counts, l_maxu, l_times, l_skipped, 0.2, 8)
            if l_found:
                print(l_text, file=sys.stderr)
                sys.exit(f"[중단] 레이아웃 위반 {sum(l_counts.values())}건 — 장면 좌표·카메라 프레임을 고친 뒤 재캡처 "
                         "(scripts/check_layout.py, 우회는 --skip-layout-check)")
            print(f"  통과 — 검사 시각 {len(l_times)}개, 슬라이드별 최대 도형 단위 " + ", ".join(f"{k} {v[0]}" for k, v in sorted(l_maxu.items())))
    if duration is None or duration <= 0:
        sys.exit("[오류] 양수 duration 필요 — --duration 또는 --timeline(duration 포함) 지정")

    size = args.size or DEFAULT_OUT_SIZE[kind]
    m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", size.lower())
    if not m:
        sys.exit(f"[오류] --size 형식은 WxH (예: 2560x1440): {size}")
    width, height = int(m.group(1)), int(m.group(2))
    design_w, design_h = DESIGN[kind]
    out = args.out or args.html.parent / "capture.mp4"

    if args.mode == "frames":
        total = int(round(duration * args.fps))
        print(f"[1/2] 프레임 캡처 시작 — {duration:.1f}s × {args.fps}fps = {total}프레임 "
              f"({width}x{height}, 레이아웃 {design_w}x{design_h}, {CHUNK_SEC:.0f}s 청크 + 워치독)")
        run_frames_chunked(args.html, duration, args.fps, width, height, kind, out)
        print(f"[2/2] 완료: {out} ({duration:.1f}s, {args.fps}fps, {width}x{height})")
        # 캔버스 카메라 슬라이드(.slide--canvas)는 padding 기반 자막 안전영역 방어가 없고 카메라가 움직이므로,
        # 구간 중간 1점 검사로는 부족하다 → 캡처 결과 전 프레임을 다시 검사한다(2026-09-14, C2).
        has_canvas = re.search(r'<section[^>]*class="[^"]*\bslide--canvas\b', args.html.read_text(encoding="utf-8", errors="ignore"))
        if kind == "main" and not args.skip_caption_check and has_canvas:
            import check_caption_safe
            print("[게이트] 캔버스 카메라 감지 — 캡처 전 프레임 자막 안전 영역 검사 (check_caption_safe --capture) …")
            bad = check_caption_safe.run_capture(out, check_caption_safe.DEFAULT_THRESHOLD)
            if bad:
                for t, frac in bad[:12]:
                    print(f"  ✗ t={t:.1f}s ({frac:.3f}%)", file=sys.stderr)
                sys.exit(f"[중단] 캡처 전 프레임 자막 안전 영역 침범 {len(bad)}프레임 — 캔버스 카메라 프레임을 고친 뒤 재캡처 "
                         "(capture.mp4 는 진단용으로 남겨 둠, 우회는 --skip-caption-check)")
            print("  통과 — 침범 0프레임")
        return

    workdir = tempfile.mkdtemp(prefix="capture_")
    try:
        print(f"[1/3] (realtime) 녹화 시작 — {duration:.1f}s 실시간 소요 ({width}x{height})")
        webm = record_webm(args.html, duration, width, height, workdir)
        print("[2/3] t=0 프레임 검출 (blackdetect)")
        t0 = detect_t0(webm)
        print(f"      t0 = {t0:.3f}s → 트림 + mp4 인코딩")
        trim_to_mp4(webm, t0, duration, args.fps, out)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"[3/3] 완료: {out} ({duration:.1f}s)")


if __name__ == "__main__":
    main()
