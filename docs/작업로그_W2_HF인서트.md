# 작업로그 W2 — HF 히어로 인서트 경로 구현 (2026-08-27)

설계 정본 = `docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md` §3-5 + §2(함정 목록).
근거 원문 = 세션 스크래치 `hf-review/DIGEST.md` Q2(컴포지션 계약)·Q2-B(Python 렌더 구동).
HF 클론 = `공유 프로젝트/hyperframes` HEAD **7170dc6** (= release/v0.8.16), 읽기 전용 참조.
버전 핀 = `hyperframes@0.8.16`. 커밋 없음(작업 지시).

---

## 1. 신규 파일

### 1-1. `템플릿/hf-insert/` (인서트 스캐폴드)

```
템플릿/hf-insert/
  index.html            루트 컴포지션 1920x1080·30fps·8s + 계약 체크리스트 주석
  hyperframes.json      registry 핀 + paths(blocks/components=parts, assets=assets)
  package.json          devDependencies.hyperframes = "0.8.16" (핀 명시)
  assets/gsap.min.js    HF 리포 skills/music-to-video/references/motion-primitives/assets/
                        에서 복사. GSAP 3.15.0, 헤더 배너(Standard License) 원문 보존
  assets/fonts/         Pretendard-{Regular,SemiBold,Bold,Black}.otf (C:\Windows\Fonts 복사)
  parts/                레지스트리 부품 5종 벤더 (아래 1-2)
```

`index.html` 상단 주석 = HF 컴포지션 계약 체크리스트(개선안 §2 + DIGEST Q2-A 요약):
루트 규약(`<template>` 금지·정적 치수/길이/fps·`data-end` 금지) / 클립·가시성
(**반개구간 `[start, start+duration)`이라 최종 상태는 duration보다 살짝 앞에 착지**,
`data-start` 없는 배경은 스스로 `position:absolute; inset:0`) / 타임라인
(**GSAP `<script>`가 컴포넌트 스크립트보다 먼저**, `gsap.timeline({paused:true})` 정확히 1개를
`window.__timelines["insert"]`에 등록, **진입은 `fromTo()`**, 초기 상태는 타임라인 밖 `gsap.set`,
CSS transition/@keyframes/rAF/`repeat:-1`/`Math.random` 금지) / 폰트(스택의 모든 이름에
`@font-face` 필요, 한글은 로컬 `url()`, 시스템 폴백은 `src: local()` 스텁) /
팔레트(흰 배경 `#F59E0B` 텍스트는 2.15:1로 check 실패 → 앰버는 그래픽 전용,
큰 텍스트 `#D97706`, 작은 텍스트 `#b06f07`) / 자막 안전영역(하단 21% = y>853px 텍스트 금지) /
검증 순서(lint error 0 → check → snapshot → render).

4색 토큰 CSS 변수는 `design.md`/`템플릿/presentation-16x9.html`과 동일값:
`#ffffff` / `#141413` / `#F59E0B`(--accent) / `#D97706`(--accent-text) / `#16a34a`(--green)
\+ 텍스트용 진앰버 `#b06f07`(--accent-ink). HF 부품이 읽는 호스트 토큰
(`--fg/--bg/--surface/--border/--muted/--brand/--accent-2/--font-display`)도 같은 값으로 매핑.

### 1-2. `템플릿/hf-insert/parts/` (부품 벤더 5종)

HF `registry/components/<name>/<name>.html` → `parts/<name>.html`.
각 파일 상단에 출처 주석(리포 URL · 커밋 7170dc6 · Apache-2.0 · 수정 내역) 삽입.

| 파일 | 원본 | 수정 |
|---|---|---|
| `count-up.html` | registry/components/count-up | 색 토큰 + GSAP 로컬 |
| `chart-story.html` | registry/components/chart-story | 색 토큰 + GSAP 로컬 |
| `titlecard-lockup.html` | registry/components/titlecard-lockup | 색 토큰 + GSAP 로컬 |
| `marker-highlight.html` | registry/components/marker-highlight | 색 토큰 + GSAP 로컬 |
| `grid-card-assemble.html` | registry/components/grid-card-assemble | 색 토큰 + GSAP 로컬 |

