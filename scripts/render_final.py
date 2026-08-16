"""완성본 mp4를 만든다 (opt-in — 캡컷 검수를 생략할 때의 선택지). 엔진 2종: remotion | ffmpeg.

왜 이 스크립트인가:
  기본 파이프라인은 "무음 capture.mp4 + CapCut 드래프트"까지만 만들고, 최종 합성(오디오·자막·
  오버레이 얹기)은 사람이 CapCut에서 검수·내보내기 한다. 이 스크립트는 그 검수를 생략하고 바로
  완성본 mp4를 뽑고 싶을 때만 쓰는 별도 경로다 — 기존 파이프라인(스킬·scripts·템플릿)은 건드리지
  않는다. 입력 해석·자막 색·자막 위치·오버레이 로직은 assemble_capcut.py를 그대로 미러링한다.

무엇을 하나 (작업 폴더의 타임라인.json 기준, 두 엔진 공통 전처리):
  1. 싱크 계약 검증 — validate_pipeline.run (위반 시 중단, fail-loud).
  2. 자막 16자 강제 — split_captions.enforce_file (assemble_capcut.py와 동일한 choke point,
     캡 값은 split_captions.MAX_CHARS 한 곳에서 import).
  3. 입력(capture.mp4 · narration.m4a · full.srt · ov<n>.mp4 · 타임라인) 해석.
  이후 엔진별로:
  - remotion: 리모션/public/job/ 스테이징 → `npm run final` → 리모션/out/final.mp4 복사.
  - ffmpeg : SRT→ASS 변환 후 filter_complex(오버레이 overlay + ass 자막 굽기)로 직접 인코딩.

본편 vs 쇼츠 (타임라인.json의 type으로 자동 감지 — assemble_capcut.py와 동일 판정):
  - 본편(type=main, 16:9): capture를 1920x1080으로 정규화, 나레이션 전체를 t=0부터, ov 오버레이 지원.
  - 쇼츠(type=short, 9:16, ffmpeg 엔진 한정): capture를 1080x1920으로 정규화, audio_cuts대로
    나레이션에서 구간을 잘라(atrim+concat) 이어붙임(assemble_capcut.py short 분기와 동일 결과),
    자막은 ASS PlayRes 1080x1920 · CAPTION_Y["short"] 하단 384px. 쇼츠 폴더(05_쇼츠/short-NN)를
    그대로 job 인자로 주면 된다.

엔진 기본값:
  기본 = ffmpeg (2026-07-23 실측 확정: 같은 343초 영상 기준 remotion 약 29분 /
  ffmpeg libx264 약 3.5분 / --nvenc 약 69초, 시각 결과 동등 — 리모션/README.md 벤치마크 참조).
  remotion 엔진은 --engine remotion으로 유지(향후 슬라이드 자체를 Remotion으로 그리는 시점의 경로).

미지원:
  - 쇼츠 + remotion 엔진 — 쇼츠는 ffmpeg 엔진(기본)만 지원, remotion 쇼츠는 CapCut 경로를 쓰세요.
  - 쇼츠 영상 오버레이(ov<n>.mp4) — 스키마에 쇼츠 오버레이가 없어 미구현(assemble_capcut.py도
    short 분기에서 오버레이를 무시한다). 쇼츠 자막은 전부 잉크색.

사용:
  python render_final.py <작업 폴더>                       # ffmpeg (기본: NVENC 자동, 불가 시 libx264 폴백) — 본편/쇼츠 자동
  python render_final.py <쇼츠 폴더 05_쇼츠/short-NN>       # 쇼츠 자동 감지(1080x1920)
  python render_final.py <작업 폴더> --x264                # libx264(crf17) 강제 (CPU 인코딩)
  python render_final.py <작업 폴더> --engine remotion      # Remotion 경로 (본편만)
  python render_final.py <작업 폴더> --out final_v2.mp4    # 출력 파일명 지정
  python render_final.py <작업 폴더> --dry-run             # 검증·ASS·명령만(인코딩 안 함)
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

# 한국어 Windows cp949 콘솔에서 특수문자 출력 크래시 방지 (다른 scripts와 동일)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = pathlib.Path(__file__).resolve().parent.parent
REMOTION = REPO / "리모션"
JOB_DIR = REMOTION / "public" / "job"
RENDER_OUT = REMOTION / "out" / "final.mp4"

# ── ffmpeg 자막(ASS) 규격 — 본편은 FinalVideo.tsx/자막-안전영역.md(16:9), 쇼츠는
#    세로-레이아웃.md(9:16)를 픽셀로 환산. kind별로 PlayRes·크기·여백만 다르고 폰트·색은 공통. ──
# 폰트   : Pretendard  (design.md §2-3 · 자막-안전영역.md/세로-레이아웃.md 폰트 표 · FinalVideo FONT_STACK 1순위)
# 크기   : 60px @1080p (FinalVideo.tsx fontSize:60 — 두 규격 모두 "56px 이상"을 실제로 쓴 값. 쇼츠도 동일 물리크기)
# 색     : #141413 잉크. ASS는 &HAABBGGRR 순서라 R=14 G=14 B=13 → BBGGRR=13 14 14 → &H00131414.
#          assemble_capcut.py CAPTION_COLOR(#141413)·FinalVideo COLORS.ink와 동일. 본편 오버레이(실사) 구간만 흰색.
ASS_FONT = "Pretendard"
ASS_STYLE_INK = "&H00131414"
ASS_OVERRIDE_WHITE = "{\\c&H00FFFFFF&}"          # 컷 단위 흰색 오버라이드 (&HFFFFFF) — 본편 오버레이 구간 한정
# kind별 규격:
#  - playres            : ASS PlayRes = 렌더 정규화 해상도(본편 1920x1080 / 쇼츠 1080x1920).
#  - fontsize           : 60px (자막-안전영역.md·세로-레이아웃.md "56px 이상" 공통).
#  - margin_lr          : 좌우 여백. 본편=160px(FinalVideo padding '0 160px') /
#                         쇼츠=48px(세로-레이아웃.md 세로 콘텐츠 좌우 패딩 48px → 유효 폭 984px).
#  - center_from_bottom : 자막 '중심'의 하단거리. CAPTION_Y로 환산 = (1+transform_y)×(H/2).
#                         본편 -0.70 → (1-0.70)×540=162 / 쇼츠 -0.60 → (1-0.60)×960=384 (세로-레이아웃 문서 '하단 384px').
ASS_SPEC = {
    "main":  {"playres": (1920, 1080), "fontsize": 60, "margin_lr": 160, "center_from_bottom": 162},
    "short": {"playres": (1080, 1920), "fontsize": 60, "margin_lr": 48,  "center_from_bottom": 384},
}


def _ass_params(kind: str):
    """kind별 ASS 규격 → (playres, fontname, fontsize, margin_lr, margin_v). MarginV 산식은 본편과 동일.

    ASS Alignment=2(하단 정렬)의 MarginV는 '텍스트 하단↔화면 하단' 거리다. FinalVideo/CapCut은 자막
    '중심'을 center_from_bottom에 놓으므로, 중심을 맞추려면 절반 줄높이만큼 내려 준다(162-37=125 / 384-37=347)."""
    spec = ASS_SPEC[kind]
    fontsize = spec["fontsize"]
    line_h = round(fontsize * 1.25)              # FinalVideo lineHeight:1.25 → 75px
    margin_v = spec["center_from_bottom"] - line_h // 2
    return spec["playres"], ASS_FONT, fontsize, spec["margin_lr"], margin_v


def _stage(src: pathlib.Path, dest: pathlib.Path) -> str:
    """하드링크 시도 → 실패(다른 볼륨·권한 등) 시 복사 폴백 (stage_capcut_kit.py와 동일 방식)."""
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
        return "하드링크"
    except OSError:
        shutil.copy2(src, dest)
        return "복사"


# ── 공통 전처리 (엔진 무관) ────────────────────────────────────────────────────
def _resolve_inputs(base: pathlib.Path, tl: dict):
    """audio·srt·video·overlays·ov_files 해석 — assemble_capcut.py와 동일 규칙 (fail-loud).

    오디오 키: 본편=tl["audio"](전체 나레이션) / 쇼츠=tl["audio_source"](구간을 잘라 쓸 원본 나레이션).
    오버레이: 본편만 — 쇼츠는 스키마에 오버레이가 없어 assemble_capcut.py처럼 무시한다."""
    kind = tl.get("type", "main")
    audio = (base / tl["audio" if kind == "main" else "audio_source"]).resolve()
    srt = (base / tl["srt"]).resolve()
    video = None
    for cand in (base / "04_영상소스" / "capture.mp4", base / "capture.mp4"):
        if cand.is_file():
            video = cand
            break
    if video is None:
        sys.exit("[오류] 영상 소스 mp4 없음 — capture_slides.py로 먼저 녹화하세요 (04_영상소스/capture.mp4)")
    for f, label in ((audio, "오디오"), (srt, "SRT"), (video, "capture.mp4")):
        if not f.is_file():
            sys.exit(f"[오류] {label} 없음: {f}")

    overlays = (tl.get("video_overlays") or []) if kind == "main" else []
    ov_files = {}
    for o in overlays:
        ov = (base / "04_영상소스" / f"ov{o['n']}.mp4").resolve()
        if not ov.is_file():
            sys.exit(f"[오류] 오버레이 소재 없음: {ov} — scripts/encode_overlays.py를 먼저 실행하세요")
        ov_files[o["n"]] = ov
    return audio, srt, video, overlays, ov_files


def _gate_and_enforce(timeline: pathlib.Path, srt: pathlib.Path):
    """싱크 계약 게이트 + 자막 16자 강제 — 두 엔진 공통, assemble_capcut.py와 동일 choke point."""
    # ① 싱크 계약 — SRT·SLIDE_TIMELINE·타임라인·미디어 일치를 렌더 전에 기계 검증 (fail-loud)
    try:
        import validate_pipeline
    except ImportError as ex:
        sys.exit(f"[오류] validate_pipeline.py 로드 실패 — 싱크 검증 없이 렌더하지 않습니다: {ex}")
    v_errors = validate_pipeline.run(timeline, media=True)
    if v_errors:
        for e in v_errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(f"[중단] 싱크 계약 위반 {len(v_errors)}건 — 해소 후 재실행 (scripts/validate_pipeline.py)")

    # ② 자막 16자 강제 — 캡 값은 split_captions에서 import (여기 하드코딩 금지)
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


# ── 리모션 엔진 (기존 동작 — 불변) ────────────────────────────────────────────
def _render_remotion(base, tl, audio, srt, video, overlays, ov_files):
    # ③ 스테이징 — public/job/ 을 비우고 시작 (하드링크 → 실패 시 복사)
    if JOB_DIR.exists():
        shutil.rmtree(JOB_DIR)
    JOB_DIR.mkdir(parents=True)
    staged = [
        ("capture.mp4", _stage(video, JOB_DIR / "capture.mp4")),
        ("narration.m4a", _stage(audio, JOB_DIR / "narration.m4a")),
        ("full.srt", _stage(srt, JOB_DIR / "full.srt")),
    ]
    for n, ov in ov_files.items():
        staged.append((f"ov{n}.mp4", _stage(ov, JOB_DIR / f"ov{n}.mp4")))
    # 타임라인은 ASCII 이름으로 기록 — staticFile 한글 URL 이슈 회피 (video_overlays만 있으면 됨)
    (JOB_DIR / "timeline.json").write_text(
        json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    for name, how in staged:
        print(f"  스테이징: {name} ({how})")
    print(f"  스테이징: timeline.json (복사)")

    # ④ 리모션 렌더 — npm run final (npx 직접 호출은 보안 훅이 차단하므로 npm 스크립트 경유)
    npm = shutil.which("npm") or "npm"  # Windows에서 npm.cmd 절대경로 확보
    print("[렌더] npm run final 실행 — 영상 길이에 따라 수 분 걸릴 수 있습니다...")
    proc = subprocess.run([npm, "run", "final"], cwd=str(REMOTION))  # stdout/err 상속(진행·에러 그대로 노출)
    if proc.returncode != 0:
        sys.exit(f"[실패] 리모션 렌더 실패 (npm run final exit {proc.returncode}) — 위 로그의 에러 전문을 확인하세요.")

    # ⑤ 산출물 → 작업 폴더/완성본/final.mp4
    if not RENDER_OUT.is_file():
        sys.exit(f"[실패] 렌더 산출물이 없습니다: {RENDER_OUT}")
    dest_dir = base / "완성본"
    dest_dir.mkdir(exist_ok=True)
    final_dest = dest_dir / "final.mp4"
    shutil.copy2(RENDER_OUT, final_dest)

    size_mb = final_dest.stat().st_size / (1024 * 1024)
    print(f"[완료] 완성본: {final_dest} ({size_mb:.1f} MB)")
    print(f"  입력  오디오 : {audio}")
    print(f"  입력  비디오 : {video}")
    print(f"  입력  자막   : {srt}")
    print(f"  오버레이     : {len(overlays)}개")
    print("  (이 경로는 캡컷 검수를 생략한 선택지입니다 — 기본은 여전히 CapCut 드래프트 검수 후 내보내기)")


# ── ffmpeg 엔진 ───────────────────────────────────────────────────────────────
def _ass_time(t: float) -> str:
    """초 → ASS 타임코드 h:mm:ss.cc (센티초)."""
    if t < 0:
        t = 0.0
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """ASS Dialogue 텍스트 이스케이프 — 중괄호(오버라이드 블록 문자)·줄바꿈(\\N)."""
    text = text.replace("{", "\\{").replace("}", "\\}")   # 리터럴 중괄호 (libass는 \{ \} 지원)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
    return text


def _srt_sec(value: str) -> float:
    hms, ms = value.strip().split(",")
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms) / 1000.0


def _read_srt_cues(path: pathlib.Path):
    """SRT 파싱 → (start_s, end_s, text). text는 원문 줄바꿈 보존(이후 \\N 변환)."""
    content = path.read_text(encoding="utf-8-sig").strip()
    for block in re.split(r"\r?\n\s*\r?\n", content):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start_text, end_text = lines[1].split(" --> ", 1)
        yield _srt_sec(start_text), _srt_sec(end_text), "\n".join(lines[2:])


def _build_ass(srt: pathlib.Path, overlays: list, kind: str = "main") -> tuple[str, int, int]:
    """SRT → ASS 문자열. 오버레이 구간과 겹치는 컷만 흰색 오버라이드 (assemble_capcut.py와 동일 판정).

    kind로 PlayRes·크기·여백만 갈린다(본편 16:9 / 쇼츠 9:16). 쇼츠는 overlays=[]라 전부 잉크색.
    반환: (ass_text, 전체 컷 수, 흰색 컷 수)."""
    (resx, resy), fontname, fontsize, margin_lr, margin_v = _ass_params(kind)
    # 오버레이 구간(초) — assemble_capcut.py: on_overlay = any(start < oe and end > os)
    #  style=whiteboard(흰 배경 드로잉)는 제외 — 자막 잉크색 유지 (assemble_capcut.py와 동일)
    ov_ranges = [(float(o["start"]), float(o["end"])) for o in overlays if o.get("style") != "whiteboard"]

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {resx}",
        f"PlayResY: {resy}",
        "WrapStyle: 0",                     # 0 = 스마트 자동 줄바꿈
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        # Bold=-1(900 상당), Outline=0/Shadow=0(FinalVideo에 외곽선·그림자 없음), Alignment=2(하단 중앙)
        (f"Style: Default,{fontname},{fontsize},{ASS_STYLE_INK},&H000000FF,&H00000000,"
         f"&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,"
         f"{margin_lr},{margin_lr},{margin_v},1"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events, total, white = [], 0, 0
    for cs, ce, text in _read_srt_cues(srt):
        on_overlay = any(cs < oe and ce > os_ for os_, oe in ov_ranges)
        payload = _ass_escape(text)
        if on_overlay:
            payload = ASS_OVERRIDE_WHITE + payload
            white += 1
        total += 1
        events.append(
            f"Dialogue: 0,{_ass_time(cs)},{_ass_time(ce)},Default,,0,0,0,,{payload}")
    return "\n".join(header + events) + "\n", total, white


def _build_filter(overlays: list, playres: tuple = (1920, 1080)) -> str:
    """filter_complex 구성: capture(바닥) + 각 ov를 start~end 구간에 overlay + ass 자막 굽기.

    - ov 입력 index는 overlays 순서와 1:1 ([1:v]=overlays[0] ...). 오디오는 마지막 입력.
    - ov는 자기 t=0부터 시작하므로 setpts로 타임스탬프를 start만큼 밀어 t=start에 첫 프레임이 오게 한다.
    - ass 필터 경로는 'subs.ass' 상대명 — Windows 한글/콜론/역슬래시 이스케이프 함정을 cwd 고정으로 우회
      (실제 파일은 JOB_DIR에 스테이징하고 subprocess cwd=JOB_DIR).
    - 바닥은 반드시 playres로 정규화한다(본편 1920x1080 / 쇼츠 1080x1920): capture.mp4가 고해상도
      (본편 실측 2560x1440, 쇼츠 1440x2560)로 캡처된 경우 그대로 두면 오버레이(1080p 소재)가 좌상단에만
      얹히고 ASS PlayRes 자막 좌표도 어긋난다.
    """
    w, h = playres
    parts, cur = [f"[0:v]scale={w}:{h}:flags=lanczos[base]"], "[base]"
    for i, o in enumerate(overlays, start=1):        # 입력 index i (0=capture, N+1=audio)
        s, e = float(o["start"]), float(o["end"])
        parts.append(f"[{i}:v]setpts=PTS-STARTPTS+{s:.3f}/TB[ov{i}]")
        nxt = f"[b{i}]"
        parts.append(
            f"{cur}[ov{i}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'{nxt}")
        cur = nxt
    parts.append(f"{cur}ass=subs.ass[vout]")         # 상대 경로 (cwd=JOB_DIR) — 이스케이프 함정 우회
    return ";".join(parts)


def _short_audio_cuts(audio_cuts: list, audio_dur_s: float) -> list:
    """쇼츠 audio_cuts → [[dst_s, src_s, dur_s], ...] (dst 순). assemble_capcut.py short 분기와 동일 산식:
    src_end를 오디오 길이로 클램프, dst 순으로 정렬, 반올림 수준 겹침(≤0.5s)은 앞 컷을 줄여 흡수하고
    0.5s 초과 겹침은 중단(fail-loud). d≤0(구간이 오디오 밖)도 중단."""
    cuts = []
    for i, cut in enumerate(sorted(audio_cuts, key=lambda c: c["dst_start"]), 1):
        src = float(cut["src_start"])
        dst = float(cut["dst_start"])
        d = min(float(cut["src_end"]), audio_dur_s) - src
        if d <= 0:
            sys.exit(f"[오류] 컷 {i}: src 구간이 오디오 길이({audio_dur_s:.1f}s) 밖 — "
                     f"타임라인.json audio_cuts와 오디오가 어긋남(스킵하면 쇼츠 오디오가 조용히 빠진다)")
        if d < float(cut["src_end"]) - src:
            print(f"[경고] 컷 {i}: src_end가 오디오 길이를 초과해 {d:.2f}s로 잘림", file=sys.stderr)
        cuts.append([dst, src, d])
    for i in range(1, len(cuts)):
        overlap = cuts[i - 1][0] + cuts[i - 1][2] - cuts[i][0]
        if overlap > 0.5:
            sys.exit(f"[오류] audio_cuts 겹침 {overlap:.2f}s (컷 {i}↔{i + 1}) — 타임라인.json의 dst_start를 수정하세요")
        if overlap > 0:  # 반올림 수준 겹침은 앞 컷을 줄여 흡수 (dst 앵커 = 싱크 보존)
            cuts[i - 1][2] -= overlap
    return cuts


def _build_short_filter(cuts: list, audio_idx: int, playres: tuple) -> str:
    """쇼츠 filter_complex: 비디오 정규화+자막 굽기 + audio_cuts atrim/concat.

    오디오는 나레이션(입력 audio_idx)에서 각 컷 [src, src+dur]을 atrim으로 뽑아 asetpts로 t=0 리셋하고
    dst 순서대로 concat 한다 → 결과 오디오 길이 = 컷 길이 합(assemble_capcut.py와 동일 결과).
    비디오(capture)는 duration 전체를 유지하므로, 컷 합 < duration이면 뒤쪽 CTA 구간은 무음 꼬리가 된다."""
    w, h = playres
    video_part = f"[0:v]scale={w}:{h}:flags=lanczos[base];[base]ass=subs.ass[vout]"
    a_parts, labels = [], []
    for i, (_dst, src, d) in enumerate(cuts):
        lbl = f"a{i}"
        a_parts.append(
            f"[{audio_idx}:a]atrim=start={src:.3f}:end={src + d:.3f},asetpts=PTS-STARTPTS[{lbl}]")
        labels.append(f"[{lbl}]")
    a_parts.append("".join(labels) + f"concat=n={len(cuts)}:v=0:a=1[aout]")
    return video_part + ";" + ";".join(a_parts)


def _encode_with_progress(cmd: list, duration: float) -> int:
    """ffmpeg를 JOB_DIR cwd로 실행하며 -progress pipe:1의 out_time_us를 duration으로 나눠 진행률 표시.
    stderr는 상속(미리다이렉트 안 함)이라 실패 시 ffmpeg 에러 전문이 그대로 노출된다. 반환: 종료 코드."""
    proc = subprocess.Popen(cmd, cwd=str(JOB_DIR), stdout=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    last_pct = -1
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_us=") and duration > 0:
            try:
                cur_s = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            pct = min(100, int(cur_s / duration * 100))
            if pct != last_pct:
                last_pct = pct
                print(f"\r  인코딩 {pct:3d}%  ({cur_s:6.1f}s / {duration:.1f}s)", end="", flush=True)
        elif line == "progress=end":
            print()
    proc.wait()
    return proc.returncode


def _pick_encoder(force_nvenc: bool, force_x264: bool) -> bool:
    """인코더 자동 선택 — NVENC 가용하면 h264_nvenc(기본), 아니면 libx264 폴백.

    2026-07-23 실측(343초 실전 샘플, 무손실 참조 대비): nvenc cq19 SSIM 0.999835 ≥ x264 crf17
    0.999749, 렌더 2.1배 빠름(47s vs 99s), 파일 1.5배 큼 — 화질 동등 이상이라 nvenc를 기본으로 한다.
    가용성은 인코더 목록이 아니라 1프레임 시험 인코딩으로 판정한다(빌드에 인코더가 있어도
    NVIDIA GPU/드라이버가 없으면 런타임에야 실패하므로). --x264로 CPU 강제, --nvenc는 불가 시 fail-loud."""
    if force_x264:
        return False
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
         "-c:v", "h264_nvenc", "-f", "null", "-"],
        capture_output=True)
    ok = probe.returncode == 0
    if force_nvenc and not ok:
        sys.exit("[오류] --nvenc 지정됐지만 h264_nvenc 시험 인코딩 실패 — NVIDIA GPU/드라이버를 확인하세요 (--x264로 CPU 인코딩 가능)")
    if not ok:
        print("[인코더] NVENC 시험 인코딩 실패 → libx264(crf17)로 폴백합니다")
    return ok


def _ffmpeg_cmd(ff, video, overlays, ov_files, audio, filtergraph, out_path, nvenc):
    """ffmpeg argv 구성. 화질: libx264 crf17 preset medium (FinalVideo 렌더와 동급) / --nvenc는 cq19."""
    cmd = [ff, "-hide_banner", "-y", "-i", str(video)]
    for o in overlays:                               # ov 입력 순서 = filter의 [i:v] 순서와 반드시 일치
        cmd += ["-i", str(ov_files[o["n"]])]
    cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", filtergraph]
    cmd += ["-map", "[vout]", "-map", f"{1 + len(overlays)}:a"]   # 오디오 = 마지막 입력
    if nvenc:
        # h264_nvenc, cq 19 수준 (VBR, 비트레이트 상한 없음 → 품질 목표)
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-progress", "pipe:1", "-nostats", str(out_path)]
    return cmd


def _shq(a: str) -> str:
    """표시용 인용 — 공백·특수문자(한글 경로 포함) 있으면 큰따옴표 (Windows PowerShell 규칙)."""
    if a == "" or any(ch in a for ch in " []';&()"):
        return '"' + a.replace('"', '\\"') + '"'
    return a


def _resolve_out(base: pathlib.Path, out_arg, make_dir: bool) -> pathlib.Path:
    """--out 해석: 절대/경로 포함이면 그대로, 단순 파일명이면 완성본/ 아래. 미지정 시 완성본/final.mp4."""
    dest_dir = base / "완성본"
    if make_dir:
        dest_dir.mkdir(exist_ok=True)
    if out_arg:
        p = pathlib.Path(out_arg)
        if p.is_absolute() or str(p.parent) != ".":
            return p.resolve()
        return (dest_dir / out_arg)
    return dest_dir / "final.mp4"


def _render_ffmpeg(base, tl, audio, srt, video, overlays, ov_files, out_arg, nvenc, dry_run):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()             # encode_overlays.py와 동일한 ffmpeg 바이너리 획득 방식

    duration = float(tl.get("duration") or 0.0)
    out_path = _resolve_out(base, out_arg, make_dir=not dry_run)

    # SRT → ASS. libass가 상대경로로 열 수 있도록 JOB_DIR에 subs.ass를 놓고 cwd를 JOB_DIR로 둔다.
    # (한글·콜론·역슬래시가 섞인 절대경로를 filter 문자열에 직접 넣으면 ffmpeg 필터 파서가 깨진다.)
    playres, fontname, fontsize, margin_lr, margin_v = _ass_params("main")
    ass_text, total_cap, white_cap = _build_ass(srt, overlays, "main")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    ass_path = JOB_DIR / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    print(f"[자막] ASS 생성: {ass_path} (컷 {total_cap}개, 오버레이 흰색 {white_cap}개, 잉크 {total_cap - white_cap}개)")
    print(f"       규격: {fontname} {fontsize}px · 하단 여백(MarginV) {margin_v}px · 좌우 {margin_lr}px")

    filtergraph = _build_filter(overlays, playres)
    cmd = _ffmpeg_cmd(ff, video, overlays, ov_files, audio, filtergraph, out_path, nvenc)

    engine_label = "h264_nvenc(cq19)" if nvenc else "libx264(crf17/medium)"
    print(f"[ffmpeg] 엔진 {engine_label} · 입력 capture+ov{len(overlays)}+narration · cwd={JOB_DIR}")
    print("[ffmpeg] 명령:")
    print("  " + " ".join(_shq(a) for a in cmd))

    if dry_run:
        print("[dry-run] 인코딩을 실행하지 않습니다 (검증·ASS·명령 구성까지 확인 완료).")
        print(f"[dry-run] 출력 예정 경로: {out_path}")
        return

    # 진행률·종료 코드 검사(fail-loud)는 _encode_with_progress에 위임 (쇼츠 경로와 공용).
    rc = _encode_with_progress(cmd, duration)
    if rc != 0:
        sys.exit(f"[실패] ffmpeg 렌더 실패 (exit {rc}) — 위 stderr의 에러 전문을 확인하세요.")
    if not out_path.is_file():
        sys.exit(f"[실패] ffmpeg 산출물이 없습니다: {out_path}")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[완료] 완성본: {out_path} ({size_mb:.1f} MB, {engine_label})")
    print(f"  입력  오디오 : {audio}")
    print(f"  입력  비디오 : {video}")
    print(f"  입력  자막   : {srt} → {ass_path.name}")
    print(f"  오버레이     : {len(overlays)}개")
    print("  (이 경로는 캡컷 검수를 생략한 선택지입니다 — 기본은 여전히 CapCut 드래프트 검수 후 내보내기)")


def _render_ffmpeg_short(base, tl, audio, srt, video, out_arg, nvenc, dry_run):
    """쇼츠(9:16) ffmpeg 경로 — 1080x1920 정규화 + audio_cuts atrim/concat + ASS 자막(쇼츠 규격).

    본편 _render_ffmpeg과 다른 점만: capture를 1080x1920으로 정규화, 오디오를 나레이션 전체가 아니라
    audio_cuts대로 잘라 이어붙임(assemble_capcut.py short 분기와 동일 결과), 자막은 쇼츠 ASS 규격.
    쇼츠는 오버레이가 없으므로 전부 잉크색. capture(=duration)가 컷 합보다 길면 뒤 CTA는 무음 꼬리."""
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()

    duration = float(tl.get("duration") or 0.0)
    out_path = _resolve_out(base, out_arg, make_dir=not dry_run)

    # 오디오 컷 계산 — src_end 클램프용 나레이션 실측 길이가 필요(validate_pipeline.probe_duration 재사용).
    import validate_pipeline
    audio_dur_s = validate_pipeline.probe_duration(audio)
    audio_cuts = tl.get("audio_cuts") or []
    if not audio_cuts:
        sys.exit("[오류] 쇼츠 타임라인.json에 audio_cuts가 없습니다 — youtube-short-generator 스킬로 생성하세요.")
    cuts = _short_audio_cuts(audio_cuts, audio_dur_s)
    cut_sum = sum(d for _dst, _src, d in cuts)

    # SRT → ASS (쇼츠 규격). 쇼츠 오버레이 미지원 → overlays=[] (전부 잉크색).
    playres, fontname, fontsize, margin_lr, margin_v = _ass_params("short")
    ass_text, total_cap, white_cap = _build_ass(srt, [], "short")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    ass_path = JOB_DIR / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    print(f"[자막] ASS 생성(쇼츠 9:16): {ass_path} (컷 {total_cap}개, 전부 잉크 — 쇼츠 오버레이 미지원)")
    print(f"       규격: {fontname} {fontsize}px · PlayRes {playres[0]}x{playres[1]} · 하단 여백(MarginV) {margin_v}px · 좌우 {margin_lr}px")

    filtergraph = _build_short_filter(cuts, audio_idx=1, playres=playres)   # 입력: 0=capture, 1=narration
    cmd = [ff, "-hide_banner", "-y", "-i", str(video), "-i", str(audio)]
    cmd += ["-filter_complex", filtergraph]
    cmd += ["-map", "[vout]", "-map", "[aout]"]
    if nvenc:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
    # -shortest 없음: capture(=duration) 전체 길이를 유지해 CTA 꼬리를 살리고, 짧은 오디오는 무음으로 끝난다.
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-progress", "pipe:1", "-nostats", str(out_path)]

    engine_label = "h264_nvenc(cq19)" if nvenc else "libx264(crf17/medium)"
    print(f"[ffmpeg] 엔진 {engine_label} · 쇼츠(9:16) · 입력 capture+narration(컷 {len(cuts)}개={cut_sum:.2f}s) · cwd={JOB_DIR}")
    print("[ffmpeg] 명령:")
    print("  " + " ".join(_shq(a) for a in cmd))

    if dry_run:
        print("[dry-run] 인코딩을 실행하지 않습니다 (검증·ASS·명령 구성까지 확인 완료).")
        print(f"[dry-run] 출력 예정 경로: {out_path}")
        return

    rc = _encode_with_progress(cmd, duration)
    if rc != 0:
        sys.exit(f"[실패] ffmpeg 쇼츠 렌더 실패 (exit {rc}) — 위 stderr의 에러 전문을 확인하세요.")
    if not out_path.is_file():
        sys.exit(f"[실패] ffmpeg 산출물이 없습니다: {out_path}")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[완료] 완성본(쇼츠): {out_path} ({size_mb:.1f} MB, {engine_label})")
    print(f"  입력  오디오 : {audio} (audio_cuts {len(cuts)}개 → {cut_sum:.2f}s)")
    print(f"  입력  비디오 : {video}")
    print(f"  입력  자막   : {srt} → {ass_path.name}")
    print("  (이 경로는 캡컷 검수를 생략한 선택지입니다 — 기본은 여전히 CapCut 드래프트 검수 후 내보내기)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="완성본 렌더 (opt-in, 캡컷 검수 생략 경로) — 본편 16:9/쇼츠 9:16 자동 감지. 엔진 remotion|ffmpeg (쇼츠는 ffmpeg만)")
    ap.add_argument("job", type=pathlib.Path,
                    help="작업 폴더 경로 (타임라인.json이 있는 폴더 — 본편 작업 폴더 또는 쇼츠 05_쇼츠/short-NN 폴더)")
    ap.add_argument("--engine", choices=("ffmpeg", "remotion"), default="ffmpeg",
                    help="렌더 엔진 (기본 ffmpeg — 2026-07-23 실측 확정. remotion은 본편 전용 옵션 경로)")
    ap.add_argument("--nvenc", action="store_true",
                    help="h264_nvenc(cq19) 강제 — 기본도 NVENC 자동이라 평소엔 불필요, 불가 시 중단시키고 싶을 때만")
    ap.add_argument("--x264", action="store_true",
                    help="libx264(crf17) 강제 — NVENC 자동 선택을 끄고 CPU 인코딩")
    ap.add_argument("--out", help="ffmpeg 엔진 출력 파일명/경로 (기본 완성본/final.mp4 — 비교 시 이름 분리용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="ffmpeg 엔진: 검증·ASS 생성·명령 구성까지만 (인코딩 미실행)")
    args = ap.parse_args()

    base = args.job.resolve()
    if not base.is_dir():
        sys.exit(f"[오류] 작업 폴더 없음: {base}")
    timeline = base / "타임라인.json"
    if not timeline.is_file():
        sys.exit(f"[오류] 타임라인.json 없음: {timeline}")

    tl = json.loads(timeline.read_text(encoding="utf-8"))
    kind = tl.get("type", "main")
    if kind not in ("main", "short"):
        sys.exit(f"[중단] 알 수 없는 타임라인 type='{kind}' — 'main' 또는 'short'만 지원합니다.")
    if kind == "short" and args.engine == "remotion":
        sys.exit("[중단] 쇼츠(9:16, type=short)는 remotion 엔진 미지원 — ffmpeg 엔진(기본) 또는 CapCut 경로를 쓰세요.")

    if (args.nvenc or args.x264) and args.engine != "ffmpeg":
        sys.exit("[오류] --nvenc/--x264는 --engine ffmpeg에서만 유효합니다.")
    if args.nvenc and args.x264:
        sys.exit("[오류] --nvenc와 --x264는 동시에 쓸 수 없습니다.")
    if args.out and args.engine != "ffmpeg":
        sys.exit("[오류] --out은 --engine ffmpeg에서만 유효합니다 (리모션 경로는 완성본/final.mp4 고정).")
    if args.dry_run and args.engine != "ffmpeg":
        sys.exit("[오류] --dry-run은 --engine ffmpeg에서만 유효합니다.")

    # 스크립트 형제 모듈 import 경로 확보
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    # 공통 전처리: 입력 해석 → 싱크 계약 게이트 → 자막 16자 강제 (두 엔진·본편/쇼츠 동일)
    audio, srt, video, overlays, ov_files = _resolve_inputs(base, tl)
    _gate_and_enforce(timeline, srt)

    if args.engine == "ffmpeg":
        use_nvenc = _pick_encoder(args.nvenc, args.x264)   # 기본 = NVENC 자동(불가 시 x264 폴백)
    if kind == "short":
        _render_ffmpeg_short(base, tl, audio, srt, video,
                             args.out, use_nvenc, args.dry_run)
    elif args.engine == "remotion":
        _render_remotion(base, tl, audio, srt, video, overlays, ov_files)
    else:
        _render_ffmpeg(base, tl, audio, srt, video, overlays, ov_files,
                       args.out, use_nvenc, args.dry_run)


if __name__ == "__main__":
    main()
