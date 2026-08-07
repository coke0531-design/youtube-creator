# 리모션 (Remotion 평가 샌드박스)

**상태: 평가 완료 — 현행 파이프라인(HTML+헤드리스 캡처) 유지, Remotion 전환 보류** (2026-06-11)

이 폴더는 "직접 캡처 대신 Remotion을 쓰면 더 효율적인가?"를 실측 평가하기 위한 샌드박스다.
**현행 워크플로우의 일부가 아니다** — 스킬 5종·템플릿·capture_slides.py는 그대로 유효하다.

## 평가 결론 (왜 전환하지 않았나)

| 쟁점 | 판정 |
|------|------|
| **구조적 이점 무용** | Remotion의 차별 가치는 오디오·자막 통합 최종 렌더인데, 이 워크스페이스는 "최종 합성 금지 — CapCut에서 사용자 검수·export" 계약(CLAUDE.md 전역 규칙 1)이라 어차피 산출물은 **무음 capture.mp4 1개**로 동일. CapCut 드래프트 조립도 동일하게 필요 |
| **속도 이점 미미 (실측)** | 이 머신(6코어)에서 12초/360프레임 1080p 렌더 = **19.1초**(번들링 포함, concurrency 3x) → 378초 영상 환산 약 8~15분. 현행 frames 모드 추정(10~20분)과 동급, 결정적 차이 없음 |
| **전면 포팅 필수** | 현 템플릿 모션은 전부 CSS 트랜지션+클래스 토글 상태 기계 — Remotion 프레임 클록과 비호환이라 iframe 재활용 불가, 컴포넌트 문법 전체(design.md §5)를 16:9/9:16 두 벌 재작성해야 함 |
| **구버전 자산 재활용 가치 낮음** | 구 Remotion 스킬(1554줄)의 패턴 13종은 검정 배경+#00FF88 3색 전제 — v3 디자인 SSOT(흰 배경 4색)와 전면 충돌, 사실상 리컬러가 아닌 재설계 |
| **의존성·정책 비용** | pip 3종 → npm 대규모 트리 추가 (npm 공급망 정책상 `--ignore-scripts`+버전 핀 필수). Remotion은 일부 기업 조건에서 유료 라이선스(개인/소규모는 무료) |

**현행 frames 캡처의 실전 불안정(풀링 008에서 실패 흔적)은 실재하나**, 그 해법은 렌더러 교체가 아니라
청크 병렬화·관측성 수선(자식 stdout 로그 라우팅) 같은 저비용 보완이 우선이다 — 상세는 감사 보고 참조.

## 재검토 트리거 (이 중 하나가 발생하면 전환 재논의)

1. "무음 capture.mp4 + CapCut 드래프트" 계약이 바뀌어 **통합 최종 렌더가 허용**되는 시점
2. frames 캡처가 보완(병렬화·관측성) 후에도 **반복 실패**할 때
3. Chromium 업데이트로 `HeadlessExperimental.beginFrame` CDP가 깨졌을 때

## 샌드박스 내용

- `src/SampleVideo.tsx` — **타임라인.json(slides/stages) → Remotion 컴포지션 매핑 데모** (싱크 계약 t=0=음성 시작 유지, design.md 4색 적용). 전환 시 출발점.
- `src/timeline.ts` — 타임라인.json 스키마의 TS 표현 + `slideAt()` (프레임→슬라이드/스테이지 해석)
- `src/design.ts` — design.md §2-3 색상 토큰 (SSOT는 design.md)
- `out/preview.png`, `out/capture.mp4` — 검증 렌더 산출물 (12s, 1080p)

## 사용법

```bash
npm run dev            # Remotion Studio (오디오 스크럽 프리뷰)
npm run still          # 스틸 1장 렌더 (디자인 확인)
npm run render         # 풀 렌더 → out/capture.mp4
```

⚠️ `npx remotion ...` 직접 호출은 보안 훅이 차단한다 — **npm run 스크립트를 통해 실행**할 것.

## 원격 접속 (Remotion Studio 상시 서비스, 2026-07-23)

- Windows 서비스 **`RemotionStudio`**(NSSM, 자동 시작)가 Studio를 포트 3000에 상시 구동한다.
  - NSSM이 한글 경로 인자를 깨뜨리므로 실행 엔트리는 ASCII 경로 래퍼 `C:\ProgramData\RemotionStudio\start.js` (경로는 \u 이스케이프로 내장).
  - 로그: `logs\studio.out.log` / `logs\studio.err.log`
  - 관리: `nssm stop|start|restart RemotionStudio` (nssm은 win-cli-bridge\tools\nssm.exe)
- Tailscale serve가 **https://desktop-rkughh3.tail075a2b.ts.net:8445** → localhost:3000 으로 프록시한다 (tailnet 전용, 재부팅 후에도 유지). 노트북 등 tailnet에 물린 기기 브라우저에서 이 주소로 Studio를 열어 프리뷰·렌더를 원격 조작할 수 있다.
  - 해제: `tailscale serve --https=8445 off`
