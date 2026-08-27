# youtube-creator

유튜브 **영상 조립 전용** 워크스페이스. 입력은 [확정 대본 + 나레이션 녹음본 (+선택: 시연 영상 소스)]이고, 출력은 [CapCut 조립 드래프트] 또는 (명시 요청 시) [완성본 final.mp4]다. `.claude/skills/`의 프로젝트 스킬 2개(본편 youtube-editor, 쇼츠 youtube-short-generator)로 처리한다.
**주제 발굴·대본 초안은 이 워크스페이스 밖에서 온다** — 대본 초안은 content-oracle 워크스페이스가 만들고, 다듬기·녹음은 사용자가 한다. 여기서는 자막(SRT)·슬라이드(HTML)·헤드리스 캡처(capture.mp4)·CapCut 드래프트 자동 조립까지 만든다. 최종 영상 합성(export)은 기본적으로 하지 않는다(전역 규칙 1의 예외만).

## 디자인 SSOT — design.md

- **모든 시각 산출물**(영상 소스 슬라이드, 인포그래픽, 썸네일)의 색상·폰트·모션은 프로젝트 루트의 **`design.md`가 단일 출처**다. 스킬 문서와 충돌하면 design.md가 우선.
- **4색 원칙 (영상 소스)**: 흰 배경 `#ffffff` + 잉크 `#141413` + 주 강조 앰버 `#F59E0B`(작은 텍스트는 `#D97706`) + 보조 강조 그린 `#16a34a`. 영상 소스에 검정/다크 배경 금지.
- 구 색상(`#00FF88`, `#FFD700`, 영상 소스 내 `#FBBF24`, 배경 `#000000`)이 보이면 design.md §6-8 매핑대로 교체한다.
- **모션 규범**도 design.md가 SSOT다 — §4의 **모션 교리 4법칙**(부드러움>튐 / 리빌은 나레이션 큐·후반 50% / 나쁜 모션보다 정지+루트 5종 / 컷은 속도 일치)과 **벡터 예약표**가 렉시콘 preset 선택보다 위에 있다.
- `docs/개선안_2026-08-27_브리프-스토리보드-모션v2.md` = **이번 개편(브리프·스토리보드·모션 v2·게이트 2종)의 결정 기록**. 상세 규격은 `.claude/skills/youtube-editor/SKILL.md`·`스토리보드-규격.md` 참조.

## 스킬 파이프라인

| 단계 | 스킬 | 산출물 |
|------|------|--------|
| 0. 의도·연출 계층 | `youtube-editor` (Step 0.5·4) | **`01_대본/BRIEF.md`**(메시지·타깃·목표·앵글·톤·금지 + 비주얼 텔링 피치 3~5안) → **`04_영상소스/STORYBOARD.md`**(프레임별 type·persuasion·beat·blueprint·route·vec·focal + Scene 줄). 대본→슬라이드 직행 금지. 규격 = `.claude/skills/youtube-editor/스토리보드-규격.md` |
| 1. 본편 소스 | `youtube-editor` | 16:9 슬라이드 HTML + 자막 SRT + 편집지시서/타임라인.json + capture.mp4 + **콜라주 인서트 ov<n>.mp4(오프닝 t=0 필수 + 본문 1~2개, Step 6.7)** + CapCut 드래프트 4트랙 (+ 사용자 제공 `영상 소스/` 있으면 실사 오버레이 배속 인코딩). 마무리로 대본 끝에 '영상 요약'(Step 9)과 '썸네일 생성 프롬프트'(Step 9-2) 섹션 append |
| 2. 쇼츠 소스 | `youtube-short-generator` | 9:16 슬라이드 HTML + 쇼츠 SRT + 컷지시서/타임라인.json + capture.mp4 + CapCut 드래프트 |
| 3. 쇼츠 리믹스 | `shorts-remix` | 완성 롱폼 mp4(영상 모음 등)를 입력으로 검은띠+헤드카피 9:16 완성형 쇼츠 mp4 (`scripts/remix_shorts.py` 렌더, 자막 번인). ⚠️ STT는 반드시 원본 mp4 추출 오디오 기준(타임베이스 계약), 검은띠 `#0A0A0A`는 design.md 흰 배경 규정의 예외(리믹스 프레임 한정, 2026-08-13 신설) |

