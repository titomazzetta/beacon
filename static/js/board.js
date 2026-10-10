/* Board: check-ins, needs, offers and reports for everyone on this Beacon, plus the Meshtastic radio. */
"use strict";
(() => {
const KIND = {checkin: "Check-in", need: "Need", offer: "Offer", report: "Report", note: "Note", mesh: "Mesh"};
let data = null, filter = "all", postKind = "need", timer = null, busy = false;
const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
};

try { $("ciName").value = B.store.get("beacon-name") || ""; } catch {}
$("ciName").addEventListener("change", () => B.store.set("beacon-name", $("ciName").value.trim()));

B.tabHooks.board = () => refresh();
async function refresh() {
  clearTimeout(timer);
  try { data = await B.api("/api/board"); } catch (e) { $("posts").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  render();
  timer = setTimeout(() => { if (B.tab === "board") refresh(); }, 5000);
}

function render() {
  const host = !B.sys?.guest, roster = data.roster || [];
  const help = roster.filter(r => r.status === "help").length;
  $("rosterMeta").textContent = roster.length ? `${help ? `${help} need${help === 1 ? "s" : ""} help, ` : ""}${roster.length - help} safe` : "";
  $("roster").innerHTML = roster.length ? `<div class="roster">${roster.map(r => `<div><b>${esc(r.name)}</b>
      <span class="st is-${r.status}">${r.status === "help" ? "Needs help" : "Safe"}</span> <small>${esc(ago(r.t))}${r.source === "mesh" ? ", by mesh radio" : ""}</small>
      ${r.text ? `<small>${esc(r.text)}</small>` : ""}</div>`).join("")}</div>`
    : '<p class="hint">No one has checked in yet. Check in on the left; neighbors on the Wi-Fi (or on the mesh, by sending SAFE or HELP and a name) show up here.</p>';
  const posts = (data.posts || []).filter(p => p.kind !== "checkin" && (filter === "all" || p.kind === filter));
  $("posts").innerHTML = posts.length ? posts.map(p => `
    <article class="post ${p.resolved ? "resolved" : ""} ${p.pinned ? "pinned" : ""}">
      <div class="post-head"><span class="kind k-${p.kind}">${KIND[p.kind] || "Note"}</span>${p.name ? `<b>${esc(p.name)}</b>` : ""}
        <span class="when">${esc(ago(p.t))}${p.source === "mesh" ? `, from the mesh${p.channel ? ` (channel ${p.channel})` : ""}` : ""}${p.sent_mesh ? ", also sent over the mesh" : ""}${host && p.device ? `, ${esc(p.device)}` : ""}</span>
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

function renderMesh() {
  const m = data.mesh || {}, host = !B.sys?.guest;
  const canSend = m.state === "connected" && (host || m.allow_guests);
  $("meshSendWrap").hidden = !canSend;
  if (!host && m.state !== "connected") { $("meshPanel").innerHTML = ""; return; }
  if (!m.installed) {
    $("meshPanel").innerHTML = `<div class="mesh-box"><h3>${B.icon("radio")}Meshtastic radio</h3>
      <p class="hint">Connect a Meshtastic radio to pass messages and check-ins over the air, with no internet or cell service. Add Meshtastic support when you build the drive (see START-HERE), then plug the radio into this Mac.</p></div>`;
    return;
  }
  if (m.state === "connected") {
    $("meshPanel").innerHTML = `<div class="mesh-box"><h3>${B.icon("radio")}Mesh radio connected</h3>
      <p class="hint">${esc(m.me || "Your radio")} on ${esc(m.target)}. ${m.nodes} radio${m.nodes === 1 ? "" : "s"} heard. Messages on the mesh appear in Posts; anyone can check in by sending SAFE or HELP and a name.</p>
      ${host ? `<div class="setting"><div><b>Guests can send over the mesh</b><span>Off means only this Mac can broadcast.</span></div><button class="switch" id="meshGuests" role="switch" aria-checked="${!!m.allow_guests}" aria-label="Guests can send over the mesh"></button></div>
      <div class="row" style="margin-top:12px"><button class="btn small" id="meshNodes">Radios heard</button><button class="btn small ghost" id="meshOff">Disconnect</button></div>` : `<div class="row" style="margin-top:8px"><button class="btn small" id="meshNodes">Radios heard</button></div>`}
      <div id="meshNodeList"></div></div>`;
  } else {
    $("meshPanel").innerHTML = `<div class="mesh-box"><h3>${B.icon("radio")}Meshtastic radio</h3>
      <p class="hint">${m.state === "connecting" ? "Connecting…" : "Plug a Meshtastic radio into this Mac with a data USB cable, or enter the address of one on your Wi-Fi."}</p>
      ${m.error ? `<p class="err">${esc(m.error)}</p>` : ""}
      <div class="row" style="margin-top:10px"><select id="meshPort"><option value="">Find it automatically</option></select></div>
      <div class="row" style="margin-top:8px"><input id="meshHost" placeholder="Or a Wi-Fi radio's address, like 192.168.1.40" style="flex:1;min-width:12em"></div>
      <div class="row" style="margin-top:10px"><button class="btn small primary" id="meshOn" ${m.state === "connecting" ? "disabled" : ""}>Connect</button></div></div>`;
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
    if (t.id === "meshNodes") {
      const r = await B.api("/api/mesh");
      $("meshNodeList").innerHTML = r.nodes_list.length ? `<div class="rows" style="margin-top:12px">${r.nodes_list.map(n => `<div class="row-item"><div><div class="t">${esc(n.name)}${n.short ? ` (${esc(n.short)})` : ""}</div>
        <div class="d">${n.last_heard ? "Heard " + esc(ago(n.last_heard)) : "Not heard yet"}${n.snr != null ? `, signal ${esc(n.snr)} dB` : ""}${n.hops != null ? `, ${n.hops} hop${n.hops === 1 ? "" : "s"} away` : ""}${n.battery != null ? `, battery ${esc(n.battery)}%` : ""}${n.lat != null ? ", on the map" : ""}</div></div></div>`).join("")}</div>`
        : '<p class="hint">No other radios heard yet.</p>';
    }
  } catch (err) { B.toast(err.message); }
});

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
