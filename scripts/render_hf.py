"""HF 히어로 인서트 렌더러 — 타임라인.json의 style=="hyperframes" 오버레이를 ov<n>.mp4로 렌더 (개선안 §3-5).

왜 스크립트인가:
  콜라주(render_collage.py)와 같은 자리다. `encode_overlays.py`는 "원본 영상을 배속해 구간에 맞추는"
  경로라 HF 인서트에는 쓸 수 없다(원본이 없다 — HTML이 원본이다). HF 인서트는
  `04_영상소스/hf/<n>/` 안의 HF 프로젝트를 npx hyperframes가 직접 ov<n>.mp4로 굽는다.

무엇을 하나 (오버레이 n마다):
  1. lint   — 정적 82규칙. error 0이 아니면 중단(check가 브라우저 감사를 통째로 건너뛰기 때문).
  2. check  — 레이아웃 겹침/잘림 + 명암비(큰 텍스트 3:1, 작은 텍스트 4.5:1) + 모션.
              실패 시 stderr에 원문을 뱉고 중단. --skip-check로 생략 가능(권장하지 않음).
  3. render — `hyperframes render . --output <abs>ov<n>.mp4 --fps 30 --quality high
              --workers 1 --format mp4`. 무음(오디오는 CapCut 트랙 소유).
  4. 검증   — 파일 존재 + 크기>0 + ffprobe 길이 ≥ (end - start - 0.5).
  5. 결과 표(코덱·해상도·fps·길이·오디오 트랙 유무) 출력.

절대 규칙 (개선안 §2 함정 — 어기면 사고):
  · 환경변수 HYPERFRAMES_SKIP_SKILLS=1 · HYPERFRAMES_NO_TELEMETRY=1 필수.
    (없으면 init/render가 홈의 에이전트 스킬 폴더 10곳에 스킬을 무단 복사한다.)
  · cwd 는 반드시 HF 프로젝트 폴더. youtube-creator 루트에서 돌리면 CLI가 그 폴더의
    .env 를 자동 로드해 OPENAI 키가 프로세스에 실린다.
  · Windows에서 npx 는 `npx.cmd` — shell=False 로는 확장자 없이 못 부른다.
  · 버전 핀 hyperframes@0.8.16.

사용:
  python scripts/render_hf.py <타임라인.json> [--n 3] [--n 7] [--skip-check] [--frames 1,4,7]
  전제: 각 오버레이마다 <작업>/04_영상소스/hf/<n>/index.html (템플릿/hf-insert/ 복사본)
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HF_PIN = "hyperframes@0.8.16"
LEN_TOL = 0.5            # 렌더 길이가 구간보다 이만큼 짧으면 실패
RENDER_TIMEOUT = 3600    # 인서트 1개(8초)에 26~45초 실측 — 여유 있게


def npx_cmd() -> str:
    """Windows에서는 npx.cmd 를 명시해야 shell 없이 실행된다."""
    for name in (("npx.cmd", "npx") if os.name == "nt" else ("npx",)):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("[중단] npx 를 찾지 못했습니다 — Node.js 설치를 확인하세요.")


NPX = None  # main()에서 1회 해결


def hf_run(project: pathlib.Path, argv: list, timeout: int = 600):
    """HF CLI 서브프로세스 — cwd=프로젝트 폴더(.env 유출 차단), 스킬 복사/텔레메트리 차단."""
    env = dict(os.environ)
    env["HYPERFRAMES_SKIP_SKILLS"] = "1"
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    cmd = [NPX, "--yes", HF_PIN] + argv
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(project), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0


def ffprobe_spec(path: pathlib.Path) -> dict:
    """코덱·해상도·fps·길이·오디오 트랙 유무. ffprobe 우선, 없으면 imageio_ffmpeg 번들."""
    exe = shutil.which("ffprobe")
    if not exe:                                   # 번들 ffmpeg 옆의 ffprobe는 없음 → ffmpeg로 대체 측정
        import imageio_ffmpeg
        import re
        p = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
        dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
        v = re.search(r"Video:\s*(\w+).*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", p.stderr, re.S)
        return {"duration": dur,
                "codec": v.group(1) if v else "?",
                "width": int(v.group(2)) if v else 0,
                "height": int(v.group(3)) if v else 0,
                "fps": float(v.group(4)) if v else 0.0,
                "audio": "Audio:" in p.stderr}
    p = subprocess.run([exe, "-v", "error", "-show_format", "-show_streams",
                        "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {path}\n{p.stderr[-600:]}")
    data = json.loads(p.stdout)
    streams = data.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in streams)
    fps = 0.0
    if vs and vs.get("avg_frame_rate", "0/0") != "0/0":
        num, den = (vs["avg_frame_rate"].split("/") + ["1"])[:2]
        fps = float(num) / float(den) if float(den) else 0.0
    dur = float(data.get("format", {}).get("duration") or (vs or {}).get("duration") or 0.0)
    return {"duration": dur,
            "codec": (vs or {}).get("codec_name", "?"),
            "width": int((vs or {}).get("width") or 0),
            "height": int((vs or {}).get("height") or 0),
            "fps": fps,
            "audio": audio}


def extract_frames(video: pathlib.Path, times, out_dir: pathlib.Path) -> list:
    """육안 검수용 정지 프레임 추출 — 실패해도 렌더 판정에는 영향 없음."""
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for t in times:
        out = out_dir / f"{video.stem}_t{str(t).replace('.', 'p')}.png"
        p = subprocess.run([ff, "-hide_banner", "-y", "-ss", str(t), "-i", str(video),
                            "-frames:v", "1", str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            made.append(out)
        else:
            print(f"[경고] 프레임 t={t}s 추출 실패: {p.stderr[-300:]}")
    return made


def render_one(project: pathlib.Path, out: pathlib.Path, seg: float,
               skip_check: bool) -> dict:
    """lint → check → render → 길이 검증. 실패는 RuntimeError."""
    rc, log, dt = hf_run(project, ["lint", "."])
    print(f"  · lint  ({dt:.1f}s) → rc={rc}")
    if rc != 0:
        print(log, file=sys.stderr)
        raise RuntimeError(f"lint 실패: {project}")

    if skip_check:
        print("  · check 건너뜀 (--skip-check) — 명암비·레이아웃 감사 없이 렌더합니다")
    else:
        rc, log, dt = hf_run(project, ["check", "."])
        print(f"  · check ({dt:.1f}s) → rc={rc}")
        if rc != 0:
            print(log, file=sys.stderr)
            raise RuntimeError(f"check 실패: {project} (원인 수정 후 재시도, 또는 --skip-check)")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    rc, log, dt = hf_run(project, ["render", ".", "--output", str(out.resolve()),
                                   "--fps", "30", "--quality", "high",
                                   "--workers", "1", "--format", "mp4"],
                         timeout=RENDER_TIMEOUT)
    print(f"  · render({dt:.1f}s) → rc={rc}")
    if rc != 0:
        print(log, file=sys.stderr)
        raise RuntimeError(f"render 실패: {project}")

    # 성공 판정 = 파일 존재 + 비어있지 않음 + ffprobe 길이 (CLI의 rc만 믿지 않는다)
    if not out.is_file() or out.stat().st_size == 0:
        print(log, file=sys.stderr)
        raise RuntimeError(f"render 산출물 없음/빈 파일: {out}")
    spec = ffprobe_spec(out)
    if spec["duration"] <= 0:
        print(log, file=sys.stderr)
        raise RuntimeError(f"render 산출물 길이 0: {out}")
    if seg - spec["duration"] > LEN_TOL:
        raise RuntimeError(f"길이 부족: {spec['duration']:.2f}s < 구간 {seg:.2f}s−{LEN_TOL} "
                           f"— 루트 data-duration을 구간 길이에 맞춰 정적 기입하세요")
    spec["render_sec"] = dt
    return spec


def main() -> None:
    global NPX
    ap = argparse.ArgumentParser(description="HF 인서트 렌더 (style==\"hyperframes\" 오버레이)")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--n", type=int, action="append",
                    help="특정 오버레이 n만 렌더 (반복 지정 가능). 생략 시 전부")
    ap.add_argument("--skip-check", action="store_true",
                    help="HF check(명암비·레이아웃 감사) 생략 — 권장하지 않음")
    ap.add_argument("--frames", default="",
                    help="육안 검수용 프레임 추출 시각(초), 예: 1,4,7")
    args = ap.parse_args()
    NPX = npx_cmd()

    base = args.timeline.resolve().parent
    tl = json.loads(args.timeline.read_text(encoding="utf-8"))
    duration = float(tl.get("duration") or 0)
    overlays = [o for o in (tl.get("video_overlays") or []) if o.get("style") == "hyperframes"]
    if args.n:
        overlays = [o for o in overlays if o.get("n") in set(args.n)]
    if not overlays:
        sys.exit("[중단] 타임라인.json에 style==\"hyperframes\" 오버레이가 없습니다 "
                 "(--n 필터가 과했을 수도 있습니다).")

    times = [float(x) for x in args.frames.split(",") if x.strip()] if args.frames else []
    out_dir = base / "04_영상소스"
    rows = []
    for o in overlays:
        n = o["n"]
        seg = float(o["end"]) - float(o["start"])
        if seg <= 0:
            sys.exit(f"[오류] 오버레이 {n}: 구간 길이 {seg:.2f}s ≤ 0 — start/end 확인")
        if duration and float(o["end"]) > duration + 0.01:
            sys.exit(f"[오류] 오버레이 {n}: end {o['end']} > duration {duration}")
        project = out_dir / "hf" / str(n)
        if not (project / "index.html").is_file():
            sys.exit(f"[오류] 오버레이 {n}: HF 프로젝트 없음 — {project / 'index.html'}\n"
                     f"       템플릿/hf-insert/ 를 복사해 만드세요.")
        out = out_dir / f"ov{n}.mp4"
        print(f"[ov{n}] {project} → {out.name}  (구간 {seg:.2f}s, {o.get('label', '')})")
        spec = render_one(project, out, seg, args.skip_check)
        if times:
            made = extract_frames(out, times, out_dir / "hf" / "frames")
            for m in made:
                print(f"  · 프레임 {m}")
        # src는 이 스크립트가 만든 ov<n>.mp4 자신을 가리킨다 → validate_pipeline D(원본 존재)·
        # E(길이) 통과. render_collage.py와 동일 규약.
        o["src"] = f"04_영상소스/ov{n}.mp4"
        o["src_dur"] = round(spec["duration"], 3)
        rows.append((n, seg, spec))

    tmp = args.timeline.with_suffix(".json.tmp")   # 원자적 쓰기(encode_overlays·render_collage와 동일)
    tmp.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(args.timeline)

    print("\n" + "=" * 84)
    print(f"{'n':>3}  {'구간':>7}  {'길이':>7}  {'코덱':<6} {'해상도':<11} {'fps':>6}  "
          f"{'오디오':<6} {'렌더':>7}")
    print("-" * 84)
    for n, seg, s in rows:
        print(f"{n:>3}  {seg:>6.2f}s  {s['duration']:>6.2f}s  {s['codec']:<6} "
              f"{str(s['width']) + 'x' + str(s['height']):<11} {s['fps']:>6.2f}  "
              f"{'있음' if s['audio'] else '없음':<6} {s['render_sec']:>6.1f}s")
    print("=" * 84)
    print(f"[완료] HF 인서트 {len(rows)}개 → {out_dir}\\ov*.mp4")
    print("다음 단계: validate_pipeline.py → assemble_capcut.py "
          "(오디오는 CapCut 트랙 소유 — 인서트는 무음이 정상)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as e:
        print(f"오류: HF CLI 타임아웃 ({e.timeout}s) — {e.cmd}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