**입력 계약**: 대본(`01_대본/script.md`, 파트 문법 = `## 썸네일`/`## 본문` — check_script.py가 게이트) + 녹음본(`02_음성/`)은 외부에서 온다(대본 초안 = content-oracle, 다듬기·녹음 = 사용자). 제목·썸네일 카피·업로드도 사용자 몫이며, 이 워크스페이스는 그 재료(영상 요약·썸네일 배경 프롬프트)까지만 만든다. **입력이 대본+녹음뿐이라 의도가 비는 문제는 여기서 `BRIEF.md`(Step 0.5)가 메운다** — 브리프는 "무엇을 말할까"가 아니라 **"어떻게 보여줄까"**만 다루며, 한 번 쓰면 그 작업의 진실(이후 단계는 다시 묻지 않는다).

단계를 건너뛴 요청도 가능하다 (예: 본편 없이 기존 capture로 쇼츠만). 여러 단계를 한 번에 요청받으면 위 순서로 진행한다.

## 싱크 계약 (음성·자막·영상 3자료 동기화)

최종 영상은 [① 음성 녹음 ② 타임스탬프 자막(STT) ③ 영상 소스] 3자료를 CapCut에서 합쳐 완성한다. CapCut은 공식 API가 없으므로 자동 조립은 **pycapcut 로컬 드래프트 생성**(`scripts/assemble_capcut.py`, youtube-editor 스킬 Step 8) 방식을 쓴다. 그래서:

1. **녹음이 먼저다** — 대본 확정 → 사용자 녹음(`02_음성/`) → **무음 컷**(`scripts/trim_silence.py` — 무음 ≥1s를 양끝 0.3s만 남기고 0.6s로 압축, 비파괴 `.trim.m4a`) → Whisper STT → 자막 → 영상 소스 순. 슬라이드 타이밍은 대본 추정이 아니라 **실제 발화(transcript.json)** 기준으로 확정한다. 무음 컷이 STT 앞에 있으므로 하류 전체가 트림본 타임베이스에서 파생된다 — 동기화 후처리 불필요.
2. **동일 타임베이스** — 3자료는 t=0(음성 시작, 쇼츠는 첫 컷 시작)을 공유한다. 영상 소스에는 transcript 기준 `SLIDE_TIMELINE`을 임베드해 **캡처 모드**(`?capture=1`, `scripts/capture_slides.py` 헤드리스 통녹화)로 캡처하면 자막·음성과 싱크가 일치한다 (수동 폴백: A → SPACE 화면 녹화).
2-1. **연출은 스토리보드가 상류다** — `STORYBOARD.md`(Step 4)의 프레임 블록이 편집지시서 연출 컬럼·타임라인.json의 상류이고, 샷 시퀀스 시각은 전부 `transcript.json` 단어 타임스탬프 실측이다(추정 금지). 샷 시퀀스가 있는 슬라이드는 `data-tl` + 로컬 GSAP paused 타임라인(`벤더/gsap.min.js` 동반 복사)을 갖고, `__capture.seek(t)`가 `local = t - slide.start`로 `totalTime` 2호출로 구동한다(`tl.seek()` 금지). 모션 규범 = design.md §4 **교리 4법칙·벡터 예약표**.
3. **기계용 동기화 데이터** — 편집지시서/컷지시서(사람용)와 함께 `타임라인.json`(슬라이드 타임코드 + 쇼츠 audio_cuts + 선택 `video_overlays`)을 항상 생성한다. SRT·SLIDE_TIMELINE·타임라인.json의 타임코드는 값이 일치해야 하며(불일치 = 싱크 깨짐), 이 일치는 **`scripts/validate_pipeline.py`가 기계 검증**한다 — 캡처·조립 스크립트가 시작 시 자동 실행하고 위반이면 중단(fail-loud).
4. **영상 소스 오버레이(선택)** — 사용자 제공 시연/실사 영상(`영상 소스/N.mp4`)은 transcript 실측으로 구간을 확정하고(`video_overlays`), `scripts/encode_overlays.py`가 컷 없이 **배속만**으로 구간 길이에 맞춰 `ov<n>.mp4`를 만든 뒤, 조립(assemble_capcut.py)이 슬라이드 위 별도 트랙에 얹는다(겹치는 자막은 흰색). 오디오·자막 타임코드는 불변.
5. **콜라주 인서트 — 오프닝 필수(2026-08-18 오너 결정) + 편당 2~3개**: 본편의 **가장 첫 장면(t=0)은 반드시 페이퍼 컷아웃 콜라주 인서트**로 연다(시청 시작 시 후킹·몰입 — 흰 슬라이드 타이틀로 시작하지 않는다). 편당 콜라주 = 오프닝 1개(필수, `start: 0.0`) + 본문 1~2개(실패담·나열/비교·수치 대목), 합계 ≤ 러닝타임 25%. 대본 `04_영상소스/collage/cg<n>.json` → `scripts/render_collage.py`(엔진 = `공유 프로젝트/cutout-collage-lab`) → `ov<n>.mp4`를 오버레이 트랙에 `style: "collage"`로 얹는다. 오프닝 부재·4개 이상·25% 초과는 `render_collage.py`·`validate_pipeline.py`(검사 F)가 기계로 막는다. 규칙 = youtube-editor Step 6.7 + design.md §4.
6. ⏸ **화이트보드 드로잉 장면 — 비활성(2026-08-16 오너 결정, 제안·사용 금지; 켜는 법 = `scripts/whiteboard/README.md`)**. 켜져 있을 때의 규칙: 수치 없는 스토리·비유 대목에 한해 `scripts/render_whiteboard.py`로 4색 선화가 그려지는 클립(`wb<n>.mp4`)을 만들어 같은 오버레이 트랙에 `style: "whiteboard"`로 얹는다(자막은 잉크색 유지). 🔒 영상당 1~3장면. 규칙 = design.md §4 렉시콘 + `템플릿/whiteboard/README.md`, 롤백 = `scripts/whiteboard/README.md`.

