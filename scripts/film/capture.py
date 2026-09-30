# -*- coding: utf-8 -*-
"""필름 HTML → mp4 (결정론 프레임 캡처).

필름 HTML 계약:
  window.FILM = {duration, width:1920, height:1080, fps:30}
  window.seek(t)  : 시간 t(초)의 순수 함수로 화면 전체를 그린다 (Promise 반환도 허용 — await 함)
  window.FILM_READY === true : 폰트 로드 등 준비 완료
  자막은 HTML이 그리지 않는다 (mux.py에서 번인).

방식: Playwright chromium headless(viewport=size, DSF 1) → 프레임마다 seek(t) →
      CDP Page.captureScreenshot(png) → ffmpeg stdin(image2pipe) 스트리밍 인코딩
      (h264_nvenc cq19 → 불가 시 libx264 crf18, yuv420p, bt709 tv-range).

사용:
  python capture.py film.html --out capture.mp4
  python capture.py film.html --out capture.mp4 --start 10 --end 20 --fps 30 --size 1920x1080
  python capture.py film.html --out capture.mp4 --verify-seek 5     # 순방향 2회 + 새 페이지 무작위 순서 픽셀 차 검사

종료 코드: 0 성공 / 1 verify 픽셀 차 발견 또는 인코딩 실패 / 2 입력 오류
"""
import argparse
import base64
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHROME_ARGS = [
    "--force-color-profile=srgb",
    "--disable-gpu-vsync",
    "--disable-lcd-text",
    "--font-render-hinting=none",
    "--hide-scrollbars",
    "--mute-audio",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-partial-raster",
    "--disable-skia-runtime-opts",
    "--run-all-compositor-stages-before-draw",
]

SEEK_JS = """async (t) => { await Promise.resolve(window.seek(t)); return true; }"""


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


def parse_size(s):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except Exception:
        die(f"[입력 오류] --size 형식은 1920x1080: {s}")


def _count_frames(ff, path):
    """ffprobe 없이 ffmpeg으로 프레임 수를 센다(-c copy null 출력의 frame= 값)."""
    p = subprocess.run([ff, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    import re
    m = re.findall(r"frame=\s*(\d+)", p.stderr)
    return int(m[-1]) if m else -1


def nvenc_ok(ff):
    p = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc",
                        "-f", "null", "-"], capture_output=True)
    return p.returncode == 0


def encoder_args(ff, prefer="auto", crf=18):
    """(라벨, argv) — auto: nvenc 시험 인코딩 성공 시 nvenc, 아니면 libx264."""
    use_nv = prefer == "nvenc" or (prefer == "auto" and nvenc_ok(ff))
    if prefer == "nvenc" and not nvenc_ok(ff):
        die("[오류] --encoder nvenc 지정됐지만 h264_nvenc 시험 인코딩 실패")
    if use_nv:
        return "h264_nvenc(cq19)", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                                    "-cq", "19", "-b:v", "0"]
    return f"libx264(crf{crf})", ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]


COLOR_OUT = ["-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
             "-color_primaries", "bt709", "-color_trc", "bt709"]


# ---------------------------------------------------------------- 브라우저
class FilmSession(tuple):
    """(page, cdp, film) 튜플 + reopen(): 같은 브라우저에서 새 페이지를 열어 FILM_READY까지 대기."""
    def __new__(cls, page, cdp, film, reopen):
        obj = super().__new__(cls, (page, cdp, film))
        obj.reopen = reopen
        return obj


def _load_page(browser, html, size, ready_timeout):
    w, h = size
    ctx = browser.new_context(viewport={"width": w, "height": h},
                              device_scale_factor=1, reduced_motion="reduce")
    page = ctx.new_page()
    page.on("pageerror", lambda e: print(f"[페이지 오류] {e}", file=sys.stderr))
    page.goto(html.as_uri(), wait_until="load")
    try:
        page.wait_for_function("window.FILM_READY === true", timeout=int(ready_timeout * 1000))
    except Exception:
        die(f"[입력 오류] {ready_timeout:.0f}초 안에 window.FILM_READY === true 가 되지 않았다")
    film = page.evaluate("() => window.FILM || null")
    has_seek = page.evaluate("() => typeof window.seek === 'function'")
    if not film or not has_seek:
        die("[입력 오류] window.FILM 또는 window.seek(t)가 없다 (필름 HTML 계약 위반)")
    return page, ctx.new_cdp_session(page), film


