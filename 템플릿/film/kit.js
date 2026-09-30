/* kit.js — 정본 킷 v3.2 (2026-09-30). KIT.VERSION = '3.2.0'. 모든 본편 필름의 SSOT(복사해 쓰되 수정 금지, 영상 전용 그리기는 kit_ext.js).
 * 기준 = G r2 kit.js(오너 "완벽" 판정본, 2026-09-29 킷 담당) + H 흡수분(character pose 'hold'·tint 'gray', person()·crowd()).
 * 규격 문서 = .claude/skills/youtube-editor/킷-규격.md. 일관성 검사 = scripts/film/kit_check.py(갤러리 골든 비교 + 작업 폴더 스캔).
 * 전역 window.KIT. 모든 그리기 함수는 상태가 없다(인자만으로 그린다). Math.random·타이머·rAF·CSS 애니메이션 없음.
 * 좌표계: 캔버스 1920x1080 픽셀. 도형 함수의 x,y는 "중심"(예외: rr·bar = 왼쪽 위/왼쪽 끝, line·strike·arrow = 점 좌표, character·troop = 발 밑 중앙).
 * 하단 200px(y > 880)은 자막 자리 = 무대에서도 카드 안(카드 로컬 좌표)에서도 아무것도 그리지 않는다.
 * 그리기 함수는 ctx.setTransform을 부르지 않는다(카메라·카드 줌 안에서 그대로 쓰기 위해). 예외: BASE·cardFull·screen.
 * 출처: P1 = C세트 애프터 v3.1 film.html(캐릭터·카드·체크리스트·도장) + B세트 애프터 v3 film.html(군단·시계·온도계·갈림길·레일, 흔들림 제거)
 *       P2 = E 본편 애프터 v3.1 kit.js(카드·토큰·커서·입력창·타이핑·게이지·스위치·칩·이징) — 회백 캔버스 대신 P1 팔레트 위 흰 카드.
 */
