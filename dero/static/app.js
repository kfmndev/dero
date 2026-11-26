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

document.addEventListener("click", (event) => {
  const row = event.target.closest("tr.item");
  if (!row) return;
  if (event.target.closest(".expand")) return toggleRow(row);
  if (event.target.closest("a, button, input, label, form, select")) return;
  toggleRow(row);
});
