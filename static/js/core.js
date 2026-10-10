/* Beacon UI core: helpers every tab uses. Loads first; the other scripts build on window.B. */
"use strict";

const B = window.B = {};
const $ = id => document.getElementById(id);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const enc = p => String(p).split("/").map(encodeURIComponent).join("/");
const fmtBytes = b => !(b > 0) ? "" : b >= 1024 ** 3 ? (b / 1024 ** 3).toFixed(1) + " GB" : Math.max(1, Math.round(b / 1024 ** 2)) + " MB";
const store = {  // per-device conveniences only; everything important lives on the drive
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};
const session = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch {} },
};
Object.assign(B, {$, $$, esc, enc, fmtBytes, store, session});

/* ---------------------------------------------------------------- icons */
const ICONS = {
  home: '<path d="M4 11 12 4l8 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>',
  house: '<path d="M4 11 12 4l8 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>',
  plan: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h6M9 18h3"/>',
  map: '<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6z"/><path d="M9 4v14M15 6v14"/>',
  tools: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M9 8V5.5h6V8M3 13h18M10 13v2h4v-2"/>',
  books: '<path d="M5 4h3.5v16H5zM10.5 4H14v16h-3.5z"/><path d="m16 5.2 3.3-.9 3.2 15.2-3.3.8z"/>',
  wifi: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.6 16a5 5 0 0 1 6.8 0"/><circle cx="12" cy="19.2" r="1" fill="currentColor"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  print: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="8" rx="2"/><path d="M7 14h10v6H7z"/>',
  locate: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/>',
  card: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
  book: '<path d="M4 5.5C6.5 4.5 9.5 4.5 12 6c2.5-1.5 5.5-1.5 8-.5V19c-2.5-1-5.5-1-8 .5-2.5-1.5-5.5-1.5-8-.5z"/><path d="M12 6v13.5"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  drop: '<path d="M12 3.5c3.2 4 5.5 7.2 5.5 10.2a5.5 5.5 0 0 1-11 0C6.5 10.7 8.8 7.5 12 3.5z"/>',
  pulse: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
  tornado: '<path d="M3.5 5h17M5.5 9h13M8 13h8M10 17h4.5M11.5 21h2"/>',
  snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5 12 6l2.5-1.5M9.5 19.5 12 18l2.5 1.5"/>',
  water: '<path d="M12 3.5c3.2 4 5.5 7.2 5.5 10.2a5.5 5.5 0 0 1-11 0C6.5 10.7 8.8 7.5 12 3.5z"/><path d="M9.2 14.6c.9.8 1.9.8 2.8 0s1.9-.8 2.8 0"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  compass: '<circle cx="12" cy="12" r="8.5"/><path d="m15 9-2 4-4 2 2-4z"/>',
  car: '<path d="M4 16.5V13l2.2-5h11.6L20 13v3.5"/><path d="M3.5 13h17"/><circle cx="7.5" cy="16.5" r="1.6"/><circle cx="16.5" cy="16.5" r="1.6"/><path d="M9.5 16.5h5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  shield: '<path d="M12 3 5 6v5.5c0 4.3 3 7.7 7 9.5 4-1.8 7-5.2 7-9.5V6z"/>',
  eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 6.1A9 9 0 0 1 12 6c5 0 8.5 4.5 9.5 6-.5.8-1.4 2.1-2.8 3.3M6.4 7.6C4.6 8.9 3.2 10.8 2.5 12c1 1.5 4.5 6 9.5 6a9.3 9.3 0 0 0 4.3-1.1"/><path d="M9.9 10a3 3 0 0 0 4.2 4.2"/>',
  breath: '<path d="M3 9h10.5a3 3 0 1 0-3-3"/><path d="M3 13h14.5a3 3 0 1 1-3 3"/><path d="M3 17h6"/>',
  signal: '<circle cx="12" cy="10" r="1.8"/><path d="M12 12v9M8.3 6.4a5.2 5.2 0 0 0 0 7.2M15.7 6.4a5.2 5.2 0 0 1 0 7.2M5.4 3.8a9 9 0 0 0 0 12.4M18.6 3.8a9 9 0 0 1 0 12.4"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.5 3.4 5.4 3.4 8.5s-1 6-3.4 8.5c-2.4-2.5-3.4-5.4-3.4-8.5s1-6 3.4-8.5z"/>',
  waves: '<path d="M3 8.5c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0 3 1.3 4.5 0M3 13c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0 3 1.3 4.5 0M3 17.5c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0 3 1.3 4.5 0"/>',
  route: '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h7.5a3 3 0 0 0 0-6h-7a3 3 0 0 1 0-6H16"/>',
  can: '<ellipse cx="12" cy="6" rx="6" ry="2.5"/><path d="M6 6v12c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V6"/><path d="M6 12c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5"/>',
  sprout: '<path d="M12 21v-9"/><path d="M12 12c0-4-3-6.5-7-6.5 0 4 3 6.5 7 6.5zM12 14.5c0-3.6 2.6-6 6.5-6 0 3.6-2.6 6-6.5 6z"/>',
  tent: '<path d="M3 20h18"/><path d="M5 20 12 7l7 13"/><path d="M10 20l2-4 2 4"/><path d="M10.5 4.5 12 7l1.5-2.5"/>',
  mind: '<circle cx="12" cy="6.5" r="2.5"/><path d="M5 19.5c1.6-4 4-6 7-6s5.4 2 7 6"/><path d="M4 14.5c2 .4 3.4 1.4 4.4 3M20 14.5c-2 .4-3.4 1.4-4.4 3"/>',
  bolt: '<path d="M13 2.5 5 13.5h6l-1 8 8-11h-6z"/>',
  flashlight: '<path d="M8.5 3h7v4l-1.8 3v11h-3.4V10L8.5 7z"/><path d="M12 13.5v2"/>',
  timer: '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 1.5M9.5 2.5h5M12 2.5V6"/>',
  morse: '<circle cx="4.5" cy="12" r="1.5" fill="currentColor"/><path d="M8.5 12h6"/><circle cx="19" cy="12" r="1.5" fill="currentColor"/>',
  thermo: '<path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7.5"/>',
  moon: '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
  translate: '<path d="M4 5h8M8 3v2M5.5 5c.5 3 2.4 5.5 5.5 7M10.5 5c-.5 3-2.4 5.5-5.5 7"/><path d="M13 21l3.5-9 3.5 9M14.3 18h4.4"/>',
  ruler: '<path d="M3 16.5 16.5 3 21 7.5 7.5 21z"/><path d="M7 12.5l2 2M10 9.5l2 2M13 6.5l2 2"/>',
  jug: '<path d="M8.5 3h7v3l2 3v11a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1V9l2-3z"/><path d="M8.5 6h7M9 13h6"/>',
  drops: '<path d="M8 10c1.8 2.2 3 3.9 3 5.5a3 3 0 0 1-6 0c0-1.6 1.2-3.3 3-5.5zM16 3c1.8 2.2 3 3.9 3 5.5a3 3 0 0 1-6 0C13 6.9 14.2 5.2 16 3z"/>',
  glass: '<path d="M6 4h12l-1.6 15.2a1 1 0 0 1-1 .8H8.6a1 1 0 0 1-1-.8z"/><path d="M6.6 9.5h10.8"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  board: '<path d="M4 5h16v11h-9l-5 4v-4H4z"/><path d="M8 9h8M8 12h5"/>',
  radio: '<rect x="6" y="8" width="12" height="13" rx="2"/><path d="M9 8 15 3M9 13h6M9 16.5h6"/>',
  power: '<rect x="3" y="7" width="16" height="10" rx="2"/><path d="M21 10.5v3M11.5 9.5 9 12.5h3.5L10 15"/>',
  boxes: '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>',
};
function icon(name, cls = "") {
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
B.icon = icon;
function hydrateIcons(root = document) {
  $$("[data-icon]", root).forEach(el => { if (!el.querySelector(":scope > svg.ic")) el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon)); });
}
B.hydrateIcons = hydrateIcons;

