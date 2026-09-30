# -*- coding: utf-8 -*-
"""카메라 왕복(줌인·줌아웃 반복) 검사 — 필름 HTML의 카메라 키프레임 배열을 읽어 규칙 위반을 센다 (v3.2, 2026-09-30 오너 피드백).

대상: `const CAM… = [[t, x, z], …]` 또는 `[[t, x, y, z], …]` 꼴의 배열(이름이 CAM으로 시작하거나 cam/ZOOM 포함).
규칙(스타일팩 P2 절·SKILL §4-3 "카메라 규칙"):
  R1 유지: 이동이 끝난 뒤 다음 이동 시작까지 ≥ 3.0초 (키프레임 간격 < 3.0초가 연속 2회면 위반)
  R2 폭: 한 이동의 줌 변화 |Δz| ≥ 0.15 또는 팬 |Δx| ≥ 288px(화면 폭 15%). 둘 다 미만이면 "이유 없는 밀기" 위반
  R3 왕복: 6초 안에 z가 올라갔다 내려오거나(또는 반대) 되돌아오면 위반
  R4 밀도: 구간 길이 / 이동 횟수 ≥ 4초
사용: python cam_check.py film_G4.html [--json out.json]
종료: 0 위반 없음 / 1 위반 있음 / 2 입력 오류(배열 없음)
"""
import argparse, io, json, re, sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def parse_arrays(src):
    out = {}
    for m in re.finditer(r"const\s+((?:CAM|cam|ZOOM|zoom)\w*)\s*=\s*\[(.*?)\]\s*;", src, re.S):
        name, body = m.group(1), m.group(2)
        rows = []
        for r in re.finditer(r"\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*(?:,\s*([-\d.]+))?\s*(?:,\s*([-\d.]+))?\s*\]", body):
            vals = [float(v) for v in r.groups() if v is not None]
            if len(vals) == 3:
                t, x, z = vals
            elif len(vals) == 4:
                t, x, _y, z = vals
            else:
                continue
            rows.append((t, x, z))
        if len(rows) >= 2:
            out[name] = rows
    return out


def check(rows, hold=3.0, dz_min=0.15, dx_min=288.0, back=6.0, density=4.0):
    moves = []   # (t0, t1, dz, dx)
    for (t0, x0, z0), (t1, x1, z1) in zip(rows, rows[1:]):
        if abs(z1 - z0) < 1e-6 and abs(x1 - x0) < 1e-6:
            continue
        moves.append((t0, t1, z1 - z0, x1 - x0))
    v = {"R1_hold": [], "R2_small": [], "R3_bounce": [], "R4_density": None}
    for a, b in zip(moves, moves[1:]):
        if b[0] - a[1] < hold and a[1] - a[0] < hold:
            v["R1_hold"].append(round(a[1], 2))
    for t0, t1, dz, dx in moves:
        if abs(dz) < dz_min and abs(dx) < dx_min:
            v["R2_small"].append(round(t0, 2))
    for i, a in enumerate(moves):
        for b in moves[i + 1:]:
            if b[0] - a[1] > back:
                break
            if a[2] * b[2] < -1e-6 and abs(b[2]) >= 0.05:
                v["R3_bounce"].append(round(a[0], 2)); break
    span = rows[-1][0] - rows[0][0]
    if moves and span / len(moves) < density:
        v["R4_density"] = round(span / len(moves), 2)
    return moves, v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html"); ap.add_argument("--json")
    a = ap.parse_args()
    p = Path(a.html)
    if not p.exists():
        print(f"[입력 오류] 없음: {p}", file=sys.stderr); return 2
    arrs = parse_arrays(io.open(p, encoding="utf-8").read())
    if not arrs:
        print("[입력 오류] CAM/ZOOM 키프레임 배열을 찾지 못함(카메라를 다른 방식으로 쓰면 수동 검사)", file=sys.stderr); return 2
    rc, rep = 0, {}
    for name, rows in arrs.items():
        moves, v = check(rows)
        n_bad = len(v["R1_hold"]) + len(v["R2_small"]) + len(v["R3_bounce"]) + (1 if v["R4_density"] else 0)
        if n_bad:
            rc = 1
        span = rows[-1][0] - rows[0][0]
        print(f"[{name}] 키프레임 {len(rows)} · 이동 {len(moves)} · 구간 {rows[0][0]:.1f}~{rows[-1][0]:.1f}s "
              f"(이동당 {span / max(1, len(moves)):.1f}s) → {'OK' if not n_bad else f'위반 {n_bad}'}")
        if v["R1_hold"]:
            print(f"  R1 유지 3초 미만 (이동 끝 시각): {v['R1_hold']}")
        if v["R2_small"]:
            print(f"  R2 작은 밀기(|Δz|<0.15·|Δx|<288): {v['R2_small']}")
        if v["R3_bounce"]:
            print(f"  R3 6초 안 왕복 (시작 시각): {v['R3_bounce']}")
        if v["R4_density"]:
            print(f"  R4 밀도: 이동당 {v['R4_density']}s < 4s")
        rep[name] = {"keyframes": len(rows), "moves": len(moves), "violations": v}
    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
