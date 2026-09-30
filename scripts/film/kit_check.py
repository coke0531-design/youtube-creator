# -*- coding: utf-8 -*-
"""캐릭터·킷 일관성 검사기 (정본 v3.2, 2026-09-30 — 편입안 §4 ①②③).

  ① --gallery      : 템플릿/film/kit_gallery.html 을 헤드리스로 찍어 kit_gallery.golden.png 와 픽셀 비교.
                     max diff ≤ 8 이면 통과. kit.js 가 다르게 그리면 FAIL(골든을 다시 만들 때는 --make-golden 과 이유 기록).
  ① --make-golden  : 현재 킷으로 골든을 (다시) 만든다.
  ② 폴더 스캔       : 위치 인자로 준 작업 폴더(04_영상소스 또는 그 위)의 kit.js·film_*.html·kit_ext.js 를 읽어
                     - kit.js md5 = 정본(템플릿/film/kit.js) md5   (다르면 FAIL — 실험판 사본은 불일치가 정상)
                     - 필름이 character( 를 직접 정의하지 않음        (function character / character = … / KIT.character = …)
                     - STAR 배열 재정의 없음
                     - 색 hex(따옴표 안 '#RRGGBB'·<style> 안)가 정본 킷 팔레트 밖이면 FAIL
                       (허용 = 정본 kit.js 에 적힌 hex 전부 + live.js 의 빠진 프레임 표시 #FF00FF. 실사 프레임·로고 이미지는 hex가 아니라 대상 아님)
  ③ 폴더 여러 개    : 편별 표(kit md5 · 캐릭터 기본 h · GROUND · 점프 기본 · 토큰 별 배율 · 굵기 단 · 표정/자세 사용 · 위반 수).

사용:
  python scripts/film/kit_check.py --make-golden
  python scripts/film/kit_check.py --gallery
  python scripts/film/kit_check.py "<작업>/04_영상소스" ["<다른 편>/애프터_v3.2" …] [--json out.json]
  (--gallery 와 폴더를 같이 주면 둘 다 한다)

종료 코드: 0 통과 / 1 FAIL(골든 차이·스캔 위반) / 2 입력 오류(골든 없음·폴더 없음·capture.py 없음 등)
주의: 한글 경로라 cv2.imread/imwrite 를 쓰지 않는다(np.fromfile + imdecode / imencode + tofile).
"""
import argparse
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent                      # <정본>/scripts/film
ROOT = HERE.parents[1]                                      # <정본>
TPL = ROOT / "템플릿" / "film"
KIT = TPL / "kit.js"
GALLERY = TPL / "kit_gallery.html"
GOLDEN = TPL / "kit_gallery.golden.png"
LAB_SCRIPTS = ROOT.parent / "youtube-creator-lab" / "scripts"   # 정본 scripts/film/capture.py 가 없을 때만 쓰는 대체 경로
MAX_DIFF = 8
LIVE_MISSING = "#FF00FF"                                    # live.js: 못 불러온 실사 프레임 표시색(결정론 검사용)
SKIP_DIRS = ("cap_", "_smoke", "실사프레임", "__pycache__", "node_modules")


def die(msg):
    print(f"[입력 오류] {msg}", file=sys.stderr)
    raise SystemExit(2)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


# ---------------------------------------------------------------- ① 갤러리
def load_capture():
    for d in (HERE, LAB_SCRIPTS):
        if (d / "capture.py").exists():
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            import capture  # noqa: E402
            if d != HERE:
                print(f"[안내] 정본 scripts/film/capture.py 가 없어 실험판 {d} 의 capture.py 를 쓴다")
            return capture
    die(f"capture.py 를 찾지 못했다: {HERE} · {LAB_SCRIPTS}")


def shoot_gallery():
    import numpy as np
    import cv2
    cap = load_capture()
    if not GALLERY.exists():
        die(f"갤러리 없음: {GALLERY}")
    with cap.open_film(GALLERY, (1920, 1080)) as (page, cdp, film):
        png = cap.grab(page, cdp, 0.0)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    return png, img


def imread_u(p):
    import numpy as np
    import cv2
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, img):
    import cv2
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 인코딩 실패")
    buf.tofile(str(p))


def make_golden():
    _, img = shoot_gallery()
    imwrite_u(GOLDEN, img)
    back = imread_u(GOLDEN)
    if back is None or back.shape != img.shape:
        die(f"골든 저장 뒤 다시 읽기 실패: {GOLDEN}")
    print(f"[골든] {GOLDEN}  {img.shape[1]}x{img.shape[0]}  kit md5 {md5(KIT)[:8]}")
    return 0


