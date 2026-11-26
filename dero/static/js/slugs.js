// ---- Slug colouring: a stored user option (cookie dero_hl, read by the server; CSS reacts to html[data-hl]) ----
// Digits blue and symbols red, like Bitwarden does for passwords. Same grouping as highlight_slug in Python.
function coloredSlug(slug) {
  const out = document.createDocumentFragment();
  for (const run of slug.match(/\d+|[^\p{L}\d]+|\p{L}+/gu) || []) {
    if (/^\p{L}/u.test(run)) { out.append(run); continue; }
    const span = document.createElement("span");
    span.className = /^\d/.test(run) ? "hl-digit" : "hl-symbol";
    span.textContent = run;
    out.append(span);
  }
  return out;
}

// ---- The slug input of a link's details: coloured text behind the transparent input ----
function paintSlugEdit(box) {
  const input = box.querySelector("input"), layer = box.querySelector(".slug-hl");
  const code = document.createElement("code"); code.className = "slug"; code.append(coloredSlug(input.value)); layer.replaceChildren(code);
  code.style.transform = `translateX(${-input.scrollLeft}px)`;   // the layer itself stays put and clips, so nothing can slide under the base address
}
function initSlugEdits(root = document) {
  root.querySelectorAll(".slug-edit:not(.hl-ready)").forEach(initSlugEdit);
}
function initSlugEdit(box) {
  box.classList.add("hl-ready");
  paintSlugEdit(box);
  const input = box.querySelector("input");
  input.addEventListener("input", () => paintSlugEdit(box));
  input.addEventListener("scroll", () => paintSlugEdit(box));
  input.form?.addEventListener("reset", () => setTimeout(() => paintSlugEdit(box), 0));
}
initSlugEdits();
