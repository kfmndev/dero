// Basics every page uses: copying a URL, opening a link's details, showing times in the viewer's zone,
// and swapping a region of the page for the same region of a freshly fetched one.
// Copy a short link (or the link to a search) to the clipboard: buttons carry the text in data-copy.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
  } catch {
    // clipboard needs HTTPS or localhost
    return toast("error", "Couldn't copy. Copying needs a secure (https) address.", { key: "copy" });
  }
  toast("ok", button.id === "q-share" ? "Link to this search copied" : "Copied to clipboard");
  const use = button.querySelector("use");
  const sprite = use.getAttribute("href").split("#")[0];
  button.dataset.icon ??= use.getAttribute("href"); // the button's own icon, put back below
  use.setAttribute("href", `${sprite}#check`);
  button.classList.add("done");
  setTimeout(() => {
    use.setAttribute("href", button.dataset.icon);
    button.classList.remove("done");
  }, 1500);
});

// Click a row to show or hide its details (the row after it).
function toggleRow(row) {
  const detail = row.nextElementSibling;
  if (!detail?.classList.contains("detail")) return;
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
// The viewer's own numeric format. A moment (created) is shown with its time in the viewer's zone;
// an expiry is a day that was picked, so it keeps that day (formatted as UTC, which is how it is stored).
const DATE_FORMAT = { year: "numeric", month: "2-digit", day: "2-digit" };
const LOCAL_DATE = new Intl.DateTimeFormat(undefined, DATE_FORMAT);
const LOCAL_DATETIME = new Intl.DateTimeFormat(undefined, { ...DATE_FORMAT, hour: "2-digit", minute: "2-digit" });
const PICKED_DAY = new Intl.DateTimeFormat(undefined, { ...DATE_FORMAT, timeZone: "UTC" });

function localizeTimes(root = document) {
  root.querySelectorAll("time.localtime[datetime]").forEach((el) => {
    const date = new Date(el.getAttribute("datetime"));
    if (!Number.isNaN(date.getTime()))
      el.textContent = (el.dataset.day !== undefined ? PICKED_DAY : LOCAL_DATETIME).format(date);
  });
  root.querySelectorAll(".expired-mark[data-expired]").forEach((el) => {
    // "Expired on <local date>", the UTC time stays in the column's tooltip
    const date = new Date(el.dataset.expired);
    if (Number.isNaN(date.getTime())) return;
    el.title = `Expired on ${PICKED_DAY.format(date)}`;
    el.setAttribute("aria-label", el.title);
  });
}

// Replace one region of the page with the same region from a freshly fetched page.
// Rows that were open stay open. Returns false if the region is missing.
function swapRegion(id, doc) {
  const current = document.getElementById(id),
    fresh = doc.getElementById(id);
  if (!current || !fresh) return false;
  // The parsed copy treats <noscript> content as real elements; drop it so nothing from it can apply.
  fresh.querySelectorAll("noscript").forEach((el) => el.remove());
  const open = [...current.querySelectorAll("tr.detail:not([hidden])")].map((row) => row.id);
  current.replaceWith(document.importNode(fresh, true));
  for (const rowId of open) {
    const detail = document.getElementById(rowId);
    if (detail?.previousElementSibling) toggleRow(detail.previousElementSibling);
  }
  if (typeof syncAllEdit === "function") syncAllEdit();
  if (typeof initSlugEdits === "function") initSlugEdits();
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

// Ask an upgraded <select> (see dropdowns.js) to redraw after a script changed its value. It is here, not in
// dropdowns.js, because scripts loaded before that one call it while the page loads.
function refreshSelect(select) {
  select.dispatchEvent(new Event("dero:refresh"));
}

localizeTimes();
