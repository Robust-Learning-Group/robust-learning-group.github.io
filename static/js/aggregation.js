/*
 * Hero figure: averaging vs. robust aggregation of worker gradients.
 *
 * 40 honest workers send gradients drawn around a common direction.
 * f adversarial workers collude and send gradients far away.
 * We draw the plain average and the geometric median (Weiszfeld's algorithm).
 *
 * Each adversarial point has an opacity that eases toward 0 or 1, and that
 * opacity is also its weight in both aggregates, so the markers glide
 * smoothly when the slider moves.
 */
(function () {
  "use strict";

  var canvas = document.getElementById("agg-canvas");
  var slider = document.getElementById("agg-slider");
  if (!canvas || !slider) return;

  var ctx = canvas.getContext("2d");
  var countOut = document.getElementById("agg-count");
  var countText = document.getElementById("agg-count-text");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var N_HONEST = 40;
  var MAX_BYZ = Number(slider.max);

  // ---------- Deterministic random numbers ----------
  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  var rand = mulberry32(20261014);
  function gauss() {
    var u = 1 - rand(), v = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  // Data coordinates: x in [-1, 1], y in [-0.8, 0.8], y pointing up.
  var honest = [];
  for (var i = 0; i < N_HONEST; i++) {
    honest.push({ x: -0.38 + 0.2 * gauss(), y: -0.22 + 0.17 * gauss() });
  }
  var byz = [];
  for (var j = 0; j < MAX_BYZ; j++) {
    byz.push({ x: 0.6 + 0.08 * gauss(), y: 0.48 + 0.07 * gauss(), a: 0, target: 0 });
  }

  // ---------- Aggregators (weighted) ----------
  function weightedPoints() {
    var pts = honest.map(function (p) { return { x: p.x, y: p.y, w: 1 }; });
    byz.forEach(function (p) { if (p.a > 0.001) pts.push({ x: p.x, y: p.y, w: p.a }); });
    return pts;
  }
  function mean(pts) {
    var sx = 0, sy = 0, sw = 0;
    pts.forEach(function (p) { sx += p.w * p.x; sy += p.w * p.y; sw += p.w; });
    return { x: sx / sw, y: sy / sw };
  }
  function geometricMedian(pts) {
    var z = mean(pts);
    for (var k = 0; k < 80; k++) {
      var nx = 0, ny = 0, den = 0;
      pts.forEach(function (p) {
        var d = Math.max(Math.hypot(p.x - z.x, p.y - z.y), 1e-6);
        nx += p.w * p.x / d; ny += p.w * p.y / d; den += p.w / d;
      });
      z = { x: nx / den, y: ny / den };
    }
    return z;
  }

  // ---------- Drawing ----------
  var W = 0, H = 0, colors = {};

  function readColors() {
    var s = getComputedStyle(document.documentElement);
    ["--primary", "--adversary", "--ink", "--ink-3", "--rule", "--surface"].forEach(function (v) {
      colors[v] = s.getPropertyValue(v).trim();
    });
  }

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var rect = canvas.getBoundingClientRect();
    W = rect.width; H = rect.height;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function toPx(p) {
    var s = W / 2.2;
    return { x: W / 2 + p.x * s, y: H / 2 - p.y * s };
  }

  function label(text, at, dx, dy, color, align) {
    ctx.font = "600 13px " + getComputedStyle(document.body).fontFamily;
    // Flip to the other side if the text would run off the canvas.
    var w = ctx.measureText(text).width;
    if (align === "right" && at.x + dx - w < 6) { align = "left"; dx = -dx; }
    if (align === "left" && at.x + dx + w > W - 6) { align = "right"; dx = -dx; }
    ctx.textAlign = align;
    ctx.textBaseline = "middle";
    // halo for legibility over points
    ctx.lineWidth = 4;
    ctx.strokeStyle = colors["--surface"];
    ctx.strokeText(text, at.x + dx, at.y + dy);
    ctx.fillStyle = color;
    ctx.fillText(text, at.x + dx, at.y + dy);
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // faint reference grid
    ctx.strokeStyle = colors["--rule"];
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var g = -1; g <= 1.001; g += 0.5) {
      var a = toPx({ x: g, y: 0 }), b = toPx({ x: 0, y: g });
      ctx.moveTo(a.x, 0); ctx.lineTo(a.x, H);
      ctx.moveTo(0, b.y); ctx.lineTo(W, b.y);
    }
    ctx.stroke();

    // honest gradients
    ctx.fillStyle = colors["--primary"];
    ctx.globalAlpha = 0.7;
    honest.forEach(function (p) {
      var q = toPx(p);
      ctx.beginPath(); ctx.arc(q.x, q.y, 3.6, 0, Math.PI * 2); ctx.fill();
    });

    // adversarial gradients
    ctx.strokeStyle = colors["--adversary"];
    ctx.lineWidth = 2;
    byz.forEach(function (p) {
      if (p.a < 0.01) return;
      var q = toPx(p), r = 4.2 * (0.6 + 0.4 * p.a);
      ctx.globalAlpha = p.a;
      ctx.beginPath();
      ctx.moveTo(q.x - r, q.y - r); ctx.lineTo(q.x + r, q.y + r);
      ctx.moveTo(q.x + r, q.y - r); ctx.lineTo(q.x - r, q.y + r);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;

    var pts = weightedPoints();
    var m = toPx(mean(pts));
    var gm = toPx(geometricMedian(pts));

    // drift between the two aggregates
    if (Math.hypot(m.x - gm.x, m.y - gm.y) > 6) {
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = colors["--ink-3"];
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(gm.x, gm.y); ctx.lineTo(m.x, m.y); ctx.stroke();
      ctx.setLineDash([]);
    }

    // average: hollow square
    ctx.strokeStyle = colors["--adversary"];
    ctx.fillStyle = colors["--surface"];
    ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.rect(m.x - 7, m.y - 7, 14, 14); ctx.fill(); ctx.stroke();

    // geometric median: filled diamond
    ctx.fillStyle = colors["--ink"];
    ctx.beginPath();
    ctx.moveTo(gm.x, gm.y - 9); ctx.lineTo(gm.x + 9, gm.y);
    ctx.lineTo(gm.x, gm.y + 9); ctx.lineTo(gm.x - 9, gm.y);
    ctx.closePath(); ctx.fill();

    var close = Math.hypot(m.x - gm.x, m.y - gm.y) < 40;
    label("geometric median", gm, -14, close ? 16 : 0, colors["--ink"], "right");
    label("average", m, 14, close ? -16 : 0, colors["--adversary"], "left");
  }

  // ---------- Animation: ease opacities toward targets ----------
  var running = false;
  function step() {
    var moving = false;
    byz.forEach(function (p) {
      var d = p.target - p.a;
      if (Math.abs(d) > 0.004) { p.a += d * 0.14; moving = true; } else { p.a = p.target; }
    });
    draw();
    if (moving) requestAnimationFrame(step); else running = false;
  }
  function animate() {
    if (reduceMotion) {
      byz.forEach(function (p) { p.a = p.target; });
      draw();
      return;
    }
    if (!running) { running = true; requestAnimationFrame(step); }
  }

  // The first f adversarial points are switched on, the rest off.
  function setCount(f) {
    countOut.textContent = f;
    if (countText) countText.textContent = f;
    byz.forEach(function (p, k) { p.target = k < f ? 1 : 0; });
    animate();
  }

  slider.addEventListener("input", function () { setCount(Number(slider.value)); });

  function init() {
    readColors();
    resize();
    var f = Number(slider.value);
    countOut.textContent = f;
    if (countText) countText.textContent = f;
    if (reduceMotion) { setCount(f); return; }
    draw();
    // One-time entrance: adversaries join a moment after load.
    setTimeout(function () { setCount(Number(slider.value)); }, 500);
  }

  window.addEventListener("resize", function () { resize(); draw(); });
  document.addEventListener("themechange", function () { readColors(); draw(); });

  if (document.fonts && document.fonts.ready) document.fonts.ready.then(init); else init();
})();
