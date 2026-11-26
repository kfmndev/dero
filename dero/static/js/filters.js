// ---- Filters, search and sorting apply by themselves ----
// The search box holds the whole state as one query. The dropdowns show it (and edit it); changing
// either one fetches the list again and swaps only the table, so the page doesn't jump and the
// search box keeps focus. The indicator confirms that something happened.
(() => {
  const form = document.getElementById("filters");
  if (!form) return;
  const input = document.getElementById("q");
  const highlight = form.querySelector(".qhl");
  const sortSelect = document.getElementById("filter-sort");
  const live = document.getElementById("filter-live");
  const clear = document.getElementById("reset-filters");
  const multis = [...form.querySelectorAll("details.multi")];
  const queryMultis = multis.filter((details) => details.dataset.key); // status, created by
  const columnsMenu = document.getElementById("filter-columns");
  const lists = {
    statuses: JSON.parse(form.dataset.statuses || "[]"),
    sortKeys: JSON.parse(form.dataset.sortKeys || "[]"),
    defaultDesc: JSON.parse(form.dataset.sortDefaultDesc || "{}"), // which sorts go newest or most first by default
  };
  const SPRITE = live.querySelector("use").getAttribute("href").split("#")[0];
  const IDLE = live.querySelector("span").textContent;
  let seq = 0,
    typing,
    resetTimer;

  function indicator(state, text) {
    const use = live.querySelector("use");
    live.classList.toggle("busy", state === "busy");
    live.classList.toggle("updated", state === "done");
    use.setAttribute("href", `${SPRITE}#${state === "done" ? "check" : "refresh"}`);
    live.querySelector("span").textContent = text;
    clearTimeout(resetTimer);
    if (state === "done") resetTimer = setTimeout(() => indicator("idle", IDLE), 1400);
  }

  // a term with a key and an operator but no value yet (status=) filters nothing
  const hasFilter = (parsed) => parsed.toks.some((t) => t.kind === "term" && t.key !== "sortby" && !t.empty);

  const defaultColumns = () => (columnsMenu?.dataset.default ? columnsMenu.dataset.default.split(",") : []);
  const chosenColumns = () =>
    columnsMenu ? [...columnsMenu.querySelectorAll("input[type=checkbox]:checked")].map((box) => box.value) : [];
  const columnsDiffer = () => chosenColumns().join() !== defaultColumns().join();

  function setClear(active) {
    // disabled, never hidden: nothing may move
    clear.setAttribute("aria-disabled", String(!active));
    if (active) clear.removeAttribute("tabindex");
    else clear.tabIndex = -1;
  }

  // ---- the highlighted search bar
  const field = form.querySelector(".qfield"),
    removers = form.querySelector(".qx-layer");

  // one small x after every term, every outermost group and every operator, inside the padding of its chip
  function drawRemovers() {
    removers.replaceChildren();
    const base = field.getBoundingClientRect();
    highlight.querySelectorAll(".q-term, .q-group, .q-op").forEach((el) => {
      if (el.classList.contains("q-group") && el.parentElement.closest(".q-group")) return;
      if (!el.classList.contains("q-group") && el.closest(".q-group")) return; // a group is removed as a whole
      const x = el.getBoundingClientRect().right - base.left;
      if (x < 6 || x > base.width - 6) return; // scrolled out of view
      const label = input.value.slice(Number(el.dataset.from), Number(el.dataset.to)).trim();
      const button = document.createElement("button");
      button.type = "button";
      button.className = "qx";
      button.tabIndex = -1; // the text itself is the keyboard way to edit
      button.title = `Remove ${label}`;
      button.setAttribute("aria-label", `Remove ${label}`);
      button.dataset.from = el.dataset.from;
      button.dataset.to = el.dataset.to;
      if (el.classList.contains("q-op")) button.dataset.kind = "operator";
      button.style.left = `${x - 11}px`; // inside the chip's right padding, a little after the text
      button.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${SPRITE}#x"/></svg>`; // an icon sits exactly in the middle
      removers.append(button);
    });
  }

  removers.addEventListener("mousedown", (event) => event.preventDefault()); // keep the focus where it is
  removers.addEventListener("click", (event) => {
    const button = event.target.closest(".qx");
    if (!button) return;
    const cut = button.dataset.kind === "operator" ? removeOperator : removePart;
    setQuery(cut(input.value, Number(button.dataset.from), Number(button.dataset.to)));
    input.focus();
  });
  window.addEventListener("resize", drawRemovers);

  function syncScroll() {
    highlight.style.transform = `translateX(${-input.scrollLeft}px)`;
    drawRemovers(); // the chips moved with the scroll
  }

  function draw() {
    renderQuery(parseQuery(input.value), input.value, highlight, lists);
    syncScroll();
    requestAnimationFrame(syncScroll); // the caret may have moved the text after the event
  }

  // ---- query -> dropdowns
  function showMulti(details, derived) {
    const boxes = [...details.querySelectorAll("input[type=checkbox]")];
    const label = details.querySelector(".multi-label");
    if (!details.dataset.allLabel) details.dataset.allLabel = label.textContent;
    details.classList.toggle("custom", Boolean(derived.custom));
    const on = new Set(derived.custom ? [] : derived.set.map((v) => v.toLowerCase()));
    boxes.forEach((box) => (box.checked = on.has(box.value.toLowerCase())));
    const names = boxes.filter((box) => box.checked).map((box) => box.nextElementSibling.textContent);
    if (derived.custom) label.textContent = "Custom";
    else if (derived.set.length === boxes.length) label.textContent = details.dataset.allLabel;
    else if (!names.length) label.textContent = "None";
    else if (names.length <= 2) label.textContent = names.join(", ");
    else label.textContent = `${names.length} selected`;
  }

  function syncControls() {
    const parsed = parseQuery(input.value);
    queryMultis.forEach((details) =>
      showMulti(details, deriveSet(parsed, details.dataset.key, JSON.parse(details.dataset.all || "[]"))),
    );
    const wanted = deriveSort(parsed, lists.sortKeys, lists.defaultDesc);
    sortSelect.value = [...sortSelect.options].some((o) => o.value === wanted) ? wanted : DEFAULT_SORT;
    refreshSelect(sortSelect);
    setClear(input.value.trim() !== "" || columnsDiffer());
  }

  // ---- dropdowns -> query
  function setQuery(text, { fetch = true } = {}) {
    input.value = text;
    draw();
    syncControls();
    if (fetch) update();
  }

  queryMultis.forEach((details) => {
    details.addEventListener("change", () => {
      const all = JSON.parse(details.dataset.all || "[]");
      const checked = [...details.querySelectorAll("input[type=checkbox]:checked")].map((b) => b.value);
      // the query always says what the boxes say: all = every value, none = every value excluded (key!=...), so
      // nothing is shown. The creators are the open-ended list, so "every creator" is a * (new users are included).
      const everything = checked.length === all.length,
        none = checked.length === 0 && all.length > 0;
      const every = details.dataset.key === "creator" ? ["*"] : all;
      setQuery(
        editQuery(
          input.value,
          details.dataset.key,
          everything || none ? every : all.filter((v) => checked.includes(v)),
          none,
        ),
      );
    });
  });

  // Columns are a view setting, not part of the query: remembered in a cookie so the server draws them.
  // At least one column stays: the last one that is on can't be switched off (it is disabled until another is on).
  const lockLastColumn = () => {
    if (!columnsMenu) return;
    const on = [...columnsMenu.querySelectorAll("input[type=checkbox]:checked")];
    columnsMenu
      .querySelectorAll("input[type=checkbox]")
      .forEach((box) => (box.disabled = on.length === 1 && box.checked));
  };
  lockLastColumn();
  if (columnsMenu) {
    columnsMenu.addEventListener("change", (event) => {
      if (!columnsMenu.querySelector("input[type=checkbox]:checked")) {
        event.target.checked = true;
        lockLastColumn();
        return;
      } // (keyboard or script)
      lockLastColumn();
      const all = JSON.parse(columnsMenu.dataset.all || "[]");
      const chosen = [...columnsMenu.querySelectorAll("input[type=checkbox]:checked")].map((box) => box.value);
      const ordered = all.filter((key) => chosen.includes(key));
      document.cookie = `${columnsMenu.dataset.cookie}=${ordered.join(",")}; path=${columnsMenu.dataset.cookiePath || "/"}; max-age=31536000; SameSite=Lax`;
      columnsMenu.querySelector(".multi-label").textContent = `${ordered.length} of ${all.length}`;
      setClear(input.value.trim() !== "" || columnsDiffer());
      update();
    });
  }

  sortSelect.addEventListener("change", () => setQuery(editQuery(input.value, "sortby", [sortSelect.value]))); // signed, always

  document.addEventListener("click", (event) => {
    // sortable column headers set the sort in the query
    const link = event.target.closest("#links-results th a");
    if (link) {
      event.preventDefault();
      setQuery(new URL(link.href).searchParams.get("q") || "");
      return;
    }
  });

  // ---- query -> results
  async function update() {
    const q = input.value.trim();
    const url = form.getAttribute("action") + (q ? `?${new URLSearchParams({ q })}` : "");
    const mine = ++seq;
    indicator("busy", "Updating…");
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      if (mine !== seq) return; // a newer change already replaced this one
      if (!swapRegion("links-results", doc)) throw new Error("unexpected page");
      const fresh = document.getElementById("links-results");
      history.replaceState(null, "", url);
      const n = Number(fresh.dataset.count),
        total = Number(fresh.dataset.overall);
      indicator("done", hasFilter(parseQuery(q)) ? `Updated · ${n} of ${total}` : "Updated");
    } catch {
      location.href = url; // fall back to a normal page load
    }
  }

  // A parenthesis (or an operator next to one) typed against a term gets a space on each side, so the chips and
  // their x never run into it. Only while typing or pasting: deleting a space must stay possible.
  function spaceOut() {
    const text = input.value;
    const toks = parseQuery(text).toks.filter((t) => t.kind !== "ws");
    const special = (t) => ["lpar", "rpar", "and", "or"].includes(t.kind);
    const paren = (t) => t.kind === "lpar" || t.kind === "rpar";
    const at = [];
    for (let i = 0; i < toks.length - 1; i++) {
      const a = toks[i],
        b = toks[i + 1];
      if (a.end !== b.start || a.kind === "not") continue; // already apart, or a "!" that belongs to the next term
      if (!special(a) && !special(b)) continue;
      if (paren(a) && paren(b)) continue; // ((a)) stays as typed
      at.push(a.end);
    }
    if (!at.length) return false;
    let caret = input.selectionStart,
      out = "",
      last = 0;
    for (const p of at) {
      out += `${text.slice(last, p)} `;
      last = p;
      if (p <= input.selectionStart) caret++;
    }
    input.value = out + text.slice(last);
    input.setSelectionRange(caret, caret);
    return true;
  }

  input.addEventListener("input", (event) => {
    if (event.inputType?.startsWith("insert")) spaceOut();
    draw();
    syncControls();
    clearTimeout(typing);
    typing = setTimeout(update, 250);
  });
  ["keyup", "click", "focus", "select", "scroll"].forEach((name) => input.addEventListener(name, syncScroll));
  document.addEventListener("selectionchange", () => {
    if (document.activeElement === input) syncScroll();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(typing);
    update();
  });

  clear.addEventListener("click", (event) => {
    // back to the start: no query, no sort, the default columns
    event.preventDefault();
    if (clear.getAttribute("aria-disabled") === "true") return;
    if (columnsMenu) {
      const all = JSON.parse(columnsMenu.dataset.all || "[]"),
        wanted = defaultColumns();
      columnsMenu.querySelectorAll("input[type=checkbox]").forEach((box) => (box.checked = wanted.includes(box.value)));
      lockLastColumn();
      columnsMenu.querySelector(".multi-label").textContent = `${wanted.length} of ${all.length}`;
      document.cookie = `${columnsMenu.dataset.cookie}=${wanted.join(",")}; path=${columnsMenu.dataset.cookiePath || "/"}; max-age=31536000; SameSite=Lax`;
    }
    setQuery("");
  });

  const helpToggle = document.getElementById("q-help-toggle"),
    help = document.getElementById("q-help");
  helpToggle.addEventListener("click", () => {
    help.hidden = !help.hidden;
    helpToggle.setAttribute("aria-expanded", String(!help.hidden));
  });

  setQuery(input.value, { fetch: false }); // draw the first time

  // what the live-visits script (live.js) needs from this one
  window.deroFilters = { form, input, lists, live, update, indicator };
})();
