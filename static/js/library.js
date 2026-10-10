/* Library: what's on the drive, downloads, the brain, maps, reading and paper backups. */
"use strict";
(() => {
const TIER_ORDER = ["core", "extended", "complete", "everything"];
let lib = null, status = null, books = null, sizes = {}, chosenTier = null, timer = null;
const selected = new Set();

/* ---------------------------------------------------------------- section index */
function buildIndex() {
  const secs = $$("#libPane > section").filter(s => getComputedStyle(s).display !== "none");
  $("libIndex").innerHTML = secs.map(s => `<a href="#${s.id}" data-sec="${s.id}">${esc(s.querySelector("h2").textContent)}</a>`).join("");
}
$("libIndex").addEventListener("click", e => {
  const a = e.target.closest("a[data-sec]");
  if (!a) return;
  e.preventDefault();
  $(a.dataset.sec).scrollIntoView({block: "start", behavior: "smooth"});
});
/* Highlight the section whose heading has passed a line near the top of the pane (the last one
   once the pane is scrolled to the end). Works the same whichever element does the scrolling. */
let spyQueued = false;
function spy() {
  spyQueued = false;
  if (B.tab !== "library") return;
  const secs = $$("#libPane > section").filter(s => getComputedStyle(s).display !== "none");
  if (!secs.length) return;
  const pane = $("libPane"), line = innerHeight * 0.22;
  const atEnd = pane.scrollHeight > pane.clientHeight
    ? pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 4
    : innerHeight + scrollY >= document.documentElement.scrollHeight - 4;
  let cur = secs[0].id;
  for (const s of secs) if (s.getBoundingClientRect().top <= line) cur = s.id;
  if (atEnd) cur = secs[secs.length - 1].id;
  $$("#libIndex a").forEach(a => a.classList.toggle("on", a.dataset.sec === cur));
}
const queueSpy = () => { if (!spyQueued) { spyQueued = true; requestAnimationFrame(spy); } };
document.addEventListener("scroll", queueSpy, {capture: true, passive: true});
addEventListener("resize", queueSpy);

/* ---------------------------------------------------------------- loading */
B.tabHooks.library = () => { buildIndex(); refresh(); queueSpy(); };
async function refresh() {
  clearTimeout(timer);
  const guest = !!B.sys?.guest;
  try {
    [lib, status] = await Promise.all([B.api("/api/library"), B.api("/api/status")]);
  } catch (e) {
    $("docs").innerHTML = `<p class="err">${esc(e.message)}</p>`;
    return;
  }
  lib.bands.forEach(b => b.items.forEach(i => { if (i.size) sizes[i.id] = i.size; }));
  if (!guest) {
    if (!B.sys || Date.now() - (B.sysAt || 0) > 8000) { await B.loadSystem(); B.sysAt = Date.now(); }
    renderInstall(); renderBrain(); renderMaps(); renderBands(); renderJobs(); renderCheckButton();
  }
  renderDocs(); renderPaper(); renderBuy(); renderSavedList();
  if (!books) { try { books = await B.api("/api/books"); } catch { books = []; } }
  renderShelf();
  buildIndex(); queueSpy();
  const busy = lib.jobs.some(j => ["queued", "downloading"].includes(j.state)) || status.ingest.running;
  timer = setTimeout(() => { if (B.tab === "library") refresh(); }, busy ? 2500 : 15000);
}
B.refreshLibrary = refresh;

/* ---------------------------------------------------------------- install levels */
function tierSet(tier) {
  const out = [], groups = {};
  lib.bands.forEach(b => b.items.forEach(i => {
    if (i.type === "link" || i.optional || TIER_ORDER.indexOf(i.tier) > TIER_ORDER.indexOf(tier)) return;
    if (i.group) {
      const prev = groups[i.group];
      if (!prev || TIER_ORDER.indexOf(i.tier) >= TIER_ORDER.indexOf(prev.tier)) {
        if (prev) out.splice(out.indexOf(prev), 1);
        groups[i.group] = i; out.push(i);
      }
    } else out.push(i);
  }));
  return out;
}
function renderInstall() {
  $("libMeta").textContent = `${lib.free_gb} GB free on the drive, ${lib.online ? "online" : "offline"}`;
  let prevIds = new Set();
  const tiers = lib.tiers.map(t => {
    const all = tierSet(t.id), own = all.filter(i => !prevIds.has(i.id));
    prevIds = new Set(all.map(i => i.id));
    const missing = all.filter(i => !i.installed);
    const known = missing.reduce((a, i) => a + (sizes[i.id] > 0 ? sizes[i.id] : 0), 0);
    const unknown = missing.filter(i => i.type === "zim" && !(sizes[i.id] > 0)).length;
    return {...t, all, own, missing, known, unknown, ownDone: own.filter(i => i.installed).length};
  });
  if (!chosenTier || !tiers.find(t => t.id === chosenTier)) chosenTier = (tiers.find(t => t.missing.length) || tiers[0]).id;
  $("gauge").innerHTML = tiers.map(t => {
    const pct = t.own.length ? Math.round(100 * t.ownDone / t.own.length) : 100;
    return `<button class="${t.id === chosenTier ? "on" : ""}" data-tier="${t.id}" aria-pressed="${t.id === chosenTier}">
      <div class="gbar"><i style="width:${pct}%"></i></div><div class="glabel">${esc(t.title)}<span>${t.ownDone}/${t.own.length}</span></div></button>`;
  }).join("");
  const t = tiers.find(x => x.id === chosenTier);
  const size = t.missing.length ? (t.known ? `about ${fmtBytes(t.known)}${t.unknown ? " plus a few items of unknown size" : ""} to download` : (t.unknown ? "sizes not checked yet" : "")) : "";
  $("tierDetail").innerHTML = `<div class="tier-detail"><div class="td-text"><h3>${esc(t.title)}</h3><p>${esc(t.about)}</p>
      <p>${t.all.length - t.missing.length} of ${t.all.length} installed${size ? ", " + size : ""}.</p></div>
    <div class="row">${t.missing.length && t.unknown && lib.online ? `<button class="btn ghost" id="sizesBtn">Check sizes</button>` : ""}
      <button class="btn ${t.missing.length ? "primary" : ""}" id="tierGo" ${!lib.online || !t.missing.length ? "disabled" : ""}>${t.missing.length ? "Download " + esc(t.title) : "All installed"}</button></div></div>
    ${!lib.online && t.missing.length ? '<p class="hint" style="margin-top:10px">Connect this Mac to the internet to download. Everything installed keeps working offline.</p>' : ""}`;
}
$("gauge").addEventListener("click", e => { const b = e.target.closest("[data-tier]"); if (b) { chosenTier = b.dataset.tier; renderInstall(); } });
$("tierDetail").addEventListener("click", async e => {
  if (e.target.closest("#tierGo")) {
    e.target.closest("#tierGo").disabled = true;
    try {
      const r = await B.api("/api/library/download", {tier: chosenTier});
      B.toast(r.queued ? `Downloading ${r.queued} item${r.queued === 1 ? "" : "s"}` : "Nothing new to download");
      if (r.errors.length) alert(r.errors.join("\n"));
    } catch (err) { B.toast(err.message); }
    refresh();
  }
  if (e.target.closest("#sizesBtn")) {
    const b = e.target.closest("#sizesBtn");
    b.disabled = true; b.textContent = "Checking…";
    try { const r = await B.api("/api/library/sizes", {}); if (r.sizes) Object.assign(sizes, r.sizes); } catch (err) { B.toast(err.message); }
    refresh();
  }
});

/* ---------------------------------------------------------------- brain */
function jobFor(id) { return lib.jobs.find(j => j.id === id); }
function jobState(j) {
  if (!j) return "";
  if (j.state === "downloading") {
    const pct = j.total ? Math.round(100 * j.done / j.total) : null;
    return `<span class="state">${pct != null ? pct + "%" : "Working"}</span>`;
  }
  if (j.state === "queued") return '<span class="state">Waiting</span>';
  if (j.state === "failed") return `<span class="state bad" title="${esc(j.error)}">Failed</span>`;
  return "";
}
function renderBrain() {
  const s = B.sys;
  if (!s) return;
  $("brainMeta").textContent = s.active_model ? `Using ${s.active_model}` : "No brain installed yet";
  $("brainRows").innerHTML = s.tiers.map(t => {
    const j = jobFor("model-" + t.model), busy = j && ["queued", "downloading"].includes(j.state);
    const rec = t.model === s.recommended.model;
    const act = t.installed ? `<span class="state ok">Installed</span>`
      : busy ? jobState(j) : `${j?.state === "failed" ? jobState(j) : ""}<button class="btn small" data-pull="${esc(t.model)}" ${lib.online ? "" : "disabled"}>Download</button>`;
    return `<div class="row-item"><div><div class="t">${esc(t.model)}${rec ? ' <span class="tag" style="color:var(--signal);border-color:var(--signal)">Best for this Mac</span>' : ""}</div>
      <div class="d">${esc(t.label)}, ${t.size_gb} GB. ${t.fits ? "Runs on this computer." : `Needs ${t.min_ram_gb} GB of memory; keep it for a bigger Mac.`}</div>
      ${busy && j.total ? `<div class="pbar"><i style="width:${Math.round(100 * j.done / j.total)}%"></i></div>` : ""}</div>
      <div class="act">${act}</div></div>`;
  }).join("");
  const inst = s.tiers.filter(t => t.installed);
  $("modelSel").innerHTML = `<option value="">Automatic (${esc(s.active_model || "none")})</option>` + inst.map(t => `<option ${s.chosen === t.model ? "selected" : ""}>${esc(t.model)}</option>`).join("");
}
$("brainRows").addEventListener("click", async e => {
  const b = e.target.closest("[data-pull]");
  if (!b) return;
  b.disabled = true;
  try { await B.api("/api/models/pull", {model: b.dataset.pull}); B.toast("Downloading " + b.dataset.pull); } catch (err) { B.toast(err.message); }
  refresh();
});
$("modelSel").addEventListener("change", async e => {
  try { await B.api("/api/model", {model: e.target.value}); } catch (err) { B.toast(err.message); }
  await B.loadSystem(); renderBrain();
});

/* ---------------------------------------------------------------- maps */
let regionPick = null;
function renderMaps() {
  const world = lib.maps.find(m => m.kind === "world"), regions = lib.maps.filter(m => m.kind === "region");
  const jp = jobFor("map-places"), jw = jobFor("map-world");
  const busy = j => j && ["queued", "downloading"].includes(j.state);
  const keepRegion = $("regIn") ? {v: $("regIn").value, r: $("regRad").value, focus: document.activeElement?.id} : null;
  $("mapRows").innerHTML = `
    <div class="row-item"><div><div class="t">Place names</div><div class="d">Every town of 5,000 people or more, worldwide, for searching and for "where am I". About 10 MB.</div></div>
      <div class="act">${lib.places ? '<span class="state ok">Installed</span>' : busy(jp) ? jobState(jp) : `${jobState(jp)}<button class="btn small" data-map="places" ${lib.online ? "" : "disabled"}>Download</button>`}</div></div>
    <div class="row-item"><div><div class="t">World map</div><div class="d">Countries, coastlines, main roads and cities.${world ? " " + fmtBytes(world.size_mb * 1024 ** 2) + "." : ""}</div></div>
      <div class="act">${world ? '<span class="state ok">Installed</span>' : busy(jw) ? jobState(jw) : `${jobState(jw)}<button class="btn small" data-map="world" ${lib.online ? "" : "disabled"}>Build</button>`}</div></div>
    <div class="row-item" style="grid-template-columns:1fr"><div><div class="t">Detailed region</div><div class="d">Every street, trail and building around a place. 300 km across is usually a few GB.${regions.length ? " Installed: " + regions.map(m => esc(m.file.replace(/^region-|\.pmtiles$/g, "").replace(/-/g, " ")) + " (" + fmtBytes(m.size_mb * 1024 ** 2) + ")").join(", ") + "." : ""}</div>
      <div class="row" style="margin-top:10px"><div class="sugg" style="flex:1;min-width:12em"><input type="search" id="regIn" autocomplete="off" placeholder="Center it on a town"><ul id="regSug" hidden></ul></div>
        <select id="regRad"><option value="100">100 km</option><option value="300" selected>300 km</option><option value="600">600 km</option><option value="1000">1,000 km</option></select>
        <button class="btn small" id="regGo" ${lib.online ? "" : "disabled"}>Build</button></div>
      ${lib.jobs.filter(j => j.id.startsWith("map-region-") && busy(j)).map(j => `<p class="hint" style="margin-top:8px">${esc(j.title)}: ${j.total ? Math.round(100 * j.done / j.total) + "%" : "working"}${j.detail ? ", " + esc(j.detail) : ""}</p>`).join("")}</div></div>`;
  if (keepRegion) { $("regIn").value = keepRegion.v; $("regRad").value = keepRegion.r; if (keepRegion.focus === "regIn") $("regIn").focus(); }
  B.wireSuggest($("regIn"), $("regSug"), p => { regionPick = p; });
}
$("mapRows").addEventListener("click", async e => {
  const b = e.target.closest("[data-map]");
  if (b) {
    b.disabled = true;
    try { await B.api("/api/maps/build", {kind: b.dataset.map}); } catch (err) { B.toast(err.message); }
    return refresh();
  }
  if (e.target.closest("#regGo")) {
    if (!regionPick) { B.toast("Pick a town from the list first"); return; }
    try {
      await B.api("/api/maps/build", {kind: "region", label: regionPick.label.split(",")[0], lat: regionPick.lat, lon: regionPick.lon, radius: +$("regRad").value});
      B.toast("Building the map for " + regionPick.label.split(",")[0]);
    } catch (err) { B.toast(err.message); }
    refresh();
  }
});

/* ---------------------------------------------------------------- topics */
function itemRow(i) {
  if (i.type === "link") {
    return `<div class="item">${B.icon("external")}<div><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a><small>${esc(i.note || "Opens the publisher's site")}</small></div><span class="tag">link</span></div>`;
  }
  const j = i.job;
  const pct = j && j.total ? Math.round(100 * j.done / j.total) : null;
  let state;
  if (i.installed) state = '<span class="state ok">Installed</span>';
  else if (j && j.state === "downloading") state = `<span class="state">${pct != null ? pct + "%" : "Working"}</span>`;
  else if (j && j.state === "queued") state = '<span class="state">Waiting</span>';
  else if (j && j.state === "failed") state = `<span class="state bad" title="${esc(j.error)}">Failed</span>`;
  else state = `<span class="state">${sizes[i.id] > 0 ? fmtBytes(sizes[i.id]) : sizes[i.id] === -1 ? "Not found" : ""}</span>`;
  const kind = {zim: "Library", pdf: "PDF", text: "Text", page: "Web page"}[i.type] || i.type;
  return `<div class="item"><input type="checkbox" data-id="${esc(i.id)}" aria-label="${esc(i.title)}" ${i.installed ? "checked disabled" : selected.has(i.id) ? "checked" : ""} ${!lib.online && !i.installed ? "disabled" : ""}>
    <div>${esc(i.title)}<span class="tag">${esc(i.tier)}</span><small>${esc(kind)}${i.license ? ", " + esc(i.license) : ""}${i.note ? ". " + esc(i.note) : ""}</small>
      ${j && j.state === "downloading" && pct != null ? `<div class="pbar"><i style="width:${pct}%"></i></div>` : ""}${j && j.state === "failed" ? `<small class="bad">${esc(j.error)}</small>` : ""}</div>${state}</div>`;
}
function renderBands() {
  const open = new Set($$("details.band[open]").map(d => d.dataset.id));
  let have = 0, total = 0;
  $("bands").innerHTML = `<div class="rows">${lib.bands.map(b => {
    const real = b.items.filter(i => i.type !== "link"), n = real.filter(i => i.installed).length;
    have += n; total += real.length;
    return `<details class="band" data-id="${esc(b.id)}" ${open.has(b.id) ? "open" : ""}><summary><b>${esc(b.title)}</b><span class="state ${n === real.length && real.length ? "ok" : ""}">${n} of ${real.length}</span></summary>${b.items.map(itemRow).join("")}</details>`;
  }).join("")}</div>`;
  $("topicMeta").textContent = `${have} of ${total} installed`;
  updateSel();
}
function updateSel() {
  $("selInfo").textContent = selected.size ? `${selected.size} selected` : lib.online ? "Tick the items you want." : "Offline: connect to download.";
  $("dlSel").disabled = !selected.size || !lib.online;
}
$("bands").addEventListener("change", e => {
  const c = e.target;
  if (!c.dataset.id) return;
  if (c.checked) selected.add(c.dataset.id); else selected.delete(c.dataset.id);
  updateSel();
});
$("dlSel").addEventListener("click", async () => {
  if (!selected.size) return;
  try {
    const r = await B.api("/api/library/download", {ids: [...selected]});
    selected.clear();
    B.toast(`Downloading ${r.queued} item${r.queued === 1 ? "" : "s"}`);
    if (r.errors.length) alert(r.errors.join("\n"));
  } catch (err) { B.toast(err.message); }
  refresh();
});
$("kgo").addEventListener("click", kiwixSearch);
$("kq").addEventListener("keydown", e => { if (e.key === "Enter") kiwixSearch(); });
async function kiwixSearch() {
  const q = $("kq").value.trim();
  if (!q) return;
  $("kres").innerHTML = '<p class="hint">Searching the Kiwix catalog…</p>';
  let r = [];
  try { r = await B.api("/api/library/search?q=" + encodeURIComponent(q)); } catch {}
  $("kres").innerHTML = r.length ? r.map((e, i) => `<div class="row-item"><div><div class="t">${esc(e.title)}</div><div class="d">${esc(e.summary)}${e.flavour ? ` (${esc(e.flavour)})` : ""}</div></div>
      <div class="act"><span class="state">${fmtBytes(e.size)}</span><button class="btn small" data-k="${i}">Add</button></div></div>`).join("")
    : `<p class="hint">${lib?.online ? "Nothing found. Try a simpler word." : "Searching the catalog needs internet."}</p>`;
  $("kres").onclick = async ev => {
    const b = ev.target.closest("[data-k]");
    if (!b) return;
    b.disabled = true;
    try { await B.api("/api/library/add_zim", r[b.dataset.k]); B.toast("Downloading " + r[b.dataset.k].title); } catch (err) { B.toast(err.message); }
    refresh();
  };
}

/* ---------------------------------------------------------------- downloads */
function renderJobs() {
  const jobs = lib.jobs.slice().reverse();
  $("jobs").innerHTML = jobs.length ? jobs.map(j => {
    const pct = j.total ? Math.round(100 * j.done / j.total) : null;
    const live = ["queued", "downloading"].includes(j.state);
    const state = {queued: "Waiting", downloading: pct != null ? `${pct}% of ${fmtBytes(j.total)}` : "Working", done: "Done", failed: "Failed", cancelled: "Cancelled"}[j.state] || j.state;
    return `<div class="row-item"><div><div class="t">${esc(j.title)}</div><div class="d ${j.state === "failed" ? "bad" : ""}">${esc(j.error || j.detail || "")}</div>
      ${j.state === "downloading" && pct != null ? `<div class="pbar"><i style="width:${pct}%"></i></div>` : ""}</div>
      <div class="act"><span class="state ${j.state === "done" ? "ok" : j.state === "failed" ? "bad" : ""}">${esc(state)}</span>${live ? `<button class="btn small ghost" data-cancel="${esc(j.id)}">Cancel</button>` : ""}</div></div>`;
  }).join("") : '<p class="hint" style="padding:12px 2px">Nothing downloading. Downloads keep going while you use the rest of Beacon.</p>';
}
$("jobs").addEventListener("click", async e => {
  const b = e.target.closest("[data-cancel]");
  if (!b) return;
  try { await B.api("/api/library/cancel", {id: b.dataset.cancel}); } catch {}
  refresh();
});

/* ---------------------------------------------------------------- manuals and guides */
function docTitle(path) {
  const name = path.split("/").pop().replace(/\.(pdf|txt|md)$/i, "");
  return name.replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
}
function renderDocs() {
  const bandTitle = Object.fromEntries((lib?.bands || []).map(b => [b.id, b.title]));
  const bookTitle = Object.fromEntries((status.books || []).map(b => [b.id, b.title]));
  const groups = {};
  for (const m of status.manuals) {
    let g, read, save;
    if (m.path.startsWith("zim:")) {
      const [book, ...rest] = m.path.slice(4).split("/");
      g = bookTitle[book] || book.replace(/_/g, " ");
      read = "/read/kiwix/" + enc(book + "/" + rest.join("/"));
      save = null;
    } else {
      const top = m.path.includes("/") ? m.path.split("/")[0] : "";
      g = top === "cards" ? "Quick cards" : bandTitle[top] || (top ? top.replace(/-/g, " ") : "Your own files");
      read = "/read/manual/" + enc(m.path);
      save = read + "?download=1";
    }
    (groups[g] = groups[g] || []).push({...m, read, save});
  }
  const names = Object.keys(groups).sort((a, b) => (a === "Quick cards" ? -1 : b === "Quick cards" ? 1 : a.localeCompare(b)));
  const count = status.manuals.length;
  $("docMeta").textContent = count ? `${count.toLocaleString()} searchable` : "";
  $("docs").innerHTML = count ? names.map(g => `<h3 class="group-label">${esc(g)}</h3><div class="rows">${groups[g].map(m => `
    <div class="row-item"><div><div class="t">${esc(m.title || docTitle(m.path))}</div>
      <div class="d">${m.chunks ? m.chunks.toLocaleString() + " passages" : "No readable text"}${m.pages > 1 ? `, ${m.pages} pages` : ""}${m.scanned ? ". Mostly scanned images, so only part is searchable" : ""}</div></div>
      <div class="act"><a href="${esc(m.read)}" target="_blank" rel="noopener">Read</a>${m.save ? `<a href="${esc(m.save)}" download>Save</a>` : ""}</div></div>`).join("")}</div>`).join("")
    : `<p class="hint">No manuals yet.${B.sys?.guest ? "" : " Download a level above, or add your own files."}</p>`;
  if (!B.sys?.guest) {
    const pend = status.pending.length;
    $("ingestLog").textContent = status.ingest.running ? (status.ingest.log.at(-1) || "Indexing…") : pend ? `${pend} file${pend === 1 ? "" : "s"} waiting to be indexed.` : (status.ingest.log.at(-1) || "");
    $("ingestBtn").disabled = status.ingest.running;
  }
}
$("ingestBtn").addEventListener("click", async () => {
  try { await B.api("/api/ingest", {}); } catch (err) { B.toast(err.message); }
  setTimeout(refresh, 400);
});

/* ---------------------------------------------------------------- health check */
function renderCheckButton() { /* the button state is handled by the check itself */ }
function renderCheck(rep) {
  const groups = {brain: "The AI", manual: "Manuals and PDFs", library: "Offline libraries", security: "Security"};
  $("checkOut").innerHTML = `<div class="check-sum"><span class="dot ${rep.passed === rep.total ? "ok" : "warn"}"></span>${rep.passed} of ${rep.total} checks passed<span class="hint" style="margin-left:auto">${rep.seconds} seconds</span></div>`
    + Object.entries(groups).map(([k, title]) => {
      const rs = rep.results.filter(r => r.kind === k);
      return rs.length ? `<h3 class="group-label">${title}</h3><div class="rows">${rs.map(r => `<div class="row-item"><div><div class="t">${esc(r.name)}</div><div class="d">${esc(r.detail)}</div></div>
        <div class="act"><span class="state ${r.ok ? (r.warn ? "warn" : "ok") : "bad"}">${r.ok ? (r.warn ? "Warning" : "Passed") : "Problem"}</span></div></div>`).join("")}</div>` : "";
    }).join("");
  queueSpy();
}
$("runCheck").addEventListener("click", async () => {
  $("runCheck").disabled = true;
  $("checkOut").innerHTML = `<div style="margin-top:16px">${B.thinking("Searching every manual and library")}</div>`;
  try { await B.api("/api/check", {}); } catch (err) { B.toast(err.message); $("runCheck").disabled = false; return; }
  const poll = async () => {
    let c;
    try { c = await B.api("/api/check"); } catch { c = {running: false}; }
    if (c.running) return setTimeout(poll, 900);
    $("runCheck").disabled = false;
    if (c.report) renderCheck(c.report);
  };
  poll();
});

/* ---------------------------------------------------------------- saved plans and answers */
async function renderSavedList() {
  let items = [];
  try { items = await B.api("/api/archive"); } catch {}
  const host = !B.sys?.guest;
  $("savedMeta").textContent = items.length ? `${items.length} item${items.length === 1 ? "" : "s"}` : "";
  $("savedList").innerHTML = items.length ? `<div class="rows">${items.map(i => `
    <div class="row-item"><div><div class="t">${esc(i.title)}</div>
      <div class="d">${i.kind === "plan" ? "Plan" : "Answer"}, ${esc(new Date(i.created * 1000).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}))}${i.meta?.location ? ", " + esc(i.meta.location) : ""}.
        ${i.shared ? (i.by === "guest" ? `Shared from ${esc(i.device || "a guest")}.` : "Shared with everyone.") : "Only on this Mac."}</div></div>
      <div class="act"><button class="link" data-open="${esc(i.id)}">Open</button><a href="/archive/${esc(i.id)}.pdf" download>PDF</a>${host ? `<button class="link" data-del="${esc(i.id)}">Delete</button>` : ""}</div></div>`).join("")}</div>`
    : `<p class="hint">${host ? "Nothing saved yet. Plans you make are saved here automatically." : "Nothing has been shared yet."}</p>`;
}
B.onArchiveChange = () => { renderSavedList(); B.renderSavedPlans?.(); };
$("savedList").addEventListener("click", async e => {
  const o = e.target.closest("[data-open]"), d = e.target.closest("[data-del]");
  if (o) B.viewArchive(o.dataset.open);
  if (d && confirm("Delete this from the drive?")) {
    try { await B.api(`/api/archive/${d.dataset.del}/delete`, {}); } catch {}
    B.onArchiveChange();
  }
});

