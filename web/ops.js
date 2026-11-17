// Ops dashboard (task 4.6): problems first, then each HLD 12 KPI beside its target, orders per hour, the
// live event feed, and a row per store. Plain JavaScript, no build step. Logs in as the city-wide ops user.

const DEMO_PASSWORD = "demo"; // same as DEMO_PASSWORD in app/config.py; demo accounts only
const REFRESH_MS = 15000;     // numbers like minutes waiting change without an event, so refresh now and then
const EVENTS_SHOWN = 15;
const $ = (id) => document.getElementById(id);

let token = null;             // promise of the ops user's bearer token
let store = 1;
const live = { socket: null, generation: 0, refreshTimer: null };

function opsToken() {
  token ??= fetch("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ops", password: DEMO_PASSWORD }),
  }).then((res) => (res.ok ? res.json() : Promise.reject(new Error("Could not log in as ops"))))
    .then((session) => session.access_token)
    .catch((error) => { token = null; throw error; });
  return token;
}

async function api(path, isRetry = false) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${await opsToken()}` } });
  if (res.status === 401 && !isRetry) {
    token = null; // the token expired: log in again and retry once
    return api(path, true);
  }
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

// ---------------------------------------------------------------- render

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const FORMAT = {
  seconds: (v) => `${Math.round(v * 10) / 10} s`,
  fraction: (v) => `${(v * 100).toFixed(1)}%`,
  per_hour: (v) => `${Math.round(v)} / h`,
};

function actionTile(label, count, detail) {
  const known = count !== null;
  return el("div", { className: "action-tile" + (known && count > 0 ? " is-bad" : "") },
    el("div", { className: "big" }, known ? String(count) : "–"),
    el("div", { className: "label" }, label),
    el("div", { className: "detail" }, detail));
}

function renderActions({ stalled_orders: stalled, waiting_for_rider: waiting, out_of_stock: out }) {
  const longest = waiting.reduce((most, bag) => (bag.minutes_waiting > most.minutes_waiting ? bag : most), waiting[0]);
  const someOut = out.slice(0, 3).join(", ") + (out.length > 3 ? ` and ${out.length - 3} more` : "");
  $("actions").replaceChildren(
    actionTile("Stalled orders", stalled === null ? null : stalled.length,
      stalled === null ? "Not available yet (fulfilment's stall check)" : stalled.join(", ") || "None"),
    actionTile("Bags waiting for a rider", waiting.length,
      longest ? `Longest: ${plural(longest.minutes_waiting, "minute")} (${longest.order_id})` : "None"),
    actionTile("Out of stock", out.length, someOut || "None"));
}

function kpiCard(kpi) {
  const [state, mark] = !kpi.available ? ["is-unknown", "Not available"]
    : kpi.met === null ? ["is-unknown", "No data yet"]
    : kpi.met ? ["is-met", "✓ Met"] : ["is-not-met", "✗ Not met"];
  const value = kpi.available && kpi.value !== null ? FORMAT[kpi.unit](kpi.value) : "–";
  return el("article", { className: `kpi ${state}` },
    el("h3", {}, kpi.name),
    el("div", { className: "big" }, value),
    el("div", { className: "mark" }, mark),
    el("div", { className: "detail" }, `Target ${kpi.target}` + (kpi.note ? ` · ${kpi.note}` : "")));
}

function renderKpis(kpis) {
  // Problems first, then measured numbers, then what cannot be measured yet; HLD order within each group.
  const rank = (kpi) => (!kpi.available ? 3 : kpi.met === false ? 0 : kpi.met ? 1 : 2);
  $("kpis").replaceChildren(...[...kpis].sort((a, b) => rank(a) - rank(b)).map(kpiCard));
}

function renderChart(hours) {
  const most = Math.max(1, ...hours.map((h) => h.orders));
  const label = (h) => new Date(h.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const total = hours.reduce((sum, h) => sum + h.orders, 0);
  $("chart-total").textContent = `${plural(total, "paid order")} in the last ${hours.length} hours`;
  $("chart").setAttribute("aria-label", `Paid orders per hour, ${total} in total; the table below has each hour`);
  $("chart").replaceChildren(...hours.map((h) =>
    el("div", { className: "bar-slot", title: `${label(h)}: ${plural(h.orders, "order")}` },
      el("div", { className: "bar", style: `height: ${(h.orders / most) * 100}%` }))));
  $("chart-hours").replaceChildren(...hours.map((h, i) => el("span", {}, i % 3 === 2 ? label(h) : "")));
  $("chart-table").replaceChildren(...hours.map((h) =>
    el("tr", {}, el("td", {}, label(h)), el("td", {}, String(h.orders)))));
}

function renderCity(rows) {
  $("city").replaceChildren(...rows.map((r) => el("tr", { className: r.store_id === store ? "is-current" : "" },
    el("td", {}, r.store), el("td", {}, r.status),
    ...[r.waiting_orders, r.waiting_for_rider, r.low_stock, r.out_of_stock]
      .map((n) => el("td", { className: "num" }, String(n))))));
}

function eventItem(event) {
  const time = new Date(event.ts).toLocaleTimeString();
  const about = event.payload?.order_id ?? (event.payload?.sku_id !== undefined ? `SKU ${event.payload.sku_id}` : "");
  return el("li", {}, el("span", { className: "event-time" }, time),
    el("span", {}, el("span", { className: "event-type" }, event.type), about ? ` ${about}` : ""));
}

function addEvent(event) {
  const list = $("events");
  list.querySelector(".empty")?.remove();
  list.prepend(eventItem(event));
  while (list.children.length > EVENTS_SHOWN) list.lastChild.remove();
}

// ---------------------------------------------------------------- data

async function refresh() {
  const [board, city] = await Promise.all([api(`/v1/stores/${store}/kpis`), api("/v1/dashboard/overview")]);
  renderActions(board.needs_action);
  renderKpis(board.kpis);
  renderChart(board.orders_per_hour);
  renderCity(city);
  $("ops-page-message").textContent = "";
}

function refreshSafely() {
  refresh().catch((error) => {
    $("ops-page-message").textContent = error.message;
    $("ops-page-message").className = "message is-bad";
  });
}

async function loadEvents() {
  const recent = await api(`/v1/events?store_id=${store}&limit=${EVENTS_SHOWN}`);
  $("events").replaceChildren(...(recent.length ? recent.map(eventItem) : [el("li", { className: "empty" }, "No events yet")]));
}

// Live feed from task 4.5: the token goes as the first message; reconnect after a drop.
async function connectLive() {
  const generation = ++live.generation;
  const old = live.socket;
  live.socket = null; // so the old socket's close does not schedule a reconnect
  old?.close();
  const bearer = await opsToken();
  if (generation !== live.generation) return; // the store changed while logging in
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/ws/events?store_id=${store}`);
  live.socket = socket;
  socket.onopen = () => socket.send(bearer);
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "connected") $("live-status").textContent = "● Live";
    if (event.type === "ping" || event.type === "connected") return;
    addEvent(event);
    clearTimeout(live.refreshTimer);
    live.refreshTimer = setTimeout(refreshSafely, 200); // one refresh for a burst of events
  };
  socket.onclose = () => {
    if (socket !== live.socket) return;
    live.socket = null;
    token = null; // the server closes the socket when the token expires
    $("live-status").textContent = "Reconnecting…";
    setTimeout(() => { if (generation === live.generation) connectLive().catch(() => {}); }, 3000);
  };
}

async function start() {
  const stores = await api("/v1/stores");
  $("store-select").replaceChildren(...stores.map((s) => el("option", { value: s.store_id }, s.name)));
  $("store-select").onchange = () => {
    store = Number($("store-select").value);
    refreshSafely();
    loadEvents().catch(() => {});
    connectLive().catch(() => {});
  };
  await Promise.all([refresh(), loadEvents()]);
  await connectLive();
  setInterval(refreshSafely, REFRESH_MS);
}

start().catch((error) => {
  $("ops-page-message").textContent = error.message;
  $("ops-page-message").className = "message is-bad";
});
