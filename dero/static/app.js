// Copy a short link to the clipboard (buttons carry the URL in data-copy).
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
  } catch {
    return; // clipboard needs HTTPS or localhost
  }
  const use = button.querySelector("use");
  const sprite = use.getAttribute("href").split("#")[0];
  use.setAttribute("href", `${sprite}#check`);
  button.classList.add("done");
  setTimeout(() => {
    use.setAttribute("href", `${sprite}#copy`);
    button.classList.remove("done");
  }, 1500);
});

// Click a row to show or hide its details (the row after it).
function toggleRow(row) {
  const detail = row.nextElementSibling;
  if (!detail || !detail.classList.contains("detail")) return;
  const open = detail.hidden;
  detail.hidden = !open;
  row.classList.toggle("open", open);
  const button = row.querySelector(".expand");
  button.setAttribute("aria-expanded", String(open));
  const label = open ? "Hide details" : "Show details";
  button.title = label;
  button.setAttribute("aria-label", label);
}

document.addEventListener("click", (event) => {
  const row = event.target.closest("tr.item");
  if (!row) return;
  if (event.target.closest(".expand")) return toggleRow(row);
  if (event.target.closest("a, button, input, label, form, select")) return;
  toggleRow(row);
});

// ---- New link form: check it before it is sent, keep what was typed ----
// The form has `novalidate` so the messages appear inside the "New link" card
// instead of in browser bubbles. The server repeats every check.
(function () {
  const form = document.getElementById("new-link");
  if (!form) return;
  const box = document.getElementById("new-link-error");
  const SLUG = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
  const reserved = (form.dataset.reserved || "").split(",").filter(Boolean);

  function problem() {
    const target = form.elements.target, slug = form.elements.slug;
    const url = target.value.trim();
    if (!url) return [target, "Enter the URL to shorten."];
    let parsed;
    try { parsed = new URL(url); } catch { return [target, "Target must be a valid http:// or https:// URL."]; }
    if (!/^https?:$/.test(parsed.protocol) || !parsed.host || url.length > 2048)
      return [target, "Target must be a valid http:// or https:// URL."];
    const s = slug.value.trim();
    if (s && !SLUG.test(s)) return [slug, "Slug may only contain letters, digits, '-' and '_' (max 64)."];
    if (s && reserved.includes(s)) return [slug, `'${s}' is reserved.`];
    const expires = form.elements.expires_at;   // min = today (UTC), set by the server
    if (expires.value && expires.min && expires.value < expires.min)
      return [expires, "That expiry date has already passed, so the link would be dead on arrival (dates are in UTC)."];
    return null;
  }

  function show(message) {
    box.replaceChildren();
    if (!message) return;
    const icon = document.querySelector("svg.icon use");
    const sprite = icon ? icon.getAttribute("href").split("#")[0] : "";
    box.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${sprite}#alert"/></svg>`;
    const span = document.createElement("span");
    span.textContent = message;
    box.append(span);
  }

  form.addEventListener("submit", (event) => {
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    const found = problem();
    if (!found) return show("");          // valid: let the browser send it
    event.preventDefault();               // invalid: nothing is sent, nothing is cleared
    const [field, message] = found;
    field.setAttribute("aria-invalid", "true");
    show(message);
    field.focus();
  });

  form.addEventListener("input", (event) => {
    event.target.removeAttribute("aria-invalid");
    show("");
  });
})();

// ---- Filters apply by themselves ----
// Changing a dropdown (or pausing while typing in the search box) fetches the
// list again and swaps only the table, so the page doesn't jump and the search
// box keeps focus. The indicator confirms that something happened.
(function () {
  const form = document.getElementById("filters");
  if (!form) return;
  const live = document.getElementById("filter-live");
  const clear = document.getElementById("clear-filters");
  const SPRITE = live.querySelector("use").getAttribute("href").split("#")[0];
  const IDLE = live.querySelector("span").textContent;
  let seq = 0, typing, resetTimer;

  function indicator(state, text) {
    const use = live.querySelector("use");
    live.classList.toggle("busy", state === "busy");
    live.classList.toggle("updated", state === "done");
    use.setAttribute("href", `${SPRITE}#${state === "done" ? "check" : "refresh"}`);
    live.querySelector("span").textContent = text;
    clearTimeout(resetTimer);
    if (state === "done") resetTimer = setTimeout(() => indicator("idle", IDLE), 1400);
  }

  function setClear(active) {            // disabled, never hidden: nothing may move
    clear.setAttribute("aria-disabled", String(!active));
    if (active) clear.removeAttribute("tabindex"); else clear.tabIndex = -1;
  }

  function filtered(params) {
    return ["q", "status", "owner"].some((k) => params.get(k));
  }

  async function update() {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of [...params]) if (!value) params.delete(key);
    const url = form.getAttribute("action") + (params.size ? "?" + params : "");
    const mine = ++seq;
    indicator("busy", "Updating…");
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const fresh = doc.getElementById("links-results");
      if (mine !== seq) return;            // a newer change already replaced this one
      if (!fresh) throw new Error("unexpected page");
      // The parsed copy treats <noscript> content as real elements; drop it so nothing from it can apply.
      fresh.querySelectorAll("noscript").forEach((el) => el.remove());
      document.getElementById("links-results").replaceWith(document.importNode(fresh, true));
      history.replaceState(null, "", url);
      setClear(filtered(params));
      const n = Number(fresh.dataset.count), total = Number(fresh.dataset.overall);
      indicator("done", filtered(params) ? `Updated · ${n} of ${total}` : "Updated");
    } catch {
      location.href = url;                 // fall back to a normal page load
    }
  }

  form.addEventListener("change", update);
  form.addEventListener("input", (event) => {
    if (event.target.name !== "q") return;
    clearTimeout(typing);
    typing = setTimeout(update, 250);
  });
  form.addEventListener("submit", (event) => { event.preventDefault(); clearTimeout(typing); update(); });
  clear.addEventListener("click", (event) => {
    event.preventDefault();
    if (clear.getAttribute("aria-disabled") === "true") return;
    form.elements.q.value = "";
    form.elements.status.value = "";
    if (form.elements.owner) form.elements.owner.value = "";
    update();
  });
})();

// ---- Confirmation dialog (replaces window.confirm) ----
// A form with data-confirm-title asks first. The dialog is a native <dialog>:
// Esc and a click outside cancel, focus starts on Cancel, and the confirming
// button sits on the left.
(function () {
  const dialog = document.getElementById("confirm");
  if (!dialog || typeof dialog.showModal !== "function") return;

  function ask(data) {
    dialog.querySelector("#confirm-title").textContent = data.confirmTitle || "Are you sure?";
    dialog.querySelector("#confirm-name").textContent = data.confirmName || "";
    dialog.querySelector("#confirm-detail").textContent = data.confirmDetail ? "→ " + data.confirmDetail : "";
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
      form.submit();
    }
  });

  dialog.addEventListener("click", (event) => {   // click on the backdrop
    if (event.target === dialog) dialog.close("no");
  });
})();
