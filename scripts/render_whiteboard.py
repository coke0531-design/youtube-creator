"""화이트보드 드로잉 렌더 — SVG/PNG 장면을 '손이 그려 나가는' mp4(wb<n>.mp4)로 만든다 (youtube-editor Step 6.6, 선택).

왜 있나:
  플랫 인포그래픽(차트·카드)만으로는 스토리·비유·개념 설명 장면이 단조롭다. 이 스크립트는
  선화(線畵) 한 장을 나레이션 구간 길이에 맞춰 "펜이 순서대로 그려 나가는" 클립으로 만든다.
  렌더 엔진은 geeklee/srt-whiteboard-animation(MIT)을 vendoring한 scripts/whiteboard/ 이고,
  이 래퍼가 브랜드 규칙(design.md: 흰 배경·4색·자막 안전 영역)과 파이프라인 계약을 강제한다.

입력 두 갈래:
  A) SVG 장면(권장) — 우리가 직접 그린 4색 벡터. <g data-wb="1"> 처럼 그릴 순서를 붙인 그룹이 있으면
     그 순서·bbox로 annotation을 자동 생성한다(픽셀 좌표 수작업 불필요). 그룹에 data-wb-t="3.2"를 주면
     클립 시작 기준 그 초에 그리기 시작(transcript 실측값으로 나레이션과 맞춤). 없으면 균등 배분.
  B) PNG 선화(외부 이미지 생성) — --annotation <json>(원 도구 포맷) 또는 --auto(그림 전체 1구역).

속도 모델(녹음 속도와 맞추는 법):
  엔진은 각 구역의 선 길이를 그 구역에 배정된 시간(durationMs)에 정확히 맞춰 그린다 — 시간이 짧으면 빨리,
  길면 천천히(탄력적). 그래서 클립 총길이는 항상 나레이션 구간과 같고, "그리는 속도"만 배정 시간에 따라 달라진다.
  ① 기본: 구역 시간 = 클립 길이를 면적(√)×data-wb-w 가중으로 배분 → 대략 균등.
  ② 정밀: 각 구역에 data-wb-t(클립 시작 기준 초, transcript 실측)를 주면 그 문장이 시작될 때 그리기 시작한다.
  ③ 진단: 렌더 전에 구역별 [시작~끝, 잉크 px/s]를 표로 찍는다. px/s가 너무 낮으면(펜이 기어감) 구역을 합치거나
     선을 더 넣고, 너무 높으면(순식간에 그려짐) 구역을 쪼개거나 선을 줄인다. 참고 밴드 3k~30k px/s(경고만, 중단 안 함).
  ④ 내용은 적은데 문장이 긴 구역: data-wb-d="1.2"(최대 그리기 초) → 1.2초에 그리고 다음 구역 시각까지 멈춘다.
  ⑤ --tail: 다 그린 뒤 완성 그림을 보여주는 여유(기본 0.6s). --pause: 엔진 '숨 고르기' 강도(heavy/auto/light/off).

계약(fail-loud):
  - 출력은 1920x1080·30fps·무음·정확히 --duration 초(오버레이 구간 길이) → encode_overlays.py에서 배속 1.0×.
  - 배경은 흰색(#ffffff) 고정. 하단 21%(자막 안전 영역)에 잉크가 있으면 중단(--allow-bottom으로만 강행).
  - 손 자산 기본 = 템플릿/whiteboard/hand-marker-amber-top.png(위에서 내려오는 손, 펜촉 좌하단) — 손이 펜촉 '위'로 뻗어
    하단 자막을 덮지 않는다. hand-marker-amber.png(아래에서 올라오는 손)도 선택 가능하나 하단 근처를 그릴 때 자막을 가린다.
    --hand none 이면 펜 없이. 크기 --hand-height(기본 400px).

사용:
  python scripts/render_whiteboard.py <scene.svg|scene.png> --out "결과물/<작업>/04_영상소스/wb1.mp4" --duration 12.4
  옵션: --annotation <json> | --auto | --hand <png|none> | --fps 30 | --allow-bottom | --keep-png | --ink-path grid|skeleton
        --tail 0.6 | --pause heavy|auto|light|off | --dry-run(진단표만 출력, 렌더 안 함)
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

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = ROOT / "scripts" / "whiteboard" / "render_stream_whiteboard.py"
DEFAULT_HAND = ROOT / "템플릿" / "whiteboard" / "hand-marker-amber-top.png"   # 위에서 내려오는 손(펜촉 좌하단) — 자막 안 가림
HAND_TIP_ANCHOR = {"hand-marker-amber-top.png": "0,1", "hand-marker-amber.png": "0,0"}   # 자산별 펜촉 위치(정규화)
W, H = 1920, 1080
BOTTOM_SAFE_RATIO = 0.21        # 자막 안전 영역(자막-안전영역.md: 하단 230px/1080)
BOTTOM_INK_TOL = 0.003          # 안전 영역 내 잉크 픽셀 비율 허용치
TAIL_GAZE_MS = 600              # 다 그린 뒤 완성 그림을 보여주는 여유(기본 — --tail로 조절)
PACE_MIN, PACE_MAX = 3000, 30000  # 구역별 잉크 px/s 참고 밴드(밖이면 경고)
BREATH_MS = 150                 # 구역 사이 호흡
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_duration(path: pathlib.Path) -> float:
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    times = _TIME_RE.findall(p.stderr)
    if not times:
        raise RuntimeError(f"길이 측정 실패: {path}")
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


# ── A) SVG → PNG + 자동 annotation ────────────────────────────────────────────
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;background:#ffffff;width:{w}px;height:{h}px;overflow:hidden}}
svg{{display:block;width:{w}px;height:{h}px}}</style></head><body>{svg}</body></html>"""

