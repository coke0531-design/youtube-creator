# -*- coding: utf-8 -*-
"""레이아웃 실측 게이트 — 잘림 · 겹침 · 과밀 · 정렬 (2026-09-14 신설).

왜: 풀링013 1분 비교(V1 현행·V2 캔버스 카메라) 오너 지적 3건 — ① 요소 겹침 ② 한 화면에 요소가 너무 많음
③ 요소끼리 정렬이 안 맞음 — 은 기존 게이트(스토리보드·자막 안전·모션)가 하나도 잡지 못했다. 좌표를 손으로
찍은 장면은 눈으로만 검수됐고, 캔버스 카메라는 프레임 가장자리에 다른 줄의 선·사람 조각을 잘라 넣었다.
이 게이트는 presentation.html 을 캡처 모드(?capture=1)로 열어 시간을 훑으며 DOM 실측(getBoundingClientRect ·
getPointAtLength)으로 네 가지를 판정한다. 픽셀이 아니라 요소 기하라서 결정론적이고 빠르다(1분 영상 ≈ 15초).

판정(정착 상태만 — 트윈 중인 요소와 카메라 이동 중 프레임은 잘림·겹침 검사에서 제외):
  잘림  — 보이는 요소(불투명도 ≥ 0.05)가 뷰포트(1920×1080) 가장자리에 걸쳐 일부만 보임. 선은 표본점 기준.
  겹침  — 도형끼리 사각형이 교차(작은 쪽 면적의 3% 초과) · 선의 표본점이 도형 안쪽(선 굵기·6px 안쪽)을 관통.
          같은 data-grp 끼리는 허용(종이 더미·말풍선+꼬리처럼 의도한 포개기).
  과밀  — 한 프레임에 보이는 도형 단위(data-grp 가 같으면 1단위)가 상한(기본 8)을 넘음. 선은 세지 않는다.
  정렬  — data-row 가 같은 요소는 세로 중심, data-col 이 같은 요소는 가로 중심이 허용치(6px) 안이어야 한다.
          선언이 없어도: 라벨 칩(.chip)은 바로 위 도형과 가로 중심이 8px 안(옆 도형과 한 묶음인 칩은 제외) ·
          같은 종류·같은 크기 도형(칩 제외) 2개 이상은 한 줄(세로 중심) 또는 한 열(가로 중심) 중 하나로 6px 안.
선언 속성: data-grp="이름"  같은 그룹 = 겹침 허용 + 과밀 1단위 + 동종 정렬 제외(종이 더미·말풍선 묶음)
           data-under="kcard abs"  (선에) 이 종류 도형 아래로 지나가도 됨(경로 위 정거장 카드·체크포인트)
           data-row / data-col      한 줄·한 열 정렬 선언

대상 선택자(장면 부품 규약): 도형 = .fig .logo .chip .bub .kcard .paper .kpi .big3 .mini-ico .ttl .abs
                          선 = svg path/line/polyline (아이콘 심볼 내부 제외). 필요하면 --solid/--stroke 로 바꾼다.

사용:
  python check_layout.py <presentation.html> --timeline <타임라인.json> [--step 0.2] [--max-units 8]
                         [--json out.json] [--warn-only] [--times 3.0 4.5 ...]
종료 코드: 위반 1건 이상이면 1 (--warn-only 면 0). 임계는 완화하지 말고 장면을 고친다(design.md §4 규칙).
"""
import argparse, json, pathlib, sys
from playwright.sync_api import sync_playwright

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

VW, VH = 1920, 1080
SOLID = ".fig,.logo,.chip,.bub,.kcard,.paper,.kpi,.big3,.mini-ico,.ttl,.abs"
STROKE_SKIP = "symbol,defs,.fig,.kcard,.mini-ico,.logo,.ico"

