# Lottie 모션 씬 (영상 소스 슬라이드용)

AI가 1회 저작한 Lottie JSON을 슬라이드에 드롭해 재사용하는 결정론 모션 레이어.
씬 저작·수정의 원본 생성기는 `바탕화면\공유 프로젝트\lottie-시안\generate_scenes.py` (diffusionstudio/lottie 스킬 규약 기반).

## 씬 목록 (design.md 4색 원칙 · Pretendard 정합)

| 파일 | 용도 | 길이 | 비고 |
|---|---|---|---|
| `y1-title.json` | 타이틀 카드(서포트 라인 → 액티브 워드 마스크 리빌 + 앰버 마커 스윕) | 2.5s | 텍스트 교체는 JSON `t` 필드 수정 후 재생성 권장 |
| `y2-stat.json` | 히어로 스탯 카운트업(0→200% 베이크) + 캡션 | 3.2s | 수치 변경은 generate_scenes.py `build_y2` |
| `y3-diagram.json` | 3스텝 다이어그램(링 드로우 → 커넥터 트레이스 → 그린 체크) | 4.0s | |

## 사용법 (presentation-16x9.html)

1. 이 폴더(`lottie/`)를 결과물 `04_영상소스/` 폴더에 통째로 복사한다 (플레이어 `lottie.min.js` 포함).
2. 슬라이드 안에 스테이지를 배치한다:

```html
<section class="slide" data-slide>
  <div class="lottie-stage" data-lottie="lottie/y2-stat.json" style="--lw: 72%"></div>
</section>
```

- 슬라이드가 활성화될 때마다 **0프레임부터 재생** → SLIDE_TIMELINE 캡처와 결정론 동기.
- 루프가 필요하면 `data-lottie-loop="1"`.
- `file://` 등 fetch가 막히는 환경이면 JSON을 인라인하고 셀렉터로 참조:

```html
<script type="application/json" id="scene-y2">{ ...lottie json... }</script>
<div class="lottie-stage" data-lottie="#scene-y2"></div>
```

3. 폰트: 씬은 페이지에 로드된 Pretendard를 그대로 사용한다(템플릿 기본 로드). 별도 폰트 파일 불필요.

## 규칙

- 새 씬을 만들 때도 **design.md가 SSOT**: 흰 배경 + 잉크 + 앰버(주) + 그린(보조), 제목/숫자 = Pretendard 800/900, 숫자 자간 -0.05em.
- ⚠️ Lottie JSON에 빈 `"chars": []` 키를 넣으면 lottie-web이 글리프 모드로 빠져 텍스트가 전부 사라진다 — chars 키 자체를 두지 말 것.
- 검증: 헤드리스 Edge로 핵심 프레임(0 · 중간 · 마지막) 스크린샷 확인 후 사용.
