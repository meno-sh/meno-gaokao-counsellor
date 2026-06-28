// sketch.js — hand-drawn rough.js primitives for the Gaokao voice refactor.
// Ported / trimmed from animation-beautification-reference/src/core.js.
// Global `rough` (roughjs CDN) must be loaded first. Functions read global time
// counters set by Sketch.setTime(NOW, BOIL) each animation frame.
(function () {
  const C = {
    BG: '#FBF6EA', PAPER: '#FFFDF4', INK: '#2A2218', SOFT: '#6B6151', FAINT: '#B0A48E',
    RED: '#C44536', BLUE: '#3873A8', PURPLE: '#7E55A4', ORANGE: '#E2882F',
    TERRA: '#BC6242', GREEN: '#53984F',
  };
  const TINT = {
    BLUE: '#DCEAF5', PURPLE: '#EADDF1', ORANGE: '#FAE3C3', TERRA: '#F5DCCC',
    GREEN: '#DDEEDA', RED: '#F8D9D3', INK: '#F1E8D0', YELLOW: '#FAEDB8',
  };
  function tintFor(c) {
    return ({ [C.BLUE]: TINT.BLUE, [C.PURPLE]: TINT.PURPLE, [C.ORANGE]: TINT.ORANGE,
      [C.TERRA]: TINT.TERRA, [C.GREEN]: TINT.GREEN, [C.RED]: TINT.RED })[c] || TINT.INK;
  }

  const TWO_PI = Math.PI * 2;
  let NOW = 0, BOIL = 0;
  function setTime(now, boil) { NOW = now; BOIL = boil; }

  function mulberry32(seed) {
    return function () {
      let t = (seed += 0x6D2B79F5);
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // rough.js option bundle. BOIL is mixed into the seed -> boiling lines.
  function rop(seed, color, fill, opts) {
    opts = opts || {};
    return {
      stroke: color || C.INK,
      strokeWidth: opts.strokeWidth || 2,
      roughness: opts.roughness !== undefined ? opts.roughness : 1.5,
      bowing: opts.bowing !== undefined ? opts.bowing : 1.6,
      seed: ((seed | 0) + BOIL * 131) >>> 0,
      fill: fill || undefined,
      fillStyle: opts.fillStyle || 'hachure',
      fillWeight: opts.fillWeight || 1,
      hachureGap: opts.hachureGap || 8,
      hachureAngle: opts.hachureAngle || -41,
      disableMultiStroke: opts.single || false,
    };
  }

  // ---- canvas sizing (DPR aware) ----
  function fit(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || canvas.width;
    const cssH = canvas.clientHeight || canvas.height;
    const bw = Math.round(cssW * dpr), bh = Math.round(cssH * dpr);
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, rc: rough.canvas(canvas), W: cssW, H: cssH, dpr };
  }

  function clear(ctx, W, H) { ctx.clearRect(0, 0, W, H); }

  // ---- paper grain (cached pattern) ----
  let grainCanvas = null, grainPattern = null;
  function makeGrain() {
    grainCanvas = document.createElement('canvas');
    const g = 280; grainCanvas.width = g; grainCanvas.height = g;
    const gctx = grainCanvas.getContext('2d');
    const rng = mulberry32(99);
    for (let i = 0; i < 260; i++) {
      const x = rng() * g, y = rng() * g, dark = rng() > 0.45;
      gctx.fillStyle = dark ? 'rgba(90,75,50,0.032)' : 'rgba(255,255,255,0.35)';
      gctx.beginPath(); gctx.arc(x, y, 0.4 + rng() * 0.8, 0, TWO_PI); gctx.fill();
    }
  }
  function paper(ctx, W, H, fill) {
    if (!grainCanvas) makeGrain();
    ctx.fillStyle = fill || C.BG; ctx.fillRect(0, 0, W, H);
    if (!grainPattern) grainPattern = ctx.createPattern(grainCanvas, 'repeat');
    ctx.fillStyle = grainPattern; ctx.fillRect(0, 0, W, H);
  }

  function roundedRect(rc, x, y, w, h, r, seed, color, fill, opts) {
    r = Math.min(r, w / 2, h / 2);
    const p = `M ${x + r} ${y} L ${x + w - r} ${y} Q ${x + w} ${y} ${x + w} ${y + r} ` +
      `L ${x + w} ${y + h - r} Q ${x + w} ${y + h} ${x + w - r} ${y + h} ` +
      `L ${x + r} ${y + h} Q ${x} ${y + h} ${x} ${y + h - r} ` +
      `L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y} Z`;
    rc.path(p, rop(seed, color, fill, opts));
  }

  // ---- expressive stick figure (ported) ----
  const ARM_POSES = {
    rest: { l: [[-12, 6], [-16, 22]], r: [[12, 6], [16, 22]] },
    wave: { l: [[-12, 6], [-16, 22]], r: [[17, -12], [26, -30]] },
    point: { l: [[-12, 6], [-16, 22]], r: [[18, -2], [36, -8]] },
    pointL: { l: [[-18, -2], [-36, -8]], r: [[12, 6], [16, 22]] },
    shrug: { l: [[-16, -2], [-26, -10]], r: [[16, -2], [26, -10]] },
    think: { l: [[-12, 6], [-16, 22]], r: [[14, -4], [6, -20]] },
    cheer: { l: [[-16, -14], [-24, -36]], r: [[16, -14], [24, -36]] },
  };

  function stick(rc, ctx, x, y, scale, seed, opts) {
    opts = opts || {};
    const s = scale, color = opts.color || C.INK;
    const pose = ARM_POSES[opts.pose] || ARM_POSES.rest;
    const mood = opts.mood || 'neutral';
    const bob = Math.sin(NOW * 1.7 + seed * 0.9) * 1.6 * s;
    const headR = 20 * s;
    const hx = x, hy = y - 45 * s + bob;
    rc.circle(hx, hy, headR * 2, rop(seed, color, C.PAPER, { fillStyle: 'solid', strokeWidth: 2.2 }));
    for (let i = -1; i <= 1; i++) {
      const a = -Math.PI / 2 + i * 0.38;
      rc.line(hx + Math.cos(a) * headR * 0.92, hy + Math.sin(a) * headR * 0.92,
        hx + Math.cos(a) * headR * 1.28, hy + Math.sin(a) * headR * 1.30,
        rop(seed + 40 + i, color, null, { strokeWidth: 1.8, roughness: 1.0, single: true }));
    }
    if (!opts.noFace) {
      ctx.save();
      ctx.strokeStyle = color; ctx.fillStyle = color;
      ctx.lineWidth = Math.max(1.4, 1.8 * s); ctx.lineCap = 'round';
      const lookX = (opts.look ? opts.look[0] : 0) * 3 * s;
      const lookY = (opts.look ? opts.look[1] : 0) * 2.5 * s;
      const blink = ((NOW + seed * 0.41) % 4.1) < 0.14;
      const eyeY = hy - 3 * s + lookY;
      [-6.5, 6.5].forEach((ex) => {
        if (blink) { ctx.beginPath(); ctx.moveTo(hx + ex * s - 2.4 * s + lookX, eyeY); ctx.lineTo(hx + ex * s + 2.4 * s + lookX, eyeY); ctx.stroke(); }
        else { ctx.beginPath(); ctx.arc(hx + ex * s + lookX, eyeY, 1.9 * s, 0, TWO_PI); ctx.fill(); }
      });
      if (mood === 'confused') {
        ctx.beginPath(); ctx.moveTo(hx - 9.5 * s, hy - 9 * s); ctx.lineTo(hx - 3.5 * s, hy - 11 * s); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(hx + 3.5 * s, hy - 10 * s); ctx.lineTo(hx + 9.5 * s, hy - 8 * s); ctx.stroke();
      } else if (mood === 'sad') {
        ctx.beginPath(); ctx.moveTo(hx - 9.5 * s, hy - 11 * s); ctx.lineTo(hx - 3.5 * s, hy - 9 * s); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(hx + 3.5 * s, hy - 9 * s); ctx.lineTo(hx + 9.5 * s, hy - 11 * s); ctx.stroke();
      } else if (mood === 'excited') {
        ctx.beginPath(); ctx.moveTo(hx - 9.5 * s, hy - 11.5 * s); ctx.lineTo(hx - 3.5 * s, hy - 12.5 * s); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(hx + 3.5 * s, hy - 12.5 * s); ctx.lineTo(hx + 9.5 * s, hy - 11.5 * s); ctx.stroke();
      }
      ctx.beginPath();
      if (mood === 'happy') { ctx.arc(hx + lookX * 0.5, hy + 4 * s, 5.5 * s, 0.25, Math.PI - 0.25); ctx.stroke(); }
      else if (mood === 'excited') { ctx.ellipse(hx + lookX * 0.5, hy + 6.5 * s, 3.4 * s, 4.4 * s, 0, 0, TWO_PI); ctx.fill(); }
      else if (mood === 'sad') { ctx.arc(hx + lookX * 0.5, hy + 11 * s, 5 * s, Math.PI + 0.3, TWO_PI - 0.3); ctx.stroke(); }
      else if (mood === 'confused') {
        ctx.moveTo(hx - 4.5 * s, hy + 7 * s);
        ctx.quadraticCurveTo(hx - 1.5 * s, hy + 5 * s, hx + 0.5 * s, hy + 7.5 * s);
        ctx.quadraticCurveTo(hx + 2.8 * s, hy + 9.5 * s, hx + 4.5 * s, hy + 7 * s); ctx.stroke();
      } else { ctx.moveTo(hx - 4 * s + lookX * 0.5, hy + 7 * s); ctx.lineTo(hx + 4 * s + lookX * 0.5, hy + 7 * s); ctx.stroke(); }
      ctx.restore();
    }
    const shY = y - 18 * s + bob * 0.6;
    rc.curve([[x, y - 25 * s + bob], [x + 1.5 * s, y - 4 * s], [x, y + 20 * s]], rop(seed + 1, color, null, { strokeWidth: 2.2 }));
    const drawArm = (def, sd, wiggle) => {
      let [elbow, hand] = def;
      let hx2 = x + hand[0] * s, hy2 = shY + hand[1] * s;
      if (wiggle) hx2 += Math.sin(NOW * 7 + seed) * 4 * s;
      rc.curve([[x, shY], [x + elbow[0] * s, shY + elbow[1] * s], [hx2, hy2]], rop(sd, color, null, { strokeWidth: 2.2 }));
      return [hx2, hy2];
    };
    drawArm(pose.l, seed + 2, false);
    drawArm(pose.r, seed + 3, opts.pose === 'wave');
    const legSpread = 15;
    rc.curve([[x, y + 20 * s], [x - legSpread * 0.55 * s, y + 36 * s], [x - legSpread * s, y + 50 * s]], rop(seed + 4, color, null, { strokeWidth: 2.2 }));
    rc.curve([[x, y + 20 * s], [x + legSpread * 0.55 * s, y + 36 * s], [x + legSpread * s, y + 50 * s]], rop(seed + 5, color, null, { strokeWidth: 2.2 }));
    rc.line(x - legSpread * s, y + 50 * s, x - (legSpread + 7) * s, y + 50 * s, rop(seed + 6, color, null, { strokeWidth: 2.2, single: true }));
    rc.line(x + legSpread * s, y + 50 * s, x + (legSpread + 7) * s, y + 50 * s, rop(seed + 7, color, null, { strokeWidth: 2.2, single: true }));
  }

  // ---- microphone glyph (rough) — capsule + yoke cradle + stand ----
  function mic(rc, ctx, cx, cy, r, seed, opts) {
    opts = opts || {};
    const color = opts.color || C.INK;
    const fill = opts.fill || C.PAPER;
    const capW = r * 1.02, capH = r * 1.62;
    const capTop = cy - r * 1.02;
    const capBot = capTop + capH;
    const capMid = capTop + capH * 0.5;
    // capsule body (full-radius ends)
    roundedRect(rc, cx - capW / 2, capTop, capW, capH, capW / 2, seed, color, fill, { fillStyle: 'solid', strokeWidth: 2.6, roughness: 1.1 });
    // grille: three short horizontal lines across the upper capsule
    for (let i = 0; i < 3; i++) {
      const gy = capTop + capH * 0.26 + i * capH * 0.17;
      rc.line(cx - capW * 0.27, gy, cx + capW * 0.27, gy, rop(seed + 1 + i, color, null, { strokeWidth: 1.5, single: true, roughness: 0.6 }));
    }
    // yoke / cradle: a U that hugs the lower half of the capsule
    const yokeR = capW * 0.96;
    const yokeCy = capMid + capH * 0.06;
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = 2.6; ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.arc(cx, yokeCy, yokeR, 0.08 * Math.PI, 0.92 * Math.PI);
    ctx.stroke();
    ctx.restore();
    // stem from the bottom of the yoke down to the stand
    const yokeBottom = yokeCy + yokeR;
    const baseY = cy + r * 1.62;
    rc.line(cx, yokeBottom - 1, cx, baseY, rop(seed + 6, color, null, { strokeWidth: 2.6, single: true }));
    // stand foot (flat)
    rc.line(cx - r * 0.62, baseY, cx + r * 0.62, baseY, rop(seed + 7, color, null, { strokeWidth: 2.6, single: true }));
  }

  // ---- radial audio visualizer: concentric rough rings reacting to `level` 0..1 ----
  function visualizer(rc, ctx, cx, cy, baseR, level, seed, color) {
    color = color || C.TERRA;
    const rings = 3;
    for (let i = 0; i < rings; i++) {
      const phase = (NOW * 0.7 + i * 0.33) % 1;
      const grow = phase; // 0..1 expand outward
      const rr = baseR * (1.12 + i * 0.18) + grow * baseR * (0.5 + level * 1.6);
      ctx.save();
      ctx.globalAlpha = (1 - grow) * (0.18 + level * 0.5);
      rc.circle(cx, cy, rr * 2, rop(seed + i * 7, color, null, { strokeWidth: 1.8, roughness: 1.6, single: true }));
      ctx.restore();
    }
    // breathing inner halo scaled by level
    ctx.save();
    ctx.globalAlpha = 0.10 + level * 0.30;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, baseR * (1.0 + level * 0.5), 0, TWO_PI);
    ctx.fill();
    ctx.restore();
  }

  // ---- small twinkling sparkle ----
  function sparkle(rc, ctx, x, y, r, seed, color) {
    color = color || C.ORANGE;
    const tw = 0.55 + 0.45 * Math.sin(NOW * 3.2 + seed * 1.7);
    ctx.save(); ctx.globalAlpha = tw;
    rc.line(x - r, y, x + r, y, rop(seed, color, null, { strokeWidth: 1.8, roughness: 0.9, single: true }));
    rc.line(x, y - r * 1.25, x, y + r * 1.25, rop(seed + 1, color, null, { strokeWidth: 1.8, roughness: 0.9, single: true }));
    ctx.restore();
  }

  window.Sketch = { C, TINT, tintFor, setTime, fit, clear, paper, roundedRect, stick, mic, visualizer, sparkle, mulberry32, rop };
})();
