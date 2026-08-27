# 벤더 (외부 배포본 발췌)

이 폴더의 파일은 **외부 오픈소스/공식 배포본을 그대로 복사**한 것이다.
내용을 고치지 않는다. 특히 **파일 상단 배너 주석(라이선스 고지)은 절대 제거하지 않는다.**
minify·번들·주석 제거 도구를 이 폴더의 파일에 돌리지 않는다.

---

## gsap.min.js

| 항목 | 값 |
|---|---|
| 제품 | GSAP (GreenSock Animation Platform) |
| 버전 | 3.15.0 |
| 파일 | `gsap.min.js` (72,927 bytes) |
| sha256 | `92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb` |
| 가져온 곳 | `공유 프로젝트/hyperframes` (HyperFrames, Apache-2.0) 내 `skills/music-to-video/references/motion-primitives/assets/gsap.min.js` |
| 리포 | https://github.com/HeyGen-Official/HyperFrames |
| 커밋 | `7170dc63ae78dba6ddb211179b453bedf74932a6` (7170dc6) |
| 업스트림 원본 | https://gsap.com — 공식 배포본과 동일함을 확인한 발췌본 |
| 복사일 | 2026-08-27 |

### 라이선스

GSAP **Standard "No Charge" License** — https://gsap.com/standard-license
파일 상단 배너의 저작권·라이선스 고지(`@license Copyright 2026, GreenSock ...`)를
**제거·변형하지 않는 것이 이 라이선스의 조건**이다.
GSAP 유료 플러그인(Club GreenSock: SplitText, MorphSVG 등)은 이 라이선스 범위 밖이므로 벤더하지 않는다.

### 왜 로컬 벤더인가

- 영상 소스 캡처는 `file://` 오프라인 헤드리스에서 돈다. CDN 의존은 캡처 결정론을 깬다.
- 버전이 바뀌면 이징 곡선 미세값이 달라져 이미 구운 영상과 재현이 어긋난다 → **핀 고정**.
- HyperFrames의 `skills update` 같은 자동 갱신 경로는 쓰지 않는다(개조본을 덮어씀).

### 사용처

`템플릿/presentation-16x9.html` v2 (슬라이드 로컬 GSAP paused 타임라인, seek-safe 구동).
작업 결과물에서는 이 파일을 `04_영상소스/gsap.min.js`로 **복사**해 상대경로로 참조한다.