색 토큰 치환(다크 폴백 → 흰 배경 4색):
`#0b0c0e`/`#05070b`→`#ffffff` · `#f8fafc`→`#141413` · `#10161f`/`#141a23`→`#f7f6f4` ·
`#38404e`/`#475569`→`#d9d7d2` · `#94a3b8`→`#5e5d59` · `#71f5a7`→`#F59E0B` ·
`#61a8ff`→`#b06f07` · `#c5a3ff`→`#16a34a`.
추가로 CDN `gsap@3.14.2` `<script>` → 로컬 `assets/gsap.min.js`(오프라인 렌더·핀 버전).

### 1-3. `scripts/render_hf.py`

인자 `<타임라인.json> [--n N ...] [--skip-check] [--frames 1,4,7]`.

- `video_overlays`에서 `style=="hyperframes"` 항목만 대상, `--n`으로 선별 가능.
- 프로젝트 = `04_영상소스/hf/<n>/`, 산출 = `04_영상소스/ov<n>.mp4`(절대경로로 `--output`).
- 파이프라인: **lint(error 0 필수) → check → render → 길이 검증**.
  lint/check 실패 시 CLI 출력 원문을 stderr로 뱉고 중단(`--skip-check`로 check만 생략 가능).
  lint error가 1건이라도 있으면 check가 브라우저 감사를 통째로 건너뛰므로 lint를 먼저 강제한다.
- render 인자: `render . --output <abs> --fps 30 --quality high --workers 1 --format mp4`.
- **성공 판정 = CLI rc + 파일 존재 + size>0 + ffprobe 길이 > 0 + 길이 ≥ (end-start-0.5)**
  (CLI rc만 믿지 않는다 — DIGEST: 렌더 성공 후 예외는 실패로 집계되지 않음).
- ffprobe(PATH)로 코덱·해상도·fps·길이·오디오 트랙 유무를 읽어 결과 표 출력.
  ffprobe가 없으면 `imageio_ffmpeg` 번들 ffmpeg의 stderr 파싱으로 대체.
- `--frames`로 육안 검수용 PNG를 `04_영상소스/hf/frames/`에 추출(실패해도 판정에 영향 없음).
- 렌더 후 `o["src"] = "04_영상소스/ov<n>.mp4"` · `o["src_dur"]`를 타임라인에 원자적 쓰기
  → `validate_pipeline` D(원본 존재)·E(길이) 통과. `render_collage.py`와 동일 규약.

**절대 규칙 구현부**
- `hf_run()`이 매 호출마다 `HYPERFRAMES_SKIP_SKILLS=1` · `HYPERFRAMES_NO_TELEMETRY=1` 주입.
- `cwd = HF 프로젝트 폴더` 고정 (youtube-creator 루트에서 돌리면 CLI가 그 폴더 `.env`를
  자동 로드해 OPENAI 키가 프로세스에 실린다).
- `npx_cmd()`가 Windows에서 `npx.cmd`를 먼저 찾음(`shell=False`로는 확장자 없이 실행 불가).
- 버전 핀 문자열 `HF_PIN = "hyperframes@0.8.16"` 단일 상수.

---

## 2. 기존 파일 최소 diff

### 2-1. `scripts/encode_overlays.py` (본문 4줄 교체)

```diff
-        if o.get("style") == "collage":
-            # 콜라주 인서트는 render_collage.py가 ov<n>.mp4를 정확한 길이로 직접 렌더한다 —
+        if o.get("style") in ("collage", "hyperframes"):
+            # 자체 렌더 인서트는 각자의 렌더러가 ov<n>.mp4를 정확한 길이로 직접 만든다 —
             # 여기서 재인코딩하면 자기 자신을 입력으로 덮어쓰므로 반드시 건너뛴다.
-            print(f"  ov{o['n']}: collage — 건너뜀 (scripts/render_collage.py 담당)")
+            renderer = {"collage": "render_collage.py", "hyperframes": "render_hf.py"}[o["style"]]
+            print(f"  ov{o['n']}: {o['style']} — 건너뜀 (scripts/{renderer} 담당)")
             continue
```

