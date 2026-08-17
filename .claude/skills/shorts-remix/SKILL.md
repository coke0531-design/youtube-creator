---
name: shorts-remix
description: "Reprocesses finished long-form videos (영상 모음 final.mp4) into 9:16 YouTube Shorts: black letterbox frame + head copy + burned captions, rendered by scripts/remix_shorts.py from a remix plan JSON. Use for 쇼츠 리믹스 — making Shorts from an existing long-form mp4. Not for slide-rebuild shorts from transcript+HTML without a finished video (→ youtube-short-generator)."
---

# 쇼츠 리믹스 — 롱폼 영상 재가공 (9:16 검은띠 프레임)

완성된 롱폼 영상(예: `영상 모음/풀링_NNN/final.mp4`)에서 구간을 잘라 **검은띠 프레임 + 헤드카피 + 번인 자막**의 완성형 쇼츠 mp4를 만든다.

| 기존 youtube-short-generator | 이 스킬 (shorts-remix) |
|---|---|
| 입력: transcript.json + 대본 → 세로 슬라이드 **신규 제작** | 입력: **완성 롱폼 mp4** (오디오·타임베이스·클립 선정의 원천) |
| 흰 배경 인포그래픽, CapCut 조립 | 검은띠 프레임 + 1080x700 재생성 소스, ffmpeg 완성형 렌더 |

**영상 소스 2모드**: 기본 = **capture(소스 재생성)** — 컷 구간용 슬라이드를 새로 그려(1080x700, 흰 배경 4색) 캡처해 넣는다. 원본에 박힌 자막과의 이중 표시를 원천 차단하고 화면 점유를 키운다. 폴백 = extract(원본 픽셀 1080x608) — 원본에 자막이 없는 소스나 일회성 작업에만.

## 🔴 규정 관계 (design.md와의 예외)

- design.md §7의 "검정 배경 금지"와 가로세로-변환.md의 "레터박싱 금지"는 **슬라이드 소스 제작 규정**이다. 리믹스 프레임(완성 영상을 감싸는 검은띠 `#0A0A0A`)은 그 대상이 아니며, 2026-08-13 사용자 지시로 신설된 별도 산출물 계열이다.
- 헤드카피 강조색·자막 강조색은 design.md 브랜드 앰버(`#F59E0B`)를 따른다.
- 배속 금지·한글 우선 등 전역 규칙은 그대로 적용된다.

## 🔒 타임베이스 계약 (가장 중요한 함정)

**STT는 반드시 final.mp4에서 추출한 오디오로 돌린다. 폴더에 있는 녹음본(m4a) STT 금지.**
녹음본은 무음 컷 이전/이후 편집을 거쳐 final.mp4와 타임코드가 조용히 어긋난다. final.mp4 추출 오디오로 STT하면 transcript 타임코드 = 영상 타임코드가 원천 일치한다. cuts·SRT의 모든 시각은 이 타임베이스 하나만 쓴다.

## 참조 파일

| 파일 | 용도 |
|------|------|
| [클립-선정.md](클립-선정.md) | 🔑 롱폼에서 어떤 대목을 어떻게 가져올지 — 4조건·재배치·헤드카피 패턴 |
| [리믹스-레이아웃.md](리믹스-레이아웃.md) | 검은띠·헤드카피·자막의 픽셀 규격과 근거 |
| [../youtube-short-generator/감정-설계.md](../youtube-short-generator/감정-설계.md) | 쇼츠별 주력 감정 1개 + 쇼츠 간 차별화 (그대로 적용) |
| [../../../레퍼런스/쇼츠-리믹스-조사-2026-08.md](../../../레퍼런스/쇼츠-리믹스-조사-2026-08.md) | 조사 원문 (출처 포함) |

## 워크플로우

```
1. 폴더 생성    결과물/YYYY-MM-DD_<주제>-리믹스/ (아래 폴더 규약)
2. 원본 복사    final.mp4 + 최종 대본 md → 00_원본/ (영상 모음 원본은 읽기 전용)
3. 오디오 추출  ffmpeg -i final.mp4 -vn -c:a copy 01_오디오/audio.m4a
4. STT         Whisper(word timestamps) → 02_자막/transcript.json + full.srt
               ⚠️ trim_silence 금지 — 타임베이스 계약 참조
5. 클립 선정    대본+transcript 분석 → 쇼츠 2~4개 선정 (클립-선정.md 절차)
               → 03_클립/클립계획.md (후보 → 4조건 평가 → 선정 근거)
6. 헤드카피     쇼츠별 헤드카피 확정 (클립-선정.md §3 패턴 5종, 줄당 ≤15자, ≤2줄)
7. 계획 JSON   04_쇼츠/short-NN/remix.json 작성 (아래 스키마)
8. SRT 재계산  쇼츠 타임라인(t=0=첫 컷) 기준 재계산 후 16자 강제:
               python scripts/split_captions.py <short-NN.srt> && --check 통과
9. 렌더        python scripts/remix_shorts.py 04_쇼츠/short-NN/remix.json
               → short-NN.mp4 (1080x1920 완성형, 자막 번인, CTA 엔드카드 포함)
10. 검수·마무리 실기기(폰) 확인 안내 + 작업정보.md 갱신 + 업로드 가이드 출력
```