7. **연출 게이트 2종(2026-08-27 신설)** — `scripts/check_storyboard.py`(**Step 4 직후**: route 누락·샷 창 미충족·리빌 시각이 단어 타임스탬프 밖·프론트로딩·전환 유형 4종 이상 차단)와 `scripts/check_motion.py`(**Step 7 캡처 직후**: capture.mp4 프레임 차분으로 "80~90% 정지 화면" 회귀·컷 경계 죽은 박자 차단). 선택 감사기 = `scripts/hf_audit.py`(레이아웃 겹침·잘림·명암비). **기존 게이트는 그대로 유지**한다 — `validate_pipeline.py`·`check_caption_safe.py`(자막 안전영역 21vh)·`split_captions.py`(16자). HF 히어로 인서트(`style: "hyperframes"`, `scripts/render_hf.py`, 편당 0~2개)는 콜라주와 **합산해** 오버레이 총량 ≤ 러닝타임 25% 게이트를 공유한다.

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
    ├── 03_자막/             ← full.srt + transcript.json (Whisper 원본)
    ├── 04_영상소스/         ← STORYBOARD.md(연출 스토리보드 — Step 4) + presentation.html (SLIDE_TIMELINE 내장) + capture.mp4 (헤드리스 캡처) + ov<n>.mp4 + 사용 이미지/로고
    ├── 영상 소스/           ← (오버레이 모드) 사용자 제공 시연/실사 영상 원본
    ├── 캡컷 조립 재료/      ← CapCut 조립·검수에 필요한 파일만 모음 (Step 8.5 하드링크 — 사람용, 이 폴더 하나만 보면 됨)
    └── 05_쇼츠/short-NN/    ← 쇼츠별: source.html + short-NN.srt + 컷지시서.md + 타임라인.json
