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
(() => {
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
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
      });
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const isCreate = form.id === "new-link";
      if (!doc.querySelector("main")) throw new Error("unexpected answer"); // 403, 404, 500 ...

      refreshNotices(doc);

      if (isCreate) {
        // keep the typed values on an error, clear them on success
        const theirs = doc.getElementById("new-link-error");
        if (theirs?.textContent.trim())
          toast("error", theirs.querySelector("span")?.cloneNode(true) || theirs.textContent, { key: "new-link" });
        else dismissToast("new-link");
        form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
        if (res.ok) {
          form.reset();
        } else {
          for (const bad of doc.querySelectorAll("#new-link [aria-invalid]")) {
            const mine = form.elements.namedItem(bad.name); // (not elements[name]: "length" is the collection's size)
            if (mine) {
              mine.setAttribute("aria-invalid", "true");
              mine.focus();
            }
          }
          return;
        }
      }

      if (doc.querySelector(".notices .form-error")) return; // rejected: keep the form exactly as the user left it
      if (form.classList.contains("edit-form")) dismissToast(`link-${form.id.slice(1)}-notices`, true); // fixed

      // refresh the list the user is looking at
      let view = doc;
      const same = new URL(res.url).pathname + new URL(res.url).search === location.pathname + location.search;
      if (!same) view = await currentView(); // e.g. a new link: the answer was the unfiltered list
      for (const id of ["links-results", "rules-results"]) swapRegion(id, view);

      if (form.dataset.resetOnSuccess !== undefined && !doc.querySelector(".notices .form-error")) form.reset();
    } catch {
      showFailure(form);
    } finally {
      delete form.dataset.confirmed;
      form.removeAttribute("aria-busy");
      buttons.forEach((b) => {
        if (b.isConnected) b.disabled = false;
      });
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
