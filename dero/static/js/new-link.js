// ---- New link form: check it before it is sent, keep what was typed ----
// The form has `novalidate` so the messages appear inside the "New link" card
// instead of in browser bubbles. The server repeats every check.
(() => {
  const form = document.getElementById("new-link");
  if (!form) return;
  const box = document.getElementById("new-link-error");
  const reserved = (form.dataset.reserved || "").split(",").filter(Boolean);
  const alphabets = JSON.parse(form.dataset.alphabets || "{}");
  const hint = form.querySelector(".alphabet-hint");
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

  // Random or typed: only the fields that belong to the chosen option are shown, and a line below says what it draws from.
  function syncGenerator() {
    const source = sourceOf();
    form
      .querySelectorAll("[data-when-source]")
      .forEach((el) => (el.hidden = !el.dataset.whenSource.split(" ").includes(source)));
    let text = "";
    if (source === "chars") {
      const chars = [...form.elements.alphabet_custom.value];
      if (chars.length) text = `${chars.length} characters, ${new Set(chars).size} different: ${chars.join("")}`;
    } else if (alphabets[source]) text = alphabets[source];
    hint.textContent = text;
    hint.title = text; // long sets are cut with an ellipsis; the tooltip has all of it
  }

  // Generate: draw a slug of the selected type now, put it into the Custom slug field to look at, edit or create.
  // From Custom it uses the random type that was selected last.
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
    const select = form.elements.slug_source;
    select.value = "slug";
    refreshSelect(select);
    form.elements.slug.value = randomSlug(kind);
    syncGenerator();
    savePrefs();
    forgetWarning(form);
    form.elements.slug.focus();
    form.elements.slug.select();
  });

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
    if (name === "target" || name === "expires_at") forgetWarning(form); // a different value deserves a new look
    if (["slug_source", "alphabet_custom", "length"].includes(name)) {
      syncGenerator();
      savePrefs();
    }
  });
  form.addEventListener("change", (event) => {
    // the dropdown reports `change`
    if (event.target.name === "slug_source") {
      if (sourceOf() !== "slug") lastRandom = sourceOf();
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
