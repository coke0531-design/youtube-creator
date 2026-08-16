import React from 'react';
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {COLORS, FONT_STACK} from './design';
import {Caption} from './srt';

// ── 완성본 렌더(opt-in) ─────────────────────────────────────────────────────
// scripts/render_final.py가 public/job/ 에 스테이징한 산출물을 합성한다:
//   capture.mp4  — 무음 슬라이드 캡처 (바닥 트랙)
//   narration.m4a — 나레이션 오디오 (t=0 = 음성 시작, 싱크 계약 기준)
//   ov<n>.mp4    — video_overlays[] 구간에 슬라이드 위로 얹는 실사 영상 (무음)
//   full.srt / timeline.json — Root.tsx calculateMetadata가 파싱해 props로 주입
//
// 자막 = '흰 상자 자막' (2026-08-16 레퍼런스 픽셀 실측 — 스펙 SSOT는 자막-안전영역.md,
// 수치는 scripts/render_final.py ASS_BOX_*와 1:1 동기):
//   잉크 글자 52px 볼드 + 흰 상자(텍스트 밀착, 패딩 8/10px) + 테두리 2px #160E01
//   + 다크 앰버 #3B2603 하드 오프셋 섀도(우·하 10px, 블러 없음), 상자 중심 하단 86px, 컷 등장.
//   상자가 배경 무관 가독성을 보장하므로 오버레이 구간 흰색 오버라이드는 폐지.

export const FPS = 30;

export type Overlay = {n: number; start: number; end: number};

export type FinalProps = {
  captions: Caption[];
  overlays: Overlay[];
};

// 레퍼런스 실측(720p→1080p 환산): 자막 상자 '중심'의 하단거리 86px (8%H)
const CAPTION_CENTER_FROM_BOTTOM = 86;
const CAPTION_INK = COLORS.ink; // #141413 (기본 잉크)

const CaptionLayer: React.FC<FinalProps> = ({captions}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps; // 프레임 → 오디오 초 (t=0 = 음성 시작)
  const cur = captions.find((c) => t >= c.start && t < c.end);
  if (!cur) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: CAPTION_CENTER_FROM_BOTTOM,
        transform: 'translateY(50%)', // bottom 기준선을 자막 '중심'이 86px에 오도록 보정
        display: 'flex',
        justifyContent: 'center',
        padding: '0 160px',
      }}
    >
      <span
        style={{
          fontFamily: FONT_STACK,
          fontWeight: 800, // 레퍼런스 볼드 굵기 (ASS Bold=-1 상당)
          fontSize: 52, // 레퍼런스 글리프 높이 37.5px@1080p 환산
          lineHeight: 1.0,
          color: CAPTION_INK,
          backgroundColor: '#FDFEFE', // 흰 상자 — 텍스트 폭 밀착
          border: '2px solid #160E01',
          boxShadow: '10px 10px 0 #3B2603', // 하드 오프셋 섀도 (블러 0) — 브랜드 앰버 다크 스케일
          padding: '8px 10px',
          textAlign: 'center', // 중앙 정렬 (import_srt align=1)
          whiteSpace: 'pre-wrap', // 자동 줄바꿈
          maxWidth: 1400,
        }}
      >
        {cur.text}
      </span>
    </div>
  );
};

export const FinalVideo: React.FC<FinalProps> = ({captions, overlays}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: COLORS.bg}}>
      {/* ① 바닥 트랙 — 무음 슬라이드 캡처 */}
      <OffthreadVideo
        src={staticFile('job/capture.mp4')}
        muted
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
      {/* ② 오버레이 — video_overlays 구간에 슬라이드 위로 (무음) */}
      {overlays.map((o) => (
        <Sequence
          key={o.n}
          from={Math.round(o.start * fps)}
          durationInFrames={Math.max(1, Math.round((o.end - o.start) * fps))}
        >
          <AbsoluteFill>
            <OffthreadVideo
              src={staticFile(`job/ov${o.n}.mp4`)}
              muted
              style={{width: '100%', height: '100%', objectFit: 'cover'}}
            />
          </AbsoluteFill>
        </Sequence>
      ))}
      {/* ③ 자막 — 기본 잉크, 오버레이 구간 흰색 */}
      <CaptionLayer captions={captions} overlays={overlays} />
      {/* ④ 나레이션 오디오 — 영상 길이의 기준(calculateMetadata) */}
      <Audio src={staticFile('job/narration.m4a')} />
    </AbsoluteFill>
  );
};