/* ---------------------------------------------------------------- reading shelf, paper, books to buy */
function renderShelf() {
  if (!books.length) {
    $("shelf").innerHTML = `<p class="hint">No books yet.${B.sys?.guest ? "" : " Download the Reading Shelf in Topics."}</p>`;
    return;
  }
  const bandTitle = Object.fromEntries((lib?.bands || []).map(b => [b.id, b.title.replace(/^Reading Shelf: /, "")]));
  const groups = {};
  books.forEach(b => (groups[bandTitle[b.band] || b.band] = groups[bandTitle[b.band] || b.band] || []).push(b));
  $("shelf").innerHTML = Object.entries(groups).map(([g, list]) => `<h3 class="group-label">${esc(g)}</h3><div class="rows">${list.map(b => `
    <div class="row-item"><div><div class="t">${esc(b.title)}</div><div class="d">${b.size_kb >= 1024 ? (b.size_kb / 1024).toFixed(1) + " MB" : b.size_kb + " KB"} of text</div></div>
      <div class="act"><a href="/read/book/${enc(b.path)}" target="_blank" rel="noopener">Read</a><a href="/read/book/${enc(b.path)}?download=1" download>Save</a></div></div>`).join("")}</div>`).join("");
}
function renderPaper() {
  const guest = !!B.sys?.guest;
  $("paperRows").innerHTML = `
    <div class="row-item"><div><div class="t">The binder</div><div class="d">Every quick card and the cliff notes${guest ? "" : ", with your household info first"}. Open it and print, or save it as a PDF from the print window.</div></div>
      <div class="act"><a href="/binder" target="_blank" rel="noopener">Open to print</a><a href="/binder?download=1" download>Save</a></div></div>
    <div class="row-item"><div><div class="t">All quick cards</div><div class="d">One small zip file of plain-text cards plus the start guide. Opens on any phone or computer.</div></div>
      <div class="act"><a href="/download/cards.zip" download>Save</a></div></div>
    <div class="row-item"><div><div class="t">Cliff notes</div><div class="d">The essentials on a few pages of plain text.</div></div>
      <div class="act"><a href="/read/manual/cards/BEACON-CLIFFNOTES.txt" target="_blank" rel="noopener">Read</a><a href="/read/manual/cards/BEACON-CLIFFNOTES.txt?download=1" download>Save</a></div></div>`;
}
function renderGear() {
  const g = lib?.gear_list || {};
  $("gearAbout").textContent = g._about || "";
  $("gearList").innerHTML = (g.groups || []).map(grp => `<h3 class="group-label">${esc(grp.title)}</h3><div class="rows">${grp.items.map(it => `
    <div class="row-item" style="grid-template-columns:1fr"><div><div class="t">${esc(it.what)}</div><div class="d">${esc(it.why)}${it.examples ? ` <i>Examples: ${esc(it.examples)}.</i>` : ""}</div></div></div>`).join("")}</div>`).join("");
}
function renderBuy() {
  renderGear();
  const bl = lib?.buy_list || {};
  $("buyAbout").textContent = bl._about || "";
  $("buyList").innerHTML = (bl.books || []).map(b => `<li>${esc(b)}</li>`).join("");
}
})();
