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

// ---- Times are stored and sent as UTC; show them in the viewer's own time zone and locale ----
// The server renders the UTC text (that is what stays if JavaScript is off, and what the tooltip shows).
const LOCAL_TIME = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
});

function localizeTimes(root = document) {
  root.querySelectorAll("time.localtime[datetime]").forEach((el) => {
    const date = new Date(el.getAttribute("datetime"));
    if (!Number.isNaN(date.getTime())) el.textContent = LOCAL_TIME.format(date);
  });
}

// Replace one region of the page with the same region from a freshly fetched page.
// Rows that were open stay open. Returns false if the region is missing.
function swapRegion(id, doc) {
  const current = document.getElementById(id), fresh = doc.getElementById(id);
  if (!current || !fresh) return false;
  // The parsed copy treats <noscript> content as real elements; drop it so nothing from it can apply.
  fresh.querySelectorAll("noscript").forEach((el) => el.remove());
  const open = [...current.querySelectorAll("tr.detail:not([hidden])")].map((row) => row.id);
  current.replaceWith(document.importNode(fresh, true));
  for (const rowId of open) {
    const detail = document.getElementById(rowId);
    if (detail && detail.previousElementSibling) toggleRow(detail.previousElementSibling);
  }
  if (typeof syncAllEdit === "function") syncAllEdit();
  localizeTimes();
  return true;
}

document.addEventListener("click", (event) => {
  const row = event.target.closest("tr.item");
  if (!row) return;
  if (event.target.closest(".expand")) return toggleRow(row);
  if (event.target.closest("a, button, input, label, form, select")) return;
  toggleRow(row);
});

// ---- Checks shared by the "New link" form and the edit form in a link's details ----
const SLUG_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const BAD_URL = "Target must be a valid http:// or https:// URL.";

// Returns [field, message] for the first problem, or null. The server repeats every check.
function linkProblem(form, { reserved = [], savedSlug = null, slugRequired = false, dateWhenOn = false } = {}) {
  const target = form.elements.target, slug = form.elements.slug, expires = form.elements.expires_at;
  const url = target.value.trim();
  if (!url) return [target, "Enter the URL to shorten."];
  let parsed;
  try { parsed = new URL(url); } catch { return [target, BAD_URL]; }
  if (!/^https?:$/.test(parsed.protocol) || !parsed.host || url.length > 2048) return [target, BAD_URL];
  const s = slug.value.trim();
  if (!s && slugRequired) return [slug, "A short link needs a slug."];
  if (s && !SLUG_RE.test(s)) return [slug, "Slug may only contain letters, digits, '-' and '_' (max 64)."];
  if (s && s !== savedSlug && reserved.includes(s)) return [slug, `'${s}' is reserved.`];
  if (dateWhenOn && !expires.disabled && !expires.value) return [expires, "Pick the last day the link should work, or switch the expiry off."];
  // min = today (UTC), set by the server; an unchanged date may stay even if it has passed
  if (!expires.disabled && expires.value && expires.min && expires.value < expires.min && expires.value !== expires.defaultValue)
    return [expires, "That expiry date has already passed, so the link would be dead on arrival (dates are in UTC)."];
  return null;
}

// Put a message into a card's .notices container (same markup the server renders).
function showNotice(id, message, kind = "error") {
  const box = document.getElementById(id);
  if (!box) return;
  const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" }).getAttribute("href").split("#")[0];
  const p = document.createElement("p");
  p.className = kind === "error" ? "form-error" : "form-ok";
  p.setAttribute("role", kind === "error" ? "alert" : "status");
  p.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${sprite}#${kind === "error" ? "alert" : "check"}"/></svg>`;
  const span = document.createElement("span");
  span.textContent = message;
  p.append(span);
  box.replaceChildren(p);
}

// ---- Is this the usual https://domain.tld/path shape? ----
// Returns a list of short reasons why a (valid http/https) URL looks unusual; empty = nothing to warn about.
function unusualUrl(value) {
  const text = value.trim();
  let url;
  try { url = new URL(text); } catch { return []; }          // invalid URLs are errors, handled elsewhere
  const reasons = [];
  const host = url.hostname;
  if (url.protocol === "http:") reasons.push("it uses http:// instead of https://");
  if (/\s/.test(text)) reasons.push("it contains spaces");
  if (url.username || url.password) reasons.push("it contains a username or password");
  if (host.startsWith("[") || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    reasons.push("the host is an IP address, not a domain name");
  } else if (!host.includes(".")) {
    reasons.push(`the host "${host}" has no domain ending like .com`);
  } else {
    const tld = host.replace(/\.$/, "").split(".").pop();
    if (!/^(xn--[a-z0-9-]+|[a-z]{2,})$/i.test(tld)) reasons.push(`the domain ending ".${tld}" looks unusual`);
  }
  if (url.port) reasons.push(`it contains a port number (:${url.port})`);
  return reasons;
}

