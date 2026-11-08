/* Desk app. Token: {URL}#t=TOKEN -> localStorage, then removed from the URL. Every /api call sends
   Authorization: Bearer. SSE is read with fetch() (header auth). Links only come from API `link` fields. */
"use strict";
const $ = (s, r = document) => r.querySelector(s), esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const RM = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const TK = "desk_token";
(function takeToken() {
  const m = location.hash.match(/(?:^#|&)t=([^&]+)/);
  if (m) { localStorage.setItem(TK, decodeURIComponent(m[1])); history.replaceState(null, "", location.pathname + "#/home"); }
})();
const token = () => localStorage.getItem(TK);
const S = { state: null, lastOk: null, offline: false, snapshotStale: false, stateRetry: null, retryAt: 0, range: "LIVE", live: {}, chart: null, settings: null, account: null };

const CACHE = {};   // last good GET per path: shown when the desk is offline ("keep the last good numbers")
async function api(path, opt = {}) {
  let r;
  try {
    r = await fetch("/api/" + path, { ...opt, cache: "no-store",
      headers: { "Authorization": "Bearer " + token(), "ngrok-skip-browser-warning": "1", ...(opt.body ? { "Content-Type": "application/json" } : {}), ...(opt.headers || {}) } });
  } catch (e) {
    if (!opt.method && CACHE[path]) {
      setOffline(5);
      const err = new Error("Desk offline");
      err.stale = true;
      err.body = CACHE[path];
      throw err;
    }
    throw e;
  }
  if (r.status === 401) { S.unauth = true; render(); throw new Error("unauthorized"); }
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) { const e = new Error((body && body.error) || (body && body.detail) || ("HTTP " + r.status)); e.status = r.status; e.body = body; throw e; }
  if (!opt.method) CACHE[path] = body;
  return body;
}
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });

/* ---------- format */
const money = v => v == null ? "—" : (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const big$ = v => v == null ? "—" : v >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? "$" + (v / 1e3).toFixed(1) + "K" : "$" + v.toFixed(0);
const pct = v => v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
const hm = iso => iso ? new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" }) : "—";
const price = p => p == null ? "—" : p >= 1 ? "$" + p.toFixed(4) : "$" + p.toPrecision(4);
const ago = iso => { if (!iso) return ""; const m = (Date.now() - Date.parse(iso)) / 60000; return m < 60 ? Math.round(m) + "m" : (m / 60).toFixed(m < 600 ? 1 : 0) + "h"; };

/* ---------- odometer: each changed digit rolls 600ms ease-out, 30ms stagger right to left */
/* tiny prices as $0.0₄3959 so the 66px number fits 390px */
function bigPrice(v) {
  if (v == null) return "—";
  if (v >= 0.001) return esc(price(v));
  const s = v.toFixed(20).split(".")[1], z = s.match(/^0*/)[0].length, sub = String(z).split("").map(d => "₀₁₂₃₄₅₆₇₈₉"[d]).join("");
  return `$0.0<span style="font-size:.5em">${sub}</span>${s.slice(z, z + 4)}`;
}
function odometer(el, text) {
  const prev = el.dataset.v || "";
  if (prev === text) return;
  el.dataset.v = text;
  if (RM() || prev.length !== text.length) {
    el.innerHTML = [...text].map(ch => /\d/.test(ch) ? `<span class="d"><span class="s" style="transform:translateY(-${ch * 1.05}em)">${[...Array(10).keys()].map(i => `<span>${i}</span>`).join("")}</span></span>` : `<span>${esc(ch)}</span>`).join("");
    return;
  }
  const strips = el.querySelectorAll(".s"); let k = 0;
  const digits = [...text].filter(c => /\d/.test(c)), old = [...prev].filter(c => /\d/.test(c));
  const n = digits.length;
  strips.forEach((s, i) => {
    if (digits[i] !== old[i]) { const delay = (n - 1 - i) * 30; s.style.transitionDelay = delay + "ms"; s.style.transform = `translateY(-${digits[i] * 1.05}em)`; k++; }
  });
  [...el.children].forEach((c, i) => { if (!c.classList.contains("d")) c.textContent = text[i]; });
}

/* ---------- SSE over fetch */
let sseCtl = null, sseBack = 1;
async function sse() {
  if (!token()) return;
  sseCtl = new AbortController();
  try {
    const r = await fetch("/api/stream", { headers: { "Authorization": "Bearer " + token(), "ngrok-skip-browser-warning": "1" }, signal: sseCtl.signal, cache: "no-store" });
    if (r.status === 401) { S.unauth = true; render(); return; }
    if (!r.ok || !r.body) throw new Error("stream " + r.status);
    setOnline(); sseBack = 1;
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) { const chunk = buf.slice(0, i); buf = buf.slice(i + 2); onChunk(chunk); }
    }
    throw new Error("stream closed");
  } catch (e) {
    if (e.name === "AbortError") return;
    setOffline(sseBack); setTimeout(sse, sseBack * 1000); sseBack = Math.min(30, sseBack * 2);
  }
}
function onChunk(c) {
  let ev = "message", data = "";
  for (const l of c.split("\n")) { if (l.startsWith("event:")) ev = l.slice(6).trim(); else if (l.startsWith("data:")) data += l.slice(5).trim(); }
  if (!data) return;
  let d; try { d = JSON.parse(data); } catch { return; }
  onEvent(ev, d);
}
let refreshT = null;
function refreshSoon() { clearTimeout(refreshT); refreshT = setTimeout(loadState, 400); }
function onEvent(ev, d) {
  if (ev === "balance") {
    if (S.state && !S.snapshotStale && !S.offline) { S.state.balance = d.balance; paintBalance(); }
    if (route().name === "home" && !S.offline) loadChart(true);
    refreshSoon();
    return;
  }
  if (ev === "audit_start") { S.live.audit = { mint: d.mint, name: d.name, layers: {} }; paintCards(); }
  if (ev === "audit_layer") { if (!S.live.audit || S.live.audit.mint !== d.mint) S.live.audit = { mint: d.mint, layers: {} }; S.live.audit.layers[d.layer] = d; paintCards(); AuditScreen.onLayer(d); }
  if (ev === "signal") { S.live.exec = { ...d, t0: Date.now() }; paintCards(); }
  if (ev === "fill") { if (S.live.exec) S.live.exec.filled = true; paintCards(); }
  refreshSoon();
}

