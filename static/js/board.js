/* Board: check-ins, needs, offers and reports for everyone on this Beacon, the Meshtastic radio,
   and links to other Beacons on the same network so they share one Board. */
"use strict";
(() => {
const KIND = {checkin: "Check-in", need: "Need", offer: "Offer", report: "Report", note: "Note", mesh: "Mesh"};
let data = null, filter = "all", postKind = "need", timer = null, busy = false, meshSig = "", linksDrawn = false;
const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
};
const from = p => p.source === "mesh" ? ", by mesh radio" : p.source === "link" && p.via ? `, via ${esc(p.via)}` : "";

try { $("ciName").value = B.store.get("beacon-name") || ""; } catch {}
$("ciName").addEventListener("change", () => B.store.set("beacon-name", $("ciName").value.trim()));

B.tabHooks.board = () => refresh();
async function refresh() {
  clearTimeout(timer);
  try { data = await B.api("/api/board"); } catch (e) { $("posts").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  render();
  if (!B.sys?.guest) renderLinks();
  timer = setTimeout(() => { if (B.tab === "board") refresh(); }, 5000);
}

function render() {
  const host = !B.sys?.guest, roster = data.roster || [];
  const help = roster.filter(r => r.status === "help").length;
  $("rosterMeta").textContent = roster.length ? `${help ? `${help} need${help === 1 ? "s" : ""} help, ` : ""}${roster.length - help} safe` : "";
  $("roster").innerHTML = roster.length ? `<div class="roster">${roster.map(r => `<div><b>${esc(r.name)}</b>
      <span class="st is-${r.status}">${r.status === "help" ? "Needs help" : "Safe"}</span> <small>${esc(ago(r.t))}${from(r)}</small>
      ${r.text ? `<small>${esc(r.text)}</small>` : ""}</div>`).join("")}</div>`
    : '<p class="hint">No one has checked in yet. Tap We\'re safe or We need help to check in. People on the Wi-Fi, linked Beacons, and mesh radios that send SAFE or HELP with a name show up here.</p>';
  const posts = (data.posts || []).filter(p => p.kind !== "checkin" && (filter === "all" || p.kind === filter));
  $("posts").innerHTML = posts.length ? posts.map(p => `
    <article class="post ${p.resolved ? "resolved" : ""} ${p.pinned ? "pinned" : ""}">
      <div class="post-head"><span class="kind k-${p.kind}">${KIND[p.kind] || "Note"}</span>${p.name ? `<b>${esc(p.name)}</b>` : ""}
        <span class="when">${esc(ago(p.t))}${p.source === "mesh" ? `, from the mesh${p.channel ? ` (channel ${p.channel})` : ""}` : from(p)}${p.sent_mesh ? ", also sent over the mesh" : ""}${host && p.device && p.source !== "link" ? `, ${esc(p.device)}` : ""}</span>
        ${p.pinned ? '<span class="kind">Pinned</span>' : ""}${p.resolved ? '<span class="kind k-offer">Resolved</span>' : ""}</div>
      <p>${esc(p.text)}</p>
      <div class="post-actions">
        ${["need", "offer", "report"].includes(p.kind) ? `<button class="link" data-resolve="${esc(p.id)}">${p.resolved ? "Reopen" : "Mark resolved"}</button>` : ""}
        ${host ? `<button class="link" data-pin="${esc(p.id)}" data-on="${p.pinned ? 0 : 1}">${p.pinned ? "Unpin" : "Pin"}</button><button class="link" data-remove="${esc(p.id)}">Remove</button>` : ""}
      </div>
    </article>`).join("")
    : `<p class="hint" style="padding:12px 2px">${filter === "all" ? "Nothing posted yet." : "Nothing here yet."}</p>`;
  renderMesh();
}

/* ---------------------------------------------------------------- the mesh radio */
function renderMesh() {
  const m = data.mesh || {}, host = !B.sys?.guest;
  const canSend = m.state === "connected" && (host || m.allow_guests);
  $("meshSendWrap").hidden = !canSend;
  // Redraw only when something changed, so the address box and the radio list aren't wiped while in use.
  const sig = JSON.stringify([host, m.installed, m.state, m.error, m.me, m.target, m.nodes, m.allow_guests, m.auto, m.position]);
  if (sig === meshSig) return;
  meshSig = sig;
  if (!host && m.state !== "connected") { $("meshPanel").innerHTML = ""; return; }
  const auto = host ? `<div class="setting"><div><b>Connect automatically</b><span>When a radio is plugged into this Mac, Beacon connects to it.</span></div>
    <button class="switch" id="meshAuto" role="switch" aria-checked="${m.auto !== false}" aria-label="Connect automatically"></button></div>` : "";
  if (!m.installed) {
    $("meshPanel").innerHTML = `<div class="rail-box"><h3>${B.icon("radio")}Mesh radio</h3>
      <p class="hint">Connect a Meshtastic radio to pass messages and check-ins over the air, with no internet or cell service. This drive was built without Meshtastic support: run the drive builder again without --no-mesh, then plug the radio into this Mac.</p></div>`;
    return;
  }
  if (m.state === "connected") {
    const gps = m.position ? ` Its GPS puts it at ${m.position.lat.toFixed(4)}, ${m.position.lon.toFixed(4)}; the Map uses that as your location.` : "";
    $("meshPanel").innerHTML = `<div class="rail-box"><h3>${B.icon("radio")}Mesh radio connected</h3>
      <p class="hint">${esc(m.me || "Your radio")} on ${esc(m.target)}. ${m.nodes} radio${m.nodes === 1 ? "" : "s"} heard.${esc(gps)} Messages on the mesh appear in Posts; anyone can check in by sending SAFE or HELP and a name.</p>
      ${host ? `<div class="setting"><div><b>Guests can send over the mesh</b><span>Off means only this Mac can broadcast.</span></div><button class="switch" id="meshGuests" role="switch" aria-checked="${!!m.allow_guests}" aria-label="Guests can send over the mesh"></button></div>
      ${auto}<div class="row" style="margin-top:12px"><button class="btn small" id="meshNodes">Radios heard</button><button class="btn small ghost" id="meshOff">Disconnect</button></div>` : `<div class="row" style="margin-top:8px"><button class="btn small" id="meshNodes">Radios heard</button></div>`}
      <div id="meshNodeList"></div></div>`;
  } else {
    $("meshPanel").innerHTML = `<div class="rail-box"><h3>${B.icon("radio")}Mesh radio</h3>
      <p class="hint">${m.state === "connecting" ? "Connecting…" : "Plug a Meshtastic radio into this Mac with a data USB cable, or enter the address of one on your Wi-Fi."}</p>
      ${m.error ? `<p class="err">${esc(m.error)}</p>` : ""}
      <div class="row" style="margin-top:10px"><select id="meshPort" aria-label="Radio"><option value="">Find it automatically</option></select></div>
      <div class="row" style="margin-top:8px"><input id="meshHost" placeholder="Or a Wi-Fi radio's address, like 192.168.1.40" aria-label="Wi-Fi radio address" style="flex:1;min-width:12em"></div>
      <div class="row" style="margin-top:10px"><button class="btn small primary" id="meshOn" ${m.state === "connecting" ? "disabled" : ""}>Connect</button></div>
      ${auto}</div>`;
    B.api("/api/mesh").then(r => {
      const sel = $("meshPort");
      if (sel && r.ports) sel.innerHTML = '<option value="">Find it automatically</option>' + r.ports.map(p => `<option>${esc(p)}</option>`).join("");
    }).catch(() => {});
  }
}

$("meshPanel").addEventListener("click", async e => {
  const t = e.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "meshOn") { await B.api("/api/mesh/connect", {port: $("meshPort").value || null, host: $("meshHost").value.trim() || null}); setTimeout(refresh, 1500); refresh(); }
    if (t.id === "meshOff") { await B.api("/api/mesh/disconnect", {}); refresh(); }
    if (t.id === "meshGuests") { await B.api("/api/mesh/settings", {allow_guests: t.getAttribute("aria-checked") !== "true"}); refresh(); }
    if (t.id === "meshAuto") {
      const on = t.getAttribute("aria-checked") !== "true";
      await B.api("/api/mesh/settings", {auto: on});
      B.toast(on ? "Beacon connects to a radio as soon as it's plugged in" : "Connect the radio yourself with Connect");
      refresh();
    }
    if (t.id === "meshNodes") {
      const r = await B.api("/api/mesh");
      $("meshNodeList").innerHTML = r.nodes_list.length ? `<div class="rows" style="margin-top:12px">${r.nodes_list.map(n => `<div class="row-item"><div><div class="t">${esc(n.name)}${n.short ? ` (${esc(n.short)})` : ""}</div>
        <div class="d">${n.last_heard ? "Heard " + esc(ago(n.last_heard)) : "Not heard yet"}${n.snr != null ? `, signal ${esc(n.snr)} dB` : ""}${n.hops != null ? `, ${n.hops} hop${n.hops === 1 ? "" : "s"} away` : ""}${n.battery != null ? `, battery ${esc(n.battery)}%` : ""}${n.lat != null ? ", on the map" : ""}</div></div></div>`).join("")}</div>`
        : '<p class="hint">No other radios heard yet.</p>';
    }
  } catch (err) { B.toast(err.message); }
});