- 서비스가 켜져 있는 동안 로컬에서 `npm run dev`를 또 띄우면 포트 충돌한다 — 로컬 작업 시 서비스 Studio(localhost:3000)를 그대로 쓰면 된다.

## 완성본 렌더 (opt-in, 2026-07-23)

작업 폴더의 산출물(무음 `capture.mp4` + `narration.m4a` + `full.srt` + `타임라인.json` + 선택 `ov<n>.mp4`)을
한 번에 합성해 완성본 mp4를 만드는 **선택 경로**다. 엔진은 2종이고 **기본은 ffmpeg**(실측 확정, 아래 표).

```bash
python scripts/render_final.py <작업 폴더>            # 기본 = ffmpeg + NVENC 자동 (불가 시 libx264 폴백)
python scripts/render_final.py <작업 폴더> --x264     # libx264(crf17) 강제 (CPU 인코딩)
python scripts/render_final.py <작업 폴더> --engine remotion   # Remotion 경로 (옵션)
```

- **캡컷 경로와의 관계**: 기본은 여전히 "무음 capture.mp4 + CapCut 드래프트 → 사람이 검수·내보내기"다.
  이 경로는 그 검수를 생략하고 바로 완성본을 뽑고 싶을 때만 쓰는 선택지다 — `assemble_capcut.py`를 대체하지 않는다.
- **엔진 벤치마크 (2026-07-23, 343초/1080p/오버레이 4개 실전 샘플, 6코어+GTX 1060)**:

  | 엔진 | 벽시계 | SSIM(무손실 참조 대비) | 비고 |
  |------|--------|------|------|
  | remotion (`Final` 컴포지션) | 약 29분 | — | 프레임별 헤드리스 크롬 스크린샷 방식 — 합성 전용으로는 과체중 |
  | ffmpeg libx264 crf17 | 약 99초* | 0.999749 | `--x264`로 강제 가능. 파일 작음(19MB) |
  | ffmpeg NVENC cq19 | 약 47초* | 0.999835 | **기본값** (화질 동등 이상 정량 확정). 파일 1.5배(30MB) |

  (* 유휴 머신 기준. 초기 실측은 x264 약 3.5분/NVENC 69초 — 부하 상태 값.)
  두 인코딩 모두 무손실급(SSIM 0.9997+, PSNR 58~63dB)이고 육안 차이 없음(프레임·자막 가장자리 크롭 대조).
  **기본 = NVENC 자동**: 1프레임 시험 인코딩으로 가용성을 판정하고, GPU 없는 머신에선 libx264로 자동 폴백한다.
- **미러링**: 입력 해석·자막 색(기본 잉크 `#141413`, 오버레이 구간 흰색)·자막 위치(하단 162px)·오버레이
  구간 로직은 `assemble_capcut.py`를 그대로 따른다. 자막 16자 강제·싱크 계약 검증도 같은 choke point를 재사용한다.
  ffmpeg 엔진은 바닥 영상을 항상 1920x1080으로 정규화한다(capture.mp4가 1440p로 캡처된 실측 사례 —
  정규화 없이는 오버레이·자막 좌표가 어긋난다).
- **remotion 엔진 동작**: `public/job/` 스테이징 → `npm run final`(=`remotion render Final`) →
  `out/final.mp4`를 작업 폴더 `완성본/`으로 복사. 슬라이드 자체를 Remotion으로 그리게 되는 시점의 경로로 유지한다.
- **자막 폰트**: Pretendard 정적 9종을 시스템 폰트로 설치 완료(2026-07-23) — 자막은 Pretendard Bold로
  렌더된다(렌더 로그 fontselect로 확인됨). 다른 머신에서 돌릴 땐 Pretendard 미설치 시 맑은 고딕 폴백.
- **쇼츠 9:16(`type=short`)**: **ffmpeg 엔진에서 지원**(`scripts/render_final.py <쇼츠 폴더>` — 타임라인.json의
  `type`으로 자동 감지). 1080x1920 정규화 + `audio_cuts`대로 나레이션 구간을 잘라 이어붙이고(assemble_capcut.py와
  동일 결과) 쇼츠 ASS 자막(하단 384px)을 굽는다. **remotion 엔진의 쇼츠는 계속 미지원** — remotion 쇼츠는 CapCut
  경로를 쓴다. 쇼츠 영상 오버레이(ov)는 스키마에 없어 미구현(자막은 전부 잉크색).

## 설치 이력 (보안 정책 준수)

- 버전 핀 고정: remotion/@remotion/cli **4.0.496**, react 19.2.7, typescript 5.9.3
- `npm install --ignore-scripts`로 설치 (postinstall 스크립트 차단), 컴포지터/esbuild 바이너리는 optionalDependencies로 정상 확보
- Chrome Headless Shell 113MB는 첫 렌더 시 Remotion 공식 경로(chrome-for-testing)에서 다운로드됨
