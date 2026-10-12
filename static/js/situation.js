/* Your situation: a few setup questions, Your next steps, and updates from outside.
   The Beacon computer keeps its answers on the drive. A guest's answers stay on their own phone
   and travel with each question they ask; Beacon never stores them. */
"use strict";
(() => {
const KEY = "beacon-situation";
const PHASE_SUB = {
  ahead: "Get ready before anything happens: plans, supplies and skills.",
  now: "Something is underway. Beacon leads with what to do first.",
  after: "The worst has passed: safety checks, water, repairs and recovery.",
};
let opts = null, draft = null, draftStep = 0, updTimer = null;
B.situation = null;

const guest = () => !!B.sys?.guest;
const join = a => a.length < 2 ? (a[0] || "") : a.slice(0, -1).join(", ") + " and " + a.at(-1);
const isEmpty = s => !s || !(s.phase || s.concerns?.length || s.have?.length || s.place || s.nothing
  || Object.values(s.people || {}).some(Boolean));
B.situationEmpty = () => isEmpty(B.situation);
const blank = () => ({phase: "", concerns: [], people: {adults: 1, children: 0, elders: 0, pets: 0}, needs: "", place: "", home: "", have: [], nothing: false});

async function loadSituation() {
  if (guest()) {
    try { B.situation = JSON.parse(B.store.get(KEY) || "null"); } catch { B.situation = null; }
  } else {
    try { B.situation = await B.api("/api/situation"); } catch { B.situation = null; }
  }
  return B.situation;
}
B.loadSituation = loadSituation;
async function options() { return opts || (opts = await B.api("/api/situation/options")); }

function peopleText(p = {}) {
  return join([["adults", "adult", "adults"], ["children", "child", "children"], ["elders", "older adult", "older adults"], ["pets", "pet", "pets"]]
    .filter(([k]) => p[k]).map(([k, one, many]) => `${p[k]} ${p[k] === 1 ? one : many}`));
}

/* Plans start from your answers; Your household's fuller details take precedence. */
B.situationPrefill = async () => {
  const s = B.situation;
  if (isEmpty(s)) return {};
  let o = null;
  try { o = await options(); } catch {}
  const label = Object.fromEntries((o?.have || []).flatMap(g => g.items));
  const have = (s.have || []).map(k => label[k] || "").filter(Boolean);
  return {
    phase: Object.fromEntries(o?.phases || [])[s.phase] || "",
    location: s.place || "",
    people: [peopleText(s.people), s.needs].filter(Boolean).join("; "),
    resources: [s.nothing ? "Almost nothing yet" : "", ...have].filter(Boolean).join(", "),
  };
};

async function assess() {
  return B.api("/api/situation/assess", guest() ? {situation: B.situation || {}} : {});
}

/* ---------------------------------------------------------------- actions: open the card, plan or tool a step points to */
function actBtn(a) {
  if (!a || !a.type) return "";
  let ic = {card: "card", plan: B.planIcon?.(a.id) || "plan", paper: "print"}[a.type] || "house", label = a.label;
  if (a.type === "household" && guest()) return "";
  if (a.type === "tool") {  // tools are named as they are in Tools
    const t = B.tools?.list.find(x => x.id === a.id);
    if (!t || (t.host && guest())) return "";
    ic = t.icon; label = t.title;
  }
  return `<button class="btn small" data-act="${esc(a.type)}" data-id="${esc(a.id)}">${B.icon(ic)}${esc(label)}</button>`;
}
async function runAction(type, id) {
  if (type === "household") { B.householdSheet?.(); return; }
  B.closeSheet();
  if (type === "card") B.openCards(id);
  if (type === "plan") B.openPlan(id);
  if (type === "tool") B.openTool(id);
  if (type === "paper") { B.showTab("library"); setTimeout(() => $("lib-paper")?.scrollIntoView({block: "start"}), 80); }
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-act]");
  if (b && (b.closest("#sheet") || b.closest("#forYou"))) runAction(b.dataset.act, b.dataset.id);
});

