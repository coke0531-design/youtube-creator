# youtube-creator / scripts/film (연출 위임형 v3.2 필름 도구)

> 정본 편입 2026-09-30, 출처 실험판 `youtube-creator-lab/scripts/`(내용 그대로 복사, `_smoke/` 제외). 절차는 `.claude/skills/youtube-editor/SKILL.md` Step 4~8, 킷 검사기 `kit_check.py`는 같은 폴더(킷 담당 소유). 아래 본문의 "실험"·`_smoke/` 언급은 실험판 기준 기록이다.


필름 HTML 실험용 작은 도구 5개. 정본 `youtube-creator/scripts`(capture_slides.py·render_final.py·check_motion.py)는 참고만 했고 수정하지 않았다.

## 필름 HTML 계약

- `window.FILM = {duration, width: 1920, height: 1080, fps: 30}`
- `window.seek(t)`: 시간 t(초)의 **순수 함수**로 화면 전체를 그린다. CSS transition·타이머·rAF 상태에 기대지 않는다. Promise를 돌려줘도 된다(await 함).
- `window.FILM_READY === true`: 폰트 로드 뒤 세팅.
- 자막은 HTML이 그리지 않는다(mux.py에서 번인).

## 흐름

```
segment.py  → 02_음성/narration.m4a · 03_자막/{transcript.json, full.srt, beats.json}
capture.py  → capture.mp4            (필름 HTML → mp4, --verify-seek 로 결정론 검사)
beatsheet.py→ sheet.jpg              (비트별 대표 프레임 한 장)
still_ratio.py → 정지 비율 JSON       (check_motion.py 와 같은 판정식)
mux.py      → final.mp4              (자막 번인 + loudnorm, 길이 = 오디오)
```

## 스크립트 요약

