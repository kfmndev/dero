// ---- Dropdowns ----
// Every <select> is upgraded to the same dropdown as the checkbox lists (details/summary + a panel). The
// <select> stays in the page, hidden: it still holds the value, is submitted with its form and fires the
// same change events, so nothing else needs to know. Without JavaScript the plain <select> works.
function upgradeSelect(select) {
  if (select.dataset.upgraded) return;
  select.dataset.upgraded = "1";
  select.classList.add("native-hidden");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" })
    .getAttribute("href")
    .split("#")[0];
  const owner = select.closest("label") || (select.id && document.querySelector(`label[for="${select.id}"]`));
  const name = owner
    ? [...owner.childNodes]
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent)
        .join("")
        .trim()
    : "";

  const details = document.createElement("details");
  details.className = "multi single";
  const summary = document.createElement("summary");
  if (name) summary.setAttribute("aria-label", name);
  const label = document.createElement("span");
  label.className = "multi-label";
  summary.append(label);
  const panel = document.createElement("div");
  panel.className = "multi-panel single-panel";
  panel.setAttribute("role", "listbox");
  const buttons = [...select.options].map((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "option";
    button.setAttribute("role", "option");
    button.dataset.value = option.value;
    button.innerHTML = `<span></span><svg class="icon" aria-hidden="true"><use href="${sprite}#check"/></svg>`;
    button.firstChild.textContent = option.textContent;
    panel.append(button);
    return button;
  });
  details.append(summary, panel);
  select.after(details);

  const sync = () => {
    const current = select.options[select.selectedIndex];
    label.textContent = current ? current.textContent : "";
    buttons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.value === select.value)));
  };
  sync();
  select.addEventListener("dero:refresh", sync);
  select.addEventListener("change", sync);
  if (select.form) select.form.addEventListener("reset", () => setTimeout(sync, 0));

  panel.addEventListener("click", (event) => {
    const button = event.target.closest(".option");
    if (!button) return;
    details.open = false;
    summary.focus();
    if (select.value !== button.dataset.value) {
      select.value = button.dataset.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    sync();
  });

  details.addEventListener("toggle", () => {
    if (details.open) (panel.querySelector('[aria-selected="true"]') || buttons[0]).focus();
  });

  details.addEventListener("keydown", (event) => {
    // arrow keys move through the options
    const at = buttons.indexOf(document.activeElement);
    const to = { ArrowDown: at + 1, ArrowUp: at < 0 ? buttons.length - 1 : at - 1, Home: 0, End: buttons.length - 1 }[
      event.key
    ];
    if (to === undefined) return;
    event.preventDefault();
    if (!details.open) {
      details.open = true;
      return;
    }
    buttons[(to + buttons.length) % buttons.length].focus();
  });
}

document.querySelectorAll("select").forEach(upgradeSelect);

// One handler for every dropdown (checkbox lists and the upgraded selects): a click outside or Escape closes it.
document.addEventListener("click", (event) => {
  document.querySelectorAll("details.multi[open]").forEach((d) => {
    if (!d.contains(event.target)) d.open = false;
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details.multi[open]").forEach((d) => {
    d.open = false;
    d.querySelector("summary").focus();
  });
});
