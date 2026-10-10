/* Plan: pick a situation, fill in what you know, get a printable plan built from the library. */
"use strict";
(() => {
const PLAN_ICONS = {
  "evacuate": "car", "leave-country": "globe", "shelter-in-place": "house", "winter-storm": "snow", "tornado": "tornado",
  "heat-wave": "sun", "flood-hurricane": "waves", "get-home": "route", "food-30": "can", "garden": "sprout",
  "wilderness": "tent", "perimeter": "shield", "evade": "eyeoff", "mind-body": "mind", "community": "board", "power": "power",
};
const WIDE = new Set(["people", "resources", "documents", "group", "needs"]);
const HOUSEHOLD = [
  ["home", "Home address or area", "Street, city, state. Plans and maps start here."],
  ["people", "People in the household", "Names, ages, special needs, pets"],
  ["medical", "Medical conditions, medications and allergies", "Who takes what, doses, allergies, blood types"],
  ["contacts", "Emergency contacts and phone numbers", "Family, doctor, neighbors, work"],
  ["meeting", "Meeting places", "Right outside, in the neighborhood, out of town"],
  ["outside_contact", "Out-of-area contact", "Someone far away everyone checks in with"],
  ["vehicles", "Vehicles, fuel and range", "SUV with a 400-mile range, an EV with 250 miles"],
  ["skills", "Skills and key gear", "First aid training, ham license, generator, water filter"],
  ["documents", "Where documents are kept", "Passports, deeds, insurance, go-bags"],
  ["notes", "Other notes", ""],
];
let plans = [], cur = null, busy = null;

async function loadPlans() {
  if (plans.length) return;
  try { plans = await B.api("/api/plans"); }
  catch (e) { $("tpls").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  $("tpls").innerHTML = plans.map(p =>
    `<button class="index-row" data-id="${esc(p.id)}">${B.icon(PLAN_ICONS[p.id] || "plan")}<span><b>${esc(p.title)}</b></span></button>`).join("");
}
B.tabHooks.plan = () => { loadPlans(); renderSaved(); };
$("tpls").addEventListener("click", e => { const b = e.target.closest("[data-id]"); if (b) openPlan(b.dataset.id); });
$("planBack").addEventListener("click", () => { $("tab-plan").classList.remove("chosen"); $("tab-plan").scrollTop = 0; });

async function openPlan(id, prefill = {}) {
  await loadPlans();
  cur = plans.find(p => p.id === id);
  if (!cur) return;
  let fromHousehold = {};
  if (!B.sys?.guest) {
    try {
      const prof = await B.api("/api/profile");
      fromHousehold = {
        location: prof.home || "",
        people: [prof.people, prof.medical].filter(Boolean).join("; "),
        resources: [prof.vehicles, prof.skills].filter(Boolean).join("; "),
      };
    } catch {}
  }
  const values = {...fromHousehold, ...Object.fromEntries(Object.entries(prefill).filter(([, v]) => v))};
  $$("#tpls .index-row").forEach(b => b.classList.toggle("on", b.dataset.id === id));
  $("tab-plan").classList.add("chosen");
  $("planEmpty").hidden = true;
  $("planOut").innerHTML = "";
  const field = f => {
    if (f.choices) {  // a few fixed answers: one tap
      const pick = values[f.id] || f.choices[0];
      return `<div class="full"><label class="field">${esc(f.label)}</label><div class="seg" id="pf-${esc(f.id)}" role="group">${f.choices.map(c =>
        `<button type="button" data-v="${esc(c)}" class="${c === pick ? "on" : ""}" aria-pressed="${c === pick}">${esc(c)}</button>`).join("")}</div></div>`;
    }
    const wide = WIDE.has(f.id) ? " full" : "";
    const input = `<input type="text" id="pf-${esc(f.id)}" placeholder="${esc(f.placeholder)}" value="${esc(values[f.id] || "")}" autocomplete="off">`;
    const box = ["location", "destination"].includes(f.id) ? `<div class="sugg">${input}<ul id="pfs-${esc(f.id)}" hidden></ul></div>` : input;
    return `<div class="${wide.trim()}"><label class="field" for="pf-${esc(f.id)}">${esc(f.label)}</label>${box}</div>`;
  };
  const usedHousehold = Object.values(fromHousehold).some(Boolean);
  $("planForm").innerHTML = `
    <div class="plan-head"><h2>${esc(cur.title)}</h2>
      <p>Fill in what you know. Blanks are fine: Beacon will say what it assumed.${usedHousehold ? " Some answers come from Your household." : ""}</p></div>
    <div class="formgrid">${cur.fields.map(field).join("")}
      <div class="full"><label class="field" for="pf-notes">Anything else?</label><textarea id="pf-notes" rows="2" placeholder="Deadlines, worries, what you've already done"></textarea></div>
    </div>
    <div class="form-actions"><button class="btn primary big" id="genPlan">Make the plan</button></div>`;
  $$("#planForm .seg").forEach(seg => seg.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    seg.querySelectorAll("button").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
  }));
  for (const fid of ["location", "destination"]) {
    if ($("pf-" + fid)) B.wireSuggest($("pf-" + fid), $("pfs-" + fid), () => {});
  }
  $("genPlan").addEventListener("click", genPlan);
  $("planPane").scrollTop = 0; $("tab-plan").scrollTop = 0;
}
B.openPlan = async (id, prefill) => { B.showTab("plan"); await openPlan(id, prefill); };

async function genPlan() {
  if (busy) { busy.abort(); return; }
  const answers = {notes: $("pf-notes").value};
  cur.fields.forEach(f => { answers[f.id] = f.choices ? ($(`pf-${f.id}`).querySelector("button.on")?.dataset.v || "") : $("pf-" + f.id).value; });
  let saved = null;
  const date = new Date().toLocaleDateString(undefined, {year: "numeric", month: "long", day: "numeric"});
  $("planOut").innerHTML = `
    <article class="doc" id="planDoc">
      <h2 class="doc-title">${esc(cur.title)}</h2>
      <p class="doc-meta">${esc([answers.location, date].filter(Boolean).join(", "))}</p>
      <div class="cardslot"></div>
      <div class="answer" id="planBody">${B.thinking("Starting")}</div>
      <div class="srcslot"></div>
      <div class="entry-actions noprint" id="planActions"></div>
    </article>`;
  $("planDoc").scrollIntoView({behavior: "smooth", block: "start"});
  busy = new AbortController();
  $("genPlan").textContent = "Stop";
  const body = $("planBody");
  const res = await B.stream("/api/plan", {template: cur.id, answers}, {
    signal: busy.signal,
    onStatus: s => { const t = body.querySelector(".thinking span"); if (t) t.textContent = String(s).replace(/…$/, ""); },
    onCard: c => { $("planDoc").querySelector(".cardslot").innerHTML = `<div class="cardnote noprint">${B.icon("card")}<span><b>${esc(c.title)}</b><br>The quick card for this situation, ready now.</span><button class="btn small" data-card="${esc(c.file)}">Open the card</button></div>`; },
    onToken: (t, src) => { const shown = B.stripThink(t); body.innerHTML = shown ? B.md(shown, src) : B.thinking("Writing the plan"); },
    onError: m => { body.querySelector(".thinking")?.remove(); body.insertAdjacentHTML("beforeend", `<p class="err">${esc(m)}</p>`); },
    onAbort: () => { body.querySelector(".thinking")?.remove(); body.insertAdjacentHTML("beforeend", `<p class="hint">Stopped.</p>`); },
    onSaved: d => { saved = d; },
  });
  body.querySelector(".thinking")?.remove();
  busy = null;
  $("genPlan").textContent = "Make the plan";
  if (!res.text) return;
  body.innerHTML = B.md(res.text, res.sources);
  $("planDoc").querySelector(".srcslot").innerHTML = B.sourcesHTML(res.sources);
  const title = cur.title, meta = [answers.location, date].filter(Boolean).join(", ");
  const guest = !!B.sys?.guest;
  const keep = saved
    ? `<span class="hint" id="keepNote">${saved.shared ? "Saved and shared with everyone on this Beacon." : "Saved in Library. Only on this Mac."}</span>
       <button class="btn small ghost" data-a="share">${saved.shared ? "Stop sharing" : "Share with everyone"}</button>`
    : `<button class="btn small" data-a="keep">${guest ? "Share on Beacon" : "Save to Beacon"}</button>`;
  $("planActions").innerHTML = `<div class="row"><button class="btn small primary" data-a="pdf">${B.icon("download")}Save PDF</button>
    <button class="btn small" data-a="print">${B.icon("print")}Print</button><button class="btn small" data-a="speak">Read aloud</button>
    <button class="btn small" data-a="again">Make it again</button></div><div class="keep-line">${keep}</div>`;
  $("planActions").onclick = async e => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    const a = b.dataset.a;
    if (a === "pdf") B.savePDF(title, res.text, res.sources, meta);
    if (a === "print") B.printAs("plan", title);
    if (a === "speak") B.speak(res.text, b);
    if (a === "again") genPlan();
    if (a === "keep") {
      b.disabled = true;
      try { saved = await B.archiveSave("plan", title, res.text, res.sources, {location: answers.location || "", template: cur.id}); b.textContent = guest ? "Shared" : "Saved"; }
      catch (err) { B.toast(err.message); b.disabled = false; }
    }
    if (a === "share" && saved) {
      try { await B.api(`/api/archive/${saved.id}/share`, {shared: !saved.shared}); } catch (err) { B.toast(err.message); return; }
      saved.shared = !saved.shared;
      b.textContent = saved.shared ? "Stop sharing" : "Share with everyone";
      $("keepNote").textContent = saved.shared ? "Saved and shared with everyone on this Beacon." : "Saved in Library. Only on this Mac.";
      B.toast(saved.shared ? "Shared with everyone on this Beacon" : "Only on this Mac now");
      renderSaved();
    }
  };
  renderSaved();
}

