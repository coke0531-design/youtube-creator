"""캡컷 조립 재료 스테이징 — 조립·검수에 필요한 파일만 '캡컷 조립 재료/'에 모은다 (youtube-editor Step 8.5).

왜 스크립트인가:
  "조립에 필요한 것"의 목록은 타임라인.json이 이미 기계적으로 알고 있다(오디오·SRT·오버레이).
  손으로 고르면 빠뜨리고, 대용량(capture.mp4)을 복사하면 낭비 — NTFS 하드링크로 용량 0 추가.

무엇을 하나:
  1. 타임라인.json에서 audio·srt·video_overlays를 읽고, capture.mp4·편집지시서.md를 더해
     대상 목록을 만든다 (쇼츠 type=short는 audio_source 사용).
  2. 작업 폴더에 '캡컷 조립 재료/'를 만들고 각 파일을 하드링크(os.link)로 건다.
     하드링크 실패(다른 볼륨 등) 시 복사로 폴백. 재실행 시 기존 항목을 지우고 새로 건다(멱등).
  3. 필수 파일(오디오·SRT·capture) 누락은 중단(fail-loud), 선택 파일(편집지시서·오버레이)은 경고.

주의:
  - 이 폴더는 **사람용 모음**이다. CapCut 드래프트(Step 8)는 원 위치(02_음성/ 등)를 절대경로로
    참조하므로, 원본 폴더를 지우면 드래프트 링크가 깨진다.
  - 하드링크는 내용을 공유한다 — 상류 단계가 파일을 재생성했으면 이 스크립트를 다시 실행한다.

사용:
  python stage_capcut_kit.py <타임라인.json> [--copy]   # --copy = 하드링크 대신 항상 복사
"""
import argparse
import json
import os
import pathlib
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

KIT_DIR = "캡컷 조립 재료"


def stage(src: pathlib.Path, dest_dir: pathlib.Path, force_copy: bool) -> str:
    dest = dest_dir / src.name
    if dest.exists():
        dest.unlink()                      # 멱등 — 항상 최신으로 다시 건다
    if not force_copy:
        try:
            os.link(src, dest)
            return "하드링크"
        except OSError:
            pass                           # 볼륨 다름/권한 등 → 복사 폴백
    shutil.copy2(src, dest)
    return "복사"


def main() -> None:
    ap = argparse.ArgumentParser(description="캡컷 조립 재료 스테이징 (하드링크)")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--copy", action="store_true", help="하드링크 대신 항상 복사")
    args = ap.parse_args()

    base = args.timeline.resolve().parent
    tl = json.loads(args.timeline.read_text(encoding="utf-8"))
    kind = tl.get("type", "main")

    audio = base / tl["audio" if kind == "main" else "audio_source"]
    srt = base / tl["srt"]
    capture = base / "04_영상소스" / "capture.mp4"
    required = [(audio, "오디오"), (srt, "자막 SRT"), (capture, "capture.mp4")]
    # 오버레이 모드에서는 ov<n>이 조립 필수 소재다 — 빠지면 kit이 불완전(선택 취급 금지)
    for o in (tl.get("video_overlays") or []):
        required.append((base / "04_영상소스" / f"ov{o['n']}.mp4", f"오버레이 ov{o['n']}"))
    optional = [(base / "편집지시서.md", "편집지시서"),
                (args.timeline.resolve(), "타임라인.json")]

    for f, label in required:
        if not f.is_file():
            sys.exit(f"[오류] 필수 파일 없음: {label} — {f}\n"
                     f"       상류 단계(트림/전사/캡처/오버레이 인코딩)를 먼저 완료하세요.")

    dest_dir = base / KIT_DIR
    dest_dir.mkdir(exist_ok=True)

    staged = 0
    for f, label in required + [(f, l) for f, l in optional if f.is_file()]:
        how = stage(f.resolve(), dest_dir, args.copy)
        print(f"  {label}: {f.name} ({how})")
        staged += 1
    for f, label in optional:
        if not f.is_file():
            print(f"  [경고] {label} 없음 — 건너뜀: {f}", file=sys.stderr)

    print(f"[완료] '{KIT_DIR}' {staged}개 항목 — 이 폴더 하나로 CapCut 수동 조합/검수 가능")
    print("       (자동 조립 드래프트는 원 폴더를 참조하므로 원 폴더는 지우지 마세요)")


if __name__ == "__main__":
    main()