| 스크립트 | 하는 일 | 핵심 동작 |
|---|---|---|
| segment.py | 긴 녹음·transcript에서 [S,E] 구간 발췌 | aac 192k/48k 재인코딩. transcript는 원본 키 구조 유지(모르는 키도 보존). 경계에 걸친 segment·SRT 컷은 원본 중점 기준 구간 안 단어로 text 재구성. SRT는 16자 초과 시 단어 경계 균등 분할·글자 수 비례 시간 배분. 비트 원천: segments → 없으면 같은 폴더 full.srt(무음 < 0.45s·합친 길이 ≤ 4.5s 병합) → 그것도 없으면 words(0.45s 이상 갭 분할). `--beats-only`는 beats.json만 쓴다(같은 폴더 지정 가능, 다른 파일 해시 불변 확인). beats-only 없이 --src=--out 이면 거부(exit 2). |
| capture.py | 필름 HTML → mp4 | `--workers N`(v3.1): 프레임 구간을 N등분해 자식 프로세스(`--workers 0`)로 찍고 concat `-c copy`. 60초 경량 필름 97.5s→37.4s(워커 4). `FILM.holds`가 있으면 `<out>.holds.json`으로 저장. Playwright chromium headless, viewport=size, DSF 1, `--force-color-profile=srgb --disable-gpu-vsync` 등. 프레임마다 `seek(t)` → CDP `Page.captureScreenshot(png, optimizeForSpeed)` → ffmpeg image2pipe 스트리밍. h264_nvenc cq19(시험 인코딩 실패 시 libx264 crf18), yuv420p·bt709·tv-range. 10초마다 진행 로그. `--verify-seek N`: t=0·끝 프레임 포함 N개 시각을 ① 같은 페이지 순방향 2회 ② 같은 브라우저 **새 페이지에서 무작위 순서**로 찍어 ①의 1회차와 비교, 결과를 따로 보고하고 `<out>.verify.json` 저장. 차이 있으면 exit 1. |
| beatsheet.py | 비트 표 → 프레임 시트 jpg | 비트 start+offset(비트 끝 - 1/fps, 영상 끝 - 1/fps 로 클램프) 시각 캡처, 480px 타일, 밑에 `#i t=.. "앞 18자"` 라벨(malgun.ttf). `--times`는 `@n t=..` 라벨. 둘 다 주면 합친다. |
| mux.py | 완성본 합성 | SRT→ASS(PlayRes 1920x1080, Alignment 2, MarginV = --bottom, 좌우 160). 폰트 Pretendard 설치 시 Pretendard, 아니면 Malgun Gothic. `--style outline`(기본, 흰 글자·검은 외곽선 3px·볼드) / `--style box`(render_final.py 흰 상자 자막 재현). 1920x1080 lanczos 정규화 → 오버레이(선택) → ass 번인. 오디오 loudnorm I=-14:TP=-1.5:LRA=11 1-pass → 48k aac 192k. `-shortest` 없음: 비디오가 짧으면 마지막 프레임 tpad clone, 길이는 `-t 오디오 길이`. 인코더 nvenc cq19 / libx264 crf17(render_final과 동일). |
| join_acts.py (v3.1) | 막 캡처 이어 붙이기 + 이음매 검사 | 막 N 마지막 프레임 vs 막 N+1 첫 프레임 픽셀 차(mean ≤ 2 · max ≤ 80 OK, nvenc 잡음 실측 max 51~63) → concat demuxer `-c copy`. `--no-concat`로 검사만. E·F 실측 5곳 전부 OK |
| cam_check.py (v3.2) | 카메라 왕복 검사 | 필름 HTML의 `const CAM…=[[t,x,z],…]` 배열을 읽어 R1 유지 3초·R2 작은 밀기·R3 6초 왕복·R4 이동당 4초 위반을 센다. 배열 방식이 아니면 exit 2(수동 검사). G4 실측: CAM_A 24키프레임/33초 → 위반 다수 |
| still_ratio.py | 정지 화면 비율 | `--holds "a-b,c-d"` 또는 JSON(v3.1): 홀드 안 표본을 뺀 비율 열(`still_ratio_excl_holds`)과 평균(`avg_still_ratio_excl_holds`)을 함께 낸다. 판정은 기본 raw(`--judge excl`로 바꿀 수 있음). check_motion.py diff_series 그대로: 10fps·320px 그레이, `d5 = mean|f[k]-f[k-5]|`(0.5초 격자) < eps(1.0) 이면 정지. 창 [a,b]는 a+0.5 ≤ t ≤ b 표본으로 비율 계산, fail 0.75(초과)/warn 0.50(이상). 평균 = 판정 창 평균. 최대 정지 연속 구간 = 연속 정지 표본 (n-1)*0.1+0.5초. 참고용 인접 프레임(d1) 정지 비율도 출력(판정 미사용). FAIL 있으면 exit 1. |

## 스모크 결과 (2026-09-29, `_smoke/`)