@contextmanager
def open_film(html, size, ready_timeout=30.0):
    """필름 HTML을 열고 FILM_READY를 기다린다. yield FilmSession(page, cdp, film) — 튜플로 풀어 써도 된다."""
    from playwright.sync_api import sync_playwright
    html = Path(html).resolve()
    if not html.exists():
        die(f"[입력 오류] HTML이 없다: {html}")
    w, h = size
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROME_ARGS)
        try:
            page, cdp, film = _load_page(browser, html, size, ready_timeout)
            if (film.get("width"), film.get("height")) != (w, h):
                print(f"[경고] FILM 크기 {film.get('width')}x{film.get('height')} ≠ 캡처 크기 {w}x{h}")
            yield FilmSession(page, cdp, film,
                              lambda: _load_page(browser, html, size, ready_timeout))
        finally:
            browser.close()


def grab(page, cdp, t, fmt="png"):
    """seek(t) 후 한 장 캡처 → 이미지 바이트."""
    page.evaluate(SEEK_JS, float(t))
    r = cdp.send("Page.captureScreenshot", {"format": fmt, "optimizeForSpeed": True,
                                            "captureBeyondViewport": False, "fromSurface": True})
    return base64.b64decode(r["data"])


def decode_png(b):
    import cv2
    import numpy as np
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_UNCHANGED)


def _diff(a_png, b_png):
    import numpy as np
    a, b = decode_png(a_png), decode_png(b_png)
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    px = d.max(axis=2) if d.ndim == 3 else d
    return int(d.max()), int((px > 0).sum())


def verify_seek(session, t0, t1, fps, n, seed=7):
    """결정론 검사 2종. 검사 시각 = t0, t1-1/fps (항상) + 임의 프레임 시각 (합계 max(n, 2)개, 프레임 격자).
      순방향: 같은 페이지에서 시각 오름차순으로 한 바퀴 → 한 바퀴 더, 두 캡처 비교
      무작위: 같은 브라우저의 새 페이지에서 무작위 순서로 다시 찍어 순방향 1회차와 비교
    """
    page, cdp, _ = session
    rng = random.Random(seed)
    k0, k1 = int(round(t0 * fps)), max(int(round(t0 * fps)), int(round(t1 * fps)) - 1)
    ks = {k0, k1}
    pool = list(range(k0 + 1, k1))
    rng.shuffle(pool)
    for k in pool:
        if len(ks) >= max(n, 2):
            break
        ks.add(k)
    times = [k / fps for k in sorted(ks)]
    first = {t: grab(page, cdp, t) for t in times}
    second = {t: grab(page, cdp, t) for t in times}
    fwd = [{"t": round(t, 4), **dict(zip(("max_diff", "diff_pixels"), _diff(first[t], second[t])))}
           for t in times]
    page2, cdp2, _ = session.reopen()
    order = times[:]
    rng.shuffle(order)
    if len(order) > 1 and order == times:        # 셔플이 우연히 오름차순이면 뒤집는다
        order.reverse()
    third = {t: grab(page2, cdp2, t) for t in order}
    rnd = [{"t": round(t, 4), **dict(zip(("max_diff", "diff_pixels"), _diff(first[t], third[t])))}
           for t in order]
    page2.context.close()
    return fwd, rnd


