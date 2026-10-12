/* Map: MapLibre + PMTiles, everything served from the drive. Works without GPS: type a town or coordinates. */
import * as maplibregl from "/static/vendor/maplibre-gl.mjs";

const B = window.B;
const $ = id => document.getElementById(id);
const esc = B.esc;
let map = null, info = null, topo = null, ready = false, protocol = false;
let from = null, to = null, route = null, mFrom = null, mTo = null, pickMode = null;
let meshData = {type: "FeatureCollection", features: []}, meshTimer = null;

const isLight = () => B.isLight();
const palette = () => isLight()
  ? {water: "#C9DCE8", land: "#EEF1EC", border: "#9AA8B2", route: "#E2480E", here: "#0F1A24"}
  : {water: "#0A1520", land: "#172838", border: "#3B5367", route: "#FF5A1F", here: "#E6EDF2"};

function arc(a, b, n = 96) {  // great-circle points between two places
  const R = Math.PI / 180, [l1, p1, l2, p2] = [a.lon * R, a.lat * R, b.lon * R, b.lat * R];
  const d = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2));
  if (d === 0) return [[a.lon, a.lat]];
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n, A = Math.sin((1 - f) * d) / Math.sin(d), Bf = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(p1) * Math.cos(l1) + Bf * Math.cos(p2) * Math.cos(l2);
    const y = A * Math.cos(p1) * Math.sin(l1) + Bf * Math.cos(p2) * Math.sin(l2);
    const z = A * Math.sin(p1) + Bf * Math.sin(p2);
    pts.push([Math.atan2(y, x) / R, Math.atan2(z, Math.sqrt(x * x + y * y)) / R]);
  }
  for (let i = 1; i < pts.length; i++) {  // keep the line continuous across the date line
    while (pts[i][0] - pts[i - 1][0] > 180) pts[i][0] -= 360;
    while (pts[i][0] - pts[i - 1][0] < -180) pts[i][0] += 360;
  }
  return pts;
}
const routeData = () => ({type: "FeatureCollection", features: from && to ? [{type: "Feature", properties: {}, geometry: {type: "LineString", coordinates: arc(from, to)}}] : []});

async function buildStyle() {
  const origin = location.origin, flavor = isLight() ? "light" : "dark", pal = palette();
  const style = {
    version: 8, glyphs: origin + "/static/vendor/fonts/{fontstack}/{range}.pbf", sprite: origin + "/static/vendor/sprites/" + flavor,
    sources: {}, layers: [{id: "bg", type: "background", paint: {"background-color": pal.water}}],
  };
  if (!topo) topo = await fetch("/static/vendor/countries-50m.json").then(r => r.json());
  style.sources.countries = {type: "geojson", data: window.topojson.feature(topo, topo.objects.countries)};
  style.layers.push({id: "c-fill", type: "fill", source: "countries", paint: {"fill-color": pal.land}},
                    {id: "c-line", type: "line", source: "countries", paint: {"line-color": pal.border, "line-width": .6}});
  if (info.maps.length && window.pmtiles && window.basemaps) {
    const files = [...info.maps].sort((a, b) => (a.kind === "world" ? -1 : 1) - (b.kind === "world" ? -1 : 1));
    files.forEach((m, i) => {
      const src = "pm" + i;
      style.sources[src] = {type: "vector", url: `pmtiles://${origin}/maps/${encodeURIComponent(m.file)}`, attribution: "© OpenStreetMap contributors, Protomaps"};
      window.basemaps.layers(src, window.basemaps.namedFlavor(flavor), {lang: "en"})
        .filter(l => l.type !== "background").forEach(l => style.layers.push({...l, id: `${src}-${l.id}`}));
    });
  }
  style.sources.mesh = {type: "geojson", data: meshData};
  style.layers.push({id: "mesh-dot", type: "circle", source: "mesh", paint: {"circle-radius": 6, "circle-color": pal.route, "circle-stroke-width": 2, "circle-stroke-color": pal.here}},
                    {id: "mesh-label", type: "symbol", source: "mesh", layout: {"text-field": ["get", "label"], "text-font": ["Noto Sans Medium"], "text-size": 12, "text-offset": [0, 1.3], "text-anchor": "top"},
                     paint: {"text-color": pal.here, "text-halo-color": pal.water, "text-halo-width": 1.5}});
  style.sources.route = {type: "geojson", data: routeData()};
  style.layers.push({id: "route-halo", type: "line", source: "route", paint: {"line-color": pal.water, "line-width": 6, "line-opacity": .6}},
                    {id: "route", type: "line", source: "route", paint: {"line-color": pal.route, "line-width": 3, "line-dasharray": [2, 1.4]}});
  return style;
}

function note(html) {
  const n = document.createElement("div");
  n.className = "map-note"; n.innerHTML = html; n.title = "Click to dismiss";
  n.onclick = () => n.remove();
  $("map").appendChild(n);
}

