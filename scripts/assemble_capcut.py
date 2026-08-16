"""타임라인.json 기반으로 CapCut 드래프트(draft_content.json)를 자동 조립한다 (pycapcut).

트랙 3개: 나레이션(오디오) + 영상소스(비디오 = capture.mp4) + 자막(SRT 일괄 임포트).
- 본편(type=main): 오디오·비디오 전체를 t=0부터 배치
- 쇼츠(type=short): audio_cuts대로 원본 오디오를 쇼츠 타임라인에 컷 배치
- 본편에 video_overlays[]가 있으면 **4트랙**: 나레이션 / 슬라이드(capture.mp4) /
  영상소스(오버레이 ov<n>.mp4 — 슬라이드 위) / 자막. 오버레이 구간의 자막은 흰색
  (실사 영상 위 가독성), 나머지는 잉크색. ov<n>.mp4는 encode_overlays.py(Step 6.5)가
  구간 길이에 맞춰 배속 인코딩해 둔 것을 쓴다.

사용:
  python assemble_capcut.py <타임라인.json> --video <capture.mp4> [--name 드래프트명]
                            [--draft-root 경로] [--replace]

주의 (스킬 Step 8 주의사항과 동일):
- CapCut을 닫은 상태에서 실행한다 (켜져 있으면 중단 — 드래프트 덮어쓰기 위험)
- 소재 경로가 드래프트에 절대경로로 박힌다 — 조립 후 결과물 폴더 이동 금지
- SRT는 UTF-8이어야 한다
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pycapcut as cc
from pycapcut import TrackType, trange

# 한국어 Windows cp949 콘솔에서 특수문자 출력 크래시 방지 (trim_silence.py와 동일)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_DRAFT_ROOT = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / \
    "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
# 자막 세로 위치 (CapCut transform_y, 화면 중앙=0 / 하단=-1). 하단거리 = (1+transform_y)×(H/2).
# main: 자막-안전영역.md(16:9) 하단 약 162px → -0.70 / short: 세로-레이아웃.md(9:16) 하단 384px → -0.6
CAPTION_Y = {"main": -0.70, "short": -0.6}
# 자막 색 — 영상 소스는 흰 배경 고정(main·short 템플릿 모두 #ffffff)이라 잉크 #141413으로 임포트한다.
# (CapCut 임포트 기본색은 흰색이라 흰 배경에서 안 보임 — 자막-안전영역.md 색 규칙을 코드로 강제)
CAPTION_COLOR = (20 / 255, 20 / 255, 19 / 255)  # #141413 잉크
CAPTION_OVERLAY_COLOR = (1.0, 1.0, 1.0)          # 오버레이(실사 영상) 구간 흰색

# 2단계 드래프트 교체 상태 — 조립이 어떤 이유로든 중단되면 __main__ 가드가 기존 드래프트를 복원한다
_PENDING = {}


def _rollback() -> None:
    if not _PENDING:
        return
    shutil.rmtree(_PENDING["draft"], ignore_errors=True)          # 부분 생성물 제거
    backup = _PENDING.get("backup")
    if backup is not None and backup.exists():
        backup.rename(_PENDING["draft"])
        print("[복구] 조립 실패 — 기존 드래프트를 원상 복구했습니다", file=sys.stderr)
    _PENDING.clear()


def srt_time_us(value: str) -> int:
    hms, millis = value.split(",")
    hours, minutes, seconds = map(int, hms.split(":"))
    return ((hours * 3600 + minutes * 60 + seconds) * 1_000_000
            + int(millis) * 1_000)


def read_srt(path: pathlib.Path):
    """SRT 파싱 — (start_us, end_us, text) 제너레이터 (오버레이 구간별 자막 색 분기용)."""
    content = path.read_text(encoding="utf-8-sig").strip()
    for block in re.split(r"\r?\n\s*\r?\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start_text, end_text = lines[1].split(" --> ", 1)
        yield srt_time_us(start_text), srt_time_us(end_text), "\n".join(lines[2:])


def capcut_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return "CapCut.exe" in (r.stdout or "")


def main() -> None:
    ap = argparse.ArgumentParser(description="타임라인.json → CapCut 드래프트 자동 조립")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--video", type=pathlib.Path, help="캡처된 영상 소스 mp4 (기본: 타임라인 옆 04_영상소스/capture.mp4 또는 capture.mp4)")
    ap.add_argument("--name", help="드래프트 이름 (기본: 작업 폴더명)")
    ap.add_argument("--draft-root", type=pathlib.Path, default=DEFAULT_DRAFT_ROOT)
    ap.add_argument("--replace", action="store_true", help="같은 이름 드래프트가 있으면 교체")
    ap.add_argument("--force", action="store_true", help="CapCut 실행 중이어도 진행 (비권장)")
    args = ap.parse_args()

    if capcut_running() and not args.force:
        sys.exit("[중단] CapCut이 실행 중입니다 — 닫고 다시 실행하세요 (드래프트 덮어쓰기 위험).")
    if not args.draft_root.is_dir():
        sys.exit(f"[오류] CapCut 드래프트 폴더 없음: {args.draft_root}")

    base = args.timeline.parent
    tl = json.loads(args.timeline.read_text(encoding="utf-8"))
    kind = tl.get("type", "main")
    duration = float(tl["duration"])

    audio = (base / tl["audio" if kind == "main" else "audio_source"]).resolve()
    srt = (base / tl["srt"]).resolve()
    video = args.video
    if video is None:
        for cand in (base / "04_영상소스" / "capture.mp4", base / "capture.mp4"):
            if cand.is_file():
                video = cand
                break
    if video is None or not video.is_file():
        sys.exit("[오류] 영상 소스 mp4 없음 — capture_slides.py로 먼저 녹화하거나 --video 지정")
    for f, label in ((audio, "오디오"), (srt, "SRT")):
        if not f.is_file():
            sys.exit(f"[오류] {label} 없음: {f}")

    # 자막 글자수 강제 — 최종 드래프트가 항상 '한 컷 ≤MAX_CHARS자'가 되도록 choke point에서 보장한다.
    # 캡 값은 split_captions.MAX_CHARS 한 곳에서만 관리한다 (여기 하드코딩 금지).
    # 스킬이 split_captions.py를 이미 돌렸으면 멱등(무변경), 안 돌렸어도 여기서 분할된다.
    # 강제가 불가능하면(모듈/인코딩/분할 실패) 글자수 보장이 깨지므로 조용히 넘기지 않고 중단한다(fail loud).
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    try:
        import split_captions
    except ImportError as ex:
        sys.exit(f"[오류] split_captions.py 로드 실패로 자막 글자수 강제를 못 합니다: {ex}")
    cap = split_captions.MAX_CHARS
    try:
        st = split_captions.enforce_file(srt, max_chars=cap, mode="full")
    except UnicodeDecodeError:
        sys.exit(f"[오류] 자막 SRT가 UTF-8이 아닙니다 — UTF-8로 저장 후 다시 실행하세요: {srt}")
    except RuntimeError as ex:  # 분할 후에도 캡 초과가 남는 비정상 — 보장 위반
        sys.exit(f"[오류] 자막 {cap}자 강제 실패: {ex}")
    if st["changed"]:
        print(f"[자막] {cap}자 초과 {st['split']}개 컷 분할 ({st['in']}→{st['out']}컷). 원본 백업: {st['backup']}")

    # 싱크 계약 게이트 — SRT·SLIDE_TIMELINE·타임라인·미디어 일치를 조립 전에 기계 검증 (fail-loud)
    try:
        import validate_pipeline
    except ImportError as ex:
        sys.exit(f"[오류] validate_pipeline.py 로드 실패 — 싱크 검증 없이 조립하지 않습니다: {ex}")
    v_errors = validate_pipeline.run(args.timeline, media=True)
    if v_errors:
        for e in v_errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(f"[중단] 싱크 계약 위반 {len(v_errors)}건 — 해소 후 재실행 (scripts/validate_pipeline.py)")

    width, height = (1080, 1920) if kind == "short" else (1920, 1080)
    # 쇼츠는 폴더명이 short-NN이라 작업 간 충돌 — 작업 폴더명을 접두한다
    name = args.name or (f"{base.parent.parent.name}_{base.name}" if kind == "short" else base.name)

    # 본편 한정 오버레이 — ov<n>.mp4가 전부 준비돼 있어야 한다 (encode_overlays.py Step 6.5)
    overlays = (tl.get("video_overlays") or []) if kind == "main" else []
    for o in overlays:
        ov = (base / "04_영상소스" / f"ov{o['n']}.mp4").resolve()
        if not ov.is_file():
            sys.exit(f"[오류] 오버레이 소재 없음: {ov} — scripts/encode_overlays.py를 먼저 실행하세요")

    folder = cc.DraftFolder(str(args.draft_root))
    draft_dir = args.draft_root / name
    if draft_dir.exists():                        # 교체는 2단계 커밋 — 완성 전까지 기존본 보존
        if not args.replace:
            sys.exit(f"[중단] 드래프트 '{name}'이(가) 이미 있습니다 — 교체하려면 --replace, 새로 만들려면 --name 지정")
        backup_dir = args.draft_root / (name + ".bak")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        draft_dir.rename(backup_dir)
        _PENDING.update(draft=draft_dir, backup=backup_dir)
    else:
        _PENDING.update(draft=draft_dir, backup=None)
    script = folder.create_draft(name, width, height, allow_replace=False)
    script.add_track(TrackType.audio, "나레이션")
    if overlays:                        # 4트랙: 슬라이드(밑) + 영상소스 오버레이(위)
        script.add_track(TrackType.video, "슬라이드", relative_index=0)
        script.add_track(TrackType.video, "영상소스", relative_index=1)
    else:
        script.add_track(TrackType.video, "영상소스")
    script.add_track(TrackType.text, "자막")
    slide_track = "슬라이드" if overlays else "영상소스"

    # ① 오디오 트랙 — 구간은 실측 소재 길이로 클램핑 (타임라인 duration과 수ms 오차 가능)
    amat = cc.AudioMaterial(str(audio))
    if kind == "main":
        a_dur_us = min(amat.duration, int(duration * 1_000_000))
        if int(duration * 1_000_000) - amat.duration > 500_000:
            print(f"[경고] 오디오({amat.duration / 1e6:.1f}s)가 duration({duration:.1f}s)보다 짧음 — 뒷부분 무음", file=sys.stderr)
        script.add_segment(cc.AudioSegment(amat, trange(0, a_dur_us)), "나레이션")
    else:
        cuts = []
        for i, cut in enumerate(sorted(tl["audio_cuts"], key=lambda c: c["dst_start"]), 1):
            src_us = int(cut["src_start"] * 1_000_000)
            dst_us = int(cut["dst_start"] * 1_000_000)
            d_us = min(int(cut["src_end"] * 1_000_000), amat.duration) - src_us
            if d_us <= 0:
                sys.exit(f"[오류] 컷 {i}: src 구간이 오디오 길이({amat.duration / 1e6:.1f}s) 밖 — "
                         f"타임라인.json audio_cuts와 오디오가 어긋남(스킵하면 쇼츠 오디오가 조용히 빠진다)")
            if d_us < int((cut["src_end"] - cut["src_start"]) * 1_000_000):
                print(f"[경고] 컷 {i}: src_end가 오디오 길이를 초과해 {d_us / 1e6:.2f}s로 잘림", file=sys.stderr)
            cuts.append([dst_us, src_us, d_us])
        for i in range(1, len(cuts)):
            overlap = cuts[i - 1][0] + cuts[i - 1][2] - cuts[i][0]
            if overlap > 500_000:
                sys.exit(f"[오류] audio_cuts 겹침 {overlap / 1e6:.2f}s (컷 {i}↔{i + 1}) — 타임라인.json의 dst_start를 수정하세요")
            if overlap > 0:  # 반올림 수준 겹침은 앞 컷을 줄여 흡수 (dst 앵커 = 싱크 보존)
                cuts[i - 1][2] -= overlap
        for dst_us, src_us, d_us in cuts:
            script.add_segment(
                cc.AudioSegment(amat, trange(dst_us, d_us), source_timerange=trange(src_us, d_us)),
                "나레이션")

    # ② 비디오 트랙 — 캡처 mp4를 t=0부터 (mp4가 duration보다 짧으면 mp4 길이만큼)
    material = cc.VideoMaterial(str(video))
    vid_dur_us = min(material.duration, int(duration * 1_000_000))
    if int(duration * 1_000_000) - material.duration > 500_000:
        print(f"[경고] capture.mp4({material.duration / 1e6:.1f}s)가 duration({duration:.1f}s)보다 짧음 — 캡처 조기 종료 여부 확인", file=sys.stderr)
    script.add_segment(cc.VideoSegment(material, trange(0, vid_dur_us)), slide_track)

    # ②-1 영상소스 오버레이 — 슬라이드 위에 구간 길이로 정확히 트림해 배치(인코딩 오버슛 제거), 무음
    for o in overlays:
        ov = (base / "04_영상소스" / f"ov{o['n']}.mp4").resolve()
        om = cc.VideoMaterial(str(ov))
        scene_us = int(round((o["end"] - o["start"]) * 1_000_000))
        place_us = min(om.duration, scene_us)
        if scene_us - om.duration > 300_000:
            print(f"[경고] 오버레이 {o['n']}: 소재({om.duration / 1e6:.2f}s)가 구간({scene_us / 1e6:.2f}s)보다 짧음 — encode_overlays.py 재실행 검토", file=sys.stderr)
        start_us = int(round(o["start"] * 1_000_000))
        script.add_segment(
            cc.VideoSegment(om, trange(start_us, place_us),
                            source_timerange=trange(0, place_us), volume=0.0),
            "영상소스")
        print(f"  오버레이 영상{o['n']}: {o['start']:.2f}s +{place_us / 1e6:.2f}s ({ov.name})")

    # ③ 자막 트랙 — 하단 배치 + 잉크(#141413) 색. 크기·정렬은 import_srt 기본(size 5·중앙·자동줄바꿈)
    #    그대로 유지하고 색만 바꾼다(기본 색은 흰색이라 흰 배경에서 안 보임). 폰트 미세조정은 CapCut에서.
    #    오버레이가 있으면 겹치는 컷만 흰색으로 — 실사 영상 위 가독성 (풀링_011 방식).
    if overlays:
        # style=whiteboard(화이트보드 드로잉, 흰 배경)는 자막을 잉크색 그대로 둔다 — 흰 글자가 안 보임
        overlay_ranges = [(int(round(o["start"] * 1_000_000)), int(round(o["end"] * 1_000_000)))
                          for o in overlays if o.get("style") != "whiteboard"]
        ink_style = cc.TextStyle(size=5, align=1, auto_wrapping=True, color=CAPTION_COLOR)
        white_style = cc.TextStyle(size=5, align=1, auto_wrapping=True, color=CAPTION_OVERLAY_COLOR)
        caption_clip = cc.ClipSettings(transform_y=CAPTION_Y[kind])
        caption_count = white_count = 0
        for start_us, end_us, text in read_srt(srt):
            on_overlay = any(start_us < oe and end_us > os_ for os_, oe in overlay_ranges)
            script.add_segment(
                cc.TextSegment(text, trange(start_us, end_us - start_us),
                               style=white_style if on_overlay else ink_style,
                               clip_settings=caption_clip),
                "자막")
            caption_count += 1
            white_count += int(on_overlay)
        print(f"  자막: {caption_count}개 (오버레이 구간 흰색 {white_count}개, 기본 잉크색 {caption_count - white_count}개)")
    else:
        script.import_srt(str(srt), "자막",
                          text_style=cc.TextStyle(size=5, align=1, auto_wrapping=True, color=CAPTION_COLOR),
                          clip_settings=cc.ClipSettings(transform_y=CAPTION_Y[kind]))

    script.save()
    backup = _PENDING.get("backup")               # 교체 성공 확정 — 백업본 정리
    if backup is not None and backup.exists():
        shutil.rmtree(backup)
    _PENDING.clear()
    n_tracks = 4 if overlays else 3
    print(f"[완료] 드래프트 '{name}' 생성 ({width}x{height}, {duration:.1f}s, {n_tracks}트랙)")
    print(f"  오디오: {audio}\n  비디오: {video}\n  자막:  {srt}")
    print("CapCut을 열면 드래프트 목록에 보입니다 — 검수 후 내보내기는 직접 하세요.")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        _rollback()
        raise
