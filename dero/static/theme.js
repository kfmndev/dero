// Theme: follows the browser's light/dark preference until the toggle is
// clicked. The toggle (sun left, moon right) switches to the other theme and remembers it; switching
// back to what the browser prefers forgets the override again.
// Loaded in <head> so a saved choice applies before the page is drawn.
(function () {
  const KEY = "theme";
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;

  const system = () => (media.matches ? "dark" : "light");

  function saved() {
    try {
      const v = localStorage.getItem(KEY);
      return v === "light" || v === "dark" ? v : null;
    } catch {
      return null;
    }
  }

  const current = () => saved() || system();

  function apply() {
    const override = saved();
    if (override) root.setAttribute("data-theme", override);
    else root.removeAttribute("data-theme");

    const button = document.getElementById("theme-toggle");
    if (button) {
      const dark = current() === "dark";
      // only for assistive technology: the look comes from the theme tokens in the stylesheet, so the knob
      // is already in place on the first paint and does not slide on reload
      button.setAttribute("aria-checked", String(dark));
      button.title = `Switch to ${dark ? "light" : "dark"} mode`;
    }
  }

  function toggle() {
    const next = current() === "dark" ? "light" : "dark";
    try {
      if (next === system()) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {}
    apply();
  }

  apply();
  media.addEventListener("change", apply);
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("theme-toggle").addEventListener("click", toggle);
    apply();
  });
})();