| 항목 | 결과 |
|---|---|
| capture 6초 필름 | 180프레임, 캡처+인코딩 약 10~13초(14~18 fps), h264_nvenc |
| capture 60초 필름(속도 기준) | **1800프레임 97.5초**(18.5 fps) — 기준 5분 이내 통과 |
| capture `--workers 4` 60초 경량 필름 (v3.1) | 1800프레임 **37.4초**(48.1 fps), 청크 4×450, 직렬본과 프레임 수·시각 일치(픽셀 차는 인코더 잡음 mean 0.05) |
| capture `--workers 6` B세트 애프터 필름(Canvas 그레인, 무거움) | 1983프레임 **3분 51초**(8.7 fps, 워커당 1.5 fps) — v3.0 직렬 12~17분 대비 약 4배 |
| still_ratio `--holds` B세트 애프터 | 홀드 4구간 9.5초 제외 → 원시 52.6% / 홀드 제외 50.3%, 판정(raw) 불변 |
| verify-seek 5 (순수 필름) | 시각 0.0·1.7·2.3·4.9·5.9667 — **순방향 OK / 무작위(새 페이지) OK**, 전부 max_diff 0 |
| verify-seek 음성 대조(`film_impure.html`, seek 호출 수를 화면에 표시) | 순방향 FAIL 3 / 무작위 FAIL 2, exit 1 — 검사가 불순한 seek를 잡는다 |
| 실제 프레임 확인 | mp4 프레임 0·45·179 = 카운터 0.00·1.50·5.97 (지난 프레임이 찍히는 문제 없음) |
| still_ratio (6초, 4.0~5.0초 의도적 홀드) | 창 1개 정지 9.1%(5/55 표본), 최대 정지 0.90s(4.00~4.90), FAIL 0·WARN 0 — 예상값과 일치 |
| still_ratio (60초) | 창 10개 평균 0.9%, FAIL 0 |
| beatsheet `--times` 6개 | 3열x2행 1464x626 jpg, 4.2·4.8초 타일이 모두 4.00(홀드) |
| mux 기본(무음 6초 aac) | 6.00s, h264 1920x1080 yuv420p bt709 + aac 48k, 자막 outline Pretendard 60px |
| mux box + 오버레이 + 오디오 8초 | 8.00s, 마지막 프레임 2초 연장, 6.5초부터 오버레이가 자기 t=0으로 시작 |
| segment (segments 있는 원본 30.5~75s) | 오디오 44.5s, segments 13(경계 재구성 2)·words 81·SRT 29컷(최대 15자)·beats 13 |
| segment (words만 + full.srt, 5~40s) | 원천 full.srt(병합), SRT 20컷·beats 10, 경계 단어 누수 없음, 원본 키 구조 유지 |
| segment `--beats-only` 제자리 | beats 16, 음성·transcript·full.srt md5 불변 |
| segment `--beats-only` (SRT 없음) | 원천 words(갭 분할), beats 11 |

## 제약·미구현

- 캡처 속도는 1080p PNG 기준 약 15~18 fps. 10분 영상이면 약 10분 걸린다. 청크 병렬 캡처는 없다.
- capture.py는 가상 시간(BeginFrame)을 쓰지 않는다. seek(t)가 순수 함수라는 계약에 기대므로, CSS transition·animation·Web Animations·video 요소 재생은 캡처되지 않거나 비결정적이 된다. `--verify-seek`로 확인할 것.
- `reduced_motion="reduce"`로 연다. 필름이 prefers-reduced-motion에 따라 다르게 그리면 결과가 달라진다.
- mux.py loudnorm은 1-pass(dynamic). 정본 render_final.py의 2-pass linear가 아니다.
- mux.py 오버레이는 1개, 끝나면 그대로 사라짐(eof_action=pass). 알파 오버레이는 ffmpeg overlay 기본 처리에 맡긴다(미검증).
- still_ratio.py 창 판정은 길이가 정확히 window초인 창만 한다(check_motion의 "길이 > 6s"를 고정 창에 맞게 "≥ window"로 바꿈). 영상 끝 자투리 창은 SHORT로 판정 제외. 타임라인 슬라이드 단위 판정·죽은 박자 검사는 없다(check_motion.py 사용).
- segment.py의 16자 기준은 공백 포함 글자 수. words 폴백 비트에는 길이 상한이 없다(풀링013 실측 최대 9.96초 비트).
- beats-only 모드도 --start/--end를 주면 그 구간으로 잘라 재기준한다(생략 시 0~duration).

## --help 원문

