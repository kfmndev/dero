// ---- Notifications: every message is a toast ----
// A toast is a small card at the bottom of the window. Successes ("ok") fade away by themselves (hovering or focusing
// one holds it); errors and warnings stay until they are dismissed, replaced by a newer message from the same place
// (the `key`) or made obsolete; the live toast ("live") is pinned below the others until its x is clicked.
//
// The server still renders its messages inside the cards' .notices (so without JavaScript they are simply shown
// there); this script moves each of them into the stack, and `toast()` is what the other scripts call.
const SHOWN_FOR = 6500; // ms
const TOAST_KINDS = {
  ok: { cls: "form-ok", icon: "check", role: "status" },
  warn: { cls: "form-warn", icon: "alert", role: "alert" },
  error: { cls: "form-error", icon: "alert", role: "alert" },
  live: { cls: "form-live", icon: null, role: "status" }, // a blinking dot instead of an icon
};
let toastStack = null;

function toastHost() {
  if (!toastStack) {
    toastStack = document.createElement("div");
    toastStack.className = "toasts";
    toastStack.setAttribute("aria-live", "polite");
    document.body.append(toastStack);
  }
  return toastStack;
}

const toastSprite = () =>
  (document.querySelector("svg.icon use") || { getAttribute: () => "" }).getAttribute("href").split("#")[0];

function toastNamed(key) {
  return key ? [...toastHost().children].find((t) => t.dataset.key === key && !t.classList.contains("leaving")) : null;
}

// Take a toast away (with its fade, or at once).
function dismissToast(key, now = false) {
  const el = typeof key === "string" ? toastNamed(key) : key;
  if (!el) return;
  clearTimeout(el.timer);
  el.classList.add("leaving");
  if (now) return el.remove();
  el.addEventListener("animationend", () => el.remove(), { once: true });
  setTimeout(() => el.remove(), 250); // in case the animation does not run (reduced motion)
}

// Put a ready element (a <p> with an icon and a <span>) into the stack.
function placeToast(el, kind, key) {
  const same = toastNamed(key);
  const body = el.querySelector("span:not(.toast-icon)");
  if (same && same.dataset.kind === kind) {
    // the same place speaks again: its toast changes in place, with a small nudge
    same.querySelector("span:not(.toast-icon)").replaceWith(body);
    const icon = el.querySelector("svg"); // (the message may come with another icon)
    if (icon) same.querySelector("svg")?.replaceWith(icon);
    same.classList.remove("bump");
    void same.offsetWidth;
    same.classList.add("bump");
    return same;
  }
  if (same) dismissToast(same, true);
  const text = el.textContent.trim();
  if (
    kind === "ok" &&
    [...toastHost().children].some((t) => !t.classList.contains("leaving") && t.textContent.trim() === text)
  )
    return null; // the same success arrived twice (the card's notices and the refreshed list)

  const close = document.createElement("button");
  close.type = "button";
  close.className = "mini toast-close";
  close.title = close.ariaLabel = "Dismiss";
  close.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${toastSprite()}#x"/></svg>`;
  el.classList.add("toast", TOAST_KINDS[kind].cls);
  el.setAttribute("role", TOAST_KINDS[kind].role);
  el.dataset.kind = kind;
  if (key) el.dataset.key = key;
  el.append(close);
  // the live toast stays at the bottom of the stack, below the others
  const live = toastHost().querySelector(':scope > [data-kind="live"]');
  if (kind !== "live" && live) toastHost().insertBefore(el, live);
  else toastHost().append(el);

  if (kind === "ok") {
    const arm = () => (el.timer = setTimeout(() => dismissToast(el), SHOWN_FOR));
    arm();
    el.addEventListener("pointerenter", () => clearTimeout(el.timer));
    el.addEventListener("pointerleave", arm);
    el.addEventListener("focusin", () => clearTimeout(el.timer));
    el.addEventListener("focusout", arm);
  }
  close.addEventListener("click", () => dismissToast(el));
  return el;
}

// The name of the icon an element (a server-rendered notice) shows.
function iconNameOf(el) {
  return el?.querySelector("svg use")?.getAttribute("href")?.split("#")[1] || null;
}

// kind: "ok", "warn", "error" or "live". content: text (‹slug› and ⟨code⟩ are drawn as boxes) or a node. icon: the
// name of an icon of the sprite, instead of the one of the kind.
function toast(kind, content, { key = "", icon = null } = {}) {
  const el = document.createElement("p");
  const name = icon || TOAST_KINDS[kind].icon;
  el.innerHTML = name
    ? `<svg class="icon" aria-hidden="true"><use href="${toastSprite()}#${name}"/></svg>`
    : '<span class="live-dot toast-icon" aria-hidden="true"></span>';
  const span = document.createElement("span");
  if (typeof content === "string") setRich(span, content);
  else span.append(content);
  el.append(span);
  return placeToast(el, kind, key);
}

(() => {
  const main = document.querySelector("main");
  if (!main) return;
  const kindOf = (p) =>
    p.classList.contains("form-error") ? "error" : p.classList.contains("form-warn") ? "warn" : "ok";
  let problems = null;

  // what the server wrote into a card's notices becomes a toast; a success also ends the errors of its place
  function collect() {
    main.querySelectorAll(".notices > p").forEach((p) => {
      const kind = kindOf(p),
        key = p.parentElement.id;
      if (kind === "ok") dismissToast(key, true);
      p.remove();
      placeToast(p, kind, kind === "ok" ? "" : key);
    });
    // the search's problems (unknown key, bad date ...) follow the results on the page
    main.querySelectorAll(".query-problems").forEach((p) => p.remove());
    const now = document.getElementById("links-results")?.dataset.problems;
    if (now !== undefined && now !== problems) {
      problems = now;
      if (now) toast("warn", now, { key: "query" });
      else dismissToast("query");
    }
  }

  new MutationObserver(collect).observe(main, { childList: true, subtree: true });
  collect();
})();