/* Saved plans, at the top of the list: they open instantly, even with the AI off. */
async function renderSaved() {
  let items = [];
  try { items = (await B.api("/api/archive")).filter(i => i.kind === "plan"); } catch {}
  $("savedPlans").innerHTML = items.length ? `<h3 class="group-label" style="margin-top:0">Saved plans</h3><div class="tpl-list">${items.slice(0, 5).map(i =>
    `<button class="index-row" data-saved="${esc(i.id)}">${B.icon("doc")}<span><b>${esc(i.title)}</b><span class="sub">${esc(new Date(i.created * 1000).toLocaleDateString())}${i.meta?.location ? ", " + esc(i.meta.location) : ""}${i.shared ? ", shared" : ""}</span></span></button>`).join("")}</div>
    ${items.length > 5 ? `<button class="link" id="allSaved" style="margin:-8px 0 18px">All ${items.length} saved plans</button>` : ""}<h3 class="group-label">New plan</h3>` : "";
  $("allSaved")?.addEventListener("click", () => { B.showTab("library"); setTimeout(() => $("lib-saved").scrollIntoView({block: "start"}), 80); });
}
B.renderSavedPlans = renderSaved;
$("savedPlans").addEventListener("click", e => { const b = e.target.closest("[data-saved]"); if (b) B.viewArchive(b.dataset.saved); });
$("planOut").addEventListener("click", e => { const b = e.target.closest("[data-card]"); if (b) B.openCards(b.dataset.card); });