COLLECT_JS = r"""
([SOLID, STROKE_SKIP]) => {
  const slide = document.querySelector('.slide.active'); if (!slide) return null;
  const key = slide.dataset.tl || null;
  const tl = key && window.__slideTimelines ? window.__slideTimelines[key] : null;
  const lt = tl ? tl.time() : 0;
  const moving = new Set(); let camMoving = false;
  if (tl) tl.getChildren(true, true, false).forEach(tw => {
    const s = tw.startTime(), d = tw.totalDuration();
    if (lt >= s - 1e-4 && lt <= s + d + 1e-4) tw.targets().forEach(x => { moving.add(x); if (x.classList && x.classList.contains('canvas')) camMoving = true; });
  });
  function isMoving(el) { let n = el; while (n && n !== slide) { if (moving.has(n)) return true; n = n.parentElement; } return false; }   // 조상이 트윈 중이면 같이 이동 중
  function effOp(el) { let o = 1, n = el; while (n && n !== slide) { o *= parseFloat(getComputedStyle(n).opacity); n = n.parentElement; } return o; }
  const solids = [];
  slide.querySelectorAll(SOLID).forEach(el => {
    if (el.matches('.tgt') || el.closest('.tgt')) return;
    if (el.parentElement && el.parentElement.closest(SOLID) && el.parentElement.closest(SOLID) !== el) return;   // 중첩 도형은 바깥만
    const o = effOp(el); if (o < 0.05) return;
    const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return;
    solids.push({ id: (el.getAttribute('class') || el.tagName), op: +o.toFixed(2), rect: [r.left, r.top, r.right, r.bottom],
      grp: el.dataset.grp || null, row: el.dataset.row || null, col: el.dataset.col || null,
      chip: el.classList.contains('chip'), cls: (el.getAttribute('class') || '').split(/\s+/), moving: isMoving(el), text: (el.textContent || '').trim().slice(0, 8) });
  });
  const strokes = [];
  slide.querySelectorAll('svg path, svg line, svg polyline').forEach(p => {
    if (p.closest(STROKE_SKIP)) return;
    const o = effOp(p); if (o < 0.05) return;
    const cs = getComputedStyle(p);
    let frac = 1; const doff = parseFloat(cs.strokeDashoffset) || 0; const da = parseFloat(cs.strokeDasharray) || 0;
    let L = 1; try { L = p.getTotalLength(); } catch (e) { return; }
    if (p.getAttribute('pathLength') === '1' && da >= 0.99 && da <= 1.01) frac = 1 - doff;
    else if (da > 0 && da >= L * 0.9) frac = 1 - doff / da;
    if (frac <= 0.02) return;
    const ctm = p.getScreenCTM(); if (!ctm) return;
    const pts = []; const N = 40;
    for (let i = 0; i <= N; i++) { const q = p.getPointAtLength(L * frac * i / N); pts.push([ctm.a * q.x + ctm.c * q.y + ctm.e, ctm.b * q.x + ctm.d * q.y + ctm.f]); }
    const sc = Math.hypot(ctm.a, ctm.b);
    strokes.push({ id: (p.getAttribute('class') || p.tagName), pts, sw: (parseFloat(cs.strokeWidth) || 1) * sc, grp: p.dataset.grp || null, under: (p.dataset.under || '').split(/\s+/).filter(Boolean), moving: isMoving(p), op: +o.toFixed(2) });
  });
  return { slide: key, lt, camMoving, solids, strokes };
}
"""


def inter(a, b):
    l, t, r, btm = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return max(0, r - l) * max(0, btm - t)


def area(a): return max(0, a[2] - a[0]) * max(0, a[3] - a[1])


def visible_frac(rect):
    return inter(rect, [0, 0, VW, VH]) / max(1e-6, area(rect))


