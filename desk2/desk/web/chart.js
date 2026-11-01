/* Canvas charts, devicePixelRatio aware. Line (Home), candles+volume (Coin), score ring (Analyst). */
"use strict";
const RMc = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function fit(cv) {
  const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  if (cv.width !== w * d || cv.height !== h * d) { cv.width = w * d; cv.height = h * d; }
  const x = cv.getContext("2d"); x.setTransform(d, 0, 0, d, 0, 0); x.clearRect(0, 0, w, h);
  return [x, w, h];
}
const COL = { green: "#00d35a", red: "#ff453a", blue: "#0a84ff", orange: "#ff9f0a", t2: "rgba(235,235,245,0.6)", t3: "rgba(235,235,245,0.3)", sep: "rgba(84,84,88,0.55)" };

class LineChart {
  constructor(cv) { this.cv = cv; this.pts = []; this.marks = []; this.start = null; this.anim = 1; this.markA = 1; this.empty = false; }
  set(points, start, marks, animate) {
    const grew = animate && this.pts.length && points.length === this.pts.length + 1;
    this.pts = points; this.start = start; this.marks = marks || [];
    if (grew && !RMc()) { this.anim = 0; this.t0 = performance.now(); } else this.anim = 1;
    if (animate && !RMc()) { this.markA = 0; this.m0 = performance.now(); } else this.markA = 1;
    this.loop();
  }
  loop() { this.draw(); if (this.anim < 1 || this.markA < 1) requestAnimationFrame(() => this.loop()); }
  draw() {
    const [x, w, h] = fit(this.cv), now = performance.now();
    if (this.anim < 1) this.anim = Math.min(1, (now - this.t0) / 250);
    if (this.markA < 1) this.markA = Math.min(1, (now - this.m0) / 200);
    const top = 44, bot = h - 8, pad = 16;
    const P = this.pts;
    if (!P.length || this.start == null) {
      x.setLineDash([3, 4]); x.strokeStyle = COL.t3; x.lineWidth = 1;
      x.beginPath(); x.moveTo(0, h * 0.62); x.lineTo(w, h * 0.62); x.stroke(); x.setLineDash([]);
      x.fillStyle = COL.t2; x.font = "15px -apple-system, system-ui"; x.textAlign = "center";
      x.fillText("Waiting for the first trade", w / 2, h * 0.62 - 14); return;
    }
    const ts = P.map(p => Date.parse(p.ts)), vs = P.map(p => p.value);
    let lo = Math.min(this.start, ...vs), hi = Math.max(this.start, ...vs);
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const span = hi - lo; lo -= span * 0.08; hi += span * 0.08;
    let t0 = ts[0], t1 = ts[ts.length - 1]; if (t1 - t0 < 60000) t1 = t0 + 60000;
    const X = t => pad + (t - t0) / (t1 - t0) * (w - pad * 2), Y = v => bot - (v - lo) / (hi - lo) * (bot - top);
    // dashed start line
    x.setLineDash([3, 4]); x.strokeStyle = COL.t3; x.lineWidth = 1;
    x.beginPath(); x.moveTo(0, Y(this.start)); x.lineTo(w, Y(this.start)); x.stroke(); x.setLineDash([]);
    // line, last segment slides in
    const n = P.length, xy = ts.map((t, i) => [X(t), Y(vs[i])]);
    if (n > 1 && this.anim < 1) { const e = 1 - Math.pow(1 - this.anim, 3), a = xy[n - 2], b = xy[n - 1]; xy[n - 1] = [a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e]; }
    const g = x.createLinearGradient(0, top, 0, bot); g.addColorStop(0, "rgba(0,211,90,0.28)"); g.addColorStop(1, "rgba(0,211,90,0)");
    x.beginPath(); xy.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b));
    x.lineTo(xy[n - 1][0], bot); x.lineTo(xy[0][0], bot); x.closePath(); x.fillStyle = g; x.fill();
    x.beginPath(); xy.forEach(([a, b], i) => i ? x.lineTo(a, b) : x.moveTo(a, b));
    x.strokeStyle = COL.green; x.lineWidth = 2; x.lineJoin = "round"; x.stroke();
    x.fillStyle = COL.green; x.beginPath(); x.arc(xy[n - 1][0], xy[n - 1][1], 3.5, 0, 7); x.fill();
    // marks: never overlap, a later mark moves up a row
    x.font = "600 12px -apple-system, system-ui"; x.textAlign = "left"; x.globalAlpha = this.markA;
    const placed = [];
    const ms = [...this.marks].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
    for (const m of ms) {
      const mt = Date.parse(m.ts); if (mt < t0) continue;
      let i = ts.findIndex(t => t >= mt); if (i < 0) i = n - 1;
      const px = X(Math.min(mt, t1)), py = Y(vs[i]);
      const tw = x.measureText(m.label).width + 14, bx = Math.min(Math.max(2, px - tw / 2), w - tw - 2);
      let row = 0, by;
      for (;;) { by = Math.max(2, py - 30 - row * 24); if (!placed.some(r => bx < r.x + r.w + 4 && r.x < bx + tw + 4 && Math.abs(r.y - by) < 22)) break; row++; if (row > 6) break; }
      placed.push({ x: bx, y: by, w: tw });
      const c = m.kind === "bought" ? COL.blue : m.kind === "win" ? COL.green : COL.red;
      x.fillStyle = c; x.beginPath(); x.roundRect ? x.roundRect(bx, by, tw, 20, 10) : x.rect(bx, by, tw, 20); x.fill();
      x.strokeStyle = c; x.lineWidth = 1; x.beginPath(); x.moveTo(px, by + 20); x.lineTo(px, py - 4); x.stroke();
      x.fillStyle = m.kind === "win" ? "#000" : "#fff"; x.fillText(m.label, bx + 7, by + 14);
    }
    x.globalAlpha = 1;
  }
}

