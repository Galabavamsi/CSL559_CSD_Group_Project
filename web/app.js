// Demo screens for the dark store prototype. Plain JavaScript, no build step.
// Each station only calls the public API, exactly as a real app would.

// Shared helpers ($, api, el, say, guarded) are in common.js, loaded first.

const state = {
  opsStore: 1,      // store shown on the picker and ops stations
  shopStore: null,  // store serving the customer's address
  shopCell: null,   // H3 cell of that address
  products: [],
  cart: {},         // sku_id -> quantity
  hold: null,       // the current reservation, if any
  holdTimer: null,
  paid: null,       // the customer's last paid order, which they may still cancel until it is packed
  trackTimer: null, // follows that order through the store until it is delivered or cancelled
  jobs: [],         // the picker's current orders: one, or a batch at peak (task 2.6)
  walkSize: 0,      // how many orders this walk started with, so the last one of a batch keeps its tote name
  offer: null,      // a substitute offered for dropped units, waiting for the customer's answer (task 2.4)
};

// Each station logs in as a seeded demo user (common.js); the customer station needs no login.
const picker = () => `picker${state.opsStore}`;
const manager = () => `manager${state.opsStore}`;
const ADMIN = "admin";

const skuName = (skuId) => state.products.find((p) => p.sku_id === skuId)?.name || `item ${skuId}`;

// ---------------------------------------------------------------- customer station

async function checkLocation() {
  const [lat, lng] = $("location-select").value.split(",");
  const result = await api("GET", `/v1/serviceability?lat=${lat}&lng=${lng}`);
  say($("customer-message"), "");
  state.cart = {};
  state.shopCell = result.h3_cell; // sent with the order for network planning: a hexagon, not the address
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
      // No more than the store can sell: a cart over the stock shown would only be refused at checkout.
      const plus = el("button", { className: "btn btn-small", textContent: "+", disabled: locked || qty >= p.atp,
                                  title: qty >= p.atp ? `Only ${p.atp} left` : "" });
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
  const named = lines.map(([skuId, qty]) => `${qty} × ${skuName(Number(skuId))}`);
  const listed = named.slice(0, 3).join(", ") + (named.length > 3 ? ` and ${named.length - 3} more` : "");
  $("cart-summary").textContent = units ? `${listed} · ₹${total}` : "Cart is empty";
  $("checkout").disabled = !units || Boolean(state.hold);
}

