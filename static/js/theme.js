/* Apply this device's theme and text size before the first paint (kept in a file so the
   page can forbid inline scripts). */
try {
  var t = localStorage.getItem("beacon-theme"), s = localStorage.getItem("beacon-size");
  if (t) document.documentElement.dataset.theme = t;
  if (s) document.documentElement.dataset.size = s;
} catch (e) {}
