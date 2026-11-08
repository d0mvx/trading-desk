/* Overlapping /api/state completions. Node vm + assert, no test framework dependency beyond node:test. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "web");
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");

function boot() {
  let clock = Date.parse("2026-11-08T13:00:00Z");
  class FakeDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  const nodes = {};
  function makeEl(id) {
    const el = {
      id, html: "", textContent: "", style: {}, dataset: {}, className: "",
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      querySelectorAll() { return []; }, querySelector() { return null; },
      appendChild() {}, remove() {}, setAttribute() {},
      getBoundingClientRect() { return { width: 390, height: 80, top: 0, left: 0 }; },
      getContext() { return { setTransform() {}, clearRect() {} }; },
    };
    Object.defineProperty(el, "innerHTML", {
      get() { return el.html; },
      set(v) { el.html = String(v); index(el.html); },
    });
    return el;
  }
  function index(html) {
    for (const m of html.matchAll(/id="([^"]+)"/g)) nodes[m[1]] = makeEl(m[1]);
  }
  const appEl = makeEl("app");
  nodes.app = appEl;
  const pending = [];
  const timeouts = [];
  const intervals = [];
  const location = { hash: "", pathname: "/", search: "" };
  const context = {
    console, Date: FakeDate, performance: { now: () => clock },
    setTimeout(fn, ms) { const t = { fn, ms, id: timeouts.length + 1 }; timeouts.push(t); return t.id; },
    clearTimeout(id) { const t = timeouts.find(x => x.id === id); if (t) t.cleared = true; },
    setInterval(fn, ms) { const t = { fn, ms, id: intervals.length + 1 }; intervals.push(t); return t.id; },
    clearInterval() {},
    requestAnimationFrame() { return 0; },
    cancelAnimationFrame() {},
    addEventListener() {},
    location, history: { replaceState(_s, _t, url) {
      if (typeof url === "string" && url.includes("#")) location.hash = url.slice(url.indexOf("#"));
    } },
    localStorage: { mem: {}, getItem(k) { return this.mem[k] ?? null; }, setItem(k, v) { this.mem[k] = String(v); } },
    navigator: {},
    matchMedia() { return { matches: false }; },
    innerWidth: 390, devicePixelRatio: 1, scrollTo() {}, AbortController,
    document: {
      querySelector(sel) { const m = /^#([\w-]+)$/.exec(sel); return m ? nodes[m[1]] || null : null; },
      querySelectorAll() { return []; },
      createElement() { return makeEl(""); },
      body: { appendChild() {} },
    },
    fetch(url) {
      const u = String(url);
      if (u.includes("/api/stream")) {
        return Promise.resolve({ ok: true, status: 200, headers: { get: () => "" },
          body: { getReader() { return { read() { return new Promise(() => {}); } }; } } });
      }
      let resolve, reject;
      const p = new Promise((res, rej) => { resolve = res; reject = rej; });
      const slot = { url: u, resolve, reject, settled: false };
      pending.push(slot);
      return p;
    },
    Charts: { LineChart: function () { this.set = function () {}; }, ring() {}, candles() {} },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(app, context, { filename: "app.js" });
  context.localStorage.setItem("desk_token", "fixture");
  context.render();
  function book(name) {
    return { mode: "PAPER", balance: 200, today_pct: 0, multiplier: 1, running: 0, unread: 0, warning: null,
      agents: [], activity: [], server_time: "2026-11-08T13:00:00Z",
      positions: [{ name, size_usd: 18.5, unrealized_usd: name === "NEG" ? -2.54 : 3.34, unrealized_pct: name === "NEG" ? -21.15 : 18.06,
        entry_price: 0.00000421, last: name === "MISS" ? null : 0.00000505, last_at: name === "MISS" ? null : "2026-11-08T13:00:00Z",
        stop_price: 0.00000396, stop_pct: 6, trail_active: 0, exit_line: null,
        link: "https://pump.fun/coin/6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump" }] };
  }
  function stateSlots() { return pending.filter(p => !p.settled && p.url === "/api/state"); }
  function ok(slot, body) {
    slot.settled = true;
    slot.resolve({ ok: true, status: 200, headers: { get: (h) => h === "content-type" ? "application/json" : "" },
      json: async () => body, text: async () => JSON.stringify(body) });
  }
  function fail(slot) { slot.settled = true; slot.reject(new TypeError("network")); }
  function trades() { return nodes.trades ? nodes.trades.html : ""; }
  function banner() { return nodes.offline ? nodes.offline.html : ""; }
  async function flush() { await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
  function poll() { return intervals.find(t => t.ms === 30000); }
  return { context, clock: (t) => { clock = t; }, book, stateSlots, ok, fail, trades, banner, flush, timeouts, poll,
    appHtml: () => appEl.html };
}

test("older success does not replace a newer book or Stand time", async () => {
  const h = boot();
  h.clock(Date.parse("2026-11-08T13:00:00Z"));
  const first = h.context.loadState();
  const second = h.context.loadState();
  const slots = h.stateSlots();
  assert.equal(slots.length, 2);
  h.ok(slots[1], h.book("NEWBOOK"));
  await second; await h.flush();
  h.clock(Date.parse("2026-11-08T15:00:00Z"));
  h.ok(slots[0], h.book("OLDBOOK"));
  await first; await h.flush();
  assert.match(h.trades(), /NEWBOOK/);
  assert.doesNotMatch(h.trades(), /OLDBOOK/);
  assert.match(h.trades(), /Stand 14:00/);
  assert.doesNotMatch(h.trades(), /Stand 16:00/);
  assert.equal(h.banner(), "");
});

test("older failure does not offline a newer success or stall the poll", async () => {
  const h = boot();
  const first = h.context.loadState();
  const second = h.context.loadState();
  const slots = h.stateSlots();
  h.ok(slots[1], h.book("NEWBOOK"));
  await second; await h.flush();
  h.fail(slots[0]);
  await first; await h.flush();
  assert.match(h.trades(), /NEWBOOK/);
  assert.doesNotMatch(h.trades(), /Verbindung weg/);
  assert.equal(h.banner(), "");
  const before = h.stateSlots().length;
  h.poll().fn();
  assert.equal(h.stateSlots().length, before + 1);
});

test("newest failure marks offline and the poll does not start another state read", async () => {
  const h = boot();
  h.clock(Date.parse("2026-11-08T13:00:00Z"));
  const done = h.context.loadState();
  h.ok(h.stateSlots()[0], h.book("NEWBOOK"));
  await done; await h.flush();
  const again = h.context.loadState();
  h.fail(h.stateSlots()[0]);
  await again; await h.flush();
  assert.match(h.banner(), /Desk offline/);
  assert.match(h.trades(), /Verbindung weg/);
  assert.match(h.trades(), /Stand 14:00/);
  const n = h.stateSlots().length;
  h.poll().fn();
  assert.equal(h.stateSlots().length, n);
});

test("retry after the newest failure applies the next success and resumes polling", async () => {
  const h = boot();
  const done = h.context.loadState();
  h.ok(h.stateSlots()[0], h.book("NEWBOOK"));
  await done; await h.flush();
  const failed = h.context.loadState();
  h.fail(h.stateSlots()[0]);
  await failed; await h.flush();
  assert.match(h.banner(), /Desk offline/);
  const retry = h.timeouts.filter(t => t.ms === 5000 && !t.cleared).at(-1);
  assert.ok(retry);
  h.clock(Date.parse("2026-11-08T14:00:00Z"));
  const recovered = retry.fn();
  h.ok(h.stateSlots()[0], h.book("RECOVERED"));
  await recovered; await h.flush();
  assert.match(h.trades(), /RECOVERED/);
  assert.doesNotMatch(h.trades(), /Verbindung weg/);
  assert.equal(h.banner(), "");
  const n = h.stateSlots().length;
  h.poll().fn();
  assert.equal(h.stateSlots().length, n + 1);
});

test("a stream connect does not clear a stale snapshot", async () => {
  const h = boot();
  const done = h.context.loadState();
  h.ok(h.stateSlots()[0], h.book("NEWBOOK"));
  await done; await h.flush();
  const failed = h.context.loadState();
  h.fail(h.stateSlots()[0]);
  await failed; await h.flush();
  assert.match(h.banner(), /Desk offline/);
  h.context.sse();
  await h.flush();
  assert.match(h.banner(), /Desk offline/);
  assert.match(h.trades(), /Verbindung weg/);
  const n = h.stateSlots().length;
  h.poll().fn();
  assert.equal(h.stateSlots().length, n);
});

test("first load failure replaces the skeleton with an unavailable stand", async () => {
  const h = boot();
  assert.match(h.appHtml(), /id="trades"[^>]*>\s*<div class="loading"/);
  const done = h.context.loadState();
  h.fail(h.stateSlots()[0]);
  await done; await h.flush();
  assert.match(h.trades(), /Stand nicht verfügbar/);
  assert.doesNotMatch(h.trades(), /loading/);
  assert.doesNotMatch(h.trades(), /Keine offenen PAPER-Trades/);
});

test("narrow trade title ellipsizes and the stylesheet is cache-busted", () => {
  const css = fs.readFileSync(path.join(root, "app.css"), "utf8");
  const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
  assert.match(css, /#trades \.nm \.t1\{[^}]*text-overflow:\s*ellipsis/);
  assert.match(html, /href="\/app\.css\?v=20261108-open-trades"/);
  assert.match(app, /<span style="\$\{old \? "color:var\(--orange\)" : ""\}">Kurs /);
  assert.doesNotMatch(app, /<span class="num" style="\$\{old \? "color:var\(--orange\)"/);
});
