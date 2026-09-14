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

# ── ffmpeg 자막(ASS) 규격 — '흰 상자 자막' (2026-08-16 레퍼런스 픽셀 실측으로 전면 교체) ──
# 레퍼런스: Sherlock Hyunjoon 모듈러 주택 편(youtu.be/QhvJRQ9q4F0)의 번인 자막을 720p 프레임에서
# 픽셀 실측 → 1080p 환산. 스펙(자막-안전영역.md '흰 상자 자막' 절이 SSOT):
#   글자   : 잉크 #141413, 볼드, Pretendard 60px @1080p (2026-09-14 오너 채택 V4 — 이전 52px = 실측 글리프 25px@720p=37.5px@1080p 환산)
#   상자   : 흰색(#FDFEFE)이 텍스트 폭에 밀착, 패딩 ≈10px, 테두리 2px #160E01(딥 앰버 블랙)
#   그림자 : 다크 앰버 #3B2603 하드 오프셋(우·하 대각 ≈8px, 블러 없음)
#            (레퍼런스는 그 채널의 다크그린 #063B34 — 우리는 브랜드 앰버 #F59E0B를 동일 명도로
#             스케일(×0.24)한 값으로 교체. 톤·어두움은 유지, 색상만 브랜드 계열. 2026-08-16 오너 지시)
#   위치   : 하단 중앙, 상자 중심이 바닥에서 145px @1080p (2026-09-14 V4: 텍스트 하단 여백 108px — 이전 86px = 실측 8%H)
#   등장   : 컷 전환(페이드·팝 없음), 발화 내내 상시 표시
# 상자가 어떤 배경에서도 가독성을 보장하므로 구간별 흰색 오버라이드는 폐지(전 컷 동일 스타일).
# ASS 색은 &HAABBGGRR: 잉크(20,20,19)→&H00131414, 상자(253,254,254)→&H00FEFEFD,
# 테두리(22,14,1)→&H00010E16, 그림자(59,38,3)→&H0003263B.
# ── 오디오 라우드니스 정규화 (2026-08-20, 구 -1 dBTP 리미터 대체) ──
# 녹음 게인이 프로젝트마다 널뛴다 — 풀링013은 과대(-0.1 dBTP 오버슈트), 키_002는 과소(-21.4 LUFS,
# 유튜브 기준 -14 LUFS 대비 7dB 작게 들림). 렌더 시 loudnorm으로 -14 LUFS / -1 dBTP에 맞춰
# 두 방향 문제를 모두 흡수한다. 기본은 나레이션 파일을 선측정한 2-pass linear(고정 게인 —
# 다이내믹스 펌핑 없음), 측정 실패 시 1-pass dynamic 폴백. loudnorm은 내부 192kHz 업샘플
# 후 그대로 내보내므로 aresample=48000으로 되돌린다.
LOUDNORM_TARGET = "I=-14:TP=-1.5:LRA=11"   # TP -1.5 = AAC 오버슈트(~+0.3dB 실측) 후에도 -1 dBTP 이내
AUDIO_LOUDNORM_FALLBACK = f"loudnorm={LOUDNORM_TARGET},aresample=48000"