기존 collage 건너뛰기와 동형. 그 외 로직 변경 없음.

### 2-2. `scripts/validate_pipeline.py` (검사 D에 3줄 + 상수 1 + 독스트링 1줄)

읽고 판정한 것:
- **검사 D**: `src` 실존·구간·겹침 검사는 collage 규약(`src`가 자기 자신 `ov<n>.mp4`)을 그대로
  따르므로 hyperframes도 **수정 없이 동등하게 동작**한다. 단 `style` 값에 화이트리스트가 없어
  오타(`"hyperframe"`)가 나면 `encode_overlays.py`가 실사 소스로 오인해 `ov<n>.mp4`를
  자기 자신으로 재인코딩한다 → 이 한 구멍만 막았다.
- **검사 E**: `ov<n>.mp4 ≥ 구간−0.5s`는 style 무관 → 수정 불필요.
- **검사 F**: 콜라주 오프닝 필수 + `COLLAGE_MAX=3`은 `style=="collage"`만 세므로 HF 인서트가
  콜라주 상한을 잠식하지 않는다(개선안 §3-5 "편당 0~2곳"은 별도 계층) → 수정 불필요.

```diff
+# 자체 렌더 인서트 style 화이트리스트 — collage=render_collage.py, hyperframes=render_hf.py.
+# style 없음 = 사용자 제공 실사/시연 소스(encode_overlays.py가 배속 인코딩).
+OVERLAY_STYLES = {"collage", "hyperframes"}
@@ 검사 D 루프 안
+        if o.get("style") is not None and o["style"] not in OVERLAY_STYLES:
+            errors.append(f"D: 오버레이 {n} style \"{o['style']}\" 미지원 "
+                          f"— 허용: {sorted(OVERLAY_STYLES)} 또는 style 없음(실사 소스)")
```

수정 금지 파일(`템플릿/presentation-16x9.html`·`design.md`·`CLAUDE.md`·`.claude/skills/**`·
`scripts/check_*.py`)은 건드리지 않았다.

---

## 3. 실측 (필수 게이트 — 전부 통과)

폴더: `결과물/2026-08-27_HF인서트-실측/`

```
타임라인.json                       샘플(duration 8.0, slides 1, video_overlays 1, waiver 1)
02_자막/자막.srt                     컷 1개
04_영상소스/hf/1/index.html          인서트 본문 (titlecard-lockup 개작 + count-up 조합)
04_영상소스/hf/1/{assets,hyperframes.json,package.json}   스캐폴드 복사본
04_영상소스/ov1.mp4                  렌더 산출물
04_영상소스/hf/frames/ov1_t{1p0,4p0,7p0}.png + ov1_lastframe.png
```

**연출**: 한국어 워드마크 "일잘러의 클로드 노하우"(Pretendard Black 128px, `#141413`) +
키커 "PART 2"(`#b06f07`) + 앰버 하이라인 드로우온(`#F59E0B`, 측정 dash) +
count-up frame-row "0 → 1,000시간"(`#D97706`) + 부제(`#5e5d59`).
리빌 스케줄 0.0 / 0.22 / 0.95 / 1.5~3.8(카운트) / 4.45(부제) → **후반 50%에도 리빌**,
프론트로딩 없음. 홀드는 진짜 정지(숨쉬기 루프 없음), `T_END = D - 0.1`에 최종 착지.
자막 안전영역: stage `padding-bottom: 227px`(=21%) → 최하단 텍스트(부제) 베이스라인 y≈730px.

### 3-1. 명령과 시간

