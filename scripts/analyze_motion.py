# -*- coding: utf-8 -*-
"""레퍼런스 영상 모션 문법 분석 (결정론).

레퍼런스 영상을 컷 단위로 해부해 "모션 문법"(컷 길이·전환 지점·등장 순서)을
분석할 재료를 만든다. 판정은 전부 ffmpeg 장면 전환 감지(결정론)이고,
전환 유형·카메라 워크 같은 정성 항목은 사람/AI가 contact sheet를 보고 기입한다.

산출물 (기본: <영상 폴더>/모션문법_<영상이름>/):
  - cuts/cut_NNN.jpg   컷별 대표 프레임(중간 지점)
  - contact_sheet.jpg  전체 컷 한눈에 보기(타일)
  - 모션문법.md         컷 표(시작/끝/길이) + 정성 기입란

사용:
  python scripts/analyze_motion.py "레퍼런스.mp4"
  python scripts/analyze_motion.py "레퍼런스.mp4" --scene 0.25 --cols 6
"""
import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg을 찾을 수 없다 — pip install imageio-ffmpeg 또는 PATH에 ffmpeg 추가")
    return exe


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(ffmpeg: str, video: Path):
    """duration(초)·fps를 ffmpeg -i stderr에서 파싱."""
    p = run([ffmpeg, "-hide_banner", "-i", str(video)])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        sys.exit(f"길이를 읽지 못했다 — 영상 파일인지 확인: {video}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    fm = re.search(r"(\d+(?:\.\d+)?)\s*fps", p.stderr)
    fps = float(fm.group(1)) if fm else 0.0
    return duration, fps


def detect_cuts(ffmpeg: str, video: Path, threshold: float):
    """장면 전환 감지 → 전환 시각 리스트(초)."""
    p = run([
        ffmpeg, "-hide_banner", "-i", str(video),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ])
    times = [float(t) for t in re.findall(r"pts_time:\s*(\d+\.?\d*)", p.stderr)]
    # showinfo가 같은 시각을 중복 출력하는 경우 제거
    dedup = []
    for t in sorted(times):
        if not dedup or t - dedup[-1] > 0.05:
            dedup.append(t)
    return dedup


def fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def main():
    ap = argparse.ArgumentParser(description="레퍼런스 영상 모션 문법 분석 (결정론 컷 해부)")
    ap.add_argument("video", help="레퍼런스 영상 파일")
    ap.add_argument("--out", help="출력 폴더 (기본: <영상 폴더>/모션문법_<이름>)")
    ap.add_argument("--scene", type=float, default=0.30,
                    help="장면 전환 문턱 0~1 (기본 0.30 — 컷이 덜 잡히면 낮추고, 과하면 올린다)")
    ap.add_argument("--cols", type=int, default=6, help="contact sheet 열 수 (기본 6)")
    ap.add_argument("--height", type=int, default=180, help="컷 프레임 세로 px (기본 180)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="컷이 안 잡힐 때(부드러운 전환 영상) 고정 간격 샘플링 초 (기본 2.0)")
    ap.add_argument("--max-frames", type=int, default=120,
                    help="구간 수 상한 (기본 120 — contact sheet·표가 분석 가능한 크기를 유지)")
    ap.add_argument("--force", action="store_true",
                    help="장편 가드(30분 초과 중단)를 무시하고 강행")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.is_file():
        sys.exit(f"파일 없음: {video}")
    out = Path(args.out) if args.out else video.parent / f"모션문법_{video.stem}"
    cuts_dir = out / "cuts"
    cuts_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    duration, fps = probe(ffmpeg, video)
    frame_total = int(duration * fps) if fps else 0
    print(f"영상: {video.name} — {duration:.2f}s, {fps:g}fps (~{frame_total}프레임)")

    # 장편 가드 (fail-loud): 레퍼런스 분석은 짧은 발췌가 목적이다.
    # scene 감지는 전체 디코드라 실측 ~21배속(1440p 기준) — 장편·고해상도는 수 분~수십 분 소요.
    if duration > 1800 and not args.force:
        sys.exit(
            f"영상이 {duration / 60:.0f}분 — 30분 초과는 중단한다 (scene 감지 = 전체 디코드).\n"
            f"분석할 구간만 발췌해서 다시 실행하라:\n"
            f'  ffmpeg -ss <시작초> -t <길이초> -i "{video}" -c copy 발췌.mp4\n'
            f"전체가 정말 필요하면 --force로 강행 (구간 수는 --max-frames {args.max_frames}개로 캡)."
        )

    times = detect_cuts(ffmpeg, video, args.scene)
    if len(times) >= 1:
        # scene 컷이 상한을 넘으면 자르지 않고 중단한다 — 컷 표를 몰래 솎으면 문법 분석이 왜곡된다.
        if len(times) + 1 > args.max_frames:
            sys.exit(
                f"감지된 컷 {len(times) + 1}개 > 상한 {args.max_frames} — 문턱이 너무 낮거나 영상이 너무 길다.\n"
                f"--scene을 올리거나(현재 {args.scene}), 구간을 발췌하거나, --max-frames를 늘려라."
            )
        mode = f"scene 감지 (문턱 {args.scene})"
        bounds = [0.0] + times + [duration]
    else:
        # 부드러운 전환(페이드·스태거·흰 배경 슬라이드)은 scene 점수가 원리적으로 낮아
        # 컷이 안 잡힌다 → 고정 간격 샘플링으로 폴백 (원 방법론의 전 구간 contact sheet)
        interval = args.interval
        if duration / interval > args.max_frames:
            interval = duration / args.max_frames
            print(f"간격 {args.interval}s로는 {math.ceil(duration / args.interval)}구간 > 상한 {args.max_frames}"
                  f" → 간격을 {interval:.2f}s로 넓힌다 (--max-frames로 조정 가능)")
        mode = f"고정 간격 {interval:.2f}s 샘플링 (scene 감지 0건 폴백 — 부드러운 전환 영상)"
        n = max(1, math.ceil(duration / interval))
        bounds = [i * interval for i in range(n)] + [duration]
        print(f"scene 전환 0건 → 고정 간격 {interval:.2f}s 샘플링으로 폴백 (전환이 부드러운 영상)")
    cuts = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] > 0.01]
    print(f"구간: {len(cuts)}개 — {mode}")

    for i, (start, end) in enumerate(cuts, 1):
        mid = (start + end) / 2
        dst = cuts_dir / f"cut_{i:03d}.jpg"
        p = run([ffmpeg, "-hide_banner", "-y", "-ss", f"{mid:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", f"scale=-1:{args.height}", "-q:v", "3", str(dst)])
        if p.returncode != 0 or not dst.is_file():
            sys.exit(f"프레임 추출 실패 (cut {i}, t={mid:.2f}s):\n{p.stderr[-500:]}")

    rows = math.ceil(len(cuts) / args.cols)
    sheet = out / "contact_sheet.jpg"
    p = run([ffmpeg, "-hide_banner", "-y", "-start_number", "1",
             "-i", str(cuts_dir / "cut_%03d.jpg"),
             "-filter_complex", f"tile={args.cols}x{rows}", "-frames:v", "1",
             "-q:v", "3", str(sheet)])
    if p.returncode != 0:
        sys.exit(f"contact sheet 생성 실패:\n{p.stderr[-500:]}")

    md = out / "모션문법.md"
    lines = [
        f"# 모션 문법 — {video.name}",
        "",
        f"- 길이 {duration:.2f}s · {fps:g}fps · 구간 {len(cuts)}개 — {mode}",
        f"- contact sheet: `contact_sheet.jpg` (좌→우, 위→아래 = 컷 순서) · 컷별 프레임: `cuts/`",
        "- 시작/끝/길이는 실측(결정론). **전환·카메라·등장 순서는 시트와 원본을 보고 기입한다** — \"좋은 느낌\"이 아니라 수치·순서로 적는다.",
        "",
        "| 컷 | 시작 | 끝 | 길이(s) | 전환(유형·ms) | 카메라(줌/팬·시점) | 등장 순서(UI/텍스트 무엇이 먼저) |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, (start, end) in enumerate(cuts, 1):
        lines.append(f"| {i:03d} | {fmt(start)} | {fmt(end)} | {end - start:.2f} |  |  |  |")
    lines += [
        "",
        "## 관찰 요약 (기입)",
        "",
        "- 평균 컷 길이 / 최장·최단 컷과 그 역할:",
        "- 반복되는 전환 패턴(유형·지속 ms):",
        "- 카메라가 들어오는 순간의 공통점:",
        "- 우리 preset(design.md §4)으로 번역하면: preset + duration + params + transition + camera =",
        "",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"완료 → {out}")
    print(f"  - {sheet.name} / cuts/{len(cuts)}장 / {md.name}")


if __name__ == "__main__":
    main()