/* ---------------------------------------------------------------- talking to the drive */
const JSON_HEADERS = {"Content-Type": "application/json", "X-Beacon": "1"};  // Beacon refuses actions without this header (CSRF)
B.joinLost = () => { location.href = "/"; };  // a guest's code expired: the server shows the join page
async function api(url, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(url, opt); } catch { throw new Error("Can't reach Beacon. Is it still running?"); }
  if (r.status === 401) { B.joinLost(); throw new Error("Enter the Beacon code first."); }
  let data = null;
  try { data = await r.json(); } catch {}
  if (!r.ok) throw new Error((data && data.error) || `Beacon couldn't do that (error ${r.status}).`);
  return data;
}
B.api = api;

/* Server-sent events from /api/ask, /api/plan and /api/translate. */
function stripThink(t) {
  return t.replace(/<think>[\s\S]*?(<\/think>|$)/g, "").trim();
}
B.stripThink = stripThink;
async function stream(url, body, h = {}) {
  let text = "", sources = [], model = "";
  try {
    const res = await fetch(url, {method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body), signal: h.signal});
    if (res.status === 401) { B.joinLost(); return {text: "", sources, model}; }
    if (!res.ok || !res.body) throw new Error("bad response");
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2);
        const kind = (raw.match(/^event: (.*)$/m) || [])[1];
        let data = null;
        try { data = JSON.parse((raw.match(/^data: (.*)$/m) || [])[1] ?? "null"); } catch {}
        if (kind === "status") h.onStatus?.(data);
        else if (kind === "sources") { sources = data || []; h.onSources?.(sources); }
        else if (kind === "token") { text += data; h.onToken?.(text, sources); }
        else if (kind === "error") h.onError?.(data);
        else if (kind === "card") h.onCard?.(data);
        else if (kind === "saved") h.onSaved?.(data);
        else if (kind === "done") model = data || "";
      }
    }
  } catch (e) {
    if (e.name === "AbortError") h.onAbort?.();
    else h.onError?.("Lost the connection to Beacon. Make sure it's still running, then try again.");
  }
  return {text: stripThink(text), sources, model};
}
B.stream = stream;

