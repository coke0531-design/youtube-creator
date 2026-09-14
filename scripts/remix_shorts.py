"""롱폼 영상 → 쇼츠 리믹스 렌더 (계획 JSON 1개 → 1080x1920 mp4).

왜 이 스크립트인가:
  기존 쇼츠 경로(youtube-short-generator → capture_slides → assemble_capcut/render_final)는
  "슬라이드를 새로 그려서" 쇼츠를 만든다. 이 스크립트는 반대로 **이미 완성된 롱폼 영상에서
  구간을 잘라** 세로 캔버스에 얹는 리믹스 전용 경로다 — 새 소재 제작 없이 발췌만으로 쇼츠를 뽑는다.
  기존 파이프라인(타임라인.json 계약·capture.mp4·audio_cuts)은 전혀 건드리지 않고,
  ASS 자막 변환·ffmpeg 인코딩 관례만 render_final.py에서 복제했다(임포트 결합 없음 —
  스키마가 다른 별개 경로라 한쪽 변경이 다른 쪽을 깨면 안 된다).

영상 슬롯을 채우는 방식 2가지 (plan의 "video.mode"):
  extract (기본·기존 동작) — 원본 final.mp4의 픽셀을 그대로 잘라 넣는다.
    ⚠️ 원본에 자막이 박혀 있으면 리믹스 자막과 이중으로 보인다. 16:9 원본은 1080x608로 작다.
  capture — 컷 구간에 맞춰 **새로 그린 슬라이드 소스**(templates/shorts-remix-source.html 계열을
    scripts/capture_remix_source.py로 캡처한 mp4)를 영상 슬롯에 넣고, 오디오만 원본에서 컷·콘캣한다.
    이중 자막이 사라지고 슬롯을 1080x700까지 키울 수 있다. 캡처 길이 ≠ 컷합이면 exit 2(fail-loud).

무엇을 하나 (계획 JSON 기준):
  1. 검증 — 소스 실존, cuts 비겹침·양수 길이, 총 길이 20~179초, SRT 실존 (fail-loud, exit 2).
     cuts의 시간 순서는 강제하지 않는다 — 결론 선행 재배치(시간 역순 점프컷)가 실사용 케이스다.
  2. 컷 + 콘캣 — extract는 영상+오디오 함께, capture는 오디오만 정밀 트림(출력 시킹 = 프레임 정확)
     후 계획에 적힌 순서 그대로 이어붙임. 배속 없음.
  3. 레이아웃 — 영상 소스를 #0A0A0A 1080x1920 캔버스의 y=video_y에 가운데 정렬로 얹음.
     extract는 1080폭에 맞춘 원본 비율(16:9 → 608), capture는 1080 x video.h(기본 700).
  4. 프레임 오버레이 — 템플릿/shorts-remix-frame.html을 Playwright로 1080x1920 투명 PNG 캡처 후 최상단 overlay.
  5. 자막 번인 — 쇼츠 타임라인 기준 SRT를 ASS로 변환해 굽는다(하단 자막 구역). --no-subs로 생략(CapCut 폴백).
  6. CTA 엔드카드 — CTA 모드 프레임 PNG(불투명) + 무음을 cta.duration초 만큼 뒤에 콘캣.
  7. 인코딩 — H.264 High / yuv420p / 30fps 고정 / AAC 48kHz 스테레오 / +faststart.
  8. 실측 — ffprobe로 출력 해상도·길이·오디오 유무를 확인해 요약 출력.

계획 JSON 스키마 (경로는 전부 이 JSON 파일 위치 기준 상대경로):
  {
    "type": "remix_short",
    "source_video": "00_원본/final.mp4",
    "audio_source": "00_원본/final.mp4",      // 선택 — 없으면 source_video에서 오디오를 딴다
    "video": {"mode": "capture",              // 선택 — 없으면 extract(기존 동작)
              "path": "source-capture.mp4",   // capture 모드 필수. 컷합과 같은 길이(±0.3s)
              "h": 700},                      // 영상 슬롯 높이 (capture 기본 700, extract 기본 608)
    "canvas": {"w": 1080, "h": 1920, "bg": "#0A0A0A"},
    "video_y": 500,
    "head_copy": {"lines": ["첫 줄", "둘째 줄"], "accent_words": ["강조어"]},
    "cuts": [{"src_start": 12.34, "src_end": 20.10}],   // 시간 역순 재배치 허용 (겹침만 금지)
    "srt": "short-01.srt",
    "cta": {"duration": 2.0, "text": "풀버전은 채널에"},
    "output": "short-01.mp4"
  }

사용:
  python remix_shorts.py <계획.json>
  python remix_shorts.py <계획.json> --no-subs        # 자막 번인 생략 (CapCut에서 수동으로 얹을 때)
  python remix_shorts.py <계획.json> --keep-tmp       # 중간 산출물(.tmp/) 보존 — 디버깅용
  python remix_shorts.py <계획.json> --allow-length   # 20~179초 길이 게이트 우회 (의도적 예외만)
  python remix_shorts.py <계획.json> --dry-run        # 검증·PNG·ASS·명령 구성까지 (인코딩 미실행)
"""
import argparse
import json
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
FRAME_HTML = REPO / "템플릿" / "shorts-remix-frame.html"

