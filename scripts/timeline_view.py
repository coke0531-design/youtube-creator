# -*- coding: utf-8 -*-
"""시간 구간 시각 드릴다운 — [start,end] 한 구간을 PNG 한 장 + JSON 사이드카로 펼친다.

아이디어 출처: browser-use/video-use `helpers/timeline_view.py` (MIT) — 이 파이프라인
(타임라인.json + capture.mp4 + transcript.json)에 맞게 개작.

왜 스크립트인가
  check_motion.py는 "S03이 WARN"까지만 알려준다. 원인(정지 화면인가·나레이션 갭인가·
  컷 경계가 어긋났나)은 그 구간을 눈으로 봐야 갈린다. 매번 ffmpeg를 손으로 두드리는
  대신 한 번의 호출로 같은 x축(시간) 위에 프레임·차분·파형·단어·경계를 겹쳐 본다.

무엇을 하나
  1) 필름스트립  : [start,end] 등간격 --frames장 (ffmpeg -ss 정확 시킹, 프레임당 1회 호출)
  2) 프레임 차분 : check_motion과 같은 방식(gray 10fps rawvideo)의 인접 프레임 평균 절대차
  3) 파형        : 오디오 구간을 s16le/8kHz 모노로 디코드 → 열별 peak 엔벌로프
  4) 단어 라벨   : transcript words + 갭(≥--gap) 앰버 밴드
  5) 경계선      : 타임라인.json slides[].start(잉크 실선) / video_overlays[](그린 점선)
  숫자는 전부 JSON 사이드카 + stdout 요약으로도 나간다 (그림만 남기지 않는다).

사용
  python scripts/timeline_view.py "결과물/2026-08-27_E2E_..." 10 16
  python scripts/timeline_view.py <작업폴더>/타임라인.json 0 6 --frames 8
  python scripts/timeline_view.py <작업폴더> 30 40 --video 완성본/final.mp4
  옵션: --video --audio --transcript --frames 12 --width 1600 --gap 0.4 --out --font

종료 코드: 0 = 성공, 2 = 입력 오류(파일 없음·범위 오류·ffmpeg 실패)
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FFMPEG_TIMEOUT = 60      # 호출당 상한(초) — 프레임 1장·짧은 구간 디코드라 60s면 충분
SAMPLE_FPS = 10          # 차분 해상도 (check_motion.py와 동일)
DIFF_WIDTH = 160         # 차분용 분석 폭
AUDIO_SR = 8000          # 파형 디코드 샘플레이트

INK = (20, 20, 19)
AMBER = (245, 158, 11)
GREEN = (22, 163, 74)
GRAY = (140, 140, 138)
LIGHT = (225, 225, 222)
BG = (255, 255, 255)
BAND = (253, 235, 200)   # 갭 밴드(연한 앰버)

PAD_L, PAD_R, PAD_T, PAD_B = 56, 24, 10, 10
H_HEADER = 34
H_STRIP_LABEL = 15
H_DIFF = 60
H_WAVE = 120
H_WORD_TIER = 19
WORD_TIERS = 3
H_AXIS = 26
ROW_GAP = 12

FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def die(msg: str):
    """입력 오류 종료 — exit 2 (fail-loud)."""
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


def run_ff(cmd, what: str, timeout=FFMPEG_TIMEOUT):
    """ffmpeg 1회 호출 — rc≠0/타임아웃은 조용히 넘기지 않고 exit 2."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        die(f"[측정 실패] {what}: ffmpeg가 {timeout}s 안에 끝나지 않았다")
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()[-500:]
        die(f"[측정 실패] {what}: ffmpeg rc={p.returncode} {err}")
    return p.stdout