CapCut에서 직접 만지고 싶다는 요청이면 `--no-subs`로 렌더하고 SRT를 남긴다(자막은 CapCut에서).

### 폴더 규약

```
결과물/YYYY-MM-DD_<주제>-리믹스/
├── 작업정보.md
├── 00_원본/    final.mp4 + 대본.md (사본)
├── 01_오디오/  audio.m4a (final.mp4 추출본)
├── 02_자막/    transcript.json + full.srt (영상 타임베이스)
├── 03_클립/    클립계획.md
└── 04_쇼츠/short-NN/  remix.json + short-NN.srt + short-NN.mp4 + 헤드카피 메모
```

### remix.json 스키마

```json
{
  "type": "remix_short",
  "source_video": "../../00_원본/final.mp4",
  "canvas": {"w": 1080, "h": 1920, "bg": "#0A0A0A"},
  "video_y": 500,
  "head_copy": {"lines": ["첫 줄 ≤15자", "둘째 줄 ≤15자"], "accent_words": ["강조어"]},
  "video": {"mode": "capture", "path": "source_capture.mp4", "h": 700},
  "audio_source": "../../01_오디오/audio.m4a",
  "cuts": [
    {"src_start": 201.15, "src_end": 224.60},
    {"src_start": 132.40, "src_end": 148.90}
  ],
  "srt": "short-01.srt",
  "cta": {"duration": 2.0, "text": "풀버전은 채널에 👆"},
  "output": "short-01.mp4"
}
```

- 경로는 JSON 파일 위치 기준 상대경로. cuts는 **영상 타임베이스**, srt는 **쇼츠 타임라인** 기준.
- cuts는 **재배치 순서대로** 적는다(시간 역순 허용 — 결론 선행). 구간 겹침만 금지.
- capture 모드 워크플로우: 컷 확정 후 `source.html`(쇼츠 타임라인 SLIDE_TIMELINE, 보일러플레이트 = `템플릿/shorts-remix-source.html`)을 만들어 캡처하고, 캡처 길이 = 컷합(±0.3s, 렌더가 기계 검증). 소스 내용은 나레이션이 말하는 것만 그린다 — 대사에 없는 메시지 추가 금지.
- SRT 재계산 공식은 [../youtube-short-generator/오디오-컷.md](../youtube-short-generator/오디오-컷.md)와 동일 (dst = src − 앞선 컷 제거분 누적).

## 길이·개수·업로드 (근거: 조사 문서)

- 쇼츠당 **20~60초, 정보성 목표 35~45초**. 60초 초과 시 상업 음원 절대 금지(전 세계 차단 위험 — 나레이션·자체 음원만이면 무관).
- 롱폼 1편당 **2~4개**, 서로 주제·주력 감정이 달라야 한다(감정-설계.md).
- 업로드: 롱폼 먼저 → 쇼츠는 당일·다음날·48~72시간·1주 뒤로 분산. 각 쇼츠에 **관련 동영상 링크**(스튜디오 → 쇼츠 → 관련 동영상)로 본편 연결 + 마지막 CTA와 약속 일치.

## 체크리스트

- [ ] STT가 final.mp4 추출 오디오 기준인가 (녹음본 STT 아님)
- [ ] 쇼츠별 4조건 통과: 2초 훅 / 단일 생각 / 깔끔한 끝 / 맥락 자립 (클립계획.md에 평가 기록)
- [ ] 헤드카피 ≤2줄·줄당 ≤15자·패턴 5종 중 하나·강조어는 앰버
- [ ] split_captions.py --check 통과 (모든 컷 ≤16자)
- [ ] 렌더 실측: 1080x1920, 총길이 = 컷합 + CTA, 오디오 존재 (스크립트가 ffprobe로 출력)
- [ ] 첫 프레임에 훅이 보이는가 (빈 화면·페이드인 시작 금지 — 0초부터 본론)
- [ ] 1930x1080 소스(풀링_005·006·008) 여부 확인 — 스크립트가 흡수하지만 검수 시 좌우 여백 확인
- [ ] 작업정보.md 갱신 + 실기기 확인 안내 + 업로드 분산 일정 제안
