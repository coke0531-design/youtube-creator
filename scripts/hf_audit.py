# -*- coding: utf-8 -*-
"""HF 감사기 주입 — presentation.html 레이아웃·명암비·모션 정지 검사.

설계 정본: docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md §3-4.

HyperFrames `check`의 브라우저 감사 스크립트 3종(순수 DOM)을 우리 슬라이드 덱에
주입해 시점별로 돌린다. 벤더 원본은 `벤더/hf-audit/`(커밋 7170dc6 고정, Apache-2.0).

  layout-audit.browser.js   텍스트 잘림·넘침·가림·보이지 않는 텍스트·컨테이너 이탈·겹침
  contrast-audit.browser.js WCAG 명암비 (큰 텍스트 3:1 / 작은 텍스트 4.5:1 — 원본 임계 유지)
  motion-sample.browser.js  가시 요소 서명 → 인접 샘플이 동일하면 "정지 창"

한글 재보정: 원본의 ATOMIC_LABEL_MAX_CHARS(16자, 라틴 기준 '한 단어 라벨' 판정)를
주입 시점 문자열 치환으로 8자로 낮춘다. 벤더 파일 자체는 고치지 않는다.

샘플 시점
  - 슬라이드 중간 지점 (타임라인.json)
  - STORYBOARD.md가 있으면 각 Scene 경계 + 0.5s

사용
  python scripts/hf_audit.py "결과물/2026-08-06_풀링013_..."
  python scripts/hf_audit.py <presentation.html> --timeline <타임라인.json>
  python scripts/hf_audit.py <작업폴더> --json --out audit.json
  옵션: --size 2560x1440  --atomic-max 8  --warn-only  --limit N(샘플 수 제한, 디버그)

종료 코드: 0 = 통과(또는 --warn-only), 1 = 레이아웃 error 또는 명암비 실패 존재, 2 = 입력 오류
"""
import argparse
import base64
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "벤더" / "hf-audit"
SCENE_OFFSET = 0.5      # Scene 경계 뒤 몇 초 지점을 볼 것인가
DEFAULT_ATOMIC_MAX = 8  # 한글 라벨 재보정 (원본 16)


def die(msg: str):
    """입력 오류 종료 — 게이트 위반(1)과 구분되는 exit 2."""
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def load_vendor(name: str, atomic_max: int) -> str:
    path = VENDOR / name
    if not path.exists():
        die(f"[입력 오류] 벤더 스크립트가 없다: {path}")
    src = path.read_text(encoding="utf-8")
    if name.startswith("layout-audit"):
        needle = "const ATOMIC_LABEL_MAX_CHARS = 16;"
        if needle not in src:
            print(f"[경고] {name}: ATOMIC_LABEL_MAX_CHARS 상수를 찾지 못했다 — 재보정 생략",
                  file=sys.stderr)
        else:
            src = src.replace(needle, f"const ATOMIC_LABEL_MAX_CHARS = {atomic_max};")
    return src


def sample_times(slides, storyboard_frames):
    """(t, 라벨) 목록 — 슬라이드 중간 + Scene 경계+0.5s."""
    points = []
    for s in slides:
        start, end = float(s["start"]), float(s["end"])
        sid = s.get("id", f"#{s.get('index', '?')}")
        points.append((round((start + end) / 2, 3), sid, "슬라이드 중간"))
    for f in storyboard_frames or []:
        fields = f.get("fields", {})
        astart, _ = parse_audio(fields)
        if astart is None:
            continue
        for sc in f["scenes"][1:]:      # 첫 Scene의 시작(=프레임 시작)은 슬라이드 컷과 동일
            t = round(astart + sc["start"] + SCENE_OFFSET, 3)
            points.append((t, f"Frame {f['no']:02d}", f"Scene {sc['n']} +{SCENE_OFFSET}s"))
    seen = {}
    for t, sid, why in sorted(points):
        seen.setdefault(round(t, 2), (t, sid, why))
    return [seen[k] for k in sorted(seen)]


