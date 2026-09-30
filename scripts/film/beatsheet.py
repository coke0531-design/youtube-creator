# -*- coding: utf-8 -*-
"""비트 표 기반 프레임 시트 — 필름 HTML의 비트별 대표 프레임을 한 장 jpg로.

각 비트의 start+offset 시각을 seek(t)로 캡처(타일 폭 480px로 축소), 타일 밑에
'#i t=.. "텍스트 앞 18자"' 라벨을 그려 격자로 붙인다. --times로 임의 시각도 가능(둘 다 주면 합친다).

사용:
  python beatsheet.py film.html --beats beats.json --out sheet.jpg
  python beatsheet.py film.html --beats beats.json --out sheet.jpg --offset 0.4 --cols 4
  python beatsheet.py film.html --times "1.0,2.5,4.2" --out sheet.jpg

beats.json = [{"i":1,"start":0.0,"end":2.3,"text":"..."}, ...]  (segment.py 출력)
시각은 [0, FILM.duration - 1/fps]로, 비트 안에서는 end - 1/fps 이하로 클램프한다.
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture import die, grab, open_film, parse_size  # noqa: E402

FONT = r"C:\Windows\Fonts\malgun.ttf"
TILE_W = 480
LABEL_H = 34
GAP = 6


def main():
    ap = argparse.ArgumentParser(description="비트 표 기반 프레임 시트(jpg)")
    ap.add_argument("html", help="필름 HTML 경로")
    ap.add_argument("--beats", help="beats.json (segment.py 출력)")
    ap.add_argument("--times", help='임의 시각 목록 "1.0,2.5,..."')
    ap.add_argument("--out", required=True, help="출력 jpg")
    ap.add_argument("--offset", type=float, default=0.4, help="비트 start에서 더할 초(기본 0.4)")
    ap.add_argument("--cols", type=int, default=4, help="열 수(기본 4)")
    ap.add_argument("--size", default="1920x1080", help="캡처 뷰포트(기본 1920x1080)")
    args = ap.parse_args()
    if not args.beats and not args.times:
        die("[입력 오류] --beats 또는 --times 중 하나는 필요하다")

    from PIL import Image, ImageDraw, ImageFont

    items = []   # (t_raw, label_prefix, text, clamp_end)
    if args.beats:
        beats = json.loads(Path(args.beats).read_text(encoding="utf-8"))
        for b in beats:
            items.append((float(b["start"]) + args.offset, f"#{b.get('i', '?')}",
                          str(b.get("text", "")), float(b["end"])))
    if args.times:
        for j, s in enumerate(x for x in args.times.split(",") if x.strip()):
            items.append((float(s), f"@{j + 1}", "", None))
    if not items:
        die("[입력 오류] 캡처할 시각이 없다")

    size = parse_size(args.size)
    tiles = []
    with open_film(args.html, size) as (page, cdp, film):
        fps = float(film.get("fps") or 30)
        last = float(film["duration"]) - 1.0 / fps
        for t, pre, text, bend in items:
            if bend is not None:
                t = min(t, bend - 1.0 / fps)
            t = max(0.0, min(t, last))
            img = Image.open(io.BytesIO(grab(page, cdp, t, fmt="png"))).convert("RGB")
            h = round(img.height * TILE_W / img.width)
            tiles.append((img.resize((TILE_W, h), Image.LANCZOS), pre, t, text))

    font = ImageFont.truetype(FONT, 18)
    cols = max(1, min(args.cols, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    th = tiles[0][0].height
    cell_h = th + LABEL_H
    sheet = Image.new("RGB", (cols * TILE_W + (cols + 1) * GAP, rows * cell_h + (rows + 1) * GAP), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for idx, (im, pre, t, text) in enumerate(tiles):
        r, c = divmod(idx, cols)
        x = GAP + c * (TILE_W + GAP)
        y = GAP + r * (cell_h + GAP)
        sheet.paste(im, (x, y))
        snippet = text.strip().replace("\n", " ")[:18]
        label = f'{pre} t={t:.2f}' + (f' "{snippet}"' if snippet else "")
        draw.text((x + 6, y + th + 6), label, font=font, fill=(235, 235, 235))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=88)
    print(f"[완료] {out}  타일 {len(tiles)}개 ({cols}열 x {rows}행)  {sheet.width}x{sheet.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
