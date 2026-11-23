// Picker phone screen (task 2.8): the same API as the demo's picker station, one line at a time.
// Open http://<laptop-ip>:8000/picker.html?store=1 on a phone on the same Wi-Fi (start the app with --host 0.0.0.0).

const phone = {
  store: Number(new URLSearchParams(location.search).get("store")) || 1,
  jobs: [],         // the orders being picked: one, or a batch at peak (task 2.6)
  walkSize: 0,      // how many orders this walk started with, so the last one of a batch keeps its tote
  offer: null,      // a substitute offered for dropped units, waiting for the customer's answer (task 2.4)
};
const me = () => `picker${phone.store}`;
// A walk is a batch if it started with more than one order (or, after a reload, still holds a tote past A).
const batch = () => phone.walkSize > 1 || phone.jobs.some((j) => j.tote && j.tote !== "A");

/** Lines still to pick from every order, nearest bin first: the order the picker walks them. */
function linesToPick() {
  const lines = phone.jobs.filter((job) => job.state === "picking")
    .flatMap((job) => job.tasks.filter((task) => task.status === "pending").map((task) => ({ job, task })));
  return lines.sort((a, b) => (a.task.walk_seq ?? 1e6) - (b.task.walk_seq ?? 1e6)
    || (a.job.tote || "").localeCompare(b.job.tote || "") || a.task.seq - b.task.seq);
}

function show(card) {
  for (const id of ["idle", "offer", "line", "pack"]) $(id).hidden = id !== card;
}

function render() {
  $("who").textContent = me();
  const offered = phone.offer && phone.jobs.find((j) => j.job_id === phone.offer.jobId && j.state === "picking");
  if (offered) {                                      // answer the offer before walking on
    const { qty, name, price } = phone.offer;
    $("offer-what").textContent = `${batch() ? `Tote ${offered.tote}: ` : ""}${qty} × ${name} (Rs ${price})`;
    show("offer");
    return;
  }
  phone.offer = null;
  const lines = linesToPick();
  if (lines.length) {
    const { job, task } = lines[0];
    const left = task.qty - task.scanned_qty;
    $("progress").textContent = `${lines.length} line${lines.length === 1 ? "" : "s"} to go`
      + (batch() ? ` · ${phone.jobs.length} orders in this walk` : ` · order ${job.order_id}`);
    $("bin").textContent = task.bin;
    $("what").textContent = `Pick ${task.qty} × ${task.sku}`;
    $("scanned").textContent = task.qty > 1 ? `${task.scanned_qty} of ${task.qty} scanned` : "";
    $("tote").hidden = !batch();
    $("tote").textContent = `Into tote ${job.tote}`;
    $("scan-all").hidden = left < 2;
    $("scan-all").textContent = `Scan all ${left}`;
    $("found").value = "";
    $("found").max = String(task.qty - 1);
    $("found").hidden = task.qty < 2;
    show("line");
    return;
  }
  const ready = phone.jobs.find((job) => job.state === "picking");          // every line done: pack it
  if (ready) {
    $("pack-what").textContent = batch() ? `Pack tote ${ready.tote}: order ${ready.order_id}` : `Pack order ${ready.order_id}`;
    show("pack");
    return;
  }
  show("idle");
}

function current() {
  return linesToPick()[0];
}

function replaceJob(job) {
  phone.jobs = phone.jobs.map((j) => (j.job_id === job.job_id ? job : j));
}

function dropJob(jobId) {
  phone.jobs = phone.jobs.filter((j) => j.job_id !== jobId);
}

/** The order was cancelled (task 2.3), or sat idle and went to someone else (task 2.5): drop it, say what to do. */
async function orderGone(error, job) {
  if (!["job_not_picking", "not_your_order"].includes(error.code)) throw error;
  const now = await api("GET", `/v1/fulfilment-jobs/${job.job_id}`, undefined, me());
  const label = batch() ? `Tote ${job.tote}: ` : "";
  dropJob(job.job_id);
  render();
  say($("message"), label + (now.state === "cancelled"
    ? "This order was cancelled. Put its items back on their shelves."
    : "This order sat idle, so it went back to the queue. Put back anything you took for it."), "bad");
}

async function nextOrder() {
  const result = await api("GET", `/v1/pickers/${me()}/next-batch?store_id=${phone.store}`, undefined, me());
  // Asking again mid-walk returns what is left of the same walk: it stays a batch even when one order remains.
  const sameWalk = result.jobs.length > 0 && result.jobs.every((j) => phone.jobs.some((s) => s.job_id === j.job_id));
  phone.walkSize = sameWalk ? Math.max(phone.walkSize, result.jobs.length) : result.jobs.length;
  phone.jobs = result.jobs;
  say($("message"), !result.jobs.length ? "No paid orders are waiting."
    : batch() ? `Busy store: ${result.jobs.length} orders in one walk. Each item goes in the tote shown.` : "");
  render();
}