function candles(cv, cs, exitLine, entry) {
  const [x, w, h] = fit(cv);
  if (!cs.length) { x.fillStyle = COL.t2; x.font = "15px -apple-system, system-ui"; x.textAlign = "center"; x.fillText("No prices recorded yet", w / 2, h / 2); return; }
  const vh = h * 0.2, top = 10, bot = h - vh - 10;
  let lo = Math.min(...cs.map(c => c.l)), hi = Math.max(...cs.map(c => c.h));
  if (exitLine) { lo = Math.min(lo, exitLine); hi = Math.max(hi, exitLine); }
  if (entry) { lo = Math.min(lo, entry); hi = Math.max(hi, entry); }
  if (hi - lo < hi * 1e-6) { hi *= 1.01; lo *= 0.99; }
  const Y = v => bot - (v - lo) / (hi - lo) * (bot - top);
  const n = Math.max(cs.length, 30), cw = (w - 32) / n, bw = Math.max(2, cw * 0.65);
  const vmax = Math.max(1e-9, ...cs.map(c => c.v));
  cs.forEach((c, i) => {
    const cx = 16 + (i + 0.5) * cw + (n - cs.length) * cw, up = c.c >= c.o, col = up ? COL.green : COL.red;
    x.strokeStyle = col; x.fillStyle = col; x.lineWidth = 1;
    x.beginPath(); x.moveTo(cx, Y(c.h)); x.lineTo(cx, Y(c.l)); x.stroke();
    const y1 = Y(Math.max(c.o, c.c)), y2 = Y(Math.min(c.o, c.c)); x.fillRect(cx - bw / 2, y1, bw, Math.max(1, y2 - y1));
    x.globalAlpha = 0.45; const vv = c.v / vmax * (vh - 4); x.fillRect(cx - bw / 2, h - vv, bw, vv); x.globalAlpha = 1;
  });
  if (exitLine) {
    x.setLineDash([5, 4]); x.strokeStyle = COL.orange; x.lineWidth = 1.5; x.beginPath(); x.moveTo(0, Y(exitLine)); x.lineTo(w, Y(exitLine)); x.stroke(); x.setLineDash([]);
    x.fillStyle = COL.orange; x.font = "600 11px -apple-system, system-ui"; x.textAlign = "left"; x.fillText("Risk trailing stop", 16, Y(exitLine) - 5);
  }
}

function ring(cv, score, min) {
  const [x, w, h] = fit(cv), r = Math.min(w, h) / 2 - 7, cx = w / 2, cy = h / 2;
  x.lineWidth = 10; x.lineCap = "round"; x.strokeStyle = "#2c2c2e"; x.beginPath(); x.arc(cx, cy, r, 0, Math.PI * 2); x.stroke();
  if (score == null) return;
  x.strokeStyle = score >= min ? COL.green : (score >= min - 20 ? "#ffd60a" : COL.red);
  x.beginPath(); x.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0.01, score / 100)); x.stroke();
}
window.Charts = { LineChart, candles, ring };