def _loudnorm_chain(ff: str, audio) -> str:
    """나레이션 파일을 선측정해 2-pass linear loudnorm 필터 문자열을 만든다(실패 시 dynamic 폴백).

    쇼츠는 audio_cuts로 잘라 이어붙인 뒤 이 필터를 통과하지만, 파트 간 라우드니스 편차가
    ~1 LU 수준(키_002 실측 -20.6~-22.4 LUFS)이라 전체 파일 측정값을 그대로 써도 오차가 작다."""
    r = subprocess.run(
        [ff, "-hide_banner", "-nostats", "-i", str(audio),
         "-af", f"loudnorm={LOUDNORM_TARGET}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "")
    if not m:
        print("[오디오] loudnorm 선측정 실패 → 1-pass dynamic 폴백 (품질 차이 경미)")
        return AUDIO_LOUDNORM_FALLBACK
    v = json.loads(m.group(0))
    print(f"[오디오] 나레이션 실측 {float(v['input_i']):.1f} LUFS / TP {float(v['input_tp']):+.1f} dBTP "
          f"→ loudnorm 2-pass linear (목표 -14 LUFS / -1.5 dBTP)")
    return (f"loudnorm={LOUDNORM_TARGET}"
            f":measured_I={v['input_i']}:measured_TP={v['input_tp']}"
            f":measured_LRA={v['input_lra']}:measured_thresh={v['input_thresh']}"
            f":offset={v['target_offset']}:linear=true,aresample=48000")
ASS_FONT = "Pretendard"
ASS_STYLE_INK = "&H00131414"
ASS_BOX_FILL = "&H00FEFEFD"
ASS_BOX_RIM = "&H00010E16"
ASS_BOX_SHADOW = "&H0003263B"
ASS_BOX_PAD = 8         # 흰 상자 패딩(px, 1080 기준). ASS 불투명 상자는 em 승강부만큼 세로가 더 붙어 8이 레퍼런스 밀착감과 일치
ASS_BOX_RIM_W = 2       # 테두리 두께(px)
ASS_BOX_SHADOW_OFF = 10  # 하드 섀도 대각 오프셋(px, 레퍼런스 실측 7px@720p 환산)
# kind별 규격:
#  - playres            : ASS PlayRes = 렌더 정규화 해상도(본편 1920x1080 / 쇼츠 1080x1920).
#  - fontsize           : 본편 60px(2026-09-14 오너 채택 V4 — 이전 52px 레퍼런스 환산에서 확대). 쇼츠는 폰 시청 거리 보정으로 기존 60px 유지.
#  - margin_lr          : 좌우 여백(줄바꿈 한계). 본편 160px 유지 / 쇼츠 48px.
#  - center_from_bottom : 자막 '중심'의 하단거리. 본편 145px(2026-09-14 V4: 텍스트 하단 여백 54→108px, 이전 86px) / 쇼츠 384px(세로-레이아웃.md).
ASS_SPEC = {
    "main":  {"playres": (1920, 1080), "fontsize": 60, "margin_lr": 160, "center_from_bottom": 145},
    "short": {"playres": (1080, 1920), "fontsize": 60, "margin_lr": 48,  "center_from_bottom": 384},
}


# 실행 시 덮어쓰기(--caption-fontsize / --caption-bottom). 기본 규격은 그대로 두고 비교용 변주만 허용한다(2026-09-14 V4 비교).
CAPTION_OVERRIDE = {"fontsize": None, "bottom": None}   # bottom = 텍스트 하단↔화면 하단 거리(px) = ASS MarginV 직접 지정


def _ass_params(kind: str):
    """kind별 ASS 규격 → (playres, fontname, fontsize, margin_lr, margin_v). MarginV 산식은 본편과 동일.

    ASS Alignment=2(하단 정렬)의 MarginV는 '텍스트 하단↔화면 하단' 거리다. FinalVideo/CapCut은 자막
    '중심'을 center_from_bottom에 놓으므로, 중심을 맞추려면 절반 줄높이만큼 내려 준다(162-37=125 / 384-37=347)."""
    spec = ASS_SPEC[kind]
    fontsize = spec["fontsize"] if CAPTION_OVERRIDE["fontsize"] is None else CAPTION_OVERRIDE["fontsize"]
    line_h = round(fontsize * 1.25)              # FinalVideo lineHeight:1.25 → 75px
    margin_v = spec["center_from_bottom"] - line_h // 2
    if CAPTION_OVERRIDE["bottom"] is not None:
        margin_v = CAPTION_OVERRIDE["bottom"]
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
    """SRT → ASS 문자열 — '흰 상자 자막' (레퍼런스 실측 스타일, 상단 ASS_BOX_* 참조).

    구현: BorderStyle=3(불투명 상자) 2레이어. 같은 텍스트를 두 번 그린다:
      Layer 0 "CapRim": 글자 투명(알파 FF) + 상자 = 테두리색, Outline = 패딩+테두리 두께
                        → 흰 상자보다 사방 2px 큰 진녹흑 상자 = 테두리.
                        Shadow = 8 → 이 상자의 오프셋 사본이 BackColour(다크그린)로 깔림 = 하드 섀도.
      Layer 1 "Cap"   : 잉크 글자 + 흰 상자(Outline = 패딩), Shadow = 0.
    상자가 배경 무관 가독성을 보장하므로 오버레이 구간 흰색 오버라이드는 폐지 — overlays 인자는
    호출부 호환용으로만 남긴다. 반환: (ass_text, 전체 컷 수, 0)."""
    (resx, resy), fontname, fontsize, margin_lr, margin_v = _ass_params(kind)
    style_fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
                 "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                 "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    common = f"-1,0,0,0,100,100,0,0,3"      # Bold=-1, BorderStyle=3(불투명 상자)
    tail = f"2,{margin_lr},{margin_lr},{margin_v},1"   # Alignment=2(하단 중앙)
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
        style_fmt,
        # 테두리+그림자 레이어: 글자 알파 FF(투명) — 상자(테두리색)와 그 그림자만 남는다
        (f"Style: CapRim,{fontname},{fontsize},&HFF131414,&H000000FF,{ASS_BOX_RIM},"
         f"{ASS_BOX_SHADOW},{common},{ASS_BOX_PAD + ASS_BOX_RIM_W},{ASS_BOX_SHADOW_OFF},{tail}"),
        # 본체 레이어: 잉크 글자 + 흰 상자
        (f"Style: Cap,{fontname},{fontsize},{ASS_STYLE_INK},&H000000FF,{ASS_BOX_FILL},"
         f"{ASS_BOX_FILL},{common},{ASS_BOX_PAD},0,{tail}"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events, total = [], 0
    for cs, ce, text in _read_srt_cues(srt):
        payload = _ass_escape(text)
        total += 1
        events.append(f"Dialogue: 0,{_ass_time(cs)},{_ass_time(ce)},CapRim,,0,0,0,,{payload}")
        events.append(f"Dialogue: 1,{_ass_time(cs)},{_ass_time(ce)},Cap,,0,0,0,,{payload}")
    return "\n".join(header + events) + "\n", total, 0


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
    # out_range=tv: capture가 full-range(yuvj420p)로 캡처돼도 limited로 통일 — Windows '영화 및 TV'
    # 하드웨어 디코더가 full-range H.264에서 0xC00D36D6로 끊긴다 (2026-08-16 실측)
    parts, cur = [f"[0:v]scale={w}:{h}:flags=lanczos:out_range=tv[base]"], "[base]"
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


CUT_FADE_SEC = 0.03   # 컷 경계 페이드(초) — 단어 경계 컷은 무음이 아니라 하드 컷이면 팝이 난다 (2026-09-03)


def _cut_fade_chain(d: float, fade: float = CUT_FADE_SEC) -> str:
    """컷 하나(길이 d초)의 양끝 페이드 필터. 길이는 불변(afade는 샘플을 잘라내지 않는다).

    컷이 아주 짧으면 페이드가 서로 겹치지 않게 절반씩으로 줄인다. 페이드 구간이 0이면 anull.
    쇼츠 audio_cuts는 무음 안이 아니라 단어 경계에서 자르므로(트림 컷과 다름) 경계 팝 방지가 필요하다."""
    f = min(fade, d / 2)
    if f <= 0:
        return "anull"
    return f"afade=t=in:st=0:d={f:.3f},afade=t=out:st={max(d - f, 0):.3f}:d={f:.3f}"


def _build_short_filter(cuts: list, audio_idx: int, playres: tuple, audio_chain: str = None) -> str:
    """쇼츠 filter_complex: 비디오 정규화+자막 굽기 + audio_cuts atrim/concat (컷마다 양끝 30ms 페이드).

    오디오는 나레이션(입력 audio_idx)에서 각 컷 [src, src+dur]을 atrim으로 뽑아 asetpts로 t=0 리셋하고
    dst 순서대로 concat 한다 → 결과 오디오 길이 = 컷 길이 합(assemble_capcut.py와 동일 결과).
    비디오(capture)는 duration 전체를 유지하므로, 컷 합 < duration이면 뒤쪽 CTA 구간은 무음 꼬리가 된다."""
    w, h = playres
    video_part = f"[0:v]scale={w}:{h}:flags=lanczos:out_range=tv[base];[base]ass=subs.ass[vout]"
    a_parts, labels = [], []
    for i, (_dst, src, d) in enumerate(cuts):
        lbl = f"a{i}"
        a_parts.append(
            f"[{audio_idx}:a]atrim=start={src:.3f}:end={src + d:.3f},asetpts=PTS-STARTPTS,"
            f"{_cut_fade_chain(d)}[{lbl}]")
        labels.append(f"[{lbl}]")
    a_parts.append("".join(labels) + f"concat=n={len(cuts)}:v=0:a=1[acat]")
    a_parts.append(f"[acat]{audio_chain}[aout]" if audio_chain else "[acat]anull[aout]")
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


def _ffmpeg_cmd(ff, video, overlays, ov_files, audio, filtergraph, out_path, nvenc, audio_chain=None):
    """ffmpeg argv 구성. 화질: libx264 crf17 preset medium (FinalVideo 렌더와 동급) / --nvenc는 cq19."""
    cmd = [ff, "-hide_banner", "-y", "-i", str(video)]
    for o in overlays:                               # ov 입력 순서 = filter의 [i:v] 순서와 반드시 일치
        cmd += ["-i", str(ov_files[o["n"]])]
    cmd += ["-i", str(audio)]
    a_idx = 1 + len(overlays)                                    # 오디오 = 마지막 입력
    if audio_chain:
        filtergraph = f"{filtergraph};[{a_idx}:a]{audio_chain}[aout]"
    cmd += ["-filter_complex", filtergraph]
    cmd += ["-map", "[vout]", "-map", "[aout]" if audio_chain else f"{a_idx}:a"]
    if nvenc:
        # h264_nvenc, cq 19 수준 (VBR, 비트레이트 상한 없음 → 품질 목표)
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
    cmd += ["-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
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


def _render_ffmpeg(base, tl, audio, srt, video, overlays, ov_files, out_arg, nvenc, dry_run, limiter=True):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()             # encode_overlays.py와 동일한 ffmpeg 바이너리 획득 방식

    duration = float(tl.get("duration") or 0.0)
    out_path = _resolve_out(base, out_arg, make_dir=not dry_run)

    # SRT → ASS. libass가 상대경로로 열 수 있도록 JOB_DIR에 subs.ass를 놓고 cwd를 JOB_DIR로 둔다.
    # (한글·콜론·역슬래시가 섞인 절대경로를 filter 문자열에 직접 넣으면 ffmpeg 필터 파서가 깨진다.)
    playres, fontname, fontsize, margin_lr, margin_v = _ass_params("main")
    ass_text, total_cap, _ = _build_ass(srt, overlays, "main")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    ass_path = JOB_DIR / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    print(f"[자막] ASS 생성: {ass_path} (컷 {total_cap}개, 흰 상자 자막 — 전 컷 동일 스타일)")
    print(f"       규격: {fontname} {fontsize}px · 하단 여백(MarginV) {margin_v}px · 좌우 {margin_lr}px")

    filtergraph = _build_filter(overlays, playres)
    audio_chain = _loudnorm_chain(ff, audio) if limiter else None
    cmd = _ffmpeg_cmd(ff, video, overlays, ov_files, audio, filtergraph, out_path, nvenc, audio_chain)

    engine_label = "h264_nvenc(cq19)" if nvenc else "libx264(crf17/medium)"
    print(f"[ffmpeg] 엔진 {engine_label} · 입력 capture+ov{len(overlays)}+narration · 라우드니스 {'-14 LUFS/-1 dBTP ON' if audio_chain else 'OFF'} · cwd={JOB_DIR}")
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


def _render_ffmpeg_short(base, tl, audio, srt, video, out_arg, nvenc, dry_run, limiter=True):
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
    ass_text, total_cap, _ = _build_ass(srt, [], "short")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    ass_path = JOB_DIR / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    print(f"[자막] ASS 생성(쇼츠 9:16): {ass_path} (컷 {total_cap}개, 흰 상자 자막)")
    print(f"       규격: {fontname} {fontsize}px · PlayRes {playres[0]}x{playres[1]} · 하단 여백(MarginV) {margin_v}px · 좌우 {margin_lr}px")

    audio_chain = _loudnorm_chain(ff, audio) if limiter else None
    filtergraph = _build_short_filter(cuts, audio_idx=1, playres=playres, audio_chain=audio_chain)   # 입력: 0=capture, 1=narration
    cmd = [ff, "-hide_banner", "-y", "-i", str(video), "-i", str(audio)]
    cmd += ["-filter_complex", filtergraph]
    cmd += ["-map", "[vout]", "-map", "[aout]"]
    if nvenc:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
    # -shortest 없음: capture(=duration) 전체 길이를 유지해 CTA 꼬리를 살리고, 짧은 오디오는 무음으로 끝난다.
    cmd += ["-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
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
    def _pos_int(v):
        n = int(v)
        if n <= 0: raise argparse.ArgumentTypeError(f"양수여야 한다: {v}")
        return n
    ap.add_argument("--caption-fontsize", type=_pos_int, default=None,
                    help="자막 글자 크기 덮어쓰기(px, PlayRes 기준 — 본편 기본 60). 비교 변주용, 기본 규격은 바꾸지 않는다")
    ap.add_argument("--caption-bottom", type=_pos_int, default=None,
                    help="자막 텍스트 하단↔화면 하단 거리 덮어쓰기(px = ASS MarginV — 본편 기본 108). 비교 변주용")
    ap.add_argument("--no-limiter", action="store_true",
                    help="오디오 라우드니스 정규화(-14 LUFS/-1 dBTP loudnorm) 끄기 (기본 ON — 녹음 게인 과대·과소 모두 흡수)")
    args = ap.parse_args()
    CAPTION_OVERRIDE["fontsize"] = args.caption_fontsize
    CAPTION_OVERRIDE["bottom"] = args.caption_bottom

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
    if (args.caption_fontsize or args.caption_bottom) and (kind != "main" or args.engine != "ffmpeg"):
        sys.exit("[중단] --caption-fontsize/--caption-bottom 은 본편(type=main) + ffmpeg 엔진에서만 유효합니다 "
                 "(쇼츠 규격·Remotion CaptionLayer 는 별도 SSOT).")
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
                             args.out, use_nvenc, args.dry_run, not args.no_limiter)
    elif args.engine == "remotion":
        _render_remotion(base, tl, audio, srt, video, overlays, ov_files)
    else:
        _render_ffmpeg(base, tl, audio, srt, video, overlays, ov_files,
                       args.out, use_nvenc, args.dry_run, not args.no_limiter)


if __name__ == "__main__":
    main()