// ---- New link form: check it before it is sent, keep what was typed ----
// The form has `novalidate` so the messages appear inside the "New link" card
// instead of in browser bubbles. The server repeats every check.
(function () {
  const form = document.getElementById("new-link");
  if (!form) return;
  const box = document.getElementById("new-link-error");
  const reserved = (form.dataset.reserved || "").split(",").filter(Boolean);

  function problem() {
    return linkProblem(form, { reserved });
  }

  function show(message, kind = "error") {
    box.replaceChildren();
    box.className = kind === "warn" ? "form-warn" : "form-error";
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
    form.elements.target.removeAttribute("data-warn");
    const found = problem();
    if (!found) {
      // Valid. An unusual-looking address gets one warning first; sending it again (same address) goes through.
      const value = form.elements.target.value.trim(), reasons = unusualUrl(value);
      if (reasons.length && form.dataset.warned !== value) {
        event.preventDefault();
        form.dataset.warned = value;
        form.elements.target.setAttribute("data-warn", "");
        show(`This doesn't look like a usual https://domain.tld/path address: ${reasons.join(", ")}. ` +
             `Check it, or press Create again to add it as it is.`, "warn");
        form.elements.target.focus();
        return;
      }
      return show("");                    // let the browser send it
    }
    event.preventDefault();               // invalid: nothing is sent, nothing is cleared
    const [field, message] = found;
    field.setAttribute("aria-invalid", "true");
    show(message);
    field.focus();
  });

  function forgetWarning() {
    delete form.dataset.warned;
    form.elements.target.removeAttribute("data-warn");
  }

  form.addEventListener("input", (event) => {
    event.target.removeAttribute("aria-invalid");
    show("");
    if (event.target === form.elements.target) forgetWarning();     // a different address deserves a new look
  });
  form.addEventListener("reset", forgetWarning);
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
      if (mine !== seq) return;            // a newer change already replaced this one
      if (!swapRegion("links-results", doc)) throw new Error("unexpected page");
      const fresh = document.getElementById("links-results");
      history.replaceState(null, "", url);
      setClear(filtered(params));
      const n = Number(fresh.dataset.count), total = Number(fresh.dataset.overall);
      indicator("done", filtered(params) ? `Updated · ${n} of ${total}` : "Updated");
    } catch {
      location.href = url;                 // fall back to a normal page load
    }
  }

  document.addEventListener("click", (event) => {          // sortable column headers
    const link = event.target.closest("#links-results th a");
    if (!link) return;
    const params = new URL(link.href).searchParams;
    const wanted = `${params.get("sort")}:${params.get("dir")}`;
    const order = form.elements.order;
    if (![...order.options].some((o) => o.value === wanted)) return;   // unknown: let the link work normally
    event.preventDefault();
    order.value = wanted;
    update();
  });

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
    dialog.querySelector("#confirm-detail").textContent = data.confirmDetail || "";
    dialog.querySelector("#confirm-text .icon").hidden = !data.confirmDetail;       // the arrow only makes sense with a second URL
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

  dialog.addEventListener("click", (event) => {   // click on the backdrop
    if (event.target === dialog) dialog.close("no");
  });
})();

// ---- Editing a link in its details (target, short link, expiry) ----
// The switch enables the date field (off = never expires). "Update" and
// "Discard" stay disabled until something differs from what is saved. The
// target and slug inputs sit in other places of the row and belong to the
// form through their form="" attribute.
function syncEdit(form) {
  const toggle = form.querySelector(".expiry-switch"), date = form.elements.expires_at;
  const target = form.elements.target, slug = form.elements.slug;
  date.disabled = !toggle.checked;
  date.required = toggle.checked;
  const dirty = toggle.checked !== toggle.defaultChecked || (toggle.checked && date.value !== date.defaultValue)
    || target.value !== target.defaultValue || slug.value !== slug.defaultValue;
  for (const button of document.querySelectorAll(`[form="${form.id}"], [data-discard="${form.id}"]`)) {
    if (button.dataset.discard) button.hidden = false;     // without JavaScript there is nothing to discard
    if (button.tagName === "BUTTON") button.disabled = !dirty;
  }
}

function syncAllEdit() {
  document.querySelectorAll(".edit-form").forEach(syncEdit);
}

function editFormOf(element) {
  const form = element.form;
  return form && form.classList.contains("edit-form") ? form : null;
}

document.addEventListener("change", (event) => {
  const form = editFormOf(event.target);
  if (!form) return;
  syncEdit(form);
  if (event.target.classList.contains("expiry-switch") && event.target.checked) form.elements.expires_at.focus();
});