| 단계 | 명령 | 결과 | 시간 |
|---|---|---|---|
| 스캐폴드 lint | `HYPERFRAMES_SKIP_SKILLS=1 HYPERFRAMES_NO_TELEMETRY=1 npx --yes hyperframes@0.8.16 lint .` (cwd=`템플릿/hf-insert`) | **0 errors, 0 warnings** (1차 실패 1건 수정 후 — 아래 5절) | 약 5s |
| 스캐폴드 check | 동 `check .` | **Check passed** — Lint 0/0, Runtime 0/0, Layout 0 issues / 9 samples, Motion 0/0, **Contrast 14/14 WCAG AA** | 약 11s |
| 실측 전체 | `python scripts/render_hf.py "결과물/2026-08-27_HF인서트-실측/타임라인.json" --frames 1,4,7` | lint rc=0 (4.6s) → check rc=0 (11.0s) → render rc=0 (17.9s) → 길이 검증 통과 | **전체 35.2s** |
| 파이프라인 검증 | `python scripts/validate_pipeline.py "…/타임라인.json"` | **[통과] exit 0** (B INFO 건너뜀, F waiver 경고, E 오디오 INFO 건너뜀, E ov1 길이 통과) | 즉시 |
| 회귀 — style 오타 | 위 타임라인의 style을 `"hyperframe"`으로 바꿔 실행 | **exit 2**, `✗ D: 오버레이 1 style "hyperframe" 미지원 — 허용: ['collage', 'hyperframes'] 또는 style 없음(실사 소스)` | 즉시 |
| 회귀 — 건너뛰기 | `python scripts/encode_overlays.py "…/타임라인.json"` | `ov1: hyperframes — 건너뜀 (scripts/render_hf.py 담당)`, exit 0 (재인코딩 없음) | 즉시 |

렌더 실패·check 실패로 인한 재시도는 **0회**(스캐폴드 lint 1건만 1회 수정). 3회 상한 미도달.

### 3-2. ffprobe 스펙 (`04_영상소스/ov1.mp4`)

```
codec_name=h264      width=1920   height=1080   pix_fmt=yuv420p
avg_frame_rate=30/1  duration=8.000000  nb_read_frames=240  size=466,720 bytes
audio stream = 없음 (무음 — 오디오는 CapCut 트랙 소유, 설계대로)
```
구간 8.00s ↔ 렌더 8.00s (오차 0). 프레임 수 240 = 30fps × 8s 정확 일치.

### 3-3. 프레임 (육안 검수용, 절대경로)

- `C:\Workspace-Hub\공유 프로젝트\youtube-creator\결과물\2026-08-27_HF인서트-실측\04_영상소스\hf\frames\ov1_t1p0.png`
  — 키커+워드마크 안착 완료, 하이라인 드로우 진행 중(약 45%). 카운트·부제 미등장.
- `…\ov1_t4p0.png` — 하이라인 완주, 카운트 "1,000시간" 도착 후 펄스 종료. 부제 미등장.
- `…\ov1_t7p0.png` — 부제까지 전부 등장, 정지 홀드. 최하단 텍스트 y≈730px < 853px(자막 안전영역 확보).
- `…\ov1_lastframe.png`(t≈7.96, 추가 검증) — 비백색 픽셀 5.25%, 최소 휘도 11
  → **마지막 프레임이 비지 않음**(반개구간 함정 회피 확인).

육안 판정: Pretendard 한글이 OTF 로컬 폰트로 정상 렌더(폴백 대체 없음), 앰버 하이라인·
카운트 색 모두 4색 규약대로, 레이아웃 겹침·잘림 없음.

---

## 4. 홈 스킬 폴더 오염 검사

검사 대상: `C:\Users\사용자2` 하위 모든 `.<name>/skills` 및 `.<name>/agents/skills`
(총 37개 dot 디렉터리 스캔 → 실존 스킬 폴더 5곳 = .agents/.claude/.codex/.commandcode/.factory, 엔트리 12건).

| 시점 | 결과 |
|---|---|
| 베이스라인(첫 `npx` 실행 전) | 엔트리 12건, `hyperframes*` **0건** |
| 스캐폴드 lint 직후 | 베이스라인과 **diff 없음** |
| 실측 lint+check+render 직후 | 베이스라인과 **diff 없음** |