```
=== segment.py
usage: segment.py [-h] --src SRC [--start START] [--end END] --out OUT [--beats-only]

긴 녹음·transcript에서 구간을 잘라 실험 재료 폴더를 만든다

options:
  -h, --help     show this help message and exit
  --src SRC      작업 폴더(02_음성/narration.m4a, 03_자막/transcript.json)
  --start START  시작 초 S (--beats-only면 생략 시 0)
  --end END      끝 초 E (--beats-only면 생략 시 transcript.duration)
  --out OUT      출력 폴더 (--beats-only면 --src와 같아도 됨)
  --beats-only   음성·transcript·full.srt는 건드리지 않고 03_자막/beats.json만 만든다
=== capture.py
usage: capture.py [-h] --out OUT [--fps FPS] [--size SIZE] [--start START] [--end END] [--verify-seek N]
                  [--encoder {auto,nvenc,x264}] [--ready-timeout READY_TIMEOUT]
                  html

필름 HTML(window.FILM + seek(t)) → mp4 결정론 캡처

positional arguments:
  html                  필름 HTML 경로

options:
  -h, --help            show this help message and exit
  --out OUT             출력 mp4
  --fps FPS             프레임레이트(기본 FILM.fps 또는 30)
  --size SIZE           뷰포트=출력 크기 (기본 1920x1080)
  --start START         시작 초(기본 0)
  --end END             끝 초(기본 FILM.duration)
  --verify-seek N       N개 시각(t=0·끝 프레임 포함)을 순방향 2회 + 새 페이지 무작위 순서로 캡처해 픽셀 차 0인지 검사 (<out>.verify.json)
  --encoder {auto,nvenc,x264}
                        auto = nvenc 시험 성공 시 nvenc, 아니면 libx264
  --ready-timeout READY_TIMEOUT
                        FILM_READY 대기 상한 초
=== beatsheet.py
usage: beatsheet.py [-h] [--beats BEATS] [--times TIMES] --out OUT [--offset OFFSET] [--cols COLS]
                    [--size SIZE]
                    html

비트 표 기반 프레임 시트(jpg)

positional arguments:
  html             필름 HTML 경로

options:
  -h, --help       show this help message and exit
  --beats BEATS    beats.json (segment.py 출력)
  --times TIMES    임의 시각 목록 "1.0,2.5,..."
  --out OUT        출력 jpg
  --offset OFFSET  비트 start에서 더할 초(기본 0.4)
  --cols COLS      열 수(기본 4)
  --size SIZE      캡처 뷰포트(기본 1920x1080)
=== mux.py
usage: mux.py [-h] --video VIDEO --audio AUDIO --srt SRT --out OUT [--font-size FONT_SIZE] [--bottom BOTTOM]
              [--style {outline,box}] [--overlay OVERLAY] [--overlay-start OVERLAY_START]
              [--encoder {auto,nvenc,x264}] [--keep-ass]

캡처 영상 + 나레이션 + SRT 번인(+오버레이) → 완성본 mp4 (길이=오디오)

options:
  -h, --help            show this help message and exit
  --video VIDEO         capture.mp4
  --audio AUDIO         narration.m4a
  --srt SRT             full.srt
  --out OUT             출력 final.mp4
  --font-size FONT_SIZE
                        자막 크기 px @1080 (기본 60)
  --bottom BOTTOM       텍스트 하단↔화면 하단 px = ASS MarginV (기본 108)
  --style {outline,box}
                        outline = 흰 글자 검은 외곽선 3px(기본) / box = render_final 흰 상자 자막
  --overlay OVERLAY     오버레이 영상(선택, 1920x1080 권장)
  --overlay-start OVERLAY_START
                        오버레이 시작 초(기본 0)
  --encoder {auto,nvenc,x264}
  --keep-ass            생성한 ASS를 출력 옆에 <out>.ass로 남긴다
=== still_ratio.py
usage: still_ratio.py [-h] [--eps EPS] [--window WINDOW] [--fail FAIL] [--warn WARN] [--width WIDTH]
                      [--json OUT]
                      mp4

정지 화면 비율 측정 (check_motion.py와 같은 판정식, 고정 창 단위)

positional arguments:
  mp4              측정할 mp4

options:
  -h, --help       show this help message and exit
  --eps EPS        정지 판정 임계(0.5초 차분 평균 절대차, 기본 1.0)
  --window WINDOW  창 길이 초(기본 6)
  --fail FAIL      FAIL 정지 비율(기본 0.75)
  --warn WARN      WARN 정지 비율(기본 0.50)
  --width WIDTH    분석 폭(기본 320)
  --json OUT       결과 JSON 저장 경로
```
