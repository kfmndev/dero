// ---- Confirmation dialog (replaces window.confirm) ----
// A form with data-confirm-title asks first. The dialog is a native <dialog>:
// Esc and a click outside cancel, focus starts on Cancel, and the confirming
// button sits on the left.
(() => {
  const dialog = document.getElementById("confirm");
  if (!dialog || typeof dialog.showModal !== "function") return;

  function ask(data) {
    dialog.querySelector("#confirm-title").textContent = data.confirmTitle || "Are you sure?";
    // A short link: base address in the normal font, the slug in its coloured box (cut like everywhere else).
    // Anything else (a rule's pattern) is shown as code.
    const name = dialog.querySelector("#confirm-name"),
      full = data.confirmName || "";
    name.replaceChildren();
    if (/^https?:\/\//.test(full)) {
      const cut = full.lastIndexOf("/") + 1,
        slugPart = full.slice(cut);
      const base = document.createElement("span"),
        code = document.createElement("code");
      base.className = "confirm-base";
      base.textContent = full.slice(0, cut);
      code.className = "slug";
      code.append(coloredSlug(slugPart.length > 20 ? slugPart.slice(0, 20) : slugPart));
      if (slugPart.length > 20) {
        code.append("…");
        code.title = slugPart;
      }
      name.append(base, code);
    } else {
      const code = document.createElement("code");
      code.className = "slug";
      code.textContent = full;
      name.append(code);
    }
    dialog.querySelector("#confirm-detail").textContent = data.confirmDetail || "";
    dialog.querySelector("#confirm-text .icon").hidden = !data.confirmDetail; // the arrow only makes sense with a second URL
    dialog.querySelector("#confirm-yes span").textContent = data.confirmYes || "Confirm";
    return new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
      dialog.returnValue = "no";
      dialog.showModal();
    });
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.dataset || form.dataset.confirmTitle === undefined || form.dataset.confirmed) return;
    event.preventDefault();
    if (await ask(form.dataset)) {
      form.dataset.confirmed = "1";
      form.requestSubmit();
    }
  });

  dialog.addEventListener("click", (event) => {
    // click on the backdrop
    if (event.target === dialog) dialog.close("no");
  });
})();
