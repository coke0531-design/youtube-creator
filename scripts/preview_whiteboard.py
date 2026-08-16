"""화이트보드 장면 미리보기 — 슬라이드(capture.mp4) 위에 wb<n>.mp4를 얹고 나레이션+자막을 붙인 짧은 mp4를 만든다 (Step 6.6 실측용).

왜 있나: 화이트보드 클립 하나를 판단하려고 본편 전체를 재조립·렌더할 필요는 없다. 앞뒤 슬라이드 몇 초를 붙여
"슬라이드 → 드로잉 → 슬라이드" 흐름과 자막·나레이션 정합만 빠르게 본다. 본편 타임라인.json은 건드리지 않는다.

사용:
  python scripts/preview_whiteboard.py <작업폴더> <wbN.mp4> --start 113.8 --end 128.75 [--pad 2.0] [--name 팀장비유]
  → <작업폴더>/완성본/미리보기_화이트보드_<name>.mp4  (구간 = start-pad ~ end+pad, 자막은 render_final과 동일 ASS 규격·잉크색)
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render_final as rf  # noqa: E402  (ASS 자막 규격 재사용)
import imageio_ffmpeg  # noqa: E402


def _t2s(x: str) -> float:
    h, m, s = x.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _s2t(x: float) -> str:
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser(description="화이트보드 장면 미리보기 합성")
    ap.add_argument("job", type=pathlib.Path, help="결과물 작업 폴더")
    ap.add_argument("wb", type=pathlib.Path, help="wb<n>.mp4 (04_영상소스/)")
    ap.add_argument("--start", type=float, required=True, help="오버레이 시작(오디오 초)")
    ap.add_argument("--end", type=float, required=True, help="오버레이 끝(오디오 초, 페이드 포함)")
    ap.add_argument("--pad", type=float, default=2.0, help="앞뒤로 붙일 슬라이드 초(기본 2)")
    ap.add_argument("--name", default=None, help="파일명 꼬리표(기본: wb 파일명)")
    a = ap.parse_args()

    job = a.job.resolve()
    cap = job / "04_영상소스" / "capture.mp4"
    aud_rel = __import__("json").loads((job / "타임라인.json").read_text(encoding="utf-8"))["audio"]
    aud, srt = job / aud_rel, job / "03_자막" / "full.srt"
    for f in (cap, aud, srt, a.wb):
        if not f.is_file():
            sys.exit(f"[오류] 없음: {f}")
    t0, t1 = max(0.0, a.start - a.pad), a.end + a.pad
    s, e = a.start - t0, a.end - t0

    tmp = pathlib.Path(os.environ.get("TMP", ".")) / "wbprev"
    tmp.mkdir(parents=True, exist_ok=True)
    cues = re.findall(r"\d+\n(\S+) --> (\S+)\n(.+?)(?:\n\n|\Z)", srt.read_text(encoding="utf-8"), re.S)
    lines, n = [], 0
    for c0, c1, txt in cues:
        c0, c1 = _t2s(c0), _t2s(c1)
        if c1 <= t0 or c0 >= t1:
            continue
        n += 1
        lines.append(f"{n}\n{_s2t(max(c0, t0) - t0)} --> {_s2t(min(c1, t1) - t0)}\n{txt.strip()}\n")
    sub_srt = tmp / "prev.srt"
    sub_srt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ass, total, white = rf._build_ass(sub_srt, [{"start": s, "end": e, "style": "whiteboard"}], "main")
    (tmp / "subs.ass").write_text(ass, encoding="utf-8")

    name = a.name or a.wb.stem
    out = job / "완성본" / f"미리보기_화이트보드_{name}.mp4"
    out.parent.mkdir(exist_ok=True)
    fg = (f"[0:v]scale=1920:1080:flags=lanczos[base];[1:v]setpts=PTS-STARTPTS+{s:.3f}/TB[wb];"
          f"[base][wb]overlay=0:0:eof_action=pass:enable='between(t,{s:.3f},{e:.3f})'[ov];[ov]ass=subs.ass[vout]")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-hide_banner", "-y", "-loglevel", "error",
           "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(cap), "-i", str(a.wb.resolve()),
           "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(aud),
           "-filter_complex", fg, "-map", "[vout]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"[오류] ffmpeg 실패\n{r.stderr[-1200:]}")
    print(f"[완료] {out}  ({t0:.2f}~{t1:.2f}s, 자막 {total}컷·잉크색)")


if __name__ == "__main__":
    main()