/* ---------------------------------------------------------------- the setup questions */
async function openSetup() {
  let o;
  try { o = await options(); } catch (e) { B.toast(e.message); return; }
  const host = !guest();
  let upd = null;
  if (host) { try { upd = await B.api("/api/updates"); } catch {} }
  let auto = !!upd?.auto;
  const s = draft || {...blank(), ...structuredClone(isEmpty(B.situation) ? {} : B.situation)};
  s.people = {adults: 0, children: 0, elders: 0, pets: 0, ...(s.people || {})};
  if (!Object.values(s.people).some(Boolean)) s.people.adults = 1;
  const steps = ["phase", "concerns", "people", "place", "have", ...(host ? ["updates"] : [])];
  let i = draft ? Math.min(draftStep, steps.length - 1) : 0;
  draft = s;

  const el = B.openSheet(`<div class="wiz">
      <div class="wiz-progress"><span class="vh" id="wizCount"></span>${steps.map(() => '<i aria-hidden="true"></i>').join("")}</div>
      <div id="wizBody"></div>
      <div class="wiz-foot"><button class="btn ghost" id="wizBack" type="button">Back</button><span class="spacer"></span>
        <button class="link" id="wizSkip" type="button">Skip</button><button class="btn primary" id="wizNext" type="button">Next</button></div>
    </div>`, () => { draftStep = i; }, {wide: true});
  const body = el.querySelector("#wizBody");
  const chip = (v, l, on, off) => `<button type="button" class="chip-opt ${on ? "on" : ""}" data-v="${esc(v)}" aria-pressed="${!!on}" ${off ? "disabled" : ""}>${B.icon("check")}${esc(l)}</button>`;

  function collect() {
    const needs = body.querySelector("#wNeeds"), place = body.querySelector("#wPlace");
    if (needs) s.needs = needs.value.trim();
    if (place) s.place = place.value.trim();
  }
  function draw() {
    const step = steps[i];
    el.querySelectorAll(".wiz-progress i").forEach((b, n) => b.classList.toggle("on", n <= i));
    el.querySelector("#wizCount").textContent = `Question ${i + 1} of ${steps.length}`;
    if (step === "phase") {
      body.innerHTML = `<h2>When is this for?</h2>
        <p class="sheet-note">Beacon puts first what matters most for the moment you're in.</p>
        <div class="choices" role="radiogroup">${o.phases.map(([v, l]) => `<button type="button" class="choice ${s.phase === v ? "on" : ""}" role="radio" aria-checked="${s.phase === v}" data-v="${v}">
          <b>${esc(l)}</b><span>${esc(PHASE_SUB[v] || "")}</span></button>`).join("")}</div>`;
      body.querySelector(".choices").onclick = e => {
        const b = e.target.closest(".choice"); if (!b) return;
        s.phase = b.dataset.v;
        body.querySelectorAll(".choice").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
      };
    }
    if (step === "concerns") {
      body.innerHTML = `<h2>What are you facing?</h2>
        <p class="sheet-note">Pick any that apply. Not sure yet is fine: Beacon starts with the basics that fit almost everything.</p>
        <div class="chips">${o.concerns.map(([v, l]) => chip(v, l, s.concerns.includes(v))).join("")}</div>`;
      body.querySelector(".chips").onclick = e => {
        const b = e.target.closest(".chip-opt"); if (!b) return;
        const on = !s.concerns.includes(b.dataset.v);
        s.concerns = on ? [...s.concerns, b.dataset.v] : s.concerns.filter(c => c !== b.dataset.v);
        b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      };
    }
    if (step === "people") {
      body.innerHTML = `<h2>Who's with you?</h2>
        <p class="sheet-note">Beacon plans water and food for everyone you count here.</p>
        <div class="steppers">${o.people.map(([k, l]) => `<div class="stepper"><span>${esc(l)}</span>
          <button type="button" class="icon-btn" data-k="${k}" data-d="-1" aria-label="One fewer: ${esc(l)}">${B.icon("minus")}</button>
          <b id="cnt-${k}" aria-live="polite">${s.people[k] || 0}</b>
          <button type="button" class="icon-btn" data-k="${k}" data-d="1" aria-label="One more: ${esc(l)}">${B.icon("plus")}</button></div>`).join("")}</div>
        <label class="field" for="wNeeds">Medical or special needs (optional)</label>
        <input id="wNeeds" maxlength="300" autocomplete="off" placeholder="Insulin, a CPAP machine, a wheelchair, a baby on formula" value="${esc(s.needs)}">
        <p class="small-print" style="margin-top:8px">${host ? "Saved on this drive. Guests on your Wi-Fi can't see it." : "Saved on this phone only. Beacon uses it to answer you and never stores it."}</p>`;
      body.querySelector(".steppers").onclick = e => {
        const b = e.target.closest("[data-k]"); if (!b) return;
        const k = b.dataset.k;
        s.people[k] = Math.max(0, Math.min(99, (s.people[k] || 0) + +b.dataset.d));
        body.querySelector("#cnt-" + k).textContent = s.people[k];
      };
    }
    if (step === "place") {
      body.innerHTML = `<h2>Where are you?</h2>
        <p class="sheet-note">A town or area is enough. Plans and maps start here${host ? ", and official alerts are checked for it when updates are on" : ""}.</p>
        <label class="field" for="wPlace">Town or area</label>
        <div class="sugg"><input id="wPlace" type="search" autocomplete="off" maxlength="120" placeholder="A town, or coordinates like 39.74, -104.99" value="${esc(s.place)}"><ul id="wPlaceSug" hidden></ul></div>
        <label class="field">Where you're staying</label>
        ${B.segHTML("home", o.homes, s.home)}`;
      B.wireSuggest(body.querySelector("#wPlace"), body.querySelector("#wPlaceSug"), p => { s.place = p.label; });
      B.wireSeg(body, "home", v => { s.home = v; });
    }
    if (step === "have") {
      body.innerHTML = `<h2>What do you have?</h2>
        <p class="sheet-note">Tap what you have now. Beacon shows what each is good for, what to get next and how to make do without it.</p>
        <div class="chips"><button type="button" class="chip-opt nothing ${s.nothing ? "on" : ""}" id="wNothing" aria-pressed="${!!s.nothing}">${B.icon("check")}Almost nothing yet</button></div>
        ${o.have.map(g => `<h3 class="group-label">${esc(g.group)}</h3><div class="chips">${g.items.map(([v, l]) =>
          chip(v, l, s.have.includes(v), s.nothing && !v.startsWith("skill_"))).join("")}</div>`).join("")}`;
      body.onclick = e => {
        const b = e.target.closest(".chip-opt"); if (!b || b.disabled) return;
        if (b.id === "wNothing") {
          s.nothing = !s.nothing;
          if (s.nothing) s.have = s.have.filter(k => k.startsWith("skill_"));
          draw(); return;
        }
        const on = !s.have.includes(b.dataset.v);
        s.have = on ? [...s.have, b.dataset.v] : s.have.filter(k => k !== b.dataset.v);
        b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      };
    } else body.onclick = null;
    if (step === "updates") {
      const sources = (upd?.feeds || []).map(f => f.title);
      body.innerHTML = `<h2>Updates when you're online</h2>
        <p class="sheet-note">Beacon works offline. When this Mac has internet, it can also check official alerts, disaster reports and headlines, and keep them on the drive so you, the AI and phones on your Wi-Fi can read them offline.</p>
        <div class="setting"><div><b>Check for updates when online</b><span>Off unless you turn it on. Checks at most every 30 minutes, and only while this Mac has internet.</span></div>
          <button class="switch" id="wUpd" type="button" role="switch" aria-checked="${auto}" aria-label="Check for updates when online"></button></div>
        <p class="small-print" style="margin-top:12px">What leaves this Mac: a request to each source${sources.length ? ` (${esc(join(sources))})` : ""}. The weather service also gets your town's rough location, to about a kilometer. Nothing about you or your questions is sent.</p>`;
      body.querySelector("#wUpd").onclick = e => { auto = !auto; e.currentTarget.setAttribute("aria-checked", auto); };
    }
    el.querySelector("#wizBack").style.visibility = i ? "visible" : "hidden";
    el.querySelector("#wizSkip").hidden = i === steps.length - 1;
    el.querySelector("#wizNext").textContent = i === steps.length - 1 ? "See your next steps" : "Next";
    B.hydrateIcons(body);
    body.querySelector("#wNeeds")?.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); next(); } });
    $("sheet").scrollTop = 0;
  }
  async function finish() {
    collect();
    try {
      if (host) {
        B.situation = await B.api("/api/situation", s);
        delete B.situation.saved;
        if (auto !== !!upd?.auto) await B.api("/api/updates/settings", {auto});
      } else {
        B.store.set(KEY, JSON.stringify(s));
        B.situation = structuredClone(s);
      }
    } catch (err) { B.toast(err.message); return; }
    draft = null; draftStep = 0;
    renderSteps(); renderUpdates();
    openNextSteps();
  }
  function next() {
    collect();
    if (i === steps.length - 1) finish(); else { i++; draw(); }
  }
  el.querySelector("#wizNext").onclick = next;
  el.querySelector("#wizSkip").onclick = () => { collect(); i = Math.min(i + 1, steps.length - 1); draw(); };
  el.querySelector("#wizBack").onclick = () => { collect(); i = Math.max(0, i - 1); draw(); };
  draw();
}
B.openSetup = openSetup;

