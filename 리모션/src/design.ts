// design.md(SSOT) §2-3 영상 소스 표준 색상 — 값 변경은 design.md에서만
export const COLORS = {
  bg: '#ffffff',
  surface: '#f7f6f4',
  track: '#efeeea',
  ink: '#141413',
  inkSub: '#5e5d59',
  meta: '#a39e98',
  accent: '#F59E0B', // 주 강조 (그래픽·큰 숫자)
  accentText: '#D97706', // 주 강조 (작은 텍스트)
  green: '#16a34a', // 보조 강조 (성공/체크/2번째 시리즈)
  border: 'rgba(20,20,19,0.08)',
  borderStrong: 'rgba(20,20,19,0.14)',
} as const;

export const FONT_STACK =
  "'Pretendard', 'Noto Sans KR', system-ui, -apple-system, sans-serif";
export const MONO_STACK =
  "'JetBrains Mono', 'Fira Code', 'Consolas', monospace";
