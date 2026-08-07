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
// 자막 규칙은 assemble_capcut.py를 그대로 미러링한다:
//   기본색 = 잉크 #141413 (흰 배경 슬라이드), 오버레이가 떠 있는 구간만 흰색 #ffffff.
//   하단 배치 = CAPTION_SAFE_AREA.md "하단에서 약 162px" (CAPTION_Y main=-0.70 환산).

export const FPS = 30;

export type Overlay = {n: number; start: number; end: number};

export type FinalProps = {
  captions: Caption[];
  overlays: Overlay[];
};

// CAPTION_Y["main"] = -0.70 → 하단거리 = (1 + (-0.70)) × (1080/2) = 162px (자막 세로 '중심')
const CAPTION_CENTER_FROM_BOTTOM = 162;
const CAPTION_INK = COLORS.ink; // #141413 (기본 잉크)
const CAPTION_WHITE = '#ffffff'; // 오버레이(실사 영상) 구간

const overlayActiveAt = (overlays: Overlay[], t: number): boolean =>
  overlays.some((o) => t >= o.start && t < o.end);

const CaptionLayer: React.FC<FinalProps> = ({captions, overlays}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps; // 프레임 → 오디오 초 (t=0 = 음성 시작)
  const cur = captions.find((c) => t >= c.start && t < c.end);
  if (!cur) {
    return null;
  }
  const color = overlayActiveAt(overlays, t) ? CAPTION_WHITE : CAPTION_INK;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: CAPTION_CENTER_FROM_BOTTOM,
        transform: 'translateY(50%)', // bottom 기준선을 자막 '중심'이 162px에 오도록 보정
        display: 'flex',
        justifyContent: 'center',
        padding: '0 160px',
      }}
    >
      <span
        style={{
          fontFamily: FONT_STACK,
          fontWeight: 900, // CAPTION_SAFE_AREA.md: Black/ExtraBold
          fontSize: 60, // 1080p 기준 56px 이상
          lineHeight: 1.25,
          color,
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