/* ---------------------------------------------------------------- Your next steps */
const SECTIONS = a => [
  ["Do first", a.first.map((f, n) => `${n + 1}. ${f.text}`)],
  ["What's missing", a.gaps.map(g => `- **${g.label}.** ${g.text}${g.make_do ? ` Until then: ${g.make_do}` : ""}`)],
  ["What you have", a.have.map(h => `- **${h.label}.** ${h.text}`)],
  ["Plans for you", a.plans.map(p => `- ${p.title}`)],
  ["Quick cards", a.cards.map(c => `- ${c.label}`)],
];

async function openNextSteps() {
  let a;
  try { a = await assess(); } catch (e) { B.toast(e.message); return; }
  const host = !guest();
  const el = B.openSheet(`<div id="nextSteps">
    <h2>Your next steps</h2>
    <p class="sheet-note">${esc(a.headline || "What anyone getting ready should do first.")}</p>
    <div class="sheet-actions" style="margin-top:0"><button class="btn small" data-x="edit">Change your answers</button>
      <button class="btn small" data-x="pdf">${B.icon("download")}Save PDF</button><button class="btn small" data-x="ask">Ask Beacon</button></div>
    <h3>Do first</h3>
    <ol class="steps">${a.first.map(f => `<li><span>${esc(f.text)}</span>${actBtn(f.action)}</li>`).join("")}</ol>
    ${a.gaps.length ? `<h3>What's missing</h3><div class="rows">${a.gaps.map(g => `<div class="row-item"><div><div class="t">${esc(g.label)}</div>
      <div class="d">${esc(g.text)}${g.make_do ? `<br><b>Until then:</b> ${esc(g.make_do)}` : ""}</div></div><div class="act">${actBtn(g.action)}</div></div>`).join("")}</div>` : ""}
    ${a.have.length ? `<h3>What you have</h3><div class="rows">${a.have.map(h => `<div class="row-item"><div><div class="t">${esc(h.label)}</div>
      <div class="d">${esc(h.text)}</div></div><div class="act">${actBtn(h.action)}</div></div>`).join("")}</div>` : ""}
    ${a.plans.length ? `<h3>Plans for you</h3><div class="tpl-list">${a.plans.map(p =>
      `<button class="index-row" data-act="plan" data-id="${esc(p.id)}">${B.icon(B.planIcon?.(p.id) || "plan")}<span><b>${esc(p.title)}</b><span class="sub">${esc(p.phase)}</span></span></button>`).join("")}</div>` : ""}
    ${a.cards.length ? `<h3>Quick cards</h3><div class="row">${a.cards.map(c => actBtn({type: "card", id: c.file, label: c.label})).join("")}</div>` : ""}
    ${host && a.library.length ? `<h3>Add to the library</h3><p class="hint">Manuals that fit your situation and aren't on the drive yet. They download once, whenever this Mac has internet.</p>
      <div class="rows">${a.library.map(it => `<div class="row-item"><div><div class="t">${esc(it.title)}</div></div></div>`).join("")}</div>
      <div class="sheet-actions"><button class="btn" data-x="dl">${B.icon("download")}Download these</button></div>` : ""}</div>`, null, {wide: true});
  el.querySelector("#nextSteps").addEventListener("click", async e => {
    const b = e.target.closest("[data-x]");
    if (!b) return;
    const x = b.dataset.x;
    if (x === "edit") openSetup();
    if (x === "ask") { B.closeSheet(); B.ask("Look at my situation. What should I do first, what am I missing, and how do I make do without it?"); }
    if (x === "pdf") {
      const md = [a.headline, ...SECTIONS(a).filter(([, rows]) => rows.length).map(([h, rows]) => `## ${h}\n\n${rows.join("\n")}`)].filter(Boolean).join("\n\n");
      B.savePDF("Your next steps", md, [], B.today());
    }
    if (x === "dl") {
      b.disabled = true;
      try {
        const r = await B.api("/api/library/download", {ids: a.library.map(it => it.id)});
        B.toast(r.queued ? `Downloading ${r.queued} item${r.queued === 1 ? "" : "s"}. Follow along in Library, under Downloads.` : "Already on the drive or downloading.");
      } catch (err) { B.toast(err.message); b.disabled = false; }
    }
  });
}
B.openNextSteps = openNextSteps;