def check_gallery():
    import numpy as np
    if not GOLDEN.exists():
        die(f"골든 없음: {GOLDEN} (먼저 --make-golden)")
    gold = imread_u(GOLDEN)
    _, cur = shoot_gallery()
    if gold is None or cur is None or gold.shape != cur.shape:
        print(f"[갤러리] FAIL 크기 다름 골든 {None if gold is None else gold.shape} · 현재 {None if cur is None else cur.shape}")
        return 1
    d = np.abs(gold.astype(np.int16) - cur.astype(np.int16))
    mx, npx = int(d.max()), int((d.max(axis=2) > MAX_DIFF).sum())
    if mx <= MAX_DIFF:
        print(f"[갤러리] 통과  max diff {mx} (≤ {MAX_DIFF})  kit md5 {md5(KIT)[:8]}")
        return 0
    outp = Path(tempfile.gettempdir()) / "kit_gallery.current.png"
    imwrite_u(outp, cur)
    ys, xs = np.nonzero(d.max(axis=2) > MAX_DIFF)
    print(f"[갤러리] FAIL  max diff {mx} > {MAX_DIFF} · 차이 픽셀 {npx} · 범위 x {xs.min()}~{xs.max()} y {ys.min()}~{ys.max()}")
    print(f"  현재 캡처: {outp}  (킷을 일부러 바꿨다면 --make-golden 으로 골든 갱신 + 이유를 킷-규격.md 변경 기록에)")
    return 1


# ---------------------------------------------------------------- ②③ 스캔
RE_HEX_Q = re.compile(r"""['"`](#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})['"`]""")
RE_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
RE_HEX_CSS = re.compile(r"(?<![\w&])(#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b")
RE_CHAR_DEF = re.compile(r"function\s+character\s*\(|\b(?:const|let|var)\s+character\s*=|\bKIT\s*\.\s*character\s*=|\bK\s*\.\s*character\s*=")
RE_STAR_DEF = re.compile(r"\b(?:const|let|var)\s+STAR\s*=|\bKIT\s*\.\s*STAR\s*=|\bK\s*\.\s*STAR\s*=")
RE_FACE = re.compile(r"""\bface\s*[:=]\s*['"](\w+)['"]""")
RE_FACES = re.compile(r"""\bfaces\s*:\s*\[([^\]]*)\]""")
RE_POSE = re.compile(r"""\bpose\s*[:=]\s*['"](\w+)['"]""")


def norm_hex(h):
    h = h.upper()
    if len(h) == 4:                                          # #abc → #AABBCC
        h = "#" + "".join(c * 2 for c in h[1:])
    return h[:7]                                             # #RRGGBBAA → 색만


def allowed_hex():
    s = {norm_hex(h) for h in re.findall(r"['\"](#[0-9a-fA-F]{3,8})['\"]", read(KIT))}
    s.add(LIVE_MISSING)
    return s


def hex_in(src):
    out = [m.group(1) for m in RE_HEX_Q.finditer(src)]
    for st in RE_STYLE.findall(src):
        out += RE_HEX_CSS.findall(st)
    return out


def kit_facts(src):
    """kit.js 본문에서 규격 값을 읽는다(없으면 None)."""
    def g(rx, cast=str):
        m = re.search(rx, src)
        return cast(m.group(1)) if m else None
    f = {
        "GROUND": g(r"GROUND\s*=\s*(\d+)", int),
        "h": g(r"function character[\s\S]{0,900}?o\.h\s*\|\|\s*(\d+)", int),
        "jump": g(r"const (?:hop|jumpH)\s*=\s*\([^)]*h\s*=\s*(\d+)", int),   # G = hop(…, h = 60), H = jumpH(…, h = 110)
        "tokenStar": ("r·1.34/13" if re.search(r"r\s*\*\s*1\.34\s*/\s*13", src) else
                      "r·0.125" if re.search(r"r\s*\*\s*\.125", src) else None),
        "weights": 4 if re.search(r"\[\s*900\s*,", src) else 3 if re.search(r"\[\s*800\s*,\s*'ExtraBold'", src) else None,
        "version": g(r"VERSION\s*:\s*'([\d.]+)'"),
        "hold": bool(re.search(r"pose\s*===\s*'hold'", src)),
        "person": bool(re.search(r"function person\s*\(", src)),
    }
    return f


def find_workdir(p):
    p = Path(p)
    if (p / "04_영상소스").is_dir():
        return p / "04_영상소스"
    return p


def walk(d):
    for f in sorted(d.rglob("*")):
        if any(part.startswith(SKIP_DIRS) for part in f.relative_to(d).parts[:-1]):
            continue
        if f.is_file():
            yield f


