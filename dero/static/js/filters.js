// ---- Filters, search and sorting apply by themselves ----
// The search box holds the whole state as one query. The dropdowns show it (and edit it); changing
// either one fetches the list again and swaps only the table, so the page doesn't jump and the
// search box keeps focus.
(() => {
  const form = document.getElementById("filters");
  if (!form) return;
  const input = document.getElementById("q");
  const highlight = form.querySelector(".qhl");
  const sortSelect = document.getElementById("filter-sort");
  const clear = document.getElementById("reset-filters");
  const multis = [...form.querySelectorAll("details.multi")];
  const queryMultis = multis.filter((details) => details.dataset.key); // status, created by
  const columnsMenu = document.getElementById("filter-columns");
  const lists = {
    statuses: JSON.parse(form.dataset.statuses || "[]"),
    sortKeys: JSON.parse(form.dataset.sortKeys || "[]"),
    defaultDesc: JSON.parse(form.dataset.sortDefaultDesc || "{}"), // which sorts go newest or most first by default
  };
  // the setting "Explicit search terms" (settings dialog): the dropdowns write even the choices that mean the default
  const explicit = () => {
    try {
      return localStorage.getItem("dero.explicit") === "1";
    } catch {
      return false;
    }
  };
  const SPRITE = (document.querySelector("svg.icon use") || { getAttribute: () => "" })
    .getAttribute("href")
    .split("#")[0];
  let seq = 0,
    typing;

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

  // One small x after every term, group, operator and stray ")", inside the padding of its chip or pill: the room for an
  // x exists only where there is one. A group's x removes the whole group, the parentheses and what is between them.
  function drawRemovers() {
    removers.replaceChildren();
    const base = field.getBoundingClientRect();
    highlight.querySelectorAll(".q-term, .q-group, .q-op, .q-stray").forEach((el) => {
      // A closed group has its x in its closing parenthesis, which is a pill like and / or (or, if that one is stuck to
      // its neighbours, after it, in the room the group keeps for it). An unclosed group has none: its ( has one. Every
      // other x is in the right padding of its chip.
      if (el.classList.contains("q-unclosed")) return;
      const closing = el.classList.contains("q-group") ? el.lastElementChild : null;
      const pill = closing?.classList.contains("q-pill") && closing.textContent === ")";
      if (el.classList.contains("q-group") && !pill && el.parentElement.closest(".q-group")) return; // no room for a second x
      const anchor = pill ? closing : el;
      const x = anchor.getBoundingClientRect().right - base.left - field.clientLeft; // (the layer starts inside the border)
      if (x < 6 || x > base.width - 6) return; // scrolled out of view
      const label = queryText().slice(Number(el.dataset.from), Number(el.dataset.to)).trim();
      const button = document.createElement("button");
      button.type = "button";
      button.className = "qx";
      button.tabIndex = -1; // the text itself is the keyboard way to edit
      button.title = `Remove ${label}`;
      button.setAttribute("aria-label", `Remove ${label}`);
      button.dataset.from = el.dataset.from;
      button.dataset.to = el.dataset.to;
      if (el.classList.contains("q-op") || el.classList.contains("q-stray")) button.dataset.kind = "operator"; // just itself
      // the x sits in the middle of the space after the text: for a chip that is the right padding plus the 1px ring of
      // the chip, for a group the padding after its closing parenthesis (a group has no ring)
      // the x sits in the middle of the space after the text: the right padding, plus the border of a pill or the 1px
      // ring around a chip (which is outside its box)
      const style = getComputedStyle(anchor);
      const space = Number.parseFloat(style.paddingRight) + Number.parseFloat(style.borderRightWidth);
      const ring = anchor.classList.contains("q-term") ? 1 : 0;
      button.style.left = `${x - (space - ring) / 2 - 5}px`; // (the x is 10px wide)
      button.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${SPRITE}#x"/></svg>`; // an icon sits exactly in the middle
      removers.append(button);
    });
  }

  // While the pointer is on an x, everything a click on it would remove is marked (dimmed; a group is outlined too):
  // a group's x removes the parentheses and what is inside, and the term's or group's x also the and / or joining it
  function markRemoval(button) {
    const from = Number(button.dataset.from),
      to = Number(button.dataset.to);
    const { start, end } =
      button.dataset.kind === "operator" ? { start: from, end: to } : partRange(input.value, from, to);
    highlight.querySelectorAll("[data-from]").forEach((el) => {
      const inside = Number(el.dataset.from) >= start && Number(el.dataset.to) <= end;
      if (inside && !el.parentElement.closest(".q-doomed")) el.classList.add("q-doomed");
    });
  }
  const unmarkRemoval = () => highlight.querySelectorAll(".q-doomed").forEach((el) => el.classList.remove("q-doomed"));
  removers.addEventListener("mouseover", (event) => {
    const button = event.target.closest(".qx");
    if (button) markRemoval(button);
  });
  removers.addEventListener("mouseout", unmarkRemoval);

  removers.addEventListener("mousedown", (event) => event.preventDefault()); // keep the focus where it is
  removers.addEventListener("click", (event) => {
    const button = event.target.closest(".qx");
    if (!button) return;
    const cut = button.dataset.kind === "operator" ? removeOperator : removePart;
    setQuery(cut(input.value, Number(button.dataset.from), Number(button.dataset.to)));
    input.focus();
  });
  // The pills have an outline one pixel wide, and their text (so the pill) sits at fractional positions: at some the
  // outline is smeared over two device pixels and looks heavier or lighter than at others, which the browser does not
  // snap for text. So every edge of a pill is moved onto a whole device pixel, by moving its padding and its margin
  // the same amount in opposite directions: the text of the pill, and everything after it, stays where it is.
  function snapPills() {
    const scale = window.devicePixelRatio || 1;
    // the outline is a whole number of device pixels wide (one css pixel, or at a fractional ratio the nearest whole)
    highlight.style.setProperty("--hair", `${Math.max(1, Math.round(scale)) / scale}px`);
    const snap = (edge) => (Math.round(edge * scale) - edge * scale) / scale; // css px to a whole device pixel
    highlight.querySelectorAll(".q-op, .q-paren.q-pill").forEach((el) => {
      el.style.padding = "";
      el.style.margin = "";
      const style = getComputedStyle(el),
        rect = el.getBoundingClientRect();
      const px = (name) => Number.parseFloat(style[name]);
      const [left, right, top, bottom] = [rect.left, rect.right, rect.top, rect.bottom].map(snap);
      el.style.padding = `${px("paddingTop") - top}px ${px("paddingRight") + right}px ${px("paddingBottom") + bottom}px ${px("paddingLeft") - left}px`;
      el.style.marginLeft = `${px("marginLeft") + left}px`;
      el.style.marginRight = `${px("marginRight") - right}px`;
    });
  }

  function syncScroll() {
    highlight.style.transform = `translateX(${-input.scrollLeft}px)`;
    snapPills();
    drawRemovers(); // the chips moved with the scroll
  }
  window.addEventListener("resize", syncScroll); // (also when the zoom changes the pixel ratio)
  document.fonts?.ready.then(syncScroll); // the text moves a little when the font arrives

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

  // the share button copies the address of this search (nothing to share while the box is empty)
  const share = document.getElementById("q-share");
  function syncShare() {
    const q = queryText().trim();
    share.disabled = !q;
    share.dataset.copy = q ? new URL(addressFor(q), location.href).href : "";
  }

  function syncControls() {
    syncShare();
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
  const queryText = () => plainQuery(input.value); // what the box says, with plain spaces: for the address, the server, drafts

  function setQuery(text, { fetch = true } = {}) {
    input.value = spaceQuotes(spaced(text));
    draw();
    syncControls();
    remember(queryText());
    if (fetch) update();
  }

  queryMultis.forEach((details) => {
    details.addEventListener("change", () => {
      const all = JSON.parse(details.dataset.all || "[]");
      const checked = [...details.querySelectorAll("input[type=checkbox]:checked")].map((b) => b.value);
      // none = every value excluded (key!=...), so nothing is shown. All = no term, or with explicit terms every value.
      // The creators are the open-ended list, so "every creator" is a * (new users are included).
      const everything = checked.length === all.length,
        none = checked.length === 0 && all.length > 0;
      const every = details.dataset.key === "creator" ? ["*"] : all;
      const values =
        none || (everything && explicit()) ? every : everything ? null : all.filter((v) => checked.includes(v));
      setQuery(editQuery(input.value, details.dataset.key, values, none));
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

  const writeSort = (text, value) => editQuery(text, "sortby", sortTermValues(value, lists.defaultDesc, explicit()));
  sortSelect.addEventListener("change", () => setQuery(writeSort(input.value, sortSelect.value)));

  document.addEventListener("click", (event) => {
    // sortable column headers set the sort in the query
    const link = event.target.closest("#links-results th a");
    if (link) {
      event.preventDefault();
      const q = new URL(link.href).searchParams.get("q") || ""; // the address spells the sort out; write it as set
      setQuery(writeSort(q, deriveSort(parseQuery(q), lists.sortKeys, lists.defaultDesc)));
      return;
    }
  });

  // ---- query -> results
  const addressFor = (q) => form.getAttribute("action") + (q ? `?${new URLSearchParams({ q })}` : "");

  // The address holds the query, so a reload keeps it. It is set before the request, not after the answer: a reload
  // while the server still thinks about it must not lose what is in the box.
  const syncAddress = (q) => {
    try {
      history.replaceState(null, "", addressFor(q));
    } catch {} // a browser may refuse when it is called too often
  };

  // The text of the box is also kept in this browser for a moment: the address only follows typing after a short
  // pause, and a reload in that pause would lose the last characters. Used only by a reload, shortly after (below).
  const DRAFT = "dero.query",
    DRAFT_MS = 5000;
  function remember(text) {
    try {
      localStorage.setItem(DRAFT, JSON.stringify({ text, at: Date.now() }));
    } catch {}
  }
  function recentDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(DRAFT) || "null");
      return draft && Date.now() - draft.at < DRAFT_MS ? draft.text : null;
    } catch {
      return null;
    }
  }

  async function update() {
    const q = queryText().trim();
    const url = addressFor(q);
    syncAddress(q);
    const mine = ++seq;
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      if (mine !== seq) return; // a newer change already replaced this one
      if (!swapRegion("links-results", doc)) throw new Error("unexpected page");
    } catch {
      location.href = url; // fall back to a normal page load
    }
  }

  // ---- a link that would discard the search asks first (the setting "Ask before a link discards the search")
  // Only links to this list count: one with another query, or the plain list. Reset and the sort headers handle their
  // own click, links to other pages leave the search in the browser's history (Back brings it back).
  const leave = document.getElementById("leave-query");
  const asksBeforeLeaving = () => {
    try {
      return localStorage.getItem("dero.leave") !== "0";
    } catch {
      return true;
    }
  };
  function askToLeave(now, next) {
    leave.querySelector("#leave-now").textContent = now;
    leave.querySelector("#leave-effect").textContent = next ? "will be replaced by" : "will be cleared.";
    const replacement = leave.querySelector("#leave-next");
    replacement.hidden = !next;
    replacement.textContent = next;
    return new Promise((resolve) => {
      leave.addEventListener("close", () => resolve(leave.returnValue === "discard"), { once: true });
      leave.returnValue = "keep";
      leave.showModal();
    });
  }
  if (leave && typeof leave.showModal === "function") {
    leave.addEventListener("click", (event) => {
      if (event.target === leave) leave.close("keep");
    }); // a click outside keeps the search
    document.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const link = event.target.closest("a[href]");
      const now = queryText().trim();
      if (!link || !now || link.target === "_blank" || link.hasAttribute("download") || !asksBeforeLeaving()) return;
      const to = new URL(link.href, location.href);
      if (to.origin !== location.origin || to.pathname !== new URL(form.action).pathname) return;
      const next = (to.searchParams.get("q") || "").trim();
      if (next === now) return;
      event.preventDefault();
      askToLeave(now, next).then((discard) => {
        if (discard) location.href = link.href;
      });
    });
  }

  // Rewrites the box as one edit that the browser can undo: setting input.value would wipe its undo history (Ctrl+Z
  // would stop at the first space that was tidied). Only the part that differs is replaced, through the editing
  // commands; the input event they cause is ignored (rewriting). The selection is the caller's to set.
  let rewriting = false;
  function rewriteBox(text) {
    const old = input.value;
    if (text === old) return;
    let from = 0,
      oldEnd = old.length,
      newEnd = text.length;
    while (from < oldEnd && from < newEnd && old[from] === text[from]) from++;
    while (oldEnd > from && newEnd > from && old[oldEnd - 1] === text[newEnd - 1]) {
      oldEnd--;
      newEnd--;
    }
    rewriting = true;
    input.setSelectionRange(from, oldEnd);
    const inserted = text.slice(from, newEnd);
    if (inserted) document.execCommand("insertText", false, inserted);
    else document.execCommand("delete");
    rewriting = false;
    if (input.value !== text) input.value = text; // the browser refused: set it (the undo history is lost then)
  }

  // A parenthesis (or an operator next to one) typed against a term or another parenthesis gets a space on each side
  // (see missingSpaces), so the chips and their x never run into it. Only while typing or pasting: deleting a space
  // must stay possible. A query that comes from elsewhere (the address, a dropdown) is spaced the same way in setQuery.
  function spaceOut() {
    const text = input.value;
    const at = missingSpaces(text);
    if (!at.length) return false;
    let caret = input.selectionStart,
      out = "",
      last = 0;
    for (const p of at) {
      out += `${text.slice(last, p)} `;
      last = p;
      if (p <= input.selectionStart) caret++;
    }
    rewriteBox(out + text.slice(last));
    input.setSelectionRange(caret, caret);
    return true;
  }

  // Keeps the look-alike spaces right while typing or pasting: a quote opened or closed changes which spaces are inside
  // quotes. The selection stays where it was.
  function showQuotedSpaces() {
    const fixed = spaceQuotes(input.value);
    if (fixed === input.value) return;
    const { selectionStart, selectionEnd, selectionDirection } = input;
    rewriteBox(fixed);
    input.setSelectionRange(selectionStart, selectionEnd, selectionDirection);
  }

  // Dragging selected text out of the box hands over plain spaces too
  input.addEventListener("dragstart", (event) => {
    const { selectionStart: from, selectionEnd: to } = input;
    if (from !== to) event.dataTransfer.setData("text/plain", plainQuery(input.value.slice(from, to)));
  });

  // Copying or cutting hands over plain spaces, never the look-alikes
  for (const name of ["copy", "cut"]) {
    input.addEventListener(name, (event) => {
      const { selectionStart: from, selectionEnd: to } = input;
      if (from === to) return;
      event.clipboardData.setData("text/plain", plainQuery(input.value.slice(from, to)));
      event.preventDefault();
      if (name === "cut") {
        input.setRangeText("", from, to, "end");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
  }

  // Setting the value while an input method is composing (Japanese, Chinese ...) would cancel the composition: the
  // spaces are tidied when it ends instead
  const tidy = (event) => {
    if (event.inputType?.startsWith("insert")) spaceOut();
    showQuotedSpaces();
  };
  input.addEventListener("compositionend", () => {
    tidy({ inputType: "insertCompositionText" });
    draw();
    syncControls();
  });

  input.addEventListener("input", (event) => {
    if (rewriting) return; // our own edit (rewriteBox): the event of the one that caused it does the rest
    // not while composing (it would cancel it), and not for undo or redo (the user is going back, not typing)
    if (!event.isComposing && !event.inputType?.startsWith("history")) tidy(event);
    draw();
    syncControls();
    remember(queryText());
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
  // the examples in the help are drawn as the search bar draws a query
  help.querySelectorAll("[data-q]").forEach((el) => {
    const text = spaceQuotes(spaced(el.dataset.q)); // spaced: room around parentheses, as in the bar
    renderQuery(parseQuery(text), text, el, lists);
  });

  // After a reload within moments of typing, what was typed is put back (the address may not have caught up yet)
  const typed = performance.getEntriesByType("navigation")[0]?.type === "reload" ? recentDraft() : null;
  if (typed !== null && typed !== queryText()) setQuery(typed);
  else setQuery(input.value, { fetch: false }); // draw the first time; the draft is now what this page shows

  // what the live-visits script (live.js) needs from this one
  window.deroFilters = { form, input, lists, update };
})();
