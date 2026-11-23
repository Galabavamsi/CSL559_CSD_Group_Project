// Hub intake, on a phone at the dock: a receiver weighs and grades a farm lot, the server packs what was accepted
// into the units customers buy, and the receiver puts each portion into its bin. A pack is on sale the moment its
// bin is confirmed. Open /intake.html?store=1. Plain JavaScript, no build step; common.js has the helpers.

const dock = {
  store: Number(new URLSearchParams(location.search).get("store")) || 1,
  units: {},        // produce item id -> the units customers buy it in, smallest first
  lot: null,        // the lot being weighed
  grade: "A",
  receipt: null,    // the goods receipt being put away
  done: 0,          // portions put away for this receipt, for the progress line
};
const me = () => `receiver${dock.store}`;
const kg = (n) => `${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })} kg`;
const clock = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
const slot = (lot) => `${new Date(lot.drop_from).toLocaleDateString("en-IN", { weekday: "short", day: "numeric",
  month: "short" })}, ${clock(lot.drop_from)} to ${clock(lot.drop_until)}`;
const day = (date) => new Date(`${date}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
// One key per action, so a tap repeated on a bad connection is done once.
// (crypto.randomUUID needs HTTPS; getRandomValues also works on a plain-HTTP address.)
const newKey = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");

/** A write with an Idempotency-Key, as the receiver of this hub. */
async function write(path, body, key) {
  const res = await fetch(path, {
    method: "POST",
    headers: { Authorization: `Bearer ${await tokenFor(me())}`, "Content-Type": "application/json",
      "Idempotency-Key": key },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error?.message || `Request failed (${res.status})`);
    error.code = data.error?.code;
    throw error;
  }
  return data;
}

function show(card) {
  for (const id of ["lots", "weigh", "putaway"]) $(id).hidden = id !== card;
}

// ---------------------------------------------------------------- the lots

function lotRow(lot, label, onclick) {
  const record = lot.rejection_rate_30d === undefined ? ""
    : lot.rejection_rate_30d === null ? " · first delivery"
    : ` · ${Math.round(lot.rejection_rate_30d * 100)}% turned away in 30 days`;
  return el("li", {},
    el("div", {},
      el("p", { className: "lot-name" }, `${lot.item}, ${kg(lot.qty_kg)}`),
      el("p", { className: "lot-meta" }, [lot.farm, lot.farmer].filter(Boolean).join(" · ")),
      el("p", { className: "lot-meta" }, `Slot ${slot(lot)}${record}`)),
    el("button", { className: "btn btn-primary", onclick }, label));
}

async function loadLots() {
  const [expected, waiting] = await Promise.all([
    api("GET", `/v1/stores/${dock.store}/expected-drops`, undefined, me()),
    api("GET", `/v1/stores/${dock.store}/lots-on-dock`, undefined, me()),
  ]);
  $("expected").replaceChildren(...(expected.length
    ? expected.map((lot) => lotRow(lot, "Weigh", () => startWeighing(lot)))
    : [el("li", { className: "empty" }, "No lots are on their way to this hub.")]));
  $("waiting-block").hidden = !waiting.length;
  $("waiting").replaceChildren(...waiting.map((lot) => lotRow(lot, "Put away",
    guarded($("message"), () => startPutaway(lot.quality_check.receipt_id)))));
  show("lots");
}

// ---------------------------------------------------------------- weighing and grading

function setGrade(grade) {
  dock.grade = grade;
  for (const button of $("grades").children) button.setAttribute("aria-checked", String(button.dataset.grade === grade));
  $("rejected").disabled = grade === "reject";      // a rejected lot is turned away whole
  preview();
}

/** What recording will do, worked out here only to show it: the server decides. */
function preview() {
  const received = Number($("received").value);
  const rejected = dock.grade === "reject" ? received : Number($("rejected").value) || 0;
  let text;
  if (!(received > 0)) text = "Enter the weight that arrived.";
  else if (dock.grade === "reject") text = `All ${kg(received)} turned away. Nothing is packed, and the farmer sees why.`;
  else if (rejected < 0 || rejected >= received) text = "The weight turned away must be less than the weight that arrived. To turn the whole lot away, grade it Reject.";
  else {
    const grams = Math.round((received - rejected) * 1000);
    const unit = dock.units[dock.lot.item_id]?.[0];
    if (!unit) text = `${kg(grams / 1000)} accepted.`;
    else {
      const packs = Math.floor(grams / unit.unit_grams);
      const trim = grams - packs * unit.unit_grams;
      text = `${kg(grams / 1000)} accepted: ${packs} × ${unit.name}` + (trim ? `, and ${kg(trim / 1000)} of trim.` : ".");
    }
  }
  $("preview").textContent = text;
}

function startWeighing(lot) {
  dock.lot = lot;
  dock.key = newKey();
  $("weigh-lot").textContent = `${lot.item}, ${kg(lot.qty_kg)} listed`;
  $("weigh-from").textContent = `${[lot.farm, lot.farmer].filter(Boolean).join(" · ")} · harvested ${day(lot.harvest_date)}`;
  $("received").value = String(lot.qty_kg);
  $("rejected").value = "0";
  $("remarks").value = "";
  setGrade("A");
  say($("message"), "");
  show("weigh");
}

async function record() {
  const lot = dock.lot;
  const body = { received_kg: Number($("received").value), rejected_kg: Number($("rejected").value) || 0,
    grade: dock.grade, remarks: $("remarks").value.trim() || null };
  if (!(body.received_kg > 0)) return say($("message"), "Enter the weight that arrived.", "bad");
  const result = await write(`/v1/listings/${lot.listing_id}/intake`, body, `intake-${dock.key}`);
  const check = result.quality_check;
  if (!result.receipt) {              // rejected, or too little to fill one pack
    await loadLots();
    return say($("message"), `${lot.item} from ${lot.farm}: ${kg(check.rejected_kg)} turned away, nothing packed.`, "bad");
  }
  const packed = result.packed.map((line) => `${line.units} × ${line.sku}`).join(", ");
  say($("message"), `Grade ${check.grade}: ${kg(check.accepted_kg)} accepted, packed as ${packed}`
    + (check.trim_kg ? `, ${kg(check.trim_kg)} trim` : "") + `. Batch ${check.batch_no}.`, "good");
  await startPutaway(result.receipt.receipt_id);
}

// ---------------------------------------------------------------- putting away

async function startPutaway(receiptId) {
  dock.receipt = receiptId;
  dock.done = 0;
  await nextPortion();
}

/** Show the next portion to put away, or close the receipt when nothing is left on the dock. */
async function nextPortion() {
  const tasks = await api("GET", `/v1/goods-receipts/${dock.receipt}/putaway-tasks`, undefined, me());
  if (!tasks.length) return closeReceipt(false);
  const task = tasks[0];
  dock.task = task;
  dock.key = newKey();
  const stuck = task.bin_code === null;       // no bin has room, or the batch number clashes: the server says which
  $("put-progress").textContent = `Portion ${dock.done + 1} of ${dock.done + tasks.length} · batch ${task.batch_no}, use by ${day(task.expiry_date)}`;
  $("put-what").textContent = `${task.qty} × ${task.sku}`;
  $("put-go").hidden = $("put-bin").hidden = $("put-btn").hidden = stuck;
  $("put-bin").textContent = task.bin_code ?? "";
  $("put-problem").hidden = $("send-back").hidden = !stuck;
  $("put-problem").textContent = task.problem ?? "";
  show("putaway");
}

async function putAway() {
  const task = dock.task;
  await write(`/v1/goods-receipts/${dock.receipt}/putaway`,
    { sku_id: task.sku_id, batch_no: task.batch_no, bin_code: task.bin_code, qty: task.qty }, `putaway-${dock.key}`);
  dock.done += 1;
  say($("message"), `${task.qty} × ${task.sku} in ${task.bin_code}: on sale now.`, "good");
  await nextPortion();
}

async function closeReceipt(sendBack) {
  const closed = await write(`/v1/goods-receipts/${dock.receipt}/close${sendBack ? "?send_back=true" : ""}`, null,
    `close-${dock.receipt}-${sendBack}`);
  const onSale = closed.lines.reduce((total, line) => total + line.put_away, 0);
  const back = closed.lines.reduce((total, line) => total + line.sent_back, 0);
  dock.receipt = null;
  await loadLots();
  say($("message"), `Done: ${onSale} pack${onSale === 1 ? "" : "s"} on sale` + (back ? `, ${back} sent back.` : "."),
    back ? "bad" : "good");
}

// ---------------------------------------------------------------- start

async function start() {
  const stores = await api("GET", "/v1/stores");
  $("store").replaceChildren(...stores.map((s) => el("option", { value: String(s.store_id) }, s.name)));
  if (!stores.some((s) => s.store_id === dock.store)) dock.store = stores[0]?.store_id ?? 1;
  $("store").value = String(dock.store);
  $("who").textContent = me();
  $("store").onchange = guarded($("message"), async () => {
    dock.store = Number($("store").value);
    history.replaceState(null, "", `?store=${dock.store}`);
    $("who").textContent = me();
    say($("message"), "");
    await loadLots();
  });
  for (const button of $("grades").children) button.onclick = () => setGrade(button.dataset.grade);
  $("received").oninput = $("rejected").oninput = preview;
  $("record").onclick = guarded($("message"), record);
  $("weigh-back").onclick = guarded($("message"), loadLots);
  $("reload").onclick = guarded($("message"), async () => { say($("message"), ""); await loadLots(); });
  $("put-btn").onclick = guarded($("message"), putAway);
  $("send-back").onclick = guarded($("message"), () => closeReceipt(true));
  for (const item of await api("GET", "/v1/produce-items")) dock.units[item.item_id] = item.units;
  await loadLots();
}

guarded($("message"), start)();
