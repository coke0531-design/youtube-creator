# youtube-creator

유튜브 **영상 조립 전용** 워크스페이스. 입력은 [확정 대본 + 나레이션 녹음본 (+선택: 시연 영상 소스)]이고, 본편 출력은 **[완성본 `완성본/final.mp4`]**(연출 위임형 v3.2 기본, 2026-09-30)이고, CapCut 드래프트는 요청 시·쇼츠 경로다. `.claude/skills/`의 프로젝트 스킬 2개(본편 youtube-editor, 쇼츠 youtube-short-generator)로 처리한다.
**주제 발굴·대본 초안은 이 워크스페이스 밖에서 온다** — 대본 초안은 content-oracle 워크스페이스가 만들고, 다듬기·녹음은 사용자가 한다. 여기서는 자막(SRT)·비트 표·연출 브리프·막 단위 필름 HTML·헤드리스 캡처(capture.mp4)·자막 번인 완성본까지 만든다(본편). 쇼츠는 슬라이드 HTML·CapCut 드래프트 경로 그대로다.

## 디자인 SSOT — design.md

- **모든 시각 산출물**(영상 소스 슬라이드, 인포그래픽, 썸네일)의 색상·폰트·모션은 프로젝트 루트의 **`design.md`가 단일 출처**다. 스킬 문서와 충돌하면 design.md가 우선.
- **4색 원칙 (영상 소스)**: 흰 배경 `#ffffff` + 잉크 `#141413` + 주 강조 앰버 `#F59E0B`(작은 텍스트는 `#D97706`) + 보조 강조 그린 `#16a34a`. 영상 소스에 검정/다크 배경 금지.
- 구 색상(`#00FF88`, `#FFD700`, 영상 소스 내 `#FBBF24`, 배경 `#000000`)이 보이면 design.md §6-8 매핑대로 교체한다.
- **본편 16:9 필름은 design.md §4-A 필름 연출 규범 v3.2가 우선**한다(종이 미색 `#F7F3EA` 무대 + 카드 안 흰 P2, 카메라 규칙 4조, 실사는 카드 안 창, 선은 곧게). 아래 4색 흰 배경·교리 4법칙·벡터 예약표는 슬라이드 경로(쇼츠·레거시) 규범이다.
- **모션 규범**도 design.md가 SSOT다 — §4의 **모션 교리 4법칙**(부드러움>튐 / 리빌은 나레이션 큐·후반 50% / 나쁜 모션보다 정지+루트 5종 / 컷은 속도 일치)과 **벡터 예약표**가 렉시콘 preset 선택보다 위에 있다.
- `docs/편입안_2026-09-30_연출위임형-v3.2.md` = **연출 위임형 v3.2 정본 편입의 결정 기록**(본편 = DIRECTION·킷·막 필름·완성본). 상세 규격은 `.claude/skills/youtube-editor/SKILL.md`·`연출-브리프.md`·`스타일팩.md`·`장치사전.md`·`킷-규격.md`.
- `docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md` = 이전 개편(브리프·스토리보드·모션 v2·게이트 2종)의 결정 기록. 스토리보드 규격은 `docs/legacy/스토리보드-규격.md`로 옮겼다(슬라이드 경로 한정).

## 스킬 파이프라인