/* ---------------------------------------------------------------- linked Beacons (the Beacon computer only) */
async function renderLinks() {
  let v;
  try { v = await B.api("/api/links"); } catch { return; }
  if (!linksDrawn) {
    linksDrawn = true;
    $("linksPanel").innerHTML = `<div class="rail-box"><h3>${B.icon("link")}Linked Beacons</h3>
      <p class="hint">Another Beacon on this network can share this Board, so check-ins, needs and mesh messages reach everyone on either one. On the other Beacon, turn on Share to see its address and code.</p>
      <label class="field" for="linkName">This Beacon's name</label>
      <div class="row"><input id="linkName" maxlength="40" autocomplete="off" style="flex:1;min-width:9em"><button class="btn small" id="linkRename" type="button">Save</button></div>
      <div id="linkList"></div>
      <h3 class="group-label" style="margin-top:18px">Link to another Beacon</h3>
      <div class="row"><button class="btn small" id="linkFind" type="button">Find Beacons nearby</button></div>
      <div id="linkFound"></div>
      <label class="field" for="linkUrl">Its address</label><input id="linkUrl" autocomplete="off" placeholder="beacon-2.local or 192.168.1.20:8643">
      <label class="field" for="linkCode">Its code</label>
      <div class="row"><input id="linkCode" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="4 digits" style="width:7em;flex:none"><button class="btn small primary" id="linkAdd" type="button">Link</button></div></div>`;
    $("linkName").value = v.me?.name || "";
  }
  $("linkList").innerHTML = v.links.length ? `<div class="rows" style="margin-top:14px">${v.links.map(l => `<div class="row-item"><div>
      <div class="t">${esc(l.name)}</div>
      <div class="d">${esc(l.url.replace(/^https?:\/\//, ""))}. ${l.error ? `<span class="bad">${esc(l.error)}</span>` : l.last_ok ? `Synced ${esc(ago(l.last_ok))}: ${l.pulled} in, ${l.pushed} out.` : "Syncing…"}</div></div>
      <div class="act"><button class="btn small ghost" data-unlink="${esc(l.id)}">Unlink</button></div></div>`).join("")}</div>` : "";
}
$("linksPanel").addEventListener("click", async e => {
  const t = e.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "linkRename") {
      await B.api("/api/links/name", {name: $("linkName").value});
      B.toast("Renamed. Linked Beacons see the new name on their next sync.");
    }
    if (t.id === "linkFind") {
      t.disabled = true; t.textContent = "Looking…";
      let found = [];
      try { found = await B.api("/api/links/discover"); } finally { t.disabled = false; t.textContent = "Find Beacons nearby"; }
      $("linkFound").innerHTML = found.length ? `<div class="rows" style="margin-top:10px">${found.map(f => `<div class="row-item"><div><div class="t">${esc(f.name)}</div>
          <div class="d">${esc(f.url.replace(/^https?:\/\//, ""))}</div></div><div class="act"><button class="btn small" data-use="${esc(f.url)}">Use</button></div></div>`).join("")}</div>`
        : '<p class="hint" style="margin-top:8px">No other Beacons found. The other one needs Share turned on, on the same network. You can also type its address.</p>';
    }
    if (t.dataset.use) { $("linkUrl").value = t.dataset.use.replace(/^http:\/\//, ""); $("linkCode").focus(); }
    if (t.id === "linkAdd") {
      t.disabled = true;
      try {
        const l = await B.api("/api/links", {url: $("linkUrl").value, code: $("linkCode").value});
        $("linkUrl").value = $("linkCode").value = ""; $("linkFound").innerHTML = "";
        B.toast(`Linked to ${l.name}. Its posts appear here in a few seconds.`);
        setTimeout(refresh, 3000);
      } finally { t.disabled = false; }
    }
    if (t.dataset.unlink && confirm("Unlink this Beacon? Posts already shared stay on both Boards.")) {
      await B.api("/api/links/remove", {id: t.dataset.unlink});
      B.toast("Unlinked");
    }
    if (t.id !== "linkFind" && !t.dataset.use) renderLinks();
  } catch (err) { B.toast(err.message); }
});
$("linksPanel").addEventListener("keydown", e => { if (e.target.id === "linkCode" && e.key === "Enter") $("linkAdd").click(); });

/* ---------------------------------------------------------------- posting */
async function post(kind, extra = {}) {
  if (busy) return;
  busy = true;
  try {
    const p = await B.api("/api/board", {kind, mesh: $("meshSend").checked && !$("meshSendWrap").hidden, ...extra});
    B.toast(kind === "checkin" ? (p.status === "help" ? "Checked in as needing help. People here can see it." : "Checked in as safe") : "Posted");
    if (extra.text !== undefined && kind !== "checkin") $("postText").value = "";
    refresh();
  } catch (err) { B.toast(err.message); }
  busy = false;
}
$$("#tab-board [data-status]").forEach(b => b.addEventListener("click", () => {
  const name = $("ciName").value.trim();
  if (!name) { B.toast("Add your name or household first"); $("ciName").focus(); return; }
  B.store.set("beacon-name", name);
  post("checkin", {name, status: b.dataset.status, text: $("ciNote").value.trim()});
}));
$("postKind").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]");
  if (!b) return;
  postKind = b.dataset.v;
  $$("#postKind button").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
});
$("postBtn").addEventListener("click", () => {
  const text = $("postText").value.trim();
  if (!text) { $("postText").focus(); return; }
  post(postKind, {name: $("ciName").value.trim(), text});
});
$("boardFilter").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]");
  if (!b) return;
  filter = b.dataset.v;
  $$("#boardFilter button").forEach(x => x.classList.toggle("on", x === b));
  render();
});
$("posts").addEventListener("click", async e => {
  const r = e.target.closest("[data-resolve]"), p = e.target.closest("[data-pin]"), d = e.target.closest("[data-remove]");
  try {
    if (r) await B.api("/api/board/resolve", {id: r.dataset.resolve});
    if (p) await B.api("/api/board/pin", {id: p.dataset.pin, pinned: p.dataset.on === "1"});
    if (d && confirm("Remove this post for everyone?")) await B.api("/api/board/remove", {id: d.dataset.remove});
  } catch (err) { B.toast(err.message); }
  if (r || p || d) refresh();
});
$("printRoster").addEventListener("click", () => B.printAs("board", "Check-in roster"));
})();
