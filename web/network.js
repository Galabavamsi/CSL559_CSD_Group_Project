// Network planning map (task 4.4): store zones, demand by H3 cell, and suggested new sites.
// Plain JavaScript, no build step. Logs in as the seeded ops user, like the stations in app.js.

const $ = (id) => document.getElementById(id);
// Map colours come from .network in styles.css: fixed values, because the map tiles are light in either theme.
const colour = (name) => getComputedStyle($("map")).getPropertyValue(name).trim();
const customers = (n) => `+${n} customer${n === 1 ? "" : "s"}`;

let token = null;
let fitted = null; // the area last fitted: the stores and the suggested sites, or the city chosen
let cities = [];   // from /v1/cities, for the city chooser
// ?city=bhilai opens the map on one city; the chooser changes it. Everything is still drawn: only the view moves.
let city = new URLSearchParams(location.search).get("city") || "";
const map = L.map("map");
const layers = L.layerGroup().addTo(map);
// Fit again whenever the map's box changes size. A fit made while the box had no size (the page laid out late,
// a window resized for a projector) would otherwise stay zoomed out to the whole world.
new ResizeObserver(() => {
  map.invalidateSize();
  if (fitted) map.fitBounds(fitted);
}).observe($("map"));
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

async function api(path, isRetry = false) {
  token ??= await staffLogin("ops"); // staff-login.js
  const res = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
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

function drawCells(cells, field, fill) {
  const most = Math.max(1, ...cells.map((c) => c[field]));
  for (const cell of cells.filter((c) => c[field] > 0)) {
    L.polygon(cell.boundary, { color: fill, weight: 1, fillColor: fill, fillOpacity: 0.3 + 0.6 * (cell[field] / most) })
      .bindTooltip(`${cell.orders} paid orders, ${cell.misses} turned away, ${cell.requests || 0} asked for delivery`)
      .addTo(layers);
  }
}

async function load() {
  const [stores, cells, sites, allCities] = await Promise.all([
    api("/v1/stores"),
    api("/v1/network-planning/heatmap"),
    api("/v1/network-planning/suggestions"),
    api("/v1/cities"),
  ]);
  layers.clearLayers();
  cities = allCities;
  $("city").replaceChildren(el("option", { value: "" }, "All cities"),
    ...cities.map((c) => el("option", { value: c.city }, `${c.name} (${c.hubs} hub${c.hubs === 1 ? "" : "s"})`)));
  $("city").value = cities.some((c) => c.city === city) ? city : "";

  for (const s of stores) {
    L.circle([s.lat, s.lng], { radius: s.radius_km * 1000, color: colour("--map-zone"), weight: 3, fillOpacity: 0.08 })
      .bindTooltip(el("span", {}, `${s.name} (${s.status})`), { permanent: true, direction: "center" }) // text, not HTML
      .addTo(layers);
  }
  drawCells(cells, "orders", colour("--map-orders"));
  drawCells(cells, "misses", colour("--map-misses"));
  sites.forEach((site, i) => {
    L.circle([site.lat, site.lng], { radius: site.radius_km * 1000, color: colour("--map-ink"), weight: 2,
      dashArray: "6 6", fillColor: colour("--map-site"), fillOpacity: 0.15 }).addTo(layers);
    L.circleMarker([site.lat, site.lng], { radius: 9, color: colour("--map-ink"), weight: 2,
      fillColor: colour("--map-site"), fillOpacity: 1 })
      .bindTooltip(`Site ${i + 1}: ${customers(site.demand_gained)}`, { permanent: true, direction: "right" })
      .addTo(layers);
  });

  $("suggestions").replaceChildren(...(sites.length
    ? sites.map((site, i) => el("li", {},
        el("span", {}, `Site ${i + 1} `, el("code", {}, site.h3_cell)),
        el("strong", {}, customers(site.demand_gained)),
        el("button", { className: "btn btn-small", onclick: () => openHub(site, i + 1) }, "Open a hub here")))
    : [el("li", { className: "empty" }, "No turned-away customers yet, so nothing to suggest.")]));

  const sum = (field) => cells.reduce((total, c) => total + c[field], 0);
  $("totals").replaceChildren(
    ...[["Paid orders", sum("orders")], ["Turned away", sum("misses")], ["Asked for delivery", sum("requests")],
        ["Cells with demand", cells.length]]
      .map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, String(value)))));

  const chosen = cities.find((c) => c.city === $("city").value);
  const points = [...stores.map((s) => [s.lat, s.lng]), ...sites.map((s) => [s.lat, s.lng])];
  if (chosen) {
    fitted = L.latLng(chosen.lat, chosen.lng).toBounds(chosen.radius_km * 2000 * 1.2); // the built-up area and a margin
    map.fitBounds(fitted);
  } else if (points.length) {
    fitted = L.latLngBounds(points).pad(0.4);
    map.fitBounds(fitted);
  }
  $("network-message").textContent = "";
}

function say(text, mood) {
  $("network-message").textContent = text;
  $("network-message").className = `message is-${mood}`;
}

/** Open a hub at a suggested site. Looking at the map is the ops lead's job; opening a hub is an admin's, so this
 *  logs in again as the admin. The server creates the hub, its shelves, its zone and its logins in one change. */
async function openHub(site, number) {
  const name = window.prompt(`A name for the hub at site ${number}, for example "BH-04 Risali":`)?.trim();
  if (!name) return;
  try {
    // One key for this click, so a retry after a dropped answer cannot open the hub twice.
    // (crypto.randomUUID needs HTTPS; getRandomValues also works on a plain-HTTP address.)
    const key = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
    const res = await fetch("/v1/admin/stores", {
      method: "POST",
      headers: { Authorization: `Bearer ${await staffLogin("admin")}`, "Content-Type": "application/json",
        "Idempotency-Key": `open-hub-${key}` },
      body: JSON.stringify({ name, lat: site.lat, lng: site.lng }),
    });
    const hub = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(hub.error?.message || `The hub was not opened (${res.status})`);
    await load();
    say(`${hub.name} is open in ${hub.city}: it serves ${hub.zone_cells} cells within ${hub.radius_km} km and starts `
      + `empty. Its logins are ${hub.logins.join(", ")}.`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

function refresh() {
  load().catch((error) => say(error.message, "bad"));
}

$("refresh").onclick = refresh;
$("city").onchange = () => {
  city = $("city").value;
  history.replaceState(null, "", city ? `?city=${city}` : location.pathname);
  refresh();
};
refresh();