def analyze(snap, max_units, tol_row, tol_label):
    """한 시각의 스냅샷 → 위반 목록 [(종류, 키, 설명)]"""
    out = []
    if not snap: return out
    solids, strokes = snap["solids"], snap["strokes"]
    settled = not snap["camMoving"]
    # 잘림
    if settled:
        for s in solids:
            if s["moving"]: continue
            f = visible_frac(s["rect"])
            if 0.03 < f < 0.97:
                out.append(("잘림", f'{s["id"]}', f'{s["id"]}({s["text"]}) 가 {f*100:.0f}%만 보임'))
        for st in strokes:
            if st["moving"]: continue
            ins = sum(1 for x, y in st["pts"] if 0 <= x <= VW and 0 <= y <= VH)
            n = len(st["pts"])
            if 0 < ins < n and 0.05 < ins / n < 0.95:
                out.append(("잘림", f'선 {st["id"]}', f'선 {st["id"]} 이 {ins/n*100:.0f}%만 보임(가장자리 관통)'))
    # 겹침
    if settled:
        for i in range(len(solids)):
            a = solids[i]
            if a["moving"]: continue
            for j in range(i + 1, len(solids)):
                b = solids[j]
                if b["moving"]: continue
                if a["grp"] and a["grp"] == b["grp"]: continue
                x = inter(a["rect"], b["rect"])
                if x > 0.03 * min(area(a["rect"]), area(b["rect"])):
                    out.append(("겹침", f'{a["id"]}|{b["id"]}', f'{a["id"]}({a["text"]}) × {b["id"]}({b["text"]}) 사각형 교차 {x:.0f}px²'))
        for st in strokes:
            if st["moving"]: continue
            for s in solids:
                if s["moving"] or (st["grp"] and st["grp"] == s["grp"]): continue
                if any(u in s["cls"] for u in st["under"]): continue   # data-under="kcard abs": 그 종류 아래/위로 지나가도 됨
                m = max(6, st["sw"])
                l, t, r, b = s["rect"][0] + m, s["rect"][1] + m, s["rect"][2] - m, s["rect"][3] - m
                if r <= l or b <= t: continue
                hit = sum(1 for x, y in st["pts"] if l < x < r and t < y < b)
                if hit:
                    out.append(("겹침", f'선 {st["id"]}|{s["id"]}', f'선 {st["id"]} 이 {s["id"]}({s["text"]}) 안쪽을 관통(표본 {hit}점)'))
    # 과밀 — 도형 단위(그룹 1단위), 불투명도 ≥ 0.5 만 정식으로 센다
    units = set()
    for s in solids:
        if s["op"] >= 0.5 and inter(s["rect"], [0, 0, VW, VH]) > 0: units.add(s["grp"] or id(s))
    if len(units) > max_units:
        names = sorted({(s["grp"] or s["id"].split()[0]) for s in solids if s["op"] >= 0.5 and inter(s["rect"], [0, 0, VW, VH]) > 0})
        out.append(("과밀", f'{len(units)}', f'보이는 도형 {len(units)}단위 > 상한 {max_units} — {", ".join(names)}'))
    # 정렬 — 선언(data-row/col)
    if settled:
        rows, cols = {}, {}
        for s in solids:
            if s["moving"]: continue
            if s["row"]: rows.setdefault(s["row"], []).append(s)
            if s["col"]: cols.setdefault(s["col"], []).append(s)
        for name, g in rows.items():
            if len(g) < 2: continue
            cy = [(r["rect"][1] + r["rect"][3]) / 2 for r in g]
            if max(cy) - min(cy) > tol_row:
                out.append(("정렬", f'row:{name}', f'data-row={name} 세로 중심 편차 {max(cy)-min(cy):.0f}px > {tol_row}'))
        for name, g in cols.items():
            if len(g) < 2: continue
            cx = [(r["rect"][0] + r["rect"][2]) / 2 for r in g]
            if max(cx) - min(cx) > tol_row:
                out.append(("정렬", f'col:{name}', f'data-col={name} 가로 중심 편차 {max(cx)-min(cx):.0f}px > {tol_row}'))
        # 자동: 라벨 칩 ↔ 바로 위 도형
        for c in solids:
            if not c["chip"] or c["moving"]: continue
            best = None
            ccy = (c["rect"][1] + c["rect"][3]) / 2
            inline = any((not s is c) and (not s["moving"]) and abs((s["rect"][1] + s["rect"][3]) / 2 - ccy) <= 40 and
                         (0 <= c["rect"][0] - s["rect"][2] <= 60 or 0 <= s["rect"][0] - c["rect"][2] <= 60) for s in solids)
            if inline: continue   # 옆 도형과 한 묶음(예: 「3」+「핵심」) — 위 도형의 라벨이 아니다
            for s in solids:
                if s is c or s["chip"] or s["moving"] or s["id"].split()[0] == "abs": continue
                if c["grp"] and c["grp"] == s["grp"]: continue
                gap = c["rect"][1] - s["rect"][3]
                if -4 <= gap <= 150 and min(c["rect"][2], s["rect"][2]) > max(c["rect"][0], s["rect"][0]):
                    if best is None or gap < best[0]: best = (gap, s)
            if best:
                s = best[1]
                dx = abs((c["rect"][0] + c["rect"][2]) / 2 - (s["rect"][0] + s["rect"][2]) / 2)
                if dx > tol_label:
                    out.append(("정렬", f'label:{c["id"]}', f'라벨 {c["id"]}({c["text"]}) 가 위 도형 {s["id"]} 과 가로 중심 {dx:.0f}px 어긋남 > {tol_label}'))
        # 자동: 같은 종류·같은 크기 도형은 한 줄 또는 한 열
        kinds = {}
        for s in solids:
            if s["moving"] or s["chip"]: continue
            w, h = round(s["rect"][2] - s["rect"][0]), round(s["rect"][3] - s["rect"][1])
            kinds.setdefault((s["id"].split()[0], w // 4, h // 4), []).append(s)
        for (k, w, h), g in kinds.items():
            if len(g) < 2: continue
            if len({x["grp"] for x in g}) == 1 and g[0]["grp"]: continue   # 같은 그룹(종이 더미)은 제외
            cy = [(r["rect"][1] + r["rect"][3]) / 2 for r in g]; cx = [(r["rect"][0] + r["rect"][2]) / 2 for r in g]
            dy, dx = max(cy) - min(cy), max(cx) - min(cx)
            if dy > tol_row and dx > tol_row:
                out.append(("정렬", f'kind:{k}', f'같은 종류 {k} {len(g)}개가 한 줄도 한 열도 아님(세로 편차 {dy:.0f}·가로 편차 {dx:.0f})'))
    return out


def run(html, timeline, step=0.2, max_units=8, tol=6.0, tol_label=8.0, skip_overlay=True, times=None):
    """게이트 본체(capture_slides.py 가 캡처 전에 자동 호출). 반환 = (found, counts, maxu, times, skipped)
    found: {(slide, 종류, 키): {desc, times}} — 비어 있으면 PASS."""
    html, timeline = pathlib.Path(html), pathlib.Path(timeline)
    tl = json.loads(timeline.read_text(encoding="utf-8"))
    if "duration" not in tl: raise SystemExit(f"[오류] 타임라인에 duration 이 없다: {timeline}")
    dur = float(tl["duration"])
    if times is None and not (step > 0): raise SystemExit(f"[오류] --step 은 양수여야 한다: {step}")
    # 오버레이(콜라주 등 video_overlays 전부)가 덮는 구간은 슬라이드가 보이지 않으므로 건너뛴다 — 건너뛴 구간은 리포트에 명시
    skipped = [] if not skip_overlay else [(float(o["start"]), float(o["end"])) for o in tl.get("video_overlays", [])]
    if times is not None:
        times = sorted(float(t) for t in times)          # __capture.seek 는 순방향 전용 — 역순 입력이면 앞 시각이 건너뛰어진다
    else:
        times, t = [], 0.0
        while t < dur - 1e-6:
            if not any(s <= t < e for s, e in skipped): times.append(round(t, 3))
            t += step

    found = {}   # (slide, kind, key) -> {desc, times}
    maxu = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1"])
        pg = b.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=1)
        pg.goto(html.resolve().as_uri() + "?capture=1")
        pg.wait_for_function("window.__capture && window.__capture.ready", timeout=30000)
        for t in times:
            pg.evaluate(f"window.__capture.seek({t})")
            pg.wait_for_timeout(25)
            snap = pg.evaluate(COLLECT_JS, [SOLID, STROKE_SKIP])
            if not snap: continue
            sid = snap["slide"] or "?"
            n_units = len({(s["grp"] or i) for i, s in enumerate(snap["solids"]) if s["op"] >= 0.5 and inter(s["rect"], [0, 0, VW, VH]) > 0})
            if n_units > maxu.get(sid, (0, 0))[0]: maxu[sid] = (n_units, t)
            for kind, key, desc in analyze(snap, max_units, tol, tol_label):
                e = found.setdefault((sid, kind, key), {"desc": desc, "times": []})
                e["times"].append(t)
        b.close()
    kinds = ["잘림", "겹침", "과밀", "정렬"]
    counts = {k: sum(1 for (sid, kd, key) in found if kd == k) for k in kinds}
    return found, counts, maxu, times, skipped


def format_report(html, found, counts, maxu, times, skipped, step, max_units):
    def rng(ts):
        ts = sorted(ts); segs = []; s0 = p0 = ts[0]
        for x in ts[1:]:
            if x - p0 > step * 1.5 + 1e-6: segs.append((s0, p0)); s0 = x
            p0 = x
        segs.append((s0, p0))
        return ", ".join(f"{s:.1f}~{e:.1f}s" if e > s else f"{s:.1f}s" for s, e in segs[:4]) + (" …" if len(segs) > 4 else "")
    out = [f"# check_layout — {pathlib.Path(html).name}  (검사 시각 {len(times)}개 · step {step}s · 도형 상한 {max_units})",
           "| 종류 | 건수 |", "|---|---|"]
    out += [f"| {k} | {counts[k]} |" for k in ["잘림", "겹침", "과밀", "정렬"]]
    if skipped: out.append("\n건너뛴 구간(오버레이가 덮음, 미검사): " + ", ".join(f"{s:.1f}~{e:.1f}s" for s, e in skipped))
    out.append("\n## 슬라이드별 최대 도형 단위")
    out += [f"- {sid}: {n}단위 (t={t:.1f}s)" for sid, (n, t) in sorted(maxu.items())]
    if found:
        out.append("\n## 위반 목록")
        out += [f"- [{kd}] {sid}: {e['desc']} — {rng(e['times'])}" for (sid, kd, key), e in sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1], min(kv[1]["times"])))]
    verdict = "PASS" if not found else "FAIL"
    out.append(f"\n판정: {verdict} (잘림 {counts['잘림']} · 겹침 {counts['겹침']} · 과밀 {counts['과밀']} · 정렬 {counts['정렬']})")
    out.append("참고: 정착 상태만 검사(트윈 중·카메라 이동 중 제외). 임계는 완화하지 말고 장면 좌표·프레임을 고친다.")
    return "\n".join(out), verdict