| 단계 | 스킬 | 산출물 |
|------|------|--------|
| 0. 의도·연출 계층 | `youtube-editor` (Step 0.5·4) | **`01_대본/BRIEF.md`**(메시지·타깃·목표·앵글·톤·금지) → `03_자막/beats.json`(`scripts/film/segment.py --beats-only`) → **`04_영상소스/DIRECTION.md`**(연출 브리프 6블록 + 막 표 + 핸드오프 표 + 실물 소스 표). 대본→필름 직행 금지. 규격 = `.claude/skills/youtube-editor/연출-브리프.md` |
| 1. 본편 (v3.2) | `youtube-editor` | 자막 SRT + 킷(`kit.js` = `템플릿/film/kit.js` 사본, 수정 금지 + `kit_ext.js`·`KIT.md`) + 막별 `BEATS_<막>.md`·`film_<막>.html`(P1 종이 무대 + 카드 안 P2, 사용자 제공 `영상 소스/`는 카드 안 실사 창) + `capture.mp4`(막 캡처 → `join_acts.py`) + **`완성본/final.mp4`**(`scripts/film/mux.py`). 콜라주·HF·CapCut 드래프트는 선택·레거시. 마무리로 대본 끝에 '영상 요약'(Step 9)과 '썸네일 생성 프롬프트'(Step 9-2) 섹션 append |
| 2. 쇼츠 소스 | `youtube-short-generator` | 9:16 슬라이드 HTML + 쇼츠 SRT + 컷지시서/타임라인.json + capture.mp4 + CapCut 드래프트 |
| 3. 쇼츠 리믹스 | `shorts-remix` | 완성 롱폼 mp4(영상 모음 등)를 입력으로 검은띠+헤드카피 9:16 완성형 쇼츠 mp4 (`scripts/remix_shorts.py` 렌더, 자막 번인). ⚠️ STT는 반드시 원본 mp4 추출 오디오 기준(타임베이스 계약), 검은띠 `#0A0A0A`는 design.md 흰 배경 규정의 예외(리믹스 프레임 한정, 2026-08-13 신설) |

**입력 계약**: 대본(`01_대본/script.md`, 파트 문법 = `## 썸네일`/`## 본문` — check_script.py가 게이트) + 녹음본(`02_음성/`)은 외부에서 온다(대본 초안 = content-oracle, 다듬기·녹음 = 사용자). 제목·썸네일 카피·업로드도 사용자 몫이며, 이 워크스페이스는 그 재료(영상 요약·썸네일 배경 프롬프트)까지만 만든다. **입력이 대본+녹음뿐이라 의도가 비는 문제는 여기서 `BRIEF.md`(Step 0.5, 메시지·타깃·목표)와 `DIRECTION.md`(Step 4, "어떻게 보여줄까")가 메운다** — 둘 다 한 번 쓰면 그 작업의 진실(이후 단계는 다시 묻지 않는다).

단계를 건너뛴 요청도 가능하다 (예: 본편 없이 기존 capture로 쇼츠만). 여러 단계를 한 번에 요청받으면 위 순서로 진행한다.

## 싱크 계약 (음성·자막·영상 3자료 동기화)

최종 영상은 [① 음성 녹음 ② 타임스탬프 자막(STT) ③ 영상 소스] 3자료를 합쳐 완성한다 — 본편은 `scripts/film/mux.py`가 완성본으로(youtube-editor Step 8), 쇼츠·레거시는 CapCut 드래프트(**pycapcut 로컬 드래프트 생성**, `scripts/assemble_capcut.py`)로. 그래서:

1. **녹음이 먼저다** — 대본 확정 → 사용자 녹음(`02_음성/`) → **무음 컷**(`scripts/trim_silence.py` — 무음 ≥1s를 양끝 0.3s만 남기고 0.6s로 압축, 비파괴 `.trim.m4a`) → Whisper STT → 자막 → 영상 소스 순. 슬라이드 타이밍은 대본 추정이 아니라 **실제 발화(transcript.json)** 기준으로 확정한다. 무음 컷이 STT 앞에 있으므로 하류 전체가 트림본 타임베이스에서 파생된다 — 동기화 후처리 불필요.
2. **동일 타임베이스** — 3자료는 t=0(음성 시작, 쇼츠는 첫 컷 시작)을 공유한다. 본편 필름은 `seek(t)` 순수 함수를 `scripts/film/capture.py`가 프레임마다 찍어 프레임 0 = 막 시작 초가 보장된다(2-1). 슬라이드 경로의 영상 소스에는 transcript 기준 `SLIDE_TIMELINE`을 임베드해 **캡처 모드**(`?capture=1`, `scripts/capture_slides.py` 헤드리스 통녹화)로 캡처하면 자막·음성과 싱크가 일치한다 (수동 폴백: A → SPACE 화면 녹화).
2-1. **연출은 DIRECTION·비트 표가 상류다(본편 v3.2)** — `DIRECTION.md`(Step 4)의 막 표·핸드오프 표와 막별 `BEATS_<막>.md`가 필름의 상류이고, 비트 시각은 전부 `transcript.json` 실측(`beats.json`)이다. 필름은 순수 `seek(t)`(막 기준 t + `FILM.offset` = 원본 초)로 그리고 `scripts/film/capture.py --verify-seek`가 결정론을 검사한다. 막 N 끝 프레임 = 막 N+1 첫 프레임 = `KIT.HANDOFF`(이음매는 `join_acts.py`가 픽셀 검사). 규범 = design.md §4-A. (슬라이드 경로: `STORYBOARD.md`(Step 4)의 프레임 블록이 편집지시서 연출 컬럼·타임라인.json의 상류이고, 샷 시퀀스 시각은 전부 `transcript.json` 단어 타임스탬프 실측이다(추정 금지). 샷 시퀀스가 있는 슬라이드는 `data-tl` + 로컬 GSAP paused 타임라인(`벤더/gsap.min.js` 동반 복사)을 갖고, `__capture.seek(t)`가 `local = t - slide.start`로 `totalTime` 2호출로 구동한다(`tl.seek()` 금지). 모션 규범 = design.md §4 **교리 4법칙·벡터 예약표**.)
3. **기계용 동기화 데이터(슬라이드 경로)** — 편집지시서/컷지시서(사람용)와 함께 `타임라인.json`(슬라이드 타임코드 + 쇼츠 audio_cuts + 선택 `video_overlays`)을 항상 생성한다. SRT·SLIDE_TIMELINE·타임라인.json의 타임코드는 값이 일치해야 하며(불일치 = 싱크 깨짐), 이 일치는 **`scripts/validate_pipeline.py`가 기계 검증**한다 — 캡처·조립 스크립트가 시작 시 자동 실행하고 위반이면 중단(fail-loud).
4. **실사 소스 = 카드 안 창(본편 v3.2, 2026-09-30)** — 사용자 제공 시연/실사 영상(`영상 소스/N.mp4`)은 transcript 실측으로 대사 구간을 확정하고, 30fps JPEG 시퀀스(`04_영상소스/실사프레임/`) + `live.js`로 **필름이 카드 안 고정 창에 직접 그린다**(둥근 모서리 r32·잉크 테두리 4px, 줌은 창 안 그림에만, 길이는 재생 속도 0.6~1.5로 맞춤·보간 금지, `<video>` 금지). 오디오·자막 타임코드는 불변. 규칙 = youtube-editor SKILL §4-4 + design.md §4-A. (레거시 슬라이드 경로의 `encode_overlays.py` 배속 오버레이 트랙은 요청 시만.)
5. **콜라주 인서트 — 선택(2026-09-29 오너 결정으로 필수에서 격하)**: 본편 기본은 **첫 프레임 = 썸네일**(필름 t=0에 캐릭터·핵심 요소가 이미 있다)이고, 콜라주는 요청이 있을 때만 슬라이드 경로로 얹는다. 이하는 콜라주를 쓸 때의 규칙(구 2026-08-18 오프닝 필수 규칙): 편당 콜라주 = 오프닝 1개(필수, `start: 0.0`) + 본문 1~2개(실패담·나열/비교·수치 대목), 합계 ≤ 러닝타임 25%. 대본 `04_영상소스/collage/cg<n>.json` → `scripts/render_collage.py`(엔진 = `공유 프로젝트/cutout-collage-lab`) → `ov<n>.mp4`를 오버레이 트랙에 `style: "collage"`로 얹는다. 오프닝 부재·4개 이상·25% 초과는 `render_collage.py`·`validate_pipeline.py`(검사 F)가 기계로 막는다. 규칙 = youtube-editor Step 6.7 + design.md §4.
6. ⏸ **화이트보드 드로잉 장면 — 비활성(2026-08-16 오너 결정, 제안·사용 금지; 켜는 법 = `scripts/whiteboard/README.md`)**. 켜져 있을 때의 규칙: 수치 없는 스토리·비유 대목에 한해 `scripts/render_whiteboard.py`로 4색 선화가 그려지는 클립(`wb<n>.mp4`)을 만들어 같은 오버레이 트랙에 `style: "whiteboard"`로 얹는다(자막은 잉크색 유지). 🔒 영상당 1~3장면. 규칙 = design.md §4 렉시콘 + `템플릿/whiteboard/README.md`, 롤백 = `scripts/whiteboard/README.md`.

