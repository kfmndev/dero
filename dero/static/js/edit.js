// ---- Editing a link in its details (target, short link, expiry) ----
// The switch enables the date field (off = never expires). "Update" and
// "Discard" stay disabled until something differs from what is saved. The
// target and slug inputs sit in other places of the row and belong to the
// form through their form="" attribute.
function syncEdit(form) {
  const toggle = form.querySelector(".expiry-switch"),
    date = form.elements.expires_at;
  const target = form.elements.target,
    slug = form.elements.slug;
  date.disabled = !toggle.checked;
  date.required = toggle.checked;
  const dirty =
    toggle.checked !== toggle.defaultChecked ||
    (toggle.checked && date.value !== date.defaultValue) ||
    target.value !== target.defaultValue ||
    slug.value !== slug.defaultValue;
  for (const button of document.querySelectorAll(`[form="${form.id}"], [data-discard="${form.id}"]`)) {
    if (button.dataset.discard) button.hidden = false; // without JavaScript there is nothing to discard
    if (button.tagName === "BUTTON") button.disabled = !dirty;
  }
}

function syncAllEdit() {
  document.querySelectorAll(".edit-form").forEach(syncEdit);
}

function editFormOf(element) {
  const form = element.form;
  return form?.classList.contains("edit-form") ? form : null;
}

document.addEventListener("change", (event) => {
  const form = editFormOf(event.target);
  if (!form) return;
  syncEdit(form);
  if (event.target.classList.contains("expiry-switch") && event.target.checked) form.elements.expires_at.focus();
});

document.addEventListener("input", (event) => {
  const form = editFormOf(event.target);
  if (!form) return;
  event.target.removeAttribute("aria-invalid");
  if (event.target.name === "target" || event.target.name === "expires_at") forgetWarning(form);
  syncEdit(form);
});

document.addEventListener("click", (event) => {
  const discard = event.target.closest("[data-discard]");
  if (!discard) return;
  const form = document.getElementById(discard.dataset.discard);
  form.reset(); // back to what is saved (reaches the inputs with form="")
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  forgetWarning(form);
  syncEdit(form);
});

// Check the edit form before it is sent; errors go to the "All links" card.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.classList?.contains("edit-form")) return;
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  const found = linkProblem(form, {
    reserved: (form.dataset.reserved || "").split(",").filter(Boolean),
    savedSlug: form.elements.slug.defaultValue,
    slugRequired: true,
    dateWhenOn: true,
  });
  if (!found) {
    if (needsLookup(form)) {
      event.preventDefault();
      lookupThenResubmit(form);
      return;
    }
    warnFirst(form, event, "Update", (message, _field, icon) =>
      showNotice(`link-${form.id.slice(1)}-notices`, message, "warn", icon),
    );
    return;
  }
  event.preventDefault();
  const [field, message] = found;
  field.setAttribute("aria-invalid", "true");
  showNotice(`link-${form.id.slice(1)}-notices`, message, "error", problemIcon(field, message));
  field.focus();
});
syncAllEdit();
