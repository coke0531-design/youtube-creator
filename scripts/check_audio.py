"""녹음본 품질 게이트 — 클리핑·트루피크·라우드니스를 렌더 전에 수치로 잡는다.

왜 스크립트인가 (2026-08-17 실측):
  풀링012·013 완성본에서 "녹음이 깨지는 것처럼 들리는" 구간의 원인은 파이프라인이 아니라
  **녹음 원본의 입력 게인 과대**였다 — 파트 파일 대부분이 트루피크 -0.1 dBTP, 0dB 근접 샘플
  수백 개, 6샘플 이상 평탄/스파이크 런 수십 회(p13-1: 551/43/16). trim·concat·final 인코딩은
  원본을 그대로 보존(라우드니스 -18 LUFS 동일, 추가 손상 0). 이 게이트가 있었다면 녹음 직후에
  잡혔다. 판정 기준:
    - True Peak > -1.0 dBTP  → 경고 (유튜브·스트리밍 권장 상한 -1 dBTP; AAC 인코딩 오버슈트로 재생 시 찌그러짐)
    - 0.985 이상 샘플 런 ≥6개가 10회 이상 → 경고 (클리핑/과입력 흔적)
    - 통합 라우드니스 < -24 LUFS 또는 > -12 LUFS → 경고 (너무 작거나 큼; 유튜브 정규화 -14 LUFS 기준)
  경고가 있으면 재녹음(입력 게인 -6~-10dB, 피크 -6 dBFS 목표) 권고. 재녹음 불가 시 render_final.py의
  트루피크 리미터(기본 ON, --no-limiter로 끔)가 -1 dBTP로 눌러 재생 오버슈트만 막는다 — 이미 잘린
  파형은 복원하지 못한다.

사용:
  python check_audio.py <오디오 파일 또는 02_음성 폴더> [--strict]
  (폴더면 *.m4a/*.wav 전부, trim 사본·narration 포함)
"""
import argparse
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
TP_MAX = -1.0          # dBTP
LUFS_MIN, LUFS_MAX = -24.0, -12.0
CLIP_LEVEL = 0.985     # 정규화 진폭 — 이 위는 '0dB 근접'
RUN_MIN = 6            # 연속 샘플 수 — 이 이상이면 클리핑/스파이크 흔적
RUN_COUNT_WARN = 10


def measure(path: pathlib.Path) -> dict:
    # ebur128: 통합 라우드니스·트루피크
    o = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", o)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", o)
    res = {"lufs": float(lufs[-1]) if lufs else None, "tp": float(tp[-1]) if tp else None}
    # PCM 스캔: 0dB 근접 샘플·런
    try:
        import numpy as np
    except ImportError:
        res.update(over=None, runs=None, maxrun=None)
        return res
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    over = np.abs(x) > CLIP_LEVEL
    d = np.diff(np.concatenate([[0], over.astype(int), [0]]))
    runs = np.where(d == -1)[0] - np.where(d == 1)[0]
    res.update(over=int(over.sum()), runs=int((runs >= RUN_MIN).sum()), maxrun=int(runs.max()) if len(runs) else 0,
               dur=len(x) / 48000)
    return res


def judge(r: dict) -> list:
    w = []
    if r["tp"] is not None and r["tp"] > TP_MAX:
        w.append(f"트루피크 {r['tp']:+.1f} dBTP > {TP_MAX} (재생 시 찌그러짐 위험)")
    if r.get("runs") is not None and r["runs"] >= RUN_COUNT_WARN:
        w.append(f"클리핑 흔적: 0dB 근접 런(≥{RUN_MIN}샘플) {r['runs']}회, 최대 {r['maxrun']}샘플, 근접 샘플 {r['over']}개")
    if r["lufs"] is not None and not (LUFS_MIN <= r["lufs"] <= LUFS_MAX):
        w.append(f"라우드니스 {r['lufs']:.1f} LUFS 범위 밖({LUFS_MIN}~{LUFS_MAX})")
    return w


def main():
    ap = argparse.ArgumentParser(description="녹음본 품질 게이트 (트루피크·클리핑·라우드니스)")
    ap.add_argument("target")
    ap.add_argument("--strict", action="store_true", help="경고 있으면 exit 1")
    a = ap.parse_args()
    t = pathlib.Path(a.target)
    files = sorted([*t.glob("*.m4a"), *t.glob("*.wav"), *t.glob("*.mp3")]) if t.is_dir() else [t]
    if not files:
        sys.exit(f"[오류] 오디오 없음: {t}")
    total = 0
    for f in files:
        r = measure(f)
        w = judge(r)
        total += len(w)
        flag = "⚠" if w else "✓"
        print(f"{flag} {f.name}: TP {r['tp']:+.1f} dBTP · {r['lufs']:.1f} LUFS · 근접런 {r.get('runs')}회(max {r.get('maxrun')})")
        for x in w:
            print(f"     - {x}")
    if total:
        print(f"\n[권고] 경고 {total}건 — 근본 해결은 재녹음(입력 게인 -6~-10dB, 피크 -6 dBFS 목표). "
              "불가 시 render_final.py 리미터(기본 ON)가 -1 dBTP로 눌러 재생 오버슈트만 막는다.")
    sys.exit(1 if (a.strict and total) else 0)


if __name__ == "__main__":
    main()