7. **본편 게이트(v3.2)** — `scripts/film/kit_check.py`(킷 단계: 작업 폴더 `kit.js` md5 = 정본 `템플릿/film/kit.js`, 필름의 캐릭터·STAR 재정의·팔레트 밖 hex 차단, `--gallery` golden 픽셀 비교) · `scripts/film/cam_check.py`(막 필름: 카메라 3초 유지·작은 밀기·6초 왕복·이동당 4초) · `capture.py --verify-seek`(결정론) · `join_acts.py`(이음매 mean ≤ 2·max ≤ 80) · `scripts/film/still_ratio.py --holds`(6초 창 raw 75% 초과 0, 홀드 제외 평균 ≤ 45% 목표) · `split_captions.py --check`(16자). **슬라이드 경로 연출 게이트 2종(2026-08-27 신설)** — `scripts/check_storyboard.py`(**Step 4 직후**: route 누락·샷 창 미충족·리빌 시각이 단어 타임스탬프 밖·프론트로딩·전환 유형 4종 이상 차단)와 `scripts/check_motion.py`(**Step 7 캡처 직후**: capture.mp4 프레임 차분으로 "80~90% 정지 화면" 회귀·컷 경계 죽은 박자 차단). 선택 감사기 = `scripts/hf_audit.py`(레이아웃 겹침·잘림·명암비). **기존 게이트는 그대로 유지**한다 — `validate_pipeline.py`·`check_caption_safe.py`(자막 안전영역 21vh)·`split_captions.py`(16자). HF 히어로 인서트(`style: "hyperframes"`, `scripts/render_hf.py`, 편당 0~2개)는 콜라주와 **합산해** 오버레이 총량 ≤ 러닝타임 25% 게이트를 공유한다.

## 결과물 폴더 규약 (모든 산출물의 저장 위치)

작업(영상 1편) 단위로 `결과물/` 아래에 날짜 폴더를 만들고, 모든 산출물을 거기에 저장한다:

```
결과물/
└── YYYY-MM-DD_<주제-슬러그>/
    ├── 작업정보.md          ← 필수: 날짜/주제/타겟/상태/산출물 목록/메모 (산출물 생길 때마다 갱신)
    ├── 편집지시서.md        ← 본편 슬라이드 ↔ 오디오 타임코드 매핑 (사람용 — CapCut 가이드)
    ├── 타임라인.json        ← 같은 데이터의 기계용 (pyCapCut 드래프트 자동 조립 입력)
    ├── 01_대본/             ← BRIEF.md(기획 브리프 — Step 0.5 신설) + script.md(나레이션 정본 — '썸네일' 파트가 있으면 '본문' 파트만 녹음/STT 대상) + 기획메모.md — 외부(content-oracle·사용자)에서 받아 복사해 온다
    ├── 02_음성/             ← 녹음 원본 + .trim.m4a(무음 컷 정본 — STT·조립은 트림본 사용, 원본 보존)
    ├── 03_자막/             ← full.srt + transcript.json (Whisper 원본) + beats.json (비트 표)
    ├── 04_영상소스/         ← 본편 v3.2: DIRECTION.md + kit.js(정본 사본)·kit_ext.js·KIT.md·live.js + BEATS_<막>.md·film_<막>.html + 실사프레임/ + capture_<막>.mp4·capture.mp4·capture.holds.json·still.json·seams.json + 시트 jpg (레거시: STORYBOARD.md·presentation.html·ov<n>.mp4)
    ├── 완성본/              ← final.mp4 (본편 기본 산출물 — scripts/film/mux.py)
    ├── 영상 소스/           ← (오버레이 모드) 사용자 제공 시연/실사 영상 원본
    ├── 캡컷 조립 재료/      ← CapCut 조립·검수에 필요한 파일만 모음 (Step 8.5 하드링크 — 사람용, 이 폴더 하나만 보면 됨)
    └── 05_쇼츠/short-NN/    ← 쇼츠별: source.html + short-NN.srt + 컷지시서.md + 타임라인.json
```

