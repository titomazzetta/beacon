/* Home: ask anything, common situations, and the quick cards / emergency overlay. */
"use strict";
(() => {

const SITUATIONS = [
  {icon: "drop", title: "Heavy bleeding", sub: "Stop it now", card: "first-aid-essentials.md", anchor: "bleeding", urgent: true},
  {icon: "pulse", title: "Not breathing", sub: "Start CPR now", card: "first-aid-essentials.md", anchor: "CPR", urgent: true},
  {icon: "tornado", title: "Tornado warning", sub: "Where to shelter right now",
   q: "A tornado warning was just issued for my area. What do I do right now, and where in the building should we shelter?"},
  {icon: "snow", title: "Power out in a freeze", sub: "Stay warm without poisoning anyone",
   q: "The power has been out for a day and it's below freezing. How do we keep warm safely, and protect the pipes and the food?"},
  {icon: "water", title: "Water may be unsafe", sub: "Make it safe to drink",
   q: "Our tap water might be contaminated. How do I make water safe to drink?"},
  {icon: "sun", title: "Heat illness", sub: "Exhaustion or stroke?",
   q: "Someone is overheating in a heat wave. How do I tell heat exhaustion from heat stroke, and what do I do?"},
  {icon: "compass", title: "Lost, no GPS", sub: "Find north, then stay or move",
   q: "I'm lost with no GPS or compass. How do I find north, and should I stay put or move?"},
  {icon: "car", title: "Stranded in a car", sub: "Snow, breakdown or flood",
   q: "My car is stuck in snow and it's getting dark. What should I do to stay safe until help comes?"},
  {icon: "clock", title: "Leave in 15 minutes", sub: "What to grab, what to do",
   q: "We have to evacuate in 15 minutes. What do we grab, and what do we do before we leave?"},
  {icon: "shield", title: "Secure the house", sub: "Deter, detect, delay",
   q: "Things are unstable and I'm worried about break-ins. How do I make our home a hard target and set up a watch with my family?"},
  {icon: "eyeoff", title: "Move without being seen", sub: "Evade and reach safety",
   q: "We need to get to a safer area without drawing attention. How do we plan the route, stay hidden and move safely?"},
  {icon: "breath", title: "Panicking", sub: "Calm down in two minutes",
   q: "I'm panicking and can't think straight. Walk me through calming down right now."},
  {icon: "signal", title: "Signal for rescue", sub: "SOS by light, sound or mirror",
   q: "How do I signal for rescue with a flashlight, whistle, mirror or fire?"},
  {icon: "boxes", title: "Starting with nothing", sub: "Water, warmth and food from what's around",
   q: "We have almost nothing: no stored water, no power and little food. What can we do with ordinary household items to get safe water, stay warm and eat?"},
  {icon: "waves", title: "Stranded by water", sub: "Island, coast or a crossing",
   q: "We're stranded on a coast or a small island. What do we do first for water, shelter, fire and getting rescued?"},
];

$("situations").innerHTML = SITUATIONS.map((s, i) => `
  <button class="index-row ${s.urgent ? "urgent" : ""}" data-i="${i}">${B.icon(s.icon)}
    <span><b>${esc(s.title)}</b><span class="sub">${esc(s.sub)}</span></span>${s.card ? "<em>Opens instantly</em>" : ""}</button>`).join("");
$("situations").addEventListener("click", e => {
  const b = e.target.closest("[data-i]");
  if (!b) return;
  const s = SITUATIONS[b.dataset.i];
  if (s.card) openCards(s.card, {urgent: true, anchor: s.anchor});
  else ask(s.q);
});
$("allCards").addEventListener("click", () => openCards(null));
$("helpBtn").addEventListener("click", () => openCards("first-aid-essentials.md", {urgent: true}));

/* ---------------------------------------------------------------- what's on the drive */
async function renderOnDrive() {
  let st, maps;
  try { [st, maps] = await Promise.all([B.api("/api/status"), B.api("/api/maps")]); } catch { return; }
  const manuals = st.manuals.filter(m => !m.path.startsWith("zim:") && !m.path.startsWith("cards/")).length;
  const books = st.books || [];
  const bits = [];
  if (manuals) bits.push(`${manuals.toLocaleString()} manuals and guides`);
  if (books.length) bits.push(books.length === 1 ? `the ${books[0].title} library` : `${books.length} offline libraries, including ${books.slice(0, 2).map(b => b.title).join(" and ")}`);
  if (maps.maps.length) bits.push(maps.maps.length === 1 ? "an offline map" : `${maps.maps.length} offline maps`);
  const list = bits.length > 1 ? bits.slice(0, -1).join(", ") + " and " + bits.at(-1) : bits[0];
  $("onDrive").textContent = list
    ? `On this drive: ${list}.`
    : (B.sys?.guest ? "The library on the Beacon computer is still empty." : "The library is empty so far. Open Library to add manuals, Wikipedia and maps.");
}
B.afterBoot.push(renderOnDrive);

/* ---------------------------------------------------------------- asking */
let chatHistory = [], busy = null;
const homeScroll = $("homeScroll");
function nearBottom() { return homeScroll.scrollHeight - homeScroll.scrollTop - homeScroll.clientHeight < 160; }
function setTalking(on) {
  $("tab-home").classList.toggle("talking", on);
  $("tab-home").classList.toggle("idle", !on);
}
function setBusy(ctrl) {
  busy = ctrl;
  $("sendBtn").textContent = ctrl ? "Stop" : "Ask";
  $("sendBtn").classList.toggle("primary", !ctrl);
}
const cardNote = c => `<div class="cardnote noprint">${B.icon("card")}<span><b>${esc(c.title)}</b><br>Checked steps you can follow right now, no AI needed.</span><button class="btn small" data-card="${esc(c.file)}">Open the card</button></div>`;

async function ask(text) {
  text = String(text || "").trim();
  if (!text || busy) return;
  B.showTab("home");
  setTalking(true);
  const entry = document.createElement("article");
  entry.className = "entry";
  entry.innerHTML = `<h2 class="q">${esc(text)}</h2><div class="cardslot"></div><div class="answer">${B.thinking("Starting")}</div><div class="srcslot"></div><div class="entry-actions noprint"></div>`;
  $("convo").appendChild(entry);
  entry.scrollIntoView({block: "start", behavior: "smooth"});
  const ans = entry.querySelector(".answer");
  const ctrl = new AbortController();
  setBusy(ctrl);
  let follow = true;
  const res = await B.stream("/api/ask", {question: text, history: chatHistory.slice(-6), use_library: $("useLib").checked,
                                          ...(B.sys?.guest && B.situation ? {situation: B.situation} : {})}, {
    signal: ctrl.signal,
    onStatus: s => { const t = ans.querySelector(".thinking span"); if (t) t.textContent = String(s).replace(/…$/, ""); },
    onCard: c => { entry.querySelector(".cardslot").innerHTML = cardNote(c); },
    onToken: (t, src) => {
      follow = follow && nearBottom();
      const shown = B.stripThink(t);
      ans.innerHTML = shown ? B.md(shown, src) : B.thinking("Thinking");
      if (follow) homeScroll.scrollTop = homeScroll.scrollHeight;
    },
    onError: m => { ans.querySelector(".thinking")?.remove(); ans.insertAdjacentHTML("beforeend", `<p class="err">${esc(m)}</p>`); },
    onAbort: () => { ans.querySelector(".thinking")?.remove(); ans.insertAdjacentHTML("beforeend", `<p class="hint">Stopped.</p>`); },
  });
  ans.querySelector(".thinking")?.remove();
  if (res.text) {
    ans.innerHTML = B.md(res.text, res.sources);
    entry.querySelector(".srcslot").innerHTML = B.sourcesHTML(res.sources);
    chatHistory.push({role: "user", content: text}, {role: "assistant", content: res.text});
    entryActions(entry, text, res.text, res.sources);
  }
  setBusy(null);
  if (matchMedia("(hover: hover)").matches) $("q").focus();
}
B.ask = ask;

function entryActions(entry, question, answer, sources) {
  const bar = entry.querySelector(".entry-actions");
  const title = question.length > 80 ? question.slice(0, 77) + "…" : question;
  bar.innerHTML = `<button class="btn small" data-a="speak">Read aloud</button><button class="btn small" data-a="copy">Copy</button>
    <button class="btn small" data-a="pdf">${B.icon("download")}Save PDF</button>
    <button class="btn small" data-a="keep">${B.sys?.guest ? "Share on Beacon" : "Save to Beacon"}</button>`;
  bar.addEventListener("click", async e => {
    const b = e.target.closest("[data-a]");
    if (!b) return;
    if (b.dataset.a === "speak") B.speak(answer, b);
    if (b.dataset.a === "copy") B.copy(question + "\n\n" + answer);
    if (b.dataset.a === "pdf") B.savePDF(title, answer, sources, B.today());
    if (b.dataset.a === "keep") {
      b.disabled = true;
      try { await B.archiveSave("answer", title, answer, sources); b.textContent = B.sys?.guest ? "Shared" : "Saved"; }
      catch (err) { B.toast(err.message); b.disabled = false; }
    }
  });
}

$("convo").addEventListener("click", e => { const b = e.target.closest("[data-card]"); if (b) openCards(b.dataset.card); });
$("heroForm").addEventListener("submit", e => { e.preventDefault(); const t = $("heroQ").value; $("heroQ").value = ""; ask(t); });
$("composer").addEventListener("submit", e => {
  e.preventDefault();
  if (busy) { busy.abort(); return; }
  const t = $("q").value; $("q").value = ""; grow($("q")); ask(t);
});
for (const [box, form] of [["heroQ", "heroForm"], ["q", "composer"]]) {
  $(box).addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $(form).requestSubmit(); }
  });
  $(box).addEventListener("input", () => grow($(box)));
}
function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 200) + "px"; }
$("newConvo").addEventListener("click", () => {
  busy?.abort(); chatHistory = []; $("convo").innerHTML = ""; setTalking(false); B.stopSpeaking();
  homeScroll.scrollTop = 0; $("heroQ").focus();
});
$("printConvo").addEventListener("click", () => B.printAs("chat", "Questions and answers"));
$("saveConvo").addEventListener("click", () => {
  if (!chatHistory.length) return;
  const md = [];
  for (let i = 0; i < chatHistory.length; i += 2) md.push(`## ${chatHistory[i].content}\n\n${chatHistory[i + 1]?.content || ""}`);
  B.savePDF("Questions and answers", md.join("\n\n"), [], B.today());
});

