/* Tools: small offline helpers. None of them need the AI. */
"use strict";
(() => {
/* ---------------------------------------------------------------- shared helpers */
let ctx = null;
function audio() {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
  } catch { ctx = null; }
  return ctx;
}
function beep(freq = 1000, ms = 40, vol = .25, at = 0) {
  const a = audio(); if (!a) return;
  const t = at || a.currentTime, o = a.createOscillator(), g = a.createGain();
  o.frequency.value = freq; o.type = "sine";
  g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(.0001, t + ms / 1000);
  o.connect(g).connect(a.destination); o.start(t); o.stop(t + ms / 1000 + .02);
}
let wake = null;
async function keepAwake(on) {
  try {
    if (on && !wake && navigator.wakeLock) wake = await navigator.wakeLock.request("screen");
    if (!on && wake) { await wake.release(); wake = null; }
  } catch { wake = null; }
}
const num = v => { const n = parseFloat(String(v).replace(",", ".")); return Number.isFinite(n) ? n : NaN; };
const round = (v, d = 0) => { const f = 10 ** d; return Math.round(v * f) / f; };
const fmt = (v, d = 0) => round(v, d).toLocaleString(undefined, {maximumFractionDigits: d});
function frac(v) {  // 0.375 → "3/8"; kitchen measures
  const whole = Math.floor(v + 1e-9), rest = v - whole;
  const parts = [[0, ""], [1 / 8, "1/8"], [1 / 4, "1/4"], [1 / 3, "1/3"], [3 / 8, "3/8"], [1 / 2, "1/2"], [5 / 8, "5/8"], [2 / 3, "2/3"], [3 / 4, "3/4"], [7 / 8, "7/8"], [1, ""]];
  let best = parts[0];
  for (const p of parts) if (Math.abs(p[0] - rest) < Math.abs(best[0] - rest)) best = p;
  const w = whole + (best[0] === 1 ? 1 : 0);
  return [w ? String(w) : "", best[1]].filter(Boolean).join(" ") || "0";
}
function fracUp(v) {  // the next kitchen measure up, so the water always gets enough bleach
  const whole = Math.floor(v), rest = v - whole;
  const parts = [[0, ""], [1 / 8, "1/8"], [1 / 4, "1/4"], [1 / 3, "1/3"], [1 / 2, "1/2"], [2 / 3, "2/3"], [3 / 4, "3/4"], [1, ""]];
  const p = parts.find(x => x[0] >= rest - .02);
  const w = whole + (p[0] === 1 ? 1 : 0);
  return [w ? String(w) : "", p[1]].filter(Boolean).join(" ") || "1/8";
}
const clock = d => d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
const hms = ms => { const s = Math.max(0, Math.floor(ms / 1000)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s % 60).padStart(2, "0"); };
const tzLabel = () => { const o = -new Date().getTimezoneOffset(); return "UTC" + (o >= 0 ? "+" : "−") + Math.floor(Math.abs(o) / 60) + (Math.abs(o) % 60 ? ":" + String(Math.abs(o) % 60).padStart(2, "0") : ""); };
const readout = (cells, layout = "") => `<div class="readout ${layout}">${cells.map(([v, l, cls]) => `<div class="${cls || ""}"><b>${v}</b><span>${l}</span></div>`).join("")}</div>`;

/* ---------------------------------------------------------------- CPR metronome */
function cprTool(el) {
  let timer = null, count = 0, started = 0, mode = B.store.get("beacon-cpr-mode") || "hands", pause = null;
  el.innerHTML = `
    <div class="cpr"><div class="cpr-ring" id="cprRing"><div><b id="cprCount">110</b><span id="cprLabel">pushes a minute</span></div></div></div>
    <div class="row" style="justify-content:center"><button class="btn primary big" id="cprGo">Start</button>
      ${B.segHTML("cprmode", [["hands", "Hands only"], ["30:2", "30 pushes, 2 breaths"]], mode)}</div>
    <div class="row" style="justify-content:center;margin-top:12px"><label class="check"><input type="checkbox" id="cprSound" checked> Click sound</label><span class="hint" id="cprTime"></span></div>
    <ol class="tool-steps">
      <li>Call 911 or 112, or have someone call. Use an AED as soon as one arrives.</li>
      <li>Heel of one hand on the center of the chest, the other hand on top, arms straight.</li>
      <li>Push hard and fast with every click: at least 2 inches (5 cm) deep for an adult, then let the chest come all the way back up.</li>
      <li>Trained and willing? After 30 pushes, give 2 breaths. Otherwise keep pushing without stopping.</li>
      <li>Swap with someone every 2 minutes if you can. Don't stop until help takes over or the person starts breathing.</li>
    </ol>`;
  B.wireSeg(el, "cprmode", v => { mode = v; B.store.set("beacon-cpr-mode", v); });
  const ring = el.querySelector("#cprRing"), cnt = el.querySelector("#cprCount"), lab = el.querySelector("#cprLabel");
  function tick() {
    if (pause) return;
    count++;
    const shown = mode === "30:2" ? ((count - 1) % 30) + 1 : count;
    cnt.textContent = shown; lab.textContent = mode === "30:2" ? "of 30" : "pushes";
    ring.classList.add("beat"); setTimeout(() => ring.classList.remove("beat"), 90);
    if (el.querySelector("#cprSound")?.checked) beep(1100, 35, .3);
    const secs = Math.floor((Date.now() - started) / 1000);
    el.querySelector("#cprTime").textContent = `Running ${hms(secs * 1000)}` + (secs >= 120 && secs % 120 < 10 ? ". Swap pushers if you can." : "");
    if (mode === "30:2" && shown === 30) {
      pause = setTimeout(() => { pause = null; ring.classList.remove("breathe"); }, 5000);
      setTimeout(() => {
        ring.classList.add("breathe"); cnt.textContent = "2 breaths"; lab.textContent = "then keep pushing";
        if (el.querySelector("#cprSound")?.checked) { beep(620, 160, .3); setTimeout(() => beep(620, 160, .3), 1000); }
      }, 300);
    }
  }
  function start() {
    audio(); keepAwake(true);
    count = 0; started = Date.now();
    timer = setInterval(tick, 60000 / 110);
    el.querySelector("#cprGo").textContent = "Stop";
    tick();
  }
  function stop() {
    clearInterval(timer); clearTimeout(pause); timer = pause = null;
    keepAwake(false);
    ring.classList.remove("beat", "breathe");
    cnt.textContent = "110"; lab.textContent = "pushes a minute";
    const go = el.querySelector("#cprGo"); if (go) go.textContent = "Start";
  }
  el.querySelector("#cprGo").addEventListener("click", () => timer ? stop() : start());
  return stop;
}

/* ---------------------------------------------------------------- tourniquet timer */
function tourniquetTool(el) {
  const KEY = "beacon-tourniquets";
  const load = () => { try { return JSON.parse(B.store.get(KEY) || "[]"); } catch { return []; } };
  const save = l => B.store.set(KEY, JSON.stringify(l));
  el.innerHTML = `
    <p class="callout">Write the time on the tourniquet or on the person's forehead. <b>Don't loosen it or take it off</b>; that's for the hospital.</p>
    <div class="row"><input id="tqWhere" placeholder="Where it is: left thigh, right arm" style="flex:1;min-width:12em"><button class="btn primary big" id="tqAdd">Tourniquet on now</button></div>
    <div class="timer-list" id="tqList"></div>
    <p class="small-print" style="margin-top:14px">Timers are kept on this device, even if the page is closed.</p>`;
  function render() {
    const list = load();
    el.querySelector("#tqList").innerHTML = list.length ? list.map((t, i) => `
      <div class="timer-row"><div><b data-t="${t.t}">${hms(Date.now() - t.t)}</b><br><span>On at ${esc(clock(new Date(t.t)))}${t.where ? ", " + esc(t.where) : ""}</span></div>
      <button class="btn small ghost" data-del="${i}">Remove</button></div>`).join("") : '<p class="hint" style="padding:14px 2px">No tourniquet timers running.</p>';
  }
  el.querySelector("#tqAdd").addEventListener("click", () => {
    const list = load();
    list.push({t: Date.now(), where: el.querySelector("#tqWhere").value.trim()});
    save(list); el.querySelector("#tqWhere").value = ""; render();
    B.toast("Write it down: " + clock(new Date()));
  });
  el.querySelector("#tqList").addEventListener("click", e => {
    const b = e.target.closest("[data-del]");
    if (!b || !confirm("Remove this timer? Only do this once the person is in medical care.")) return;
    const list = load(); list.splice(+b.dataset.del, 1); save(list); render();
  });
  render();
  const iv = setInterval(() => el.querySelectorAll("[data-t]").forEach(b => { b.textContent = hms(Date.now() - +b.dataset.t); }), 1000);
  return () => clearInterval(iv);
}

/* ---------------------------------------------------------------- oral rehydration */
function orsTool(el) {
  el.innerHTML = `
    <div class="tool-form"><div><label class="field" for="orsL">Clean water, in liters</label><input id="orsL" type="number" inputmode="decimal" min="0.25" step="0.25" value="1"></div></div>
    <div id="orsOut"></div>
    <ol class="tool-steps">
      <li>Use water that's safe to drink: boiled and cooled, or treated.</li>
      <li>Use level teaspoons. Stir until the sugar and salt dissolve.</li>
      <li>Sip small amounts often. For a child, a spoonful every minute or two. Keep breastfeeding babies as usual.</li>
      <li><b>Never add more salt.</b> Too much is dangerous, especially for children. It should taste no saltier than tears.</li>
      <li>Make a fresh batch every day and pour out what's left after 24 hours.</li>
    </ol>
    <p class="callout">Get medical help for blood in the stool, a high fever, confusion, very little urine, or anyone who can't keep fluids down.</p>
    <p class="small-print">WHO and UNICEF home recipe: 1 liter of clean water, 6 level teaspoons of sugar, half a level teaspoon of salt. Ready-made ORS packets are better when you have them.</p>`;
  const upd = () => {
    const l = num(el.querySelector("#orsL").value);
    if (!(l > 0)) { el.querySelector("#orsOut").innerHTML = ""; return; }
    const sugar = 6 * l, salt = .5 * l;
    el.querySelector("#orsOut").innerHTML = readout([
      [frac(sugar) + " tsp", "level teaspoons of sugar" + (sugar >= 3 ? ` (${frac(sugar / 3)} tablespoons)` : "")],
      [frac(salt) + " tsp", "level teaspoons of salt"],
      [fmt(l * 1.0567, 1) + " qt", `of water (${fmt(l, 2)} liters)`],
    ]);
  };
  el.querySelector("#orsL").addEventListener("input", upd);
  upd();
}

/* ---------------------------------------------------------------- bleach for drinking water */
function bleachTool(el) {
  let unit = "gal", strength = "6", cloudy = "clear";
  const KEY = "beacon-bleach-wait";
  el.innerHTML = `
    <div class="tool-form">
      <div><label class="field" for="blAmt">How much water</label><input id="blAmt" type="number" inputmode="decimal" min="0" step="any" value="1"></div>
      <div><label class="field">&nbsp;</label>${B.segHTML("blunit", [["gal", "Gallons"], ["l", "Liters"]], unit)}</div>
    </div>
    <label class="field">Bleach strength on the label</label>${B.segHTML("blstr", [["6", "6%"], ["8.25", "8.25%"]], strength)}
    <label class="field">The water is</label>${B.segHTML("blcloud", [["clear", "Clear"], ["cloudy", "Cloudy or very cold"]], cloudy)}
    <div id="blOut"></div>
    <ol class="tool-steps">
      <li>Use plain, unscented bleach less than a year old. Not splash-less, scented or color-safe.</li>
      <li>Filter cloudy water through a clean cloth or coffee filter first, or let it settle and pour off the clear part.</li>
      <li>Stir, then wait 30 minutes. It should smell slightly of chlorine. If it doesn't, add the same amount again and wait 15 more minutes.</li>
    </ol>
    <div class="row" style="margin-top:16px"><button class="btn" id="blWait">${B.icon("timer")}Start the 30-minute wait</button><span class="hint" id="blLeft"></span></div>
    <p class="callout">Bleach and boiling kill germs. They don't remove fuel, chemicals or heavy metals. If flood water may have mixed in, find another source.</p>
    <p class="small-print">Amounts from the EPA's emergency drinking water guidance.</p>`;
  const upd = () => {
    const amt = num(el.querySelector("#blAmt").value);
    if (!(amt > 0)) { el.querySelector("#blOut").innerHTML = ""; return; }
    const gal = unit === "gal" ? amt : amt / 3.78541;
    const perGal = strength === "6" ? 8 : 6;
    const drops = Math.max(1, Math.round(gal * perGal * (cloudy === "cloudy" ? 2 : 1)));
    const tsp = drops / 96;  // the EPA's larger amounts work out to about 96 drops per teaspoon
    const cells = [[fmt(drops) + " drops", "of bleach" + (cloudy === "cloudy" ? ", doubled for cloudy or cold water" : "")]];
    if (drops >= 12) cells.push([`${fracUp(tsp)} tsp`, tsp >= 3 ? `about ${fracUp(tsp / 3)} tablespoons` : "if you'd rather measure with a teaspoon"]);
    cells.push(["30 min", "wait before drinking"]);
    el.querySelector("#blOut").innerHTML = readout(cells);
  };
  B.wireSeg(el, "blunit", v => { unit = v; upd(); });
  B.wireSeg(el, "blstr", v => { strength = v; upd(); });
  B.wireSeg(el, "blcloud", v => { cloudy = v; upd(); });
  el.querySelector("#blAmt").addEventListener("input", upd);
  let done = false;
  const left = () => {
    const end = +B.store.get(KEY) || 0, ms = end - Date.now();
    const lab = el.querySelector("#blLeft");
    if (!end || ms < -2 * 3600000) { lab.textContent = ""; if (end) B.store.del(KEY); return; }
    if (ms > 0) { lab.textContent = `${hms(ms)} left. Ready at ${clock(new Date(end))}.`; done = false; }
    else { lab.textContent = "Done. Smell it: a slight chlorine smell means it's ready."; if (!done && ms > -5000) { done = true; beep(880, 300, .3); B.toast("The water's 30 minutes are up"); } }
  };
  el.querySelector("#blWait").addEventListener("click", () => { audio(); B.store.set(KEY, String(Date.now() + 30 * 60000)); left(); });
  upd(); left();
  const iv = setInterval(left, 1000);
  return () => clearInterval(iv);
}

/* ---------------------------------------------------------------- water to store */
function waterTool(el) {
  el.innerHTML = `
    <div class="tool-form">
      <div><label class="field" for="wPeople">People</label><input id="wPeople" type="number" inputmode="numeric" min="1" value="2"></div>
      <div><label class="field" for="wDays">Days</label><input id="wDays" type="number" inputmode="numeric" min="1" value="14"></div>
    </div>
    <label class="check" style="margin-top:14px"><input type="checkbox" id="wHot"> Hot weather, heavy work, nursing or sick: double it</label>
    <div id="wOut"></div>
    <p class="small-print">Based on 1 gallon (3.8 liters) per person per day for drinking and basic hygiene, as Ready.gov recommends. Keep at least 3 days; 2 weeks is better. Add water for pets.</p>`;
  const upd = () => {
    const p = num(el.querySelector("#wPeople").value), d = num(el.querySelector("#wDays").value);
    if (!(p > 0 && d > 0)) { el.querySelector("#wOut").innerHTML = ""; return; }
    const gal = p * d * (el.querySelector("#wHot").checked ? 2 : 1), lit = gal * 3.78541;
    el.querySelector("#wOut").innerHTML = readout([
      [fmt(gal) + " gal", fmt(lit) + " liters in all"],
      [fmt(Math.ceil(gal / 5)), "5-gallon jugs"],
      [fmt(Math.ceil(lit / 12)), "cases of 24 half-liter bottles"],
    ]);
  };
  el.querySelectorAll("input").forEach(i => i.addEventListener("input", upd));
  upd();
}

/* ---------------------------------------------------------------- Morse code */
const MORSE = {A: ".-", B: "-...", C: "-.-.", D: "-..", E: ".", F: "..-.", G: "--.", H: "....", I: "..", J: ".---", K: "-.-", L: ".-..", M: "--",
  N: "-.", O: "---", P: ".--.", Q: "--.-", R: ".-.", S: "...", T: "-", U: "..-", V: "...-", W: ".--", X: "-..-", Y: "-.--", Z: "--..",
  0: "-----", 1: ".----", 2: "..---", 3: "...--", 4: "....-", 5: ".....", 6: "-....", 7: "--...", 8: "---..", 9: "----.",
  ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "@": ".--.-.", "'": ".----.", "!": "-.-.--", "-": "-....-", "(": "-.--.", ")": "-.--.-", ":": "---...", "=": "-...-", "+": ".-.-."};
const REVERSE = Object.fromEntries(Object.entries(MORSE).map(([k, v]) => [v, k]));
const toMorse = text => text.toUpperCase().trim().split(/\s+/).map(w => [...w].map(c => MORSE[c]).filter(Boolean).join(" ")).filter(Boolean).join(" / ");
const pretty = code => code.replace(/\./g, "·").replace(/-/g, "–");
function fromMorse(code) {
  return code.replace(/[·•]/g, ".").replace(/[–—_−]/g, "-").trim().split(/\s*\/\s*|\s{3,}/)
    .map(w => w.trim().split(/\s+/).map(c => REVERSE[c] || "?").join("")).join(" ");
}
function timeline(code) {  // [on?, units] using standard timing: dot 1, dash 3, gaps 1 / 3 / 7
  const out = [];
  code.split(" / ").forEach((word, wi) => {
    if (wi) out.push([false, 7]);
    word.split(" ").forEach((letter, li) => {
      if (li) out.push([false, 3]);
      [...letter].forEach((s, si) => { if (si) out.push([false, 1]); out.push([true, s === "." ? 1 : 3]); });
    });
  });
  return out;
}
let soundStop = null;
function playMorse(code, unit = 100) {
  stopSound();
  const a = audio(); if (!a) { B.toast("This device can't play sound here."); return; }
  const o = a.createOscillator(), g = a.createGain();
  o.frequency.value = 700; g.gain.value = 0; o.connect(g).connect(a.destination);
  let t = a.currentTime + .05;
  for (const [on, u] of timeline(code)) {
    const d = u * unit / 1000;
    if (on) { g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(.3, t + .005); g.gain.setValueAtTime(.3, t + d - .005); g.gain.linearRampToValueAtTime(0, t + d); }
    t += d;
  }
  o.start(); o.stop(t + .05);
  soundStop = () => { try { o.stop(); } catch {} soundStop = null; };
  o.onended = () => { soundStop = null; };
}
function stopSound() { soundStop?.(); }
function morseTool(el) {
  el.innerHTML = `
    <label class="field" for="mIn" style="margin-top:0">Type words, or dots and dashes to decode</label>
    <textarea id="mIn" rows="2" placeholder="SOS, or ... --- ...">SOS</textarea>
    <div class="morse-out" id="mOut" aria-live="polite"></div>
    <div class="row"><button class="btn primary" id="mFlash">${B.icon("flashlight")}Flash it</button><button class="btn" id="mPlay">Play the sound</button><button class="btn ghost" id="mStop">Stop</button></div>
    <div class="morse-chart">${[..."ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"].map(k => `<div>${k}<span>${pretty(MORSE[k])}</span></div>`).join("")}</div>
    <p class="small-print" style="margin-top:12px">SOS is three short, three long, three short, sent as one signal with no gaps. Any signal repeated three times also means distress.</p>`;
  const inp = el.querySelector("#mIn"), out = el.querySelector("#mOut");
  const isCode = t => /^[\s.\-·•–—_/−]+$/.test(t) && /[.\-·•–—_−]/.test(t);
  const codeOf = () => isCode(inp.value) ? inp.value.replace(/[·•]/g, ".").replace(/[–—_−]/g, "-").trim().replace(/\s*\/\s*/g, " / ") : toMorse(inp.value);
  const upd = () => { out.textContent = isCode(inp.value) ? fromMorse(inp.value) : pretty(toMorse(inp.value)); };
  inp.addEventListener("input", upd);
  el.querySelector("#mFlash").addEventListener("click", () => { const c = codeOf(); if (c) B.lightOn("message", c); });
  el.querySelector("#mPlay").addEventListener("click", () => { const c = codeOf(); if (c) playMorse(c); });
  el.querySelector("#mStop").addEventListener("click", stopSound);
  upd();
  return stopSound;
}

/* ---------------------------------------------------------------- flashlight and SOS (full screen) */
let lightTimer = null, lightMode = null, lightSound = false, lightOsc = null;
function lightPaint(on) {
  const face = $("lightFace");
  face.style.background = on ? (lightMode === "red" ? "#ff0000" : "#ffffff") : "#000";
  if (lightSound && lightMode !== "white" && lightMode !== "red") {
    const a = audio();
    if (a && on && !lightOsc) { lightOsc = a.createOscillator(); const g = a.createGain(); g.gain.value = .25; lightOsc.frequency.value = 750; lightOsc.connect(g).connect(a.destination); lightOsc.start(); }
    if (!on && lightOsc) { try { lightOsc.stop(); } catch {} lightOsc = null; }
  }
}
function lightRun(code, unit = 250) {
  const steps = timeline(code).concat([[false, 7]]);
  let i = 0;
  const step = () => {
    const [on, u] = steps[i % steps.length]; i++;
    lightPaint(on);
    lightTimer = setTimeout(step, u * unit);
  };
  step();
}
function lightOn(mode = "white", code = "") {
  clearTimeout(lightTimer); lightTimer = null;
  if (lightOsc) { try { lightOsc.stop(); } catch {} lightOsc = null; }
  lightMode = mode;
  $("light").hidden = false; keepAwake(true);
  $$("#light [data-light]").forEach(b => b.classList.toggle("on", b.dataset.light === mode || (b.dataset.light === "sound" && lightSound)));
  $("lightFace").textContent = "";
  if (mode === "white" || mode === "red") lightPaint(true);
  else if (mode === "sos") lightRun("...---...");  // SOS is sent as one signal, with no gaps between the letters
  else if (mode === "message") lightRun(code);
}
function lightOff() {
  clearTimeout(lightTimer); lightTimer = null;
  if (lightOsc) { try { lightOsc.stop(); } catch {} lightOsc = null; }
  $("light").hidden = true; $("lightFace").style.background = "#000"; keepAwake(false); lightMode = null;
}
Object.assign(B, {lightOn, lightOff});
$("light").addEventListener("click", e => {
  const b = e.target.closest("[data-light]");
  if (!b) return;
  const m = b.dataset.light;
  if (m === "off") lightOff();
  else if (m === "sound") { lightSound = !lightSound; audio(); b.classList.toggle("on", lightSound); if (!lightSound && lightOsc) { try { lightOsc.stop(); } catch {} lightOsc = null; } }
  else lightOn(m);
});

/* ---------------------------------------------------------------- heat index and wind chill */
const NWS_HEAT = [
  [125, "Extreme danger", "Heat stroke is highly likely."],
  [104, "Danger", "Heat cramps or heat exhaustion likely; heat stroke possible with long exposure or activity."],
  [91, "Extreme caution", "Heat stroke, heat cramps or heat exhaustion possible with long exposure or activity."],
  [80, "Caution", "Fatigue possible with long exposure or activity."],
];
const ECCC_COLD = [  // Environment and Climate Change Canada wind chill risk: [coldest wind chill in °C for the level, ...]
  [-55, "Extreme risk", "Exposed skin can freeze in less than 2 minutes. Outdoor conditions are hazardous."],
  [-48, "Severe risk", "Exposed skin can freeze in 2 to 5 minutes."],
  [-40, "Very high risk", "Exposed skin can freeze in 5 to 10 minutes."],
  [-28, "High risk", "Exposed skin can freeze in 10 to 30 minutes. Check faces, fingers and toes for numbness or whiteness."],
  [-10, "Moderate risk", "Uncomfortable. Hypothermia and frostbite are possible after long periods outside without good protection."],
  [Infinity, "Low risk", "Slightly uncomfortable."],
];
function heatIndexF(T, RH) {  // NWS: Rothfusz regression with its adjustments
  let hi = .5 * (T + 61 + (T - 68) * 1.2 + RH * .094);
  if ((hi + T) / 2 < 80) return hi;
  hi = -42.379 + 2.04901523 * T + 10.14333127 * RH - .22475541 * T * RH - .00683783 * T * T - .05481717 * RH * RH
    + .00122874 * T * T * RH + .00085282 * T * RH * RH - .00000199 * T * T * RH * RH;
  if (RH < 13 && T >= 80 && T <= 112) hi -= ((13 - RH) / 4) * Math.sqrt((17 - Math.abs(T - 95)) / 17);
  else if (RH > 85 && T >= 80 && T <= 87) hi += ((RH - 85) / 10) * ((87 - T) / 5);
  return hi;
}
const windChillF = (T, V) => 35.74 + .6215 * T - 35.75 * V ** .16 + .4275 * T * V ** .16;  // NWS 2001 formula
const fToC = f => (f - 32) * 5 / 9, cToF = c => c * 9 / 5 + 32;
function heatColdTool(el) {
  let tu = B.store.get("beacon-tunit") || "F", wu = tu === "F" ? "mph" : "kmh";
  el.innerHTML = `
    <div class="tool-form">
      <div><label class="field" for="hcT">Air temperature</label><input id="hcT" type="number" inputmode="decimal" step="any" placeholder="${tu === "F" ? "95" : "35"}"></div>
      <div><label class="field">&nbsp;</label>${B.segHTML("tunit", [["F", "°F"], ["C", "°C"]], tu)}</div>
      <div><label class="field" for="hcH">Humidity, %</label><input id="hcH" type="number" inputmode="decimal" min="0" max="100" step="any" placeholder="60"></div>
      <div><label class="field" for="hcW">Wind speed</label><input id="hcW" type="number" inputmode="decimal" min="0" step="any" placeholder="10"></div>
      <div><label class="field">&nbsp;</label>${B.segHTML("wunit", [["mph", "mph"], ["kmh", "km/h"]], wu)}</div>
    </div>
    <div id="hcOut"></div>
    <p class="small-print">Heat index: National Weather Service formula and categories, for shade. Full sun can add up to 15°F (8°C). Wind chill: National Weather Service formula with Environment Canada's frostbite risk levels.</p>`;
  const upd = () => {
    const t = num(el.querySelector("#hcT").value), h = num(el.querySelector("#hcH").value), w = num(el.querySelector("#hcW").value);
    const out = el.querySelector("#hcOut");
    if (!Number.isFinite(t)) { out.innerHTML = '<p class="hint" style="margin-top:16px">Enter the temperature, plus humidity for heat or wind for cold.</p>'; return; }
    const T = tu === "F" ? t : cToF(t);
    const both = f => `${fmt(f)}°F / ${fmt(fToC(f))}°C`;
    if (T >= 80 && Number.isFinite(h)) {
      const hi = heatIndexF(T, Math.min(100, Math.max(0, h)));
      const cat = NWS_HEAT.find(c => hi >= c[0]);
      out.innerHTML = readout([[both(hi), "feels like (heat index)", cat && cat[0] >= 104 ? "alert" : ""], [cat ? cat[1] : "Below caution", "National Weather Service level"]])
        + (cat ? `<p class="callout"><b>${esc(cat[1])}.</b> ${esc(cat[2])} Drink water often, rest in shade, and check on older people, children and pets. Hot, dry or confused means heat stroke: call for help and cool the person fast.</p>` : "");
      return;
    }
    const mph = Number.isFinite(w) ? (wu === "mph" ? w : w / 1.609344) : NaN;
    if (T <= 50 && mph >= 3) {
      const wc = windChillF(T, mph), wcC = fToC(wc);
      const r = ECCC_COLD.find(c => Math.round(wcC) <= c[0]);
      out.innerHTML = readout([[both(wc), "feels like (wind chill)", wcC <= -28 ? "alert" : ""], [r[1], "frostbite risk"]])
        + `<p class="callout"><b>${esc(r[1])}.</b> ${esc(r[2])} In winds over 30 mph (50 km/h), skin can freeze even faster.</p>`;
      return;
    }
    out.innerHTML = readout([[both(T), "about what it feels like"]])
      + `<p class="hint">Heat index applies from 80°F (27°C) with humidity entered. Wind chill applies at 50°F (10°C) or colder with wind of at least 3 mph (5 km/h).</p>`;
  };
  B.wireSeg(el, "tunit", v => { tu = v; B.store.set("beacon-tunit", v); upd(); });
  B.wireSeg(el, "wunit", v => { wu = v; upd(); });
  el.querySelectorAll("input").forEach(i => i.addEventListener("input", upd));
  upd();
}

/* ---------------------------------------------------------------- lightning distance */
function lightningTool(el) {
  let t0 = 0, iv = null;
  const log = [];
  el.innerHTML = `
    <div class="cpr"><button class="cpr-ring" id="lgBtn" style="background:none;color:inherit;cursor:pointer"><div><b id="lgBig">Flash</b><span id="lgSmall">Tap when you see lightning</span></div></button></div>
    <div id="lgOut"></div>
    <div class="timer-list" id="lgLog" hidden></div>
    <p class="callout"><b>When thunder roars, go indoors.</b> If you can hear thunder, you're close enough to be struck. Stay inside until 30 minutes after the last thunder.</p>`;
  const btn = el.querySelector("#lgBtn"), big = el.querySelector("#lgBig"), small = el.querySelector("#lgSmall");
  btn.addEventListener("click", () => {
    if (!t0) {
      t0 = Date.now(); big.textContent = "0"; small.textContent = "Tap when you hear thunder";
      iv = setInterval(() => { big.textContent = Math.floor((Date.now() - t0) / 1000); }, 200);
      return;
    }
    const s = (Date.now() - t0) / 1000;
    clearInterval(iv); t0 = 0;
    big.textContent = "Flash"; small.textContent = "Tap at the next lightning";
    log.unshift({s, at: new Date()});
    const mi = s / 5, km = s / 3;
    el.querySelector("#lgOut").innerHTML = readout([[fmt(s, 1) + " s", "flash to thunder"], [fmt(mi, 1) + " mi", fmt(km, 1) + " km away"]])
      + (s < 30 ? `<p class="callout"><b>Close enough to strike you.</b> Get inside a building or a hard-topped car now. Stay away from open fields, hilltops, lone trees, water and metal fences.</p>` : "");
    const trend = log.length > 1 ? (log[0].s < log[1].s - 1 ? "Getting closer" : log[0].s > log[1].s + 1 ? "Moving away" : "About the same distance") : "";
    const lg = el.querySelector("#lgLog");
    lg.hidden = false;
    lg.innerHTML = (trend ? `<p class="group-label">${trend}</p>` : "") + log.slice(0, 6).map(r => `<div class="timer-row"><div><span>${esc(clock(r.at))}</span></div><span>${fmt(r.s / 5, 1)} mi / ${fmt(r.s / 3, 1)} km</span></div>`).join("");
  });
  return () => clearInterval(iv);
}

/* ---------------------------------------------------------------- sun and moon */
function solar(day, lat, lon) {  // NOAA solar calculator equations
  const rad = Math.PI / 180, deg = 180 / Math.PI;
  const y = day.getFullYear(), m = day.getMonth(), d = day.getDate();
  const base = Date.UTC(y, m, d);
  const jd = base / 86400000 + 2440587.5 + .5 - lon / 360;
  const T = (jd - 2451545) / 36525;
  const L0 = ((280.46646 + T * (36000.76983 + T * .0003032)) % 360 + 360) % 360;
  const M = 357.52911 + T * (35999.05029 - .0001537 * T);
  const e = .016708634 - T * (.000042037 + .0000001267 * T);
  const C = Math.sin(M * rad) * (1.914602 - T * (.004817 + .000014 * T)) + Math.sin(2 * M * rad) * (.019993 - .000101 * T) + Math.sin(3 * M * rad) * .000289;
  const omega = 125.04 - 1934.136 * T;
  const lambda = L0 + C - .00569 - .00478 * Math.sin(omega * rad);
  const eps = 23 + (26 + (21.448 - T * (46.815 + T * (.00059 - T * .001813))) / 60) / 60 + .00256 * Math.cos(omega * rad);
  const decl = Math.asin(Math.sin(eps * rad) * Math.sin(lambda * rad)) * deg;
  const yv = Math.tan(eps / 2 * rad) ** 2;
  const eqt = 4 * deg * (yv * Math.sin(2 * L0 * rad) - 2 * e * Math.sin(M * rad) + 4 * e * yv * Math.sin(M * rad) * Math.cos(2 * L0 * rad)
    - .5 * yv * yv * Math.sin(4 * L0 * rad) - 1.25 * e * e * Math.sin(2 * M * rad));
  const noon = 720 - 4 * lon - eqt;
  const at = min => new Date(base + min * 60000);
  const pair = zenith => {
    const cosH = (Math.cos(zenith * rad) - Math.sin(lat * rad) * Math.sin(decl * rad)) / (Math.cos(lat * rad) * Math.cos(decl * rad));
    if (cosH > 1) return "never";   // the sun stays below this angle all day
    if (cosH < -1) return "always"; // it stays above it all day
    const H = Math.acos(cosH) * deg;
    return [at(noon - 4 * H), at(noon + 4 * H)];
  };
  return {noon: at(noon), sun: pair(90.833), civil: pair(96), decl};
}
function moonPhase(when) {
  const syn = 29.530588853;
  const jd = when.getTime() / 86400000 + 2440587.5;
  const age = (((jd - 2451550.26) % syn) + syn) % syn;  // days since a known new moon (6 Jan 2000)
  const f = age / syn;
  const names = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"];
  return {name: names[Math.floor(f * 8 + .5) % 8], lit: (1 - Math.cos(2 * Math.PI * f)) / 2, toFull: ((f < .5 ? .5 : 1.5) - f) * syn, toNew: (1 - f) * syn};
}
function sunTool(el) {
  let place = B.lastPlace || null;
  const today = new Date(), iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  el.innerHTML = `
    <div class="tool-form">
      <div style="grid-column:span 2"><label class="field" for="smPlace">Where</label><div class="sugg"><input id="smPlace" type="search" autocomplete="off" placeholder="City, or coordinates like 39.74, -104.99" value="${esc(place?.label || "")}"><ul id="smSug" hidden></ul></div></div>
      <div><label class="field" for="smDate">Day</label><input id="smDate" type="date" value="${iso(today)}"></div>
    </div>
    <div id="smOut"></div>
    <p class="small-print">Times are in this device's time zone (${tzLabel()}) and accurate to a minute or two. Moon phase dates can be off by half a day.</p>`;
  const upd = () => {
    const out = el.querySelector("#smOut");
    const [yy, mm, dd] = (el.querySelector("#smDate").value || iso(today)).split("-").map(Number);
    const day = new Date(yy, mm - 1, dd, 12);
    const mo = moonPhase(day);
    const moonCells = [[mo.name, `${Math.round(mo.lit * 100)}% lit`],
      [mo.toFull < mo.toNew ? `${fmt(mo.toFull)} days` : `${fmt(mo.toNew)} days`, mo.toFull < mo.toNew ? "until the full moon" : "until the new moon"]];
    if (!place) { out.innerHTML = '<p class="hint" style="margin-top:16px">Pick a place to see sunrise and sunset.</p>' + readout(moonCells); return; }
    const s = solar(day, place.lat, place.lon);
    const t = (p, i) => p === "never" ? "None" : p === "always" ? "All day" : clock(p[i]);
    const len = Array.isArray(s.sun) ? (s.sun[1] - s.sun[0]) / 3600000 : s.sun === "always" ? 24 : 0;
    const south = place.lat >= s.decl;
    out.innerHTML = readout([
      [t(s.civil, 0), "first light"], [t(s.sun, 0), "sunrise"], [t(s.sun, 1), "sunset"], [t(s.civil, 1), "last light"],
      [`${Math.floor(len)} h ${String(Math.round((len % 1) * 60)).padStart(2, "0")} m`, "of daylight"], [clock(s.noon), `sun due ${south ? "south" : "north"}`],
    ]) + readout(moonCells)
      + `<p class="callout">At ${esc(clock(s.noon))} the sun is due ${south ? "south" : "north"} and shadows point ${south ? "north" : "south"}. ${mo.lit > .6 ? "Tonight is bright: easier to see, and easier to be seen." : mo.lit < .25 ? "Tonight is dark: carry a red light and move carefully." : ""}</p>`;
  };
  B.wireSuggest(el.querySelector("#smPlace"), el.querySelector("#smSug"), p => { place = p; B.lastPlace = p; upd(); });
  el.querySelector("#smDate").addEventListener("input", upd);
  upd();
}

/* ---------------------------------------------------------------- translate (uses the AI) */
const LANGS = [["Arabic", "ar"], ["Bengali", "bn"], ["Chinese (Mandarin)", "zh"], ["English", "en"], ["Farsi (Persian)", "fa"], ["French", "fr"],
  ["German", "de"], ["Greek", "el"], ["Haitian Creole", "ht"], ["Hebrew", "he"], ["Hindi", "hi"], ["Indonesian", "id"], ["Italian", "it"],
  ["Japanese", "ja"], ["Korean", "ko"], ["Polish", "pl"], ["Portuguese", "pt"], ["Romanian", "ro"], ["Russian", "ru"], ["Spanish", "es"],
  ["Swahili", "sw"], ["Tagalog", "tl"], ["Turkish", "tr"], ["Ukrainian", "uk"], ["Urdu", "ur"], ["Vietnamese", "vi"]];
const PHRASES = ["We need a doctor.", "Where is the nearest hospital?", "We need clean water.", "We are not dangerous. We need help.",
  "Is this road safe?", "Where is the border crossing?", "Do you speak English?", "We are looking for our family."];
function translateTool(el) {
  let ctrl = null, lastLang = B.store.get("beacon-lang") || "Spanish";
  el.innerHTML = `
    <label class="field" for="trIn" style="margin-top:0">What do you want to say?</label>
    <textarea id="trIn" rows="3" placeholder="Type in any language"></textarea>
    <div class="row" style="margin-top:8px">${PHRASES.map(p => `<button class="btn small ghost" data-p="${esc(p)}">${esc(p)}</button>`).join("")}</div>
    <div class="row" style="margin-top:14px"><label class="check" for="trLang">Into</label>
      <select id="trLang">${LANGS.map(([n]) => `<option ${n === lastLang ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <button class="btn primary" id="trGo">Translate</button></div>
    <div class="translation" id="trOut" aria-live="polite"></div>
    <div class="row" style="margin-top:10px"><button class="btn small" id="trSpeak">Read aloud</button><button class="btn small" id="trCopy">Copy</button></div>
    <p class="small-print" style="margin-top:12px">Translated by the AI on the Beacon computer. Keep sentences short and simple, and double-check anything critical, like medicines or allergies.</p>`;
  const out = el.querySelector("#trOut");
  el.querySelector(".row").addEventListener("click", e => { const b = e.target.closest("[data-p]"); if (b) el.querySelector("#trIn").value = b.dataset.p; });
  el.querySelector("#trGo").addEventListener("click", async () => {
    if (ctrl) { ctrl.abort(); return; }
    const text = el.querySelector("#trIn").value.trim(), to = el.querySelector("#trLang").value;
    if (!text) return;
    B.store.set("beacon-lang", to);
    ctrl = new AbortController();
    el.querySelector("#trGo").textContent = "Stop";
    out.innerHTML = B.thinking("Translating");
    const res = await B.stream("/api/translate", {text, to}, {
      signal: ctrl.signal,
      onToken: t => { out.textContent = B.stripThink(t); },
      onError: m => { out.innerHTML = `<span class="err">${esc(m)}</span>`; },
    });
    if (res.text) out.textContent = res.text;
    else if (out.querySelector(".thinking")) out.textContent = "";
    ctrl = null;
    el.querySelector("#trGo").textContent = "Translate";
  });
  el.querySelector("#trSpeak").addEventListener("click", e => {
    const code = (LANGS.find(([n]) => n === el.querySelector("#trLang").value) || [])[1];
    if (out.textContent.trim()) B.speak(out.textContent, e.currentTarget, code);
  });
  el.querySelector("#trCopy").addEventListener("click", () => { if (out.textContent.trim()) B.copy(out.textContent); });
  return () => ctrl?.abort();
}

/* ---------------------------------------------------------------- unit converter */
const UNITS = {
  distance: [["mi", "miles", 1609.344], ["km", "kilometers", 1000], ["m", "meters", 1], ["ft", "feet", .3048], ["yd", "yards", .9144], ["in", "inches", .0254], ["cm", "centimeters", .01], ["nmi", "nautical miles", 1852]],
  weight: [["lb", "pounds", .45359237], ["kg", "kilograms", 1], ["oz", "ounces", .028349523125], ["g", "grams", .001]],
  volume: [["gal", "US gallons", 3.785411784], ["l", "liters", 1], ["qt", "US quarts", .946352946], ["cup", "US cups", .2365882365], ["floz", "US fluid ounces", .0295735295625], ["ml", "milliliters", .001], ["tbsp", "tablespoons", .01478676478125], ["tsp", "teaspoons", .00492892159375]],
  speed: [["mph", "miles per hour", .44704], ["kmh", "km per hour", 1 / 3.6], ["kn", "knots", .514444], ["ms", "meters per second", 1]],
  temperature: [["F", "°F"], ["C", "°C"], ["K", "kelvin"]],
};
function unitsTool(el) {
  let cat = B.store.get("beacon-unitcat") || "distance";
  el.innerHTML = `
    ${B.segHTML("ucat", [["distance", "Distance"], ["weight", "Weight"], ["volume", "Volume"], ["temperature", "Temperature"], ["speed", "Speed"]], cat)}
    <div class="tool-form" style="margin-top:6px">
      <div><label class="field" for="uVal">Amount</label><input id="uVal" type="number" inputmode="decimal" step="any" value="1"></div>
      <div><label class="field" for="uFrom">In</label><select id="uFrom" style="width:100%"></select></div>
    </div>
    <div id="uOut"></div>`;
  const fill = () => { el.querySelector("#uFrom").innerHTML = UNITS[cat].map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join(""); };
  const upd = () => {
    const v = num(el.querySelector("#uVal").value), from = el.querySelector("#uFrom").value, out = el.querySelector("#uOut");
    if (!Number.isFinite(v)) { out.innerHTML = ""; return; }
    let cells;
    if (cat === "temperature") {
      const c = from === "C" ? v : from === "F" ? fToC(v) : v - 273.15;
      cells = [[fmt(cToF(c), 1) + "°F", "Fahrenheit"], [fmt(c, 1) + "°C", "Celsius"], [fmt(c + 273.15, 1) + " K", "kelvin"]].filter((_, i) => ["F", "C", "K"][i] !== from);
    } else {
      const base = v * UNITS[cat].find(u => u[0] === from)[2];
      cells = UNITS[cat].filter(u => u[0] !== from).map(([, n, f]) => { const x = base / f; return [fmt(x, Math.abs(x) >= 100 ? 0 : Math.abs(x) >= 1 ? 2 : 4), n]; });
    }
    out.innerHTML = readout(cells);
  };
  B.wireSeg(el, "ucat", v => { cat = v; B.store.set("beacon-unitcat", v); fill(); upd(); });
  el.querySelector("#uVal").addEventListener("input", upd);
  el.querySelector("#uFrom").addEventListener("change", upd);
  fill(); upd();
}

/* ---------------------------------------------------------------- power budget */
const DEVICES = [  // rough typical figures; the card says to check labels
  ["Phone charging", 15, 2], ["LED bulb", 9, 5], ["Wi-Fi router", 10, 24], ["Laptop", 45, 3], ["Mac running Beacon's AI", 60, 4],
  ["CPAP (no heated humidifier)", 40, 8], ["Fridge (average while cycling)", 70, 24], ["Chest freezer (average)", 35, 24],
  ["Fan", 40, 8], ["TV", 80, 3], ["Electric blanket", 100, 8], ["Microwave", 1000, 0.25], ["Coffee maker", 900, 0.25],
  ["Oxygen concentrator", 350, 24], ["Well pump", 1000, 1], ["Space heater", 1500, 4]];
function powerTool(el) {
  const KEY = "beacon-power";
  let st;
  try { st = JSON.parse(B.store.get(KEY) || "null"); } catch {}
  st = st || {rows: [["Phone charging", 15, 2, 2], ["LED bulb", 9, 5, 3], ["Wi-Fi router", 10, 24, 1], ["Fridge (average while cycling)", 70, 24, 1]],
              battery: 2048, inverter: 2400, panels: 400, sun: 4};
  const save = () => B.store.set(KEY, JSON.stringify(st));
  el.innerHTML = `
    <div id="pwOut"></div>
    <div id="pwRows" class="rows"></div>
    <div class="row" style="margin-top:10px"><select id="pwAdd"><option value="">Add a device…</option>${DEVICES.map((d, i) => `<option value="${i}">${esc(d[0])}, about ${d[1]} W</option>`).join("")}<option value="custom">Something else</option></select></div>
    <div class="tool-form" style="margin-top:8px">
      <div><label class="field" for="pwBat">Battery size (Wh)</label><input id="pwBat" type="number" inputmode="numeric" min="0" value="${st.battery}"></div>
      <div><label class="field" for="pwInv">Most watts at once (W)</label><input id="pwInv" type="number" inputmode="numeric" min="0" value="${st.inverter}"></div>
      <div><label class="field" for="pwPanels">Solar panels (W)</label><input id="pwPanels" type="number" inputmode="numeric" min="0" value="${st.panels}"></div>
      <div><label class="field" for="pwSun">Peak sun hours</label><input id="pwSun" type="number" inputmode="decimal" min="0" max="12" step="0.5" value="${st.sun}"></div>
    </div>
    <p class="small-print">Example battery: a 2,048 Wh power station with 2,400 W of output (like the Anker SOLIX C2000 Gen 2). About 85% of a battery's watt-hours reach your devices through the inverter, and solar panels give about 75% of their rating times the sun hours. Device figures are typical; check your labels. See the Off-grid power card for safety.</p>`;
  function rows() {
    el.querySelector("#pwRows").innerHTML = st.rows.map((r, i) => `<div class="row-item" style="grid-template-columns:1fr auto">
      <div><div class="t">${esc(r[0])}</div><div class="d">
        <input type="number" inputmode="numeric" min="0" value="${r[1]}" data-i="${i}" data-k="1" aria-label="Watts" style="width:5.5em;padding:4px 8px"> W ×
        <input type="number" inputmode="decimal" min="0" max="24" step="0.25" value="${r[2]}" data-i="${i}" data-k="2" aria-label="Hours a day" style="width:5em;padding:4px 8px"> h a day ×
        <input type="number" inputmode="numeric" min="1" value="${r[3]}" data-i="${i}" data-k="3" aria-label="How many" style="width:4em;padding:4px 8px"> of them = <b>${fmt(r[1] * r[2] * r[3])} Wh</b></div></div>
      <div class="act"><button class="btn small ghost" data-del="${i}" aria-label="Remove ${esc(r[0])}">Remove</button></div></div>`).join("") || '<p class="hint" style="padding:10px 2px">Add the devices you need to keep running.</p>';
  }
  function out() {
    const use = st.rows.reduce((a, r) => a + r[1] * r[2] * r[3], 0), peak = st.rows.reduce((a, r) => a + r[1] * r[3], 0);
    const usable = st.battery * .85, solar = st.panels * st.sun * .75;
    const daysBattery = use ? usable / use : Infinity, net = use - solar;
    const withSolar = !use ? "Nothing to power" : net <= 0 ? "Indefinitely, if the sun holds" : `${fmt(usable / net, 1)} days`;
    const big = st.rows.filter(r => r[1] > st.inverter);
    el.querySelector("#pwOut").innerHTML = readout([
      [`${fmt(use)} Wh`, "used per day"],
      [`${fmt(peak)} W`, `if everything runs at once${peak > st.inverter ? ", over the limit" : ""}`, peak > st.inverter ? "alert" : ""],
      [Number.isFinite(daysBattery) ? `${fmt(daysBattery, 1)} days` : "No use", "on the battery alone"],
      [`${fmt(solar)} Wh`, "from solar per day"],
      [withSolar, "with solar recharging"],
    ]) + (big.length ? `<p class="callout"><b>Too big for this battery's outlets:</b> ${big.map(r => esc(r[0])).join(", ")}. Run them on a generator outdoors, or do without.</p>` : "")
      + (peak > st.inverter && !big.length ? `<p class="callout">Don't run everything at once: stagger the big loads (microwave, pump, coffee maker) so the total stays under ${fmt(st.inverter)} W.</p>` : "");
  }
  el.querySelector("#pwRows").addEventListener("input", e => {
    const t = e.target;
    if (t.dataset.i === undefined) return;
    st.rows[+t.dataset.i][+t.dataset.k] = Math.max(0, num(t.value) || 0);
    save(); out();
    const b = t.closest(".d")?.querySelector("b"), r = st.rows[+t.dataset.i];
    if (b) b.textContent = `${fmt(r[1] * r[2] * r[3])} Wh`;
  });
  el.querySelector("#pwRows").addEventListener("click", e => {
    const d = e.target.closest("[data-del]");
    if (!d) return;
    st.rows.splice(+d.dataset.del, 1); save(); rows(); out();
  });
  el.querySelector("#pwAdd").addEventListener("change", e => {
    const v = e.target.value;
    if (v === "custom") {
      const name = prompt("What is it?");
      if (name) st.rows.push([name.slice(0, 40), 50, 2, 1]);
    } else if (v !== "") st.rows.push([DEVICES[+v][0], DEVICES[+v][1], DEVICES[+v][2], 1]);
    e.target.value = ""; save(); rows(); out();
  });
  for (const [id, k] of [["pwBat", "battery"], ["pwInv", "inverter"], ["pwPanels", "panels"], ["pwSun", "sun"]]) {
    el.querySelector("#" + id).addEventListener("input", e => { st[k] = Math.max(0, num(e.target.value) || 0); save(); out(); });
  }
  rows(); out();
}

/* ---------------------------------------------------------------- supplies (saved on the drive) */
const FOODS = [["Rice, 1 lb bag", 1650], ["Dry beans, 1 lb bag", 1550], ["Pasta, 1 lb box", 1600], ["Rolled oats, 42 oz canister", 4500],
  ["Peanut butter, 16 oz jar", 2650], ["Canned beans, 15 oz can", 385], ["Canned vegetables, 15 oz can", 150], ["Canned chicken, 12.5 oz can", 280],
  ["Canned tuna, 5 oz can", 120], ["MRE, one meal", 1250], ["Freeze-dried meal pouch", 500], ["Protein or granola bar", 200]];
const WATER_UNITS = [["gal", "gallons", 1], ["l", "liters", .264172], ["bottle", "half-liter bottles", .132086], ["jug5", "5-gallon jugs", 5]];
function suppliesTool(el) {
  let data = {people: 2, items: []}, timer = null;
  el.innerHTML = `
    <div class="tool-form"><div><label class="field" for="spPeople">People (and pets, roughly)</label><input id="spPeople" type="number" inputmode="numeric" min="1" value="2"></div></div>
    <div id="spOut"></div>
    <h3 class="group-label">Add</h3>
    <div class="tool-form">
      <div><label class="field" for="spCat">Kind</label><select id="spCat" style="width:100%"><option value="water">Water</option><option value="food">Food</option><option value="medicine">Medicine</option><option value="power">Power and fuel</option><option value="other">Other</option></select></div>
      <div id="spWhat"></div>
      <div><label class="field" for="spQty">How many</label><input id="spQty" type="number" inputmode="decimal" min="0" step="any" value="1"></div>
      <div><label class="field" for="spExp">Expires (optional)</label><input id="spExp" type="month"></div>
    </div>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="spAdd">Add</button></div>
    <div id="spList" style="margin-top:18px"></div>
    <h3 class="group-label" style="margin-top:22px">Make it last</h3>
    <div class="tool-form"><div><label class="field" for="spDays">Days until help or resupply</label><input id="spDays" type="number" inputmode="numeric" min="1" value="14"></div></div>
    <div id="spRation"></div>
    <p class="small-print">Saved on this drive, with your household info. Food figures are typical calories for each item; check labels for your own. Planning numbers: 1 gallon of water and about 2,000 calories per person per day.</p>`;
  const what = () => {
    const cat = el.querySelector("#spCat").value;
    el.querySelector("#spWhat").innerHTML = cat === "water"
      ? `<label class="field" for="spUnit">In</label><select id="spUnit" style="width:100%">${WATER_UNITS.map(u => `<option value="${u[0]}">${u[1]}</option>`).join("")}</select>`
      : cat === "food"
        ? `<label class="field" for="spFood">What</label><select id="spFood" style="width:100%">${FOODS.map((f, i) => `<option value="${i}">${esc(f[0])} (about ${fmt(f[1])} cal)</option>`).join("")}<option value="custom">Something else</option></select>
           <input id="spName" placeholder="Name" style="margin-top:6px" hidden><input id="spKcal" type="number" min="0" placeholder="Calories each" style="margin-top:6px" hidden>`
        : `<label class="field" for="spName">What</label><input id="spName" placeholder="${cat === "medicine" ? "Ibuprofen 200 mg, 100 tablets" : cat === "power" ? "AA batteries, propane 1 lb" : "What it is"}">`;
    el.querySelector("#spFood")?.addEventListener("change", e => {
      const custom = e.target.value === "custom";
      el.querySelector("#spName").hidden = !custom; el.querySelector("#spKcal").hidden = !custom;
    });
  };
  const save = () => { clearTimeout(timer); timer = setTimeout(() => B.api("/api/supplies", data).catch(err => B.toast(err.message)), 400); };
  const monthsLeft = exp => { if (!exp) return Infinity; const [y, m] = exp.split("-").map(Number); const now = new Date(); return (y - now.getFullYear()) * 12 + (m - 1 - now.getMonth()); };
  function render() {
    const p = Math.max(1, data.people || 1);
    const gallons = data.items.filter(i => i.cat === "water").reduce((a, i) => a + i.qty * i.gal, 0);
    const kcal = data.items.filter(i => i.cat === "food").reduce((a, i) => a + i.qty * i.kcal, 0);
    const expiring = data.items.filter(i => monthsLeft(i.expires) <= 2);
    el.querySelector("#spOut").innerHTML = readout([
      [`${fmt(gallons / p, 1)} days`, `of water (${fmt(gallons, 1)} gallons)`, gallons / p < 3 ? "alert" : ""],
      [`${fmt(kcal / (p * 2000), 1)} days`, `of food (${fmt(kcal)} calories)`, kcal / (p * 2000) < 3 ? "alert" : ""],
      [String(expiring.length), "items expired or expiring within 2 months", expiring.length ? "alert" : ""],
    ]);
    const groups = {water: "Water", food: "Food", medicine: "Medicine", power: "Power and fuel", other: "Other"};
    el.querySelector("#spList").innerHTML = data.items.length ? Object.entries(groups).map(([k, label]) => {
      const list = data.items.filter(i => i.cat === k);
      return list.length ? `<h3 class="group-label">${label}</h3><div class="rows">${list.map(i => {
        const left = monthsLeft(i.expires);
        return `<div class="row-item"><div><div class="t">${esc(i.name)} <span class="tag">× ${fmt(i.qty, 2)}</span></div>
          <div class="d">${k === "water" ? `${fmt(i.qty * i.gal, 1)} gallons` : k === "food" ? `${fmt(i.qty * i.kcal)} calories` : ""}${i.expires ? `${k === "water" || k === "food" ? ", " : ""}${left < 0 ? '<span class="bad">expired</span>' : left <= 2 ? '<span class="warn">expires soon</span>' : "good until"} ${esc(i.expires)}` : ""}</div></div>
          <div class="act"><button class="btn small ghost" data-del="${esc(i.id)}">Remove</button></div></div>`;
      }).join("")}</div>` : "";
    }).join("") : '<p class="hint">Nothing listed yet. Add your water first, then food and medicines.</p>';
    const days = Math.max(1, num(el.querySelector("#spDays").value) || 14);
    const w = gallons / (p * days), f = kcal / (p * days);
    el.querySelector("#spRation").innerHTML = readout([
      [`${fmt(w, 2)} gal`, `water per person per day (${fmt(w * 3.785, 1)} liters)`, w < .5 ? "alert" : ""],
      [`${fmt(f)} cal`, "food per person per day", f < 1200 ? "alert" : ""],
    ]) + (w < .5 ? '<p class="callout"><b>Not enough water to last.</b> Below about half a gallon (2 liters) a day, people weaken quickly, sooner in heat. Find more water now (the Water card lists hidden sources) and treat it.</p>' : "")
      + (f < 1200 && f > 0 ? '<p class="callout"><b>Food is tight.</b> Adults can get by on less for a while if they have water and rest, but children, pregnant women and the sick come first. Ration early and evenly rather than running out.</p>' : "");
  }
  el.querySelector("#spCat").addEventListener("change", what);
  el.querySelector("#spPeople").addEventListener("input", e => { data.people = Math.max(1, Math.round(num(e.target.value) || 1)); render(); save(); });
  el.querySelector("#spDays").addEventListener("input", render);
  el.querySelector("#spAdd").addEventListener("click", () => {
    const cat = el.querySelector("#spCat").value, qty = num(el.querySelector("#spQty").value);
    if (!(qty > 0)) { B.toast("Enter how many"); return; }
    const item = {id: Math.random().toString(36).slice(2, 10), cat, qty, unit: "", kcal: 0, gal: 0, expires: el.querySelector("#spExp").value, name: ""};
    if (cat === "water") {
      const u = WATER_UNITS.find(x => x[0] === el.querySelector("#spUnit").value);
      Object.assign(item, {name: `Water, ${u[1]}`, unit: u[0], gal: u[2]});
    } else if (cat === "food" && el.querySelector("#spFood").value !== "custom") {
      const f = FOODS[+el.querySelector("#spFood").value];
      Object.assign(item, {name: f[0], kcal: f[1]});
    } else {
      item.name = (el.querySelector("#spName")?.value || "").trim();
      if (!item.name) { B.toast("Name it first"); return; }
      if (cat === "food") item.kcal = num(el.querySelector("#spKcal").value) || 0;
    }
    data.items.push(item); render(); save();
    B.toast("Added " + item.name);
  });
  el.querySelector("#spList").addEventListener("click", e => {
    const d = e.target.closest("[data-del]");
    if (!d) return;
    data.items = data.items.filter(i => i.id !== d.dataset.del); render(); save();
  });
  what();
  B.api("/api/supplies").then(d => { data = d; el.querySelector("#spPeople").value = d.people; render(); }).catch(() => render());
  return () => clearTimeout(timer);
}

/* ---------------------------------------------------------------- radio channels and calling for help */
const FRS = [["1", "462.5625"], ["2", "462.5875"], ["3", "462.6125"], ["4", "462.6375"], ["5", "462.6625"], ["6", "462.6875"], ["7", "462.7125"],
  ["8", "467.5625"], ["9", "467.5875"], ["10", "467.6125"], ["11", "467.6375"], ["12", "467.6625"], ["13", "467.6875"], ["14", "467.7125"],
  ["15", "462.5500"], ["16", "462.5750"], ["17", "462.6000"], ["18", "462.6250"], ["19", "462.6500"], ["20", "462.6750"], ["21", "462.7000"], ["22", "462.7250"]];
const PMR = Array.from({length: 16}, (_, i) => [String(i + 1), (446.00625 + i * .0125).toFixed(5)]);
const NATO = {A: "Alfa", B: "Bravo", C: "Charlie", D: "Delta", E: "Echo", F: "Foxtrot", G: "Golf", H: "Hotel", I: "India", J: "Juliett",
  K: "Kilo", L: "Lima", M: "Mike", N: "November", O: "Oscar", P: "Papa", Q: "Quebec", R: "Romeo", S: "Sierra", T: "Tango", U: "Uniform",
  V: "Victor", W: "Whiskey", X: "X-ray", Y: "Yankee", Z: "Zulu", 0: "Zero", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
  6: "Six", 7: "Seven", 8: "Eight", 9: "Niner"};
const chanGrid = (rows, hi = []) => `<div class="chan-grid">${rows.map(([c, f]) => `<div class="${hi.includes(c) ? "hi" : ""}"><b>${c}</b><span>${f}</span></div>`).join("")}</div>`;
const chanTable = rows => `<table class="chan"><tr><th>Channel</th><th>MHz</th><th>Use</th></tr>${rows.map(([c, f, use, hi]) =>
  `<tr class="${hi ? "hi" : ""}"><td>${c}</td><td class="f">${f}</td><td>${use}</td></tr>`).join("")}</table>`;
const notes = list => `<ul class="tool-notes">${list.map(n => `<li>${n}</li>`).join("")}</ul>`;
const RADIO = {
  walkie: () => `<h3 class="group-label">FRS and GMRS: the walkie-talkies sold in stores</h3>${chanGrid(FRS, ["20"])}
    ${notes([
      "<b>Channel 20</b> (462.675 MHz) is widely used for emergencies and travelers, and any FRS radio can reach it.",
      "<b>Privacy codes don't make a channel private.</b> They only hide other people's talk from you. Set the code to 0 or off to hear everyone, especially in an emergency.",
      "FRS needs no license, up to 2 watts. Channels 8 to 14 are limited to half a watt, so they reach the least far.",
      "GMRS radios can use up to 50 watts on channels 15 to 22, and repeaters that carry them across a city. They need an FCC license: no exam, and one license covers your family.",
      "Expect a mile or two in town and in trees, much more from a hilltop. Height beats power."])}
    <h3 class="group-label">MURS: no license, VHF</h3>${chanTable([["1", "151.820", ""], ["2", "151.880", ""], ["3", "151.940", ""], ["4", "154.570", "Blue Dot"], ["5", "154.600", "Green Dot"]])}
    ${notes(["Up to 2 watts. VHF carries better than FRS through woods and rolling country, and the channels are quieter."])}`,
  cb: () => chanTable([["9", "27.065", "Emergencies and traveler help", true], ["19", "27.185", "Highway and trucker channel: road conditions, relays"]])
    + notes(["No license needed. 40 channels on 27 MHz; most car and truck CBs use AM.",
      "Fewer people listen on channel 9 than they used to, so try 19 too: truckers can relay a call for help.",
      "A CB with a good antenna on a vehicle reaches several miles; handhelds much less."]),
  marine: () => chanTable([["16", "156.800", "Distress, safety and calling. The Coast Guard listens.", true], ["9", "156.450", "Boaters' calling channel (US)"],
      ["22A", "157.100", "Coast Guard safety broadcasts. They announce them on 16."], ["13", "156.650", "Ship to ship, about navigation"], ["70", "156.525", "Digital distress calls only (DSC), no voice"]])
    + notes(["A radio with DSC has a red distress button. With a GPS and a registered number (MMSI), one press sends who you are and where.",
      "Marine radios are for use on the water. In a real emergency, calling for help on 16 is what it's for.",
      "Handheld range is about 5 miles boat to boat, farther to a tall Coast Guard antenna."]),
  ham: () => chanTable([["2 m", "146.520", "National calling frequency (FM, simplex)", true], ["2 m", "146.550", "Common simplex chat frequency"],
      ["70 cm", "446.000", "National calling frequency (FM, simplex)"], ["Europe", "145.500 / 433.500", "Calling frequencies in Europe"]])
    + notes(["Listening is legal for anyone. Talking needs an amateur license (the Technician exam covers handhelds and local repeaters).",
      "Repeaters carry a handheld across a whole metro area. Look up your local ones now (frequency, offset and tone) and write them down.",
      "Many areas hold weekly emergency nets (ARES, RACES): listen in to learn who's out there.",
      "The amateur rules let a station in distress use any means it has to get help (47 CFR 97.405)."]),
  listen: () => chanTable([["WX 1 to 7", "162.400 to 162.550", "NOAA Weather Radio: official alerts around the clock", true],
      ["AM / FM", "Local stations", "Emergency Alert System broadcasts. A car radio works when phones don't."]])
    + notes(["AM carries much farther at night than by day.", "A hand-crank AM/FM/weather radio is the most useful single radio to own.",
      "A scanner hears fire, ambulance and aviation radio where they aren't encrypted."]),
  europe: () => `<h3 class="group-label">PMR446: Europe's licence-free walkie-talkies</h3>${chanGrid(PMR)}
    ${notes(["No licence, half a watt, 16 channels. There's no official emergency channel: agree on one with your group in advance.",
      "CB channel 9 is the emergency channel across most of Europe; 19 is the road channel in many countries.",
      "Ham calling frequencies: 145.500 MHz (2 m) and 433.500 MHz (70 cm). Marine channel 16 is the same everywhere.",
      "Phones: 112 reaches emergency services anywhere in Europe."])}`,
};
function radioTool(el, opt = {}) {
  let tab = B.store.get("beacon-radiotab") || "walkie", urg = "mayday";
  el.innerHTML = `
    ${readout([["Ch 20", "Walkie-talkies (FRS and GMRS), 462.675 MHz"], ["Ch 9", "CB emergency, 27.065 MHz"],
      ["Ch 19", "CB highway, 27.185 MHz: truckers can relay"], ["Ch 16", "Marine distress, 156.800 MHz"],
      ["146.520", "Ham calling, MHz"], ["WX 1 to 7", "NOAA weather, 162.400 to 162.550 MHz"]], "cols-3")}
    ${B.segHTML("rtab", [["walkie", "Walkie-talkies"], ["cb", "CB"], ["marine", "Marine"], ["ham", "Ham"], ["listen", "Listen"], ["europe", "Europe"]], tab)}
    <div id="rBody"></div>
    <h3 class="group-label" id="rCall" style="margin-top:30px">Call for help</h3>
    ${B.segHTML("urg", [["mayday", "MAYDAY: a life is in danger"], ["pan", "PAN-PAN: urgent, not life-threatening"]], urg)}
    <div class="tool-form" style="margin-top:4px">
      <div><label class="field" for="rName">Who you are</label><input id="rName" autocomplete="off" placeholder="Your name or call sign"></div>
      <div><label class="field" for="rWhere">Where you are</label><input id="rWhere" autocomplete="off" placeholder="Address, landmarks or coordinates"></div>
      <div><label class="field" for="rWhat">What happened</label><input id="rWhat" autocomplete="off" placeholder="A fall; broken leg; can't walk"></div>
      <div><label class="field" for="rWho">How many people</label><input id="rWho" autocomplete="off" placeholder="3 people, 1 hurt"></div>
      <div><label class="field" for="rNeed">What you need</label><input id="rNeed" autocomplete="off" placeholder="Medical help and a carry-out"></div>
    </div>
    <div class="row" style="margin-top:10px"><button class="btn small" id="rHere" type="button">${B.icon("locate")}Use my location</button></div>
    <div class="script" id="rScript" aria-live="polite"></div>
    <div class="row"><button class="btn small" id="rSpeak" type="button">Read aloud, slowly</button><button class="btn small" id="rCopy" type="button">Copy</button></div>
    <ol class="tool-steps">
      <li>Pick the channel most likely to be heard: walkie-talkies 20, CB 9 then 19, marine 16, or a ham repeater.</li>
      <li>Listen for a few seconds so you don't talk over someone.</li>
      <li>Hold the talk button, wait a second, then speak slowly with the radio a few inches from your mouth.</li>
      <li>Let go and listen for at least a minute.</li>
      <li>No answer? Repeat every few minutes, try other channels, and get higher: a hilltop or an upper floor can double your range.</li>
      <li>Between tries, save the battery and write down everything you hear.</li>
    </ol>
    <h3 class="group-label" style="margin-top:24px">If you hear a call for help</h3>
    ${notes(["Write down who, where and what, word for word.", "Answer: say their name, then \"this is\" and yours, then \"received\". Ask them to repeat anything you missed.",
      "Pass it to 911 or 112 if you can reach them, or relay it to anyone who can help. Stay on the channel."])}
    <h3 class="group-label" style="margin-top:24px">Spell it out</h3>
    <div class="tool-form"><div><label class="field" for="rSpell">A name, call sign or street</label><input id="rSpell" autocomplete="off" placeholder="Garcia"></div></div>
    <p class="morse-out" id="rSpelled" style="font-size:1.25rem;letter-spacing:0"></p>`;
  const v = id => el.querySelector("#" + id).value.trim();
  const show = () => { el.querySelector("#rBody").innerHTML = RADIO[tab](); };
  function script() {
    const name = v("rName") || "[your name]", where = v("rWhere") || "[where you are]";
    const lines = urg === "mayday"
      ? ["MAYDAY, MAYDAY, MAYDAY.", `This is ${name}, ${name}, ${name}.`, `MAYDAY, ${name}.`]
      : ["PAN-PAN, PAN-PAN, PAN-PAN.", "All stations, all stations, all stations.", `This is ${name}, ${name}, ${name}.`];
    lines.push(`We are at ${where}.`, (v("rWhat") || "[what happened]").replace(/\.?$/, "."), (v("rWho") || "[how many people, and who is hurt]").replace(/\.?$/, "."),
      `We need ${v("rNeed") || "[what help you need]"}`.replace(/\.?$/, "."), "Over.");
    el.querySelector("#rScript").textContent = lines.join("\n");
  }
  B.wireSeg(el, "rtab", t => { tab = t; B.store.set("beacon-radiotab", t); show(); });
  B.wireSeg(el, "urg", u => { urg = u; script(); });
  el.querySelector(".tool-form").addEventListener("input", script);
  el.querySelector("#rHere").onclick = async () => {
    let p = null;
    try { const m = await B.api("/api/mesh"); p = m.state === "connected" && m.position ? m.position : null; } catch {}
    const where = p ? `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}` : B.lastPlace?.label || B.situation?.place || "";
    if (!where) { B.toast("No location yet: pick one on the Map, or type it."); return; }
    el.querySelector("#rWhere").value = where; script();
  };
  el.querySelector("#rSpeak").onclick = e => B.speak(el.querySelector("#rScript").textContent.replace(/\[[^\]]*\]/g, ""), e.currentTarget, undefined, .8);
  el.querySelector("#rCopy").onclick = () => B.copy(el.querySelector("#rScript").textContent);
  el.querySelector("#rSpell").addEventListener("input", e => {
    el.querySelector("#rSpelled").textContent = [...e.target.value.toUpperCase()].map(c => NATO[c] || (c === " " ? "/" : "")).filter(Boolean).join(" ");
  });
  show(); script();
  if (opt.call) setTimeout(() => el.querySelector("#rCall").scrollIntoView({block: "start"}), 60);
  return () => B.stopSpeaking();
}

/* ---------------------------------------------------------------- the toolbox */
const TOOLS = [
  {id: "cpr", group: "First aid", icon: "pulse", title: "CPR metronome", sub: "Keeps the beat at 110 pushes a minute", run: cprTool},
  {id: "tourniquet", group: "First aid", icon: "timer", title: "Tourniquet timer", sub: "Remembers when it went on", run: tourniquetTool},
  {id: "ors", group: "First aid", icon: "glass", title: "Rehydration drink", sub: "The WHO home recipe for any amount", run: orsTool},
  {id: "bleach", group: "Water", icon: "drops", title: "Bleach for drinking water", sub: "Drops for any amount, plus a timer", run: bleachTool},
  {id: "water", group: "Water", icon: "jug", title: "Water to store", sub: "For your people and your days", run: waterTool},
  {id: "supplies", group: "Supplies and power", icon: "boxes", title: "Supplies", sub: "What you have, and how many days it lasts", run: suppliesTool, host: true},
  {id: "power", group: "Supplies and power", icon: "power", title: "Power budget", sub: "Batteries, solar and what they can run", run: powerTool},
  {id: "light", group: "Signals", icon: "flashlight", title: "Flashlight and SOS", sub: "Turns the screen into a light", run: null},
  {id: "morse", group: "Signals", icon: "morse", title: "Morse code", sub: "Translate it, flash it, sound it", run: morseTool},
  {id: "radio", group: "Signals", icon: "radio", title: "Radio channels", sub: "Who's listening where, and how to call for help", run: radioTool},
  {id: "weather", group: "Weather and sky", icon: "thermo", title: "Heat and cold", sub: "Heat index and frostbite risk", run: heatColdTool},
  {id: "lightning", group: "Weather and sky", icon: "bolt", title: "Lightning distance", sub: "Count from flash to thunder", run: lightningTool},
  {id: "sun", group: "Weather and sky", icon: "moon", title: "Sun and moon", sub: "Daylight, directions, moonlight", run: sunTool},
  {id: "translate", group: "Words and numbers", icon: "translate", title: "Translate", sub: "Say it in another language, out loud", run: translateTool},
  {id: "units", group: "Words and numbers", icon: "ruler", title: "Convert units", sub: "Distance, weight, volume, temperature", run: unitsTool},
];
let active = null;  // {container, cleanup}
function mount(id, container, opt = {}) {
  const t = TOOLS.find(x => x.id === id);
  if (!t) return;
  if (!t.run) { lightOn("white"); return; }
  unmount();
  container.innerHTML = `${opt.compact ? `<h2>${esc(t.title)}</h2><p class="sub hint">${esc(t.sub)}</p>` : ""}<div class="tool-body"></div>`;
  const body = container.querySelector(".tool-body");
  let cleanup = null;
  try { cleanup = t.run(body, opt) || null; } catch (e) { body.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  B.hydrateIcons(container);
  active = {container, cleanup, id};
}
function unmount(container) {
  if (!active || (container && active.container !== container)) return;
  try { active.cleanup?.(); } catch {}
  const was = active; active = null;
  if (was.container === $("toolView") && !$("toolView").hidden) showIndex();
}
B.tools = {mount, unmount, list: TOOLS};

const groups = [...new Set(TOOLS.map(t => t.group))];
$("toolGroups").innerHTML = groups.map(g => `<div class="tool-group"><h3>${esc(g)}</h3><div class="index">${TOOLS.filter(t => t.group === g).map(t =>
  `<button class="index-row ${t.host ? "admin" : ""}" data-tool="${t.id}">${B.icon(t.icon)}<span><b>${esc(t.title)}</b><span class="sub">${esc(t.sub)}</span></span></button>`).join("")}</div></div>`).join("");
function showIndex() {
  $("toolView").hidden = true; $("toolIndex").hidden = false;
}
function openTool(id) {
  const t = TOOLS.find(x => x.id === id);
  if (!t) return;
  if (!t.run) { lightOn("white"); return; }
  $("toolIndex").hidden = true; $("toolView").hidden = false;
  $("toolView").innerHTML = `<button class="btn small ghost back" id="toolBack" data-icon="back">All tools</button>
    <div class="row" style="align-items:flex-start;justify-content:space-between"><h2>${esc(t.title)}</h2><button class="btn small ghost" id="toolPrint" data-icon="print">Print</button></div>
    <p class="sub">${esc(t.sub)}</p><div id="toolMount"></div>`;
  B.hydrateIcons($("toolView"));
  $("toolBack").onclick = () => { unmount(); showIndex(); };
  $("toolPrint").onclick = () => B.printAs("tool", t.title);
  mount(id, $("toolMount"));
  active.container = $("toolView");
  $("toolsPane").scrollTop = 0; $("tab-tools").scrollTop = 0;
}
B.openTool = id => { B.showTab("tools"); openTool(id); };
$("toolGroups").addEventListener("click", e => { const b = e.target.closest("[data-tool]"); if (b) openTool(b.dataset.tool); });
})();
