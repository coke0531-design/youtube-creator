"""싱크 계약 통합 검증기 — SRT·SLIDE_TIMELINE·타임라인.json·미디어 길이의 일치를 기계로 강제한다.

왜 스크립트인가:
  "SRT·SLIDE_TIMELINE·타임라인.json의 타임코드는 값이 일치해야 한다"(CLAUDE.md 싱크 계약)는
  지금까지 문서 규칙일 뿐 기계 게이트가 없었다 — 불일치 = 싱크 깨진 완성본이 조용히 나간다.
  캡처(Step 7)·조립(Step 8) 전에 이 검증기가 fail-loud로 막는다 (capture_slides.py와
  assemble_capcut.py가 자동 호출, 단독 실행도 가능).

무엇을 검증하나 (타임라인.json 기준):
  A. slides[]  : index 순차·유일, 0 ≤ start < end, 인접 연속(갭·겹침 ≤ 0.011s), 마지막 end ≈ duration
  B. SLIDE_TIMELINE(HTML) : 비스테이지 엔트리 수 = slides 수, t = slides[i].start(±2ms), s = index.
     스테이지 엔트리(g 포함)는 해당 슬라이드 구간 안에 있어야 함. HTML 없으면 건너뜀(초안 모드).
  C. SRT       : 컷 ≥ 1, start < end, 단조·비겹침(±1ms), 마지막 end ≤ duration + 1s
  D. video_overlays : n 양의 정수·유일, 0 ≤ start < end ≤ duration, 서로 비겹침, 원본(src) 실존,
     style은 화이트리스트(collage/hyperframes/없음) — 오타는 실사 경로로 오인돼 재인코딩 사고
  E. 미디어    : audio ≈ duration(±0.5s), capture.mp4(있으면) ≈ duration(±0.5s),
     ov<n>.mp4(있으면) ≥ 구간−0.5s. 파일이 아직 없으면 INFO로 표시만(단계 진행 중일 수 있음).
  F. 콜라주 오프닝 (본편만) : style=="collage"·start==0.0 오버레이가 반드시 1개 존재(첫 장면 후킹 —
     오너 결정 2026-08-18), 콜라주 개수 ≤ 3. 예전 작업 폴더 재조립처럼 예외가 필요하면 타임라인에
     "opening_collage_waiver": "<사유>" 를 적는다 → 경고로 강등(사유가 로그에 남는다).

사용:
  python validate_pipeline.py <타임라인.json> [--no-media]
  exit 0 = 통과 / exit 2 = 계약 위반(반드시 해소 후 진행)
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SLIDE_GAP_TOL = 0.011      # 인접 슬라이드 연속 허용 오차(초)
TIMELINE_T_TOL = 0.002     # SLIDE_TIMELINE t ↔ slides.start 허용 오차(초)
SRT_OVERLAP_TOL = 0.001    # 자막 컷 겹침 허용(초)
MEDIA_TOL = 0.5            # 미디어 길이 허용 오차(초)
OPENING_TOL = 0.001        # 콜라주 오프닝 start == 0 판정 허용 오차(초)
COLLAGE_MAX = 3            # 편당 콜라주 인서트 상한
# 자체 렌더 인서트 style 화이트리스트 — collage=render_collage.py, hyperframes=render_hf.py.
# style 없음 = 사용자 제공 실사/시연 소스(encode_overlays.py가 배속 인코딩).
OVERLAY_STYLES = {"collage", "hyperframes"}
DUR_HEAD_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")
ST_ENTRY_RE = re.compile(r"\{\s*t:\s*([0-9.]+)\s*,\s*s:\s*(\d+)\s*(?:,\s*g:\s*(\d+))?\s*\}")


def probe_duration(path: pathlib.Path) -> float:
    """헤더 Duration(±0.1s 정밀) — 게이트 허용오차 0.5s 대비 충분, 디코드보다 수십 배 빠름."""
    import imageio_ffmpeg
    p = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = DUR_HEAD_RE.search(p.stderr)
    if not m:
        raise RuntimeError(f"길이 파싱 실패: {path}")
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


def _srt_sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def run(timeline_path, media: bool = True, skip_capture: bool = False) -> list:
    """검증 실행 → 오류 문자열 목록(빈 목록 = 통과). INFO/경고는 즉시 출력.
    skip_capture: 캡처 직전 게이트용 — 곧 재생성될 기존 capture.mp4 길이 검사를 생략."""
    timeline_path = pathlib.Path(timeline_path)
    base = timeline_path.resolve().parent
    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    duration = float(tl["duration"])
    errors = []

    # A. slides (쇼츠는 slides가 없을 수 있음 — audio_cuts 중심이라 INFO만)
    slides = tl.get("slides") or []
    if not slides:
        if tl.get("type", "main") == "main":
            errors.append("A: slides가 비어 있음")
        else:
            print("[INFO] A 건너뜀 — 쇼츠 타임라인에 slides 없음")
    for i, s in enumerate(slides):
        if s.get("index") != i:
            errors.append(f"A: {s.get('id', i)} index {s.get('index')} ≠ 순번 {i}")
        if not (0 <= s["start"] < s["end"]):
            errors.append(f"A: {s['id']} 구간 비정상 {s['start']}–{s['end']}")
        if i and abs(s["start"] - slides[i - 1]["end"]) > SLIDE_GAP_TOL:
            errors.append(f"A: {slides[i-1]['id']}→{s['id']} 불연속 "
                          f"(end {slides[i-1]['end']} vs start {s['start']})")
    if slides and abs(slides[-1]["end"] - duration) > MEDIA_TOL:
        errors.append(f"A: 마지막 슬라이드 end {slides[-1]['end']} ≉ duration {duration}")

    # B. SLIDE_TIMELINE (HTML)
    html_path = base / tl.get("source_html", "04_영상소스/presentation.html")
    if html_path.is_file():
        html = html_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"SLIDE_TIMELINE\s*=\s*\[(.*?)\]", html, re.S)
        if not m:
            errors.append(f"B: SLIDE_TIMELINE 배열을 찾지 못함: {html_path.name}")
        else:
            entries = ST_ENTRY_RE.findall(m.group(1))
            main_entries = [(float(t), int(s)) for t, s, g in entries if not g]
            stage_entries = [(float(t), int(s), int(g)) for t, s, g in entries if g]
            if len(main_entries) != len(slides):
                errors.append(f"B: SLIDE_TIMELINE 슬라이드 엔트리 {len(main_entries)}개 ≠ slides {len(slides)}개")
            for (t, sidx), sl in zip(main_entries, slides):
                if sidx != sl["index"] or abs(t - sl["start"]) > TIMELINE_T_TOL:
                    errors.append(f"B: 엔트리(t={t}, s={sidx}) ≠ {sl['id']}(start={sl['start']})")
            for t, sidx, g in stage_entries:
                sl = slides[sidx] if sidx < len(slides) else None
                if not sl or not (sl["start"] - TIMELINE_T_TOL <= t <= sl["end"] + TIMELINE_T_TOL):
                    errors.append(f"B: 스테이지 엔트리(t={t}, s={sidx}, g={g})가 슬라이드 구간 밖")
    else:
        print(f"[INFO] B 건너뜀 — HTML 없음(초안 모드?): {html_path}")

    # C. SRT
    srt_path = base / tl["srt"]
    if srt_path.is_file():
        cues = SRT_TIME_RE.findall(srt_path.read_text(encoding="utf-8-sig", errors="replace"))
        if not cues:
            errors.append(f"C: SRT에 컷이 없음: {srt_path.name}")
        prev_end = 0.0
        for c in cues:
            cs, ce = _srt_sec(*c[:4]), _srt_sec(*c[4:])
            if cs >= ce:
                errors.append(f"C: 컷 start≥end ({cs:.3f}→{ce:.3f})")
            if cs < prev_end - SRT_OVERLAP_TOL:
                errors.append(f"C: 컷 겹침/역행 ({prev_end:.3f} 뒤에 {cs:.3f})")
            prev_end = max(prev_end, ce)
        if cues and prev_end > duration + 1.0:
            errors.append(f"C: 마지막 자막 end {prev_end:.3f} > duration+1s ({duration})")
    else:
        print(f"[INFO] C 건너뜀 — SRT 없음: {srt_path}")

    # D. video_overlays
    overlays = tl.get("video_overlays") or []
    seen_n = set()
    ordered = sorted(overlays, key=lambda o: o["start"])
    for o in overlays:
        n = o.get("n")
        if not isinstance(n, int) or n <= 0 or n in seen_n:
            errors.append(f"D: 오버레이 n 비정상/중복: {n}")
        seen_n.add(n)
        if o.get("style") is not None and o["style"] not in OVERLAY_STYLES:
            # 오타(예: "hyperframe")는 encode_overlays.py가 일반 실사 오버레이로 오인해
            # ov<n>.mp4를 자기 자신으로 재인코딩한다 → 화이트리스트로 fail-loud.
            errors.append(f"D: 오버레이 {n} style \"{o['style']}\" 미지원 "
                          f"— 허용: {sorted(OVERLAY_STYLES)} 또는 style 없음(실사 소스)")
        if not (0 <= o["start"] < o["end"] <= duration + 0.01):
            errors.append(f"D: 오버레이 {n} 구간 비정상 {o['start']}–{o['end']} (duration {duration})")
        if not (base / o["src"]).is_file():
            errors.append(f"D: 오버레이 {n} 원본 없음: {o['src']}")
    for a, b in zip(ordered, ordered[1:]):
        if b["start"] < a["end"] - 0.001:
            errors.append(f"D: 오버레이 {a['n']}↔{b['n']} 구간 겹침")

    # F. 콜라주 오프닝 (본편) — 첫 장면은 반드시 콜라주 (SKILL.md Step 6.7, 2026-08-18)
    if tl.get("type", "main") == "main":
        collages = [o for o in overlays if o.get("style") == "collage"]
        has_opening = any(abs(float(o["start"])) <= OPENING_TOL for o in collages)
        if not has_opening:
            msg = ("F: 콜라주 오프닝 인서트 없음 — 본편 첫 장면(t=0)은 style=\"collage\"·start=0.0 오버레이여야 함 "
                   "(SKILL.md Step 6.7 '오프닝 콜라주 필수')")
            waiver = tl.get("opening_collage_waiver")
            if waiver:
                print(f"[경고] {msg} — waiver 적용: {waiver}")
            else:
                errors.append(msg)
        if len(collages) > COLLAGE_MAX:
            errors.append(f"F: 콜라주 인서트 {len(collages)}개 > 상한 {COLLAGE_MAX} (오프닝 1 + 본문 1~2)")

    # E. 미디어 길이
    if media:
        kind = tl.get("type", "main")
        audio_path = base / tl["audio" if kind == "main" else "audio_source"]
        checks = [("오디오", audio_path, duration, MEDIA_TOL, kind == "main")]
        cap = base / "04_영상소스" / "capture.mp4"
        if cap.is_file() and not skip_capture:
            checks.append(("capture.mp4", cap, duration, MEDIA_TOL, True))
        for o in overlays:
            ov = base / "04_영상소스" / f"ov{o['n']}.mp4"
            if ov.is_file():
                seg = o["end"] - o["start"]
                d = probe_duration(ov)
                if seg - d > MEDIA_TOL:
                    errors.append(f"E: ov{o['n']}.mp4 {d:.2f}s < 구간 {seg:.2f}s−{MEDIA_TOL}")
            else:
                print(f"[INFO] E — ov{o['n']}.mp4 아직 없음 (encode_overlays.py 전이면 정상)")
        for label, p, target, tol, strict in checks:
            if not p.is_file():
                print(f"[INFO] E 건너뜀 — {label} 없음: {p}")
                continue
            d = probe_duration(p)
            if strict and abs(d - target) > tol:
                errors.append(f"E: {label} {d:.2f}s ≉ duration {target:.2f}s (허용 ±{tol}s)")

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="싱크 계약 통합 검증 (fail-loud)")
    ap.add_argument("timeline", type=pathlib.Path)
    ap.add_argument("--no-media", action="store_true", help="미디어 길이 검증 생략(빠른 구조 검사)")
    args = ap.parse_args()
    errors = run(args.timeline, media=not args.no_media)
    if errors:
        print(f"\n[FAIL] 싱크 계약 위반 {len(errors)}건 — 해소 전 캡처/조립 진행 금지:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(2)
    print("[통과] 싱크 계약 검증 — SRT·SLIDE_TIMELINE·타임라인·미디어 일치")


if __name__ == "__main__":
    main()
