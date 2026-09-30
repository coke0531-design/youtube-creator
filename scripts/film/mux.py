# -*- coding: utf-8 -*-
"""완성본 합성 — 캡처 영상 + 나레이션 + SRT 자막 번인 (+ 선택 오버레이).

- SRT → ASS (PlayRes 1920x1080, Alignment 2 하단 중앙, MarginV = --bottom, 좌우 여백 160)
  폰트: Pretendard 설치돼 있으면 Pretendard, 없으면 'Malgun Gothic'
  --style outline (기본): 흰 글자 + 검은 외곽선 3px(볼드)
  --style box           : 정본 render_final.py의 '흰 상자 자막'(잉크 글자·흰 상자·앰버 테두리/하드 섀도)
- 비디오: 1920x1080 lanczos 정규화(out_range=tv) → 오버레이(선택, overlay-start부터) → ass 번인
- 오디오: loudnorm I=-14:TP=-1.5:LRA=11 (1-pass) → aresample 48000, aac 192k
- 길이 = 오디오 기준. -shortest 쓰지 않음. 비디오가 짧으면 마지막 프레임 tpad(clone), 길면 -t로 자름.
- 인코더: h264_nvenc cq19 → 불가 시 libx264 crf17 (render_final.py와 동일), yuv420p bt709 tv

사용:
  python mux.py --video capture.mp4 --audio narration.m4a --srt full.srt --out final.mp4
  python mux.py ... --font-size 60 --bottom 108 --overlay ov.mp4 --overlay-start 12.5
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture import COLOR_OUT, die, encoder_args, find_ffmpeg  # noqa: E402

PLAYRES = (1920, 1080)
MARGIN_LR = 160
# render_final.py '흰 상자 자막' 색·치수 (box 스타일용)
BOX_INK, BOX_FILL, BOX_RIM, BOX_SHADOW = "&H00131414", "&H00FEFEFD", "&H00010E16", "&H0003263B"
BOX_PAD, BOX_RIM_W, BOX_SHADOW_OFF = 8, 2, 10


def pick_font():
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    for d in dirs:
        if d.is_dir() and any(d.glob("Pretendard*")):
            return "Pretendard"
    return "Malgun Gothic"


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def srt_sec(v):
    hms, ms = v.strip().replace(".", ",").split(",")
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms) / 1000.0


def read_srt(path):
    content = Path(path).read_text(encoding="utf-8-sig").strip()
    for block in re.split(r"\r?\n\s*\r?\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        a, b = lines[1].split(" --> ", 1)
        yield srt_sec(a), srt_sec(b), "\n".join(lines[2:])


def esc(text):
    text = text.replace("{", "\\{").replace("}", "\\}")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")


def build_ass(srt, font, size, bottom, style):
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
           "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    tail = f"2,{MARGIN_LR},{MARGIN_LR},{bottom},1"
    if style == "box":
        common = "-1,0,0,0,100,100,0,0,3"
        styles = [f"Style: CapRim,{font},{size},&HFF131414,&H000000FF,{BOX_RIM},{BOX_SHADOW},{common},"
                  f"{BOX_PAD + BOX_RIM_W},{BOX_SHADOW_OFF},{tail}",
                  f"Style: Cap,{font},{size},{BOX_INK},&H000000FF,{BOX_FILL},{BOX_FILL},{common},"
                  f"{BOX_PAD},0,{tail}"]
        layers = [(0, "CapRim"), (1, "Cap")]
    else:
        styles = [f"Style: Cap,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
                  f"-1,0,0,0,100,100,0,0,1,3,0,{tail}"]
        layers = [(0, "Cap")]
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAYRES[0]}", f"PlayResY: {PLAYRES[1]}",
            "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
            "[V4+ Styles]", fmt, *styles, "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ev, n = [], 0
    for s, e, text in read_srt(srt):
        n += 1
        for layer, st in layers:
            ev.append(f"Dialogue: {layer},{ass_time(s)},{ass_time(e)},{st},,0,0,0,,{esc(text)}")
    return "\n".join(head + ev) + "\n", n


def probe_dur(path):
    exe = shutil.which("ffprobe")
    if exe:
        p = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True)
        try:
            return float(p.stdout.strip())
        except ValueError:
            pass
    p = subprocess.run([find_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        die(f"[입력 오류] 길이를 읽지 못했다: {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main():
    ap = argparse.ArgumentParser(description="캡처 영상 + 나레이션 + SRT 번인(+오버레이) → 완성본 mp4 (길이=오디오)")
    ap.add_argument("--video", required=True, help="capture.mp4")
    ap.add_argument("--audio", required=True, help="narration.m4a")
    ap.add_argument("--srt", required=True, help="full.srt")
    ap.add_argument("--out", required=True, help="출력 final.mp4")
    ap.add_argument("--font-size", type=int, default=60, help="자막 크기 px @1080 (기본 60)")
    ap.add_argument("--bottom", type=int, default=108, help="텍스트 하단↔화면 하단 px = ASS MarginV (기본 108)")
    ap.add_argument("--style", choices=["outline", "box"], default="outline",
                    help="outline = 흰 글자 검은 외곽선 3px(기본) / box = render_final 흰 상자 자막")
    ap.add_argument("--overlay", help="오버레이 영상(선택, 1920x1080 권장)")
    ap.add_argument("--overlay-start", type=float, default=0.0, help="오버레이 시작 초(기본 0)")
    ap.add_argument("--encoder", choices=["auto", "nvenc", "x264"], default="auto")
    ap.add_argument("--keep-ass", action="store_true", help="생성한 ASS를 출력 옆에 <out>.ass로 남긴다")
    args = ap.parse_args()

    for f in [args.video, args.audio, args.srt] + ([args.overlay] if args.overlay else []):
        if not Path(f).exists():
            die(f"[입력 오류] 파일이 없다: {f}")
    ff = find_ffmpeg()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    a_dur, v_dur = probe_dur(args.audio), probe_dur(args.video)
    pad = max(0.0, a_dur - v_dur)
    font = pick_font()
    ass, ncue = build_ass(args.srt, font, args.font_size, args.bottom, args.style)
    enc_label, enc = encoder_args(ff, args.encoder, crf=17)

    w, h = PLAYRES
    parts = [f"[0:v]scale={w}:{h}:flags=lanczos:out_range=tv,setsar=1"
             + (f",tpad=stop_mode=clone:stop_duration={pad + 0.5:.3f}" if pad > 0 else "") + "[base]"]
    cur = "[base]"
    inputs = ["-i", str(Path(args.video).resolve())]
    if args.overlay:
        inputs += ["-i", str(Path(args.overlay).resolve())]
        s = args.overlay_start
        parts.append(f"[1:v]scale={w}:{h}:flags=lanczos,setpts=PTS-STARTPTS+{s:.3f}/TB[ov]")
        parts.append(f"{cur}[ov]overlay=0:0:eof_action=pass:enable='gte(t,{s:.3f})'[b1]")
        cur = "[b1]"
    a_idx = len(inputs) // 2
    inputs += ["-i", str(Path(args.audio).resolve())]
    parts.append(f"{cur}ass=subs.ass[vout]")
    parts.append(f"[{a_idx}:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    fg = ";".join(parts)

    print(f"[mux] 영상 {v_dur:.2f}s · 오디오 {a_dur:.2f}s → 출력 {a_dur:.2f}s"
          f"{f' (마지막 프레임 {pad:.2f}s 연장)' if pad > 0 else ''} · 자막 {ncue}컷 {args.style} "
          f"{font} {args.font_size}px bottom {args.bottom} · 인코더 {enc_label}")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="mux_") as td:
        (Path(td) / "subs.ass").write_text(ass, encoding="utf-8")
        if args.keep_ass:
            out.with_suffix(".ass").write_text(ass, encoding="utf-8")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", fg,
               "-map", "[vout]", "-map", "[aout]", *enc, *COLOR_OUT,
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{a_dur:.3f}",
               "-movflags", "+faststart", str(out)]
        p = subprocess.run(cmd, cwd=td, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not out.exists():
        print(f"[실패] ffmpeg rc={p.returncode}: {p.stderr[-1200:]}", file=sys.stderr)
        return 1
    o_dur = probe_dur(out)
    print(f"[완료] {out}  길이 {o_dur:.2f}s (오디오 {a_dur:.2f}s, 차 {o_dur - a_dur:+.2f}s)  {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
