// ---- New link form: check it before it is sent, keep what was typed ----
// The form has `novalidate` so the messages appear inside the "New link" card
// instead of in browser bubbles. The server repeats every check.
(() => {
  const form = document.getElementById("new-link");
  if (!form) return;
  const box = document.getElementById("new-link-error");
  const reserved = (form.dataset.reserved || "").split(",").filter(Boolean);
  const alphabets = JSON.parse(form.dataset.alphabets || "{}");
  const PREFS = "dero.generator";
  const sourceOf = () => form.elements.slug_source.value;
  const lengthField = () => form.elements.namedItem("length");

  // The message is a toast; the field it is about is marked (aria-invalid or data-warn) and focused by the caller.
  function show(message, kind = "error") {
    if (message) toast(kind, message, { key: "new-link" });
    else dismissToast("new-link");
  }
  // an error the server rendered into the form (a post without the script) is shown the same way
  if (box?.textContent.trim()) {
    toast("error", box.querySelector("span")?.cloneNode(true) || box.textContent.trim(), { key: "new-link" });
    box.replaceChildren();
  }

  const slugField = form.elements.slug,
    slugGroup = document.getElementById("new-link-slug");
  let stash = "", // what was typed as a custom slug, while a random type is selected
    shown = sourceOf(); // the generator before the last change

  function repaintSlug() {
    slugField.dispatchEvent(new Event("input")); // the coloured copy behind it follows (not bubbling: not the user typing)
  }

  // Random or typed: only the options that belong to the chosen type are shown, next to the dropdown.
  // The slug field is always there: with a random type it is empty (placeholder "random") until the generator is used
  // (it then shows the drawn slug) or the user clicks or types in it, which switches the generator to Custom.
  function syncGenerator() {
    const source = sourceOf();
    const random = source !== "slug";
    slugGroup.classList.toggle("is-random", random);
    slugField.placeholder = random ? "random" : "my-link";
    form
      .querySelectorAll("[data-when-source]")
      .forEach((el) => (el.hidden = !el.dataset.whenSource.split(" ").includes(source)));
  }

  // Generate (only offered with a random type): draw a slug of the selected type now and show it in the slug field.
  // What is shown is what will be created. Clicking into the field makes it a custom slug (the generator switches).
  let lastRandom = sourceOf() === "slug" ? "default" : sourceOf();
  const generate = form.querySelector("#new-link-generate");
  const reservedSet = new Set(reserved);
  function randomSlug(kind) {
    const alphabet =
      kind === "chars" ? [...form.elements.alphabet_custom.value] : [...(alphabets[kind] || alphabets.default)];
    const length = Number(lengthField().value),
      pool = new Uint32Array(length);
    for (let attempt = 0; attempt < 20; attempt++) {
      crypto.getRandomValues(pool);
      const slug = [...pool].map((n) => alphabet[n % alphabet.length]).join("");
      if (!reservedSet.has(slug) && slug.replace(/\./g, "")) return slug;
    }
    return "";
  }
  generate.addEventListener("click", () => {
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    const kind = sourceOf() === "slug" ? lastRandom : sourceOf();
    const found = generatorProblem(form, reserved, kind);
    if (found) {
      found[0].setAttribute("aria-invalid", "true");
      show(found[1], "error");
      found[0].focus();
      return;
    }
    show("");
    slugField.value = randomSlug(kind);
    repaintSlug();
    forgetWarning(form);
  });

  // A slug that was drawn and is shown is created as it is: with a random type selected, the slug field counts as custom
  function settle() {
    if (sourceOf() !== "slug" && slugField.value.trim()) switchToCustom(false); // (not remembered: the next one is random again)
  }

  // Clicking or typing in the slug field means "my own": the type switches to Custom.
  function switchToCustom(remember = true) {
    if (sourceOf() === "slug") return;
    lastRandom = sourceOf();
    const select = form.elements.slug_source;
    select.value = "slug";
    refreshSelect(select);
    stash = "";
    syncGenerator();
    if (remember) savePrefs();
  }
  slugField.addEventListener("pointerdown", () => switchToCustom());

  function savePrefs() {
    // the choice is remembered in this browser
    try {
      localStorage.setItem(
        PREFS,
        JSON.stringify({
          source: sourceOf(),
          custom: form.elements.alphabet_custom.value,
          length: lengthField().value,
        }),
      );
    } catch {}
  }

  function loadPrefs() {
    try {
      const saved = JSON.parse(localStorage.getItem(PREFS) || "null");
      if (!saved) return;
      const select = form.elements.slug_source;
      if ([...select.options].some((o) => o.value === saved.source)) {
        select.value = saved.source;
        refreshSelect(select);
      }
      form.elements.alphabet_custom.value = saved.custom || "";
      if (saved.length) lengthField().value = saved.length;
    } catch {}
  }

  if (form.dataset.fresh === "yes") loadPrefs(); // after a rejected submit the server's values win
  syncGenerator();

  form.addEventListener("submit", (event) => {
    settle();
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    const found = linkProblem(form, { reserved, generator: true });
    if (!found) {
      if (needsLookup(form)) {
        event.preventDefault();
        lookupThenResubmit(form);
        return;
      }
      if (warnFirst(form, event, "Create", (message) => show(message, "warn"))) return;
      return show(""); // let the browser send it
    }
    event.preventDefault(); // invalid: nothing is sent, nothing is cleared
    const [field, message] = found;
    field.setAttribute("aria-invalid", "true");
    show(message, "error");
    field.focus();
  });

  form.addEventListener("input", (event) => {
    event.target.removeAttribute("aria-invalid");
    show("");
    const name = event.target.name;
    if (name === "slug") switchToCustom();
    if (name === "target" || name === "expires_at") forgetWarning(form); // a different value deserves a new look
    if (["slug_source", "alphabet_custom", "length"].includes(name)) {
      syncGenerator();
      savePrefs();
    }
  });
  form.addEventListener("change", (event) => {
    // the dropdown reports `change`
    if (event.target.name === "slug_source") {
      if (sourceOf() !== "slug") {
        lastRandom = sourceOf();
        if (slugField.value) {
          if (shown === "slug") stash = slugField.value; // a random type has no typed slug; it comes back with Custom
          slugField.value = ""; // (a drawn one is out of date when the generator changes)
          repaintSlug();
        }
      } else if (!slugField.value && stash) {
        slugField.value = stash;
        repaintSlug();
      }
      shown = sourceOf();
      syncGenerator();
      savePrefs();
    }
  });
  form.addEventListener("reset", () => {
    forgetWarning(form);
    setTimeout(() => {
      loadPrefs();
      syncGenerator();
    }, 0); // reset restores the defaults; the remembered choice comes back
  });
})();

// ---- New link: the small switch enables the expiry date (off = never expires) ----
(() => {
  const toggle = document.getElementById("new-expiry-switch");
  if (!toggle) return;
  const date = toggle.form.elements.expires_at;
  const sync = () => {
    date.disabled = !toggle.checked;
  };
  toggle.addEventListener("change", () => {
    sync();
    if (toggle.checked) date.focus();
    else {
      date.value = "";
      date.removeAttribute("aria-invalid");
    }
  });
  toggle.form.addEventListener("reset", () => setTimeout(sync, 0));
  sync();
})();