/* ---------------------------------------------------------------- Home: your next steps */
async function renderSteps() {
  const box = $("fySteps");
  if (!box || !B.sys) return;
  if (isEmpty(B.situation)) {
    box.innerHTML = `<div class="fy-head"><h2>Your next steps</h2></div>
      <p class="fy-note">Tell Beacon what you're facing, who's with you and what you have. It lays out what to do first, what's missing and how to make do without it.</p>
      <div class="row"><button class="btn primary" data-fy="setup">Set up for your situation</button>
        <span class="hint">About two minutes. ${guest() ? "Your answers stay on this phone." : "Change them any time."}</span></div>`;
    return;
  }
  let a;
  try { a = await assess(); } catch { return; }
  const missing = a.gaps.map(g => g.label[0].toLowerCase() + g.label.slice(1));  // they read as one sentence
  box.innerHTML = `<div class="fy-head"><h2>Your next steps</h2><span class="spacer"></span><button class="link" data-fy="setup">Change your answers</button></div>
    <p class="fy-note">${esc(a.headline)}</p>
    <ol class="steps">${a.first.slice(0, 3).map(f => `<li><span>${esc(f.text)}</span>${actBtn(f.action)}</li>`).join("")}</ol>
    ${missing.length ? `<p class="fy-missing"><b>Still missing:</b> ${esc(missing.length > 4 ? missing.slice(0, 4).join(", ") + ` and ${missing.length - 4} more` : join(missing))}.</p>` : ""}
    <div class="row" style="margin-top:14px"><button class="btn" data-fy="all">All your next steps</button></div>`;
}
$("forYou").addEventListener("click", e => {
  const b = e.target.closest("[data-fy]");
  if (!b) return;
  const f = b.dataset.fy;
  if (f === "setup") openSetup();
  if (f === "all") openNextSteps();
  if (f === "updates") openUpdates();
  if (f === "updon") setUpdates(true);
  if (f === "check") checkNow();
});

