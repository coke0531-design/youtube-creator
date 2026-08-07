import React from 'react';
import {Composition, staticFile} from 'remotion';
import {getAudioDurationInSeconds} from '@remotion/media-utils';
import {SAMPLE_TIMELINE, SampleVideo} from './SampleVideo';
import {FinalVideo, FinalProps, FPS as FINAL_FPS} from './FinalVideo';
import {parseSrt} from './srt';

const FPS = 30;

export const Root: React.FC = () => (
  <>
    <Composition
      id="Main"
      component={SampleVideo}
      width={1920}
      height={1080}
      fps={FPS}
      defaultProps={{timeline: SAMPLE_TIMELINE}}
      // 타임라인.json의 duration이 곧 영상 길이 — 싱크 계약(t=0=음성 시작) 유지
      calculateMetadata={({props}) => ({
        durationInFrames: Math.ceil(props.timeline.duration * FPS),
      })}
    />
    {/* 완성본 렌더(opt-in) — scripts/render_final.py가 public/job/ 스테이징 후 호출 */}
    <Composition
      id="Final"
      component={FinalVideo}
      width={1920}
      height={1080}
      fps={FINAL_FPS}
      defaultProps={{captions: [], overlays: []} as FinalProps}
      // 영상 길이 = 나레이션 오디오 길이. full.srt·타임라인.json은 fetch로 읽어 props에 주입.
      calculateMetadata={async () => {
        const [srtText, timelineText, durationSec] = await Promise.all([
          fetch(staticFile('job/full.srt')).then((r) => r.text()),
          fetch(staticFile('job/timeline.json')).then((r) => r.text()),
          getAudioDurationInSeconds(staticFile('job/narration.m4a')),
        ]);
        const tl = JSON.parse(timelineText) as {
          video_overlays?: {n: number; start: number; end: number}[];
        };
        const overlays = (tl.video_overlays ?? []).map((o) => ({
          n: o.n,
          start: o.start,
          end: o.end,
        }));
        return {
          durationInFrames: Math.ceil(durationSec * FINAL_FPS),
          props: {captions: parseSrt(srtText), overlays},
        };
      }}
    />
  </>
);
