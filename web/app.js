// Demo screens for the dark store prototype. Plain JavaScript, no build step.
// Each station only calls the public API, exactly as a real app would.

const $ = (id) => document.getElementById(id);

const state = {
  opsStore: 1,      // store shown on the picker and ops stations
  shopStore: null,  // store serving the customer's address
  products: [],
  cart: {},         // sku_id -> quantity
  hold: null,       // the current reservation, if any
  holdTimer: null,
  job: null,        // the picker's current order
};

// ---------------------------------------------------------------- helpers

// Staff logins (HLD 10). Each station logs in as a seeded demo user; the customer station needs no login.
const DEMO_PASSWORD = "demo"; // same as DEMO_PASSWORD in app/config.py; demo accounts only
const tokens = {}; // username -> promise of a bearer token, so calls made together share one login
const picker = () => `picker${state.opsStore}`;
const manager = () => `manager${state.opsStore}`;
const ADMIN = "admin";

function tokenFor(user) {
  tokens[user] ??= api("POST", "/v1/auth/login", { username: user, password: DEMO_PASSWORD })
    .then((session) => session.access_token)
    .catch((error) => {
      delete tokens[user]; // let the next call try to log in again
      throw error;
    });
  return tokens[user];
}

/** Call the API. Pass `user` to send that staff member's token; leave it out for the open customer endpoints. */
async function api(method, path, body, user, isRetry = false) {
  const headers = body ? { "Content-Type": "application/json" } : {};
  if (user) headers.Authorization = `Bearer ${await tokenFor(user)}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401 && user && !isRetry) {
    delete tokens[user]; // the token expired: log in again and retry once
    return api(method, path, body, user, true);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error?.message || `Request failed (${res.status})`);
    error.code = data.error?.code;
    error.details = data.error?.details;
    throw error;
  }
  return data;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function say(target, text, kind) {
  target.textContent = text;
  target.className = "message" + (kind ? ` is-${kind}` : "");
}

/** Run an action; show any failure in the station's message line. */
function guarded(messageEl, action) {
  return async (...args) => {
    try {
      await action(...args);
    } catch (error) {
      say(messageEl, error.message, "bad");
    }
  };
}

const skuName = (skuId) => state.products.find((p) => p.sku_id === skuId)?.name || `item ${skuId}`;

// ---------------------------------------------------------------- customer station

async function checkLocation() {
  const [lat, lng] = $("location-select").value.split(",");
  const result = await api("GET", `/v1/serviceability?lat=${lat}&lng=${lng}`);
  say($("customer-message"), "");
  state.cart = {};
  if (!result.serviceable) {
    state.shopStore = null;
    $("shop").hidden = true;
    $("service-message").textContent =
      `No store delivers here yet. The nearest, ${result.nearest_store}, is ${result.nearest_distance_km} km away.`;
    return;
  }
  state.shopStore = result.store_id;
  $("service-message").textContent =
    `${result.store} delivers here in about ${result.eta_minutes} minutes` +
    (result.status === "busy" ? " (it is busy right now)." : ".");
  $("shop").hidden = false;
  await loadProducts();
}

async function loadProducts() {
  if (!state.shopStore) return;
  state.products = await api("GET", `/v1/stores/${state.shopStore}/availability`);
  renderProducts();
}

function renderProducts() {
  const inStock = state.products.filter((p) => p.atp > 0);
  const locked = Boolean(state.hold);
  $("product-list").replaceChildren(
    ...inStock.map((p) => {
      const qty = state.cart[p.sku_id] || 0;
      const left = el("span", { className: p.atp <= 5 ? "few" : "" }, `${p.atp} left`);
      const minus = el("button", { className: "btn btn-small", textContent: "−", disabled: locked || qty === 0 });
      const plus = el("button", { className: "btn btn-small", textContent: "+", disabled: locked });
      minus.setAttribute("aria-label", `Remove one ${p.name}`);
      plus.setAttribute("aria-label", `Add one ${p.name}`);
      minus.onclick = () => changeCart(p.sku_id, -1);
      plus.onclick = () => changeCart(p.sku_id, +1);
      return el("li", {},
        el("div", {},
          el("div", { className: "product-name" }, p.name),
          el("div", { className: "product-meta" }, `₹${p.price}, `, left)),
        el("div", { className: "stepper" }, minus, el("span", {}, String(qty)), plus));
    }),
  );
  const hidden = state.products.length - inStock.length;
  $("hidden-note").textContent = hidden
    ? `${hidden} ${hidden === 1 ? "item is" : "items are"} hidden because the store has none to sell.`
    : "";
  renderCart();
}

function changeCart(skuId, step) {
  const next = Math.max(0, (state.cart[skuId] || 0) + step);
  if (next) state.cart[skuId] = next;
  else delete state.cart[skuId];
  renderProducts();
}

function renderCart() {
  const lines = Object.entries(state.cart);
  const units = lines.reduce((sum, [, qty]) => sum + qty, 0);
  const total = lines.reduce((sum, [skuId, qty]) => {
    const product = state.products.find((p) => p.sku_id === Number(skuId));
    return sum + (product ? product.price * qty : 0);
  }, 0);
  $("cart-summary").textContent = units ? `${units} ${units === 1 ? "item" : "items"}, ₹${total}` : "Cart is empty";
  $("checkout").disabled = !units || Boolean(state.hold);
}

async function checkout() {
  const lines = Object.entries(state.cart).map(([skuId, qty]) => ({ sku_id: Number(skuId), qty }));
  const orderId = "ORD-" + Date.now().toString(36).toUpperCase();
  try {
    state.hold = await api("POST", "/v1/reservations", { order_id: orderId, store_id: state.shopStore, lines });
  } catch (error) {
    if (error.code !== "insufficient_stock") throw error;
    const short = error.details.lines.map((l) => `${skuName(l.sku_id)} (${l.available} left)`).join(", ");
    say($("customer-message"), `Not enough stock for ${short}. Nothing was held; change your cart and try again.`, "bad");
    await loadProducts();
    return;
  }
  say($("customer-message"), "");
  showHold();
  renderProducts();
  refreshOps();
}

function showHold() {
  $("hold-panel").hidden = false;
  const expires = new Date(state.hold.expires_at).getTime();
  const tick = () => {
    const seconds = Math.max(0, Math.round((expires - Date.now()) / 1000));
    $("hold-timer").textContent =
      `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} left to pay.`;
    if (seconds === 0) {
      clearHold();
      say($("customer-message"), "The hold ran out. Use “Release expired holds” on the ops desk, then order again.", "bad");
    }
  };
  tick();
  state.holdTimer = setInterval(tick, 1000);
}

function clearHold() {
  clearInterval(state.holdTimer);
  state.hold = null;
  $("hold-panel").hidden = true;
  renderProducts();
}

async function pay() {
  const paid = await api("POST", `/v1/reservations/${state.hold.reservation_id}/confirm`);
  state.cart = {};
  clearHold();
  say($("customer-message"), `Paid. Order ${paid.order_id} is waiting for a picker.`, "good");
  await loadProducts();
  refreshOps();
}

async function cancelHold() {
  await api("DELETE", `/v1/reservations/${state.hold.reservation_id}`);
  clearHold();
  say($("customer-message"), "Order cancelled. The items are back on sale.");
  await loadProducts();
  refreshOps();
}

// ---------------------------------------------------------------- picker station

async function nextJob() {
  const result = await api("GET", `/v1/pickers/${picker()}/next-task?store_id=${state.opsStore}`, undefined, picker());
  state.job = result.job;
  say($("picker-message"), result.job ? "" : "No paid orders are waiting in this store.");
  renderJob();
  refreshOps();
}

const TASK_STATUS_TEXT = {
  picked: "Picked",
  short: "Dropped: none left in the store",
  reallocated: "Not here: moved to another bin",
};

function renderJob() {
  const job = state.job;
  $("job-panel").hidden = !job;
  if (!job) return;
  $("job-title").textContent = `Order ${job.order_id}`;
  $("task-list").replaceChildren(
    ...job.tasks.map((task) => {
      const head = el("div", { className: "task-head" },
        el("span", { className: "bin" }, task.bin || "no bin"),
        el("span", { className: "task-qty" }, `${task.qty} × ${task.sku}`));
      const item = el("li", { className: task.status === "pending" ? "" : "is-done" }, head);
      if (task.batch_no) {
        item.append(el("p", { className: "task-meta" }, `Batch ${task.batch_no}, expires ${task.expiry_date}`));
      }
      if (task.status === "pending" && job.state === "picking") {
        const scanRight = el("button", { className: "btn btn-small btn-primary", textContent: "Scan item" });
        const scanWrong = el("button", { className: "btn btn-small", textContent: "Scan a wrong item" });
        const missing = el("button", { className: "btn btn-small", textContent: "Not on shelf" });
        scanRight.onclick = guarded($("picker-message"), () => scanTask(task, task.barcode));
        scanWrong.onclick = guarded($("picker-message"), () => scanTask(task, "0000000000000"));
        missing.onclick = guarded($("picker-message"), () => reportShort(task));
        item.append(el("div", { className: "row row-wrap" }, scanRight, scanWrong, missing));
      } else {
        item.append(el("span", { className: `task-status ${task.status}` }, TASK_STATUS_TEXT[task.status] || task.status));
      }
      return item;
    }),
  );
  const pending = job.tasks.some((t) => t.status === "pending");
  $("pack-row").hidden = !(job.state === "picking" && !pending);
  $("handover").hidden = job.state !== "packed";
}

async function scanTask(task, barcode) {
  const result = await api("POST", `/v1/pick-tasks/${task.task_id}/scans`, { barcode, qty: task.qty }, picker());
  if (!result.match) {
    say($("picker-message"), result.message, "bad");
    return;
  }
  state.job = result.job;
  say($("picker-message"), result.lines_left ? `Picked. ${result.lines_left} to go.` : "All lines done. Pack the order.", "good");
  renderJob();
}

async function reportShort(task) {
  const result = await api("POST", `/v1/pick-tasks/${task.task_id}/short`, undefined, picker());
  state.job = result.job;
  say($("picker-message"), result.message, result.dropped ? "bad" : "");
  renderJob();
  refreshOps();
}

async function packJob() {
  const slot = $("crate-slot").value.trim() || "S-01";
  state.job = await api("POST", `/v1/fulfilment-jobs/${state.job.job_id}/packed`, { crate_slot: slot }, picker());
  const done = state.job.state === "packed";
  say($("picker-message"),
    done ? `Packed into ${slot}. The stock has now left the books.` : "Nothing could be picked, so the order was cancelled.",
    done ? "good" : "bad");
  if (!done) state.job = null;
  renderJob();
  refreshOps();
}

async function handover() {
  const job = await api("POST", `/v1/fulfilment-jobs/${state.job.job_id}/handover`, undefined, picker());
  say($("picker-message"), `Order ${job.order_id} is with the rider.`, "good");
  state.job = null;
  renderJob();
  refreshOps();
}

// ---------------------------------------------------------------- ops station

async function refreshOps() {
  const store = state.opsStore;
  const [dash, stock, transfers, events] = await Promise.all([
    api("GET", `/v1/stores/${store}/dashboard`, undefined, manager()),
    api("GET", `/v1/stores/${store}/availability`),
    api("GET", `/v1/transfer-orders?store_id=${store}`, undefined, manager()),
    api("GET", `/v1/events?store_id=${store}&limit=12`, undefined, manager()),
  ]);
  renderTiles(dash);
  renderStock(stock);
  renderTransfers(transfers);
  renderEvents(events);
}

function renderTiles(d) {
  const tiles = [
    ["Store", d.status === "busy" ? "Busy" : d.status === "open" ? "Open" : "Closed", d.status !== "open"],
    ["Waiting for a picker", d.orders.created, false],
    ["Being picked", d.orders.picking, false],
    ["Packed, awaiting rider", d.orders.packed, false],
    ["Handed to rider", d.orders.handed_over, false],
    ["Average pack time", d.avg_seconds_to_pack === null ? "none yet" : `${d.avg_seconds_to_pack} s`, false],
    ["Holds in progress", d.active_holds, false],
    ["Items below reorder point", d.skus_below_reorder_point, d.skus_below_reorder_point > 0],
    ["Open transfer orders", d.open_transfer_orders, false],
  ];
  $("tiles").replaceChildren(
    ...tiles.map(([label, value, bad]) =>
      el("div", { className: bad ? "is-bad" : "" }, el("dt", {}, label), el("dd", {}, String(value)))),
  );
}

function renderStock(rows) {
  $("stock-rows").replaceChildren(
    ...rows.map((r) =>
      el("tr", { className: r.atp < r.reorder_point ? "is-low" : "" },
        el("td", {}, r.name),
        el("td", { className: "num" }, String(r.on_hand)),
        el("td", { className: "num" + (r.reserved ? " held" : "") }, String(r.reserved)),
        el("td", { className: "num" }, String(r.atp)),
        el("td", { className: "num" }, String(r.reorder_point)))),
  );
}

function renderTransfers(orders) {
  if (!orders.length) {
    $("transfer-list").replaceChildren(el("li", { className: "empty" }, "None yet. Check what needs reordering to raise one."));
    return;
  }
  $("transfer-list").replaceChildren(
    ...orders.map((order) => {
      const units = order.lines.reduce((sum, l) => sum + l.qty_ordered, 0);
      const label = `#${order.transfer_order_id}: ${order.lines.length} ${order.lines.length === 1 ? "item" : "items"}, ${units} units`;
      const row = el("li", {}, el("span", {}, label));
      if (order.status === "created") {
        const button = el("button", { className: "btn btn-small", textContent: "Hub dispatches truck" });
        button.onclick = guarded($("ops-message"), async () => {
          await api("POST", `/v1/transfer-orders/${order.transfer_order_id}/dispatch`, undefined, manager());
          say($("ops-message"), `Truck for transfer order #${order.transfer_order_id} is on its way.`);
          await refreshOps();
        });
        row.append(button);
      } else if (order.status === "dispatched") {
        const button = el("button", { className: "btn btn-small btn-primary", textContent: "Receive truck" });
        button.onclick = guarded($("ops-message"), () => receiveTruck(order));
        row.append(button);
      } else {
        row.append(el("span", { className: "note" }, "Received"));
      }
      return row;
    }),
  );
}