/* ---------------------------------------------------------------- updates from outside */
const LVL = {alert: "bad", warn: "warn", info: "info"};
const SCOPES = [["local", "Alerts for your area"], ["world", "World"], ["news", "Headlines"]];
const when = t => !t ? "" : new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
function checkedLine(u) {
  if (!u.checked) return guest() ? "The Beacon computer hasn't checked for updates yet." : u.auto ? "Not checked yet. Beacon checks whenever this Mac is online." : "Updates are off.";
  return `Checked ${when(u.checked)}${u.place ? ` for ${u.place}` : ""}${u.checking ? ". Checking again now" : ""}.`;
}
function alertBar(items) {
  const bar = $("alertBar");
  const urgent = items.filter(i => i.scope === "local" && i.level !== "info");
  if (!urgent.length) { bar.hidden = true; return; }
  const top = urgent[0];
  bar.innerHTML = `${B.icon("alert")}<span><b>${esc(top.event || top.title)}</b>${top.area ? ` for ${esc(top.area)}` : ""}${top.expires ? `, until ${esc(when(top.expires))}` : ""}.${urgent.length > 1 ? ` ${urgent.length - 1} more alert${urgent.length > 2 ? "s" : ""}.` : ""}</span>
    <button class="btn small" id="alertOpen">Details</button>`;
  bar.hidden = false;
  bar.querySelector("#alertOpen").onclick = () => openUpdates(top.id);
}
async function renderUpdates() {
  clearTimeout(updTimer);
  const box = $("fyUpdates");
  if (!box || !B.sys) return;
  let u;
  try { u = await B.api("/api/updates"); } catch { box.hidden = true; return; }
  B.updates = u;
  const items = u.items || [], host = !guest();
  alertBar(items);
  if (!items.length && !host) { box.hidden = true; $("forYou").classList.add("solo"); return; }
  box.hidden = false; $("forYou").classList.remove("solo");
  if (!items.length) {
    box.innerHTML = `<div class="fy-head"><h2>Updates</h2></div>
      ${u.auto ? `<p class="fy-note">${esc(checkedLine(u))} No alerts or headlines yet.</p>
        <div class="row">${u.online ? `<button class="btn" data-fy="check">Check now</button>` : `<span class="hint">This Mac is offline right now.</span>`}<button class="link" data-fy="updates">Settings</button></div>`
      : `<p class="fy-note">When this Mac is online, Beacon can check official alerts, disaster reports and headlines, and keep them here for reading offline. Nothing about you is sent.</p>
        <div class="row"><button class="btn" data-fy="updon">Turn on updates</button><button class="link" data-fy="updates">What it checks</button></div>`}`;
  } else {
    box.innerHTML = `<div class="fy-head"><h2>Updates</h2><span class="spacer"></span><button class="link" data-fy="updates">All ${items.length}</button></div>
      <p class="fy-note">${esc(checkedLine(u))}</p>
      <div class="upd-list">${items.slice(0, 4).map(i => `<button class="upd-row" data-upd="${esc(i.id)}"><i class="dot ${LVL[i.level] || "info"}"></i>
        <span><b>${esc(i.title)}</b><small>${esc(i.source)}${i.time ? `, ${esc(when(i.time))}` : ""}</small></span></button>`).join("")}</div>`;
  }
  updTimer = setTimeout(renderUpdates, u.checking ? 6000 : 10 * 60 * 1000);
}
$("fyUpdates").addEventListener("click", e => { const b = e.target.closest("[data-upd]"); if (b) openUpdates(b.dataset.upd); });

