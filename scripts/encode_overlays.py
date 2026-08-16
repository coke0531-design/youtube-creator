"""영상 소스 오버레이 인코딩 — 타임라인.json의 video_overlays를 ov<n>.mp4로 변환 (youtube-editor Step 6.5).

왜 스크립트인가:
  사용자 제공 시연/실사 영상(영상 소스/N.mp4)을 해당 나레이션 구간 길이에 맞추는 방법은
  "컷 없이 배속만" — 배속 팩터는 (구간 길이 ÷ 원본 길이)의 기계적 계산이라 결정론으로 강제한다.
  (화면 녹화는 액션 흐름이 나레이션과 이미 일치하므로 컷 없이 배속이 맞다 — 풀링_011 실증.)

무엇을 하나:
  1. 타임라인.json의 video_overlays[]를 읽어 각 원본(src)의 길이를 실측한다.
  2. 배속 = src_dur / (end - start). setpts로 배속만 적용(컷 없음).
  3. 1920x1080으로 화면비 보존 스케일 + 흰 패딩(슬라이드 흰 배경과 동화) — 왜곡 없음.
  4. 오디오 제거(-an) — 조립에서도 volume=0이지만 소재 자체를 무음으로 균일화.
  5. 산출: 04_영상소스/ov<n>.mp4 (+ 타임라인의 src_dur 필드 실측값으로 갱신).

가드(fail-loud):
  - 원본 없음 / 구간 길이 ≤ 0 → 중단.
  - 배속이 0.5×~2.0× 밖이면 경고(구간 배정이 잘못됐을 신호) — --force 없이는 중단.
  - 출력 길이가 구간 길이보다 0.5s 이상 짧으면 중단(오버슛은 조립에서 잘리므로 무해).

사용:
  python encode_overlays.py <타임라인.json> [--force]
  전제: 타임라인.json에 video_overlays[] 존재 (스키마: youtube-editor SKILL.md Step 6).
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

import imageio_ffmpeg

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FF = imageio_ffmpeg.get_ffmpeg_exe()
SPEED_MIN, SPEED_MAX = 0.5, 2.0     # 배속 가드 — 밖이면 구간 배정 오류 의심
OUT_SHORT_TOL = 0.5                  # 출력이 구간보다 이만큼 짧으면 실패
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _run_ff(args):
    p = subprocess.run([FF, "-hide_banner"] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stderr


def probe_duration(path: pathlib.Path) -> float:
    """디코드 정확 길이(초) — trim_silence.py와 동일 방식(-f null 마지막 time=)."""
    rc, stderr = _run_ff(["-i", str(path), "-f", "null", "-"])
    times = _TIME_RE.findall(stderr)
    if rc != 0 or not times:
        raise RuntimeError(f"길이 측정 실패: {path}\n{stderr[-800:]}")
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def encode(src: pathlib.Path, out: pathlib.Path, factor: float):
    """배속(setpts)만 적용 + 1920x1080 화면비 보존(흰 패딩) + 무음."""
    vf = (f"setpts=PTS*{factor:.6f},"
          "scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:-1:-1:color=white,setsar=1")
    rc, stderr = _run_ff(["-y", "-i", str(src), "-vf", vf, "-an",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", str(out)])
    if rc != 0:
        raise RuntimeError(f"인코딩 실패: {src}\n{stderr[-800:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="video_overlays → ov<n>.mp4 배속 인코딩")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--force", action="store_true", help="배속 가드(0.5~2.0×) 초과 강행")
    args = ap.parse_args()

    base = args.timeline.resolve().parent
    tl = json.loads(args.timeline.read_text(encoding="utf-8"))
    overlays = tl.get("video_overlays") or []
    if not overlays:
        sys.exit("[중단] 타임라인.json에 video_overlays가 없습니다 — 오버레이 없는 작업이면 이 단계는 건너뜁니다.")

    out_dir = base / "04_영상소스"
    out_dir.mkdir(exist_ok=True)

    changed = False
    for o in overlays:
        if o.get("style") == "collage":
            # 콜라주 인서트는 render_collage.py가 ov<n>.mp4를 정확한 길이로 직접 렌더한다 —
            # 여기서 재인코딩하면 자기 자신을 입력으로 덮어쓰므로 반드시 건너뛴다.
            print(f"  ov{o['n']}: collage — 건너뜀 (scripts/render_collage.py 담당)")
            continue
        src = (base / o["src"]).resolve()
        if not src.is_file():
            sys.exit(f"[오류] 원본 영상 없음: {src}")
        seg = float(o["end"]) - float(o["start"])
        if seg <= 0:
            sys.exit(f"[오류] 오버레이 {o['n']}: 구간 길이 {seg:.2f}s ≤ 0 — start/end 확인")
        src_dur = probe_duration(src)
        if abs(src_dur - float(o.get("src_dur") or src_dur)) > 0.05:
            print(f"[알림] 오버레이 {o['n']}: src_dur 실측 {src_dur:.3f}s로 갱신 "
                  f"(기재 {o.get('src_dur')})")
        o["src_dur"] = round(src_dur, 3)
        changed = True

        speed = src_dur / seg                 # >1 = 빨리 감기, <1 = 슬로우
        factor = 1.0 / speed                  # setpts 곱 팩터
        if not (SPEED_MIN <= speed <= SPEED_MAX) and not args.force:
            sys.exit(f"[중단] 오버레이 {o['n']}: 배속 {speed:.3f}× — 가드({SPEED_MIN}~{SPEED_MAX}×) 밖. "
                     f"구간 배정을 확인하거나 --force로 강행")

        out = out_dir / f"ov{o['n']}.mp4"
        encode(src, out, factor)
        out_dur = probe_duration(out)
        if seg - out_dur > OUT_SHORT_TOL:
            sys.exit(f"[오류] 오버레이 {o['n']}: 출력 {out_dur:.2f}s < 구간 {seg:.2f}s — 인코딩 이상")
        print(f"  ov{o['n']}: {src.name} {src_dur:.2f}s → {out_dur:.2f}s "
              f"(구간 {seg:.2f}s, 배속 {speed:.3f}×) [{o.get('label', '')}]")

    if changed:                               # src_dur 실측값 반영 (원자적 쓰기)
        tmp = args.timeline.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(args.timeline)
    print(f"[완료] 오버레이 {len(overlays)}개 → {out_dir}\\ov*.mp4")
    print("다음 단계: Step 7 캡처(미완료 시) → Step 8 assemble_capcut.py (video_overlays 자동 인식 — 4트랙)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