def scan(folder, canon_md5, allow):
    d = find_workdir(folder)
    if not d.is_dir():
        die(f"폴더 없음: {folder}")
    files = list(walk(d))
    kits = sorted([f for f in files if f.name == "kit.js"], key=lambda f: len(f.relative_to(d).parts))
    films = [f for f in files if re.match(r"film_.*\.html$", f.name)]
    exts = [f for f in files if f.name == "kit_ext.js"]
    rep = {"folder": str(folder), "workdir": str(d), "films": len(films), "fails": [], "warns": []}
    if kits:
        k = kits[0]
        km = md5(k)
        rep["kit"] = str(k.relative_to(d))
        rep["kit_md5"] = km
        rep["kit_match"] = km == canon_md5
        rep.update(kit_facts(read(k)))
        if km != canon_md5:
            rep["fails"].append(f"kit.js md5 {km[:8]} ≠ 정본 {canon_md5[:8]} ({k.relative_to(d)})")
        for extra in kits[1:]:
            if md5(extra) != canon_md5:
                rep["warns"].append(f"다른 kit.js 사본 md5 불일치: {extra.relative_to(d)}")
    else:
        rep["kit"] = None
        rep["kit_md5"] = None
        rep["kit_match"] = None
        rep["warns"].append("kit.js 없음(필름 안 인라인 킷?)")
    faces, poses = {}, {}
    for f in films + exts:
        src = read(f)
        rel = str(f.relative_to(d))
        if RE_CHAR_DEF.search(src):
            rep["fails"].append(f"character( 직접 정의: {rel}")
        if RE_STAR_DEF.search(src):
            rep["fails"].append(f"STAR 재정의: {rel}")
        bad = sorted({norm_hex(h) for h in hex_in(src)} - allow)
        if bad:
            rep["fails"].append(f"팔레트 밖 hex {', '.join(bad)}: {rel}")
        for m in RE_FACE.findall(src):
            faces[m] = faces.get(m, 0) + 1
        for grp in RE_FACES.findall(src):
            for m in re.findall(r"['\"](\w+)['\"]", grp):
                faces[m] = faces.get(m, 0) + 1
        for m in RE_POSE.findall(src):
            poses[m] = poses.get(m, 0) + 1
    rep["faces"] = faces
    rep["poses"] = poses
    extra_faces = sorted(set(faces) - {"base", "focus", "surprise"})
    if extra_faces:
        rep["fails"].append(f"표정 3종 밖: {', '.join(extra_faces)}")
    return rep


def short_name(folder):
    p = Path(folder)
    parts = [x for x in p.parts if x not in ("04_영상소스",)]
    tail = parts[-2:] if len(parts) >= 2 else parts
    return "/".join(tail)


def print_table(reps, canon):
    cf = kit_facts(read(KIT))
    print(f"\n정본 kit.js md5 {canon[:8]} · v{cf['version']} · GROUND {cf['GROUND']} · h {cf['h']} · 점프 {cf['jump']} · "
          f"토큰 별 {cf['tokenStar']} · 굵기 {cf['weights']}단 · hold {cf['hold']} · person {cf['person']}\n")
    hdr = ["편", "kit md5", "일치", "GROUND", "h", "점프", "토큰 별", "굵기", "필름", "표정 사용", "자세 사용", "판정"]
    rows = []
    for r in reps:
        fx = lambda k: "—" if r.get(k) is None else str(r.get(k))
        face = " ".join(f"{k}{v}" for k, v in sorted(r["faces"].items(), key=lambda x: -x[1])) or "—"
        pose = " ".join(f"{k}{v}" for k, v in sorted(r["poses"].items(), key=lambda x: -x[1])) or "—"
        verdict = "OK" if not r["fails"] else f"FAIL {len(r['fails'])}"
        rows.append([short_name(r["folder"]), (r["kit_md5"] or "없음")[:8],
                     "—" if r["kit_match"] is None else ("예" if r["kit_match"] else "아니오"),
                     fx("GROUND"), fx("h"), fx("jump"), fx("tokenStar"), (fx("weights") + "단") if r.get("weights") else "—",
                     str(r["films"]), face, pose, verdict])
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for row in rows:
        print("| " + " | ".join(row) + " |")
    for r in reps:
        if r["fails"] or r["warns"]:
            print(f"\n[{short_name(r['folder'])}]")
            for s in r["fails"]:
                print(f"  FAIL  {s}")
            for s in r["warns"]:
                print(f"  경고  {s}")


def main():
    ap = argparse.ArgumentParser(description="정본 킷 일관성 검사(갤러리 골든 비교 + 작업 폴더 스캔)")
    ap.add_argument("folders", nargs="*", help="스캔할 작업 폴더(04_영상소스 또는 그 위 애프터 폴더)")
    ap.add_argument("--gallery", action="store_true", help="kit_gallery.html 을 찍어 골든과 비교(max ≤ 8)")
    ap.add_argument("--make-golden", action="store_true", help="골든 png 를 (다시) 만든다")
    ap.add_argument("--json", help="스캔 결과 JSON 저장 경로")
    a = ap.parse_args()
    if not KIT.exists():
        die(f"정본 kit.js 없음: {KIT}")
    if not (a.gallery or a.make_golden or a.folders):
        ap.print_help()
        return 2
    rc = 0
    if a.make_golden:
        rc = max(rc, make_golden())
    if a.gallery:
        rc = max(rc, check_gallery())
    if a.folders:
        canon = md5(KIT)
        allow = allowed_hex()
        reps = [scan(f, canon, allow) for f in a.folders]
        print_table(reps, canon)
        if any(r["fails"] for r in reps):
            rc = max(rc, 1)
        if a.json:
            Path(a.json).write_text(json.dumps(reps, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