def parse_audio(fields):
    try:
        from check_storyboard import parse_audio_range
    except ImportError:
        return None, None
    return parse_audio_range(fields.get("오디오", "") or fields.get("audio", ""))


def find_storyboard(root: Path):
    """root와 상위 2단계에서 STORYBOARD.md(루트·01_대본·04_영상소스)를 찾는다 — check_storyboard와 동기."""
    cur = root.resolve()
    for _ in range(3):
        for c in (cur / "STORYBOARD.md", cur / "01_대본" / "STORYBOARD.md",
                  cur / "04_영상소스" / "STORYBOARD.md"):
            if c.exists():
                return c
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_inputs(target: Path, timeline_arg):
    if target.is_dir():
        html = target / "04_영상소스" / "presentation.html"
        if not html.exists():
            cands = list(target.glob("**/presentation.html"))
            if not cands:
                die(f"[입력 오류] presentation.html을 찾지 못했다: {target}")
            html = cands[0]
        root = target
    else:
        html = target
        if not html.exists():
            die(f"[입력 오류] 파일이 없다: {html}")
        root = html.parent.parent
    tl = Path(timeline_arg) if timeline_arg else root / "타임라인.json"
    if not tl.exists():
        die(f"[입력 오류] 타임라인.json이 없다: {tl}")
    return html, tl, root


def run(html: Path, points, size, atomic_max, verbose=True):
    from playwright.sync_api import sync_playwright

    layout_js = load_vendor("layout-audit.browser.js", atomic_max)
    contrast_js = load_vendor("contrast-audit.browser.js", atomic_max)
    motion_js = load_vendor("motion-sample.browser.js", atomic_max)

    width, height = size
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb",
                                           "--font-render-hinting=none"])
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=1)
        page.goto(html.resolve().as_uri() + "?capture=1")
        page.wait_for_function("window.__capture && window.__capture.ready", timeout=60_000)
        for js in (layout_js, contrast_js, motion_js):
            page.add_script_tag(content=js)

        prev_sig = None
        for i, (t, sid, why) in enumerate(points, 1):
            page.evaluate("t => window.__capture.seek(t)", t)
            page.wait_for_timeout(120)   # 전환 CSS 정착

            layout = page.evaluate("o => window.__hyperframesLayoutAudit(o)",
                                   {"time": t, "tolerance": 2})
            candidates = page.evaluate("() => window.__contrastAuditPrepare()")
            try:
                shot = page.screenshot(type="png")
                b64 = base64.b64encode(shot).decode("ascii")
                contrast = page.evaluate(
                    "a => window.__contrastAuditFinish(a[0], a[1], a[2])",
                    [b64, t, candidates])
            except Exception as exc:                       # noqa: BLE001
                page.evaluate("() => window.__contrastAuditRestoreIfPending()")
                contrast = []
                print(f"[경고] t={t}s 명암비 검사 실패: {exc}", file=sys.stderr)

            sample = page.evaluate("o => window.__hyperframesMotionSample(o)",
                                   {"selectors": [], "livenessScopes": ["*"]})
            sig = json.dumps(sample.get("liveness", {}), ensure_ascii=False, sort_keys=True)
            frozen = prev_sig is not None and sig == prev_sig
            prev_sig = sig

            bad_contrast = [c for c in contrast if not c.get("wcagAA")]
            results.append({
                "t": t, "slide": sid, "why": why,
                "layout": layout, "contrast_checked": len(contrast),
                "contrast_fail": bad_contrast, "frozen_vs_prev": frozen,
            })
            if verbose:
                print(f"  [{i}/{len(points)}] t={t:>7.2f}s {sid:<10} {why:<18} "
                      f"layout {len(layout):>2} · 명암비 {len(bad_contrast)}/{len(contrast)}"
                      f"{' · 정지' if frozen else ''}")
        browser.close()
    return results