EXIT_BAD = 2            # 검증 실패 종료 코드 (계약: fail-loud는 전부 exit 2)

# ── 쇼츠 규격 상수 ────────────────────────────────────────────────────────────
FPS = 30                        # 고정 프레임레이트 (컷 경계 프레임 정확성의 전제)
MIN_SEC, MAX_SEC = 20.0, 179.0  # 쇼츠 허용 길이 — 3분(180s) 미만이어야 YouTube Shorts로 인정
DEFAULT_CANVAS = {"w": 1080, "h": 1920, "bg": "#0A0A0A"}
DEFAULT_VIDEO_Y = 500
DEFAULT_H_EXTRACT = 608   # extract 기본 — 16:9 원본을 1080폭에 맞췄을 때의 높이 (기존 동작 보존)
DEFAULT_H_CAPTURE = 700   # capture 기본 — 새로 그린 소스는 비율이 자유라 슬롯을 키운다
CAPTURE_DUR_TOL = 0.3     # 캡처 길이 vs 컷합 허용 오차(초). 넘으면 fail-loud

# ── 자막(ASS) 규격 — 리믹스 전용. render_final.py의 쇼츠 규격과 폰트 계열은 같지만
#    "검정 띠 위 흰 자막 + 외곽선"이라 색·크기·여백이 다르다(원본 규격을 덮어쓰지 않는다). ──
# 폰트   : Pretendard Black (시스템 설치 폰트명 — libass가 이름으로 찾는다)
# 크기   : 62px @1080 폭 (2026-08-13 상향: 54 → 62. 폰에서 읽히는 크기 우선)
# 색     : 흰색 &H00FFFFFF + 검정 외곽선 3px (실사 영상 위·검정 띠 위 모두 읽힌다)
# 위치   : Alignment=2(하단 중앙), MarginV=590 → 텍스트 하단이 화면 하단에서 590px 위(y≈1330).
#          영상 슬롯(y 500~1200) 아래 검정 구역 안이고, 한 줄 자막(62×1.2≈74px)의 상단이
#          y≈1256 → 소스 하단(1200)과 56px 떨어진다(요구 40px 이상 충족).
#          하단 UI 회피 구역(y 1460~) 경계에서도 130px 여유.
#          ⚠️ 두 줄로 넘어가는 컷이 있으면 상단이 y≈1182까지 올라가 슬롯을 침범한다.
#          split_captions.py --check(컷당 16자 이하)를 통과시켜 한 줄을 유지할 것.
ASS_FONT = "Pretendard Black"
ASS_FONTSIZE = 62
ASS_MARGIN_V = 590
ASS_MARGIN_LR = 60
ASS_OUTLINE = 3


# ── 공통 유틸 ────────────────────────────────────────────────────────────────
def die(msg: str) -> None:
    """검증 실패 — 조용한 폴백 없이 즉시 중단 (exit 2)."""
    print(f"[오류] {msg}", file=sys.stderr)
    sys.exit(EXIT_BAD)


def ffmpeg_exe() -> str:
    """encode_overlays.py·render_final.py와 동일한 ffmpeg 바이너리 획득 방식."""
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)")
_RES_RE = re.compile(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})")


