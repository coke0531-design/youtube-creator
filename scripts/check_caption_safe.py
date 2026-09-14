"""자막 안전 영역(하단 21vh) 침범 검사 — 레이아웃 게이트 (fail-loud).

왜 스크립트인가:
  "하단 230px 자막 영역 침범 없음"(youtube-editor 체크리스트)은 지금까지 사람 눈 검수에만
  의존했다 — 템플릿의 caption-safe 패딩은 콘텐츠가 가용 높이를 넘으면 뚫린다(flex 가운데
  정렬이 넘침을 위아래로 밀어냄). validate_pipeline은 타임코드만 보고 레이아웃은 못 본다.
  이 검사기가 캡처 전에 슬라이드·스테이지 전수를 헤드리스로 렌더해 픽셀로 강제한다.
  (실증: 풀링_012 S23 인용 슬라이드가 세로로 길어 자막과 겹친 채 완성본까지 나감, 2026-07-27)

무엇을 하나:
  타임라인.json의 slides[](+stages)마다 구간 중간 시점을 ?capture=1 + __capture.seek로 렌더,
  하단 21vh 밴드를 스크린샷 → 흰 배경(그레이 ≥240) 아닌 픽셀 비율을 잰다.
  비율 > 임계(기본 0.30%) = 침범(FAIL). 등장 애니메이션이 끝난 상태(seek 후 대기)를 잰다.

사용:
  python scripts/check_caption_safe.py <타임라인.json>            # 전수 검사 (exit 2 = 침범)
  python scripts/check_caption_safe.py <타임라인.json> --save-dir d  # 침범 밴드 PNG 저장(육안 확인용)
  python scripts/check_caption_safe.py <타임라인.json> --threshold 0.5
"""
import argparse
import json
import pathlib
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

VIEW_W, VIEW_H = 1920, 1080
CAPTION_SAFE_FRAC = 0.21          # 템플릿 --caption-safe: 21vh
WHITE_MIN = 240                   # 이 그레이 값 미만 = 콘텐츠 픽셀 (subtle 틴트/그림자는 240 이상)
DEFAULT_THRESHOLD = 0.30          # 침범 판정 비율(%) — 카드 그림자 번짐 등 미세 노이즈 허용
SETTLE_MS = 1400                  # seek 후 등장 애니메이션(스태거+0.6s) 안정화 대기


def gray_stats(png_bytes: bytes) -> float:
    """PNG 밴드 → 그레이 rawvideo로 디코드해 '흰 배경 아님' 픽셀 비율(%)을 계산 (PIL 불필요)."""
    import imageio_ffmpeg
    p = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        input=png_bytes, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"밴드 디코드 실패: {p.stderr[-300:]}")
    data = p.stdout
    dark = sum(1 for b in data if b < WHITE_MIN)
    return dark / len(data) * 100


def collect_samples(tl: dict) -> list:
    """슬라이드·스테이지별 (라벨, 검사 시점 t) — 시점은 구간 중간, 스테이지는 스테이지 구간 중간."""
    samples = []
    for s in tl.get("slides") or []:
        bounds = [s["start"]] + [g["start"] for g in s.get("stages") or []] + [s["end"]]
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            tag = s["id"] if i == 0 else f"{s['id']}·g{i}"
            samples.append((tag, s.get("label", ""), (a + b) / 2))
    return samples


