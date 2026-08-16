"""환경 진단 — 파이프라인이 요구하는 런타임을 한 번에 점검한다 (읽기 전용, 수리는 안 함).

새 기기 셋업 직후·오랜만의 작업 재개·원인 불명 실패 때 가장 먼저 실행한다.
검사: Python 버전 / pip 패키지(requirements.txt 대비) / ffmpeg 실행 / Playwright Chromium /
      CapCut 드래프트 폴더·비암호화 여부 / .env 키 존재(값은 출력 안 함) / 교정사전 JSON 파싱.

사용: python scripts/doctor.py    (exit 0 = 전부 통과, 1 = 결함 있음)
"""
import importlib.metadata as md
import json
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
DRAFT_ROOT = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / \
    "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
results = []  # (ok, critical, label, detail)


def check(ok, label, detail="", critical=True):
    results.append((bool(ok), critical, label, detail))
    mark = "✅" if ok else ("❌" if critical else "⚠️")
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))


def main() -> None:
    # 1) Python
    check(sys.version_info >= (3, 10), "Python ≥ 3.10", sys.version.split()[0])

    # 2) pip 패키지 (requirements.txt 대비)
    req = ROOT / "requirements.txt"
    pins = dict(re.findall(r"^([A-Za-z0-9_-]+)==([^\s#]+)", req.read_text(encoding="utf-8"), re.M)) \
        if req.is_file() else {}
    for pkg in ("pycapcut", "playwright", "imageio-ffmpeg", "opencv-python-headless", "numpy"):
        try:
            ver = md.version(pkg)
            pinned = pins.get(pkg)
            check(pinned is None or ver == pinned, f"패키지 {pkg}",
                  f"{ver}" + (f" (고정 {pinned}과 다름 — 검증 안 된 버전)" if pinned and ver != pinned else ""),
                  critical=False if pinned and ver != pinned else True)
        except md.PackageNotFoundError:
            check(False, f"패키지 {pkg}", "미설치 — python -m pip install -r requirements.txt")

    # 3) ffmpeg
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        p = subprocess.run([ff, "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        check(p.returncode == 0, "ffmpeg 실행", (p.stdout or "").splitlines()[0][:60])
    except Exception as ex:
        check(False, "ffmpeg 실행", str(ex)[:80])

    # 4) Playwright Chromium (설치 폴더 존재 — launch 없이 가볍게)
    pw_dir = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    chromes = list(pw_dir.glob("chromium-*")) if pw_dir.is_dir() else []
    check(bool(chromes), "Playwright Chromium",
          chromes[0].name if chromes else "없음 — python -m playwright install chromium")

    # 5) CapCut 드래프트 폴더 + 비암호화 확인 (아무 드래프트의 draft_content.json이 JSON으로 열리는가)
    if DRAFT_ROOT.is_dir():
        check(True, "CapCut 드래프트 폴더", str(DRAFT_ROOT))
        samples = list(DRAFT_ROOT.glob("*/draft_content.json"))[:3]
        if samples:
            ok = False
            for s in samples:
                try:
                    json.loads(s.read_text(encoding="utf-8"))
                    ok = True
                    break
                except Exception:
                    continue
            check(ok, "CapCut 드래프트 비암호화",
                  "" if ok else "draft_content.json 파싱 실패 — CapCut이 업데이트로 암호화됐을 수 있음(수동 폴백 필요)")
        else:
            check(True, "CapCut 드래프트 비암호화", "기존 드래프트 없음(첫 조립 후 재확인)", critical=False)
    else:
        check(False, "CapCut 드래프트 폴더", f"없음: {DRAFT_ROOT} — CapCut 설치/1회 실행 필요")

    # 6) .env 키 존재 (값은 절대 출력하지 않음)
    env = ROOT / ".env"
    if env.is_file():
        keys = set(re.findall(r"^([A-Z_]+)=", env.read_text(encoding="utf-8"), re.M))
        for k in ("OPENAI_API_KEY", "REPLICATE_API_TOKEN"):
            check(k in keys, f".env {k}", "" if k in keys else "없음 — Whisper/썸네일 단계에서 필요",
                  critical=(k == "OPENAI_API_KEY"))
    else:
        check(False, ".env", "없음 — OPENAI_API_KEY(전사)·REPLICATE_API_TOKEN(썸네일) 필요")

    # 7) 교정사전
    corr = ROOT / "레퍼런스" / "교정사전.json"
    try:
        json.loads(corr.read_text(encoding="utf-8"))
        check(True, "교정사전.json 파싱")
    except Exception as ex:
        check(False, "교정사전.json 파싱", str(ex)[:80], critical=False)

    bad = [r for r in results if not r[0] and r[1]]
    soft = [r for r in results if not r[0] and not r[1]]
    print(f"\n== 진단 결과: 치명 결함 {len(bad)}건, 주의 {len(soft)}건 / 총 {len(results)}항목")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