def main():
    ap = argparse.ArgumentParser(description="HF 감사기 주입 (레이아웃·명암비·정지)")
    ap.add_argument("target", help="작업 폴더 또는 presentation.html 경로")
    ap.add_argument("--timeline", help="타임라인.json 경로")
    ap.add_argument("--storyboard", help="STORYBOARD.md 경로 (기본: 자동 탐색)")
    ap.add_argument("--size", default="2560x1440", help="뷰포트 (기본 2560x1440 = 캡처 규격)")
    ap.add_argument("--atomic-max", type=int, default=DEFAULT_ATOMIC_MAX,
                    help="ATOMIC_LABEL_MAX_CHARS 런타임 오버라이드 (기본 8, 원본 16)")
    ap.add_argument("--limit", type=int, help="샘플 시점 수 제한(디버그)")
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="JSON 결과 저장 경로")
    args = ap.parse_args()

    html, tl, root = resolve_inputs(Path(args.target), args.timeline)
    slides = json.loads(tl.read_text(encoding="utf-8")).get("slides") or []
    if not slides:
        die(f"[입력 오류] 타임라인에 slides가 없다: {tl}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sb_path = Path(args.storyboard) if args.storyboard else find_storyboard(root)
    frames = []
    if sb_path and sb_path.exists():
        from check_storyboard import parse_storyboard
        frames = parse_storyboard(sb_path)

    points = sample_times(slides, frames)
    if args.limit:
        points = points[:args.limit]
    width, height = (int(x) for x in args.size.lower().split("x"))

    log = sys.stderr if args.json else sys.stdout   # --json은 stdout을 JSON 전용으로 비운다
    print(f"HTML: {html}", file=log)
    print(f"타임라인: {tl}  (슬라이드 {len(slides)})", file=log)
    print(f"STORYBOARD: {sb_path if frames else '(없음 — 슬라이드 중간만 샘플)'}", file=log)
    print(f"샘플 시점 {len(points)}개 · 뷰포트 {width}x{height} · "
          f"ATOMIC_LABEL_MAX_CHARS={args.atomic_max}", file=log)
    print("-" * 88, file=log)

    results = run(html, points, (width, height), args.atomic_max, verbose=not args.json)

    layout_n = sum(len(r["layout"]) for r in results)
    layout_err = sum(1 for r in results for i in r["layout"] if i.get("severity") == "error")
    layout_warn = layout_n - layout_err
    contrast_n = sum(len(r["contrast_fail"]) for r in results)
    checked_n = sum(r["contrast_checked"] for r in results)
    frozen = [r for r in results if r["frozen_vs_prev"]]

    payload = {
        "html": str(html), "timeline": str(tl),
        "storyboard": str(sb_path) if frames else None,
        "viewport": f"{width}x{height}", "atomic_label_max_chars": args.atomic_max,
        "samples": results,
        "summary": {"samples": len(results), "layout_findings": layout_n,
                    "layout_errors": layout_err, "layout_warnings": layout_warn,
                    "contrast_checked": checked_n, "contrast_failures": contrast_n,
                    "frozen_samples": len(frozen)},
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("-" * 88)
        for r in results:
            if not r["layout"] and not r["contrast_fail"]:
                continue
            print(f"t={r['t']:.2f}s  {r['slide']}  ({r['why']})")
            for issue in r["layout"]:
                sev = issue.get("severity", "?")
                code = issue.get("code", "layout")
                sel = issue.get("selector", "?")
                text = (issue.get("text") or "")[:28].replace("\n", " ")
                print(f"    [레이아웃/{sev}] {code} — {sel} {text!r}")
            for c in r["contrast_fail"]:
                need = 3.0 if c.get("large") else 4.5
                print(f"    [명암비] {c['ratio']}:1 < {need}:1  {c['selector']} "
                      f"{c['text'][:24]!r}  fg{c['fg']} / bg{c['bg']}")
        print("-" * 88)
        print(f"샘플 {len(results)} · 레이아웃 findings {layout_n}"
              f"(error {layout_err} / warning {layout_warn}) · "
              f"명암비 실패 {contrast_n}/{checked_n} · 정지 샘플 {len(frozen)}")
        if args.out:
            print(f"JSON 저장: {args.out}")

    # FAIL 조건 = 레이아웃 error + 명암비 실패. 레이아웃 warning은 경고로만 센다.
    if (layout_err or contrast_n) and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