async function scan(all) {
  const { job, task } = current();
  const qty = all ? task.qty - task.scanned_qty : 1;
  let result;
  try {
    result = await api("POST", `/v1/pick-tasks/${task.task_id}/scans`,
      { barcode: task.barcode, qty, picker_id: me() }, me());
  } catch (error) {
    return orderGone(error, job);
  }
  if (!result.match) return say($("message"), result.message, "bad");
  replaceJob(result.job);
  const left = linesToPick().length;
  say($("message"), result.message === "Picked." ? (left ? `Picked. ${left} to go.` : "All picked. Back to the desk.")
    : result.message, "good");
  render();
}

async function notOnShelf() {
  const { job, task } = current();
  const found = $("found").value === "" ? undefined : Number($("found").value);
  let result;
  try {
    result = await api("POST", `/v1/pick-tasks/${task.task_id}/short`,
      found === undefined ? { picker_id: me() } : { found, picker_id: me() }, me());
  } catch (error) {
    return orderGone(error, job);
  }
  replaceJob(result.job);
  phone.offer = result.substitute_offer
    ? { jobId: job.job_id, droppedSkuId: task.sku_id, qty: result.dropped, ...result.substitute_offer } : null;
  say($("message"), result.message, result.dropped ? "bad" : "");
  render();
}

/** In a real app the customer answers on their own phone; in the demo the picker answers for them. */
async function acceptOffer() {
  const offer = phone.offer;
  const job = phone.jobs.find((j) => j.job_id === offer.jobId);
  phone.offer = null;
  let result;
  try {
    result = await api("POST", `/v1/fulfilment-jobs/${offer.jobId}/substitutions`,
      { dropped_sku_id: offer.droppedSkuId, substitute_sku_id: offer.sku_id, qty: offer.qty, picker_id: me() }, me());
  } catch (error) {
    if (error.code === "not_offered") {         // stock moved since the offer was shown
      const now = error.details?.offered;
      phone.offer = now ? { ...offer, ...now } : null;
      say($("message"), now ? `The offer changed: ${now.name} (Rs ${now.price}) is on offer now.`
        : "Nothing similar is in stock any more: the missing item stays refunded.", "bad");
      return render();
    }
    render();
    return orderGone(error, job);
  }
  replaceJob(result.job);
  say($("message"), result.message, "good");
  render();
}

function declineOffer() {
  phone.offer = null;
  say($("message"), "No substitute: the missing item stays refunded.");
  render();
}

async function pack() {
  const job = phone.jobs.find((j) => j.state === "picking");
  const slot = $("slot").value.trim() || "S-01";
  let packed;
  try {
    packed = await api("POST", `/v1/fulfilment-jobs/${job.job_id}/packed`, { crate_slot: slot, picker_id: me() }, me());
  } catch (error) {
    return orderGone(error, job);
  }
  const label = batch() ? `Tote ${job.tote}: ` : "";
  dropJob(job.job_id);
  if (packed.state === "packed") {
    $("slot").value = nextSlot(slot);
    say($("message"), `${label}Packed into ${slot}. Leave it for the rider.`, "good");
  } else {
    say($("message"), `${label}Nothing could be picked, so the order was cancelled.`, "bad");
  }
  render();
}

function start() {
  $("store").value = String(phone.store);
  // The page ships with hubs 1 and 2; a hub opened since is added here.
  api("GET", "/v1/stores").then((stores) => {
    $("store").replaceChildren(...stores.map((s) => el("option", { value: String(s.store_id) }, String(s.store_id))));
    $("store").value = String(phone.store);
  }).catch(() => {});
  $("store").onchange = () => {
    phone.store = Number($("store").value);
    phone.jobs = [];
    phone.walkSize = 0;
    phone.offer = null;
    history.replaceState(null, "", `?store=${phone.store}`);
    say($("message"), "");
    render();
  };
  $("next").onclick = guarded($("message"), nextOrder);
  $("scan-one").onclick = guarded($("message"), () => scan(false));
  $("scan-all").onclick = guarded($("message"), () => scan(true));
  $("short").onclick = guarded($("message"), notOnShelf);
  $("pack-btn").onclick = guarded($("message"), pack);
  $("accept-offer").onclick = guarded($("message"), acceptOffer);
  $("decline-offer").onclick = guarded($("message"), declineOffer);
  render();
  // Pick up orders this picker was already working on (e.g. after a page reload) without claiming new ones.
  api("GET", `/v1/fulfilment-jobs?store_id=${phone.store}&state=picking`, undefined, me())
    .then((jobs) => {
      phone.jobs = jobs.filter((job) => job.picker_id === me()).sort((a, b) => (a.tote || "").localeCompare(b.tote || ""));
      phone.walkSize = phone.jobs.length;
      render();
    })
    .catch(() => {});
}

start();
