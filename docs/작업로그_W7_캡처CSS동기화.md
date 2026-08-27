# 작업로그 W7 — 캡처 CSS 애니메이션 가상시간 동기화 (v2.1)

- 날짜: 2026-08-27 · 담당: Fable 직접 (W6 "남은 일 1번" 해소 — 선택지 ⓑ 채택)
- 대상: `템플릿/presentation-16x9.html`, `템플릿/presentation-9x16.html`, `템플릿/shorts-remix-source.html` (capture_slides.py·capture_remix_source.py는 무변경)

## 1. 문제 (W6 실측)

가상시간 프레임 캡처(BeginFrame 제어 + `Emulation.setVirtualTimePolicy`)에서 **CSS
transition/animation은 가상시간이 아니라 벽시계로 돈다.** 캡처가 벽시계보다 빠르면 접히고
(wipe-reveal 0.95s→1프레임), 느리면 길어진다 — 즉 **머신 부하에 따라 비결정**이고 타이밍
자체가 틀린다(딜레이 무시·조기 시작).

비포 재현(템플릿 샘플 덱 20s, 이번 세션): 16.0s 슬라이드 전환+1s hbar-fill 전체 모션이
**3프레임**(굵은 임계) / 세밀 임계로 봐도 시작 16.1s·종료 16.77s로 타이밍 오류.

## 2. 수정 — `__capture.seek`에서 WAAPI 좌표 찍기

GSAP는 `driveTimeline`이 좌표를 직접 찍는데 CSS는 브라우저 시계 소유였다. 같은 원리로:

```js
const __animBirth = new WeakMap();
function syncCssAnimations(t) {
  document.getAnimations().forEach(a => {   // getAnimations()가 스타일 플러시 → 방금 태어난 트랜지션도 잡힘
    if (!__animBirth.has(a)) { __animBirth.set(a, entryTime); a.pause(); }
    a.currentTime = Math.max(0, t - __animBirth.get(a)) * 1000;   // delay 포함 타이밍이 currentTime에 들어있다
  });
}
```

- 계약: 이 시스템의 모든 CSS 모션은 슬라이드 activation(go)에서 발화(transition-delay 포함)
  → 애니메이션이 태어난 시점의 `entryTime`을 birth로 태깅, `currentTime = t − birth`.
  컷/크로스페이드의 퇴장 트랜지션도 같은 go에서 태어나므로 같은 기준이 맞다.
- 취소된 트랜지션(같은 속성 재발화 시)의 currentTime 세팅은 try/catch로 무시.
- **`[data-counter]`의 rAF 카운터도 캡처에서 비결정**(2회 캡처 픽셀 드리프트 실측, 8.93~9.7s
  도넛 카운터 구간) → 캡처 모드에서는 rAF 경로 차단, `syncCounters(slide, local)`가 같은 수치
  계약(+0.35s/9:16은 +0.30s, cubic-out)으로 시간 좌표 구동.
- 9:16(v1 구조)에는 `entryTime` 추적 + `CAPTURE` 플래그부터 이식.

## 3. 검증 (실측)

| 항목 | 비포 | 애프터 |
|---|---|---|
| 16:9 샘플 16s 전환+1s hbar | 3프레임(타이밍 오류) | **16.0~17.4s 연속 39프레임, 이징 좌표 일치**(17.0s에 cubic-out 85% 지점 750px 계산=실측) |
| 결정론(같은 입력 2회 캡처) | 11프레임 픽셀 드리프트 | **600프레임 픽셀차 0.0** |
| 9:16 스모크(8s, 청크 모드) | — | 4.8s 크로스페이드 16프레임 분산, **240프레임 픽셀차 0.0**, 중간 프레임 육안 정상 |
| 프레임 육안 | — | 도넛 카운터 중간값 58%·바 성장 중간·크로스페이드 중간 상태 정상 |

검증 자산: 스크래치패드 `csssync/` (before/after mp4·디버그 스크립트 — 세션 종료 시 소멸).

## 4. 영향 범위·주의

- **v2.1 이전 보일러플레이트로 만든 결과물 HTML은 여전히 접힌다** — 재사용 시 템플릿 최신
  `__capture` 블록으로 갱신할 것. (E2E 풀링013-v6은 전 모션 GSAP라 해당 없음.)
- 프리뷰(수동 넘김·오토플레이)는 무변경 — 동기화는 seek(캡처) 경로에서만 돈다.
- 교리 유지: 샷 시퀀스는 여전히 `data-tl` GSAP이 정본. 이 픽스는 CSS preset(등장·강조·차트
  선언 모션)의 신뢰를 복구한 것이지 GSAP 계층을 대체하지 않는다. design.md §4 🟡 항목 참조.
- shorts-remix-source.html도 같은 seek 캡처에 CSS 모션(0.4~0.5s pop/slam)이 있어 동일 이식.
  전체 파이프라인 대신 헤드리스 배선 검증으로 확인(seek 0.25s → 애니 7개 전부 paused·currentTime 250ms 일치).
