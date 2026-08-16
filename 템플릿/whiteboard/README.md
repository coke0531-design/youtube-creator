# 템플릿/whiteboard/ — 화이트보드 드로잉 장면 (whiteboard draw, 선택 연출)

플랫 인포그래픽(차트·카드·리스트) 사이에 **"펜이 그림을 그려 나가는" 장면**을 끼워 넣는 연출이다. 스토리·비유·개념 설명처럼 수치가 없는 대목에서 "종이에 그려 주는 설명" 느낌을 낸다. 렌더 엔진·출처·롤백은 `scripts/whiteboard/README.md`, 파이프라인 단계는 youtube-editor SKILL.md **Step 6.6**, 게이트는 design.md §4 렉시콘 표.

## 파일

| 파일 | 역할 |
|------|------|
| `scene-example.svg` | 장면 예시(사람 → 노트북(AI) → 완료 문서). 복사해서 새 장면의 출발점으로 쓴다 |
| `hand-marker-amber-top.png` | **기본 손 자산** — 위에서 내려오는 손(펜촉 = 좌하단, 손은 우상단으로 뻗음). 손이 하단 자막 영역을 덮지 않는다(2026-08-16 실측으로 결정). `hand-marker-amber.png`를 반시계 90° 회전한 것 |
| `hand-marker-amber.svg` / `.png` | 손+마커 원본(4색 벡터, 자체 제작) — 아래에서 올라오는 손(펜촉 = 좌상단). 하단 근처를 그릴 때 자막을 가리므로 기본에서 제외. SVG를 고치면 PNG·top PNG를 다시 굽는다(아래) |
| `README.md` | 이 문서 |

## 장면 SVG 작성 규칙 (그대로 지키면 래퍼 가드를 통과한다)

1. **캔버스 1920x1080, 배경 흰색** `<rect width="1920" height="1080" fill="#ffffff"/>` — 미색·회색 배경 금지(design.md 흰 배경 고정).
2. **4색만**: 선 = 잉크 `#141413`(두께 6~10px, round cap/join), 채움 = 흰색 / 뉴트럴 `#f7f6f4` / 앰버 `#F59E0B` / 그린 `#16a34a`. 레드·블루·보라 금지. 원 도구의 "미색 종이 + 빨강·주황·파랑 점묘"는 쓰지 않는다.
3. **하단 21%(y > 853)는 비운다** — 자막 안전 영역. 래퍼가 잉크 0.3% 초과 시 중단한다.
4. **글자를 넣지 않는다** — 텍스트는 자막·슬라이드 몫. 고유명사 로고도 텍스트 대신 도형(또는 슬라이드의 로고 칩)으로.
5. **그릴 순서 = `data-wb="N"`** 을 `<g>`에 붙인다(1부터 연속, 중복 금지). 순서는 나레이션이 언급하는 순서 = "배경 → 주인공 → 변화 → 결과". `data-wb-label`은 로그·편집지시서용 이름.
6. **나레이션과 맞추기(선택)**: `data-wb-t="3.2"`(클립 시작 기준 초, transcript 실측)를 주면 그 시각에 그 구역을 그리기 시작한다. **전부 주거나 전부 생략**(혼용 금지). 생략하면 면적(√)×`data-wb-w`(가중, 기본 1)에 비례해 배분. 내용은 적은데 문장이 긴 구역은 `data-wb-d="1.2"`(최대 그리기 초)로 빨리 그리고 멈추게 한다. `--dry-run`이 구역별 [시작~끝·잉크 px/s] 진단표를 찍어 준다(참고 밴드 3k~30k px/s) — 나레이션 문장 시작 시각과 나란히 놓고 맞춘다.
7. **간결하게** — 구역 3~6개, 선은 굵고 적게. 원 도구 권장대로 "극단적으로 미니멀한 스케치". 그림자·그라데이션·질감 금지.
8. **인물·사물은 한 덩어리로 잇는다** — 엔진은 한 구역 안에서 '가장 큰 덩어리 → 가까운 조각' 순으로 그리므로, 몸에서 떨어진 머리·눈·장식은 맨 나중에 그려져 기괴해 보인다. 머리는 목선으로 몸에 붙이고, 반드시 먼저 나와야 할 것은 `data-wb` 그룹을 따로 뗀다(인물 → 소품 → 화살표처럼).
9. **구역은 사각 bbox** — 뒤 구역의 사각형이 앞 구역과 겹치면 겹친 픽셀은 뒤 차례에 그려진다(둘러싸는 순환 화살표·큰 배경 그룹이 함정). `--dry-run` 진단표의 '가려짐 %'를 0으로 만든다: 그룹을 쪼개고(위 호·아래 호 따로) 배치를 옮긴다.
10. **전환 규칙** — 클립 끝 0.45s는 흰색으로 페이드된다(`--fade-out`, 슬라이드 크로스 디졸브와 동일). 오버레이 **end = 다음 슬라이드 시작 + 0.45s**, start = 해당 슬라이드 시작. 이렇게 해야 경계의 반쯤 섞인 디졸브 프레임이 드러나지 않는다.
11. 이 장면은 **정지 그림 1장**이다. 요소 자체의 모션(스태거·팝)은 없다 — 움직임은 "그려지는 과정"이 전부다. 요소 등장 안무가 필요하면 화이트보드가 아니라 일반 슬라이드+렉시콘 preset을 쓴다.