- 새 작업 시작 시 이 구조를 먼저 생성하고 `작업정보.md`를 쓴다. 기존 작업 이어서 할 때는 해당 폴더를 찾아 이어서 작업한다.
- 같은 날짜·주제 폴더가 이미 있으면 새로 만들지 말고 그 폴더에 이어서 저장한다.
- **산출 위치는 결과물/ 고정 (2026-07-15 사용자 결정)**: 사용자가 기초 자료(`대본/`+`녹음본/`+선택 `영상 소스/`)가 든 외부 폴더를 지정해도 그 자리에 산출하지 않는다 — 새 `결과물/` 작업 폴더에 기초 자료를 복사해 온 뒤 모든 산출물을 그 안에 만든다. 외부 원본은 읽기 전용(대본 끝 섹션 append도 작업 폴더 사본에만).

## 전역 규칙 (모든 스킬 공통)

1. **본편은 완성본이 기본(2026-09-30 오너 결정, v3.2)**: youtube-editor는 막 필름 캡처를 `scripts/film/mux.py`로 합성해 `완성본/final.mp4`(자막 번인·loudnorm·끝에서 1.15배속, 길이 = 오디오 ÷ 1.15)를 만든다 — 오너 판정 방식이 완성본 시청이기 때문. CapCut 드래프트는 명시 요청 시에만(레거시 경로). **쇼츠·레거시 슬라이드 경로는 아래 종전 규칙 그대로**: 기본 경로는 캡컷 검수다 — 완성본 영상의 합성·내보내기는 하지 않고 CapCut에서 사용자가 검수 후 직접 한다. 단 **영상 소스 캡처**(`scripts/capture_slides.py` 헤드리스 통녹화 → capture.mp4)와 **CapCut 드래프트 조립**(`scripts/assemble_capcut.py`)은 AI가 수행한다. CapCut 조합 상태와 수동 폴백은 편집지시서로 안내한다. **예외(2026-07-23 사용자 결정)**: 사용자가 "완성본으로 뽑아줘" 등 검수 생략을 명시하면 `scripts/render_final.py`(기본 ffmpeg 엔진, 본편 16:9 한정)로 완성본을 합성할 수 있다 — 사용법·벤치마크는 `리모션/README.md` 참조. 명시 요청 없이 완성본을 만들지는 않는다.
2. **배속은 완성본 합성 끝에서 한 번만(2026-10-06 오너 결정)**: 본편 완성본은 `scripts/film/mux.py --speed`(기본 1.15, 음높이 유지)로 1.15배속이 걸려 나온다. 그 앞 단계(음성·자막·비트·필름·캡처)에서는 배속 변환을 하지 않고, 완성본 시각이 필요한 곳(챕터 등)만 원본 시각 ÷ 1.15로 환산한다. 중간 단계에서 허용되는 유일한 오디오 편집은 **무음 컷**(youtube-editor Step 1.5, `scripts/trim_silence.py`)이며 반드시 STT **이전**에만 수행한다 — 컷 이후의 트림본(`.trim.m4a`)이 모든 타임코드(자막, 편집지시서, 타임스탬프)의 기준이다.
2-1. **자막 한 컷 ≤16자**: 자막(SRT)은 한 컷에 **최대 16자(공백 포함)**만 노출한다. AI는 자연스러운 구로 묶기만 하고, 16자 분할은 `scripts/split_captions.py`가 결정론적으로 강제한다(프롬프트 아님). `assemble_capcut.py`가 임포트 직전 한 번 더 멱등 강제 — 최종 드래프트는 항상 ≤16자. 분할 컷은 원래 자막 구간 안에 머물러 싱크 불변. 규격: youtube-editor `자막-안전영역.md`.
3. **한글 우선**: 슬라이드/인포그래픽 내 모든 텍스트는 한글. 고유명사(GPT, Claude, Cursor 등)만 영어 허용.
4. **인포그래픽 퍼스트**: 슬라이드는 텍스트만으로 구성하지 않는다. 항상 SVG/차트/도형이 주인공.
5. **레퍼런스 자동 참조**: 슬라이드·썸네일 프롬프트 작업 시 `레퍼런스/`(로고·스티커·썸네일 스타일)를 **묻지 말고 자동 스캔**해서 활용한다 (예: Step 9-2의 claude.png 모양 참고).
6. **API 토큰**: `.env`에서 읽는다 — `OPENAI_API_KEY`(Whisper). 토큰 값을 출력하거나 커밋하지 않는다.