```

- 새 작업 시작 시 이 구조를 먼저 생성하고 `작업정보.md`를 쓴다. 기존 작업 이어서 할 때는 해당 폴더를 찾아 이어서 작업한다.
- 같은 날짜·주제 폴더가 이미 있으면 새로 만들지 말고 그 폴더에 이어서 저장한다.
- **산출 위치는 결과물/ 고정 (2026-07-15 사용자 결정)**: 사용자가 기초 자료(`대본/`+`녹음본/`+선택 `영상 소스/`)가 든 외부 폴더를 지정해도 그 자리에 산출하지 않는다 — 새 `결과물/` 작업 폴더에 기초 자료를 복사해 온 뒤 모든 산출물을 그 안에 만든다. 외부 원본은 읽기 전용(대본 끝 섹션 append도 작업 폴더 사본에만).

## 전역 규칙 (모든 스킬 공통)

1. **최종 합성/export는 기본 금지, 명시 요청 시만 허용**: 기본 경로는 캡컷 검수다 — 완성본 영상의 합성·내보내기는 하지 않고 CapCut에서 사용자가 검수 후 직접 한다. 단 **영상 소스 캡처**(`scripts/capture_slides.py` 헤드리스 통녹화 → capture.mp4)와 **CapCut 드래프트 조립**(`scripts/assemble_capcut.py`)은 AI가 수행한다. CapCut 조합 상태와 수동 폴백은 편집지시서로 안내한다. **예외(2026-07-23 사용자 결정)**: 사용자가 "완성본으로 뽑아줘" 등 검수 생략을 명시하면 `scripts/render_final.py`(기본 ffmpeg 엔진, 본편 16:9 한정)로 완성본을 합성할 수 있다 — 사용법·벤치마크는 `리모션/README.md` 참조. 명시 요청 없이 완성본을 만들지는 않는다.
2. **원본 속도**: 배속 변환을 하지 않는다. 허용되는 유일한 오디오 편집은 **무음 컷**(youtube-editor Step 1.5, `scripts/trim_silence.py`)이며 반드시 STT **이전**에만 수행한다 — 컷 이후의 트림본(`.trim.m4a`)이 모든 타임코드(자막, 편집지시서, 타임스탬프)의 기준이다.
2-1. **자막 한 컷 ≤16자**: 자막(SRT)은 한 컷에 **최대 16자(공백 포함)**만 노출한다. AI는 자연스러운 구로 묶기만 하고, 16자 분할은 `scripts/split_captions.py`가 결정론적으로 강제한다(프롬프트 아님). `assemble_capcut.py`가 임포트 직전 한 번 더 멱등 강제 — 최종 드래프트는 항상 ≤16자. 분할 컷은 원래 자막 구간 안에 머물러 싱크 불변. 규격: youtube-editor `자막-안전영역.md`.
3. **한글 우선**: 슬라이드/인포그래픽 내 모든 텍스트는 한글. 고유명사(GPT, Claude, Cursor 등)만 영어 허용.
4. **인포그래픽 퍼스트**: 슬라이드는 텍스트만으로 구성하지 않는다. 항상 SVG/차트/도형이 주인공.
5. **레퍼런스 자동 참조**: 슬라이드·썸네일 프롬프트 작업 시 `레퍼런스/`(로고·스티커·썸네일 스타일)를 **묻지 말고 자동 스캔**해서 활용한다 (예: Step 9-2의 claude.png 모양 참고).
6. **API 토큰**: `.env`에서 읽는다 — `OPENAI_API_KEY`(Whisper). 토큰 값을 출력하거나 커밋하지 않는다.

## 환경 전제

- Windows 환경에서는 `python3` 명령이 없을 수 있다 — `python` 또는 `py -3`로 폴백한다.
- 슬라이드 HTML은 브라우저에서 열어 확인한다 (Remotion/Node 빌드 불필요). `리모션/`은 렌더러 전환 평가용 샌드박스(2026-06-11, 전환 보류 결론)로 현행 파이프라인 소속이 아니다 — 결론·재검토 트리거는 `리모션/README.md` 참조.
- 공용 에셋: `레퍼런스/로고/`(자주 쓰는 제품 로고), `레퍼런스/교정사전.json`(Whisper 오인식 영구 교정 사전 — 문맥 무관 항목만 등재), `템플릿/`(슬라이드 보일러플레이트), `scripts/`(캡처·드래프트 조립·자막 16자 분할 `split_captions.py`·오인식 교정 `apply_corrections.py`·무음 컷 `trim_silence.py`·오버레이 배속 인코딩 `encode_overlays.py`·조립 재료 스테이징 `stage_capcut_kit.py`·싱크 계약 검증 `validate_pipeline.py`·자막 안전 영역 검사 `check_caption_safe.py`(본편 캡처 전 자동 게이트)·대본 구조/사실 게이트 `check_script.py`·레퍼런스 모션 문법 분석 `analyze_motion.py`(선택)·콜라주 인서트 렌더 `render_collage.py`(오프닝 필수, 엔진 = 별도 레포 cutout-collage-lab)·화이트보드 드로잉 렌더 `render_whiteboard.py`(선택, 엔진 `scripts/whiteboard/` vendored MIT)·**스토리보드 게이트 `check_storyboard.py`**·**모션 게이트 `check_motion.py`**·HF 감사기 `hf_audit.py`(선택)·HF 히어로 인서트 렌더 `render_hf.py`(선택)·환경 진단 `doctor.py`). 모션 v2용 로컬 GSAP = `벤더/gsap.min.js`.
- pip 의존성은 `requirements.txt`의 검증 버전으로 고정한다. 새 기기·원인 불명 실패 시 `python scripts/doctor.py`부터.
- CapCut 자동화 의존성(pip): `pycapcut`, `playwright`(+`python -m playwright install chromium`), `imageio-ffmpeg`. 드래프트 조립 시 CapCut은 닫혀 있어야 하고, 국제판 비암호화 버전(9.x, 2026-05 확인)을 유지한다 — **CapCut 자동 업데이트 OFF**.

## 스킬 수정 시

- 스킬 간 규칙이 어긋나지 않게 유지한다 (특히 색상 규칙은 design.md만 고친다).
- 규칙 경고문과 코드 예시가 모순되면 안 된다 — 예시가 경고를 무력화한다. 규칙을 바꾸면 해당 스킬의 모든 코드 예시도 같이 바꾼다.