def probe(path: pathlib.Path) -> dict:
    """실측 — ffprobe가 있으면 ffprobe(정확), 없으면 ffmpeg -i 헤더 파싱으로 폴백.

    반환 {"dur": 초, "w": 폭, "h": 높이, "audio": bool}. 실패는 fail-loud."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-show_entries", "stream=codec_type,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            data = json.loads(r.stdout)
            info = {"dur": float(data.get("format", {}).get("duration") or 0.0),
                    "w": 0, "h": 0, "audio": False}
            for st in data.get("streams", []):
                if st.get("codec_type") == "video" and not info["w"]:
                    info["w"], info["h"] = int(st.get("width") or 0), int(st.get("height") or 0)
                elif st.get("codec_type") == "audio":
                    info["audio"] = True
            return info
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = _DUR_RE.search(r.stderr)
    if not m:
        die(f"길이 파싱 실패 (손상 파일이거나 미디어가 아님): {path}")
    h, mm, s = m.groups()
    v = _RES_RE.search(r.stderr)
    return {"dur": int(h) * 3600 + int(mm) * 60 + float(s),
            "w": int(v.group(1)) if v else 0, "h": int(v.group(2)) if v else 0,
            "audio": "Audio:" in r.stderr}


def run_ff(cmd: list, label: str) -> None:
    """ffmpeg 실행 — 실패 시 stderr 꼬리를 그대로 노출하고 중단(조용한 실패 금지)."""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:], file=sys.stderr)
        sys.exit(f"[실패] {label} (ffmpeg exit {r.returncode}) — 위 stderr 전문을 확인하세요.")


def shq(a: str) -> str:
    """표시용 인용 (render_final.py와 동일 규칙 — 한글·공백 경로 대비)."""
    if a == "" or any(ch in a for ch in " []';&()"):
        return '"' + a.replace('"', '\\"') + '"'
    return a


# ── 1) 계획 JSON 로드 + 검증 ────────────────────────────────────────────────
def load_plan(plan_path: pathlib.Path, no_subs: bool, allow_length: bool) -> dict:
    """계획 JSON 파싱 + 전 항목 검증. 경로는 JSON 파일 위치 기준으로 해석한다."""
    if not plan_path.is_file():
        die(f"계획 JSON 없음: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as ex:
        die(f"계획 JSON 파싱 실패: {ex}")
    base = plan_path.resolve().parent

    if plan.get("type") != "remix_short":
        die(f"type이 'remix_short'가 아님: {plan.get('type')!r} — 이 스크립트는 리믹스 전용입니다.")

    # source_video
    src = (base / plan["source_video"]).resolve() if plan.get("source_video") else None
    if src is None or not src.is_file():
        die(f"source_video 없음: {src} (계획 JSON 위치 기준 상대경로로 씁니다)")

    # video 블록 — mode/path/h. 없으면 extract(기존 동작)
    vconf = plan.get("video") or {}
    vmode = str(vconf.get("mode") or "extract").lower()
    if vmode not in ("extract", "capture"):
        die(f"video.mode는 'extract' 또는 'capture'여야 합니다: {vmode!r}")
    video_h = int(vconf.get("h") or (DEFAULT_H_CAPTURE if vmode == "capture" else DEFAULT_H_EXTRACT))
    if video_h <= 0:
        die(f"video.h가 양수가 아닙니다: {video_h}")
    cap_path, cap_info = None, None
    if vmode == "capture":
        if not vconf.get("path"):
            die("video.mode=capture인데 video.path가 없습니다 — 캡처한 소스 mp4 경로가 필요합니다")
        cap_path = (base / vconf["path"]).resolve()
        if not cap_path.is_file():
            die(f"video.path 없음: {cap_path} (계획 JSON 위치 기준 상대경로로 씁니다)")
        cap_info = probe(cap_path)

    # audio_source — 오디오를 딸 원본. 없으면 source_video (extract 모드는 항상 source_video)
    asrc = src
    if plan.get("audio_source"):
        asrc = (base / plan["audio_source"]).resolve()
        if not asrc.is_file():
            die(f"audio_source 없음: {asrc}")
    if vmode == "extract" and asrc != src:
        die("extract 모드는 영상·오디오를 같은 소스에서 함께 잘라야 합니다 — audio_source를 지우거나 "
            "video.mode를 capture로 바꾸세요")

    # cuts — 비겹침·양수 길이. 시간 순서는 강제하지 않는다(결론 선행 재배치 허용).
    cuts = plan.get("cuts") or []
    if not cuts:
        die("cuts가 비어 있습니다 — 최소 1구간 필요")
    src_info = probe(src)
    a_info = src_info if asrc == src else probe(asrc)
    norm = []
    for i, c in enumerate(cuts, 1):
        try:
            a, b = float(c["src_start"]), float(c["src_end"])
        except (KeyError, TypeError, ValueError):
            die(f"컷 {i}: src_start/src_end가 숫자가 아닙니다 — {c!r}")
        if b <= a:
            die(f"컷 {i}: src_end({b})가 src_start({a}) 이하 — 길이 0 이하 구간은 만들 수 없습니다")
        if a < 0:
            die(f"컷 {i}: src_start가 음수({a})")
        if b > a_info["dur"] + 0.05:
            die(f"컷 {i}: src_end({b:.2f}s)가 오디오 소스 길이({a_info['dur']:.2f}s)를 넘습니다")
        norm.append((a, b))
    # 겹침 검사 — 계획 순서와 무관하게, 시작 시각으로 정렬해 인접쌍만 본다.
    order = sorted(range(len(norm)), key=lambda k: norm[k][0])
    for p, q in zip(order, order[1:]):
        if norm[q][0] < norm[p][1] - 1e-6:
            die(f"컷 {p + 1}({norm[p][0]:.2f}~{norm[p][1]:.2f}s)과 "
                f"컷 {q + 1}({norm[q][0]:.2f}~{norm[q][1]:.2f}s)의 구간이 겹칩니다 — "
                "같은 대사가 두 번 나옵니다. 순서 재배치는 허용되지만 겹침은 금지입니다")
    cut_sum = sum(b - a for a, b in norm)

    # capture 소스는 쇼츠 타임라인과 길이가 같아야 한다 — 어긋나면 그림과 말이 통째로 밀린다
    if cap_info is not None and abs(cap_info["dur"] - cut_sum) > CAPTURE_DUR_TOL:
        die(f"캡처 소스 길이({cap_info['dur']:.2f}s)가 컷합({cut_sum:.2f}s)과 "
            f"{abs(cap_info['dur'] - cut_sum):.2f}s 어긋납니다 (허용 {CAPTURE_DUR_TOL}s) — "
            "SLIDE_TIMELINE·캡처 --duration을 컷합에 맞추세요")

    cta = plan.get("cta") or {}
    cta_dur = float(cta.get("duration") or 0.0)
    if cta_dur < 0:
        die(f"cta.duration이 음수: {cta_dur}")
    total = cut_sum + cta_dur
    if not (MIN_SEC <= total <= MAX_SEC):
        msg = (f"완성 길이 {total:.2f}s (컷합 {cut_sum:.2f}s + CTA {cta_dur:.2f}s)가 "
               f"쇼츠 허용 범위 {MIN_SEC:.0f}~{MAX_SEC:.0f}초 밖입니다")
        if not allow_length:
            die(msg + " — cuts를 조정하세요 (의도적 예외면 --allow-length)")
        print(f"[경고] {msg} — --allow-length로 통과시킵니다", file=sys.stderr)

    # srt — --no-subs일 때만 없어도 된다
    srt = (base / plan["srt"]).resolve() if plan.get("srt") else None
    if not no_subs:
        if srt is None:
            die("srt가 계획에 없습니다 — 자막 없이 뽑으려면 --no-subs를 주세요")
        if not srt.is_file():
            die(f"srt 없음: {srt} — 자막 없이 뽑으려면 --no-subs를 주세요")

    canvas = {**DEFAULT_CANVAS, **(plan.get("canvas") or {})}
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(canvas["bg"])):
        die(f"canvas.bg는 #RRGGBB 형식이어야 합니다: {canvas['bg']!r}")
    video_y = int(plan.get("video_y", DEFAULT_VIDEO_Y))
    if not (0 <= video_y < canvas["h"]):
        die(f"video_y({video_y})가 캔버스 높이({canvas['h']}) 밖입니다")
    if vmode == "capture" and video_y + video_h > canvas["h"]:
        die(f"영상 슬롯(y {video_y}~{video_y + video_h})이 캔버스 높이({canvas['h']})를 넘습니다")

    out = plan.get("output")
    if not out:
        die("output(출력 파일명)이 없습니다")
    out_path = (base / out).resolve()

    head = plan.get("head_copy") or {}
    lines = [str(l) for l in (head.get("lines") or []) if str(l).strip()]
    if len(lines) > 2:
        die(f"head_copy.lines는 최대 2줄입니다 (현재 {len(lines)}줄)")
    for l in lines:
        if len(l) > 15:
            print(f"[경고] 헤드카피 줄이 15자를 넘습니다({len(l)}자) — 폰트가 자동 축소됩니다: {l}",
                  file=sys.stderr)

    return {
        "base": base, "src": src, "src_info": src_info, "cuts": norm, "cut_sum": cut_sum,
        "audio_src": asrc, "audio_info": a_info,
        "video_mode": vmode, "video_h": video_h, "cap_path": cap_path, "cap_info": cap_info,
        "srt": srt, "canvas": canvas, "video_y": video_y, "out": out_path,
        "lines": lines, "accent_words": [str(w) for w in (head.get("accent_words") or []) if str(w).strip()],
        "cta_dur": cta_dur, "cta_text": str(cta.get("text") or ""),
    }


# ── 2) 컷 + 콘캣 ────────────────────────────────────────────────────────────
CUT_FADE_SEC = 0.03   # 컷 경계 오디오 페이드(초) — 대사 경계 하드 컷의 팝 방지 (2026-09-03, render_final.py와 동일)


def _cut_fade_chain(d: float, fade: float = CUT_FADE_SEC) -> str:
    """컷 하나(길이 d초)의 양끝 afade 체인. 길이 불변. 짧은 컷은 절반씩으로 줄이고 0이면 anull."""
    f = min(fade, d / 2)
    if f <= 0:
        return "anull"
    return f"afade=t=in:st=0:d={f:.3f},afade=t=out:st={max(d - f, 0):.3f}:d={f:.3f}"


def _enc_v(nvenc: bool) -> list:
    """중간 산출물 인코딩 옵션 — 재인코딩 손실을 줄이려 최종보다 높은 품질로 굽는다."""
    if nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "17", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]


def cut_and_concat(ff: str, plan: dict, tmp: pathlib.Path, nvenc: bool) -> pathlib.Path:
    """각 cut을 영상+오디오 함께 정밀 트림 후 콘캣해 body 소스를 만든다.

    ⚠️ -ss를 -i **뒤**에 둔다(출력 시킹). 입력 시킹(-i 앞)은 키프레임으로 스냅해 빠르지만
    요청 구간과 실제 구간이 최대 몇 초까지 어긋난다 — 리믹스는 대사 경계로 자르므로 정확도가 우선.
    재인코딩이라 컷 경계 프레임이 정확하고, 배속(setpts/atempo)은 쓰지 않는다(원본 속도 고정)."""
    has_audio = plan["src_info"]["audio"]
    if not has_audio:
        print("[경고] 원본에 오디오 스트림이 없습니다 — 무음 트랙을 합성합니다", file=sys.stderr)
    parts = []
    for i, (a, b) in enumerate(plan["cuts"], 1):
        seg = tmp / f"cut_{i:02d}.mp4"
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(plan["src"])]
        if not has_audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        if has_audio:
            # 영상·오디오 모두 trim 필터로 자르고 PTS 를 0 으로 재기준화한 뒤 세그먼트 상대 페이드(cut_audio_only 와 같은 체인).
            # -ss/-to 출력 시킹 + 절대 시각 페이드 조합은 시킹·필터 타임베이스 해석이 ffmpeg 버전에 따라 달라 페이드가
            # 엉뚱한 자리(무음화)에 걸릴 수 있다(2026-09-14 리뷰) — trim 필터도 0부터 디코드하므로 정확도는 같다.
            cmd += ["-filter_complex",
                    f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v];"
                    f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,{_cut_fade_chain(b - a)}[a]",
                    "-map", "[v]", "-map", "[a]"]
        else:
            cmd += ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-map", "0:v:0", "-map", "1:a:0"]
        cmd += _enc_v(nvenc)
        cmd += ["-r", str(FPS), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        if not has_audio:
            cmd += ["-shortest"]
        cmd += [str(seg)]
        print(f"  [컷 {i}/{len(plan['cuts'])}] {a:.2f}s → {b:.2f}s ({b - a:.2f}s)")
        run_ff(cmd, f"컷 {i} 트림")
        parts.append(seg)

    if len(parts) == 1:
        return parts[0]
    lst = tmp / "concat_cuts.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    body = tmp / "body_src.mp4"
    # 전부 같은 인코더·파라미터로 구웠으므로 무손실 콘캣(-c copy)이 가능하다.
    run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", str(lst), "-c", "copy", str(body)], "컷 콘캣")
    return body


def cut_audio_only(ff: str, plan: dict, tmp: pathlib.Path) -> pathlib.Path:
    """capture 모드 — 오디오만 컷·콘캣한다 (영상은 새로 그린 캡처본을 쓴다).

    atrim + concat 필터 한 방으로 처리한다. 세그먼트 파일을 거치지 않으므로 계획에 적힌 순서를
    그대로 따르고(시간 역순 재배치 가능), 콘캣 경계에서 프레임/샘플이 밀리지 않는다."""
    asrc, cuts = plan["audio_src"], plan["cuts"]
    if not plan["audio_info"]["audio"]:
        die(f"오디오 소스에 오디오 스트림이 없습니다: {asrc}")
    parts, labels = [], []
    for i, (a, b) in enumerate(cuts):
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,{_cut_fade_chain(b - a)}[a{i}]")
        labels.append(f"[a{i}]")
        print(f"  [오디오 컷 {i + 1}/{len(cuts)}] {a:.2f}s → {b:.2f}s ({b - a:.2f}s)")
    fg = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(cuts)}:v=0:a=1[aout]"
    out = tmp / "body_audio.m4a"
    run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(asrc),
            "-filter_complex", fg, "-map", "[aout]",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)],
           "오디오 컷 + 콘캣")
    got = probe(out)
    if abs(got["dur"] - plan["cut_sum"]) > CAPTURE_DUR_TOL:
        die(f"콘캣한 오디오 길이({got['dur']:.2f}s)가 컷합({plan['cut_sum']:.2f}s)과 다릅니다")
    return out


# ── 3) 프레임 PNG 캡처 (Playwright) ─────────────────────────────────────────
def capture_frame(out_png: pathlib.Path, *, lines=None, accent_words=None,
                  cta_text: str = "", canvas=None, hole_top=None, hole_bottom=None) -> None:
    """shorts-remix-frame.html을 1080x1920 투명 PNG로 캡처한다 (capture_slides.py와 동일 관례).

    omit_background=True가 핵심 — body가 투명이라 가운데(영상 구멍)는 알파 0으로 남고,
    ffmpeg overlay를 얹으면 그 구멍으로 원본 영상이 비친다.
    CTA 모드(cta_text 지정)는 캔버스 전체가 불투명이라 알파가 없다."""
    from urllib.parse import urlencode
    from playwright.sync_api import sync_playwright

    if not FRAME_HTML.is_file():
        die(f"프레임 템플릿 없음: {FRAME_HTML}")
    canvas = canvas or DEFAULT_CANVAS
    if cta_text:
        query = {"cta": "1", "text": cta_text}
    else:
        lines = lines or []
        query = {}
        if len(lines) > 0:
            query["l1"] = lines[0]
        if len(lines) > 1:
            query["l2"] = lines[1]
        if accent_words:
            query["em"] = ",".join(accent_words)
        # 투명 구멍의 위·아래 경계를 실제 영상 슬롯에 맞춘다 (안 넘기면 템플릿 기본 500/1108).
        if hole_top is not None:
            query["ht"] = str(int(hole_top))
        if hole_bottom is not None:
            query["hb"] = str(int(hole_bottom))
    url = FRAME_HTML.resolve().as_uri() + "?" + urlencode(query)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars"])
        ctx = browser.new_context(viewport={"width": canvas["w"], "height": canvas["h"]},
                                  device_scale_factor=1)
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=30_000)
        # 헤드카피 폰트 자동 축소가 끝난 뒤에 찍는다 (fonts.ready 이후 세팅되는 플래그)
        page.wait_for_function("document.documentElement.dataset.frameReady === '1'", timeout=10_000)
        page.screenshot(path=str(out_png), omit_background=not cta_text)
        browser.close()
    if not out_png.is_file():
        die(f"프레임 PNG 캡처 실패: {out_png}")


# ── 4) SRT → ASS (리믹스 규격) ──────────────────────────────────────────────
def _ass_time(t: float) -> str:
    """초 → ASS 타임코드 h:mm:ss.cc (render_final.py와 동일)."""
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """ASS Dialogue 이스케이프 — 중괄호·줄바꿈 (render_final.py와 동일)."""
    text = text.replace("{", "\\{").replace("}", "\\}")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")


def _srt_sec(value: str) -> float:
    hms, ms = re.split(r"[,.]", value.strip(), maxsplit=1)
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s + int(ms.ljust(3, "0")) / 1000.0


def build_ass(srt: pathlib.Path, canvas: dict, total_dur: float) -> tuple[str, int]:
    """쇼츠 타임라인 기준 SRT → ASS 문자열. 반환 (ass_text, 컷 수).

    자막 시간은 '리믹스 결과물' 기준이다(원본 타임코드가 아님) — 컷 후 이어붙인 타임라인."""
    content = srt.read_text(encoding="utf-8-sig").strip()
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {canvas['w']}",
        f"PlayResY: {canvas['h']}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        # 흰색 + 검정 외곽선 3 / Alignment=2(하단 중앙) / MarginV=550 (영상 아래 검정 구역)
        (f"Style: Default,{ASS_FONT},{ASS_FONTSIZE},&H00FFFFFF,&H000000FF,&H00000000,"
         f"&H00000000,-1,0,0,0,100,100,0,0,1,{ASS_OUTLINE},0,2,"
         f"{ASS_MARGIN_LR},{ASS_MARGIN_LR},{ASS_MARGIN_V},1"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events, over = [], 0
    for block in re.split(r"\r?\n\s*\r?\n", content):
        rows = block.splitlines()
        if len(rows) < 3 or " --> " not in rows[1]:
            continue
        a_txt, b_txt = rows[1].split(" --> ", 1)
        a, b = _srt_sec(a_txt), _srt_sec(b_txt)
        if a > total_dur + 0.5:
            over += 1
        events.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,"
                      + _ass_escape("\n".join(rows[2:])))
    if not events:
        die(f"SRT에서 자막 컷을 하나도 읽지 못했습니다: {srt}")
    if over:
        print(f"[경고] SRT 컷 {over}개가 완성 길이({total_dur:.2f}s) 뒤에 있어 화면에 안 나옵니다 "
              "— SRT는 원본이 아니라 '리믹스 결과물' 타임라인 기준이어야 합니다", file=sys.stderr)
    return "\n".join(header + events) + "\n", len(events)


# ── 5) 레이아웃 + 오버레이 + 자막 번인 ──────────────────────────────────────
def _scaled_size(info: dict, canvas: dict) -> tuple[int, int]:
    """원본을 캔버스 폭에 맞춘 (w, h) — 짝수 보정.

    ffmpeg의 scale=1080:-2:force_original_aspect_ratio=decrease는 한 변이 -2면 동작이
    정의되지 않아(양변 지정이 전제) 소스에 따라 결과가 흔들린다. 그래서 파이썬에서 실측
    해상도로 직접 계산해 고정 픽셀로 넘긴다 — 1930x1080 같은 비표준 소스도 결정론적이다."""
    if info["w"] <= 0 or info["h"] <= 0:
        die("원본 해상도를 읽지 못했습니다 (영상 스트림 없음?)")
    w = canvas["w"]
    h = int(round(info["h"] * w / info["w"]))
    return w, h - (h % 2)


def render_body(ff: str, plan: dict, body_src: pathlib.Path, audio_in, frame_png: pathlib.Path,
                ass_path, tmp: pathlib.Path, nvenc: bool, dry_run: bool) -> pathlib.Path:
    """레이아웃(캔버스+영상) + 프레임 오버레이 + (선택)자막 번인 → body.mp4.

    audio_in이 있으면(capture 모드) 오디오는 그 파일에서, 영상은 body_src(캡처본)에서 온다."""
    canvas = plan["canvas"]
    y = plan["video_y"]
    if plan["video_mode"] == "capture":
        # 새로 그린 소스는 슬롯 크기에 정확히 맞춰 그렸으므로 고정 픽셀로 스케일한다.
        sw, sh = canvas["w"], plan["video_h"]
        src_desc = f"{plan['cap_info']['w']}x{plan['cap_info']['h']} (캡처 소스)"
        dur = plan["cut_sum"]
    else:
        sw, sh = _scaled_size(plan["src_info"], canvas)
        src_desc = f"{plan['src_info']['w']}x{plan['src_info']['h']} (원본 픽셀)"
        dur = probe(body_src)["dur"]

    # ass 필터 경로는 상대명 'subs.ass' + cwd=tmp — Windows 한글·콜론·역슬래시가 섞인 절대경로를
    # 필터 문자열에 직접 넣으면 ffmpeg 필터 파서가 깨진다 (render_final.py와 동일 회피).
    fg = [
        f"color=c={canvas['bg']}:s={canvas['w']}x{canvas['h']}:r={FPS}[bg]",
        f"[0:v]scale={sw}:{sh}:flags=lanczos,setsar=1[vid]",
        f"[bg][vid]overlay=x=(W-w)/2:y={y}:shortest=1[laid]",
        "[laid][1:v]overlay=x=0:y=0:format=auto[framed]",
    ]
    last = "[framed]"
    if ass_path is not None:
        fg.append(f"{last}ass=subs.ass[vout]")
        last = "[vout]"
    else:
        fg.append(f"{last}null[vout]")
        last = "[vout]"

    out = tmp / "body.mp4"
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(body_src), "-i", str(frame_png)]
    if audio_in is not None:
        cmd += ["-i", str(audio_in)]
    cmd += ["-filter_complex", ";".join(fg),
            "-map", "[vout]", "-map", ("2:a:0" if audio_in is not None else "0:a:0")]
    cmd += _enc_v(nvenc)
    cmd += ["-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", f"{dur:.3f}", str(out)]
    print(f"  [레이아웃] {src_desc} → {sw}x{sh} @ y={y} "
          f"(슬롯 y {y}~{y + sh}) · 캔버스 {canvas['w']}x{canvas['h']} {canvas['bg']}")
    if dry_run:
        print("  [dry-run] " + " ".join(shq(a) for a in cmd))
        return out
    r = subprocess.run(cmd, cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:], file=sys.stderr)
        sys.exit(f"[실패] 본편 레이아웃/오버레이 렌더 (ffmpeg exit {r.returncode})")
    return out


def render_cta(ff: str, plan: dict, tmp: pathlib.Path, nvenc: bool) -> pathlib.Path:
    """CTA 엔드카드 — 불투명 PNG 정지화면 + 무음. body와 동일 인코딩 파라미터(콘캣 전제)."""
    png = tmp / "cta.png"
    capture_frame(png, cta_text=plan["cta_text"], canvas=plan["canvas"])
    out = tmp / "cta.mp4"
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-loop", "1", "-framerate", str(FPS), "-t", f"{plan['cta_dur']:.3f}", "-i", str(png),
           "-f", "lavfi", "-t", f"{plan['cta_dur']:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += _enc_v(nvenc)
    cmd += ["-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
    run_ff(cmd, "CTA 엔드카드 렌더")
    return out


def finalize(ff: str, plan: dict, body: pathlib.Path, cta, tmp: pathlib.Path) -> None:
    """body(+CTA) → 최종 mp4. 최종 인코딩 규격(H.264 High/yuv420p/30fps/AAC 48k/faststart)."""
    plan["out"].parent.mkdir(parents=True, exist_ok=True)
    inputs, fg, n = [], [], 0
    for p in ([body, cta] if cta else [body]):
        inputs += ["-i", str(p)]
        fg.append(f"[{n}:v][{n}:a]")
        n += 1
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", *inputs]
    if n > 1:
        cmd += ["-filter_complex", "".join(fg) + f"concat=n={n}:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]
    cmd += ["-c:v", "libx264", "-profile:v", "high", "-level", "4.1",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(plan["out"])]
    run_ff(cmd, "최종 인코딩")


# ── main ────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(
        description="롱폼 영상 → 쇼츠 리믹스 렌더 (계획 JSON 1개 → 1080x1920 mp4)")
    ap.add_argument("plan", type=pathlib.Path, help="리믹스 계획 JSON 경로 (type=remix_short)")
    ap.add_argument("--no-subs", action="store_true",
                    help="자막 번인 생략 — CapCut에서 수동으로 얹을 때(폴백)")
    ap.add_argument("--keep-tmp", action="store_true", help="중간 산출물(.tmp/) 보존 — 디버깅용")
    ap.add_argument("--allow-length", action="store_true",
                    help=f"완성 길이 {MIN_SEC:.0f}~{MAX_SEC:.0f}초 게이트 우회 (의도적 예외만)")
    ap.add_argument("--nvenc", action="store_true",
                    help="중간 인코딩에 h264_nvenc 사용 (최종은 항상 libx264 — 호환성 우선)")
    ap.add_argument("--dry-run", action="store_true",
                    help="검증·프레임 PNG·ASS·명령 구성까지만 (인코딩 미실행)")
    args = ap.parse_args()

    plan = load_plan(args.plan.resolve(), args.no_subs, args.allow_length)
    ff = ffmpeg_exe()
    tmp = plan["out"].parent / ".tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    total = plan["cut_sum"] + plan["cta_dur"]
    print(f"[계획] {args.plan} — 컷 {len(plan['cuts'])}개 {plan['cut_sum']:.2f}s "
          f"+ CTA {plan['cta_dur']:.2f}s = {total:.2f}s · 영상 모드 {plan['video_mode']}")
    print(f"       원본: {plan['src']} ({plan['src_info']['w']}x{plan['src_info']['h']}, "
          f"{plan['src_info']['dur']:.2f}s, 오디오 {'있음' if plan['src_info']['audio'] else '없음'})")
    if plan["video_mode"] == "capture":
        print(f"       캡처 소스: {plan['cap_path'].name} "
              f"({plan['cap_info']['w']}x{plan['cap_info']['h']}, {plan['cap_info']['dur']:.2f}s) "
              f"→ 슬롯 {plan['canvas']['w']}x{plan['video_h']} @ y={plan['video_y']}")
        print(f"       오디오 소스: {plan['audio_src'].name} (컷만 적용)")

    # 프레임 PNG (헤드카피) — dry-run에서도 만들어 실제 캡처 가능 여부를 확인한다
    frame_png = tmp / "frame.png"
    print("[프레임] shorts-remix-frame.html → 투명 PNG 캡처 (Playwright headless)")
    capture_frame(frame_png, lines=plan["lines"], accent_words=plan["accent_words"],
                  canvas=plan["canvas"], hole_top=plan["video_y"],
                  hole_bottom=plan["video_y"] + plan["video_h"])
    print(f"         헤드카피 {plan['lines']} · 강조 {plan['accent_words']} → {frame_png.name}")

    # 자막 ASS
    ass_path = None
    if not args.no_subs:
        ass_text, cues = build_ass(plan["srt"], plan["canvas"], total)
        ass_path = tmp / "subs.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        print(f"[자막] ASS 생성: {ass_path.name} (컷 {cues}개) · {ASS_FONT} {ASS_FONTSIZE}px "
              f"· 외곽선 {ASS_OUTLINE}px · MarginV {ASS_MARGIN_V}px")
    else:
        print("[자막] --no-subs — 번인 생략 (CapCut 수동 폴백)")

    if args.dry_run:
        print("[dry-run] 컷·인코딩을 실행하지 않습니다 (검증·프레임 PNG·ASS까지 확인 완료).")
        print(f"[dry-run] 출력 예정: {plan['out']}")
        return

    if plan["video_mode"] == "capture":
        print(f"[컷] 오디오만 정밀 트림 + 콘캣 ({len(plan['cuts'])}구간, 계획 순서 그대로, 배속 없음)")
        audio_in = cut_audio_only(ff, plan, tmp)
        body_src = plan["cap_path"]
    else:
        print(f"[컷] 정밀 트림 + 콘캣 ({len(plan['cuts'])}구간, 배속 없음)")
        audio_in = None
        body_src = cut_and_concat(ff, plan, tmp, args.nvenc)

    print("[합성] 캔버스 + 영상 + 프레임 오버레이" + ("" if args.no_subs else " + 자막 번인"))
    body = render_body(ff, plan, body_src, audio_in, frame_png, ass_path, tmp, args.nvenc, False)

    cta = None
    if plan["cta_dur"] > 0:
        print(f"[CTA] 엔드카드 {plan['cta_dur']:.2f}s — \"{plan['cta_text']}\"")
        cta = render_cta(ff, plan, tmp, args.nvenc)

    print("[인코딩] 최종 H.264 High / yuv420p / 30fps / AAC 48kHz 스테레오 / +faststart")
    finalize(ff, plan, body, cta, tmp)

    if not plan["out"].is_file():
        sys.exit(f"[실패] 출력 파일이 없습니다: {plan['out']}")

    # 실측 — 설계값과 비교해 조용한 어긋남을 잡는다
    got = probe(plan["out"])
    size_mb = plan["out"].stat().st_size / (1024 * 1024)
    ok_res = (got["w"], got["h"]) == (plan["canvas"]["w"], plan["canvas"]["h"])
    ok_dur = abs(got["dur"] - total) <= 0.5
    print(f"\n[완료] {plan['out']} ({size_mb:.1f} MB)")
    print(f"  해상도 : {got['w']}x{got['h']} " +
          ("✅" if ok_res else f"❌ 기대 {plan['canvas']['w']}x{plan['canvas']['h']}"))
    print(f"  길이   : {got['dur']:.2f}s " +
          ("✅" if ok_dur else f"❌ 기대 {total:.2f}s (±0.5s)") +
          f"  (컷합 {plan['cut_sum']:.2f}s + CTA {plan['cta_dur']:.2f}s)")
    print(f"  오디오 : {'있음 ✅' if got['audio'] else '없음 ❌'}")
    print(f"  자막   : {'번인' if ass_path else '없음(--no-subs)'}")

    if not args.keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"  중간물 : {tmp} (--keep-tmp)")

    if not (ok_res and ok_dur and got["audio"]):
        sys.exit("[중단] 출력 실측이 설계값과 다릅니다 — 위 ❌ 항목을 확인하세요.")


if __name__ == "__main__":
    main()