async function setUpdates(on) {
  try { await B.api("/api/updates/settings", {auto: on}); } catch (err) { B.toast(err.message); return; }
  B.toast(on ? "Updates on. Beacon checks whenever this Mac is online." : "Updates off");
  if (on) await checkNow(true);
  renderUpdates();
}
async function checkNow(quiet) {
  try { await B.api("/api/updates/refresh", {}); }
  catch (err) { if (!quiet) B.toast(err.message); return; }
  if (!quiet) B.toast("Checking for updates");
  setTimeout(renderUpdates, 4000);
}

async function openUpdates(focus) {
  let u = B.updates || {items: []};
  try { u = await B.api("/api/updates"); } catch {}
  const host = !guest(), items = u.items || [];
  const failed = Object.keys(u.errors || {}).map(id => (u.feeds || []).find(f => f.id === id)?.title || id);
  const sources = (u.feeds || []).map(f => f.title);
  const el = B.openSheet(`<div id="updSheet">
    <h2>Updates</h2>
    <p class="sheet-note">${esc(checkedLine(u))}${host ? "" : " They were fetched by the Beacon computer and saved for reading offline."}</p>
    ${host ? `<div class="sheet-actions" style="margin-top:0"><button class="btn small" id="updNow" ${u.online === false ? "disabled" : ""}>Check now</button>${u.online === false ? '<span class="hint">This Mac is offline right now.</span>' : ""}</div>` : ""}
    ${SCOPES.map(([scope, label]) => {
      const list = items.filter(i => i.scope === scope);
      return list.length ? `<h3>${label}</h3><div class="upd-list">${list.map(i => `<article class="upd" id="upd-${esc(i.id)}"><i class="dot ${LVL[i.level] || "info"}"></i><div>
        <b>${esc(i.title)}</b>
        ${i.summary ? `<p class="sum" title="Show more">${esc(i.summary)}</p>` : ""}
        ${i.instruction ? `<p><b>What to do:</b> ${esc(i.instruction)}</p>` : ""}
        <small>${esc([i.source, i.area, i.time ? (scope === "news" ? "" : "issued ") + when(i.time) : "", i.expires ? "until " + when(i.expires) : ""].filter(Boolean).join(", "))}</small>
        <div class="row" style="margin-top:8px"><button class="btn small" data-askupd="${esc(i.id)}">Ask Beacon</button>${i.url ? `<a class="btn small ghost" href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${B.icon("external")}Source</a>` : ""}</div>
      </div></article>`).join("")}</div>` : "";
    }).join("")}
    ${items.length ? "" : `<p class="hint">${u.checked ? "No alerts or headlines right now." : "Nothing yet."}</p>`}
    ${failed.length ? `<p class="small-print">Couldn't reach ${esc(join(failed))} last time.</p>` : ""}
    ${host ? `<h3>Settings</h3>
      <div class="setting"><div><b>Check for updates when online</b><span>Checks at most every 30 minutes, only while this Mac has internet.</span></div>
        <button class="switch" id="updAuto" role="switch" aria-checked="${!!u.auto}" aria-label="Check for updates when online"></button></div>
      <p class="small-print" style="margin-top:12px">What leaves this Mac: a request to each source${sources.length ? ` (${esc(join(sources))})` : ""}. The weather service also gets your town's rough location, to about a kilometer, for places in the US. Nothing about you or your questions is sent. Updates are saved on the drive, so phones on your Wi-Fi and the AI can read them offline; the AI is told they may be out of date.</p>` : ""}</div>`, null, {wide: true});
  el.querySelector("#updNow")?.addEventListener("click", async e => {
    e.currentTarget.disabled = true;
    await checkNow();
    setTimeout(() => { if ($("updSheet")) openUpdates(); }, 5000);
  });
  el.querySelector("#updAuto")?.addEventListener("click", async e => {
    const on = e.currentTarget.getAttribute("aria-checked") !== "true";
    e.currentTarget.setAttribute("aria-checked", on);
    await setUpdates(on);
  });
  el.querySelector("#updSheet").addEventListener("click", e => {
    const sum = e.target.closest("p.sum");
    if (sum) sum.classList.toggle("open");
    const b = e.target.closest("[data-askupd]");
    if (!b) return;
    const it = items.find(x => x.id === b.dataset.askupd);
    if (!it) return;
    B.closeSheet();
    B.ask(`An update from ${it.source} says: "${it.title}"${it.area ? ` (${it.area})` : ""}. What does it mean for us, and what should we do now?`);
  });
  if (focus) {
    const f = el.querySelector("#upd-" + CSS.escape(focus));
    if (f) { f.classList.add("focus"); setTimeout(() => f.scrollIntoView({block: "center"}), 60); }
  }
}
B.openUpdates = openUpdates;

B.afterBoot.push(() => { renderSteps(); renderUpdates(); });
})();