async function receiveTruck(order) {
  const receipt = await api("POST", "/v1/goods-receipts", {
    store_id: order.store_id,
    transfer_order_id: order.transfer_order_id,
    lines: order.lines.map((l) => ({ sku_id: l.sku_id, qty: l.qty_ordered })),
  }, manager());
  const bins = receipt.received.map((r) => `${r.sku} to ${r.bin}`).join("; ");
  say($("ops-message"), `Truck received and put away: ${bins}.`, "good");
  await refreshOps();
  await loadProducts();
}

function renderEvents(events) {
  if (!events.length) {
    $("event-list").replaceChildren(el("li", { className: "empty" }, "No events yet. Place an order to see them appear."));
    return;
  }
  $("event-list").replaceChildren(
    ...events.map((e) => {
      const time = new Date(e.ts).toLocaleTimeString([], { hour12: false });
      const detail = Object.entries(e.payload).map(([k, v]) => `${k}=${v}`).join(", ");
      return el("li", {},
        el("span", { className: "event-time" }, time),
        el("span", {}, el("span", { className: "event-type" }, e.type), detail ? ` ${detail}` : ""));
    }),
  );
}

async function runReplenishment() {
  const { transfer_order: order } = await api("POST", `/v1/replenishment/run?store_id=${state.opsStore}`, undefined, manager());
  say($("ops-message"), order
    ? `Transfer order #${order.transfer_order_id} raised for ${order.lines.map((l) => `${l.qty_ordered} × ${l.sku}`).join(", ")}.`
    : "Nothing to reorder: every item is above its reorder point or already on its way.");
  await refreshOps();
}