## 환경 전제

- Windows 환경에서는 `python3` 명령이 없을 수 있다 — `python` 또는 `py -3`로 폴백한다.
- 슬라이드 HTML은 브라우저에서 열어 확인한다 (Remotion/Node 빌드 불필요). `리모션/`은 렌더러 전환 평가용 샌드박스(2026-06-11, 전환 보류 결론)로 현행 파이프라인 소속이 아니다 — 결론·재검토 트리거는 `리모션/README.md` 참조.
- 본편 필름 도구(v3.2): `템플릿/film/`(공용 킷 `kit.js` — 수정 금지 SSOT·실사 로더 `live.js`·막 필름 뼈대 `film_act_template.html`·`kit_gallery.html`+golden) · `scripts/film/`(비트 표·구간 발췌 `segment.py`·결정론 캡처 `capture.py`(`--verify-seek`·`--workers`)·비트 시트 `beatsheet.py`·정지 비율 `still_ratio.py`(`--holds`)·완성본 합성 `mux.py`·막 잇기+이음매 검사 `join_acts.py`·카메라 검사 `cam_check.py`·킷 일관성 검사 `kit_check.py`, 설명 = `scripts/film/README.md`).
- 공용 에셋: `레퍼런스/로고/`(자주 쓰는 제품 로고), `레퍼런스/교정사전.json`(Whisper 오인식 영구 교정 사전 — 문맥 무관 항목만 등재), `템플릿/`(슬라이드 보일러플레이트), `scripts/`(캡처·드래프트 조립·자막 16자 분할 `split_captions.py`·오인식 교정 `apply_corrections.py`·무음 컷 `trim_silence.py`·오버레이 배속 인코딩 `encode_overlays.py`·조립 재료 스테이징 `stage_capcut_kit.py`·싱크 계약 검증 `validate_pipeline.py`·자막 안전 영역 검사 `check_caption_safe.py`(본편 캡처 전 자동 게이트)·대본 구조/사실 게이트 `check_script.py`·레퍼런스 모션 문법 분석 `analyze_motion.py`(선택)·콜라주 인서트 렌더 `render_collage.py`(오프닝 필수, 엔진 = 별도 레포 cutout-collage-lab)·화이트보드 드로잉 렌더 `render_whiteboard.py`(선택, 엔진 `scripts/whiteboard/` vendored MIT)·**스토리보드 게이트 `check_storyboard.py`**·**모션 게이트 `check_motion.py`**·HF 감사기 `hf_audit.py`(선택)·HF 히어로 인서트 렌더 `render_hf.py`(선택)·환경 진단 `doctor.py`·구 단위 전사 읽기 뷰 `pack_transcript.py`(Step 2 직후 `03_자막/transcript_packed.md` — 무음 갭=쇼츠 컷 후보 표시, transcript.json 불변)·구간 시각 드릴다운 `timeline_view.py`(선택 — [start,end] 필름스트립+프레임 차분+파형+단어 큐+갭 PNG와 같은 이름 JSON. check_motion WARN 원인 분류·스토리보드 Scene 큐 검수용, 상시 스캔 도구 아님)). 모션 v2용 로컬 GSAP = `벤더/gsap.min.js`.
- pip 의존성은 `requirements.txt`의 검증 버전으로 고정한다. 새 기기·원인 불명 실패 시 `python scripts/doctor.py`부터.
- CapCut 자동화 의존성(pip): `pycapcut`, `playwright`(+`python -m playwright install chromium`), `imageio-ffmpeg`. 드래프트 조립 시 CapCut은 닫혀 있어야 하고, 국제판 비암호화 버전(9.x, 2026-05 확인)을 유지한다 — **CapCut 자동 업데이트 OFF**.

## 스킬 수정 시

- 스킬 간 규칙이 어긋나지 않게 유지한다 (특히 색상 규칙은 design.md만 고친다).
- 규칙 경고문과 코드 예시가 모순되면 안 된다 — 예시가 경고를 무력화한다. 규칙을 바꾸면 해당 스킬의 모든 코드 예시도 같이 바꾼다.