async function householdSheet() {
  let prof = {};
  try { prof = await B.api("/api/profile"); } catch {}
  const drive = B.sys?.drive || {};
  const lock = drive.encrypted === true ? "This drive is encrypted, so it's locked with a password whenever it's unplugged."
    : drive.encrypted === false ? "<b>This drive isn't encrypted:</b> anyone who finds it can read this. START-HERE.txt shows how to lock it with a password."
    : "Keep the drive somewhere safe: this is saved on it.";
  const el = B.openSheet(`
    <h2>Your household</h2>
    <p class="sheet-note">Plans use this automatically, and it prints at the front of the paper binder. Guests on your Wi-Fi can't see it.</p>
    <p class="${drive.encrypted === false ? "callout" : "hint"}">${lock}</p>
    ${HOUSEHOLD.map(([k, label, ph]) => `<label class="field" for="hh-${k}">${esc(label)}</label><textarea id="hh-${k}" rows="2" placeholder="${esc(ph)}">${esc(prof[k] || "")}</textarea>`).join("")}
    <div class="sheet-actions"><button class="btn primary" id="hhSave">Save</button><a class="btn ghost" href="/binder" target="_blank" rel="noopener">Print the binder</a><span class="spacer"></span><button class="btn ghost" id="hhErase">Erase all of it</button></div>`);
  el.querySelector("#hhErase").onclick = async () => {
    if (!confirm("Erase your household info from this drive? This can't be undone.")) return;
    try { await B.api("/api/profile/erase", {}); B.toast("Household info erased"); B.closeSheet(); }
    catch (err) { B.toast(err.message); }
  };
  el.querySelector("#hhSave").onclick = async () => {
    const body = {};
    HOUSEHOLD.forEach(([k]) => { body[k] = $("hh-" + k).value; });
    try { await B.api("/api/profile", body); B.toast("Saved to the drive"); B.closeSheet(); }
    catch (err) { B.toast(err.message); }
  };
}
B.householdSheet = householdSheet;
$("householdBtn").addEventListener("click", householdSheet);
})();
