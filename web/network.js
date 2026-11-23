// Network planning map (task 4.4): store zones, demand by H3 cell, and suggested new sites.
// Plain JavaScript, no build step. Logs in as the seeded ops user, like the stations in app.js.

const $ = (id) => document.getElementById(id);
// Map colours come from .network in styles.css: fixed values, because the map tiles are light in either theme.
const colour = (name) => getComputedStyle($("map")).getPropertyValue(name).trim();
const customers = (n) => `+${n} customer${n === 1 ? "" : "s"}`;

let token = null;
let fitted = null; // the area last fitted: the stores and the suggested sites
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
      .bindTooltip(`${cell.orders} paid orders, ${cell.misses} turned away`)
      .addTo(layers);
  }
}

async function load() {
  const [stores, cells, sites] = await Promise.all([
    api("/v1/stores"),
    api("/v1/network-planning/heatmap"),
    api("/v1/network-planning/suggestions"),
  ]);
  layers.clearLayers();

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
        el("strong", {}, customers(site.demand_gained))))
    : [el("li", { className: "empty" }, "No turned-away customers yet, so nothing to suggest.")]));

  const sum = (field) => cells.reduce((total, c) => total + c[field], 0);
  $("totals").replaceChildren(
    ...[["Paid orders", sum("orders")], ["Turned away", sum("misses")], ["Cells with demand", cells.length]]
      .map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, String(value)))));

  const points = [...stores.map((s) => [s.lat, s.lng]), ...sites.map((s) => [s.lat, s.lng])];
  if (points.length) {
    fitted = L.latLngBounds(points).pad(0.4);
    map.fitBounds(fitted);
  }
  $("network-message").textContent = "";
}

function refresh() {
  load().catch((error) => {
    $("network-message").textContent = error.message;
    $("network-message").className = "message is-bad";
  });
}

$("refresh").onclick = refresh;
refresh();