document.addEventListener("input", (event) => {
  const form = editFormOf(event.target);
  if (!form) return;
  event.target.removeAttribute("aria-invalid");
  syncEdit(form);
});

document.addEventListener("click", (event) => {
  const discard = event.target.closest("[data-discard]");
  if (!discard) return;
  const form = document.getElementById(discard.dataset.discard);
  form.reset();                                            // back to what is saved (reaches the inputs with form="")
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  syncEdit(form);
});

// Check the edit form before it is sent; errors go to the "All links" card.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.classList || !form.classList.contains("edit-form")) return;
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  const found = linkProblem(form, {
    reserved: (form.dataset.reserved || "").split(",").filter(Boolean),
    savedSlug: form.elements.slug.defaultValue,
    slugRequired: true,
    dateWhenOn: true,
  });
  if (!found) return;
  event.preventDefault();
  const [field, message] = found;
  field.setAttribute("aria-invalid", "true");
  showNotice("links-notices", message);
  field.focus();
});

syncAllEdit();
localizeTimes();


// ---- Row switches submit when flipped ----
document.addEventListener("change", (event) => {
  const toggle = event.target.closest(".row-switch");
  if (toggle) toggle.form.requestSubmit();
});

// ---- Actions without page reloads ----
// Every POST form in <main> is sent with fetch(). The server still answers
// with a redirect and a full page, so that page is used to refresh only what
// changed: the messages, the table and (for "New link") its feedback line.
// Without JavaScript the same forms work as ordinary form posts.
(function () {
  const main = document.querySelector("main");
  if (!main) return;
  // Messages live in the card they belong to (.notices containers, one per scope).
  function refreshNotices(doc) {
    for (const theirs of doc.querySelectorAll(".notices")) {
      const mine = document.getElementById(theirs.id);
      if (mine) mine.innerHTML = theirs.innerHTML;
    }
  }

  function showFailure(form) {
    const box = (form.closest("section") || document).querySelector(".notices");
    if (!box) return;
    const p = document.createElement("p");
    p.className = "form-error";
    p.setAttribute("role", "alert");
    p.textContent = "That didn't work. Reload the page and try again.";
    box.replaceChildren(p);
  }

  async function currentView() {
    const res = await fetch(location.pathname + location.search, { credentials: "same-origin" });
    return new DOMParser().parseFromString(await res.text(), "text/html");
  }

  async function submit(form) {
    const buttons = [...form.elements].filter((el) => el.tagName === "BUTTON");
    buttons.forEach((b) => (b.disabled = true));
    form.setAttribute("aria-busy", "true");
    try {
      const res = await fetch(form.getAttribute("action"), {
        method: "POST", body: new FormData(form), credentials: "same-origin",
      });
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const isCreate = form.id === "new-link";
      if (!doc.querySelector("main")) throw new Error("unexpected answer");   // 403, 404, 500 ...

      refreshNotices(doc);

      if (isCreate) {                                  // keep the typed values on an error, clear them on success
        const box = document.getElementById("new-link-error"), theirs = doc.getElementById("new-link-error");
        if (box && theirs) box.innerHTML = theirs.innerHTML;
        form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
        if (res.ok) {
          form.reset();
        } else {
          for (const bad of doc.querySelectorAll("#new-link [aria-invalid]")) {
            const mine = form.elements[bad.name];
            if (mine) { mine.setAttribute("aria-invalid", "true"); mine.focus(); }
          }
          return;
        }
      }

      if (doc.querySelector(".notices .form-error")) return;     // rejected: keep the form exactly as the user left it

      // refresh the list the user is looking at
      let view = doc;
      const same = new URL(res.url).pathname + new URL(res.url).search === location.pathname + location.search;
      if (!same) view = await currentView();            // e.g. a new link: the answer was the unfiltered list
      for (const id of ["links-results", "rules-results"]) swapRegion(id, view);

      if (form.dataset.resetOnSuccess !== undefined && !doc.querySelector(".notices .form-error")) form.reset();
    } catch {
      showFailure(form);
    } finally {
      delete form.dataset.confirmed;
      form.removeAttribute("aria-busy");
      buttons.forEach((b) => { if (b.isConnected) b.disabled = false; });
      if (form.isConnected && form.classList.contains("edit-form")) syncEdit(form);
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.method !== "post" || !main.contains(form)) return;
    if (form.dataset.confirmTitle !== undefined && !form.dataset.confirmed) {
      // Only reached when <dialog> is unsupported: fall back to the browser's own question.
      if (!window.confirm(form.dataset.confirmTitle)) return event.preventDefault();
    }
    event.preventDefault();
    submit(form);
  });
})();
