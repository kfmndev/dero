// ---- Live visits ----
// Uses the search bar's pieces that filters.js hands over (window.deroFilters).
(() => {
  const { form, input, lists, update } = window.deroFilters || {};
  if (!form) return;
  const live = document.getElementById("live-toggle");

  // An option in the settings: the server pushes a message when a counter goes up (server-sent
  // events). The row of a visited slug lights up and its count is changed in place; the table is only fetched again
  // when the order depends on the visits or links were created or deleted.
  const LIVE_KEY = "dero.live";
  let source = null,
    hiddenTimer = null,
    dropped = false;
  const liveOn = () => {
    try {
      return localStorage.getItem(LIVE_KEY) === "1";
    } catch {
      return false;
    }
  };
  const sortsByVisits = () =>
    /visits$/.test(deriveSort(parseQuery(input.value), lists.sortKeys, lists.defaultDesc) || "");

  function flash(row) {
    row.classList.remove("visited");
    void row.offsetWidth; // restart the animation
    row.classList.add("visited");
    setTimeout(() => row.classList.remove("visited"), 2600);
  }

  async function visited(changed) {
    const names = changed.map((c) => c.slug);
    if (sortsByVisits()) await update();
    else {
      let added = 0;
      for (const c of changed) {
        const row = document.querySelector(`#links-results tr.item[data-id="${c.id}"]`);
        if (!row) continue;
        row.dataset.visits = String(c.visits);
        const cell = row.querySelector("td.col-visits");
        if (cell) cell.textContent = String(c.visits);
        added += c.delta;
      }
      const total = document.querySelector("#links-results tfoot td.num");
      if (total && added) total.textContent = String(Number(total.textContent) + added);
    }
    for (const c of changed) {
      const row = document.querySelector(`#links-results tr.item[data-id="${c.id}"]`);
      if (row) flash(row);
    }
    // one pinned toast, always about the latest visit; it stays until its x is clicked
    const first = names[0];
    toast("live", `Live · ‹${first}›${names.length > 1 ? ` and ${names.length - 1} more` : ""} visited`, {
      key: "live",
    });
  }

  function openStream() {
    if (source || typeof EventSource === "undefined") return;
    source = new EventSource(form.dataset.liveUrl);
    source.addEventListener("visit", (event) => visited(JSON.parse(event.data)));
    source.addEventListener("refresh", () => update());
    source.addEventListener("open", () => {
      if (dropped) {
        dropped = false;
        update();
      }
    }); // after a gap: catch up
    source.addEventListener("error", () => {
      dropped = true;
    }); // the browser reconnects itself
  }

  function closeStream() {
    if (source) source.close();
    source = null;
  }

  function setLive(on) {
    closeStream();
    live.classList.toggle("is-live", on);
    if (on) openStream();
    else dismissToast("live", true);
  }

  // a tab nobody looks at gives its connection (a worker thread) back after a while
  document.addEventListener("visibilitychange", () => {
    clearTimeout(hiddenTimer);
    if (!liveOn()) return;
    if (document.visibilityState === "hidden") hiddenTimer = setTimeout(closeStream, 30000);
    else if (!source) {
      openStream();
      dropped = true;
    }
  });

  document.addEventListener("dero:live", () => setLive(liveOn()));
  setLive(liveOn());
})();