/* ---------------------------------------------------------------- markdown (escape first, then format) */
function sourceLink(s) {
  if (s.kind === "kiwix") return "/read/kiwix/" + enc(s.ref);
  if (s.kind === "zimpdf") return "/read/kiwix/" + enc(s.ref) + (s.page ? "#page=" + s.page : "");
  const [file, page] = String(s.ref || "").split("#");
  return "/read/manual/" + enc(file) + (page ? "#" + page : "");
}
B.sourceLink = sourceLink;
function md(src, sources = []) {
  const inline = t => t
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/\[(\d{1,2})\]/g, (m, n) => {
      const s = sources[n - 1];
      return s ? `<a class="cite" href="${esc(sourceLink(s))}" target="_blank" rel="noopener" title="${esc(s.book + ": " + s.title)}">${n}</a>` : m;
    });
  const out = [];
  let para = [], list = null, table = [], code = null, quote = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join("<br>"))}</p>`); para = []; }
    if (list) { out.push(`<${list.tag}>` + list.items.map(i => `<li>${inline(i)}</li>`).join("") + `</${list.tag}>`); list = null; }
    if (table.length) {
      out.push("<table>" + table.filter(r => !/^\|[\s:|-]+\|$/.test(r))
        .map(r => "<tr>" + r.slice(1, -1).split("|").map(c => `<td>${inline(c.trim())}</td>`).join("") + "</tr>").join("") + "</table>");
      table = [];
    }
    if (quote.length) { out.push(`<blockquote>${inline(quote.join("<br>"))}</blockquote>`); quote = []; }
  };
  for (const raw of esc(src).split("\n")) {
    const line = raw.trimEnd(), t = line.trim();
    if (code !== null) {
      if (t.startsWith("```")) { out.push(`<pre>${code.join("\n")}</pre>`); code = null; } else code.push(line);
      continue;
    }
    if (t.startsWith("```")) { flush(); code = []; continue; }
    if (!t) { flush(); continue; }
    const h = t.match(/^(#{1,4}) (.*)/);
    if (h) { flush(); const lvl = Math.min(h[1].length + 1, 4); out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { flush(); out.push("<hr>"); continue; }
    if (t.startsWith("&gt; ") || t === "&gt;") { if (para.length || list || table.length) flush(); quote.push(t.replace(/^&gt; ?/, "")); continue; }
    if (/^\|.*\|$/.test(t)) { if (para.length || list || quote.length) flush(); table.push(t); continue; }
    const ul = t.match(/^[-*•] (.*)/), ol = t.match(/^\d+[.)] (.*)/);
    if (ul || ol) {
      const tag = ul ? "ul" : "ol";
      if (para.length || table.length || quote.length || (list && list.tag !== tag && !/^\s{2,}/.test(raw))) flush();
      if (!list) list = {tag, items: []};
      list.items.push((ul || ol)[1]);
      continue;
    }
    if (list && /^\s{2,}/.test(raw)) { list.items[list.items.length - 1] += " " + t; continue; }  // wrapped list line
    if (list || table.length || quote.length) flush();
    para.push(t);
  }
  if (code !== null) out.push(`<pre>${code.join("\n")}</pre>`);
  flush();
  return out.join("");
}
B.md = md;
function sourcesHTML(sources) {
  if (!sources || !sources.length) return "";
  return `<div class="sources"><h3>Sources</h3><ol class="src">${sources.map(s =>
    `<li><a href="${esc(sourceLink(s))}" target="_blank" rel="noopener">${esc(s.book)}</a>${s.title && s.title !== s.book ? `, ${esc(s.title)}` : ""}</li>`).join("")}</ol></div>`;
}
B.sourcesHTML = sourcesHTML;
B.thinking = label => `<div class="thinking"><i></i><span>${esc(label)}</span></div>`;

/* ---------------------------------------------------------------- feedback, sheets, speech */
let toastTimer;
function toast(msg, ms = 2800, alert = false) {
  const t = $("toast");
  t.textContent = msg; t.classList.add("on"); t.classList.toggle("alert", alert);
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), ms);
}
B.toast = toast;

let sheetOnClose = null, sheetReturn = null;
function openSheet(html, onClose, opts = {}) {
  if (!$("sheet").hidden) closeSheet();
  $("sheet").classList.toggle("wide", !!opts.wide);
  sheetReturn = document.activeElement;
  $("sheetIn").innerHTML = `<button class="icon-btn sheet-x" data-close aria-label="Close">${icon("close")}</button>${html}`;
  $("scrim").hidden = false; $("sheet").hidden = false;
  $("sheet").classList.remove("open"); void $("sheet").offsetWidth; $("sheet").classList.add("open");
  $("sheet").scrollTop = 0; $("sheet").focus();
  sheetOnClose = onClose || null;
  hydrateIcons($("sheetIn"));
  return $("sheetIn");
}
function closeSheet() {
  if ($("sheet").hidden) return;
  $("sheet").hidden = true; $("scrim").hidden = true;
  const f = sheetOnClose; sheetOnClose = null;
  try { f?.(); } catch {}
  try { sheetReturn?.focus?.(); } catch {}
}
Object.assign(B, {openSheet, closeSheet});

let speakingBtn = null;
function speak(text, btn, lang) {
  if (!("speechSynthesis" in window)) { toast("This browser can't read aloud."); return; }
  const wasMine = speakingBtn === btn && speechSynthesis.speaking;
  speechSynthesis.cancel(); resetSpeakBtn();
  if (wasMine) return;
  const clean = String(text).replace(/<[^>]+>/g, " ").replace(/\[(\d+)\]/g, "").replace(/[#*`|>_]/g, " ").replace(/\s+/g, " ").trim();
  const u = new SpeechSynthesisUtterance(clean);
  if (lang) {
    u.lang = lang;
    const v = speechSynthesis.getVoices().find(v => v.lang.toLowerCase().startsWith(lang.toLowerCase()));
    if (v) u.voice = v;
  }
  u.onend = u.onerror = () => { if (speakingBtn === btn) resetSpeakBtn(); };
  speechSynthesis.speak(u);
  if (btn) { speakingBtn = btn; btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = "Stop reading"; }
}
function resetSpeakBtn() { if (speakingBtn) speakingBtn.textContent = speakingBtn.dataset.label || "Read aloud"; speakingBtn = null; }
function stopSpeaking() { try { speechSynthesis.cancel(); } catch {} resetSpeakBtn(); }
Object.assign(B, {speak, stopSpeaking});

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); return; } catch {}
  const ta = document.createElement("textarea");  // phones on the Wi-Fi link have no clipboard API
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;top:0;opacity:0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); toast("Copied"); } catch { toast("This device didn't allow copying."); }
  ta.remove();
}
B.copy = copy;