async function init() {
  if (map) { map.resize(); return; }
  try { info = await B.api("/api/maps"); } catch { info = {maps: [], places: false}; }
  if (info.maps.length && window.pmtiles && !protocol) {
    const p = new window.pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", p.tile);
    protocol = true;
  }
  map = new maplibregl.Map({
    container: "map", style: await buildStyle(), center: [-40, 30], zoom: 1.6,
    attributionControl: {compact: true}, canvasContextAttributes: {preserveDrawingBuffer: true},
  });
  map.addControl(new maplibregl.NavigationControl({visualizePitch: false}), "top-right");
  map.addControl(new maplibregl.ScaleControl({unit: "imperial"}), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({unit: "metric"}), "bottom-right");
  map.on("load", () => { ready = true; draw(); refreshMesh(); });
  const touch = matchMedia("(hover: none)").matches;
  if (touch) map.on("move", () => { const c = map.getCenter(); $("cursor").textContent = `Center ${c.lat.toFixed(4)}, ${c.lng.toFixed(4)}`; });
  else map.on("mousemove", e => { $("cursor").textContent = `${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}`; });
  map.on("click", onClick);
  if (!info.maps.length) {
    note(B.sys?.guest ? "This is the basic world outline. Detailed maps can be added on the Beacon computer."
      : info.places ? "This is the basic world outline. Build the world map and a detailed map of your area in <b>Library</b>, under Maps."
      : "This is the basic world outline. Add place names and maps in <b>Library</b>, under Maps. You can still type coordinates.");
  }
}

B.onTheme = async () => {
  if (!map || !info) return;
  map.setStyle(await buildStyle(), {diff: false});
  map.once("styledata", () => draw(false));
};

function marker(p, color, old) {
  old?.remove();
  if (!p) return null;
  return new maplibregl.Marker({color}).setLngLat([p.lon, p.lat]).setPopup(new maplibregl.Popup({offset: 24}).setText(p.label || "")).addTo(map);
}
function draw(fit = true) {
  if (!ready) return;
  const pal = palette();
  mFrom = marker(from, pal.here, mFrom);
  mTo = marker(to, pal.route, mTo);
  map.getSource("route")?.setData(routeData());
  if (!fit) return;
  if (from && to) {
    const c = arc(from, to), lons = c.map(p => p[0]), lats = c.map(p => p[1]);
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], {padding: 70, maxZoom: 12, duration: 600});
  } else if (from || to) {
    const p = from || to;
    map.flyTo({center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 9), duration: 700});
  }
}

async function nearestLabel(lat, lon) {
  let near = [];
  try { near = await B.api(`/api/places/nearest?lat=${lat}&lon=${lon}`); } catch {}
  return {near, label: `${lat.toFixed(4)}, ${lon.toFixed(4)}` + (near[0] ? ` (near ${near[0].name.split(",")[0]})` : "")};
}

async function update() {
  draw();
  $("planTrip").disabled = !from;
  if (from) B.lastPlace = from;
  if (from) {
    const {near} = await nearestLabel(from.lat, from.lon);
    $("nearby").innerHTML = near.length ? `<h3>Nearest towns</h3>` + near.map(n => `<div>${esc(n.name)}<span>${(n.km / 1.609344).toFixed(1)} mi (${n.km} km)</span></div>`).join("") : "";
  } else $("nearby").innerHTML = "";
  if (from && to) {
    try { route = await B.api("/api/route", {from, to}); } catch { route = null; }
    if (!route) { $("routeFacts").innerHTML = ""; return; }
    $("routeFacts").innerHTML = `<div class="facts">
      <div class="fact"><b>${route.miles.toLocaleString()} mi</b><span>${route.km.toLocaleString()} km in a straight line</span></div>
      <div class="fact"><b>${route.bearing}° ${esc(route.compass)}</b><span>heading to start (true north)</span></div>
      ${route.walk_days != null
        ? `<div class="fact"><b>${route.walk_days} days</b><span>on foot, about 15 miles (25 km) a day</span></div><div class="fact"><b>${route.drive_hours} h</b><span>driving, roughly</span></div>`
        : `<div class="fact"><b>${route.flight_hours} h</b><span>flying, nonstop</span></div><div class="fact"><b>Overseas</b><span>needs a flight or a boat</span></div>`}
    </div>`;
  } else { route = null; $("routeFacts").innerHTML = ""; }
}

function setPick(mode) {
  pickMode = mode;
  document.querySelector(".map-pick")?.remove();
  if (!map) return;
  map.getCanvas().style.cursor = mode ? "crosshair" : "";
  if (mode) {
    const n = document.createElement("div");
    n.className = "map-pick";
    n.textContent = mode === "from" ? "Tap the map where you are" : "Tap the map where you're going";
    $("map").appendChild(n);
  }
}
async function onClick(e) {
  if (!pickMode) return;
  const p = {lat: e.lngLat.lat, lon: e.lngLat.lng};
  p.label = (await nearestLabel(p.lat, p.lon)).label;
  if (pickMode === "from") { from = p; $("fromIn").value = p.label; } else { to = p; $("toIn").value = p.label; }
  setPick(null);
  update();
}