_JS_GROUPS = """
() => Array.from(document.querySelectorAll('[data-wb]')).map(el => {
  const r = el.getBoundingClientRect();
  return { id: el.id || null, seq: Number(el.dataset.wb), t: el.dataset.wbT ? Number(el.dataset.wbT) : null,
           w8: el.dataset.wbW ? Number(el.dataset.wbW) : 1,
           d: el.dataset.wbD ? Number(el.dataset.wbD) : null,
           label: el.dataset.wbLabel || el.id || ('구역 ' + el.dataset.wb),
           x: r.left, y: r.top, w: r.width, h: r.height };
})"""


def svg_to_png(svg: pathlib.Path, png: pathlib.Path):
    """SVG를 1920x1080 흰 배경 PNG로 굽고 [data-wb] 그룹의 화면 bbox를 돌려준다."""
    from playwright.sync_api import sync_playwright
    html = _PAGE.format(w=W, h=H, svg=svg.read_text(encoding="utf-8"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.set_content(html)
        pg.wait_for_timeout(150)
        groups = pg.evaluate(_JS_GROUPS)
        pg.screenshot(path=str(png), full_page=False)
        b.close()
    return groups


def auto_annotation(groups: list, total_ms: int, scene_id: str, pad: int = 14, tail_ms: int = TAIL_GAZE_MS) -> dict:
    """[data-wb] 그룹 bbox → 원 도구 annotation. 시작 시각은 data-wb-t(초) 우선, 없으면 면적(√)×data-wb-w 배분."""
    if not groups:
        # 그룹 표기가 없으면 그림 전체를 한 구역으로 — 그려지는 순서는 엔진(grid/skeleton)이 정한다
        groups = [{"id": "all", "seq": 1, "t": None, "label": "전체", "x": 0, "y": 0, "w": W, "h": H}]
    groups = sorted(groups, key=lambda g: g["seq"])
    seqs = [g["seq"] for g in groups]
    if len(set(seqs)) != len(seqs):
        sys.exit(f"[오류] data-wb 순번 중복: {seqs}")
    draw_ms = max(1000, total_ms - tail_ms)
    n = len(groups)
    if any(g["t"] is not None for g in groups):
        if any(g["t"] is None for g in groups):
            sys.exit("[오류] data-wb-t는 전부 주거나 전부 빼야 한다(혼용 금지)")
        starts = [int(round(g["t"] * 1000)) for g in groups]
        if starts != sorted(starts) or starts[0] < 0 or starts[-1] >= draw_ms:
            sys.exit(f"[오류] data-wb-t가 순번과 어긋나거나 클립 길이를 넘음: {starts} (그리기 가능 {draw_ms}ms)")
        ends = starts[1:] + [draw_ms]
    else:
        # 면적(√)에 비례해 시간 배분 — 큰 그림이 더 오래 그려지되 극단은 완화
        weights = [max(1.0, (g["w"] * g["h"]) ** 0.5) * float(g.get("w8", 1) or 1) for g in groups]
        tot = sum(weights)
        cur, starts, ends = 0, [], []
        for wgt in weights:
            starts.append(cur)
            cur += int(round(draw_ms * wgt / tot))
            ends.append(cur)
        ends[-1] = draw_ms
    elements = []
    for g, s, e in zip(groups, starts, ends):
        dur = max(400, e - s - BREATH_MS)
        if g.get("d"):                       # data-wb-d: 이 구역은 최대 d초 안에 그리고 다음 시각까지 멈춤(내용 적은 구역)
            dur = max(400, min(dur, int(round(float(g["d"]) * 1000))))
        x0, y0 = max(0, int(g["x"]) - pad), max(0, int(g["y"]) - pad)
        x1, y1 = min(W, int(g["x"] + g["w"]) + pad), min(H, int(g["y"] + g["h"]) + pad)
        elements.append({
            "id": g["id"] or f"wb{g['seq']}", "label": g["label"], "sequence": g["seq"],
            "narrativeRole": g["label"], "subtitle": "", "type": "structure",
            "region": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
            "reveal": {"direction": "top_to_bottom", "startMs": s, "durationMs": dur,
                       "maskPaddingPx": pad, "protectedRegions": []},
            "handPath": {"start": [x0, y0], "end": [x1, y1], "easing": "easeInOut"},
        })
    return {"sceneId": scene_id, "canvas": {"width": W, "height": H}, "storyBasis": "",
            "sceneDurationMs": total_ms, "elements": elements}


# ── 진단: 구역별 일정·속도(잉크 px/s) ─────────────────────────────────────────
def pace_report(png: pathlib.Path, ann: dict, total_ms: int) -> None:
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    ink = img.astype(int).sum(axis=2) < 3 * 235
    print("  구역 일정 (클립 시작 기준) — 나레이션 문장 시작과 비교하세요:")
    print("   순번  시작~끝(s)      길이   잉크px    px/s   라벨")
    warned = 0
    for e in sorted(ann["elements"], key=lambda e: e["sequence"]):
        r, rv = e["region"], e["reveal"]
        n = int(ink[r["y"]:r["y"] + r["height"], r["x"]:r["x"] + r["width"]].sum())
        s0, d = rv["startMs"] / 1000, rv["durationMs"] / 1000
        pps = n / d if d > 0 else 0
        flag = ""
        if n == 0:
            flag = "  ⚠ 잉크 없음(빈 구역?)"
        elif pps < PACE_MIN:
            flag = "  ⚠ 느림(펜이 기어감) — 구역 합치기/선 추가/시간 줄이기"
        elif pps > PACE_MAX:
            flag = "  ⚠ 빠름(순식간) — 구역 쪼개기/선 줄이기/시간 늘리기"
        warned += bool(flag)
        print(f"   {e['sequence']:>3}  {s0:6.2f}~{s0 + d:6.2f}  {d:5.2f}s  {n:7d}  {pps:6.0f}   {e.get('label', '')}{flag}")
    last = max(e["reveal"]["startMs"] + e["reveal"]["durationMs"] for e in ann["elements"]) / 1000
    print(f"   완성 그림 유지: {last:.2f}~{total_ms / 1000:.2f}s ({total_ms / 1000 - last:.2f}s)"
          + (f"   ⚠ 경고 {warned}건" if warned else ""))


# ── 가드: 자막 안전 영역 ───────────────────────────────────────────────────────
def check_bottom_safe(png: pathlib.Path) -> float:
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"[오류] PNG 읽기 실패: {png}")
    h = img.shape[0]
    band = img[int(h * (1 - BOTTOM_SAFE_RATIO)):, :, :]
    ink = (band.astype(int).sum(axis=2) < 3 * 235).mean()   # 흰색이 아닌 픽셀 비율
    return float(ink)


def main() -> None:
    ap = argparse.ArgumentParser(description="화이트보드 드로잉 클립 렌더 (SVG/PNG → wb<n>.mp4)")
    ap.add_argument("scene", type=pathlib.Path, help="장면 SVG(권장) 또는 PNG 선화")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="출력 mp4 (예: 04_영상소스/wb1.mp4)")
    ap.add_argument("--duration", type=float, required=True, help="클립 길이(초) = 오버레이 구간 길이(end-start)")
    ap.add_argument("--annotation", type=pathlib.Path, help="PNG용 annotation.json(원 도구 포맷). SVG는 자동 생성")
    ap.add_argument("--auto", action="store_true", help="PNG를 1구역으로 자동 annotation")
    ap.add_argument("--hand", default=str(DEFAULT_HAND), help="손 자산 PNG 경로 또는 none")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--hand-height", type=int, default=400,
                    help="손 자산 높이 px(기본 400). 손은 펜촉에서 우하단으로 뻗으므로 크면 하단 자막을 덮는다")
    ap.add_argument("--ink-path", default="grid", choices=["grid", "skeleton"])
    ap.add_argument("--color-fill", default="contour-wipe", choices=["contour-wipe", "brush"])
    ap.add_argument("--allow-bottom", action="store_true", help="하단 21% 잉크 가드 무시(권장 안 함)")
    ap.add_argument("--keep-png", action="store_true", help="SVG에서 구운 PNG·annotation을 남긴다(디버그)")
    ap.add_argument("--tail", type=float, default=TAIL_GAZE_MS / 1000, help="다 그린 뒤 완성 그림 유지 초(기본 0.6)")
    ap.add_argument("--pause", default="heavy", choices=["heavy", "auto", "light", "off"], help="엔진 숨 고르기 강도")
    ap.add_argument("--dry-run", action="store_true", help="구역 일정·속도 진단표만 출력하고 렌더하지 않는다")
    args = ap.parse_args()

    if not ENGINE.is_file():
        sys.exit(f"[오류] 렌더 엔진 없음: {ENGINE}")
    if args.duration <= 0:
        sys.exit("[오류] --duration은 양수")
    total_ms = int(round(args.duration * 1000))
    scene = args.scene.resolve()
    if not scene.is_file():
        sys.exit(f"[오류] 장면 파일 없음: {scene}")
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.with_suffix("")          # wb1 → wb1.png / wb1.annotation.json
    png = work.with_suffix(".png")
    ann_path = work.with_name(work.name + ".annotation.json")

    if scene.suffix.lower() == ".svg":
        groups = svg_to_png(scene, png)
        ann = auto_annotation(groups, total_ms, work.name, tail_ms=int(round(args.tail * 1000)))
        ann_path.write_text(json.dumps(ann, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  SVG → PNG {W}x{H}, 구역 {len(ann['elements'])}개 "
              f"({'data-wb 순번' if groups else '전체 1구역'})")
    else:
        png = scene
        if args.annotation:
            ann_path = args.annotation.resolve()
            ann = json.loads(ann_path.read_text(encoding="utf-8"))
            ann["sceneDurationMs"] = total_ms
            tmp = out.with_name(work.name + ".annotation.json")
            tmp.write_text(json.dumps(ann, ensure_ascii=False, indent=1), encoding="utf-8")
            ann_path = tmp
        elif args.auto:
            import cv2
            import numpy as np
            im = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
            h0, w0 = im.shape[:2]
            ann = auto_annotation([{"id": "all", "seq": 1, "t": None, "label": "전체",
                                    "x": 0, "y": 0, "w": w0, "h": h0}], total_ms, work.name,
                                  tail_ms=int(round(args.tail * 1000)))
            ann["canvas"] = {"width": w0, "height": h0}
            ann["elements"][0]["region"] = {"x": 0, "y": 0, "width": w0, "height": h0}
            ann_path.write_text(json.dumps(ann, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            sys.exit("[오류] PNG 입력은 --annotation <json> 또는 --auto 가 필요")

    ink = check_bottom_safe(png)
    if ink > BOTTOM_INK_TOL and not args.allow_bottom:
        sys.exit(f"[중단] 하단 {int(BOTTOM_SAFE_RATIO*100)}% 자막 안전 영역에 잉크 {ink*100:.2f}% — "
                 f"장면을 위로 올리거나(권장) --allow-bottom")
    print(f"  자막 안전 영역 잉크 {ink*100:.2f}% (허용 {BOTTOM_INK_TOL*100:.1f}%)")
    pace_report(png, ann, total_ms)
    if args.dry_run:
        print("[dry-run] 렌더 생략")
        return

    cmd = [sys.executable, str(ENGINE), str(png), str(ann_path), str(out)]
    if args.hand.lower() == "none":
        cmd.append("--bare-tip")
    else:
        hand = pathlib.Path(args.hand).resolve()
        if not hand.is_file():
            sys.exit(f"[오류] 손 자산 없음: {hand}")
        cmd.append(str(hand))
        cmd += ["--tip-anchor", HAND_TIP_ANCHOR.get(hand.name, "0,1")]
    cmd += ["--canvas", "#ffffff", "--fps", str(args.fps), "--cap-long-edge", str(W),
            "--total-ms", str(total_ms), "--ink-path", args.ink_path, "--color-fill", args.color_fill,
            "--pause", args.pause, "--hand-height", str(args.hand_height)]
    print(f"  렌더: {out.name} ({args.duration:.2f}s, {args.fps}fps, {args.ink_path}/{args.color_fill})")
    p = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True,
                       env={**__import__('os').environ, "PYTHONUTF8": "1"})
    if p.returncode != 0 or not out.is_file():
        sys.exit(f"[오류] 렌더 실패\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")

    d = probe_duration(out)
    if abs(d - args.duration) > 0.15:
        sys.exit(f"[오류] 출력 길이 {d:.2f}s ≠ 요청 {args.duration:.2f}s")
    if scene.suffix.lower() == ".svg" and not args.keep_png:
        for f in (png, ann_path):
            try:
                f.unlink()
            except OSError:
                pass
    print(f"[완료] {out}  ({d:.2f}s)")
    print("다음: 타임라인.json video_overlays에 {n, src: '04_영상소스/wbN.mp4', style: 'whiteboard', start, end, label} 추가 "
          "→ encode_overlays.py(배속 1.0×) → 캡처·조립")


if __name__ == "__main__":
    main()