/* ---------------------------------------------------------------- saving and printing */
const safeName = s => String(s).replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "Beacon";
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  toast("Saved " + name);
}
B.download = download;
const SAVE_CSS = `body{font:17px/1.6 Charter,"Iowan Old Style",Georgia,serif;color:#111;background:#fff;max-width:720px;margin:0 auto;padding:28px 20px 60px}
h1,h2,h3,h4{font-family:"DIN Alternate",-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.2}h1{font-size:28px;margin:0 0 4px}
.meta{color:#555;font-size:14px;margin:0 0 24px}h2.q{font-size:22px;margin:32px 0 10px}table{border-collapse:collapse;margin:8px 0 16px}
td,th{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}sup{color:#A63A0C;font-weight:700;font-size:11px}
.sources{border-top:1px dashed #bbb;margin-top:16px;padding-top:8px;font-size:14px;color:#444}.sources h3{font-size:14px;margin:0 0 4px}
blockquote{margin:0;padding-left:12px;border-left:3px solid #A63A0C;color:#444}pre{white-space:pre-wrap;font:inherit}
footer{margin-top:36px;font-size:13px;color:#666;border-top:1px solid #ccc;padding-top:8px}`;
function portable(el) {  // a copy of an answer that reads well as a saved file: no buttons, no dead links
  const c = el.cloneNode(true);
  c.querySelectorAll(".noprint, button, .thinking, .cardnote").forEach(n => n.remove());
  c.querySelectorAll("a.cite").forEach(a => { const s = document.createElement("sup"); s.textContent = a.textContent; a.replaceWith(s); });
  c.querySelectorAll("a").forEach(a => { const s = document.createElement("span"); s.textContent = a.textContent; a.replaceWith(s); });
  return c.innerHTML;
}
function saveHTML(title, bodyHTML) {
  const when = new Date().toLocaleString();
  const doc = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)}</title><style>${SAVE_CSS}</style></head><body><h1>${esc(title)}</h1><p class="meta">Saved from Beacon, ${esc(when)}</p>${bodyHTML}<footer>Made offline by Beacon. Check critical steps against the sources listed, and get trained help when you can.</footer></body></html>`;
  download(new Blob([doc], {type: "text/html"}), safeName("Beacon - " + title) + ".html");
}
Object.assign(B, {portable, saveHTML, safeName});

/* PDFs are made by Beacon itself (no internet, no print dialog), so a phone can save or AirDrop them. */
async function savePDF(title, markdown, sources = [], meta = "") {
  try {
    const r = await fetch("/api/pdf", {method: "POST", headers: JSON_HEADERS, body: JSON.stringify({title, markdown, sources, meta})});
    if (r.status === 401) return B.joinLost();
    if (!r.ok) throw new Error("pdf");
    download(await r.blob(), safeName("Beacon - " + title) + ".pdf");
  } catch { toast("Couldn't make the PDF. Is Beacon still running?"); }
}
B.savePDF = savePDF;
B.today = () => new Date().toLocaleDateString(undefined, {year: "numeric", month: "long", day: "numeric"});

/* The archive: plans and answers kept on the drive. */
async function archiveSave(kind, title, markdown, sources = [], meta = {}) {
  const r = await api("/api/archive", {kind, title, markdown, sources, meta});
  toast(B.sys?.guest ? "Shared on Beacon. Everyone here can open it in Library." : "Saved. Find it in Library, under Saved.");
  B.onArchiveChange?.();
  return r;
}
B.archiveSave = archiveSave;
async function viewArchive(id) {
  let it;
  try { it = await api("/api/archive/" + encodeURIComponent(id)); } catch (e) { toast(e.message); return; }
  const host = !B.sys?.guest, when = new Date(it.created * 1000).toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
  const phoneUrl = B.share?.on && it.shared && B.share.ip_url ? `${B.share.ip_url}/archive/${it.id}?code=${B.share.code}` : null;
  let qr = "";
  if (phoneUrl) { try { const q = qrcode(0, "M"); q.addData(phoneUrl); q.make(); qr = q.createSvgTag({cellSize: 5, margin: 2, scalable: true}); } catch {} }
  const el = openSheet(`
    <h2>${esc(it.title)}</h2>
    <p class="sheet-note">${it.kind === "plan" ? "Plan" : "Answer"} saved ${esc(when)}${it.meta?.location ? ", for " + esc(it.meta.location) : ""}.
      ${it.shared ? "Everyone on this Beacon can open it." : "Only on this Mac."}${it.by === "guest" ? ` Shared from ${esc(it.device || "a guest")}.` : ""}</p>
    <div class="sheet-actions" style="margin-top:0">
      <a class="btn small" href="/archive/${esc(it.id)}.pdf" download>${icon("download")}Save PDF</a>
      <a class="btn small" href="/archive/${esc(it.id)}" target="_blank" rel="noopener">Open as a page</a>
      <button class="btn small" id="avSpeak">Read aloud</button>
      ${host ? `<button class="btn small" id="avShare">${it.shared ? "Stop sharing" : "Share with everyone"}</button><button class="btn small ghost" id="avDelete">Delete</button>` : ""}
    </div>
    <div class="answer" style="margin-top:22px">${md(it.markdown, it.sources)}</div>
    ${sourcesHTML(it.sources)}
    ${qr ? `<h3>Open it on a phone</h3><div class="qr">${qr}</div><p class="hint">Phones on this Wi-Fi can scan this to open it and save the PDF.</p>` : ""}`, null, {wide: true});
  el.querySelector("#avSpeak").onclick = e => speak(it.markdown, e.currentTarget);
  el.querySelector("#avShare")?.addEventListener("click", async () => {
    try { await api(`/api/archive/${it.id}/share`, {shared: !it.shared}); } catch (err) { toast(err.message); return; }
    toast(it.shared ? "Only on this Mac now" : "Shared with everyone on this Beacon");
    B.onArchiveChange?.(); viewArchive(it.id);
  });
  el.querySelector("#avDelete")?.addEventListener("click", async () => {
    if (!confirm(`Delete "${it.title}" from the drive?`)) return;
    try { await api(`/api/archive/${it.id}/delete`, {}); } catch {}
    closeSheet(); toast("Deleted"); B.onArchiveChange?.();
  });
}
B.viewArchive = viewArchive;

function printAs(kind, title) {
  document.body.dataset.print = kind;
  $("printhead").innerHTML = `<b>Beacon</b><span>${esc(title)}</span><span>${esc(new Date().toLocaleString())}</span><em>Made offline by Beacon. Check critical steps against the cited sources.</em>`;
  setTimeout(() => window.print(), 80);
}
window.addEventListener("afterprint", () => { delete document.body.dataset.print; });
B.printAs = printAs;

/* ---------------------------------------------------------------- tabs */
const TABS = ["home", "plan", "map", "board", "tools", "library"];
const tabHooks = {};
B.tabHooks = tabHooks;
function showTab(name, opts = {}) {
  if (!TABS.includes(name)) name = "home";
  $$("#tabs button").forEach(b => {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  $$("main > section.tab").forEach(s => s.classList.toggle("on", s.id === "tab-" + name));
  if (location.hash.slice(1) !== name) window.history.replaceState(null, "", "#" + name);
  B.tab = name;
  try { tabHooks[name]?.(opts); } catch (e) { console.error(e); }
}
B.showTab = showTab;
$("tabs").addEventListener("click", e => { const b = e.target.closest("button[data-tab]"); if (b) showTab(b.dataset.tab); });
document.querySelector(".brand").addEventListener("click", e => { e.preventDefault(); showTab("home"); });
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS.includes(t) && t !== B.tab) showTab(t); });

/* ---------------------------------------------------------------- place search box (map, plans, tools) */
function wireSuggest(inp, ul, onPick) {
  let timer, items = [], seq = 0, active = -1;
  async function search() {
    const q = inp.value.trim();
    if (q.length < 2) { ul.hidden = true; items = []; return; }
    const my = ++seq;
    let r;
    try { r = await api("/api/places?q=" + encodeURIComponent(q)); } catch { return; }
    if (my !== seq) return;  // a newer keystroke won
    items = r.results; active = -1;
    if (!r.available && !items.length) {
      ul.innerHTML = '<li class="none">Place names aren\'t installed yet. You can still type coordinates like 39.74, -104.99.</li>';
    } else {
      ul.innerHTML = items.map((p, i) => `<li data-i="${i}" role="option">${esc(p.label)}</li>`).join("") || '<li class="none">No match. Try a nearby town or type coordinates.</li>';
    }
    ul.hidden = false;
  }
  inp.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 150); });
  inp.addEventListener("keydown", async e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      $$("li", ul).forEach((li, i) => li.classList.toggle("on", i === active));
      return;
    }
    if (e.key === "Escape") { ul.hidden = true; return; }
    if (e.key !== "Enter") return;
    e.preventDefault(); clearTimeout(timer);
    if (active < 0) await search();  // Enter works even before the suggestions arrive
    if (items[Math.max(active, 0)]) pick(Math.max(active, 0));
  });
  ul.addEventListener("mousedown", e => e.preventDefault());  // keep focus in the box while choosing
  ul.addEventListener("click", e => { const li = e.target.closest("li[data-i]"); if (li) pick(+li.dataset.i); });
  inp.addEventListener("blur", () => setTimeout(() => { ul.hidden = true; }, 150));
  function pick(i) { const p = items[i]; inp.value = p.label; ul.hidden = true; onPick(p); }
}
B.wireSuggest = wireSuggest;

/* ---------------------------------------------------------------- theme and text size (per device) */
const THEMES = [["auto", "Auto"], ["night", "Night"], ["day", "Day"], ["red", "Red light"]];
const SIZES = [["m", "Standard"], ["l", "Large"], ["xl", "Larger"]];
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  store.set("beacon-theme", t);
  syncThemeColor();
  B.onTheme?.();
}
function setSize(s) {
  if (s === "m") delete document.documentElement.dataset.size; else document.documentElement.dataset.size = s;
  store.set("beacon-size", s);
}
function syncThemeColor() {
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg || "#0F1A24");
}
B.isLight = () => getComputedStyle(document.documentElement).colorScheme.includes("light");
window.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", () => {
  if ((document.documentElement.dataset.theme || "auto") === "auto") { syncThemeColor(); B.onTheme?.(); }
});
const segHTML = (name, opts, cur) => `<div class="seg" role="group" data-seg="${name}">${opts.map(([v, l]) =>
  `<button type="button" data-v="${v}" class="${v === cur ? "on" : ""}" aria-pressed="${v === cur}">${esc(l)}</button>`).join("")}</div>`;
B.segHTML = segHTML;
function wireSeg(root, name, onPick) {
  const seg = root.querySelector(`[data-seg="${name}"]`);
  seg?.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    seg.querySelectorAll("button").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
    onPick(b.dataset.v);
  });
}
B.wireSeg = wireSeg;

/* ---------------------------------------------------------------- status: this computer, the brain, sharing */
B.sys = null; B.share = null;
async function loadSystem() {
  try { B.sys = await api("/api/system"); } catch { B.sys = null; }
  document.body.classList.toggle("guest", !!B.sys?.guest);
  renderStatus();
  return B.sys;
}
B.loadSystem = loadSystem;
function renderStatus() {
  const s = B.sys;
  let state = "bad", text = "Beacon isn't responding", title = "";
  if (s) {
    if (s.low_power) { state = "warn"; text = "Low power"; title = "The AI is off to save battery"; }
    else if (!s.engine_up) { state = "bad"; text = B.engineWaiting ? "AI starting" : "AI is off"; title = "The AI engine isn't running"; }
    else if (!s.active_model) { state = "warn"; text = "No AI model"; title = "Download a brain in Library"; }
    else { state = "ok"; text = s.active_model; title = `${s.active_model}, ${s.profile.name.toLowerCase()} brain`; }
  }
  $("statusDot").className = "dot " + state;
  $("statusText").textContent = text;
  $("statusBtn").title = title || "This computer and its AI";
  $("statusBtn").setAttribute("aria-label", "Status: " + text);
}
async function loadShare() {
  if (!B.sys || B.sys.guest) return;
  try { B.share = await api("/api/share"); } catch { B.share = {on: false}; }
  renderShareChip();
}
B.loadShare = loadShare;
function renderShareChip() {
  const on = !!B.share?.on, unseen = B.sec.unseen || 0;
  $("shareBtn").classList.toggle("live", on && !unseen);
  $("shareBtn").classList.toggle("alerting", unseen > 0);
  $("shareText").textContent = on ? `Wi-Fi code ${B.share.code}` : "Share";
  let badge = $("shareBtn").querySelector(".badge");
  if (unseen && !badge) { badge = document.createElement("b"); badge.className = "badge"; $("shareBtn").appendChild(badge); }
  if (badge) { if (unseen) badge.textContent = unseen > 9 ? "9+" : unseen; else badge.remove(); }
  $("shareBtn").title = unseen ? `${unseen} security alert${unseen === 1 ? "" : "s"}: open to see them`
    : on ? "Beacon is shared on your Wi-Fi" : "Let phones on your Wi-Fi use Beacon";
}

/* ---------------------------------------------------------------- connections monitor */
B.sec = {last: 0, unseen: 0, started: false, timer: null};
const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
};
const who = ev => ev.ip === "127.0.0.1" || ev.ip === "::1" ? (ev.kind.startsWith("sharing") || ev.kind.startsWith("signed-out") ? "this Mac" : "a web page on this Mac") : `${ev.device}, ${ev.ip}`;
function alertBeep() {
  try {
    const a = B._audio || (B._audio = new (window.AudioContext || window.webkitAudioContext)());
    [0, .18].forEach((d, i) => {
      const o = a.createOscillator(), g = a.createGain(), t = a.currentTime + d;
      o.frequency.value = i ? 660 : 880; g.gain.setValueAtTime(.2, t); g.gain.exponentialRampToValueAtTime(.0001, t + .15);
      o.connect(g).connect(a.destination); o.start(t); o.stop(t + .16);
    });
  } catch {}
}
async function pollSecurity() {
  clearTimeout(B.sec.timer);
  if (!B.sys || B.sys.guest) return;
  let r = null;
  try { r = await api(`/api/security/events?after=${B.sec.last}`); } catch {}
  if (r) {
    const fresh = B.sec.started ? r.events : [];  // the first look only catches up quietly
    B.sec.started = true; B.sec.last = r.last; B.sec.unseen = r.unseen;
    const alerts = fresh.filter(ev => ev.level !== "info");
    if (alerts.length) {
      const ev = alerts.at(-1);
      toast(`Security: ${ev.detail} (${who(ev)})`, 7000, true);
      alertBeep();
    }
    if (B.share && r.sharing !== !!B.share.on) await loadShare();
    renderShareChip();
    if (!$("sheet").hidden && $("conn")) renderConnections();
  }
  B.sec.timer = setTimeout(pollSecurity, B.share?.on ? 4000 : 12000);
}
B.pollSecurity = pollSecurity;
async function renderConnections(devices = false) {
  const box = $("conn");
  if (!box) return;
  let r;
  try { r = await api("/api/security" + (devices ? "?devices=1" : "")); } catch { return; }
  if (!$("conn")) return;
  const lvl = l => l === "alert" ? "bad" : l === "warn" ? "warn" : "ok";
  const sessions = r.sessions || [], events = (r.events || []).slice().reverse().slice(0, 40);
  box.innerHTML = `
    <h3>Connected now</h3>
    ${sessions.length ? `<div class="rows">${sessions.map(x => `<div class="row-item"><div><div class="t">${esc(x.device)}</div>
        <div class="d">${esc(x.ip)}${x.mac ? `, hardware address ${esc(x.mac)}` : ""}. Joined ${esc(ago(x.since))}; ${x.active ? "active now" : "last active " + esc(ago(x.last))}.</div></div>
        <div class="act"><button class="btn small ghost" data-revoke="${esc(x.id)}">Sign out</button></div></div>`).join("")}</div>`
      : `<p class="hint">${r.sharing?.on ? "No one has joined yet." : "Nobody: Wi-Fi sharing is off."}</p>`}
    <h3>Recent activity</h3>
    ${events.length ? `<div class="rows log">${events.map(ev => `<div class="row-item"><div><div class="t"><i class="dot ${lvl(ev.level)}"></i> ${esc(ev.detail)}${ev.count > 1 ? ` <span class="tag">${ev.count} times</span>` : ""}</div>
        <div class="d">${esc(who(ev))}${ev.mac ? `, ${esc(ev.mac)}` : ""}. ${esc(ago(ev.last))}.</div></div></div>`).join("")}</div>`
      : `<p class="hint">Nothing yet. Sign-ins, wrong codes and anything Beacon blocks will show up here.</p>`}
    <div class="sheet-actions"><a class="btn small" href="/api/security/log.csv" download>Save the log</a><button class="btn small ghost" id="nearbyBtn">Show other devices on this network</button></div>
    <div id="nearbyDev">${r.devices ? (r.devices.length ? `<p class="hint">Devices this Mac has seen on the network recently, from its own address table. They aren't connected to Beacon unless marked. Beacon doesn't probe or scan them.</p>
      <div class="rows">${r.devices.map(d => `<div class="row-item"><div><div class="t">${esc(d.ip)}</div><div class="d">Hardware address ${esc(d.mac)}</div></div><div class="act">${d.signed_in ? '<span class="state ok">Signed in to Beacon</span>' : ""}</div></div>`).join("")}</div>`
      : '<p class="hint">This Mac hasn\'t seen other devices on the network yet.</p>') : ""}</div>`;
  box.querySelector("#nearbyBtn").onclick = () => renderConnections(true);
  box.onclick = async e => {
    const b = e.target.closest("[data-revoke]");
    if (!b) return;
    b.disabled = true;
    try { const res = await api("/api/share/revoke", {id: b.dataset.revoke}); B.share = {...B.share, ...res}; } catch {}
    toast("Signed out that device"); renderConnections();
  };
}
async function markSeen() {
  if (!B.sec.unseen) return;
  try { await api("/api/security/seen", {}); } catch {}
  B.sec.unseen = 0; renderShareChip();
}

function systemSheet(first = false) {
  const s = B.sys;
  if (!s) { openSheet(`<h2>Beacon isn't responding</h2><p class="sheet-note">If you closed it, open Beacon again from the drive.</p>`); return; }
  const theme = document.documentElement.dataset.theme || "auto", size = document.documentElement.dataset.size || "m";
  const bat = s.battery ? `${s.battery.percent}%, ${s.battery.plugged_in ? "plugged in" : "on battery"}` : "Plugged in";
  const gpu = String(s.gpu || "").split(" — ");
  const recInstalled = s.tiers?.find(t => t.model === s.recommended.model)?.installed;
  const brain = s.active_model
    ? `<div class="brain-box"><b>${esc(s.active_model)}</b><p>${esc(s.profile.name)} brain: reads up to ${s.profile.sources} sources for each answer.${s.active_model !== s.recommended.model ? ` This computer could run ${esc(s.recommended.model)}.` : " The strongest brain this computer can run."}</p></div>`
    : `<div class="brain-box"><b>No brain installed</b><p>Recommended for this computer: ${esc(s.recommended.model)} (${esc(s.recommended.label)}).</p></div>`;
  const host = s.guest ? "" : `
    <div class="specs">
      <div><span>Computer</span><b>${esc(s.chip)}</b></div>
      <div><span>Memory</span><b>${s.ram_gb} GB${s.ram_free_gb != null ? `, ${s.ram_free_gb} GB free` : ""}</b></div>
      <div><span>Graphics</span><b>${esc(gpu[0])}</b></div>
      <div><span>Drive</span><b>${s.disk_free_gb} GB free${s.drive?.encrypted === true ? ", encrypted" : s.drive?.encrypted === false ? ", not encrypted" : ""}</b></div>
      <div><span>Power</span><b>${esc(bat)}</b></div>
      <div><span>System</span><b>${esc(s.os)}</b></div>
    </div>`;
  const notes = (!s.guest && s.notes?.length) ? `<ul class="notes">${s.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
  const el = openSheet(`
    <h2>${s.guest ? "Connected to Beacon" : first ? "This computer" : "This computer"}</h2>
    <p class="sheet-note">${s.guest
      ? "You're using Beacon over the Wi-Fi. The answers come from the AI on the Beacon computer; nothing goes to the internet."
      : first ? "Beacon checked this Mac and picked the strongest AI brain it can run." : "What Beacon is running on, and how it's set up."}</p>
    ${host}${brain}${notes}
    ${!s.guest && !recInstalled && s.recommended ? `<div class="sheet-actions" style="margin-top:12px"><button class="btn" id="getBrain">Get the recommended brain</button></div>` : ""}
    <h3>Settings</h3>
    <div class="setting admin"><div><b>Low power</b><span>Turns the AI off to save battery. Cards, tools, maps and the library keep working.</span></div>
      <button class="switch" id="lowPower" role="switch" aria-checked="${!!s.low_power}" aria-label="Low power"></button></div>
    <div class="setting"><div><b>Theme</b><span>Red light keeps your night vision.</span></div>${segHTML("theme", THEMES, theme)}</div>
    <div class="setting"><div><b>Text size</b></div>${segHTML("size", SIZES, size)}</div>
    ${s.guest ? "" : `<div class="setting"><div><b>Quit Beacon</b><span>Stops Beacon and its AI so you can eject the drive safely.</span></div><button class="btn" id="quitBtn">Quit</button></div>`}
    ${first ? `<div class="sheet-actions"><button class="btn primary big" data-close>Start</button></div>` : ""}`);
  wireSeg(el, "theme", setTheme);
  wireSeg(el, "size", setSize);
  el.querySelector("#getBrain")?.addEventListener("click", () => { closeSheet(); showTab("library"); setTimeout(() => $("lib-brain")?.scrollIntoView({block: "start"}), 60); });
  el.querySelector("#lowPower")?.addEventListener("click", async e => {
    const on = e.currentTarget.getAttribute("aria-checked") !== "true";
    e.currentTarget.setAttribute("aria-checked", on);
    try { await api("/api/power", {low: on}); toast(on ? "Low power on. The AI is off." : "Low power off. The AI is back."); } catch (err) { toast(err.message); }
    loadSystem();
  });
  el.querySelector("#quitBtn")?.addEventListener("click", quitBeacon);
}
B.systemSheet = systemSheet;
async function quitBeacon() {
  const sharing = B.share?.on ? " People using it on your Wi-Fi will be disconnected." : "";
  if (!confirm("Quit Beacon?" + sharing)) return;
  try { await api("/api/quit", {}); } catch {}
  closeSheet(); stopSpeaking();
  $("stopped").hidden = false;
}

function shareSheet() {
  const sh = B.share || {on: false};
  if (!sh.on) {
    const el = openSheet(`
      <h2>Share on your Wi-Fi</h2>
      <p class="sheet-note">Let phones, tablets and other computers on the same Wi-Fi use Beacon in their web browser: ask questions, make plans, read the library and save files to the phone. It all runs on this Mac; nothing goes to the internet.</p>
      <ul class="notes">
        <li>Each person enters a 4-digit code once, or scans a QR code.</li>
        <li>Guests can't change settings, download new content, see your household info or quit Beacon.</li>
        <li>If the Mac asks whether Python may accept incoming connections, choose Allow.</li>
        <li>Keep the Mac plugged in with the lid open. Beacon stops it from dozing off while sharing is on.</li>
        <li>No Wi-Fi network? A phone's personal hotspot works too, as long as this Mac is connected to it.</li>
      </ul>
      ${sh.error ? `<p class="err" style="margin-top:14px">Couldn't start sharing: ${esc(sh.error)}</p>` : ""}
      <div class="sheet-actions"><button class="btn primary big" id="shareOn">Start sharing</button></div>
      <h2 style="margin-top:34px;font-size:1.5rem">Connections</h2><div id="conn"></div>`);
    renderConnections(); markSeen();
    el.querySelector("#shareOn").onclick = async e => {
      e.currentTarget.disabled = true; e.currentTarget.textContent = "Starting…";
      try { B.share = await api("/api/share", {on: true}); } catch (err) { B.share = {on: false, error: err.message}; }
      renderShareChip(); shareSheet();
    };
    return;
  }
  const url = sh.join_url, addr = sh.name_url || sh.ip_url;
  let qr = "";
  try { const q = qrcode(0, "M"); q.addData(url); q.make(); qr = q.createSvgTag({cellSize: 6, margin: 2, scalable: true}); } catch {}
  const el = openSheet(`
    <h2>Sharing on your Wi-Fi</h2>
    <p class="sheet-note">On a phone connected to the same Wi-Fi, open the camera and point it at this code.</p>
    ${qr ? `<div class="qr" aria-label="QR code to join Beacon">${qr}</div>` : ""}
    <h3>Or type the address</h3>
    <p class="addr">${esc((addr || "").replace(/^http:\/\//, ""))}</p>
    ${sh.name_url && sh.ip_url ? `<p class="hint">If that doesn't open, try ${esc(sh.ip_url.replace(/^http:\/\//, ""))}</p>` : ""}
    <h3>Code</h3>
    <div class="share-code" aria-label="Code ${esc(sh.code)}">${String(sh.code).split("").map(d => `<b>${esc(d)}</b>`).join("")}</div>
    ${sh.alert ? `<p class="callout">${esc(sh.alert)}</p>` : ""}
    <p class="hint">${sh.guests ? `${sh.guests} device${sh.guests === 1 ? " is" : "s are"} signed in. ` : ""}Guests can ask, plan, read and save files. They can't change settings, download new content, see your household info or quit Beacon. Wrong codes are limited, and stopping sharing signs everyone out.</p>
    <div class="sheet-actions"><button class="btn" id="copyLink">Copy link</button><button class="btn" id="signOut">Sign everyone out</button><button class="btn" id="shareOff">Stop sharing</button></div>
    <h2 style="margin-top:34px;font-size:1.5rem">Connections</h2><div id="conn"></div>`);
  renderConnections(); markSeen();
  el.querySelector("#copyLink").onclick = () => copy(url);
  el.querySelector("#signOut").onclick = async () => {
    try { B.share = await api("/api/share/signout", {}); } catch {}
    renderShareChip(); shareSheet(); toast("Everyone's signed out. The code changed.");
  };
  el.querySelector("#shareOff").onclick = async () => {
    try { B.share = await api("/api/share", {on: false}); } catch {}
    renderShareChip(); closeSheet(); toast("Stopped sharing");
  };
}
B.shareSheet = shareSheet;
$("statusBtn").addEventListener("click", () => systemSheet(false));
$("shareBtn").addEventListener("click", shareSheet);
$("scrim").addEventListener("click", closeSheet);
$("sheet").addEventListener("click", e => { if (e.target.closest("[data-close]")) closeSheet(); });
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!$("light").hidden) B.lightOff?.();
  else if (!$("sheet").hidden) closeSheet();
  else if (!$("cards").hidden) B.closeCards?.();
});

/* ---------------------------------------------------------------- contour lines behind the hero */
function drawContours() {
  const svg = $("contours");
  if (!svg) return;
  const W = 1600, H = 720;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const hills = [{x: 1250, y: 300, rings: 15, step: 31, sx: 1.4, sy: .82}, {x: 180, y: 700, rings: 9, step: 36, sx: 1.2, sy: .9}];
  let thin = "", thick = "";
  for (const h of hills) {
    const waves = Array.from({length: 5}, (_, i) => ({k: i + 2, a: (.05 + rnd() * .12) / (i * .6 + 1), p: rnd() * 6.283}));
    for (let r = 1; r <= h.rings; r++) {
      let d = "";
      for (let i = 0; i <= 140; i++) {
        const th = i / 140 * 6.283;
        let f = 1;
        for (const w of waves) f += w.a * Math.sin(w.k * th + w.p + r * .21);
        const x = h.x + Math.cos(th) * r * h.step * f * h.sx, y = h.y + Math.sin(th) * r * h.step * f * h.sy;
        d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      }
      if (r % 5 === 0) thick += d + "Z"; else thin += d + "Z";  // every fifth line is an index contour, as on a real map
    }
  }
  svg.innerHTML = `<path d="${thin}" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="${thick}" fill="none" stroke="currentColor" stroke-width="2.2"/>`;
}

/* ---------------------------------------------------------------- start */
B.boot = async function boot() {
  hydrateIcons();
  drawContours();
  syncThemeColor();
  const start = location.hash.slice(1);
  showTab(TABS.includes(start) ? start : "home");
  const s = await loadSystem();
  if (s && !s.guest) { await loadShare(); pollSecurity(); }
  if (s && !s.guest && !session.get("checked")) { session.set("checked", "1"); systemSheet(true); }
  B.afterBoot?.forEach(f => { try { f(); } catch (e) { console.error(e); } });
  // The AI engine can take a little while to start after the drive is plugged in.
  let tries = 0;
  B.engineWaiting = !!s && !s.engine_up;
  renderStatus();
  const poll = async () => {
    const was = B.sys && B.sys.engine_up && B.sys.active_model;
    await loadSystem();
    if (B.engineWaiting && (B.sys?.engine_up || ++tries > 24)) { B.engineWaiting = false; renderStatus(); }
    const now = B.sys && B.sys.engine_up && B.sys.active_model;
    if (!was && now) B.onEngineUp?.();
    setTimeout(poll, B.engineWaiting ? 5000 : 30000);
  };
  setTimeout(poll, B.engineWaiting ? 5000 : 30000);
};
B.afterBoot = [];