# ---------------------------------------------------------------- 메인
def main():
    ap = argparse.ArgumentParser(description="필름 HTML(window.FILM + seek(t)) → mp4 결정론 캡처")
    ap.add_argument("html", help="필름 HTML 경로")
    ap.add_argument("--out", required=True, help="출력 mp4")
    ap.add_argument("--fps", type=float, default=None, help="프레임레이트(기본 FILM.fps 또는 30)")
    ap.add_argument("--size", default="1920x1080", help="뷰포트=출력 크기 (기본 1920x1080)")
    ap.add_argument("--start", type=float, default=0.0, help="시작 초(기본 0)")
    ap.add_argument("--end", type=float, default=None, help="끝 초(기본 FILM.duration)")
    ap.add_argument("--verify-seek", type=int, default=0, metavar="N",
                    help="N개 시각(t=0·끝 프레임 포함)을 순방향 2회 + 새 페이지 무작위 순서로 캡처해 픽셀 차 0인지 검사 (<out>.verify.json)")
    ap.add_argument("--encoder", choices=["auto", "nvenc", "x264"], default="auto",
                    help="auto = nvenc 시험 성공 시 nvenc, 아니면 libx264")
    ap.add_argument("--ready-timeout", type=float, default=30.0, help="FILM_READY 대기 상한 초")
    ap.add_argument("--workers", type=int, default=1,
                    help="병렬 워커 수(기본 1). N>1이면 프레임 구간을 N등분해 자식 프로세스로 찍고 concat. "
                         "seek(t)가 순수 함수라는 계약에 기댄다(--verify-seek로 확인). 0은 내부용(자식 표시)")
    args = ap.parse_args()

    size = parse_size(args.size)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = find_ffmpeg()
    enc_label, enc = encoder_args(ff, {"auto": "auto", "nvenc": "nvenc", "x264": "x264"}[args.encoder])

    rc = 0
    t_begin = time.time()
    with open_film(args.html, size, args.ready_timeout) as session:
        page, cdp, film = session
        fps = args.fps or float(film.get("fps") or 30)
        end = args.end if args.end is not None else float(film["duration"])
        if end <= args.start:
            die(f"[입력 오류] end({end}) ≤ start({args.start})")
        n = int(round((end - args.start) * fps))
        print(f"[캡처] {Path(args.html).name}  {args.start:.2f}~{end:.2f}s  {n}프레임 @{fps:g}fps "
              f"{size[0]}x{size[1]}  인코더 {enc_label}")

        if args.verify_seek > 0:
            fwd, rnd = verify_seek(session, args.start, end, fps, args.verify_seek)
            bad_f = [r for r in fwd if r["max_diff"] != 0]
            bad_r = [r for r in rnd if r["max_diff"] != 0]
            rep = {"html": str(Path(args.html).resolve()), "n": len(fwd),
                   "forward": {"ok": not bad_f, "bad": len(bad_f), "samples": fwd},
                   "random_new_page": {"ok": not bad_r, "bad": len(bad_r), "order": [r["t"] for r in rnd],
                                       "samples": rnd}}
            vpath = out.with_suffix(".verify.json")
            vpath.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
            for name, rows in (("순방향", fwd), ("무작위(새 페이지)", rnd)):
                for r in rows:
                    print(f"  [{name}] t={r['t']:.4f}s  max_diff={r['max_diff']}  diff_pixels={r['diff_pixels']}")
            print(f"[verify-seek] {len(fwd)}개 시각 · 순방향 {'OK' if not bad_f else f'FAIL {len(bad_f)}'} / "
                  f"무작위 {'OK' if not bad_r else f'FAIL {len(bad_r)}'}  ({vpath.name})")
            if bad_f or bad_r:
                rc = 1

        holds = film.get("holds")
        if isinstance(holds, list) and holds and args.workers != 0:
            hpath = out.with_suffix(".holds.json")
            hpath.write_text(json.dumps({"holds": holds}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[holds] FILM.holds {len(holds)}구간 → {hpath.name} (still_ratio.py --holds 용)")

        if args.workers > 1 and n >= args.workers * 2:
            # 병렬: 프레임 구간을 워커 수만큼 잘라 자식 프로세스(capture.py --workers 0)로 찍고 concat(-c copy)
            k0 = int(round(args.start * fps))
            bounds = [k0 + (n * i) // args.workers for i in range(args.workers + 1)]
            tmpdir = Path(tempfile.mkdtemp(prefix="cap_", dir=str(out.parent)))
            procs, chunks = [], []
            for i in range(args.workers):
                cpath = tmpdir / f"chunk_{i:02d}.mp4"
                chunks.append(cpath)
                cmd = [sys.executable, str(Path(__file__).resolve()), str(Path(args.html).resolve()),
                       "--out", str(cpath), "--fps", f"{fps:g}", "--size", f"{size[0]}x{size[1]}",
                       "--start", repr(bounds[i] / fps), "--end", repr(bounds[i + 1] / fps),
                       "--encoder", args.encoder, "--ready-timeout", str(args.ready_timeout), "--workers", "0"]
                logf = open(tmpdir / f"chunk_{i:02d}.log", "wb")
                procs.append((subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT), logf))
            print(f"[병렬] 워커 {args.workers}개 · 청크 프레임 {[bounds[i + 1] - bounds[i] for i in range(args.workers)]}")
            t_cap = time.time()
            failed = False
            for i, (p, logf) in enumerate(procs):
                p.wait()
                logf.close()
                tail = (tmpdir / f"chunk_{i:02d}.log").read_text("utf-8", "replace").strip().splitlines()
                if p.returncode != 0:
                    failed = True
                    print(f"[실패] 워커 {i} rc={p.returncode}: {' | '.join(tail[-3:])}", file=sys.stderr)
                elif tail:
                    print(f"  워커 {i}: {tail[-1]}")
            for i, cpath in enumerate(chunks):   # 워커가 rc 0으로 죽어도 파일이 없거나 프레임이 모자라면 실패 처리 (H3 실측)
                exp = bounds[i + 1] - bounds[i]
                got = _count_frames(ff, cpath) if cpath.exists() else -1
                if got != exp:
                    failed = True
                    print(f"[실패] 워커 {i} 청크 프레임 {got} ≠ {exp} ({cpath.name})", file=sys.stderr)
            if failed:
                return 1
            lst = tmpdir / "concat.txt"
            lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in chunks), encoding="utf-8")
            p = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                                "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)],
                               capture_output=True)
            if p.returncode != 0:
                print(f"[실패] concat rc={p.returncode}: {p.stderr.decode('utf-8', 'replace')[-600:]}", file=sys.stderr)
                return 1
            shutil.rmtree(tmpdir, ignore_errors=True)
            cap_sec = time.time() - t_cap
            total = time.time() - t_begin
            print(f"[완료] {out}  {n}프레임  병렬 캡처+인코딩 {cap_sec:.1f}s ({n / cap_sec:.1f} fps)  전체 {total:.1f}s")
            return rc

        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "image2pipe", "-framerate", f"{fps:g}", "-c:v", "png", "-i", "-",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
               *enc, *COLOR_OUT, "-r", f"{fps:g}", "-movflags", "+faststart", str(out)]
        errf = tempfile.TemporaryFile()
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf)
        t_cap = time.time()
        last_log = t_cap
        try:
            for k in range(n):
                t = args.start + k / fps
                proc.stdin.write(grab(page, cdp, t))
                now = time.time()
                if now - last_log >= 10:
                    done = k + 1
                    rate = done / (now - t_cap)
                    print(f"  {done}/{n} ({done / n * 100:.0f}%)  {rate:.1f} fps  "
                          f"남은 ~{(n - done) / rate:.0f}s", flush=True)
                    last_log = now
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        proc.wait()
        errf.seek(0)
        err = errf.read().decode("utf-8", "replace").strip()
        errf.close()
        if proc.returncode != 0:
            print(f"[실패] ffmpeg rc={proc.returncode}: {err[-800:]}", file=sys.stderr)
            return 1
        cap_sec = time.time() - t_cap

    total = time.time() - t_begin
    print(f"[완료] {out}  {n}프레임  캡처+인코딩 {cap_sec:.1f}s ({n / cap_sec:.1f} fps)  전체 {total:.1f}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