`HYPERFRAMES_SKIP_SKILLS=1`이 실제로 작동함을 실측 확인. 삭제·원복 조치 필요 없음.
(`C:\Users\사용자2\.hyperframes\`에는 `config.json`·`install-state.json`·`lint-streaks.json`만
존재 — 스킬 복사 아님, 작업 전부터 있던 CLI 자체 상태 파일.)

---

## 5. 함정 조우 기록

1. **`duplicate_composition_id` (실제 조우, 스캐폴드 lint 1차 실패)**
   `<html data-composition-id="insert" data-composition-duration="8">`를 레지스트리 부품 스타일로
   따라 썼더니 루트 `<div>`와 id가 충돌해 lint error 1건.
   → 레지스트리 부품(서브컴포지션, `<template>` 배송)과 **standalone 프로젝트 루트는 규약이 다르다**.
   standalone에서는 `<html>`에 `data-composition-id`를 달지 않는다. `<html lang="ko">`로 되돌려 해소.
   (DIGEST Q2-A에 명시되지 않은 항목 — 이 로그가 근거다.)

2. **cwd `.env` 자동 로드 (사전 차단)**
   모든 CLI 호출의 `cwd`를 HF 프로젝트 폴더로 고정. youtube-creator 루트에서는 한 번도 실행 안 함.

3. **홈 스킬 무단 복사 (사전 차단, 실측으로 무해 확인)** — 4절.

4. **Windows `npx.cmd` (사전 차단)**
   `shutil.which("npx.cmd")` 우선. `shell=True`는 한글·공백 경로 인용 문제 때문에 쓰지 않음.

5. **반개구간 마지막 프레임 (사전 차단, 실측 확인)**
   `T_END = D - 0.1`에 no-op 착지를 심어 마지막 프레임이 비지 않게 함. `ov1_lastframe.png`로 검증.

6. **명암비 (사전 차단)**
   텍스트 앰버는 `#D97706`(큰 텍스트, 흰 배경 대비 3.19:1)·`#b06f07`(작은 텍스트) 만 사용.
   `#F59E0B`(2.15:1)는 하이라인 그래픽에만. check Contrast 14/14 통과.

7. **폰트 스택 lint (사전 차단)**
   `font-family` 스택의 비제네릭 이름 전부에 `@font-face` 배치.
   Pretendard 4굵기는 로컬 `url()`, `Noto Sans KR`·`JetBrains Mono`·`Fira Code`·`Consolas`는
   `src: local()` 스텁. generic(`system-ui`·`-apple-system`·`sans-serif`·`ui-monospace`·
   `monospace`)은 HF `GENERIC_FAMILIES` 면제 대상이라 스텁 불필요(코드 확인:
   `packages/lint/src/rules/fonts.ts:5-22`).

8. **미조우(해당 없음)**: `tl.seek(t)` 금지·`totalTime` 2호출은 제3경로(우리 캡처 루프 인라인)
   전용이라 이 HF 렌더 경로에는 적용되지 않는다. 서브컴포지션 `snapshot --at` 필수도
   이번 실측은 standalone 단일 파일이라 해당 없음.

---

## 6. 잔여·주의

- 실측 픽스처의 오버레이는 러닝타임 100%(8s 중 8s)라 개선안 §3-5의
  "오버레이 총량 ≤ 러닝타임 25%" 게이트를 만족하지 않는다. 단위 실측용 픽스처라 의도된 것이며,
  이 게이트는 `validate_pipeline.py`가 아니라 편성 단계 판단이다.
- `--skip-check`는 제공하되 기본 비활성. 명암비·레이아웃 감사를 건너뛰므로 상용 편에는 쓰지 않는다.
- ATTRIBUTIONS 등재(HyperFrames Apache-2.0 / GSAP Standard License / 부품 5종)는
  개선안 §4-6 항목으로 이번 작업 범위 밖 — 별도 처리 필요.
- 커밋하지 않았다(작업 지시).
