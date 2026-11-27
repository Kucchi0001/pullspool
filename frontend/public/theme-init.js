// Applies the persisted (or system) theme before first paint to avoid a flash.
// Kept as an external file so the Content-Security-Policy can forbid inline
// scripts.
(function () {
  try {
    var stored = localStorage.getItem("pullspool.theme") || "system";
    var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    var theme = stored === "system" ? (prefersDark ? "dark" : "light") : stored;
    document.documentElement.dataset.theme = theme;
  } catch (error) {
    document.documentElement.dataset.theme = "light";
  }
})();
