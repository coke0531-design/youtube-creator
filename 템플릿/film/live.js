/* live.js — 실사 프레임(JPEG 시퀀스) 공용 로더 (2026-09-30, G 실사 소스 삽입 시안)
 * 영상 요소(<video>) 금지 → 미리 뽑은 프레임 JPEG를 Image로 불러 그린다. 결정론 계약:
 *   seek(t)는 async. 그리기 전에 필요한 프레임을 전부 await(decode 포함)하고, 그리기는 동기로 한다.
 *   LIVE.peek()가 못 찾은 프레임이 있으면 LIVE.misses에 쌓이고, LIVE.render()가 그것을 불러 다시 그린다(그리기는 t의 순수 함수라 결과 동일).
 * API
 *   LIVE.N                       세트별 프레임 수(실측: s123 933, cc 179, gpt 179)
 *   LIVE.idx(set, t, t0)         = min(N-1, max(0, floor((t - t0) * 30 + 1e-6)))
 *   LIVE.get(set, idx) → Promise<Image>   (decode 완료, 캐시 Map LRU 60장)
 *   LIVE.peek(set, idx) → Image|null      (동기, 이미 불러온 것만)
 *   LIVE.draw(ctx, img, R, o)    R = {x,y,w,h} 중심 좌표. 둥근 모서리 r(기본 26) 클립 + 잉크 테두리 lw(기본 4). 이미지는 R을 덮게(cover) — 16:9 R이면 꽉 채움
 *   LIVE.render(need, drawFn)    need = [[set, idx], …] 를 await → drawFn() 동기 실행 → 못 찾은 프레임이 있으면 불러 다시 drawFn()
 * 경로: 실사프레임/<set>/<idx+1 네 자리>.jpg (상대 경로, ffmpeg %04d 는 1부터) */
(function () {
  const N = { s123: 933, cc: 179, gpt: 179 };
  const CAP = 60, FPS = 30;
  const cache = new Map();          // key → {img, p}
  const misses = [];
  let gen = 0;
  const key = (set, i) => set + '/' + i;
  const clampIdx = (set, i) => Math.min(N[set] - 1, Math.max(0, i | 0));
  function url(set, i) { return '실사프레임/' + set + '/' + String(i + 1).padStart(4, '0') + '.jpg'; }
  function touch(k, v) { cache.delete(k); cache.set(k, v); while (cache.size > CAP) cache.delete(cache.keys().next().value); }
  function get(set, i) {
    i = clampIdx(set, i); const k = key(set, i), hit = cache.get(k);
    if (hit) { touch(k, hit); return hit.p; }
    const img = new Image(); img.decoding = 'sync';
    const v = { img, ok: false, p: null };
    v.p = new Promise((res, rej) => { img.onload = () => res(); img.onerror = () => rej(new Error('실사 프레임 없음: ' + url(set, i))); img.src = url(set, i); })
      .then(() => img.decode().catch(() => { })).then(() => { v.ok = true; return img; });
    touch(k, v); return v.p;
  }
  function peek(set, i) {
    i = clampIdx(set, i); const v = cache.get(key(set, i));
    if (v && v.ok) { touch(key(set, i), v); return v.img; }
    misses.push([set, i]); return null;
  }
  function idx(set, t, t0) { return Math.min(N[set] - 1, Math.max(0, Math.floor((t - t0) * FPS + 1e-6))); }
  function draw(ctx, img, R, o = {}) {
    const r = o.r == null ? 26 : o.r, lw = o.lw == null ? 4 : o.lw, a = o.alpha == null ? 1 : o.alpha;
    if (a <= 0 || R.w <= 0 || R.h <= 0) return;
    const x = R.x - R.w / 2, y = R.y - R.h / 2;
    ctx.save(); ctx.globalAlpha *= a;
    KIT.rr(ctx, x, y, R.w, R.h, r); ctx.save(); ctx.clip();
    if (img) {
      const s = Math.max(R.w / img.naturalWidth, R.h / img.naturalHeight), dw = img.naturalWidth * s, dh = img.naturalHeight * s;
      ctx.drawImage(img, R.x - dw / 2, R.y - dh / 2, dw, dh);
    } else { ctx.fillStyle = '#FF00FF'; ctx.fillRect(x, y, R.w, R.h); }   // 못 불러온 프레임 = 눈에 띄게(결정론 검사가 잡는다)
    ctx.restore();
    if (lw > 0) { KIT.rr(ctx, x, y, R.w, R.h, r); ctx.strokeStyle = KIT.C.ink; ctx.lineWidth = lw; ctx.lineJoin = 'round'; ctx.stroke(); }
    ctx.restore();
  }
  async function render(need, drawFn) {
    const my = ++gen;
    await Promise.all(need.map(([s, i]) => get(s, i)));
    for (let tries = 0; tries < 4; tries++) {
      if (my !== gen) return;                       // 더 나중 seek가 시작됐으면 그리지 않는다
      misses.length = 0; drawFn();
      if (!misses.length) return;
      const m = misses.splice(0); await Promise.all(m.map(([s, i]) => get(s, i)));
    }
  }
  window.LIVE = { N, FPS, idx, get, peek, draw, render, url, misses };
})();
