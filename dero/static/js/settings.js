// ---- Settings dialog (opens from the user name): colour slugs, explicit search terms, leave warning; the live switch ----
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
  const leaveSwitch = document.getElementById("leave-switch");
  if (leaveSwitch) {
    try {
      leaveSwitch.checked = localStorage.getItem("dero.leave") !== "0"; // on unless switched off
    } catch {}
    leaveSwitch.addEventListener("change", () => {
      try {
        localStorage.setItem("dero.leave", leaveSwitch.checked ? "1" : "0");
      } catch {}
    }); // read by filters.js when a link is clicked
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
  // "Colour slugs": where slugs are coloured, kept in the cookie dero_hl (read by the server, so nothing flashes on load)
  const menu = document.getElementById("hl-menu");
  if (!menu) return;
  const boxes = [...menu.querySelectorAll("input[type=checkbox]")];
  const names = { forms: "Forms", table: "Table", toast: "Toasts" };
  function showPlaces() {
    const on = boxes.filter((box) => box.checked).map((box) => box.value);
    menu.querySelector(".multi-label").textContent = on.length ? on.map((v) => names[v]).join(", ") : "Nowhere";
    return on;
  }
  showPlaces();
  menu.addEventListener("change", () => {
    const on = showPlaces();
    document.documentElement.dataset.hl = on.join(" ");
    document.cookie = `dero_hl=${on.join(",") || "none"}; path=/; max-age=31536000; SameSite=Lax`;
  });
})();
