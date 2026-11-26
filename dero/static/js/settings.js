// ---- Settings dialog (opens from the user name): colour slugs, live visits, explicit search terms ----
(() => {
  const dialog = document.getElementById("settings"),
    open = document.getElementById("settings-open");
  if (dialog && open && typeof dialog.showModal === "function") {
    open.addEventListener("click", () => dialog.showModal());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    }); // a click outside closes it
  }
  const liveSwitch = document.getElementById("live-switch");
  if (liveSwitch) {
    try {
      liveSwitch.checked = localStorage.getItem("dero.live") === "1";
    } catch {}
    liveSwitch.addEventListener("change", () => {
      try {
        localStorage.setItem("dero.live", liveSwitch.checked ? "1" : "0");
      } catch {}
      document.dispatchEvent(new Event("dero:live"));
    });
  }
  const explicitSwitch = document.getElementById("explicit-switch");
  if (explicitSwitch) {
    try {
      explicitSwitch.checked = localStorage.getItem("dero.explicit") === "1";
    } catch {}
    explicitSwitch.addEventListener("change", () => {
      try {
        localStorage.setItem("dero.explicit", explicitSwitch.checked ? "1" : "0");
      } catch {}
    }); // read by filters.js whenever a dropdown is used
  }
  const toggle = document.getElementById("hl-switch");
  if (!toggle) return;
  toggle.addEventListener("change", () => {
    document.documentElement.dataset.hl = toggle.checked ? "on" : "off";
    document.cookie = `dero_hl=${toggle.checked ? 1 : 0}; path=/; max-age=31536000; SameSite=Lax`;
  });
})();