async function checkout() {
  const lines = Object.entries(state.cart).map(([skuId, qty]) => ({ sku_id: Number(skuId), qty }));
  const orderId = "ORD-" + Date.now().toString(36).toUpperCase();
  try {
    state.hold = await api("POST", "/v1/reservations",
      { order_id: orderId, store_id: state.shopStore, h3_cell: state.shopCell, lines });
  } catch (error) {
    if (error.code !== "insufficient_stock") throw error;
    const short = error.details.lines.map((l) => `${skuName(l.sku_id)} (${l.available} left)`).join(", ");
    say($("customer-message"), `Not enough stock for ${short}. Nothing was held; change your cart and try again.`, "bad");
    await loadProducts();
    return;
  }
  say($("customer-message"), "");
  showPaid(null);
  showHold();
  $("hold-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });   // on a phone it is below the list
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
  showPaid(paid);
  $("paid-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  say($("customer-message"), "Payment received.", "good");
  await loadProducts();
  refreshOps();
}

/** Show the customer's paid order and follow it through the store until it is delivered or cancelled. */
function showPaid(order) {
  state.paid = order;
  clearInterval(state.trackTimer);
  $("paid-panel").hidden = !order;
  if (!order) return;
  $("paid-order").textContent = order.order_id;
  showOrderStatus({ state: "created", tasks: [] });
  state.trackTimer = setInterval(() => trackPaid().catch(() => {}), 3000);
}

/** The paid order as the store sees it. A real app would ask the Order service; here the store manager's login
 *  stands in for it, as for cancelling. */
async function paidJob(order) {
  const jobs = await api("GET", `/v1/fulfilment-jobs?store_id=${order.store_id}`, undefined, `manager${order.store_id}`);
  return jobs.find((j) => j.order_id === order.order_id);
}

const ORDER_STATUS = {
  created: "Paid. Waiting for a picker.",
  picking: "A picker is collecting your items.",
  packed: "Packed and waiting for a rider.",
  handed_over: "On its way to you.",
  cancelled: "Cancelled. Your payment will be refunded.",
};

function showOrderStatus(job) {
  const rider = job.rider?.rider_id;
  let text = ORDER_STATUS[job.state] || job.state;
  if (rider && job.state === "packed") {
    text = job.rider.status === "arrived" ? `Rider ${rider} is collecting your bag.` : `Packed. Rider ${rider} is on the way to the store.`;
  }
  if (rider && job.state === "handed_over") text = `On its way to you with rider ${rider}.`;
  const missing = job.tasks.filter((t) => t.status === "short").reduce((units, t) => units + t.qty, 0);
  if (missing && job.state !== "cancelled") {
    text += ` ${missing} ${missing === 1 ? "item was" : "items were"} out of stock and will be refunded.`;
  }
  // Dropped units the customer took a substitute for (task 2.4): one entry per item, however its lines were split.
  const swapped = {};
  for (const t of job.tasks.filter((t) => t.status === "substituted")) swapped[t.sku] = (swapped[t.sku] || 0) + t.qty;
  const swappedText = Object.entries(swapped).map(([name, qty]) => `${qty} × ${name}`).join(", ");
  if (swappedText && job.state !== "cancelled") text += ` ${swappedText} replaced by a substitute.`;
  $("paid-status").textContent = text;
  const cancellable = job.state === "created" || job.state === "picking";
  $("cancel-paid").hidden = !cancellable;
  $("paid-note").hidden = !cancellable;
}

async function trackPaid() {
  const order = state.paid;
  const job = order && await paidJob(order);
  if (!job || state.paid !== order) return;               // gone (a reset), or the customer moved on meanwhile
  showOrderStatus(job);
  if (job.state === "handed_over" || job.state === "cancelled") clearInterval(state.trackTimer);
}

async function cancelPaidOrder() {
  const { order_id: orderId, store_id: storeId } = state.paid;
  // In a real app the Order service makes this call; here the store manager's login stands in for it.
  const managerOfStore = `manager${storeId}`;
  const job = await paidJob(state.paid);
  if (!job) {
    showPaid(null);
    throw new Error(`Order ${orderId} is not in the store's list any more.`);
  }
  try {
    await api("POST", `/v1/fulfilment-jobs/${job.job_id}/cancel`, { reason: "Customer changed their mind" }, managerOfStore);
  } catch (error) {
    if (error.code !== "too_late") throw error;
    showPaid(null);                        // packed already: the panel's offer no longer holds
    say($("customer-message"), `Too late to cancel order ${orderId}: it is already packed.`, "bad");
    return;
  }
  showPaid(null);
  say($("customer-message"), `Order ${orderId} cancelled. Its items are back on sale and the payment will be refunded.`);
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
// The picker gets one order off-peak, or a batch of up to three at peak, each in its own tote (A, B, C), with every
// line of every order in one walking order (task 2.6). Scanning and packing stay per line and per order.

async function nextJob() {
  const batch = await api("GET", `/v1/pickers/${picker()}/next-batch?store_id=${state.opsStore}`, undefined, picker());
  // Asking again mid-walk returns what is left of the same walk: it stays a batch even when one order remains.
  const sameWalk = batch.jobs.length > 0 && batch.jobs.every((j) => state.jobs.some((s) => s.job_id === j.job_id));
  state.walkSize = sameWalk ? Math.max(state.walkSize, batch.jobs.length) : batch.jobs.length;
  state.jobs = batch.jobs;
  const count = batch.jobs.length;
  say($("picker-message"),
    count === 0 ? "No paid orders are waiting in this store."
      : count > 1 ? `Busy store: ${count} orders in one walk. Put each item in the tote shown on its line.` : "");
  renderJob();
  refreshOps();
}

const TASK_STATUS_TEXT = {
  picked: "Picked",
  short: "Dropped: none left in the store",
  reallocated: "Not here: moved to another bin",
  cancelled: "Order cancelled: put it back",
  substituted: "Replaced by a substitute",
};

// A walk is a batch if it started with more than one order (or, after a reload, still holds a tote past A).
const inBatch = () => state.walkSize > 1 || state.jobs.some((j) => j.tote && j.tote !== "A");
const toteLabel = (job) => (inBatch() && job.tote ? `Tote ${job.tote}: ` : "");
const linesLeft = () => state.jobs.reduce((n, job) => n + job.tasks.filter((t) => t.status === "pending").length, 0);

function updateJob(job) {
  state.jobs = state.jobs.map((j) => (j.job_id === job.job_id ? job : j));
}

function dropJob(jobId) {
  state.jobs = state.jobs.filter((j) => j.job_id !== jobId);
}

/** A scan, empty-shelf report or pack was refused because the order is no longer this picker's to pick: it was
 *  cancelled (task 2.3), or it sat idle and went back to the queue or to another picker (task 2.5). Tell the
 *  picker what to do with it; the rest of a batch carries on. Any other error is shown as usual. */
async function explainIfOrderGone(error, job) {
  if (!["job_not_picking", "not_your_order"].includes(error.code) || !job) throw error;
  const now = await api("GET", `/v1/fulfilment-jobs/${job.job_id}`, undefined, picker());
  let text;
  if (now.state === "cancelled") text = "This order was cancelled. Put the items back on their shelves.";
  else if (error.code === "not_your_order" || now.state === "created") {
    text = "This order sat idle, so it went back to the queue. Put back anything you took, then press Get next order.";
  } else throw error;
  const label = toteLabel(job);
  dropJob(job.job_id);
  renderJob();
  say($("picker-message"), label + text, "bad");
  refreshOps();
}

function renderLine(job, task) {
  const head = el("div", { className: "task-head" },
    ...(inBatch() && job.tote ? [el("span", { className: "tote" }, `Tote ${job.tote}`)] : []),
    el("span", { className: "bin" }, task.bin || "no bin"),
    el("span", { className: "task-qty" }, `${task.qty} × ${task.sku}`));
  const item = el("li", { className: task.status === "pending" ? "" : "is-done" }, head);
  if (task.batch_no) {
    item.append(el("p", { className: "task-meta" }, `Batch ${task.batch_no}, expires ${task.expiry_date}`));
  }
  if (task.status === "pending" && job.state === "picking") {
    const left = task.qty - task.scanned_qty;
    if (task.qty > 1) {
      item.append(el("p", { className: "task-meta" }, `${task.scanned_qty} of ${task.qty} scanned`));
    }
    // "Scan item" puts every unit still needed in the tote; "Scan 1" is one beep of a real scanner (task 2.2).
    const scanRight = el("button", { className: "btn btn-small btn-primary", textContent: "Scan item" });
    const scanOne = el("button", { className: "btn btn-small", textContent: "Scan 1" });
    const scanWrong = el("button", { className: "btn btn-small", textContent: "Scan a wrong item" });
    scanRight.onclick = guarded($("picker-message"), () => scanTask(job, task, task.barcode, left));
    scanOne.onclick = guarded($("picker-message"), () => scanTask(job, task, task.barcode, 1));
    scanWrong.onclick = guarded($("picker-message"), () => scanTask(job, task, "0000000000000", 1));
    // Not on shelf, or only some of it: the number found (empty means the units already scanned).
    const found = el("input", { type: "number", min: String(task.scanned_qty), max: String(task.qty - 1),
                                placeholder: "Found only…", className: "found-input" });
    found.setAttribute("aria-label", `Units of ${task.sku} found in the bin`);
    const missing = el("button", { className: "btn btn-small", textContent: "Not on shelf" });
    missing.onclick = guarded($("picker-message"),
      () => reportShort(job, task, found.value === "" ? undefined : Number(found.value)));
    item.append(el("div", { className: "row row-wrap" },
      scanRight, ...(left > 1 ? [scanOne] : []), scanWrong, ...(task.qty > 1 ? [found] : []), missing));
  } else {
    item.append(el("span", { className: `task-status ${task.status}` }, TASK_STATUS_TEXT[task.status] || task.status));
  }
  return item;
}

function renderJob() {
  const jobs = state.jobs;
  $("job-panel").hidden = !jobs.length;
  if (!jobs.length) return;
  $("job-title").textContent = inBatch()
    ? `Batch: ${jobs.map((j) => `tote ${j.tote} ${j.order_id}`).join(" · ")}`
    : `Order ${jobs[0].order_id}`;
  // One walk serves the whole batch: every line of every order, nearest bin first.
  const lines = jobs.flatMap((job) => job.tasks.map((task) => ({ job, task })));
  lines.sort((a, b) => (a.task.walk_seq ?? 1e6) - (b.task.walk_seq ?? 1e6)
    || (a.job.tote || "").localeCompare(b.job.tote || "") || a.task.seq - b.task.seq);
  $("task-list").replaceChildren(...lines.map(({ job, task }) => renderLine(job, task)));
  const ready = jobs.find((j) => j.state === "picking" && !j.tasks.some((t) => t.status === "pending"));
  $("pack-row").hidden = !ready;
  $("pack").textContent = ready && inBatch() ? `Mark tote ${ready.tote} packed` : "Mark packed";
  const offered = state.offer && jobs.find((j) => j.job_id === state.offer.jobId && j.state === "picking");
  $("offer-row").hidden = !offered;
  if (offered) {
    const { qty, name, price } = state.offer;
    $("offer-text").textContent = `${toteLabel(offered)}Offer the customer ${qty} × ${name} (Rs ${price}) instead?`;
  }
  const bagged = jobs.find((j) => j.state === "packed");
  $("handover").hidden = !bagged;
  $("handover").textContent = bagged && inBatch() ? `Rider collected tote ${bagged.tote}` : "Rider collected the bag";
}

async function scanTask(job, task, barcode, qty) {
  const result = await api("POST", `/v1/pick-tasks/${task.task_id}/scans`, { barcode, qty, picker_id: picker() }, picker())
    .catch((error) => explainIfOrderGone(error, job));
  if (!result) return;
  if (!result.match) {
    say($("picker-message"), toteLabel(job) + result.message, "bad");
    return;
  }
  updateJob(result.job);
  const lineDone = result.job.tasks.find((t) => t.task_id === task.task_id)?.status === "picked";
  const left = linesLeft();
  if (!lineDone) say($("picker-message"), toteLabel(job) + result.message, "good");     // "3 of 6 scanned."
  else say($("picker-message"), left ? `Picked. ${left} to go.` : `All lines done. Pack ${inBatch() ? "each tote" : "the order"}.`, "good");
  renderJob();
}

async function reportShort(job, task, found) {
  const body = found === undefined ? { picker_id: picker() } : { found, picker_id: picker() };
  const result = await api("POST", `/v1/pick-tasks/${task.task_id}/short`, body, picker())
    .catch((error) => explainIfOrderGone(error, job));
  if (!result) return;
  updateJob(result.job);
  // Dropped units with something similar in stock: the customer may take it instead (task 2.4).
  state.offer = result.substitute_offer
    ? { jobId: job.job_id, droppedSkuId: task.sku_id, qty: result.dropped, ...result.substitute_offer } : null;
  say($("picker-message"), toteLabel(job) + result.message, result.dropped ? "bad" : "");
  renderJob();
  refreshOps();
}

/** In a real app the customer answers the offer on their phone; in the demo the picker answers for them. */
async function acceptOffer() {
  const offer = state.offer;
  const job = state.jobs.find((j) => j.job_id === offer.jobId);
  state.offer = null;
  const result = await api("POST", `/v1/fulfilment-jobs/${offer.jobId}/substitutions`,
    { dropped_sku_id: offer.droppedSkuId, substitute_sku_id: offer.sku_id, qty: offer.qty, picker_id: picker() },
    picker()).catch((error) => { renderJob(); return explainIfOrderGone(error, job); });
  if (!result) return;
  updateJob(result.job);
  say($("picker-message"), toteLabel(job) + result.message, "good");
  renderJob();
  refreshOps();
}

function declineOffer() {
  state.offer = null;
  say($("picker-message"), "No substitute: the missing item stays refunded.");
  renderJob();
}

async function packJob() {
  const job = state.jobs.find((j) => j.state === "picking" && !j.tasks.some((t) => t.status === "pending"));
  if (!job) return;
  const slot = $("crate-slot").value.trim() || "S-01";
  const label = toteLabel(job);
  const packed = await api("POST", `/v1/fulfilment-jobs/${job.job_id}/packed`, { crate_slot: slot, picker_id: picker() }, picker())
    .catch((error) => explainIfOrderGone(error, job));
  if (!packed) return;
  const done = packed.state === "packed";
  if (done) {
    updateJob(packed);                     // kept until the rider collects it
    $("crate-slot").value = nextSlot(slot);
  } else {
    dropJob(packed.job_id);
  }
  say($("picker-message"),
    label + (done ? `Packed into ${slot}. The stock has now left the books.` : "Nothing could be picked, so the order was cancelled."),
    done ? "good" : "bad");
  renderJob();
  refreshOps();
}

async function handover() {
  const bagged = state.jobs.find((j) => j.state === "packed");
  if (!bagged) return;
  // The rider system's rider for this order checks in at the desk, which scans the bag before handing it over
  // (task 2.7): only this order's bag goes to this order's rider.
  // An order packed before riders were assigned has none: the first stand-in rider comes for it, and the server
  // gives the order to the rider who comes.
  const rider = bagged.rider?.rider_id || "R-11";
  const desk = await api("POST", `/v1/riders/${rider}/arrive`, { order_id: bagged.order_id }, picker());
  const job = await api("POST", `/v1/fulfilment-jobs/${bagged.job_id}/handover`,
    { rider_id: rider, scanned_order_id: bagged.order_id }, picker());
  say($("picker-message"), `Rider ${rider} collected order ${job.order_id} from ${desk.crate_slot}.`, "good");
  dropJob(job.job_id);
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
    ["Event relay lag", `${d.outbox_lag_seconds} s`, d.outbox_lag_seconds > 30],
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
  const { transfer_order: order, capped = [] } = await api("POST", `/v1/replenishment/run?store_id=${state.opsStore}`, undefined, manager());
  const cut = capped.length
    ? ` Not enough shelf space for: ${capped.map((c) => `${c.sku} (${c.ordered} of ${c.wanted})`).join(", ")}.`
    : "";
  say($("ops-message"), (order
    ? `Transfer order #${order.transfer_order_id} raised for ${order.lines.map((l) => `${l.qty_ordered} × ${l.sku}`).join(", ")}.`
    : capped.length ? "Nothing ordered." : "Nothing to reorder: every item is above its reorder point or already on its way.") + cut);
  await refreshOps();
}

async function runForecast() {
  const rows = await api("POST", `/v1/forecasting/run?store_id=${state.opsStore}`, undefined, manager());
  const updated = rows.filter((r) => r.daily_demand > 0).length;
  const model = rows.length ? rows[0].model.replaceAll("_", " ") : "forecast";
  say($("ops-message"), `Forecasts recalculated with the ${model} model. Reorder points updated for ${updated} ${updated === 1 ? "item" : "items"}.`);
  await refreshOps();
}

async function sweepHolds() {
  const { released } = await api("POST", "/v1/admin/sweep-reservations", undefined, ADMIN);
  say($("ops-message"), released ? `${released} expired ${released === 1 ? "hold" : "holds"} released.` : "No holds have expired.");
  await refreshOps();
  await loadProducts();
}

async function resetDemo() {
  if (!window.confirm("Reset all demo data for everyone using this copy? Every order, hold and stock change will be wiped.")) return;
  await api("POST", "/v1/admin/reset", undefined, ADMIN);
  clearHold();
  showPaid(null);
  state.cart = {};
  state.jobs = [];
  state.walkSize = 0;
  state.offer = null;
  renderJob();
  say($("ops-message"), "Demo data reset.");
  say($("customer-message"), "");
  say($("picker-message"), "");
  await refreshOps();
  await loadProducts();
}

// ---------------------------------------------------------------- start-up

// ---------------------------------------------------------------- live feed

// The server pushes each of the ops store's events over a WebSocket (task 4.5), so the ops desk
// refreshes as soon as something happens. If the socket is down, the 3-second poll takes over.
const live = { socket: null, refreshTimer: null, generation: 0 };

async function connectLive() {
  const generation = ++live.generation; // a newer call (store switch, retry) makes this one give up
  const old = live.socket;
  live.socket = null; // set before close, so the old socket's onclose does not schedule a reconnect
  old?.close();
  const store = state.opsStore;
  const token = await tokenFor(manager());
  if (generation !== live.generation) return;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/v1/ws/events?store_id=${store}`);
  live.socket = socket;
  socket.onopen = () => socket.send(token); // first message is the login: browsers cannot set headers here
  socket.onmessage = (message) => {
    const { type } = JSON.parse(message.data);
    if (type === "ping" || type === "connected") return;
    // One action can publish several events; refresh once for the burst.
    clearTimeout(live.refreshTimer);
    live.refreshTimer = setTimeout(() => refreshOps().catch(() => {}), 100);
  };
  socket.onclose = () => {
    if (live.socket !== socket) return; // replaced on purpose (store changed)
    live.socket = null;
    delete tokens[manager()]; // the token may have expired: log in afresh next time
    setTimeout(() => connectLive().catch(() => {}), 3000);
  };
}

const liveIsOpen = () => live.socket?.readyState === WebSocket.OPEN;

async function start() {
  const stores = await api("GET", "/v1/stores");
  $("store-select").replaceChildren(...stores.map((s) => el("option", { value: s.store_id }, s.name)));
  $("store-select").onchange = guarded($("ops-message"), async () => {
    state.opsStore = Number($("store-select").value);
    $("picker-id").textContent = picker();
    state.jobs = [];
    state.walkSize = 0;
    state.offer = null;
    renderJob();
    connectLive().catch(() => {});
    await refreshOps();
  });

  $("check-location").onclick = guarded($("customer-message"), checkLocation);
  $("checkout").onclick = guarded($("customer-message"), checkout);
  $("pay").onclick = guarded($("customer-message"), pay);
  $("cancel-hold").onclick = guarded($("customer-message"), cancelHold);
  $("cancel-paid").onclick = guarded($("customer-message"), cancelPaidOrder);
  $("next-job").onclick = guarded($("picker-message"), nextJob);
  $("pack").onclick = guarded($("picker-message"), packJob);
  $("handover").onclick = guarded($("picker-message"), handover);
  $("accept-offer").onclick = guarded($("picker-message"), acceptOffer);
  $("decline-offer").onclick = guarded($("picker-message"), declineOffer);
  $("run-replenishment").onclick = guarded($("ops-message"), runReplenishment);
  $("run-forecast").onclick = guarded($("ops-message"), runForecast);
  $("sweep-holds").onclick = guarded($("ops-message"), sweepHolds);
  $("reset-demo").onclick = guarded($("ops-message"), resetDemo);

  await refreshOps();
  await checkLocation();
  connectLive().catch(() => {});

  // Keep the ops desk and the shop shelf live, so changes made in another tab show up.
  setInterval(() => { if (!liveIsOpen()) refreshOps().catch(() => {}); }, 3000);
  setInterval(() => { if (!state.hold) loadProducts().catch(() => {}); }, 5000);
}

start().catch((error) => say($("ops-message"), error.message, "bad"));