def run(timeline_path: pathlib.Path, threshold: float, save_dir: pathlib.Path | None) -> list:
    from playwright.sync_api import sync_playwright
    base = timeline_path.resolve().parent
    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    html = (base / tl.get("source_html", "04_영상소스/presentation.html")).resolve()
    if not html.is_file():
        raise SystemExit(f"HTML 없음: {html}")
    samples = collect_samples(tl)
    if not samples:
        raise SystemExit("slides가 비어 있음 — 타임라인.json 확인")

    band_y = round(VIEW_H * (1 - CAPTION_SAFE_FRAC))
    clip = {"x": 0, "y": band_y, "width": VIEW_W, "height": VIEW_H - band_y}
    violations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[f"--window-size={VIEW_W},{VIEW_H}"])
        page = browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=1)
        page.goto(html.as_uri() + "?capture=1")
        page.wait_for_function("window.__capture && window.__capture.ready", timeout=30000)
        for tag, label, t in samples:  # seek는 단조 전진 — collect_samples가 시간순
            page.evaluate("t => window.__capture.seek(t)", t)
            page.wait_for_timeout(SETTLE_MS)
            png = page.screenshot(clip=clip)
            frac = gray_stats(png)
            bad = frac > threshold
            mark = "✗ 침범" if bad else "  ok"
            print(f"{mark}  {tag:<8} t={t:7.2f}s  콘텐츠 픽셀 {frac:6.3f}%  {label}")
            if bad:
                violations.append((tag, t, frac, label))
                if save_dir:
                    save_dir.mkdir(parents=True, exist_ok=True)
                    (save_dir / f"{tag.replace('·','_')}.png").write_bytes(png)
        browser.close()
    return violations


def run_capture(video: pathlib.Path, threshold: float, fps: int = 10) -> list:
    """캡처 결과 전 프레임 검사(2026-09-14, 캔버스 카메라용): 슬라이드 중간 1점이 아니라 capture.mp4 를 fps 로 훑어
    하단 21% 밴드의 비흰색 픽셀 비율이 임계를 넘는 프레임을 전부 잡는다. 카메라가 움직이는 슬라이드는 중간 시점 1점으로는
    침범을 놓칠 수 있다(캡처 후 실행: python scripts/check_caption_safe.py <타임라인.json> --capture)."""
    import imageio_ffmpeg
    w, h = 320, 180
    band = int(h * (1 - CAPTION_SAFE_FRAC))
    p = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"캡처 디코드 실패: {p.stderr[-300:]}")
    data = p.stdout; n = len(data) // (w * h); bad = []
    for i in range(n):
        fr = data[i * w * h:(i + 1) * w * h]
        seg = fr[band * w:]
        dark = sum(1 for b in seg if b < WHITE_MIN)
        frac = dark / len(seg) * 100
        if frac > threshold:
            bad.append((i / fps, frac))
    print(f"[capture] {video.name}: {n}프레임 @{fps}fps 검사, 침범 {len(bad)}프레임")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description="자막 안전 영역(하단 21vh) 침범 검사")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--capture", action="store_true",
                    help="캡처 결과(04_영상소스/capture.mp4) 전 프레임 검사 — 캔버스 카메라 슬라이드가 있으면 캡처 후 필수")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"침범 판정 픽셀 비율 %% (기본 {DEFAULT_THRESHOLD})")
    ap.add_argument("--save-dir", type=pathlib.Path, default=None,
                    help="침범 밴드 PNG 저장 폴더(육안 확인용)")
    args = ap.parse_args()
    if args.capture:
        base = args.timeline.resolve().parent
        cap = base / "04_영상소스" / "capture.mp4"
        if not cap.exists():
            cap = base / "capture.mp4"
        if not cap.exists():
            print("[오류] capture.mp4 없음 — capture_slides.py 로 먼저 캡처"); sys.exit(2)
        bad = run_capture(cap, args.threshold)
        if bad:
            print(f"\n[FAIL] 캡처 전 프레임 자막 안전 영역 침범 {len(bad)}프레임 (처음 12개):")
            for t, frac in bad[:12]:
                print(f"  ✗ t={t:.1f}s ({frac:.3f}%)")
            sys.exit(2)
        print("\n[통과] 캡처 전 프레임 자막 안전 영역 침범 없음")
        return
    violations = run(args.timeline, args.threshold, args.save_dir)
    if violations:
        print(f"\n[FAIL] 자막 안전 영역 침범 {len(violations)}건 — 슬라이드 축소/재배치 후 재검사:")
        for tag, t, frac, label in violations:
            print(f"  ✗ {tag} (t={t:.2f}s, {frac:.3f}%) {label}")
        sys.exit(2)
    print("\n[통과] 전 슬라이드·스테이지 자막 안전 영역 침범 없음")


if __name__ == "__main__":
    main()