/* ---------- offline row */
let offT = null;
function retryState(n) {
  if (S.stateRetry) return;
  S.stateRetry = setTimeout(() => { S.stateRetry = null; loadState(); }, Math.max(1000, n * 1000));
}
function setOffline(n) {
  S.offline = true; S.snapshotStale = true; S.retryAt = Date.now() + n * 1000; clearInterval(offT);
  const tick = () => { const el = $("#offline"); if (!el) return; const s = Math.max(0, Math.ceil((S.retryAt - Date.now()) / 1000));
    el.innerHTML = `<div class="err" role="alert">Desk offline · retrying in ${s}s · last update ${S.lastOk ? hm(S.lastOk) : "—"}</div>`; };
  tick(); offT = setInterval(tick, 1000);
  if (S.state && route().name === "home") paintHome();
  retryState(n);
}
function setOnline() { S.offline = false; clearInterval(offT); const el = $("#offline"); if (el) el.innerHTML = ""; }

/* screen-level failure: spec error row + retry in 5s on the same route; 404 is empty, not offline */
function failScreen(sel, e, keep = "") {
  const el = $(sel); if (!el) return;
  if (e && e.status === 404) { el.innerHTML = keep + '<div class="empty">Not on the desk yet · search its mint</div>'; return; }
  const h = location.hash; let n = 5;
  const paint = () => { const x = $(sel); if (!x || location.hash !== h) return clearInterval(t);
    x.innerHTML = keep + `<div class="err" role="alert">Desk offline · retrying in ${n}s · last update ${S.lastOk ? hm(S.lastOk) : "—"}</div>`;
    if (n-- <= 0) { clearInterval(t); route(); } };
  const t = setInterval(paint, 1000); paint();
}

