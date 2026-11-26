// ---- Success notices as toasts ----
// Errors and warnings stay where they are (below the field they are about). A success ("Created ...", "... updated",
// "Fallback saved.") is not about a field, so it appears at the bottom of the window, whichever card produced it, and
// fades away by itself. The server renders it like before, inside the card's .notices (so without JavaScript it is
// simply shown there); this script moves every .form-ok that appears in <main> into the toast stack.
(() => {
  const main = document.querySelector("main");
  if (!main) return;
  const SHOWN_FOR = 6500; // ms; hovering or focusing a toast holds it
  let stack = null;

  function host() {
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toasts";
      stack.setAttribute("aria-live", "polite");
      document.body.append(stack);
    }
    return stack;
  }

  function dismiss(toast) {
    clearTimeout(toast.timer);
    toast.classList.add("leaving");
    const gone = () => toast.remove();
    toast.addEventListener("animationend", gone, { once: true });
    setTimeout(gone, 250); // in case the animation does not run (reduced motion)
  }

  function show(notice) {
    const text = notice.textContent.trim();
    // the same message can arrive twice (the card's notices and the refreshed list): one toast
    if ([...host().children].some((t) => !t.classList.contains("leaving") && t.textContent.trim() === text)) {
      notice.remove();
      return;
    }
    const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" })
      .getAttribute("href")
      .split("#")[0];
    const close = document.createElement("button");
    close.type = "button";
    close.className = "mini toast-close";
    close.title = close.ariaLabel = "Dismiss";
    close.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${sprite}#x"/></svg>`;
    notice.classList.add("toast");
    notice.append(close);
    host().append(notice);

    const arm = () => (notice.timer = setTimeout(() => dismiss(notice), SHOWN_FOR));
    arm();
    notice.addEventListener("pointerenter", () => clearTimeout(notice.timer));
    notice.addEventListener("pointerleave", arm);
    notice.addEventListener("focusin", () => clearTimeout(notice.timer));
    notice.addEventListener("focusout", arm);
    close.addEventListener("click", () => dismiss(notice));
  }

  function collect() {
    main.querySelectorAll(".notices .form-ok").forEach(show);
  }

  new MutationObserver(collect).observe(main, { childList: true, subtree: true });
  collect();
})();
