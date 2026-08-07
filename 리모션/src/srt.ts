// SRT 파서 — 의존성 없이 직접 구현. UTF-8, 밀리초 콤마(또는 점) 표기.
// assemble_capcut.py read_srt / split_captions.py parse_srt 와 동일한 계약:
//   한 블록 = 번호줄 + "시작 --> 끝" + 텍스트(여러 줄이면 공백 1개로 합침).
// t=0 = 오디오 0초 (싱크 계약과 동일).

export type Caption = {start: number; end: number; text: string};

// 00:00:01,500 --> 00:00:05,200 (밀리초는 , 또는 . 허용, 1~3자리)
const TIME_RE =
  /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/;

const toSeconds = (h: string, m: string, s: string, ms: string): number =>
  parseInt(h, 10) * 3600 +
  parseInt(m, 10) * 60 +
  parseInt(s, 10) +
  parseInt(ms.padEnd(3, '0'), 10) / 1000;

export const parseSrt = (raw: string): Caption[] => {
  const clean = raw
    .replace(/^﻿/, '') // BOM 제거
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n');
  const captions: Caption[] = [];
  for (const block of clean.trim().split(/\n\s*\n/)) {
    const lines = block.split('\n');
    const idx = lines.findIndex((l) => TIME_RE.test(l));
    if (idx === -1) {
      continue;
    }
    const m = TIME_RE.exec(lines[idx]);
    if (!m) {
      continue;
    }
    const start = toSeconds(m[1], m[2], m[3], m[4]);
    const end = toSeconds(m[5], m[6], m[7], m[8]);
    const text = lines
      .slice(idx + 1)
      .map((l) => l.trim())
      .filter(Boolean)
      .join(' ');
    if (text) {
      captions.push({start, end, text});
    }
  }
  return captions;
};