def main():
    ap = argparse.ArgumentParser(description="레이아웃 실측 게이트(잘림·겹침·과밀·정렬)")
    ap.add_argument("html", type=pathlib.Path)
    ap.add_argument("--timeline", type=pathlib.Path, required=True)
    ap.add_argument("--step", type=float, default=0.2)
    ap.add_argument("--times", type=float, nargs="*", help="지정 시각만 검사")
    ap.add_argument("--max-units", type=int, default=8)
    ap.add_argument("--tol", type=float, default=6.0, help="행/열 정렬 허용 px")
    ap.add_argument("--tol-label", type=float, default=8.0, help="라벨 칩 가로 중심 허용 px")
    ap.add_argument("--no-skip-overlay", action="store_true", help="비디오 오버레이가 덮는 구간도 검사")
    ap.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--warn-only", action="store_true")
    a = ap.parse_args()
    if a.times is None and not (a.step > 0): ap.error(f"--step 은 양수여야 한다: {a.step}")
    found, counts, maxu, times, skipped = run(a.html, a.timeline, a.step, a.max_units, a.tol, a.tol_label,
                                              skip_overlay=not a.no_skip_overlay, times=a.times)
    text, verdict = format_report(a.html, found, counts, maxu, times, skipped, a.step, a.max_units)
    print(text)
    if a.json:
        a.json.write_text(json.dumps({"html": str(a.html), "counts": counts, "max_units": {k: v for k, v in maxu.items()},
                                      "issues": [{"slide": s, "kind": k, "key": key, "desc": e["desc"], "times": e["times"]} for (s, k, key), e in found.items()]},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if (verdict == "PASS" or a.warn_only) else 1)


if __name__ == "__main__":
    main()