/* ---------- router */
function route() {
  const h = location.hash.replace(/^#\/?/, "") || "home"; const [name, arg] = h.split("/");
  return { name: ["home", "agents", "activity", "account", "coin", "audit"].includes(name) ? name : "home", arg: arg && decodeURIComponent(arg) };
}
const ICON = {
  home: '<svg viewBox="0 0 24 24"><path d="M3 11 12 4l9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></svg>',
  agents: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M8 9h8M8 13h5"/></svg>',
  activity: '<svg viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
  account: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
  bell: '<svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/></svg>',
};
function tabbar(cur) {
  return `<nav class="tabbar">${[["home", "Home"], ["agents", "Agents"], ["activity", "Activity"], ["account", "Account"]].map(([k, l]) =>
    `<a href="#/${k}" class="${cur === k ? "on" : ""}" aria-label="${l}">${ICON[k]}<span>${l}</span></a>`).join("")}</nav>`;
}
function navbar() {
  const unread = S.state && S.state.unread > 0;
  return `<div class="nav"><a class="avatar" href="#/account" aria-label="Account">D</a><a class="who" href="#/account">Grok Bot <span>›</span></a>
    <button class="iconbtn" id="searchBtn" aria-label="Search">${ICON.search}</button>
    <button class="iconbtn" id="bellBtn" aria-label="Notifications">${ICON.bell}${unread ? '<i class="dot"></i>' : ""}</button></div><div id="offline"></div>`;
}
const backbar = (to = "#/home", label = "Back") => `<div class="nav"><a class="back" href="${to}" onclick="if(history.length>1){history.back();return false}">‹ ${label}</a></div><div id="offline"></div>`;

function render() {
  const app = $("#app");
  if (!token() || S.unauth) {
    app.innerHTML = `<div class="gate"><div class="title" style="color:#fff">Desk</div><p>Open the app with your private link.<br>This device has no access key${S.unauth ? " (the saved one was refused)" : ""}.</p>
      <form id="keyForm" style="margin-top:24px;display:flex;flex-direction:column;gap:12px;width:100%;max-width:320px">
        <input id="keyIn" type="password" autocomplete="current-password" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="Passwort"
          style="font-size:17px;padding:14px;border-radius:12px;border:1px solid #333;background:#111;color:#fff">
        <button type="submit" style="font-size:17px;padding:14px;border-radius:12px;border:0;background:#0a84ff;color:#fff;font-weight:600">Entsperren</button>
      </form></div>`;
    const f = $("#keyForm");
    if (f) f.onsubmit = e => { e.preventDefault(); const v = $("#keyIn").value.trim(); if (!v) return; localStorage.setItem(TK, v); location.hash = "#/home"; location.reload(); };
    return;
  }
  const r = route();
  ({ home: Home, agents: Agents, activity: Activity, account: Account, coin: Coin, audit: AuditScreen.render })[r.name](app, r.arg);
  if (S.offline) setOffline(Math.max(1, Math.ceil((S.retryAt - Date.now()) / 1000)));
  window.scrollTo(0, 0);
}
addEventListener("hashchange", render);

/* ---------- state */
async function loadState() {
  try {
    const body = await api("state");
    S.state = body;
    S.lastOk = new Date().toISOString();
    S.snapshotStale = false;
    setOnline();
    paintHome();
  } catch (e) {
    if (e.message === "unauthorized") return;
    if (e.stale) {
      if (!S.state) S.state = e.body;
      paintHome();
      return;
    }
    setOffline(5);
  }
}

/* ---------- HOME */
function Home(app) {
  app.innerHTML = `${navbar()}<div class="screen">
    <div class="balance"><div class="big num odo" id="bal">${S.state ? "" : '<span class="loading" style="width:240px;height:66px;display:block"></span>'}</div><span id="paper"></span></div>
    <div class="sub num" id="today">${S.state ? "" : '<span class="loading" style="width:120px;height:18px;display:block"></span>'}</div>
    <div id="warn"></div>
    <div class="sect"><h2>Offene PAPER-Trades <span id="openN"></span></h2></div>
    <div id="trades">${S.state ? "" : '<div class="loading" style="height:88px"></div>'}</div>
    <div class="chartwrap ${S.chartData ? "" : "loading"}"><canvas id="chart"></canvas></div>
    <div class="ranges">${["LIVE", "1H", "4H", "1D", "1W", "ALL"].map(k => `<button data-r="${k}" class="${S.range === k ? "on" : ""}">${k}</button>`).join("")}</div>
    <div class="sect"><h2>Agents <span id="running">· ${S.state ? S.state.running : "…"} running</span></h2></div>
    <div class="carousel" id="cards">${S.state ? "" : [0, 1].map(() => `<div class="card loading" style="${cardStyle()}"></div>`).join("")}</div>
    <div class="sect"><h2>Activity</h2><a href="#/activity">See all</a></div>
    <div id="act">${S.state ? "" : `<div class="list loading" style="height:300px"></div>`}</div>
  </div>${tabbar("home")}`;
  app.querySelectorAll(".ranges button").forEach(b => b.onclick = () => { S.range = b.dataset.r; app.querySelectorAll(".ranges button").forEach(x => x.classList.toggle("on", x === b)); S.chartData = null; loadChart(false); });
  wireNav();
  S.chart = new Charts.LineChart($("#chart"));
  if (S.chartData) S.chart.set(S.chartData.points, S.chartData.start, S.chartData.marks, false);
  paintHome(); loadChart(false);
}
function cardStyle() { const w = Math.min(innerWidth, 500) - 32; return `width:${w}px;aspect-ratio:504/470;border-radius:${42 * w / 504}px`; }
function paintBalance() {
  const el = $("#bal"); if (!el || !S.state) return;
  odometer(el, money(S.state.balance));
  const p = $("#paper"); if (p) p.innerHTML = S.state.mode === "PAPER" ? '<span class="pill paper">PAPER</span>' : "";
}
function standLine() {
  const when = S.lastOk ? hm(S.lastOk) : "—";
  if (S.snapshotStale || S.offline) return `Stand ${when} · Verbindung weg`;
  if (!S.lastOk) return "";
  return `Stand ${when}`;
}
function tradeCard(p, serverTime) {
  const usd = p.unrealized_usd, has = usd != null && p.unrealized_pct != null;
  const cls = !has ? "" : usd > 0 ? "up" : usd < 0 ? "down" : "";
  const pnl = has ? `${money(usd)} · ${pct(p.unrealized_pct)}` : "—";
  const kurs = p.last == null ? "kein Kurs" : price(p.last);
  const kursTime = p.last_at ? `Kurs ${hm(p.last_at)}` : "";
  const old = p.last_at && serverTime && (Date.parse(serverTime) - Date.parse(p.last_at) > 90000);
  const stop = p.stop_price == null ? "—" : (p.stop_pct == null ? price(p.stop_price) : `${price(p.stop_price)} · -${p.stop_pct}%`);
  const trail = p.trail_active && p.exit_line != null ? price(p.exit_line) : "Trail noch nicht aktiv";
  const link = p.link ? `<a class="btn s" href="${esc(p.link)}" target="_blank" rel="noopener">Auf pump.fun</a>` : "";
  return `<div class="pos"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px"><div class="t1" style="font-weight:600">${esc(p.name)}</div><div class="val num ${cls}">${pnl}</div></div>
    <div class="krow"><span>Einsatz</span><span class="num">${money(p.size_usd)}</span></div>
    <div class="krow"><span>Unrealisiert</span><span class="num ${cls}">${pnl}</span></div>
    <div class="krow"><span>Einstieg</span><span class="num">${price(p.entry_price)}</span></div>
    <div class="krow"><span>Kurs</span><span class="num" style="${old ? "color:var(--orange)" : ""}">${kurs}${kursTime ? " · " + kursTime : ""}</span></div>
    <div class="krow"><span>Stop</span><span class="num">${stop}</span></div>
    <div class="krow"><span>Trail</span><span class="num">${trail}</span></div>
    ${link}</div>`;
}
function tradesHtml(st) {
  if (!st) return "";
  if (st.mode !== "PAPER") return `<div class="err">Desk ist nicht im PAPER-Modus</div>`;
  const stand = standLine();
  const head = stand ? `<div class="sub num">${esc(stand)}</div>` : "";
  const rows = st.positions || [];
  if (!rows.length) return head + `<div class="empty">Keine offenen PAPER-Trades</div>`;
  return head + rows.map(p => tradeCard(p, st.server_time)).join("");
}
function paintHome() {
  if (route().name !== "home" || !S.state || !$("#today") || !$("#trades")) return;
  const st = S.state;
  paintBalance();
  $("#today").innerHTML = `<span class="${st.today_pct >= 0 ? "up" : "down"}">${pct(st.today_pct)}</span> today <span class="pill ${st.multiplier >= 1 ? "g" : "r"}">${st.multiplier.toFixed(2)}×</span>`;
  $("#warn").innerHTML = st.warning ? `<div class="err" style="color:var(--orange);background:rgba(255,159,10,.14)">${esc(st.warning)}</div>` : "";
  const openN = $("#openN"); if (openN) openN.textContent = st.mode === "PAPER" && st.positions ? `· ${st.positions.length}` : "";
  const trades = $("#trades"); if (trades) trades.innerHTML = tradesHtml(st);
  $("#running").textContent = `· ${st.running} running`;
  paintCards();
  $("#act").innerHTML = actList(st.activity);
  wireRows($("#act"));
  const bell = $("#bellBtn"); if (bell) bell.innerHTML = ICON.bell + (st.unread > 0 ? '<i class="dot"></i>' : "");
}
async function loadChart(animate) {
  try {
    const d = await api("chart?range=" + S.range);
    S.chartData = d; const w = $(".chartwrap"); if (w) w.classList.remove("loading");
    if (S.chart && route().name === "home") S.chart.set(d.points, d.start, d.marks, animate);
  } catch (e) { /* keep the last good chart; offline row shows */ }
}

/* ---------- agent cards */
const AC = { scanner: "#64d2ff", auditor: "#0a84ff", analyst: "#ffd60a", executor: "#00d35a", risk: "#ff6b9a" };
const AN = { scanner: "Scanner", auditor: "Auditor", analyst: "Analyst", executor: "Executor", risk: "Risk" };
function hbState(a) { if (a.paused) return "Paused"; if (!a.heartbeat) return "Starting"; return (Date.now() - Date.parse(a.heartbeat)) / 1000 > 120 ? "No heartbeat" : "Running"; }
function card(a, full) {
  const style = full ? "width:100%;aspect-ratio:504/470;border-radius:" + 42 * (Math.min(innerWidth, 500) - 32) / 504 + "px" : cardStyle();
  const head = `<div class="head"><i style="background:${AC[a.name]}"></i>${AN[a.name]}<span class="state">${hbState(a)}</span></div>`;
  let body = "";
  if (a.name === "scanner") {
    body = `<div class="kpi num">${a.pools}<small>pools</small></div>` + (a.rows.length ? `<div>${a.rows.map(r =>
      `<a class="krow ${r.killed ? "kill" : ""}" href="${esc(r.link)}" target="_blank" rel="noopener"><span class="n">${esc(r.name)}</span><span class="r" style="color:${r.killed ? "var(--red)" : "var(--green)"}">${r.killed ? esc(r.reason) : "→ auditor"}</span></a>`).join("")}</div>`
      : `<div class="foot" style="margin-top:12px">Listening for graduations</div>`);
  } else if (a.name === "auditor") {
    const live = S.live.audit, L = {};
    (a.layers || []).forEach(l => L[l.layer] = { pass: l.pass === 1 ? true : l.pass === 0 ? false : null, value: l.value_text, name: l.name });
    const useLive = live && Object.keys(live.layers).length < 8 && live.mint !== a.mint ? true : live && live.mint === a.mint && Object.keys(live.layers).length < (a.layers || []).length ? false : !!live;
    const src = useLive ? live.layers : L;
    const n = Object.keys(src).length, red = Object.values(src).find(l => l.pass === false);
    const line = !a.enabled ? "Take-apart is OFF" : n === 0 ? "No coin taken apart yet" : n < 8 && !red ? "taking apart..." : red ? esc(red.value) : "8/8 → Executor";
    body = `<div class="kpi num">${a.taken}<small>taken apart</small></div><div class="strips">${[1, 2, 3, 4, 5, 6, 7, 8].map(i => {
      const l = src[i]; return `<div class="strip ${l ? (l.pass === true ? "ok" : l.pass === false ? "bad" : "") : ""}">${l ? esc((l.name || "").split(" ")[0]) : ""}</div>`; }).join("")}</div>
      <div style="margin-top:10px;font-size:15px;${red ? "color:var(--red)" : ""}">${line}</div><div class="foot">${a.rejected || 0} rejected</div>`;
  } else if (a.name === "analyst") {
    body = `<div style="color:var(--t2);font-size:13px;margin-top:6px">Scoring${a.coin ? " · " + esc(a.coin) : ""}</div>
      <div class="ring"><canvas data-ring="${a.score ?? ""}" data-min="${a.min_score}" style="width:118px;height:118px"></canvas><div class="v num">${a.score ?? "—"}</div></div>
      <div class="foot">${a.score == null ? "No coin scored yet" : (a.passed ? "Passed · " : "Rejected · ") + "green from " + a.min_score} · ${esc(a.mode)}</div>`;
  } else if (a.name === "executor") {
    const ex = S.live.exec;
    let bar = "";
    if (ex) { const p = ex.filled ? 100 : Math.min(95, Math.round((Date.now() - ex.t0) / 30)); bar = `<div class="bar"><i style="width:${p}%"></i></div><div style="font-size:14px">${ex.filled ? "✓ Filled" : "Executing... " + p + "%"}</div>`; }
    body = `<div class="kpi num">${a.trades}<small>trades</small></div>
      <div style="font-size:15px">${a.last ? money(a.last.size) + " · " + (a.last.pct ?? a.stack_pct) + "% of stack" : "No trade yet tonight · " + a.stack_pct + "% of stack"}</div>${bar}`;
  } else if (a.name === "risk") {
    body = `<div style="color:var(--t2);font-size:13px;margin-top:6px">Guarding</div><div class="kpi num">${a.guarding}<small>open</small></div>
      <div style="font-size:15px">${a.last_exit === "trail" ? "Trailed out" : a.last_exit === "stop" ? "Stopped" : a.last_exit ? esc(a.last_exit) : "No exit yet"}</div>
      <div class="pills"><span class="pill r">stop -${a.stop_pct}%</span><span class="pill g">trail ${a.trail_pct}%</span></div>`;
  }
  return `<div class="card" data-agent="${a.name}" style="${style}">${head}${body}</div>`;
}
function paintCards() {
  const el = $("#cards"); if (!el || !S.state) return;
  const sl = el.scrollLeft; el.innerHTML = S.state.agents.map(a => card(a)).join(""); el.scrollLeft = sl;
  el.querySelectorAll("canvas[data-ring]").forEach(c => Charts.ring(c, c.dataset.ring === "" ? null : +c.dataset.ring, +c.dataset.min));
  el.querySelectorAll(".card").forEach(c => c.onclick = e => { if (!e.target.closest("a")) location.hash = "#/agents"; });
  if (S.live.exec && !S.live.exec.filled) setTimeout(paintCards, 300);
}

/* ---------- activity rows */
const KIND_IC = { bought: "↗", sold: "✓", stopped: "↘", rejected: "✕" };
function actList(rows, empty = "Nothing yet tonight") {
  if (!rows || !rows.length) return `<div class="empty">${empty}</div>`;
  return `<div class="list">${rows.map(r => `<div class="row" data-kind="${esc(r.kind)}" data-mint="${esc(r.mint)}" role="button" tabindex="0">
    <div class="ic ${esc(r.kind)}">${KIND_IC[r.kind] || "•"}</div><div class="tx"><div class="t1">${esc(r.title)}</div><div class="t2">${esc(r.subtitle)}</div></div>
    <div class="val num ${String(r.value).startsWith("+") ? "up" : String(r.value).startsWith("-") ? "down" : ""}">${esc(r.value)}<small>${esc(r.time)}</small></div></div>`).join("")}</div>`;
}
function wireRows(root) {
  root.querySelectorAll(".row[data-mint]").forEach(r => r.onclick = () => {
    const m = r.dataset.mint; if (!m) return;
    location.hash = r.dataset.kind === "rejected" ? "#/audit/" + encodeURIComponent(m) : "#/coin/" + encodeURIComponent(m);
  });
}
function wireNav() {
  const s = $("#searchBtn"), b = $("#bellBtn");
  if (s) s.onclick = openSearch;
  if (b) b.onclick = openPushes;
}
function sheet(html) {
  const d = document.createElement("div"); d.className = "sheet"; d.innerHTML = `<div class="in">${html}</div>`;
  d.onclick = e => { if (e.target === d) d.remove(); }; document.body.appendChild(d); return d;
}
function openSearch() {
  const d = sheet(`<div class="cmd" style="padding:0 0 12px"><input id="q" placeholder="Name, symbol or mint" autocomplete="off" autocapitalize="off"><button class="pill n" id="qgo" style="min-height:44px">Find</button></div><div id="qr"></div>`);
  const go = async () => {
    const q = $("#q", d).value.trim(); if (!q) return;
    $("#qr", d).innerHTML = '<div class="list loading" style="height:60px"></div>';
    try { const r = await post("command", { text: "why " + q }); $("#qr", d).innerHTML = `<div class="out" style="padding:0">${linkify(r.text)}</div>`;
      const m = (r.text.match(/pump\.fun\/coin\/([1-9A-HJ-NP-Za-km-z]{32,44})/) || [])[1];
      if (m) $("#qr", d).insertAdjacentHTML("beforeend", `<a class="btn s" href="#/coin/${m}">Open coin</a><a class="btn s" href="#/audit/${m}">Open Auditor</a>`);
      d.querySelectorAll("a[href^='#']").forEach(a => a.addEventListener("click", () => d.remove()));
    } catch (e) { $("#qr", d).innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  $("#qgo", d).onclick = go; $("#q", d).onkeydown = e => { if (e.key === "Enter") go(); }; $("#q", d).focus();
}
async function openPushes() {
  const d = sheet('<div class="list loading" style="height:200px"></div>');
  try {
    const r = await api("pushes");
    d.querySelector(".in").innerHTML = `<div class="sect" style="margin-top:0"><h2>Pushes</h2></div>` + (r.rows.length ? `<div class="list">${r.rows.map(p =>
      `<a class="row" href="${esc(p.url)}" target="_blank" rel="noopener"><div class="tx"><div class="t1">${esc(p.title)}</div><div class="t2">${esc(p.body)} · ${hm(p.ts)}</div></div></a>`).join("")}</div>` : '<div class="empty">No pushes yet</div>');
    post("pushes/seen").then(() => { if (S.state) { S.state.unread = 0; paintHome(); } });
  } catch (e) { d.querySelector(".in").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
function linkify(t) { return esc(t).replace(/(https:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:var(--blue)">$1</a>'); }

/* ---------- AGENTS */
async function Agents(app) {
  app.innerHTML = `${backbarless()}<div class="screen"><div class="title">Agents</div><div id="ag">${[0, 1, 2].map(() => `<div class="card loading" style="width:100%;aspect-ratio:504/470;border-radius:30px;margin-bottom:12px"></div>`).join("")}</div></div>${tabbar("agents")}`;
  wireNav();
  if (!S.state) await loadState();
  if (!S.state) { $("#ag").innerHTML = `<div class="err">Desk offline · no agent data yet</div>`; return; }
  const decs = await Promise.all(S.state.agents.map(a => api(`agents/${a.name}/decisions`).catch(() => null)));
  $("#ag").innerHTML = S.state.agents.map((a, i) => {
    const d = decs[i], lock = a.name === "risk" && a.locked;
    return `<div style="margin-bottom:22px">${card(a, true)}
      <div class="list" style="margin-top:10px"><div class="row"><div class="tx"><div class="t1">${a.paused ? "Paused" : "Running"}</div><div class="t2">${lock ? "Locked while a position is open" : "Pause or resume " + AN[a.name]}</div></div>
      <button class="switch ${a.paused ? "" : "on"} ${lock ? "lock" : ""}" data-pause="${a.name}" aria-label="Pause ${AN[a.name]}" style="min-height:31px"></button></div>
      <a class="row" href="#/account" data-set="${a.name}"><div class="tx"><div class="t1">Settings</div></div><span style="color:var(--t2)">›</span></a></div>
      <div class="grp">Last 20 decisions</div>
      ${!d ? '<div class="err">Couldn\'t load decisions</div>' : d.rows.length ? `<div class="list decisions">${d.rows.map(r => `<div class="row"><div class="tx"><div class="t1">${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.name || "coin")}</a>` : esc(r.name || "—")} · <span class="${r.ok ? "up" : "down"}">${r.ok ? "pass" : "stop"}</span></div><div class="t2">${esc(r.text)}</div></div><div class="val num"><small>${esc(r.time)}</small></div></div>`).join("")}</div>` : '<div class="empty">Nothing yet tonight</div>'}
    </div>`;
  }).join("");
  $("#ag").querySelectorAll("canvas[data-ring]").forEach(c => Charts.ring(c, c.dataset.ring === "" ? null : +c.dataset.ring, +c.dataset.min));
  $("#ag").querySelectorAll("[data-set]").forEach(a => a.onclick = () => { S.jump = a.dataset.set; });
  $("#ag").querySelectorAll("[data-pause]").forEach(b => b.onclick = async () => {
    const n = b.dataset.pause, on = b.classList.contains("on");
    try { await post(`agents/${n}/${on ? "pause" : "resume"}`); await loadState(); Agents(app); } catch (e) { toast(e.message); }
  });
}
const backbarless = () => `<div class="nav"><a class="avatar" href="#/account">D</a><a class="who" href="#/account">Grok Bot <span>›</span></a><button class="iconbtn" id="searchBtn" aria-label="Search">${ICON.search}</button><button class="iconbtn" id="bellBtn" aria-label="Notifications">${ICON.bell}${S.state && S.state.unread ? '<i class="dot"></i>' : ""}</button></div><div id="offline"></div>`;

/* ---------- ACTIVITY */
async function Activity(app) {
  app.innerHTML = `${backbarless()}<div class="screen"><div class="title">Activity</div><div id="al"><div class="list loading" style="height:420px"></div></div><div id="more"></div></div>${tabbar("activity")}`;
  wireNav();
  const rows = []; let next = null;
  const load = async () => {
    try { const r = await api("activity" + (next ? "?before=" + next : "")); rows.push(...r.rows); next = r.next;
      $("#al").innerHTML = actList(rows); wireRows($("#al"));
      $("#more").innerHTML = next ? '<button class="btn s" id="mb">Load more</button>' : ""; if (next) $("#mb").onclick = load;
    } catch (e) { failScreen("#al", e, rows.length ? actList(rows) : ""); }
  };
  load();
}

/* ---------- AUDITOR SCREEN: 8 discs, beam 350ms per layer, then 150ms to green/red. Waits on a layer if the server is slower. */
const AuditScreen = {
  cur: null,
  async render(app, mint) {
    app.innerHTML = `${backbar()}<div class="screen"><div class="title" id="an">Auditor</div><div id="au"><div class="loading" style="height:360px"></div></div></div>${tabbar("")}`;
    AuditScreen.cur = null;
    try {
      if (!mint) { const l = await api("audits"); if (!l.rows.length) { $("#au").innerHTML = '<div class="empty">No coin taken apart yet</div>' + toggleRow(); wireToggle(); return; } mint = l.rows[0].mint; }
      const d = await api("audit/" + encodeURIComponent(mint));
      $("#an").textContent = d.name;
      if (!d.layers.length) { $("#au").innerHTML = '<div class="empty">No coin taken apart yet</div>' + toggleRow(d.enabled) + `<a class="btn" href="${esc(d.link)}" target="_blank" rel="noopener">Open on pump.fun</a>`; wireToggle(); return; }
      const byL = {}; d.layers.forEach(l => byL[l.layer] = l);
      $("#au").innerHTML = `<div class="discs">${[1, 2, 3, 4, 5, 6, 7, 8].map(i => `<div class="disc" id="dz${i}"><div class="c">${i}</div><div class="n">${esc((byL[i] || {}).name || "")}</div><div class="v num" id="dv${i}"></div></div>`).join("")}</div>
        <div class="summary" id="sum"></div><div id="sum2" style="color:var(--t2)"></div>${toggleRow(d.enabled)}<a class="btn" href="${esc(d.link)}" target="_blank" rel="noopener">Open on pump.fun</a>`;
      wireToggle();
      AuditScreen.cur = { mint, d, byL, i: 0 };
      AuditScreen.step();
    } catch (e) { failScreen("#au", e); }
  },
  step() {
    const c = AuditScreen.cur; if (!c) return;
    c.i++; if (c.i > 8) return AuditScreen.done();
    const el = $("#dz" + c.i); if (!el) return;
    const show = () => { if (!el.isConnected || AuditScreen.cur !== c) return; const l = c.byL[c.i]; if (!l) { c.waiting = true; return; } // wait on this layer for the server
      c.waiting = false; el.classList.remove("scan"); el.classList.add(l.pass === 1 ? "ok" : l.pass === 0 ? "bad" : "nc");
      el.querySelector(".c").textContent = l.pass === 1 ? "✓" : l.pass === 0 ? "✕" : "·"; $("#dv" + c.i).textContent = l.value_text;
      $("#dv" + c.i).style.color = l.pass === 0 ? "var(--red)" : l.pass === null ? "var(--t3)" : "";
      if (RM()) AuditScreen.step(); else setTimeout(AuditScreen.step, 150); };
    if (RM()) return show();
    el.classList.add("scan"); el.classList.add("beam"); setTimeout(show, 350);
  },
  onLayer(d) { const c = AuditScreen.cur; if (!c || c.mint !== d.mint) return; c.byL[d.layer] = { layer: d.layer, name: d.name, value_text: d.value, pass: d.pass === true ? 1 : d.pass === false ? 0 : null };
    if (c.waiting && d.layer === c.i) { c.i--; AuditScreen.step(); } },
  async done() {
    const c = AuditScreen.cur; if (!c || !$("#sum")) return; const ls = Object.values(c.byL), red = ls.find(l => l.pass === 0);
    if (red) { $("#sum").innerHTML = `<span style="color:var(--red)">Rejected · ${esc(red.value_text)}</span>`; $("#sum2").textContent = `Grok Bot won't buy ${c.d.name}`; return; }
    $("#sum").innerHTML = `<span style="color:var(--green)">Cleared · ${ls.filter(l => l.pass === 1).length}/8 parts</span>`;
    try { const coin = await api("coin/" + encodeURIComponent(c.mint)); const p = coin.position;
      $("#sum2").textContent = p ? `Sent to Executor · ${money(p.size_usd)}` : "Sent to Analyst"; } catch { }
  },
};
function toggleRow(on = true) { return `<div class="list" style="margin-top:16px"><div class="row"><div class="tx"><div class="t1">Take apart before buying</div><div class="t2">Auditor's 8 layers</div></div><button class="switch ${on ? "on" : ""}" id="tg" aria-label="Take apart before buying"></button></div></div>`; }
function wireToggle() {
  const b = $("#tg"); if (!b) return;
  b.onclick = async () => {
    const on = b.classList.contains("on");
    if (on) { if (!confirm("Turn off take-apart? Coins would go to Analyst unchecked.")) return; if (!confirm("Sure? Every coin skips all 8 safety layers.")) return; }
    try { await post("settings", { key: "auditor.enabled", value: !on }); b.classList.toggle("on", !on); } catch (e) { toast(e.message); }
  };
}

/* ---------- COIN */
async function Coin(app, mint) {
  app.innerHTML = `${backbar()}<div class="screen" id="cs"><div class="loading" style="height:64px;margin:8px 0"></div><div class="loading" style="height:80px;margin:8px 0"></div><div class="loading" style="height:260px;margin:8px 0"></div><div class="stats">${"<div class='stat loading' style='height:64px'></div>".repeat(4)}</div></div>${tabbar("")}`;
  let d, au;
  try { [d, au] = await Promise.all([api("coin/" + encodeURIComponent(mint)), api("audit/" + encodeURIComponent(mint)).catch(() => null)]); }
  catch (e) { failScreen("#cs", e); return; }
  const c = d.coin, p = d.position, open = p && !p.closed_at, last = d.candles.length ? d.candles[d.candles.length - 1].c : (p ? p.last : null);
  const parts = au && au.layers.length ? au.layers.filter(l => l.pass === 1).length : null;
  const since = p ? (last / p.entry_price - 1) * 100 : null;
  $("#cs").innerHTML = `<div style="display:flex;align-items:center;gap:8px"><div class="title" style="margin:4px 0">${esc(d.name || "Coin")}</div>${d.mode === "PAPER" ? '<span class="pill paper">PAPER</span>' : ""}</div>
    <div class="sub">${esc(c.symbol || "")} · Solana · ${ago(c.migrated_at)} old ${parts != null ? `<a class="pill ${parts === 8 ? "g" : "r"}" href="#/audit/${encodeURIComponent(mint)}">⛨ ${parts}/8</a>` : ""}</div>
    <div class="big num" style="font-size:66px">${bigPrice(last)}</div>
    ${since != null ? `<div class="sub num"><span class="${since >= 0 ? "up" : "down"}">${since >= 0 ? "▲" : "▼"} ${Math.abs(since).toFixed(2)}% since entry</span></div>` : ""}
    <div class="chartwrap" style="height:260px"><canvas id="cc"></canvas></div>
    <div class="stats"><div class="stat"><div class="k">Market cap</div><div class="v num">${d.stats.mcap != null ? big$(d.stats.mcap) : "—"}</div></div>
    <div class="stat"><div class="k">Liquidity</div><div class="v num">${d.stats.liquidity != null ? big$(d.stats.liquidity) : "—"}</div></div>
    <div class="stat"><div class="k">24h volume</div><div class="v num">${d.stats.vol24 != null ? big$(d.stats.vol24) : "—"}</div></div>
    <div class="stat"><div class="k">Holders</div><div class="v num">${d.stats.holders != null ? d.stats.holders : "n/a"}</div></div></div>
    ${p ? `<div class="pos"><div style="font-weight:600">Your position · ${money(p.size_usd)} in · Executor</div>
      ${open ? `<div class="krow"><span>Stop line</span><span class="num">${price(p.stop_price)} · -${p.stop_pct}%</span></div>
      <div class="krow"><span>Trail line</span><span class="num">${p.trail_active ? price(p.exit_line) : "starts at +" + "${S_TRAIL}" + "%"}</span></div>
      <div class="krow"><span>Timeout in</span><span class="num">${timeLeft(p)}</span></div>` :
      `<div class="krow"><span>Closed · ${esc(p.exit_reason)}</span><span class="num ${p.pnl_usd >= 0 ? "up" : "down"}">${money(p.pnl_usd)}</span></div>`}</div>` : ""}
    <a class="btn ${open ? "r" : "g"}" href="${esc(d.link)}" target="_blank" rel="noopener">${open ? "Sell on pump.fun" : "Buy on pump.fun"}</a>`;
  const trailStart = (S.settings && S.settings.find(s => s.key === "risk.trail_start_pct") || {}).value ?? 20;
  $("#cs").innerHTML = $("#cs").innerHTML.replace("${S_TRAIL}", trailStart);
  Charts.candles($("#cc"), d.candles, open ? p.exit_line : null, p ? p.entry_price : null);
}
function timeLeft(p) {
  const h = (S.settings && (S.settings.find(s => s.key === "risk.timeout_h") || {}).value) || 3;
  const ms = Date.parse(p.opened_at) + h * 3600e3 - Date.now(); if (ms <= 0) return "due";
  const m = Math.round(ms / 60000); return Math.floor(m / 60) + "h " + (m % 60) + "m";
}

/* ---------- ACCOUNT */
const GROUPS = ["scanner", "auditor", "analyst", "executor", "risk", "fees", "desk"];
async function Account(app) {
  app.innerHTML = `${backbarless()}<div class="screen"><div class="title">Account</div><div id="acc"><div class="loading" style="height:120px"></div><div class="loading" style="height:420px;margin-top:16px"></div></div></div>${tabbar("account")}`;
  wireNav();
  let a, st;
  try { [a, st] = await Promise.all([api("account"), api("settings")]); S.settings = st.settings; S.account = a; }
  catch (e) { failScreen("#acc", e); return; }
  const standalone = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
  const pushOK = "serviceWorker" in navigator && "PushManager" in window;
  $("#acc").innerHTML = `
    <div class="seg" role="tablist"><button class="on" id="mP">PAPER</button><button id="mL">LIVE 🔒</button></div>
    <div class="list" style="margin-top:12px">
      <div class="row"><div class="tx"><div class="t1">Stack</div><div class="t2">PAPER started at ${money(a.paper_start_stack)} · free ${money(a.free)}</div></div><div class="val num">${money(a.stack)}</div></div>
      ${a.warning ? `<div class="row"><div class="tx"><div class="t1" style="color:var(--orange)">${esc(a.warning)}</div></div></div>` : ""}
      <a class="row" href="${esc(a.signup_url)}" target="_blank" rel="noopener"><div class="tx"><div class="t1">Open ${esc(a.venue)}</div><div class="t2">Every coin button opens its pump.fun page</div></div><span style="color:var(--t2)">›</span></a>
      <button class="row" id="inv" style="width:100%;text-align:left"><div class="tx"><div class="t1">Invite a friend</div><div class="t2">Share ${esc(a.signup_url)}</div></div><span style="color:var(--t2)">›</span></button>
    </div>
    <div class="grp">Notifications · Web Push</div>
    <div class="list">
      <div class="row"><div class="tx"><div class="t1">${a.push_subs ? "Connected" : "Not connected"}</div><div class="t2">${a.push_subs} device${a.push_subs === 1 ? "" : "s"} subscribed</div></div></div>
      ${standalone && pushOK ? `<button class="row" id="en" style="width:100%;text-align:left"><div class="tx"><div class="t1" style="color:var(--blue)">Enable notifications</div><div class="t2">Allow pushes on this iPhone</div></div></button>`
        : `<div class="row"><div class="tx"><div class="t2">Add to Home Screen (Share › Add to Home Screen), open it from there, then enable notifications here.</div></div></div>`}
      <button class="row" id="tp" style="width:100%;text-align:left"><div class="tx"><div class="t1" style="color:var(--blue)">Send test push</div></div></button>
    </div>
    <div class="grp">Talk to the desk</div>
    <div class="list"><div class="cmd"><input id="cmd" placeholder="why X · set stop to -8% · pause scanner" autocapitalize="off"><button class="pill n" id="cgo" style="min-height:44px">Send</button></div><div class="out" id="cout"></div></div>
    ${GROUPS.map(g => `<div class="grp" id="g-${g}">${g[0].toUpperCase() + g.slice(1)}</div><div class="list">${st.settings.filter(s => s.key.startsWith(g + ".")).map(setRow).join("")}</div>`).join("")}
    <div class="grp">Changes</div>
    ${st.change_log.length ? `<div class="list">${st.change_log.map(c => `<div class="row"><div class="tx"><div class="t1">${esc(c.key)}</div><div class="t2">${esc(c.old)} → ${esc(c.new)} · ${esc(c.who)}</div></div><div class="val"><small>${hm(c.ts)}</small></div></div>`).join("")}</div>` : '<div class="empty">No changes yet</div>'}`;
  $("#mL").onclick = async () => { const t = prompt('LIVE is locked on this desk. Type LIVE to try anyway:'); if (t == null) return;
    try { await post("mode", { mode: "LIVE", confirm: t }); } catch (e) { toast(e.message); } };
  $("#inv").onclick = async () => { try { if (navigator.share) await navigator.share({ url: a.signup_url, title: a.venue }); else throw 0; } catch (e) { if (e && e.name === "AbortError") return; try { await navigator.clipboard.writeText(a.signup_url); toast("Link copied"); } catch { toast(a.signup_url); } } };
  $("#tp").onclick = async () => { try { const r = await post("push/test"); toast(r.subs ? `Sent to ${r.delivered}/${r.subs} device(s)` : "No device subscribed yet"); } catch (e) { toast(e.message); } };
  if ($("#en")) $("#en").onclick = enablePush;
  const cmd = async () => { const t = $("#cmd").value.trim(); if (!t) return; $("#cout").textContent = "…";
    try { const r = await post("command", { text: t }); $("#cout").innerHTML = linkify(r.text) + (r.warning ? "\n" + esc(r.warning) : ""); } catch (e) { $("#cout").textContent = e.message; } };
  $("#cgo").onclick = cmd; $("#cmd").onkeydown = e => { if (e.key === "Enter") cmd(); };
  wireSettings();
  if (S.jump) { const el = $("#g-" + S.jump); S.jump = null; if (el) setTimeout(() => el.scrollIntoView(), 50); }
}
function step(s) { if (s.type === "int") return 1; const span = (s.max ?? 100) - (s.min ?? 0); return span <= 1 ? 0.01 : span <= 20 ? 0.1 : span <= 1000 ? 0.5 : 1; }
function sliderMax(s) { if (s.max == null) return 100; if (s.max > 100000) return Math.max(s.default * 5, 100); return s.max; }
function setRow(s) {
  const lab = `<div class="l"><span>${esc(s.label)}</span><small>${esc(s.key.split(".")[1])}</small></div>`;
  let ctl;
  if (s.type === "bool") ctl = `<button class="switch ${s.value ? "on" : ""}" data-k="${s.key}" data-t="bool" aria-label="${esc(s.label)}"></button>`;
  else if (s.choices) ctl = `<select data-k="${s.key}" data-t="choice">${s.choices.map(c => `<option ${c === s.value ? "selected" : ""} ${s.key === "desk.mode" && c === "LIVE" ? "disabled" : ""}>${c}</option>`).join("")}</select>`;
  else if (s.type === "str") ctl = `<input type="text" data-k="${s.key}" data-t="str" value="${esc(s.value)}" ${s.key === "desk.rpc_url" ? "readonly" : ""} style="flex:1;width:auto">`;
  else ctl = `<input type="range" min="${s.min ?? 0}" max="${sliderMax(s)}" step="${step(s)}" value="${s.value}" data-r="${s.key}" aria-label="${esc(s.label)}"><input type="number" inputmode="decimal" data-k="${s.key}" data-t="num" value="${s.value}" min="${s.min ?? ""}" max="${s.max ?? ""}" step="any">`;
  return `<div class="set">${lab}<div class="ctl">${ctl}</div><div class="msg" id="m-${s.key.replace(".", "-")}"></div></div>`;
}
function wireSettings() {
  const save = async (k, v, el) => { const m = $("#m-" + k.replace(".", "-")); m.textContent = "";
    try { const r = await post("settings", { key: k, value: v }); m.style.color = "var(--green)"; m.textContent = "Saved" + (r.warning ? " · " + r.warning : ""); setTimeout(() => { if (m.textContent.startsWith("Saved")) m.textContent = ""; }, 2500); }
    catch (e) { m.style.color = "var(--red)"; m.textContent = e.message; const s = S.settings.find(x => x.key === k); if (el && s) el.value = s.value; } };
  document.querySelectorAll("input[data-r]").forEach(r => { const n = document.querySelector(`input[data-k="${r.dataset.r}"]`);
    r.oninput = () => n.value = r.value; r.onchange = () => save(r.dataset.r, +r.value, n); });
  document.querySelectorAll("[data-k]").forEach(el => {
    const k = el.dataset.k, t = el.dataset.t;
    if (t === "bool") el.onclick = async () => { const on = !el.classList.contains("on");
      if (k === "auditor.enabled" && !on) { if (!confirm("Turn off take-apart?")) return; if (!confirm("Sure? Every coin skips all 8 safety layers.")) return; }
      await save(k, on); el.classList.toggle("on", on); };
    else if (t === "num") el.onchange = () => { const r = document.querySelector(`input[data-r="${k}"]`); if (r) r.value = el.value; save(k, +el.value, el); };
    else el.onchange = () => save(k, el.value, el);
  });
}

/* ---------- push */
function b64u(s) { const p = "=".repeat((4 - s.length % 4) % 4), b = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from([...b].map(c => c.charCodeAt(0))); }
async function enablePush() {
  try {
    const perm = await Notification.requestPermission(); if (perm !== "granted") return toast("Notifications not allowed");
    const reg = await navigator.serviceWorker.register("/sw.js"); await navigator.serviceWorker.ready;
    const key = (S.account && S.account.vapid_public) || (await (await fetch("/vapid.json", { headers: { "ngrok-skip-browser-warning": "1" } })).json()).key;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64u(key) });
    const j = sub.toJSON(); await post("push", { endpoint: j.endpoint, keys: j.keys }); toast("Notifications on"); render();
  } catch (e) { toast("Couldn't enable: " + e.message); }
}
function toast(t) { const d = document.createElement("div"); d.className = "toast"; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 3000); }

/* ---------- boot */
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { });
if (!location.hash || location.hash === "#") history.replaceState(null, "", "#/home");
render(); if (token()) { loadState(); sse(); }
setInterval(() => { if (token() && !S.offline) loadState(); }, 30000);