def probe(ffmpeg: str, path: Path):
    """(duration, (w,h), has_audio) — ffmpeg -i의 stderr 파싱 (ffprobe 비의존)."""
    p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = p.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
    if not m:
        die(f"[입력 오류] 미디어 길이를 읽지 못했다: {path}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    vm = re.search(r"Stream #\d+:\d+.*?: Video:.*?,\s*(\d+)x(\d+)", txt)
    size = (int(vm.group(1)), int(vm.group(2))) if vm else (None, None)
    has_audio = re.search(r"Stream #\d+:\d+.*?: Audio:", txt) is not None
    return dur, size, has_audio


# ------------------------------------------------------------------ 추출
def grab_frames(ffmpeg: str, video: Path, times):
    """-ss를 -i 앞에 둔 정확 시킹으로 프레임당 1회 호출 → PIL Image 리스트."""
    from PIL import Image
    import io
    out = []
    for t in times:
        buf = run_ff([ffmpeg, "-hide_banner", "-loglevel", "error",
                      "-ss", f"{t:.3f}", "-i", str(video),
                      "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                     f"프레임 추출 t={t:.2f}s")
        if not buf:
            die(f"[측정 실패] 프레임이 비었다 (t={t:.2f}s, 영상 범위를 벗어났는가?): {video}")
        out.append(Image.open(io.BytesIO(buf)).convert("RGB"))
    return out


def diff_series(ffmpeg: str, video: Path, start: float, dur: float, src_size):
    """구간을 gray 10fps rawvideo로 뽑아 인접 프레임 평균 절대차 d1 = [(t, d)]."""
    import numpy as np
    sw, sh = src_size
    height = max(2, int(round(DIFF_WIDTH * sh / sw / 2)) * 2) if (sw and sh) else 90
    fb = DIFF_WIDTH * height
    raw = run_ff([ffmpeg, "-hide_banner", "-loglevel", "error",
                  "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{dur:.3f}",
                  "-vf", f"fps={SAMPLE_FPS},scale={DIFF_WIDTH}:{height}",
                  "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                 "프레임 차분 추출", timeout=max(FFMPEG_TIMEOUT, int(dur) + 60))
    n = len(raw) // fb
    if n < 2:
        die(f"[측정 실패] 차분용 프레임이 {n}장뿐이다 — 구간이 너무 짧거나 영상 밖: {video}")
    arr = np.frombuffer(raw[:n * fb], dtype=np.uint8).reshape(n, fb).astype(np.int16)
    d = np.abs(np.diff(arr, axis=0)).mean(axis=1)
    return [(start + (k + 1) / SAMPLE_FPS, float(v)) for k, v in enumerate(d)]


def audio_samples(ffmpeg: str, audio: Path, start: float, dur: float):
    import numpy as np
    raw = run_ff([ffmpeg, "-hide_banner", "-loglevel", "error",
                  "-ss", f"{start:.3f}", "-i", str(audio), "-t", f"{dur:.3f}",
                  "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1",
                  "-ar", str(AUDIO_SR), "-"],
                 "오디오 디코드", timeout=max(FFMPEG_TIMEOUT, int(dur) + 60))
    if len(raw) < 4:
        die(f"[측정 실패] 오디오 샘플이 비었다 (구간이 파일 밖인가?): {audio}")
    return np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


# ------------------------------------------------------------------ 입력 해석
def resolve(args):
    target = Path(args.target)
    if target.is_dir():
        root, tl_path = target, target / "타임라인.json"
    elif target.is_file():
        root, tl_path = target.parent, target
    else:
        die(f"[입력 오류] 작업 폴더도 파일도 아니다: {target}")
    if not tl_path.is_file():
        die(f"[입력 오류] 타임라인.json이 없다: {tl_path}")
    try:
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
    except Exception as ex:
        die(f"[입력 오류] 타임라인.json 파싱 실패: {tl_path} — {ex}")

    def rel(p):
        p = Path(p)
        return p if p.is_absolute() else (root / p)

    video = rel(args.video) if args.video else (root / "04_영상소스" / "capture.mp4")
    if not video.is_file():
        die(f"[입력 오류] 영상이 없다: {video}")

    kind = tl.get("type", "main")
    audio = None
    if args.audio:
        audio = rel(args.audio)
        if not audio.is_file():
            die(f"[입력 오류] 오디오가 없다: {audio}")
    else:
        key = "audio" if kind == "main" else "audio_source"
        if tl.get(key):
            cand = rel(tl[key])
            if cand.is_file():
                audio = cand

    transcript = None
    tr_arg = args.transcript or tl.get("transcript")
    if args.transcript:
        transcript = rel(args.transcript)
        if not transcript.is_file():
            die(f"[입력 오류] transcript가 없다: {transcript}")
    elif tr_arg:
        cand = rel(tr_arg)
        transcript = cand if cand.is_file() else None
    if transcript is None:
        cand = root / "03_자막" / "transcript.json"
        transcript = cand if cand.is_file() else None
    return root, tl_path, tl, video, audio, transcript


def load_words(path: Path):
    if path is None:
        return []
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        die(f"[입력 오류] transcript 파싱 실패: {path} — {ex}")
    words = d.get("words") if isinstance(d, dict) else d
    if not isinstance(words, list):
        die(f"[입력 오류] transcript에 words 배열이 없다: {path}")
    out = []
    for w in words:
        try:
            out.append({"word": str(w["word"]), "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def pick_font(user_font):
    """한글 렌더용 TTF 탐색. 못 찾으면 (None, None) — 단어는 인덱스 번호로 대체(유일한 폴백)."""
    from PIL import ImageFont
    cands = ([user_font] if user_font else []) + FONT_CANDIDATES
    for c in cands:
        if c and Path(c).is_file():
            try:
                return c, ImageFont.truetype(c, 12)
            except Exception:
                continue
    if user_font:
        die(f"[입력 오류] --font 파일을 열 수 없다: {user_font}")
    return None, None


# ------------------------------------------------------------------ 그리기
def main():
    ap = argparse.ArgumentParser(description="시간 구간 시각 드릴다운 (필름스트립+차분+파형+단어+경계)")
    ap.add_argument("target", help="작업 폴더 또는 타임라인.json 경로")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--video", help="영상 경로 (기본 04_영상소스/capture.mp4)")
    ap.add_argument("--audio", help="오디오 경로 (기본 타임라인.json audio)")
    ap.add_argument("--transcript", help="transcript.json 경로")
    ap.add_argument("--frames", type=int, default=12, help="필름스트립 샘플 수(기본 12)")
    ap.add_argument("--width", type=int, default=1600, help="PNG 폭(기본 1600)")
    ap.add_argument("--gap", type=float, default=0.4, help="나레이션 갭 임계 초(기본 0.4)")
    ap.add_argument("--out", help="PNG 출력 경로 (JSON은 같은 이름 .json)")
    ap.add_argument("--font", help="한글 TTF 경로")
    args = ap.parse_args()

    start, end = float(args.start), float(args.end)
    if not (end > start):
        die(f"[입력 오류] 범위가 뒤집혔다: start={start} end={end} (end > start 여야 한다)")
    if start < 0:
        die(f"[입력 오류] start는 0 이상이어야 한다: {start}")
    if args.frames < 2:
        die(f"[입력 오류] --frames는 2 이상이어야 한다: {args.frames}")
    if args.width < 600:
        die(f"[입력 오류] --width는 600 이상이어야 한다: {args.width}")

    root, tl_path, tl, video, audio, transcript = resolve(args)
    ffmpeg = find_ffmpeg()
    vdur, vsize, v_has_audio = probe(ffmpeg, video)
    if start >= vdur:
        die(f"[입력 오류] start={start:.2f}s가 영상 길이({vdur:.2f}s) 밖이다: {video}")
    if end > vdur:
        print(f"[알림] end={end:.2f}s가 영상 길이 {vdur:.2f}s를 넘어 잘라 맞춘다", file=sys.stderr)
        end = vdur
        if not (end > start):
            die("[입력 오류] 자르고 나니 구간이 비었다")
    dur = end - start

    # --audio 미지정 + 영상 자체에 오디오 스트림이 있으면 영상 오디오를 쓴다(완성본/final.mp4 케이스)
    if audio is None and v_has_audio:
        audio = video
    if audio is not None:
        adur, _, a_has = probe(ffmpeg, audio)
        if audio != video and not a_has:
            print(f"[알림] 오디오 스트림이 없는 파일이라 파형을 건너뛴다: {audio}", file=sys.stderr)
            audio = None
        elif start >= adur:
            print(f"[알림] 구간이 오디오 길이({adur:.2f}s) 밖이라 파형을 건너뛴다", file=sys.stderr)
            audio = None

    out_png = Path(args.out) if args.out else (root / "검증" /
              f"timeline_{start:06.2f}-{end:06.2f}.png")
    if not out_png.is_absolute():
        out_png = (Path.cwd() / out_png).resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_json = out_png.with_suffix(".json")

    from PIL import Image, ImageDraw, ImageFont

    font_path, _ = pick_font(args.font)
    if font_path is None:
        print("[경고] 한글 폰트를 찾지 못했다 — 단어 텍스트 대신 인덱스 번호를 그린다 "
              "(--font 로 TTF 지정 가능). 단어 원문은 JSON에 그대로 있다.", file=sys.stderr)

    def F(size):
        if font_path:
            return ImageFont.truetype(font_path, size)
        return ImageFont.load_default()

    f_head, f_lab, f_word, f_ax = F(15), F(11), F(13), F(10)

    # ── 측정 ────────────────────────────────────────────────────────────
    times = [start + dur * i / (args.frames - 1) for i in range(args.frames)]
    times = [min(t, max(start, vdur - 0.02)) for t in times]
    frames = grab_frames(ffmpeg, video, times)
    diff = diff_series(ffmpeg, video, start, dur, vsize)
    diff_max = max(d for _, d in diff) if diff else 0.0
    scale_max = max(10.0, diff_max)
    samples = audio_samples(ffmpeg, audio, start, dur) if audio else None

    words_all = load_words(transcript)
    words = [w for w in words_all if w["end"] > start and w["start"] < end]
    gaps = []
    for a, b in zip(words_all, words_all[1:]):
        g = b["start"] - a["end"]
        if g >= args.gap and b["start"] > start and a["end"] < end:
            gaps.append({"start": round(a["end"], 2), "end": round(b["start"], 2), "dur": round(g, 2)})

    boundaries = []
    for s in (tl.get("slides") or []):
        t = float(s.get("start", -1))
        if start <= t <= end:
            boundaries.append({"t": round(t, 2), "kind": "slide",
                               "label": f"{s.get('id', '#' + str(s.get('index', '?')))} 시작"})
    for o in (tl.get("video_overlays") or []):
        name = f"ov{o.get('n', '?')}"
        for key, kind in (("start", "overlay_start"), ("end", "overlay_end")):
            if o.get(key) is None:
                continue
            t = float(o[key])
            if start <= t <= end:
                boundaries.append({"t": round(t, 2), "kind": kind,
                                   "label": f"{name} {'시작' if key == 'start' else '끝'}"})
    boundaries.sort(key=lambda b: b["t"])

    # ── 레이아웃 ────────────────────────────────────────────────────────
    W = args.width
    plot_l, plot_r = PAD_L, W - PAD_R
    plot_w = plot_r - plot_l

    def X(t):
        return plot_l + (t - start) / dur * plot_w

    tile_w = plot_w / args.frames
    fw, fh = frames[0].size
    tile_h = int(round(tile_w * fh / fw))
    y = PAD_T
    y_head = y; y += H_HEADER
    y_strip = y; y += tile_h + H_STRIP_LABEL + ROW_GAP
    y_diff = y; y += H_DIFF + H_STRIP_LABEL + ROW_GAP
    y_wave = y; y += H_WAVE + ROW_GAP
    y_words = y; y += H_WORD_TIER * WORD_TIERS + 4
    y_axis = y; y += H_AXIS
    H = int(y + PAD_B)

    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    def text(xy, s, font, fill=INK, anchor=None):
        dr.text(xy, s, font=font, fill=fill, anchor=anchor)

    # 1. 헤더
    text((PAD_L, y_head), f"{video.name} · {start:.2f}~{end:.2f}s · {dur:.2f}s · "
                          f"오디오 {audio.name if audio else '없음'}", f_head)

    # 갭 밴드 (파형+단어 행 관통) — 먼저 칠해 밑에 깔린다
    for g in gaps:
        gx0, gx1 = X(max(g["start"], start)), X(min(g["end"], end))
        dr.rectangle([gx0, y_wave, max(gx1, gx0 + 1), y_words + H_WORD_TIER * WORD_TIERS],
                     fill=BAND)
        text(((gx0 + gx1) / 2, y_wave + 2), f"갭 {g['dur']:.2f}s", f_lab, AMBER, anchor="ma")

    # 2. 필름스트립
    for t, im in zip(times, frames):
        tw = int(tile_w) - 2
        th = max(1, int(round(tw * fh / fw)))
        cx = X(t)
        left = int(min(max(cx - tw / 2, plot_l), plot_r - tw))
        img.paste(im.resize((tw, th)), (left, y_strip))
        dr.rectangle([left, y_strip, left + tw, y_strip + th], outline=LIGHT)
        text((cx, y_strip + th + 2), f"{t:.2f}", f_lab, GRAY, anchor="ma")
        dr.line([cx, y_strip + th + 1, cx, y_strip + th + 3], fill=GRAY)

    # 3. 프레임 차분 띠
    dr.line([plot_l, y_diff + H_DIFF, plot_r, y_diff + H_DIFF], fill=LIGHT)
    bw = max(1.0, plot_w / max(1, len(diff)))
    for t, d in diff:
        h = min(1.0, d / scale_max) * H_DIFF
        x0 = X(t) - bw / 2
        dr.rectangle([x0, y_diff + H_DIFF - h, x0 + max(1.0, bw - 0.6), y_diff + H_DIFF], fill=INK)
    text((4, y_diff - 1), "차분", f_lab, GRAY)
    text((4, y_diff + H_DIFF - 11), "0", f_lab, GRAY)
    text((plot_l + 2, y_diff + H_DIFF + 2),
         f"인접 프레임 평균 절대차 {SAMPLE_FPS}fps @{DIFF_WIDTH}px · max {diff_max:.2f} "
         f"(스케일 0~{scale_max:.0f})", f_lab, GRAY)

    # 4. 파형
    mid = y_wave + H_WAVE / 2
    dr.line([plot_l, mid, plot_r, mid], fill=LIGHT)
    text((4, y_wave - 1), "파형", f_lab, GRAY)
    if samples is not None and len(samples) > 1:
        import numpy as np
        ncol = max(1, int(plot_w // 2))
        idx = np.linspace(0, len(samples), ncol + 1).astype(int)
        for i in range(ncol):
            seg = samples[idx[i]:max(idx[i] + 1, idx[i + 1])]
            pk = float(np.abs(seg).max()) if len(seg) else 0.0
            h = pk * (H_WAVE / 2 - 2)
            x = plot_l + i * 2
            dr.line([x, mid - h, x, mid + h], fill=INK)
    else:
        text((plot_l + 6, mid - 7), "오디오 없음", f_word, GRAY)

    # 5. 단어 라벨
    tier_end = [-1e9] * WORD_TIERS
    for i, w in enumerate(words):
        x = X(max(w["start"], start))
        label = w["word"] if font_path else str(i)
        tw_px = dr.textlength(label, font=f_word)
        tier = next((k for k in range(WORD_TIERS) if tier_end[k] + 6 < x),
                    min(range(WORD_TIERS), key=lambda k: tier_end[k]))
        ty = y_words + tier * H_WORD_TIER
        dr.line([x, y_words - 3, x, ty + H_WORD_TIER - 3], fill=GRAY)
        text((x + 3, ty + 2), label, f_word, INK)
        tier_end[tier] = x + tw_px + 3

    # 6. 경계선 (전 행 관통)
    for b in boundaries:
        x = X(b["t"])
        if b["kind"] == "slide":
            dr.line([x, y_strip - 4, x, y_axis], fill=INK, width=2)
            col = INK
        else:
            for yy in range(int(y_strip - 4), int(y_axis), 8):
                dr.line([x, yy, x, min(yy + 4, y_axis)], fill=GREEN, width=2)
            col = GREEN
        text((x + 3, y_strip - 15), f"{b['label']} {b['t']:.2f}s", f_lab, col)

    # 시간 눈금
    dr.line([plot_l, y_axis, plot_r, y_axis], fill=GRAY)
    t = (int(start * 2) / 2)
    while t <= end + 1e-6:
        if t >= start:
            x = X(t)
            big = abs(t - round(t)) < 1e-6
            dr.line([x, y_axis, x, y_axis + (7 if big else 4)], fill=GRAY)
            if big:
                text((x, y_axis + 9), f"{t:.0f}s", f_ax, GRAY, anchor="ma")
        t += 0.5

    img.save(out_png)

    payload = {
        "video": str(video), "audio": str(audio) if audio else None,
        "transcript": str(transcript) if transcript else None,
        "timeline": str(tl_path),
        "range": [round(start, 2), round(end, 2)], "png": str(out_png),
        "frames": [{"t": round(t, 2)} for t in times],
        "diff": [{"t": round(t, 2), "d": round(d, 3)} for t, d in diff],
        "diff_max": round(diff_max, 3),
        "words": [{"word": w["word"], "start": round(w["start"], 2), "end": round(w["end"], 2)}
                  for w in words],
        "gaps": gaps, "boundaries": boundaries,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── stdout 요약 ─────────────────────────────────────────────────────
    print(f"구간 {start:.2f}~{end:.2f}s ({dur:.2f}s) · 영상 {video.name} ({vdur:.2f}s) · "
          f"오디오 {audio.name if audio else '없음'}")
    print(f"프레임 {len(times)}장 · 단어 {len(words)}개 · 차분 표본 {len(diff)} (max {diff_max:.2f})")
    if gaps:
        print(f"갭(≥{args.gap}s) {len(gaps)}건: " +
              ", ".join(f"{g['start']:.2f}~{g['end']:.2f} ({g['dur']:.2f}s)" for g in gaps))
    else:
        print(f"갭(≥{args.gap}s) 없음")
    if boundaries:
        print("경계: " + ", ".join(f"{b['label']}@{b['t']:.2f}s" for b in boundaries))
    else:
        print("경계: 구간 안에 슬라이드·오버레이 경계 없음")
    top = sorted(diff, key=lambda x: -x[1])[:3]
    if top:
        print("차분 상위 3: " + ", ".join(f"{t:.2f}s({d:.2f})" for t, d in top))
    print(f"저장: {out_png}")
    print(f"      {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
