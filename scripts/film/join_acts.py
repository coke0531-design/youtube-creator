# -*- coding: utf-8 -*-
"""막(act) 캡처들을 이어 붙이고 이음매를 검사한다 (v3.1 막 단위 실험용).

  python join_acts.py --acts capture_E1.mp4 capture_E2.mp4 ... --out capture.mp4 [--json seams.json]

- 이음매 검사: 막 N의 마지막 프레임과 막 N+1의 첫 프레임을 픽셀 비교(같은 HANDOFF 함수로 그렸다면 인코더 잡음만 남는다).
  mean_diff ≤ 2.0 · max_diff ≤ 80 이면 OK(인코더 잡음), 아니면 FAIL(이음매 불일치).
- 이어 붙이기: ffmpeg concat demuxer -c copy (같은 인코더 설정이어야 한다).
- 길이 합계를 출력한다(오디오 길이와 대조용).

종료 코드: 0 OK / 1 이음매 FAIL / 2 입력 오류
"""
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def die(m):
    print(m, file=sys.stderr); raise SystemExit(2)


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        die("[입력 오류] ffmpeg 없음")


def edge_frames(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS)
    ok, first = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, n - 1); ok2, last = cap.read()
    if not ok2:  # 일부 컨테이너는 마지막 인덱스가 어긋난다
        cap.set(cv2.CAP_PROP_POS_FRAMES, n - 2); ok2, last = cap.read()
    cap.release()
    if not (ok and ok2):
        die(f"[입력 오류] 프레임을 못 읽음: {path}")
    return first, last, n, fps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acts", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--json")
    ap.add_argument("--mean-max", type=float, default=2.0)
    ap.add_argument("--max-max", type=float, default=80.0)  # 인코더 잡음(nvenc cq19) 최대 60~65 실측, 여유 80
    ap.add_argument("--no-concat", action="store_true")
    a = ap.parse_args()
    import numpy as np
    acts = [Path(p) for p in a.acts]
    for p in acts:
        if not p.exists():
            die(f"[입력 오류] 없음: {p}")
    info = [edge_frames(p) for p in acts]
    total_frames = sum(i[2] for i in info); fps = info[0][3]
    seams, rc = [], 0
    for k in range(len(acts) - 1):
        last = info[k][1].astype(np.int16); first = info[k + 1][0].astype(np.int16)
        if last.shape != first.shape:
            die(f"[입력 오류] 해상도 불일치: {acts[k].name} vs {acts[k+1].name}")
        d = np.abs(last - first); px = d.max(axis=2)
        mean, mx, diffpx = float(d.mean()), int(d.max()), int((px > 8).sum())
        level = "OK" if (mean <= a.mean_max and mx <= a.max_max) else "FAIL"
        if level == "FAIL":
            rc = 1
        seams.append({"from": acts[k].name, "to": acts[k + 1].name, "mean_diff": round(mean, 3),
                      "max_diff": mx, "pixels_over_8": diffpx, "level": level})
        print(f"[이음매] {acts[k].name} → {acts[k+1].name}: mean {mean:.3f} · max {mx} · >8인 픽셀 {diffpx}  {level}")
    print(f"[합계] {len(acts)}막 {total_frames}프레임 @{fps:g}fps = {total_frames / fps:.2f}s")
    if not a.no_concat:
        ff = ffmpeg(); out = Path(a.out).resolve()
        fd, name = tempfile.mkstemp(suffix=".txt", dir=str(out.parent)); import os; os.close(fd)
        lst = Path(name)
        lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in acts), encoding="utf-8")
        p = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)], capture_output=True)
        lst.unlink(missing_ok=True)
        if p.returncode != 0:
            print(f"[실패] concat: {p.stderr.decode('utf-8', 'replace')[-500:]}", file=sys.stderr); return 1
        print(f"[완료] {out}")
    if a.json:
        Path(a.json).write_text(json.dumps({"acts": [str(p) for p in acts], "seams": seams,
                                            "total_frames": total_frames, "fps": fps}, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
