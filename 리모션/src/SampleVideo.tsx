import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {COLORS, FONT_STACK, MONO_STACK} from './design';
import {Timeline, slideAt} from './timeline';

// ── 동기화 데모용 타임라인 (실전에서는 결과물/<작업>/타임라인.json의 slides를 그대로 주입) ──
export const SAMPLE_TIMELINE: Timeline = {
  type: 'main',
  duration: 12,
  slides: [
    {id: 'S01', index: 0, start: 0, end: 4, label: '타이틀'},
    {id: 'S02', index: 1, start: 4, end: 8, label: 'KPI 카운터'},
    {
      id: 'S03',
      index: 2,
      start: 8,
      end: 12,
      label: '비교 바',
      stages: [{stage: 1, start: 10}],
    },
  ],
};

// CSS 트랜지션 대체: 프레임 기반 등장 (el + --i 스태거에 해당) — 순수 함수, 훅 아님
const enterStyle = (localT: number, index: number, durationSec = 0.45) => {
  const t = Math.max(0, localT - index * 0.08); // 스태거 80ms
  const p = Math.min(1, t / durationSec);
  const eased = 1 - (1 - p) ** 3; // ease-out
  return {opacity: eased, transform: `translateY(${(1 - eased) * 16}px)`};
};

const Slide: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill
    style={{
      backgroundColor: COLORS.bg,
      fontFamily: FONT_STACK,
      alignItems: 'center',
      justifyContent: 'center',
      paddingBottom: 230, // 자막 안전 영역 (CAPTION_SAFE_AREA.md)
    }}
  >
    {children}
  </AbsoluteFill>
);

const TitleSlide: React.FC<{localT: number}> = ({localT}) => (
  <Slide>
    <div style={{textAlign: 'center'}}>
      <p
        style={{
          ...enterStyle(localT, 0),
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: '0.2em',
          color: COLORS.accentText,
          backgroundColor: 'rgba(245,158,11,0.10)',
          display: 'inline-block',
          padding: '8px 20px',
          borderRadius: 4,
        }}
      >
        PULLING · REMOTION 데모
      </p>
      <h1
        style={{
          ...enterStyle(localT, 1),
          fontSize: 96,
          fontWeight: 900,
          letterSpacing: '-0.03em',
          color: COLORS.ink,
          margin: '24px 0 0',
        }}
      >
        타임라인 동기화 테스트<span style={{color: COLORS.accent}}>.</span>
      </h1>
    </div>
  </Slide>
);

const CounterSlide: React.FC<{localT: number}> = ({localT}) => {
  const p = Math.min(1, Math.max(0, (localT - 0.3) / 1.2));
  const eased = 1 - (1 - p) ** 3;
  const value = Math.round(eased * 378);
  return (
    <Slide>
      <div style={{textAlign: 'center'}}>
        <p
          style={{
            ...enterStyle(localT, 0),
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: '0.1em',
            color: COLORS.meta,
          }}
        >
          캡처 길이
        </p>
        <p
          style={{
            ...enterStyle(localT, 1),
            fontSize: 180,
            fontWeight: 900,
            fontFamily: MONO_STACK,
            fontVariantNumeric: 'tabular-nums',
            color: COLORS.accent,
            margin: 0,
          }}
        >
          {value}
          <span style={{fontSize: 64, color: COLORS.inkSub}}>초</span>
        </p>
      </div>
    </Slide>
  );
};

const BAR_ROWS = [
  {label: 'HTML 캡처', value: 0.95, color: COLORS.ink},
  {label: 'Remotion', value: 0.6, color: COLORS.accent},
] as const;

const CompareSlide: React.FC<{localT: number; stage: number}> = ({localT, stage}) => (
  <Slide>
    <div style={{width: 1200}}>
      {BAR_ROWS.map((row, i) => {
        const p = Math.min(1, Math.max(0, (localT - 0.3 - i * 0.25) / 0.9));
        const eased = 1 - (1 - p) ** 3;
        return (
          <div
            key={row.label}
            style={{
              ...enterStyle(localT, i),
              display: 'flex',
              alignItems: 'center',
              gap: 32,
              marginBottom: 40,
            }}
          >
            <p style={{width: 280, textAlign: 'right', fontSize: 40, fontWeight: 700, color: COLORS.ink, margin: 0}}>
              {row.label}
            </p>
            <div style={{flex: 1, height: 64, borderRadius: 999, backgroundColor: COLORS.track}}>
              <div
                style={{
                  width: `${eased * row.value * 100}%`,
                  height: '100%',
                  borderRadius: 999,
                  backgroundColor: row.color,
                }}
              />
            </div>
          </div>
        );
      })}
      {/* 스테이지 시스템 데모: 타임라인.json stages[].start(=10s)에 결론 등장 */}
      <p
        style={{
          opacity: stage >= 1 ? 1 : 0,
          fontSize: 36,
          fontWeight: 700,
          color: COLORS.green,
          textAlign: 'center',
          margin: '24px 0 0',
        }}
      >
        ✓ 스테이지 전환도 타임라인 기준으로 동작
      </p>
    </div>
  </Slide>
);

export const SampleVideo: React.FC<{timeline: Timeline}> = ({timeline}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps; // 프레임 → 오디오 초 (t=0 = 음성 시작, 싱크 계약과 동일)
  const cur = slideAt(timeline, t);
  if (!cur) {
    return <AbsoluteFill style={{backgroundColor: COLORS.bg}} />;
  }
  // 슬라이드 전환: 첫 0.3초 페이드 인 (capture 모드의 즉시 전환과 달리 옵션)
  const fade = interpolate(cur.localT, [0, 0.3], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{backgroundColor: COLORS.bg, opacity: fade}}>
      {cur.slide.index === 0 && <TitleSlide localT={cur.localT} />}
      {cur.slide.index === 1 && <CounterSlide localT={cur.localT} />}
      {cur.slide.index === 2 && <CompareSlide localT={cur.localT} stage={cur.stage} />}
    </AbsoluteFill>
  );
};