async function saveImage() {
  if (!map || !ready) return;
  await Promise.race([new Promise(r => { map.once("idle", r); map.triggerRepaint(); }), new Promise(r => setTimeout(r, 1500))]);
  const src = map.getCanvas(), w = src.width, h = src.height, k = window.devicePixelRatio || 1, band = Math.round(76 * k);
  const c = document.createElement("canvas");
  c.width = w; c.height = h + band;
  const g = c.getContext("2d");
  g.fillStyle = "#FFFFFF"; g.fillRect(0, 0, c.width, c.height);
  g.drawImage(src, 0, 0);
  const title = [from?.label, to?.label].filter(Boolean).join("  to  ") || "Map";
  const facts = route ? `${route.miles.toLocaleString()} mi (${route.km.toLocaleString()} km) in a straight line, heading ${route.bearing}° ${route.compass}. ` : "";
  g.fillStyle = "#0F1A24"; g.font = `bold ${Math.round(22 * k)}px "DIN Alternate", -apple-system, "Segoe UI", sans-serif`;
  g.fillText(title.slice(0, 90), 16 * k, h + 32 * k);
  g.fillStyle = "#4D5F6E"; g.font = `${Math.round(15 * k)}px Charter, Georgia, serif`;
  g.fillText(`${facts}Made offline by Beacon, ${new Date().toLocaleDateString()}.`, 16 * k, h + 58 * k);
  c.toBlob(b => { if (b) B.download(b, B.safeName("Beacon map " + (to?.label || from?.label || "")).replace(/\s+$/, "") + ".png"); }, "image/png");
}

/* Meshtastic radios that share their position appear on the map. */
async function refreshMesh() {
  clearTimeout(meshTimer);
  let r = null;
  try { r = await B.api("/api/mesh"); } catch {}
  const nodes = (r && r.state === "connected" ? r.nodes_list : []).filter(n => n.lat != null && n.lon != null);
  meshData = {type: "FeatureCollection", features: nodes.map(n => ({type: "Feature", properties: {label: n.short || n.name},
    geometry: {type: "Point", coordinates: [n.lon, n.lat]}}))};
  if (ready) map.getSource("mesh")?.setData(meshData);
  if (B.tab === "map") meshTimer = setTimeout(refreshMesh, 30000);
}

/* ---------------------------------------------------------------- wiring */
B.tabHooks.map = () => { setTimeout(init, 30); if (ready) refreshMesh(); };
if (B.tab === "map") init();
B.wireSuggest($("fromIn"), $("fromSug"), p => { from = p; update(); });
B.wireSuggest($("toIn"), $("toSug"), p => { to = p; update(); });
$("clickFrom").onclick = () => setPick("from");
$("clickTo").onclick = () => setPick("to");
$("swapBtn").onclick = () => { [from, to] = [to, from]; [$("fromIn").value, $("toIn").value] = [$("toIn").value, $("fromIn").value]; update(); };
$("clearRoute").onclick = () => { from = to = null; $("fromIn").value = $("toIn").value = ""; $("gpsNote").textContent = ""; update(); };
$("gpsBtn").onclick = async () => {
  // A mesh radio with GPS plugged into the Beacon computer knows where it is, even with no internet.
  let radio = null;
  try { const m = await B.api("/api/mesh"); radio = m.state === "connected" ? m.position : null; } catch {}
  if (radio) {
    from = {lat: radio.lat, lon: radio.lon};
    from.label = (await nearestLabel(from.lat, from.lon)).label;
    $("fromIn").value = from.label;
    $("gpsNote").textContent = "From the GPS in the mesh radio plugged into the Beacon computer.";
    update();
    return;
  }
  if (!window.isSecureContext) {
    $("gpsNote").textContent = "Phones can't share their location over this Wi-Fi link. Type your town, or the coordinates shown in your phone's Compass or Maps app.";
    return;
  }
  if (!navigator.geolocation) { $("gpsNote").textContent = "This browser can't read a location. Type your town or coordinates instead."; return; }
  $("gpsNote").textContent = "Asking this device for its location…";
  navigator.geolocation.getCurrentPosition(async pos => {
    from = {lat: pos.coords.latitude, lon: pos.coords.longitude};
    from.label = (await nearestLabel(from.lat, from.lon)).label;
    $("fromIn").value = from.label;
    $("gpsNote").textContent = `Accurate to about ${Math.round(pos.coords.accuracy)} m.`;
    update();
  }, () => {
    $("gpsNote").textContent = "No location available. Without internet, most Macs can't tell where they are: type your town or coordinates, or plug in a mesh radio that has GPS.";
  }, {timeout: 15000, enableHighAccuracy: true});
};
$("planTrip").onclick = () => {
  const overseas = route && route.walk_days == null;
  B.openPlan(to ? (overseas ? "leave-country" : "evacuate") : "get-home", {location: from?.label || "", destination: to?.label || ""});
};
$("saveMap").onclick = saveImage;
$("printMap").onclick = () => {
  map?.resize();
  $("mapTitle").textContent = [from?.label, to?.label].filter(Boolean).join(" to ") || "Map";
  B.printAs("map", "Map: " + ($("mapTitle").textContent));
};
window.BeaconMap = {init};