/* ---------------------------------------------------------------- quick cards and emergency */
let cardList = null, cardFile = null, cardText = "", cardTool = null;
async function loadCardList() {  // tab order and names come from Beacon (cards.py), plus any card added to the drive
  if (cardList) return cardList;
  try { cardList = (await B.api("/api/cards")).map(c => ({file: c.path.replace(/^cards\//, ""), label: c.label || c.title})); }
  catch { return [{file: "first-aid-essentials.md", label: "First aid"}]; }
  return cardList;
}
async function openCards(file, opt = {}) {
  const ov = $("cards");
  ov.classList.toggle("urgent", !!opt.urgent);
  $("cardsTitle").textContent = opt.urgent ? "Emergency" : "Quick cards";
  ov.hidden = false;
  const list = await loadCardList();
  $("cardTabs").innerHTML = list.map(c => `<button role="tab" data-card="${esc(c.file)}">${esc(c.label)}</button>`).join("");
  if (opt.tool) showCardTool(opt.tool);
  else await showCard(file || cardFile || list[0]?.file || "first-aid-essentials.md", opt.anchor);
  $("cardsClose").focus({preventScroll: true});
}
B.openCards = openCards;
function markCardTab(file) {
  $$("#cardTabs button").forEach(b => { const on = b.dataset.card === file; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); if (on) b.scrollIntoView({block: "nearest", inline: "center"}); });
  $$("#cardTools [data-tool]").forEach(b => b.classList.toggle("on", !file && b.dataset.tool === cardTool));
}
async function showCard(file, anchor) {
  stopCardTool();
  cardFile = file; markCardTab(file);
  $("cardActions").hidden = false;
  $("cardBody").innerHTML = '<p class="hint">Opening…</p>';
  let text = null;
  try {
    const r = await fetch("/read/manual/cards/" + encodeURIComponent(file));
    if (r.status === 401) return B.joinLost();
    if (r.ok) text = await r.text();
  } catch {}
  if (text == null) { $("cardBody").innerHTML = `<p class="err">This card isn't on the drive.</p>`; return; }
  cardText = text;
  $("cardBody").innerHTML = file.endsWith(".txt") ? `<pre class="plain">${esc(text)}</pre>` : B.md(text);
  $("cardSave").href = "/read/manual/cards/" + encodeURIComponent(file) + "?download=1";
  $("cardSave").setAttribute("download", file);
  $("cardScroll").scrollTop = 0;
  if (anchor) {
    const h = $$("#cardBody h2, #cardBody h3, #cardBody h4").find(h => h.textContent.toLowerCase().includes(anchor.toLowerCase()));
    if (h) $("cardScroll").scrollTop = h.offsetTop - 12;
  }
}
function showCardTool(id) {
  if (id === "light") { B.lightOn?.("white"); return; }
  stopCardTool();
  cardTool = id; cardFile = null; markCardTab(null);
  $("cardActions").hidden = true;
  $("cardScroll").scrollTop = 0;
  B.tools?.mount(id, $("cardBody"), {compact: true});
}
function stopCardTool() { if (cardTool) { B.tools?.unmount($("cardBody")); cardTool = null; } }
function closeCards() {
  stopCardTool(); B.stopSpeaking();
  $("cards").hidden = true;
}
B.closeCards = closeCards;
$("cardsClose").addEventListener("click", closeCards);
$("cardTabs").addEventListener("click", e => { const b = e.target.closest("[data-card]"); if (b) showCard(b.dataset.card); });
$("cardTools").addEventListener("click", e => { const b = e.target.closest("[data-tool]"); if (b) showCardTool(b.dataset.tool); });
$("cardSpeak").addEventListener("click", e => B.speak(cardText, e.currentTarget));
$("cardPrint").addEventListener("click", () => B.printAs("card", $$("#cardTabs button.on")[0]?.textContent || "Quick card"));
$("cardAsk").addEventListener("click", () => { closeCards(); B.showTab("home"); ($("tab-home").classList.contains("talking") ? $("q") : $("heroQ")).focus(); });
})();