(function () {
  'use strict';
  const W = 1920, H = 1080, SAFE = 880, GROUND = 800;
  // ---------------- 팔레트(P1 하나) ----------------
  const C = { paper: '#F7F3EA', ink: '#141413', amber: '#F59E0B', amberD: '#D97706', green: '#16a34a', white: '#FFFFFF' };
  const G = a => `rgba(20,20,19,${a})`; // 회색 = 잉크의 투명도(팔레트 밖 색 없음)
  const SHADOW = { color: 'rgba(20,20,19,0.14)', blur: 30, y: 10 };

  // ---------------- 이징(닫힌 식) ----------------
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  const pr = (t, a, b) => clamp((t - a) / (b - a));
  const easeOut = p => 1 - Math.pow(1 - clamp(p), 3);
  const easeIn = p => { p = clamp(p); return p * p * p; };
  const easeInOut = p => { p = clamp(p); return p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
  const spring = p => { p = clamp(p); if (p >= 1) return 1; const a = 7, wd = 5; return 1 - Math.exp(-a * p) * (Math.cos(wd * p) + (a / wd) * Math.sin(wd * p)); };
  // 키프레임 [[t, v1, v2...], ...] 사이 easeInOut 보간. 같은 값 두 키 = 정지
  function kf(t, keys, ease = easeInOut) {
    if (t <= keys[0][0]) return keys[0].slice(1);
    for (let i = 1; i < keys.length; i++) {
      if (t < keys[i][0]) { const a = keys[i - 1], b = keys[i]; const p = ease((t - a[0]) / (b[0] - a[0])); return a.slice(1).map((v, j) => lerp(v, b[j + 1], p)); }
    }
    return keys[keys.length - 1].slice(1);
  }
  const BEAT = 0.5;                                  // 120BPM 한 박
  const snap = t => Math.round(t / BEAT) * BEAT;
  const hop = (t, t0, d = 0.45, h = 60) => { const p = pr(t, t0, t0 + d); return (p > 0 && p < 1) ? Math.sin(Math.PI * p) * h : 0; }; // 점프 높이(닫힌 식)
  function lerpRect(a, b, p) { const o = {}; for (const k of Object.keys(a)) o[k] = (typeof a[k] === 'number' && typeof b[k] === 'number') ? lerp(a[k], b[k], p) : (p < .5 ? a[k] : b[k]); return o; }

  // ---------------- 글꼴 ----------------
  const WMAP = w => (w >= 800 ? 800 : w >= 650 ? 700 : 500); // 굵기 3단
  const F = (w, s) => `${WMAP(w)} ${s}px P, 'Malgun Gothic', sans-serif`;
  let _ready = null;
  function ready() {
    if (_ready) return _ready;
    _ready = (async () => {
      const faces = [[500, 'Medium'], [700, 'Bold'], [800, 'ExtraBold']];
      let ok = 0;
      for (const [w, n] of faces) {
        try { const f = new FontFace('P', `url('file:///C:/Windows/Fonts/Pretendard-${n}.otf')`, { weight: String(w) }); await f.load(); document.fonts.add(f); ok++; } catch (e) { /* 폴백 Malgun Gothic */ }
      }
      try { await document.fonts.ready; } catch (e) { }
      KIT.fontFamily = ok === 3 ? 'Pretendard' : 'Malgun Gothic';
      return KIT.fontFamily;
    })();
    return _ready;
  }

  // ---------------- 기본 도구 ----------------
  function rr(ctx, x, y, w, h, r) { // 왼쪽 위 기준 둥근 사각 경로
    r = Math.max(0, Math.min(r, w / 2, h / 2)); ctx.beginPath(); ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function text(ctx, s, x, y, o = {}) {
    const { size = 40, weight = 700, color = C.ink, align = 'center', alpha = 1, baseline = 'middle' } = o;
    if (alpha <= 0 || s === '' || s == null) return;
    ctx.save(); ctx.globalAlpha *= alpha; ctx.font = F(weight, size); ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = baseline; ctx.fillText(s, x, y); ctx.restore();
  }
  function tw(ctx, s, size, weight = 700) { ctx.save(); ctx.font = F(weight, size); const v = ctx.measureText(s).width; ctx.restore(); return v; }
  // 꺾은선을 p(0~1)만큼만 긋는다(draw-on). 곧은 선, 끝만 둥글게
  function line(ctx, pts, p = 1, o = {}) {
    const { lw = 8, color = C.ink, alpha = 1, dash = null } = o;
    if (p <= 0 || alpha <= 0 || pts.length < 2) return;
    const L = [0]; for (let i = 1; i < pts.length; i++) L.push(L[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    const tg = L[L.length - 1] * clamp(p);
    ctx.save(); ctx.globalAlpha *= alpha; if (dash) ctx.setLineDash(dash); ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) {
      if (L[i] <= tg) ctx.lineTo(pts[i][0], pts[i][1]);
      else { const u = (tg - L[i - 1]) / ((L[i] - L[i - 1]) || 1); ctx.lineTo(lerp(pts[i - 1][0], pts[i][0], u), lerp(pts[i - 1][1], pts[i][1], u)); break; }
    }
    ctx.stroke(); ctx.restore();
  }
  function rrPts(x, y, w, h, r) { // 둥근 사각 둘레 점(왼쪽 위 기준) — line()으로 윤곽 draw-on
    const p = []; const seg = (cx, cy, a0) => { for (let k = 0; k <= 6; k++) { const a = a0 + k / 6 * Math.PI / 2; p.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); } };
    p.push([x + r, y]); seg(x + w - r, y + r, -Math.PI / 2); seg(x + w - r, y + h - r, 0); seg(x + r, y + h - r, Math.PI / 2); seg(x + r, y + r, Math.PI); return p;
  }
  function circleP(ctx, o) { // 원 둘레를 p만큼
    const { x, y, r, p = 1, lw = 6, color = C.ink, alpha = 1, dash = false } = o;
    if (p <= 0 || alpha <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha; if (dash) ctx.setLineDash([16, 12]); ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clamp(p)); ctx.stroke(); ctx.restore();
  }
  function bar(ctx, x, y, w, h, color, alpha = 1) { // 왼쪽 끝 x, 세로 중심 y의 알약 막대
    if (w <= 0 || alpha <= 0) return; ctx.save(); ctx.globalAlpha *= alpha; rr(ctx, x, y - h / 2, w, h, h / 2); ctx.fillStyle = color; ctx.fill(); ctx.restore();
  }
  // 빗금(장치 2: 이전·부족 상태). clip = 경로를 만드는 함수
  function hatch(ctx, clip, o = {}) {
    const { color = C.ink, alpha = .55, step = 18, lw = 4 } = o; if (alpha <= 0) return;
    ctx.save(); ctx.beginPath(); clip(); ctx.clip(); ctx.strokeStyle = color; ctx.globalAlpha *= alpha; ctx.lineWidth = lw;
    for (let k = -120; k <= 120; k++) { ctx.beginPath(); ctx.moveTo(k * step - 600, -200); ctx.lineTo(k * step + 700, 1300); ctx.stroke(); }
    ctx.restore();
  }
  function hatchRect(ctx, x, y, w, h, o = {}) { // 왼쪽 위 기준
    const { alpha = 1, color = C.ink, border = true } = o; if (w <= 0 || h <= 0 || alpha <= 0) return;
    hatch(ctx, () => ctx.rect(x, y, w, h), { color, alpha: .55 * alpha });
    if (border) { ctx.save(); ctx.globalAlpha *= alpha; ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.strokeRect(x, y, w, h); ctx.restore(); }
  }

  // ---------------- 무대 ----------------
  // 종이 그레인 6%: 시드 고정 LCG로 한 번만 만든다(시간 무관). 카드가 그 위를 덮으므로 그레인은 카드 밖에만 보인다
  let _grain = null;
  function grain() {
    if (_grain) return _grain;
    _grain = document.createElement('canvas'); _grain.width = W; _grain.height = H;
    const g = _grain.getContext('2d'); const id = g.createImageData(W, H); let s = 20260929;
    for (let i = 0; i < W * H; i++) { s = (Math.imul(s, 1103515245) + 12345) >>> 0; const v = (s >>> 16) & 255; id.data[i * 4] = v; id.data[i * 4 + 1] = v; id.data[i * 4 + 2] = v; id.data[i * 4 + 3] = 255; }
    g.putImageData(id, 0, 0); return _grain;
  }
  function BASE(ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = C.paper; ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 0.06; ctx.drawImage(grain(), 0, 0); ctx.globalAlpha = 1;
  }
  function screen(ctx) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; }
  function clipSafe(ctx) { ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, SAFE); ctx.clip(); } // 짝: ctx.restore()
  // P1 카메라(무대 줌·팬): 월드 점 (cx,cy)가 화면 (960,440)에 오고 z배
  function camApply(ctx, cam) { const { cx = 960, cy = 440, z = 1 } = cam; ctx.setTransform(z, 0, 0, z, 960 - cx * z, 440 - cy * z); }
  function groundLine(ctx, o = {}) { const { p = 1, alpha = 1, x0 = 60, x1 = 1860, y = GROUND } = o; line(ctx, [[x0, y], [x1, y]], p, { lw: 5, color: C.ink, alpha: .7 * alpha }); }

  // ================= P1 세트 =================
  // 주인공 ①: 별표 얼굴 8비트 캐릭터(클로드 별표를 몸으로). 13x15 픽셀 격자, h = 전체 높이(≥ 270)
  const STAR = ['......X......', '..X...X...X..', '...X..X..X...', '....XXXXX....', '.X.XXXXXXX.X.', '..XXXXXXXXX..', 'XXXXXXXXXXXXX', '..XXXXXXXXX..', '.X.XXXXXXX.X.', '....XXXXX....', '...X..X..X...', '..X...X...X..', '......X......'];
  function starPixels(ctx, ox, oy, ps, col) { ctx.fillStyle = col; for (let r = 0; r < 13; r++) for (let c = 0; c < 13; c++) if (STAR[r][c] === 'X') ctx.fillRect(ox + c * ps, oy + r * ps, ps + .6, ps + .6); }
  // 눈(표정 3종). face: 'base'(세로 막대) | 'focus'(가로 막대, 집중) | 'surprise'(큰 네모, 놀람)
  function eyes(ctx, ox, oy, ps, face, col) {
    ctx.fillStyle = col;
    if (face === 'focus') { ctx.fillRect(ox + 3.5 * ps, oy + 6 * ps, 2 * ps, ps); ctx.fillRect(ox + 7.5 * ps, oy + 6 * ps, 2 * ps, ps); }
    else if (face === 'surprise') { ctx.fillRect(ox + 3.5 * ps, oy + 4.5 * ps, 2 * ps, 2 * ps); ctx.fillRect(ox + 7.5 * ps, oy + 4.5 * ps, 2 * ps, 2 * ps); }
    else { ctx.fillRect(ox + 4 * ps, oy + 5 * ps, ps, 2 * ps); ctx.fillRect(ox + 8 * ps, oy + 5 * ps, ps, 2 * ps); }
  }
  /* character(ctx,{x,y,h,face,pose,flip,walk,tilt,reach,jump,alpha,silhouette,tint})
   * x,y = 발 밑 중앙(보통 y = KIT.GROUND). h 기본 300(≥ 270 강제, 군단 복제는 troop이 minH를 낮춘다)
   * pose: 'stand' | 'walk'(walk = 걸음 위상 숫자, 보통 t) | 'tilt'(갸우뚱 -0.13rad) | 'reach'(팔 뻗기, reach 0~1) | 'cheer'(두 팔 위)
   *       | 'hold'(두 팔 앞으로: 카드·서류를 든 자세, H 흡수 v3.2)
   * flip = 좌우 반전(왼쪽 보기). silhouette = 잉크 16% 실루엣(군단 뒷배경). tint 'amber'(기본) | 'gray'(잉크 38% 몸 = 휩쓸리던 나·꺼진 나, H 흡수 v3.2)
   * 돌려주는 값: {x, top, w, h, headY} */
  function character(ctx, o) {
    const { x, y = GROUND, face = 'base', pose = 'stand', flip = false, walk = 0, reach = 0, jump = 0, alpha = 1, silhouette = false, minH = 270, tint = 'amber' } = o;
    const h = Math.max(minH, o.h || 300); if (alpha <= 0) return null;
    const ps = h / 15, ox = -6.5 * ps, oy = -15 * ps;
    const body = silhouette ? G(.16) : tint === 'gray' ? G(.38) : C.amber, eye = silhouette ? 'rgba(0,0,0,0)' : C.ink, leg = silhouette ? G(.16) : C.ink;
    ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y - jump); if (flip) ctx.scale(-1, 1);
    const tilt = o.tilt != null ? o.tilt : pose === 'tilt' ? -0.13 : 0; if (tilt) { ctx.translate(0, -7 * ps); ctx.rotate(tilt); ctx.translate(0, 7 * ps); }
    starPixels(ctx, ox, oy, ps, body);
    if (pose === 'reach' && reach > 0) { ctx.fillStyle = body; ctx.fillRect(ox + 12 * ps, oy + 6 * ps, reach * ps * 3.2, ps); ctx.fillRect(ox + 12 * ps + reach * ps * 3.2 - ps * .3, oy + 5 * ps, ps * 1.2, ps * 1.2); }
    if (pose === 'cheer') { ctx.fillStyle = body; ctx.fillRect(ox - ps, oy + 1 * ps, ps, 4 * ps); ctx.fillRect(ox + 13 * ps, oy + 1 * ps, ps, 4 * ps); }
    if (pose === 'hold') { ctx.fillStyle = body; ctx.fillRect(ox + 11 * ps, oy + 7 * ps, 2.6 * ps, 1.1 * ps); ctx.fillRect(ox + 13 * ps, oy + 6.2 * ps, 1.1 * ps, 1.9 * ps); } // H 흡수: 별 6행에 붙은 앞팔 + 손
    if (!silhouette) eyes(ctx, ox, oy, ps, face, eye);
    const l = pose === 'walk' ? (Math.floor(walk * 5) % 2) : 0;
    ctx.fillStyle = leg; ctx.fillRect(ox + (5 - l * .6) * ps, oy + 13 * ps, ps, 2 * ps); ctx.fillRect(ox + (7 + l * .6) * ps, oy + 13 * ps, ps, 2 * ps);
    ctx.restore();
    return { x, top: y - jump - h, w: 13 * ps, h, headY: y - jump - h + 6.5 * ps };
  }
  /* troop(ctx,{xs | x0,x1,n, y, h, face, pose, walk, silhouette, alpha, faces:[...], jumps:[...], alphas:[...]})
   * 같은 캐릭터 n명 복제(기본 6). 군단원 키는 h(기본 220, 최소 160 — 주인공 1명만 ≥ 270 규칙).
   * 개별 값 배열(faces·jumps·alphas·poses)을 주면 사람마다 다르게. 돌려주는 값: 각자의 character 결과 배열 */
  function troop(ctx, o) {
    const { n = 6, y = GROUND, h = 220, face = 'base', pose = 'stand', walk = 0, silhouette = false, alpha = 1 } = o;
    const xs = o.xs || Array.from({ length: n }, (_, i) => lerp(o.x0 != null ? o.x0 : 500, o.x1 != null ? o.x1 : 1700, n === 1 ? .5 : i / (n - 1)));
    return xs.map((x, i) => character(ctx, {
      x, y: o.ys ? o.ys[i] : y, h, minH: 160, face: o.faces ? o.faces[i] : face, pose: o.poses ? o.poses[i] : pose, walk: walk + i * .37,
      jump: o.jumps ? o.jumps[i] : 0, silhouette, alpha: alpha * (o.alphas ? o.alphas[i] : 1), flip: o.flips ? o.flips[i] : false,
    }));
  }
  // 사람 실루엣 1명(머리 원 + 어깨 몸통, H 흡수 v3.2). y = 발바닥, h ≥ 120. state 'on'(회색) | 'off'(흐려진 빈자리 점선) | 'amber' | 'ink'
  // 주인공이 아닌 "사람들"(시장·경쟁자·청중) 전용. 주인공·군단은 character/troop만 쓴다
  function person(ctx, o) {
    const { x, y = GROUND, state = 'on', alpha = 1 } = o; const h = Math.max(120, o.h || 150);
    if (alpha <= 0) return; const hr = h * .17, hy = y - h + hr, sh = y - h * .6, bw = h * .30;
    ctx.save(); ctx.globalAlpha *= alpha;
    const path = () => { ctx.beginPath(); ctx.arc(x, hy, hr, 0, Math.PI * 2); ctx.moveTo(x - bw, y); ctx.lineTo(x - bw, sh + bw * .7); ctx.quadraticCurveTo(x - bw, sh, x, sh); ctx.quadraticCurveTo(x + bw, sh, x + bw, sh + bw * .7); ctx.lineTo(x + bw, y); ctx.closePath(); };
    if (state === 'off') { path(); ctx.fillStyle = G(.05); ctx.fill(); ctx.setLineDash([10, 9]); ctx.lineWidth = 4; ctx.strokeStyle = G(.3); ctx.stroke(); }
    else { path(); ctx.fillStyle = state === 'amber' ? C.amber : state === 'ink' ? C.ink : G(.42); ctx.fill(); }
    ctx.restore();
  }
  /* crowd(ctx,{x,y,n,h,gap,xs,gray:[i..],amber:[i..],hide:[i..],move:{i:[dx,dy,alpha]},scale,alpha}) — H 흡수 v3.2
   * 회색 사람 무리 한 줄. 가운데 x, 발바닥 y(기본 GROUND). gray = 흐려져 빈자리가 된 사람(장치 2·15), amber = 강조, hide = 안 그림.
   * move = 한 사람만 밀려나거나 빠져나가는 연출(dx,dy 픽셀, alpha). 돌려주는 값: 각 사람의 {x,y,h} */
  function crowd(ctx, o = {}) {
    const { x = 960, y = GROUND, n = 5, gray = [], amber = [], hide = [], move = {}, alpha = 1, scale = 1 } = o;
    const h = Math.max(120, (o.h || 150) * scale), gap = o.gap || h * .72;
    const xs = o.xs || Array.from({ length: n }, (_, i) => x + (i - (n - 1) / 2) * gap);
    const out = [];
    xs.forEach((px, i) => {
      const m = move[i] || [0, 0, 1]; const pos = { x: px + m[0], y: y + m[1], h };
      out.push(pos); if (hide.includes(i)) return;
      person(ctx, { x: pos.x, y: pos.y, h, state: gray.includes(i) ? 'off' : amber.includes(i) ? 'amber' : 'on', alpha: alpha * (m[2] == null ? 1 : m[2]) });
    });
    return out;
  }
  /* 주인공 ③: 서류 카드(작업 카드, 앰버 모서리). paperCard(ctx,{x,y,w,h,lines,n,rot,scale,alpha,border,fill,label,labelSize,cornerP})
   * lines 0~1 = 줄이 차례로 그어짐, n = 줄 수. label = 카드 위쪽 글자(≥ 36px). cornerP = 앰버 모서리 표시(0~1) */
  function paperCard(ctx, o) {
    const { x, y, w = 360, h = 440, lines = 1, n = 4, rot = 0, scale = 1, alpha = 1, border = C.ink, fill = C.paper, lw = 6, label = '', labelSize = 40, cornerP = 1, hatchP = 0 } = o;
    if (alpha <= 0 || scale <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.rotate(rot); ctx.scale(scale, scale);
    const c = Math.min(w, h) * 0.22;
    const path = () => { ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(w / 2 - c, -h / 2); ctx.lineTo(w / 2, -h / 2 + c); ctx.lineTo(w / 2, h / 2); ctx.lineTo(-w / 2, h / 2); ctx.closePath(); };
    ctx.beginPath(); path(); ctx.fillStyle = fill; ctx.fill();
    if (hatchP > 0) hatch(ctx, path, { alpha: .4 * hatchP });
    ctx.beginPath(); path(); ctx.strokeStyle = border; ctx.lineWidth = lw; ctx.lineJoin = 'round'; ctx.stroke();
    if (cornerP > 0) { ctx.save(); ctx.globalAlpha *= clamp(cornerP); ctx.beginPath(); ctx.moveTo(w / 2 - c, -h / 2); ctx.lineTo(w / 2 - c, -h / 2 + c); ctx.lineTo(w / 2, -h / 2 + c); ctx.closePath(); ctx.fillStyle = C.amber; ctx.fill(); ctx.strokeStyle = border; ctx.lineWidth = lw; ctx.stroke(); ctx.restore(); }
    let top = -h / 2 + c;
    if (label) { text(ctx, label, -w / 2 + w * .12, -h / 2 + c * .55 + labelSize * .15, { size: labelSize, weight: 800, align: 'left' }); top = -h / 2 + c + labelSize * .4; }
    ctx.strokeStyle = C.ink; ctx.lineWidth = Math.max(4, lw * .8); ctx.lineCap = 'round'; ctx.globalAlpha *= .42;
    for (let i = 0; i < n; i++) { const f = clamp(lines * n - i); if (f <= 0) break; const yy = top + (i + .8) * (h / 2 - top - h * .1) / n; const x0 = -w / 2 + w * .12, x1 = x0 + (w * .74 - (i === n - 1 ? w * .22 : 0)) * f; ctx.beginPath(); ctx.moveTo(x0, yy); ctx.lineTo(x1, yy); ctx.stroke(); }
    ctx.restore();
  }
  // 도장(장치 5): p 0~1 = 짧은 스케일 인(1.5→1, 튀지 않음). 보통 p = pr(t, t0, t0+0.2). box = 테두리 상자
  function stamp(ctx, o) {
    const { text: s, x, y, size = 96, color = C.amberD, p = 1, rot = -0.05, box = true, alpha = 1 } = o;
    if (p <= 0 || alpha <= 0) return; const sc = 1 + .5 * (1 - easeOut(p));
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(sc, sc); ctx.globalAlpha *= clamp(p * 2.5) * alpha;
    ctx.font = F(800, size); const w = ctx.measureText(s).width;
    if (box) { ctx.strokeStyle = color; ctx.lineWidth = Math.max(5, size * .07); const pad = size * .32; ctx.strokeRect(-w / 2 - pad, -size * .7, w + pad * 2, size * 1.4); }
    ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(s, 0, size * .04); ctx.restore();
  }
  // 체크 도장(원 + 체크, 판정 확정): stampCheck(ctx,{x,y,r,p,color})
  function stampCheck(ctx, o) {
    const { x, y, r = 70, p = 1, color = C.green, alpha = 1, rot = -0.08 } = o; if (p <= 0 || alpha <= 0) return;
    const sc = 1 + .5 * (1 - easeOut(p));
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(sc, sc); ctx.globalAlpha *= clamp(p * 2.5) * alpha;
    ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.lineWidth = Math.max(6, r * .12); ctx.strokeStyle = color; ctx.stroke();
    ctx.restore();
    check(ctx, { x: x + r * .04, y: y + r * .04, s: r * 1.05, p: clamp(p * 1.4), color, lw: Math.max(8, r * .16), alpha });
  }
  /* 체크리스트(장치 10): checklist(ctx,{x,y,w,items,checked,active,title,rowH,labelP})
   * x,y = 왼쪽 위. items = 라벨 배열(≥ 36px). checked[i] 0~1 = 초록 원 체크, labelP[i] 0~1 = 라벨이 써짐(없으면 1)
   * active = 앰버 막대 표시 줄. 돌려주는 값: 줄 영역 배열 */
  function checklist(ctx, o) {
    const { x, y, w = 520, items = [], checked = [], active = -1, title = '', rowH = 110, labelP = [], alpha = 1, size = 40 } = o;
    if (alpha <= 0) return []; const NUM = ['①', '②', '③', '④', '⑤', '⑥'];
    const th = title ? 80 : 20, h = th + items.length * (rowH + 14) + 10;
    ctx.save(); ctx.globalAlpha *= alpha;
    rr(ctx, x, y, w, h, 24); ctx.fillStyle = C.paper; ctx.fill(); ctx.lineWidth = 5; ctx.strokeStyle = C.ink; ctx.stroke();
    if (title) text(ctx, title, x + w / 2, y + 46, { size: 40, weight: 800 });
    const rows = [];
    items.forEach((s, i) => {
      const ry = y + th + i * (rowH + 14);
      if (i === active) { ctx.fillStyle = C.amber; ctx.fillRect(x + 10, ry + 8, 10, rowH - 16); }
      rr(ctx, x + 28, ry, w - 48, rowH, 16); ctx.lineWidth = 3; ctx.strokeStyle = G(.4); ctx.stroke();
      const cp = clamp(checked[i] || 0), cx = x + 80, cy = ry + rowH / 2;
      ctx.beginPath(); ctx.arc(cx, cy, 30, 0, Math.PI * 2);
      if (cp > 0) { ctx.save(); ctx.globalAlpha *= clamp(cp * 3); ctx.fillStyle = C.green; ctx.fill(); ctx.restore(); }
      ctx.lineWidth = 4; ctx.strokeStyle = cp > 0 ? C.green : C.ink; ctx.stroke();
      if (cp > 0) check(ctx, { x: cx, y: cy + 2, s: 32, p: cp, color: C.white, lw: 7 }); else text(ctx, NUM[i] || String(i + 1), cx, cy + 2, { size: 36, weight: 800 });
      const lp = labelP[i] == null ? 1 : clamp(labelP[i]);
      if (lp > 0) { ctx.save(); ctx.beginPath(); ctx.rect(x + 125, ry, (w - 150) * easeOut(lp), rowH); ctx.clip(); text(ctx, s, x + 128, cy + 2, { size, weight: 800, align: 'left' }); ctx.restore(); }
      else line(ctx, [[x + 130, cy + 16], [x + w - 50, cy + 16]], 1, { lw: 3, alpha: .3, dash: [8, 10] });
      rows.push({ x: x + 28, y: ry, w: w - 48, h: rowH, cx, cy });
    });
    ctx.restore(); return rows;
  }
  // 갈림길(곧은 선 draw-on). 원점 = 갈림목. 줄기 (0,150)→(0,0), 가지 (±400,-200)×s. accent 'left'|'right' = 그 가지 앰버, 반대쪽 흐리게
  function fork(ctx, o) {
    const { x, y, s = 1, pS = 1, pL = 1, pR = 1, accent = null, alpha = 1 } = o;
    const P = (a, b) => [x + a * s, y + b * s], lw = Math.max(5, 14 * s);
    line(ctx, [P(0, 150), P(0, 0)], pS, { lw, alpha });
    line(ctx, [P(0, 0), P(-400, -200)], pL, { lw, color: accent === 'left' ? C.amber : C.ink, alpha: alpha * (accent === 'right' ? .35 : 1) });
    line(ctx, [P(0, 0), P(400, -200)], pR, { lw, color: accent === 'right' ? C.amber : C.ink, alpha: alpha * (accent === 'left' ? .35 : 1) });
    return { root: P(0, 150), fork: P(0, 0), left: P(-400, -200), right: P(400, -200) };
  }
  // 표지판: 기둥 + 칸(곧은 선). p 0~1 = 꽂힘
  function sign(ctx, o) {
    const { x, y, label, p = 1, alpha = 1, size = 40 } = o; if (p <= 0 || alpha <= 0) return;
    const w = tw(ctx, label, size, 800) + 56, h = size + 32;
    line(ctx, [[x, y + h / 2], [x, y + h / 2 + 40]], p, { lw: 6, alpha });
    ctx.save(); ctx.globalAlpha *= alpha * clamp(p * 3); ctx.fillStyle = C.paper; ctx.fillRect(x - w / 2, y - h / 2, w, h); ctx.restore();
    line(ctx, [[x - w / 2, y - h / 2], [x + w / 2, y - h / 2], [x + w / 2, y + h / 2], [x - w / 2, y + h / 2], [x - w / 2, y - h / 2]], p, { lw: 5, alpha });
    text(ctx, label, x, y + 2, { size, weight: 800, alpha: alpha * pr(p, .5, 1) });
  }
  /* 절차 레일(장치 10·21): rail(ctx,{x,y,n,cellW,cellH,gap,labels,fill,on,checks,drawP,arrowP,labelSize})
   * x,y = 레일 전체 중심. gap 0 = 붙은 칸(단계 6칸), gap > 0 = 떨어진 칸 + 칸 사이 화살표(플랜 → 울트라)
   * fill[i] 0~1 = 칸이 아래에서 앰버로 참, on[i] 0~1 = 앰버 굵은 테두리, checks[i] 0~1 = 칸 위 초록 체크, drawP = 윤곽 draw-on
   * labels = 칸 위 라벨(≥ 44px). 돌려주는 값: 칸 영역 배열 {x,y,w,h,cx,cy} */
  function rail(ctx, o) {
    const { x = 960, y = 400, n = 2, cellW = 420, cellH = 300, gap = 0, labels = [], fill = [], on = [], checks = [], drawP = 1, arrowP = 0, labelSize = 48, alpha = 1, dim = [] } = o;
    const totW = n * cellW + (n - 1) * gap, L = x - totW / 2, T = y - cellH / 2, cells = [];
    for (let i = 0; i < n; i++) {
      const cx0 = L + i * (cellW + gap), a = alpha * (dim[i] ? 1 - .65 * clamp(dim[i]) : 1);
      const fp = clamp(fill[i] || 0);
      if (fp > 0) { ctx.save(); ctx.globalAlpha *= a; ctx.fillStyle = C.amber; const ih = (cellH - 16) * easeInOut(fp); ctx.fillRect(cx0 + 8, T + cellH - 8 - ih, cellW - 16, ih); ctx.restore(); }
      if (gap > 0 || i === 0) line(ctx, rrPts(cx0, T, cellW, cellH, gap > 0 ? 18 : 2), clamp(drawP * n - i * .6), { lw: 6, alpha: a });
      else line(ctx, [[cx0, T], [cx0 + cellW, T], [cx0 + cellW, T + cellH], [cx0, T + cellH]], clamp(drawP * n - i * .6), { lw: 6, alpha: a });
      const op = clamp(on[i] || 0); if (op > 0) line(ctx, rrPts(cx0, T, cellW, cellH, gap > 0 ? 18 : 2), op, { lw: 11, color: C.amber, alpha: a });
      if (labels[i]) text(ctx, labels[i], cx0 + cellW / 2, T - labelSize * .9, { size: labelSize, weight: 800, alpha: a * clamp(drawP * 2) });
      const ck = clamp(checks[i] || 0); if (ck > 0) check(ctx, { x: cx0 + cellW / 2, y: T - (labels[i] ? labelSize * 2.1 : 44), s: 56, p: ck, color: C.green, lw: 9, alpha: a });
      if (gap > 0 && i < n - 1) arrow(ctx, { pts: [[cx0 + cellW + 14, y], [cx0 + cellW + gap - 14, y]], p: clamp(arrowP * (n - 1) - i), lw: 8, alpha });
      cells.push({ x: cx0, y: T, w: cellW, h: cellH, cx: cx0 + cellW / 2, cy: y });
    }
    return cells;
  }
  // 화살표(곧은 선 + 머리). p 0~1 = 선이 그어지고 끝에 머리
  function arrow(ctx, o) {
    const { pts, p = 1, lw = 8, color = C.ink, alpha = 1, head = 26 } = o; if (p <= 0 || alpha <= 0) return;
    line(ctx, pts, p, { lw, color, alpha });
    const L = []; let tot = 0; for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); L.push(d); tot += d; }
    let tg = tot * clamp(p), i = 0; while (i < L.length - 1 && tg > L[i]) { tg -= L[i]; i++; }
    const a = pts[i], b = pts[i + 1], u = clamp(tg / (L[i] || 1)), ex = lerp(a[0], b[0], u), ey = lerp(a[1], b[1], u), ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    line(ctx, [[ex - Math.cos(ang - .5) * head, ey - Math.sin(ang - .5) * head], [ex, ey], [ex - Math.cos(ang + .5) * head, ey - Math.sin(ang + .5) * head]], 1, { lw, color, alpha });
  }
  // 시계(장치 3): 60분 눈금 + minutes만큼 부채꼴. style 'hatch'(일반) | 'fill'(울트라). drawP = 테 draw-on, tickP = 눈금
  function clockFace(ctx, o) {
    const { x, y, r = 200, minutes = 0, style = 'fill', drawP = 1, tickP = 1, alpha = 1 } = o; if (alpha <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha;
    const a0 = -Math.PI / 2, a1 = a0 + minutes / 60 * Math.PI * 2;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = C.paper; ctx.fill();
    if (minutes > 0) { const path = () => { ctx.moveTo(x, y); ctx.arc(x, y, r * .94, a0, a1); ctx.closePath(); };
      if (style === 'fill') { ctx.beginPath(); path(); ctx.fillStyle = C.amber; ctx.fill(); } else hatch(ctx, path, { alpha: .55 }); }
    ctx.restore();
    circleP(ctx, { x, y, r, p: drawP, lw: Math.max(5, r * .045), alpha });
    for (let k = 0; k < 12; k++) { const f = clamp(tickP * 12 - k); if (f <= 0) break; const a = a0 + k / 12 * Math.PI * 2, r0 = r * (k % 3 === 0 ? .8 : .87);
      line(ctx, [[x + Math.cos(a) * r0, y + Math.sin(a) * r0], [x + Math.cos(a) * r * .95, y + Math.sin(a) * r * .95]], f, { lw: Math.max(3, r * .03), alpha }); }
    if (drawP >= 1) { line(ctx, [[x, y], [x + Math.cos(a1) * r * .78, y + Math.sin(a1) * r * .78]], 1, { lw: Math.max(5, r * .05), alpha });
      ctx.save(); ctx.globalAlpha *= alpha; ctx.fillStyle = C.ink; ctx.beginPath(); ctx.arc(x, y, Math.max(6, r * .06), 0, Math.PI * 2); ctx.fill(); ctx.restore(); }
  }
  // 온도계(장치 12, 수치 없음): x = 중심, top·bottom = 관 위·아래, hw = 관 반폭, br = 아래 구 반지름. level 0~1
  function thermo(ctx, o) {
    const { x, top = 260, bottom = 620, hw = 44, br = 72, level = 0, drawP = 1, alpha = 1, label = '' } = o; if (alpha <= 0) return;
    const by = bottom + br * .75;
    ctx.save(); ctx.globalAlpha *= alpha;
    if (level > 0 && drawP >= 1) { ctx.fillStyle = C.amber; ctx.beginPath(); ctx.arc(x, by, br * .8, 0, Math.PI * 2); ctx.fill(); const h = (bottom - top - hw) * clamp(level); ctx.fillRect(x - hw * .6, bottom + 6 - h, hw * 1.2, h); }
    ctx.restore();
    const pts = [[x - hw, bottom], [x - hw, top + hw]]; for (let i = 0; i <= 12; i++) { const a = Math.PI + i / 12 * Math.PI; pts.push([x + Math.cos(a) * hw, top + hw + Math.sin(a) * hw]); }
    pts.push([x + hw, bottom]); const ang = Math.asin(hw / br);
    for (let i = 0; i <= 28; i++) { const a = -Math.PI / 2 + ang + i / 28 * (Math.PI * 2 - 2 * ang); pts.push([x + Math.cos(a) * br, by + Math.sin(a) * br]); }
    line(ctx, pts, drawP, { lw: Math.max(5, hw * .16), alpha });
    if (label) text(ctx, label, x, top - 50, { size: 44, weight: 800, alpha });
  }
  // 큰 숫자(장치 3): size ≥ 130 강제. p 0~1 = 스케일 인. unit = 옆에 작게(앰버 진)
  function bigNumber(ctx, o) {
    const { x, y, text: s, unit = '', p = 1, color = C.ink, unitColor = C.amberD, alpha = 1 } = o;
    const size = Math.max(130, o.size || 180); if (alpha <= 0 || p <= 0) return;
    const sc = 1 + .35 * (1 - easeOut(p)), a = alpha * clamp(p * 1.6);
    const nw = tw(ctx, s, size, 800), uw = unit ? tw(ctx, unit, size * .4, 800) + 16 : 0;
    ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc);
    text(ctx, s, -uw / 2, 0, { size, weight: 800, color, alpha: a });
    if (unit) text(ctx, unit, nw / 2 - uw / 2 + 16, size * .22, { size: size * .4, weight: 800, color: unitColor, align: 'left', alpha: a });
    ctx.restore();
  }
  // 단어 박자 확대(장치 19): t0에 0.2초 스케일 인 → t1-0.15부터 사라짐. 1~3어절만
  function kw(ctx, o) {
    const { text: s, x, y, size = 72, t, t0, t1, color = C.ink } = o;
    const a = pr(t, t0, t0 + .12) * (1 - pr(t, t1 - .15, t1)); if (a <= 0) return;
    const sc = 1 + .35 * (1 - easeOut(pr(t, t0, t0 + .2)));
    ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); text(ctx, s, 0, 0, { size, weight: 800, color, alpha: a }); ctx.restore();
  }
  // 말풍선(P1 종이): 꼬리 tail 'left'|'right'. text 있으면 가운데(≥ 40px), 없으면 회색 줄 2개. p = 윤곽 draw-on
  function bubble(ctx, o) {
    const { x, y, w = 420, h = 180, p = 1, alpha = 1, tail = 'left', text: s = '', size = 48, color = C.ink } = o; if (alpha <= 0 || p <= 0) return;
    const L = x - w / 2, T = y - h / 2, r = h * .3, fa = alpha * clamp(p * 1.5), sg = tail === 'right' ? -1 : 1;
    const tx0 = x - sg * w * .2, tx1 = x - sg * w * .3, tx2 = x - sg * w * .02, ty = T + h;
    ctx.save(); ctx.globalAlpha *= fa; rr(ctx, L, T, w, h, r); ctx.fillStyle = C.paper; ctx.fill();
    ctx.beginPath(); ctx.moveTo(tx0, ty - 3); ctx.lineTo(tx1, ty + h * .35); ctx.lineTo(tx2, ty - 3); ctx.closePath(); ctx.fill(); ctx.restore();
    line(ctx, rrPts(L, T, w, h, r), p, { lw: 5, alpha });
    line(ctx, [[tx0, ty], [tx1, ty + h * .35], [tx2, ty]], clamp(p * 3 - 2), { lw: 5, alpha });
    if (s) text(ctx, s, x, y + 2, { size, weight: 800, color, alpha: fa });
    else { bar(ctx, L + w * .18, y - h * .12, w * .6, 14, G(.35), fa); bar(ctx, L + w * .18, y + h * .14, w * .4, 14, G(.35), fa); }
  }
  // 취소선(장치 4)·체크(장치 10)·엑스
  function strike(ctx, o) { const { x1, x2, y, y2, p = 1, color = C.ink, lw = 10, alpha = 1 } = o; line(ctx, [[x1, y], [x2, y2 != null ? y2 : y]], p, { lw, color, alpha }); }
  function check(ctx, o) { const { x, y, s = 70, p = 1, color = C.green, lw = 12, alpha = 1 } = o; line(ctx, [[x - s * .5, y], [x - s * .12, y + s * .38], [x + s * .55, y - s * .42]], p, { lw, color, alpha }); }
  function cross(ctx, o) { const { x, y, s = 60, p = 1, color = C.ink, lw = 12, alpha = 1 } = o; line(ctx, [[x - s / 2, y - s / 2], [x + s / 2, y + s / 2]], clamp(p * 2), { lw, color, alpha }); line(ctx, [[x + s / 2, y - s / 2], [x - s / 2, y + s / 2]], clamp(p * 2 - 1), { lw, color, alpha }); }
  // 자물쇠: s = 몸통 폭. open 0~1 = 고리가 올라가며 열림(고수만 → 누구나)
  function lock(ctx, o) {
    const { x, y, s = 200, open = 0, alpha = 1, color = C.ink } = o; if (alpha <= 0) return;
    const bw = s, bh = s * .78, e = easeInOut(open), lift = s * .28 * e, rot = -0.5 * e;
    ctx.save(); ctx.globalAlpha *= alpha;
    ctx.save(); ctx.translate(x + bw * .3, y - bh / 2 - lift); ctx.rotate(rot);
    ctx.beginPath(); ctx.moveTo(-bw * .6, 10); ctx.lineTo(-bw * .6, -bw * .12); ctx.arc(-bw * .3, -bw * .12, bw * .3, Math.PI, 0); ctx.lineTo(0, 10);
    ctx.lineWidth = s * .11; ctx.lineCap = 'round'; ctx.strokeStyle = color; ctx.stroke(); ctx.restore();
    rr(ctx, x - bw / 2, y - bh / 2, bw, bh, s * .12); ctx.fillStyle = e > .5 ? C.amber : C.paper; ctx.fill(); ctx.lineWidth = s * .06; ctx.strokeStyle = color; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y - bh * .06, s * .09, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill(); ctx.fillRect(x - s * .03, y - bh * .06, s * .06, bh * .26);
    ctx.restore();
  }

  // ---------------- 좌상단 HUD · 챕터 칩 · 우상단 미니 체크리스트(카메라·카드 줌 밖) ----------------
  const CIRCLED = { '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5' };
  // hud(ctx,"① 사용법",{p}) — 원문자면 앰버 원 + 숫자, 아니면 앰버 원 + 별표. p 0~1 = 슬라이드 인
  function hud(ctx, s, o = {}) {
    const { p = 1, alpha = 1 } = o; if (alpha <= 0 || p <= 0) return;
    const first = [...s][0], num = CIRCLED[first], label = num ? [...s].slice(1).join('').trim() : s;
    const e = easeOut(p), dx = lerp(-460, 0, e), a = alpha * clamp(p * 1.5), x = 40 + dx, y = 64, R = 32;
    ctx.save(); ctx.globalAlpha *= a; ctx.beginPath(); ctx.arc(x + R, y, R, 0, Math.PI * 2); ctx.fillStyle = C.amber; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = C.ink; ctx.stroke();
    if (!num) starPixels(ctx, x + R - 6.5 * 3.2, y - 6.5 * 3.2, 3.2, C.ink);
    ctx.restore();
    if (num) text(ctx, num, x + R, y + 2, { size: 38, weight: 800, alpha: a });
    text(ctx, label, x + 2 * R + 18, y + 1, { size: 40, weight: 800, align: 'left', alpha: a });
  }
  const HUD_W = (ctx, s) => { const num = CIRCLED[[...s][0]]; const label = num ? [...s].slice(1).join('').trim() : s; return 40 + 64 + 18 + tw(ctx, label, 40, 800); };
  // HUD 교체(경계 직전 0.3초): hudSwap(ctx, t, tSwap, '이전', '다음') — 이전이 왼쪽으로 빠지고 다음이 슬라이드 인
  function hudSwap(ctx, t, tSwap, a, b) { if (t < tSwap) { hud(ctx, a); return; } const q = pr(t, tSwap, tSwap + .3); if (q < .5) hud(ctx, a, { p: 1 - q * 2 }); else hud(ctx, b, { p: (q - .5) * 2 }); }
  // chapterChip(ctx,{n,text,p,x}) — HUD 오른쪽 잉크 알약(앰버 번호 원 + 3~6자). 막·꼭지 전환(장치 20). 전면 패널 대신
  function chapterChip(ctx, o) {
    const { n = '', text: s = '', p = 1, alpha = 1, x: x0 = 380 } = o; if (p <= 0 || alpha <= 0) return;
    const e = easeOut(p), a = alpha * clamp(p * 1.5), x = lerp(x0 - 200, x0, e), y = 64, h = 72;
    const wText = tw(ctx, s, 40, 800), w = (n ? 76 : 30) + wText + 32;
    ctx.save(); ctx.globalAlpha *= a; rr(ctx, x, y - h / 2, w, h, h / 2); ctx.fillStyle = C.ink; ctx.fill();
    if (n) { ctx.beginPath(); ctx.arc(x + 38, y, 26, 0, Math.PI * 2); ctx.fillStyle = C.amber; ctx.fill(); }
    ctx.restore();
    if (n) text(ctx, String(n), x + 38, y + 2, { size: 34, weight: 800, alpha: a });
    text(ctx, s, x + (n ? 76 : 30), y + 2, { size: 40, weight: 800, color: C.paper, align: 'left', alpha: a });
    return { x, w };
  }
  /* 우상단 미니 체크리스트 배지(예고 3칸, G2 후반부터 끝까지 상주). miniChecklist(ctx,{items,checked,on,active})
   * 가로 알약 1개(오른쪽 끝 x=1880, 세로 중심 y=64, 높이 76). checked[i] 0~1 = 칸이 초록으로 차며 체크. on 0~1 = 등장
   * 크기가 작아 "움직임"이 아니다 — 체크 순간에는 무대의 큰 요소가 같이 움직여야 한다 */
  const MINI = { right: 1880, y: 64, h: 76 };
  function miniChecklist(ctx, o = {}) {
    const { items = ['사용법', '꿀팁', '주의'], checked = [], on = 1, active = -1 } = o; if (on <= 0) return;
    const size = 36, box = 40, gapIn = 12, gapOut = 30, pad = 26;
    const ws = items.map(s => box + gapIn + tw(ctx, s, size, 800)); const W0 = ws.reduce((a, b) => a + b, 0) + gapOut * (items.length - 1) + pad * 2;
    const e = easeOut(on), x0 = MINI.right - W0, y = MINI.y, cx = x0 + W0 / 2;
    ctx.save(); ctx.globalAlpha *= clamp(on * 1.5); ctx.translate(cx, y); ctx.scale(lerp(.7, 1, e), lerp(.7, 1, e)); ctx.translate(-cx, -y);
    rr(ctx, x0, y - MINI.h / 2, W0, MINI.h, MINI.h / 2); ctx.fillStyle = C.paper; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = C.ink; ctx.stroke();
    let xx = x0 + pad;
    items.forEach((s, i) => {
      const c = clamp(checked[i] || 0);
      if (i === active) bar(ctx, xx - 8, y + 30, ws[i] + 16, 6, C.amber);
      rr(ctx, xx, y - box / 2, box, box, 8); if (c > 0) { ctx.save(); ctx.globalAlpha *= clamp(c * 3); ctx.fillStyle = C.green; ctx.fill(); ctx.restore(); }
      ctx.lineWidth = 4; ctx.strokeStyle = c > 0 ? C.green : C.ink; ctx.stroke();
      if (c > 0) check(ctx, { x: xx + box / 2, y: y + 1, s: 26, p: c, color: C.white, lw: 6 });
      text(ctx, s, xx + box + gapIn, y + 2, { size, weight: 800, align: 'left', alpha: c > 0 ? .55 : 1 });
      xx += ws[i] + gapOut;
    });
    ctx.restore();
  }
  // 화면 고정 요소 한 번에: chrome(ctx,{hud, hudP, chip:{n,text,p}, badge:{checked,on,active}})
  function chrome(ctx, o = {}) {
    ctx.save(); screen(ctx);
    if (o.hud) hud(ctx, o.hud, { p: o.hudP == null ? 1 : o.hudP });
    if (o.chip) chapterChip(ctx, Object.assign({ x: HUD_W(ctx, o.hud || '') + 30 }, o.chip));
    if (o.badge) miniChecklist(ctx, o.badge);
    ctx.restore();
  }

  // ================= P2 세트(카드 안, 카드 로컬 1920x1080) =================
  // 흰 카드(P2 주인공 판·입력창·문서 바탕). 무대 위 카드는 테두리 없이 그림자, 카드 안 카드는 옅은 잉크 테두리
  function whiteCard(ctx, o) {
    const { x, y, w, h, r = 36, shadow = true, fill = C.white, alpha = 1, stroke = G(.16), lw = 4 } = o;
    if (alpha <= 0 || w <= 0 || h <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha;
    if (shadow) { ctx.shadowColor = SHADOW.color; ctx.shadowBlur = SHADOW.blur; ctx.shadowOffsetY = SHADOW.y; }
    rr(ctx, x - w / 2, y - h / 2, w, h, r); ctx.fillStyle = fill; ctx.fill();
    if (stroke) { ctx.shadowColor = 'transparent'; ctx.lineWidth = lw; ctx.strokeStyle = stroke; ctx.stroke(); }
    ctx.restore();
  }
  // 장치 21: 모프 시작 프레임의 목표 형태 점선 윤곽
  function ghost(ctx, o) { const { x, y, w, h, r = 36, alpha = 1 } = o; if (alpha <= 0) return; ctx.save(); ctx.globalAlpha *= alpha; ctx.setLineDash([20, 14]); ctx.lineWidth = 4; ctx.strokeStyle = G(.5); rr(ctx, x - w / 2, y - h / 2, w, h, r); ctx.stroke(); ctx.restore(); }
  // 라벨 칩(메뉴·명령 이름 ≥ 44px). state: 'idle'(흰+회 테두리) | 'active'(앰버) | 'ink'(잉크, 흰 글자). hi 0~1 = idle→active 채움
  function chip(ctx, o) {
    const { x, y, text: s, size = 44, state = 'idle', hi = 0, alpha = 1, scale = 1, check: ck = 0 } = o;
    if (alpha <= 0) return null; const tW = tw(ctx, s, size, 800), h = size * 1.7, w = tW + size * 1.2 + (ck > 0 ? size : 0);
    ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.scale(scale, scale);
    rr(ctx, -w / 2, -h / 2, w, h, h / 2); ctx.fillStyle = state === 'ink' ? C.ink : C.white; ctx.fill();
    const a = state === 'active' ? 1 : clamp(hi); if (a > 0 && state !== 'ink') { ctx.save(); ctx.globalAlpha *= a; ctx.fillStyle = C.amber; ctx.fill(); ctx.restore(); }
    if (state !== 'ink') { ctx.lineWidth = 4; ctx.strokeStyle = a > 0 ? C.ink : G(.3); ctx.stroke(); }
    text(ctx, s, -w / 2 + size * .6, 2, { size, weight: 800, color: state === 'ink' ? C.white : C.ink, align: 'left' });
    if (ck > 0) check(ctx, { x: w / 2 - size * .75, y: 0, s: size * .7, p: ck, color: C.ink, lw: 7 });
    ctx.restore();
    return { x, y, w: w * scale, h: h * scale };
  }
  /* 추상 앱 화면(실제 앱 흉내 금지: 회색 상단 바 + 라벨 칩 + 본문 회색 줄 + 오른쪽 패널)
   * appScreen(ctx,{x,y,w,h,topbar:[라벨…],panel:[라벨…],active:{top,panel},hi:{top,panel},checked:{panel},panelTitle,body,inputBar,alpha})
   * active.top = 앰버 칩 번호(선택됨), hi.top 0~1 = 그 칩이 차오르는 중(클릭 순간). panel·checked도 같다(checked = 체크 표시 p).
   * body: 'lines'(회색 줄) | 'chat'(말풍선 막대 2개) | 'none'. inputBar: true면 본문 아래 빈 입력줄(채팅창 자리) + 그 rect 반환.
   * 돌려주는 값: {top:[칩 rect], panel:[칩 rect], input:rect, body:rect} — 커서 목표로 쓴다 */
  function appScreen(ctx, o) {
    const { x = 960, y = 470, w = 1640, h = 740, topbar = [], panel = [], active = {}, hi = {}, checked = {}, panelTitle = '', body = 'lines', inputBar = false, alpha = 1, panelW = 0.34 } = o;
    if (alpha <= 0) return null;
    ctx.save(); ctx.globalAlpha *= alpha;
    const L = x - w / 2, T = y - h / 2, bh = 120, out = { top: [], panel: [], input: null, body: null };
    whiteCard(ctx, { x, y, w, h, r: 30 });
    ctx.save(); rr(ctx, L, T, w, h, 30); ctx.clip(); ctx.fillStyle = G(.07); ctx.fillRect(L, T, w, bh); ctx.restore();
    line(ctx, [[L, T + bh], [L + w, T + bh]], 1, { lw: 3, color: G(.14) });
    rr(ctx, L + 36, T + bh / 2 - 26, 52, 52, 12); ctx.fillStyle = G(.18); ctx.fill(); // 추상 로고 자리(회색 네모)
    let cx = L + 120;
    topbar.forEach((s, i) => { const st = active.top === i ? 'active' : 'idle'; const cw = tw(ctx, s, 44, 800) + 44 * 1.2;
      const r0 = chip(ctx, { x: cx + cw / 2, y: T + bh / 2, text: s, size: 44, state: st, hi: hi.top === i ? hi.topP == null ? 1 : hi.topP : 0 }); out.top.push(r0); cx += cw + 22; });
    const pw = panel.length ? w * panelW : 0, bodyR = { x: L + 50, y: T + bh + 50, w: w - pw - 100, h: h - bh - 100 }; out.body = bodyR;
    if (body === 'lines') { const ws = [.82, .64, .74, .5]; ws.forEach((f, i) => bar(ctx, bodyR.x, bodyR.y + 30 + i * 62, bodyR.w * f, 24, G(.12))); }
    if (body === 'chat') { rr(ctx, bodyR.x + bodyR.w * .3, bodyR.y + 10, bodyR.w * .7, 90, 26); ctx.fillStyle = G(.08); ctx.fill(); rr(ctx, bodyR.x, bodyR.y + 130, bodyR.w * .62, 130, 26); ctx.fillStyle = G(.05); ctx.fill(); }
    if (inputBar) { const ir = { x: bodyR.x, y: T + h - 150, w: bodyR.w, h: 100 }; rr(ctx, ir.x, ir.y, ir.w, ir.h, 28); ctx.fillStyle = C.white; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = G(.3); ctx.stroke(); out.input = ir; }
    if (panel.length) {
      const PL = L + w - pw; line(ctx, [[PL, T + bh], [PL, T + h]], 1, { lw: 3, color: G(.14) });
      ctx.save(); rr(ctx, L, T, w, h, 30); ctx.clip(); ctx.fillStyle = G(.035); ctx.fillRect(PL, T + bh, pw, h - bh); ctx.restore();
      let py = T + bh + 60; if (panelTitle) { text(ctx, panelTitle, PL + 40, py, { size: 36, weight: 700, align: 'left', color: G(.6) }); py += 80; }
      panel.forEach((s, i) => { const st = active.panel === i ? 'active' : 'idle';
        const cw = tw(ctx, s, 44, 800) + 44 * 1.2 + (checked.panel === i ? 44 : 0);
        const r0 = chip(ctx, { x: PL + 40 + cw / 2, y: py, text: s, size: 44, state: st, hi: hi.panel === i ? hi.panelP == null ? 1 : hi.panelP : 0, check: checked.panel === i ? (checked.panelP == null ? 1 : checked.panelP) : 0 });
        out.panel.push(r0); py += 104; });
    }
    ctx.restore(); return out;
  }
  // 선택 목록(명령 팔레트·모델 목록). listMenu(ctx,{x,y,w,items,sel,selP,title,rowH,check}) x,y = 왼쪽 위. 돌려주는 값: 줄 rect 배열
  function listMenu(ctx, o) {
    const { x, y, w = 620, items = [], sel = -1, selP = 1, title = '', rowH = 88, alpha = 1, check: ck = 0, dimOthers = 0 } = o;
    if (alpha <= 0) return []; const th = title ? 70 : 16, h = th + items.length * rowH + 16;
    ctx.save(); ctx.globalAlpha *= alpha;
    whiteCard(ctx, { x: x + w / 2, y: y + h / 2, w, h, r: 24 });
    if (title) text(ctx, title, x + 36, y + 42, { size: 36, weight: 700, align: 'left', color: G(.6) });
    const rows = [];
    items.forEach((s, i) => { const ry = y + th + i * rowH;
      if (i === sel && selP > 0) { ctx.save(); ctx.globalAlpha *= clamp(selP); rr(ctx, x + 12, ry + 6, w - 24, rowH - 12, 18); ctx.fillStyle = C.amber; ctx.fill(); ctx.restore(); }
      text(ctx, s, x + 40, ry + rowH / 2 + 2, { size: 44, weight: 800, align: 'left', alpha: i === sel ? 1 : 1 - .6 * clamp(dimOthers) });
      if (i === sel && ck > 0) check(ctx, { x: x + w - 60, y: ry + rowH / 2, s: 44, p: ck, color: C.ink, lw: 8 });
      rows.push({ x: x + 12, y: ry + 6, w: w - 24, h: rowH - 12, cx: x + w / 2, cy: ry + rowH / 2 }); });
    ctx.restore(); return rows;
  }
  // 커서: x,y = 화살 끝. press 0~1 = 눌림(작아짐)
  function cursor(ctx, o) {
    const { x, y, press = 0, alpha = 1 } = o; if (alpha <= 0) return;
    const s = 1 - .14 * clamp(press); ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.scale(s * 1.5, s * 1.5);
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, 40); ctx.lineTo(10, 31); ctx.lineTo(17, 47); ctx.lineTo(24, 44); ctx.lineTo(17, 28); ctx.lineTo(30, 28); ctx.closePath();
    ctx.fillStyle = C.ink; ctx.strokeStyle = C.white; ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.stroke(); ctx.fill(); ctx.restore();
  }
  // ---- 입력창 + 타이핑(장치 8) ----
  function enterIcon(ctx, cx, cy, s, col, lw) {
    line(ctx, [[cx + s * .45, cy - s * .4], [cx + s * .45, cy + s * .12], [cx - s * .45, cy + s * .12]], 1, { lw, color: col });
    line(ctx, [[cx - s * .2, cy - s * .14], [cx - s * .45, cy + s * .12], [cx - s * .2, cy + s * .38]], 1, { lw, color: col });
  }
  function inputLayout(ctx, o) {
    const { x, y, w, text: s = '', size = 52 } = o;
    const L = x - w / 2, R = x + w / 2, x0 = L + 200, avail = (R - 190) - x0 - (o.tail ? (o.tail.w || 420) + 18 : 0); // 꼬리(사각지대 빈 줄) 자리를 먼저 뺀다
    let fs = size, lines = [s];
    if (tw(ctx, s, fs, 500) > avail) fs = Math.max(44, Math.floor(size * avail / tw(ctx, s, size, 500)));
    if (tw(ctx, s, fs, 500) > avail) { fs = 44; const words = s.split(' '); lines = ['']; for (const wd of words) { const cand = lines[lines.length - 1] ? lines[lines.length - 1] + ' ' + wd : wd; if (tw(ctx, cand, fs, 500) > avail && lines[lines.length - 1]) lines.push(wd); else lines[lines.length - 1] = cand; } }
    const lh = fs * 1.35, top = y - lh * (lines.length - 1) / 2;
    let acc = 0; const L2 = lines.map((ln, i) => { const st = acc; acc += [...ln].length + (i < lines.length - 1 ? 1 : 0); return { text: ln, x: x0, y: top + i * lh, start: st }; });
    return { size: fs, x0, lines: L2, L, R };
  }
  /* inputBox(ctx,{x,y,w,h,lineNo,text,typedChars,enterHi,caret,alpha,size,tail})
   * 둥근 사각 + 줄 번호 + '>' + 글자 + ⏎. typedChars = 보이는 글자 수(없으면 전부). enterHi 0~1 = ⏎ 앰버 채움·눌림.
   * tail = 글자 뒤에 붙는 앰버 빈 줄(사각지대 프롬프트 자리) {w, p, label} — 문장 창작 금지, 빈 줄 + 라벨만.
   * 돌려주는 값: 레이아웃 + {endX, endY}(커서·꼬리 위치) */
  function inputBox(ctx, o) {
    const { x, y, w, h = 150, lineNo = 1, text: s = '', typedChars, enterHi = 0, caret = true, alpha = 1, r = 36, tail = null } = o;
    if (alpha <= 0) return null;
    ctx.save(); ctx.globalAlpha *= alpha;
    whiteCard(ctx, { x, y, w, h, r });
    const lay = inputLayout(ctx, o), L = lay.L, R = lay.R;
    if (lineNo != null) text(ctx, String(lineNo), L + 72, y + 3, { size: 40, weight: 800, color: G(.4) });
    text(ctx, '>', L + 150, y, { size: 52, weight: 800 });
    const chars = [...s], n = typedChars == null ? chars.length : clamp(Math.floor(typedChars), 0, chars.length);
    let endX = lay.x0, endY = lay.lines[0].y;
    for (const ln of lay.lines) { const k = clamp(n - ln.start, 0, [...ln.text].length); if (k <= 0) continue;
      const part = [...ln.text].slice(0, k).join(''); text(ctx, part, ln.x, ln.y, { size: lay.size, weight: 500, align: 'left' }); endX = ln.x + tw(ctx, part, lay.size, 500); endY = ln.y; }
    if (tail && tail.p > 0) { const tx = endX + 18, tw0 = Math.min(tail.w || 420, R - 190 - tx) * easeOut(tail.p);
      if (tw0 > 0) { rr(ctx, tx, endY - lay.size * .55, tw0, lay.size * 1.1, 10); ctx.fillStyle = 'rgba(245,158,11,0.28)'; ctx.fill(); ctx.setLineDash([12, 10]); ctx.lineWidth = 4; ctx.strokeStyle = C.amberD; ctx.stroke(); ctx.setLineDash([]); }
      if (tail.label) text(ctx, tail.label, tx + 4, endY - lay.size * .55 - 36, { size: 36, weight: 800, color: C.amberD, align: 'left', alpha: clamp(tail.p * 2) }); endX = tx + tw0; }
    else if (caret && n < chars.length) bar(ctx, endX + 6, endY, 6, lay.size * 1.1, C.amber);
    const e = clamp(enterHi), bp = 1 - .1 * Math.sin(Math.PI * e);
    ctx.save(); ctx.translate(R - 95, y); ctx.scale(bp, bp); rr(ctx, -55, -55, 110, 110, 24);
    if (e > 0) { ctx.save(); ctx.globalAlpha *= e; ctx.fillStyle = C.amber; ctx.fill(); ctx.restore(); }
    ctx.lineWidth = 5; ctx.strokeStyle = C.ink; ctx.stroke(); enterIcon(ctx, 0, 0, 50, C.ink, 6); ctx.restore();
    ctx.restore();
    return Object.assign(lay, { endX, endY });
  }
  // 타이핑 글자 수: words = [[단어(뒤 공백 포함), 시작 초], ...]. 단어 시작마다 cps초/자
  function typed(t, words, cps = 0.07) {
    let n = 0, prevEnd = -1e9;
    for (const [s, st] of words) { const a = Math.max(st, prevEnd), len = [...s].length; if (t < a) break; const k = Math.min(len, Math.floor((t - a) / cps) + 1); n += k; if (k < len) break; prevEnd = a + len * cps; }
    return n;
  }
  // 복창 예외 명령·요청(원본 초 기준). 막 필름에서는 KIT.typed(t + FILM.offset, KIT.CMD.effort.words)
  const CMD = {
    effort: { text: '/effort', beats: [31], words: [['/', 132.38], ['effort', 132.76]] },   // 출처: 비트 #31 transcript "slash" 132.38 · "effort" 132.76
    edu: { text: '새로운 교육 상품을 기획해줘', beats: [44], words: [['새로운 ', 189.51], ['교육 ', 189.89], ['상품을 ', 190.23], ['기획해줘', 190.83]] }, // 출처: 비트 #44 transcript 단어 시각
  };

  // ---- 토큰(P2 주인공 = P1 캐릭터와 같은 별표 마크) ----
  /* token(ctx,{x,y,r,kind,face,dim,cross,caption,alpha})
   * kind: 'me'(흰 원 + 앰버 별표 + 눈 = 카드 밖 캐릭터의 얼굴) | 'ai'(잉크 원 + 앰버 별표 + 눈 = 에이전트) | 'gray'(꺼짐)
   * r = 반지름(지름 ≥ 200 → r ≥ 100, 미니 표시만 예외: mini:true). face = 캐릭터와 같은 3종 */
  function token(ctx, o) {
    const { x, y, kind = 'me', face = 'base', dim = 0, cross: cx0 = 0, caption = '', alpha = 1, mini = false, captionColor = C.ink } = o;
    const r = mini ? (o.r || 30) : Math.max(100, o.r || 110); if (alpha <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.shadowColor = 'rgba(20,20,19,.16)'; ctx.shadowBlur = r > 40 ? 18 : 4; ctx.shadowOffsetY = r > 40 ? 6 : 1;
    ctx.fillStyle = kind === 'ai' ? C.ink : kind === 'gray' ? '#DCD8CF' : C.white; ctx.fill(); ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(3, r * .07); ctx.strokeStyle = kind === 'me' ? C.amber : kind === 'gray' ? G(.25) : C.ink; ctx.stroke();
    const ps = r * 1.34 / 13, ox = x - 6.5 * ps, oy = y - 6.5 * ps;
    starPixels(ctx, ox, oy, ps, kind === 'gray' ? G(.28) : C.amber);
    if (kind !== 'gray') eyes(ctx, ox, oy, ps, face, C.ink);
    if (dim > 0) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = `rgba(247,243,234,${.62 * clamp(dim)})`; ctx.fill(); }
    ctx.restore();
    if (cx0 > 0) cross(ctx, { x, y, s: r * 1.2, p: cx0, lw: Math.max(8, r * .14), alpha });
    if (caption) text(ctx, caption, x, y + r + 46, { size: Math.max(36, r * .38), weight: 800, color: captionColor, alpha });
  }
  // 결과 문서 카드: resultDoc(ctx,{x,y,w,h,label,lines,drawP,gray,holes,holeP,scale,rot,alpha,labelSize})
  // label = 문서 이름(≥ 40px, 대본에 있는 것만). gray = 회색 결과(이전 방식). holes = 앰버 빈 칸 줄 번호(사각지대), holeP 0~1
  function resultDoc(ctx, o) {
    const { x, y, w = 420, h = 540, label = '', lines = 5, drawP = 1, gray = false, holes = [], holeP = 1, scale = 1, rot = 0, alpha = 1, labelSize = 44, check: ck = 0 } = o;
    if (alpha <= 0 || scale <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.rotate(rot); ctx.scale(scale, scale);
    whiteCard(ctx, { x: 0, y: 0, w, h, r: 24, fill: gray ? '#E9E6E0' : C.white });
    const s = Math.min(70, w * .16); ctx.beginPath(); ctx.moveTo(w / 2 - s, -h / 2); ctx.lineTo(w / 2, -h / 2 + s); ctx.lineTo(w / 2 - s, -h / 2 + s); ctx.closePath(); ctx.fillStyle = gray ? G(.14) : C.amber; ctx.fill();
    const pad = Math.max(34, w * .09); let y0 = -h / 2 + pad + labelSize * .5;
    if (label) { text(ctx, label, -w / 2 + pad, y0, { size: labelSize, weight: 800, align: 'left', color: gray ? G(.55) : C.ink }); y0 += labelSize + 26; }
    const gapY = (h / 2 - pad - y0) / Math.max(1, lines);
    for (let i = 0; i < lines; i++) { const f = clamp(drawP * lines - i), ly = y0 + (i + .5) * gapY, bw = (w - pad * 2) * (i === lines - 1 ? .6 : [.92, .78, .86, .7, .82][i % 5]);
      if (holes.includes(i)) { const hp = clamp(holeP); ctx.save(); ctx.globalAlpha *= hp; rr(ctx, -w / 2 + pad, ly - 18, bw, 36, 10); ctx.fillStyle = 'rgba(245,158,11,0.3)'; ctx.fill(); ctx.setLineDash([12, 10]); ctx.lineWidth = 4; ctx.strokeStyle = C.amberD; ctx.stroke(); ctx.restore(); if (hp < 1) bar(ctx, -w / 2 + pad, ly, bw * f, 22, G(.16), 1 - hp); }
      else bar(ctx, -w / 2 + pad, ly, bw * f, 22, gray ? G(.14) : G(.2)); }
    ctx.restore();
    if (ck > 0) stampCheck(ctx, { x: x + w * scale * .32, y: y - h * scale * .3, r: Math.max(40, w * scale * .13), p: ck, alpha });
  }
  // 계획 종이(플랜 모드): planSheet(ctx,{x,y,w,h,title,rows,drawP,checks,arrowP,alpha})
  // rows = 줄 수(숫자) 또는 짧은 라벨 배열(≥ 40px, 대본 낱말만: '순서'·'방향' 등). checks[i] 0~1 = 오른쪽 칸 체크, arrowP = 번호 사이 순서 화살표
  function planSheet(ctx, o) {
    const { x, y, w = 900, h = 640, title = '계획', rows = 4, drawP = 1, checks = [], arrowP = 0, alpha = 1, hole = -1, holeP = 0 } = o;
    if (alpha <= 0) return []; const list = typeof rows === 'number' ? Array.from({ length: rows }, () => '') : rows;
    ctx.save(); ctx.globalAlpha *= alpha;
    whiteCard(ctx, { x, y, w, h, r: 24 });
    const L = x - w / 2, T = y - h / 2, pad = 60; text(ctx, title, L + pad, T + 70, { size: 52, weight: 800, align: 'left' }); bar(ctx, L + pad, T + 112, tw(ctx, title, 52, 800), 8, C.amber);
    const top = T + 170, gapY = (h - 210) / list.length, out = [];
    list.forEach((s, i) => { const f = clamp(drawP * list.length - i), ly = top + (i + .5) * gapY;
      ctx.save(); ctx.globalAlpha *= clamp(f * 3); ctx.beginPath(); ctx.arc(L + pad + 26, ly, 26, 0, Math.PI * 2); ctx.fillStyle = C.ink; ctx.fill(); ctx.restore();
      text(ctx, String(i + 1), L + pad + 26, ly + 2, { size: 32, weight: 800, color: C.white, alpha: clamp(f * 3) });
      const lx = L + pad + 80, lw0 = w - pad * 2 - 80 - 90;
      if (i === hole && holeP > 0) { ctx.save(); ctx.globalAlpha *= holeP; rr(ctx, lx, ly - 20, lw0 * .8, 40, 10); ctx.fillStyle = 'rgba(245,158,11,0.3)'; ctx.fill(); ctx.setLineDash([12, 10]); ctx.lineWidth = 4; ctx.strokeStyle = C.amberD; ctx.stroke(); ctx.restore(); }
      else if (s) { ctx.save(); ctx.beginPath(); ctx.rect(lx, ly - 40, lw0 * easeOut(f), 80); ctx.clip(); text(ctx, s, lx, ly + 2, { size: 44, weight: 800, align: 'left' }); ctx.restore(); bar(ctx, lx + tw(ctx, s, 44, 800) + 24, ly, (lw0 - tw(ctx, s, 44, 800) - 24) * .7 * f, 20, G(.18)); }
      else bar(ctx, lx, ly, lw0 * [.9, .7, .8, .6, .75][i % 5] * f, 22, G(.2));
      const bx = L + w - pad - 50; rr(ctx, bx, ly - 25, 50, 50, 10); ctx.save(); ctx.globalAlpha *= clamp(f * 3); ctx.lineWidth = 4; ctx.strokeStyle = G(.45); ctx.stroke(); ctx.restore();
      const ck = clamp(checks[i] || 0); if (ck > 0) check(ctx, { x: bx + 25, y: ly - 2, s: 50, p: ck, color: C.green, lw: 9 });
      if (i > 0) line(ctx, [[L + pad + 26, ly - gapY + 30], [L + pad + 26, ly - 30]], clamp(arrowP * (list.length - 1) - (i - 1)), { lw: 5, color: C.amberD });
      out.push({ x: lx, y: ly, w: lw0 }); });
    ctx.restore(); return out;
  }
  // 게이지(장치 12, 수치 없음). dir 'h'(가로, 기본 폭 620 ≥ 화면 15%) | 'v'. level 0~1. color 'amber'|'gray'|'ink'|'hatch'. label = 옆/아래 글자
  function gauge(ctx, o) {
    const { x, y, dir = 'h', level = 0, color = 'amber', label = '', alpha = 1, arrowDir = null } = o; if (alpha <= 0) return;
    const w = o.w || (dir === 'h' ? 620 : 150), h = o.h || (dir === 'h' ? 96 : 520);
    const fill = color === 'amber' ? C.amber : color === 'ink' ? C.ink : G(.3), lc = color === 'amber' ? C.amberD : C.ink;
    ctx.save(); ctx.globalAlpha *= alpha; rr(ctx, x - w / 2, y - h / 2, w, h, Math.min(w, h) * .3); ctx.fillStyle = C.white; ctx.fill(); ctx.lineWidth = 5; ctx.strokeStyle = C.ink; ctx.stroke();
    const lv = clamp(level), pd = 12;
    if (lv > 0) { const r0 = Math.min(w, h) * .3 - pd * .6;
      const path = () => dir === 'h' ? rr(ctx, x - w / 2 + pd, y - h / 2 + pd, (w - pd * 2) * lv, h - pd * 2, r0) : rr(ctx, x - w / 2 + pd, y + h / 2 - pd - (h - pd * 2) * lv, w - pd * 2, (h - pd * 2) * lv, r0);
      if (color === 'hatch') { hatch(ctx, path, { alpha: .6 }); } else { path(); ctx.fillStyle = fill; ctx.fill(); } }
    ctx.restore();
    if (label) { if (dir === 'h') text(ctx, label, x - w / 2 - 26, y + 2, { size: 44, weight: 800, align: 'right', color: lc, alpha }); else text(ctx, label, x, y + h / 2 + 50, { size: 44, weight: 800, color: lc, alpha }); }
    if (arrowDir) { const ax = dir === 'h' ? x + w / 2 + 60 : x + w / 2 + 50, up = arrowDir === 'up'; arrow(ctx, { pts: [[ax, up ? y + 40 : y - 40], [ax, up ? y - 40 : y + 40]], lw: 10, color: up ? C.green : C.ink, alpha }); }
  }
  // 스위치(장치 14): on 0~1. s = 배율(기본 1.4 → 168x84). label = 왼쪽(≥ 44px)
  function toggle(ctx, o) {
    const { x, y, on = 0, label = '', s = 1.4, alpha = 1 } = o; if (alpha <= 0) return;
    ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.scale(s, s);
    rr(ctx, -60, -30, 120, 60, 30); ctx.fillStyle = G(.16); ctx.fill();
    if (on > 0) { ctx.save(); ctx.globalAlpha *= clamp(on); rr(ctx, -60, -30, 120, 60, 30); ctx.fillStyle = C.amber; ctx.fill(); ctx.restore(); }
    ctx.beginPath(); ctx.arc(lerp(-30, 30, easeInOut(on)), 0, 23, 0, Math.PI * 2); ctx.fillStyle = C.white; ctx.shadowColor = 'rgba(20,20,19,.2)'; ctx.shadowBlur = 6; ctx.fill(); ctx.restore();
    if (label) text(ctx, label, x - 60 * s - 26, y, { size: 44, weight: 800, align: 'right', alpha });
  }

  // ================= 전환: 카드 줌(P1 ↔ P2) =================
  /* 카드 rect = {x,y,w,h,r} (무대 좌표, 중심 기준). 카드 안은 "카드 로컬 1920x1080" 좌표로 그린다.
   * 카드 로컬 → 무대 좌표 매핑 = 카드를 꽉 덮는 16:9 창(cover-fit). 카드가 16:9보다 넓으면 좌우 여백은 흰 여백(줌 끝에 화면 밖으로 나간다).
   * p=1 에서 카드 로컬 좌표 = 화면 좌표(항등) → cardFull(ctx, drawInside)와 픽셀이 같다. */
  function contentRect(R) { const s = Math.max(W / R.w, H / R.h), cw = W / s, ch = H / s; return { x: R.x - cw / 2, y: R.y - ch / 2, w: cw, h: ch, s }; }
  // 카메라(닫힌 식): 보이는 무대 창이 화면 전체 → contentRect로 줄어든다. 폭은 지수 보간(일정한 확대 속도), 위치는 같은 비율 u로(고정점 있는 순수 확대)
  function cardCam(R, e) {
    const Cr = contentRect(R); const wv = W * Math.pow(Cr.w / W, e); const u = (W - Cr.w) > 1e-6 ? (W - wv) / (W - Cr.w) : e;
    return { z: W / wv, left: lerp(0, Cr.x, u), top: lerp(0, Cr.y, u), Cr };
  }
  // 카드 1장(+안 콘텐츠)을 현재 변환에 그린다. e = 줌 진행(0 무대, 1 꽉 참): 모서리·그림자가 e에 따라 사라진다
  function cardRaw(ctx, R, e, drawInside, insideA, insideS) {
    const Cr = contentRect(R), r = (R.r == null ? 36 : R.r) * (1 - e);
    ctx.save();
    if (e < 1) { ctx.shadowColor = `rgba(20,20,19,${.16 * (1 - e)})`; ctx.shadowBlur = 34; ctx.shadowOffsetY = 12; }
    rr(ctx, R.x - R.w / 2, R.y - R.h / 2, R.w, R.h, r); ctx.fillStyle = C.white; ctx.fill(); ctx.shadowColor = 'transparent';
    if (drawInside && insideA > 0) {
      rr(ctx, R.x - R.w / 2, R.y - R.h / 2, R.w, R.h, r); ctx.clip();
      ctx.translate(Cr.x, Cr.y); ctx.scale(1 / Cr.s, 1 / Cr.s);
      if (insideS !== 1) { ctx.translate(960, 540); ctx.scale(insideS, insideS); ctx.translate(-960, -540); }
      ctx.globalAlpha *= insideA; drawInside(ctx);
    }
    ctx.restore();
  }
  // 무대 위 카드(정지): inCard(ctx, R, drawInside, {alpha}) — 막 안에서 카드가 무대에 놓여 있을 때(줌 전·후, 작아진 앱 카드 3장 등)
  function inCard(ctx, R, drawInside, o = {}) { const a = o.alpha == null ? 1 : o.alpha; if (a <= 0) return; ctx.save(); ctx.globalAlpha *= a; cardRaw(ctx, R, 0, drawInside, 1, 1); ctx.restore(); }
  // 카드 안 P2 화면 전체(p=1 상태). 카드 안 구간 내내 이것을 부른다
  function cardFull(ctx, drawInside) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.fillStyle = C.white; ctx.fillRect(0, 0, W, H); if (drawInside) { ctx.save(); drawInside(ctx); ctx.restore(); } ctx.setTransform(1, 0, 0, 1, 0, 0); }
  function cardScene(ctx, e, R, drawInside, drawStage, insideA, insideS) {
    if (e >= 1) { cardFull(ctx, drawInside); return; }
    BASE(ctx);
    const cam = cardCam(R, e);
    ctx.setTransform(cam.z, 0, 0, cam.z, -cam.left * cam.z, -cam.top * cam.z);
    if (drawStage) { ctx.save(); drawStage(ctx, cam); ctx.restore(); }
    cardRaw(ctx, R, e, drawInside, insideA, insideS);
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1;
  }
  /* enterCard(ctx, p, R, drawInside, drawStage, o) — P1 → P2. p 0→1(0.5초 권장, p = pr(t, t0, t0+0.5)).
   * p=0 = 무대 + 빈 흰 카드(= inCard(R, null)), p=1 = cardFull(drawInside). 카메라 easeInOut.
   * 카드 안 콘텐츠는 처음부터 작게 보이며(투명도 p 0→0.45에서 0→1, 스케일 0.94→1) 줌과 함께 커진다.
   * o.fade=false → 처음부터 불투명(카드에 이미 내용이 있던 경우). HUD·챕터 칩·배지는 이 함수 뒤에 chrome()으로 그린다. */
  function enterCard(ctx, p, R, drawInside, drawStage, o = {}) {
    const e = easeInOut(p), fade = o.fade !== false;
    const a = fade ? easeOut(clamp(p / .45)) : 1, s = fade ? lerp(.94, 1, e) : 1;
    cardScene(ctx, e, R, drawInside, drawStage, a, s);
  }
  /* leaveCard(ctx, p, R, drawInside, drawStage, o) — P2 → P1 역방향. p=0 = cardFull(drawInside), p=1 = 무대 + 카드(내용 유지 = inCard(R, drawInside)).
   * o.fade=true → 줌아웃 뒤반(p 0.55→1)에 카드 안 내용이 사라져 빈 카드로 끝난다 */
  function leaveCard(ctx, p, R, drawInside, drawStage, o = {}) {
    const e = 1 - easeInOut(p), a = o.fade ? 1 - easeIn(pr(p, .55, 1)) : 1;
    cardScene(ctx, e, R, drawInside, drawStage, a, 1);
  }

  // ================= 핸드오프(막 이음매) =================
  // 표준 카드(P1 → P2 문): 캐릭터 오른쪽, 땅선 위에 선 흰 판. 폭 1400(≥ 1150), 높이 680, 16:9 내용 창 1209x680(가운데)
  const CARD = { x: 1060, y: 450, w: 1400, h: 680, r: 36 };
  const HERO_H = 300;
  const APP3 = [{ x: 1180, y: 400, w: 600, h: 338, r: 26 }, { x: 1270, y: 460, w: 600, h: 338, r: 26 }, { x: 1360, y: 520, w: 600, h: 338, r: 26 }];
  // 앱 화면 카드 3장의 안(G3에서 완성된 상태, 카드 로컬 좌표). 라벨은 대본 실물 메뉴 이름만
  const APP_INSIDE = [
    ctx => appScreen(ctx, { topbar: ['채팅', '코드'], active: { top: 1, panel: 0 }, panel: ['울트라 코드'], checked: { panel: 0 }, body: 'chat', inputBar: true }),
    ctx => { appScreen(ctx, { topbar: [], body: 'none' }); inputBox(ctx, { x: 960, y: 330, w: 1400, text: '/effort' }); listMenu(ctx, { x: 520, y: 450, w: 700, items: ['울트라 코드'], sel: 0, check: 1 }); },
    ctx => { const r = appScreen(ctx, { topbar: ['채팅', '워크'], active: { top: 1, panel: 0 }, panelTitle: '모델', panel: ['GPT 5.6 SOL', 'TERA'], body: 'lines' });
      text(ctx, '추론 강도', r.panel[0].x - r.panel[0].w / 2, 610, { size: 36, weight: 700, align: 'left', color: G(.6) }); toggle(ctx, { x: 1560, y: 700, on: 1, label: '울트라' }); },
  ];
  const HANDOFF_SPEC = {
    GROUND, CARD, HERO_H, APP3,
    G1G2: { t: 42.8, hud: '왜 대단한가', badge: null,
      hero: { x: 190, y: GROUND, h: HERO_H, face: 'base' },
      troop: { xs: [540, 780, 1020, 1260, 1500, 1740], y: GROUND, h: 220, face: 'base' },
      rail: { x: 1140, y: 385, n: 6, cellW: 240, cellH: 170, gap: 0, fill: [1, 1, 1, 1, 1, 1], checks: [1, 1, 1, 1, 1, 1] } },
    G2G3: { t: 117.5, hud: '① 사용법', badge: { checked: [0, 0, 0] },
      hero: { x: 200, y: GROUND, h: HERO_H, face: 'base' }, card: CARD },
    G3G4: { t: 181.4, hud: '② 활용법', badge: { checked: [1, 0, 0] },
      hero: { x: 560, y: GROUND, h: HERO_H, face: 'base' }, apps: APP3 },
    G4G5: { t: 315.1, hud: '③ 정리·주의', badge: { checked: [1, 1, 0] },
      hero: { x: 760, y: GROUND, h: HERO_H, face: 'base' },
      paper: { x: 1200, y: 560, w: 360, h: 440, lines: 1, n: 4 }, stampCheck: { x: 1300, y: 470, r: 72 } },
    THUMB: { hud: '울트라 모드', hero: { x: 960, y: GROUND, h: 340, face: 'base' },
      troop: { xs: [330, 540, 750, 1170, 1380, 1590], y: GROUND - 40, h: 240, silhouette: true },
      stamp: { text: '울트라 모드', x: 960, y: 250, size: 120 } },
  };
  // 무대만 그리는 함수(BASE·HUD 없음). 막 필름이 수렴 목표·enter/leaveCard의 drawStage로 그대로 쓴다
  const STAGE = {
    G1G2(ctx) { const S = HANDOFF_SPEC.G1G2; groundLine(ctx); rail(ctx, S.rail); troop(ctx, S.troop); character(ctx, S.hero); },
    G2G3(ctx) { const S = HANDOFF_SPEC.G2G3; groundLine(ctx); character(ctx, S.hero); },               // 카드는 enterCard/inCard가 그린다
    G3G4(ctx) { const S = HANDOFF_SPEC.G3G4; groundLine(ctx); APP3.forEach((R, i) => inCard(ctx, R, APP_INSIDE[i])); character(ctx, S.hero); },
    G4G5(ctx) { const S = HANDOFF_SPEC.G4G5; groundLine(ctx); paperCard(ctx, S.paper); stampCheck(ctx, S.stampCheck); character(ctx, S.hero); },
    THUMB(ctx) { const S = HANDOFF_SPEC.THUMB; groundLine(ctx); troop(ctx, S.troop); character(ctx, S.hero); stamp(ctx, S.stamp); },
  };
  const HANDOFF = {
    G1G2(ctx) { BASE(ctx); STAGE.G1G2(ctx); chrome(ctx, { hud: HANDOFF_SPEC.G1G2.hud }); },
    G2G3(ctx) { enterCard(ctx, 0, CARD, null, STAGE.G2G3); chrome(ctx, { hud: HANDOFF_SPEC.G2G3.hud, badge: HANDOFF_SPEC.G2G3.badge }); },
    G3G4(ctx) { BASE(ctx); STAGE.G3G4(ctx); chrome(ctx, { hud: HANDOFF_SPEC.G3G4.hud, badge: HANDOFF_SPEC.G3G4.badge }); },
    G4G5(ctx) { BASE(ctx); STAGE.G4G5(ctx); chrome(ctx, { hud: HANDOFF_SPEC.G4G5.hud, badge: HANDOFF_SPEC.G4G5.badge }); },
    THUMB(ctx) { BASE(ctx); STAGE.THUMB(ctx); chrome(ctx, { hud: HANDOFF_SPEC.THUMB.hud }); },   // G1 첫 프레임·G5 엔드카드(수미상관) 후보
    SPEC: HANDOFF_SPEC,
  };

  const KIT = {
    VERSION: '3.2.0',
    W, H, SAFE, GROUND, C, G, BEAT, fontFamily: null,
    ready, F, clamp, lerp, pr, easeOut, easeIn, easeInOut, spring, kf, snap, hop, lerpRect,
    rr, text, tw, line, rrPts, circleP, bar, hatch, hatchRect, arrow,
    BASE, screen, clipSafe, camApply, groundLine,
    // P1
    STAR, character, troop, person, crowd, paperCard, stamp, stampCheck, checklist, fork, sign, rail, clockFace, thermo, bigNumber, kw, bubble, strike, check, cross, lock,
    hud, HUD_W, hudSwap, chapterChip, miniChecklist, MINI, chrome,
    // P2
    whiteCard, ghost, chip, appScreen, listMenu, cursor, enterIcon, inputLayout, inputBox, typed, CMD, token, resultDoc, planSheet, gauge, toggle,
    // 전환
    contentRect, cardCam, inCard, cardFull, enterCard, leaveCard, CARD,
    HANDOFF, HANDOFF_SPEC, STAGE, APP_INSIDE,
  };
  window.KIT = KIT;
})();