## 외부 이미지 생성으로 선화를 받아 올 때 (PNG 경로)

직접 SVG를 그리기 어려운 복잡한 장면(인물 여럿·상황극)은 이미지 모델에서 선화 PNG를 받아 `--annotation`(구역 JSON) 또는 `--auto`(전체 1구역)로 렌더한다. 프롬프트 골격(원 도구의 출도 규범을 우리 팔레트로 옮김):

> 극단적으로 미니멀한 손그림 스케치, 노션 스타일의 절제된 낙서 미학. **순백색 배경(#FFFFFF)**, 진한 잉크색 선(#141413), 채색은 앰버(#F59E0B)와 그린(#16A34A) 두 색만 소량 개념적 포인트로. 16:9, 주제는 [___]. 여백 넉넉, 대상들 사이 간격 확보(자동 분할용), **화면 하단 20%는 비워 둘 것**. 절대 금지: 글자·숫자·라벨·문자, 사실적 질감·사진감·3D·그림자·그라데이션, 복잡한 배경, 빨강·파랑·보라·기타 채도 높은 색.

받은 PNG는 ① 흰 배경인지 ② 4색 밖 색이 없는지 ③ 하단이 비었는지 눈으로 확인한 뒤 렌더한다(래퍼가 ③은 기계 검사). 구역 JSON 포맷은 `scripts/whiteboard/render_stream_whiteboard.py` 상단 docstring(원 도구 annotation: `elements[].region{x,y,width,height}` 원본 픽셀 정수 좌표 + `reveal.startMs/durationMs`).

## 손 자산 다시 굽기 (SVG 수정 시)

```bash
python - <<'EOF'
from playwright.sync_api import sync_playwright; from pathlib import Path
svg=Path("템플릿/whiteboard/hand-marker-amber.svg").resolve()
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":640,"height":900}); pg.goto(svg.as_uri()); pg.wait_for_timeout(200)
    pg.screenshot(path="템플릿/whiteboard/hand-marker-amber.png", omit_background=True); b.close()
EOF
```
펜촉이 알파 bbox의 **좌상단 모서리**에 오도록 유지한다(렌더러 tip_anchor=(0,0)). 이어서 top 버전: `cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)`로 `hand-marker-amber-top.png` 생성(펜촉 좌하단, 래퍼 앵커 0,1). 손 크기는 `--hand-height`(기본 400px).

## 렌더·조립 (요약 — 상세는 SKILL.md Step 6.6)

```bash
python scripts/render_whiteboard.py 04_영상소스/wb-scenes/wb1.svg --out 04_영상소스/wb1.mp4 --duration 12.4   # 12.4 = end-start
# 타임라인.json video_overlays에 { "n":1, "src":"04_영상소스/wb1.mp4", "style":"whiteboard", "start":…, "end":…, "label":"…" }
python scripts/encode_overlays.py 타임라인.json     # 배속 1.000× 확인
```
장면 SVG는 결과물 `04_영상소스/wb-scenes/`에 저장한다(재렌더·수정 가능하게). 렌더 시간은 1080p 기준 클립 길이의 약 9배(10초 클립 ≈ 1.5분).