async function runForecast() {
  const rows = await api("POST", `/v1/forecasting/run?store_id=${state.opsStore}`, undefined, manager());
  const updated = rows.filter((r) => r.daily_demand > 0).length;
  say($("ops-message"), `Forecasts recalculated from the last 7 days of sales. Reorder points updated for ${updated} ${updated === 1 ? "item" : "items"}.`);
  await refreshOps();
}

async function sweepHolds() {
  const { released } = await api("POST", "/v1/admin/sweep-reservations", undefined, ADMIN);
  say($("ops-message"), released ? `${released} expired ${released === 1 ? "hold" : "holds"} released.` : "No holds have expired.");
  await refreshOps();
  await loadProducts();
}

async function resetDemo() {
  if (!window.confirm("Reset all demo data? Every order, hold and stock change will be wiped.")) return;
  await api("POST", "/v1/admin/reset", undefined, ADMIN);
  clearHold();
  state.cart = {};
  state.job = null;
  renderJob();
  say($("ops-message"), "Demo data reset.");
  say($("customer-message"), "");
  say($("picker-message"), "");
  await refreshOps();
  await loadProducts();
}

// ---------------------------------------------------------------- start-up

async function start() {
  const stores = await api("GET", "/v1/stores");
  $("store-select").replaceChildren(...stores.map((s) => el("option", { value: s.store_id }, s.name)));
  $("store-select").onchange = guarded($("ops-message"), async () => {
    state.opsStore = Number($("store-select").value);
    $("picker-id").textContent = picker();
    state.job = null;
    renderJob();
    await refreshOps();
  });

  $("check-location").onclick = guarded($("customer-message"), checkLocation);
  $("checkout").onclick = guarded($("customer-message"), checkout);
  $("pay").onclick = guarded($("customer-message"), pay);
  $("cancel-hold").onclick = guarded($("customer-message"), cancelHold);
  $("next-job").onclick = guarded($("picker-message"), nextJob);
  $("pack").onclick = guarded($("picker-message"), packJob);
  $("handover").onclick = guarded($("picker-message"), handover);
  $("run-replenishment").onclick = guarded($("ops-message"), runReplenishment);
  $("run-forecast").onclick = guarded($("ops-message"), runForecast);
  $("sweep-holds").onclick = guarded($("ops-message"), sweepHolds);
  $("reset-demo").onclick = guarded($("ops-message"), resetDemo);

  await refreshOps();
  await checkLocation();

  // Keep the ops desk and the shop shelf live, so changes made in another tab show up.
  setInterval(() => refreshOps().catch(() => {}), 3000);
  setInterval(() => { if (!state.hold) loadProducts().catch(() => {}); }, 5000);
}

start().catch((error) => say($("ops-message"), error.message, "bad"));
