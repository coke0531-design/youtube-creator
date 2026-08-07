// 타임라인.json(기계용 동기화 데이터)과 동일한 스키마 — 싱크 계약의 Remotion 측 표현.
// t=0 = 오디오 0초. start/end는 transcript.json(실제 발화) 기준 초 단위.

export type StageEntry = {
  stage: number;
  start: number;
};

export type SlideEntry = {
  id: string;
  index: number;
  start: number;
  end: number;
  label: string;
  stages?: StageEntry[];
};

export type Timeline = {
  type: 'main' | 'short';
  duration: number;
  slides: SlideEntry[];
};

/** 현재 프레임(초)이 속한 슬라이드와, 그 슬라이드 안에서의 경과 시간(초)을 돌려준다. */
export const slideAt = (
  timeline: Timeline,
  t: number,
): {slide: SlideEntry; localT: number; stage: number} | null => {
  const slide = timeline.slides.find((s) => t >= s.start && t < s.end);
  if (!slide) {
    return null;
  }
  let stage = 0;
  for (const st of slide.stages ?? []) {
    if (t >= st.start) {
      stage = st.stage;
    }
  }
  return {slide, localT: t - slide.start, stage};
};
