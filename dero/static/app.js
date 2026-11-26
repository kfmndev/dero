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
    if (!Number.isNaN(date.getTime())) el.textContent = (el.dataset.day !== undefined ? PICKED_DAY : LOCAL_DATETIME).format(date);
  });
  root.querySelectorAll(".expired-mark[data-expired]").forEach((el) => {     // "Expired on <local date>", the UTC time stays in the column's tooltip
    const date = new Date(el.dataset.expired);
    if (Number.isNaN(date.getTime())) return;
    el.title = `Expired on ${PICKED_DAY.format(date)}`;
    el.setAttribute("aria-label", el.title);
  });
}

// Replace one region of the page with the same region from a freshly fetched page.
// Rows that were open stay open. Returns false if the region is missing.
function swapRegion(id, doc) {
  const current = document.getElementById(id), fresh = doc.getElementById(id);
  if (!current || !fresh) return false;
  // The parsed copy treats <noscript> content as real elements; drop it so nothing from it can apply.
  fresh.querySelectorAll("noscript").forEach((el) => el.remove());
  const open = [...current.querySelectorAll("tr.detail:not([hidden])")].map((row) => row.id);
  current.replaceWith(document.importNode(fresh, true));
  for (const rowId of open) {
    const detail = document.getElementById(rowId);
    if (detail && detail.previousElementSibling) toggleRow(detail.previousElementSibling);
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

// ---- Checks shared by the "New link" form and the edit form in a link's details ----
const SLUG_RE = /^[A-Za-z0-9._~-]{1,64}$/;                    // what a URL path never needs to escape
const BAD_SLUG = "Slug: letters, digits and - _ . ~ only, up to 64.";
const DOTS_ONLY = "A slug can't be just dots.";
const slugProblem = (value) => (!SLUG_RE.test(value) ? BAD_SLUG : /^\.+$/.test(value) ? DOTS_ONLY : null);
const BAD_URL = "Target must be a valid http:// or https:// URL.";

// Returns [field, message] for the first problem, or null. The server repeats every check.
// `generator` = the "New link" form (slug mode, alphabet and length); otherwise a plain slug field is checked.
function linkProblem(form, { reserved = [], savedSlug = null, slugRequired = false, dateWhenOn = false, generator = false } = {}) {
  const target = form.elements.target, expires = form.elements.expires_at;
  const url = target.value.trim();
  if (!url) return [target, "Enter the URL to shorten."];
  let parsed;
  try { parsed = new URL(url); } catch { return [target, BAD_URL]; }
  if (!/^https?:$/.test(parsed.protocol) || !parsed.host || url.length > 2048) return [target, BAD_URL];
  if (generator) {
    const found = generatorProblem(form, reserved);
    if (found) return found;
  } else {
    const slug = form.elements.slug, s = slug.value.trim();
    if (!s && slugRequired) return [slug, "Enter a slug."];
    if (s && slugProblem(s)) return [slug, slugProblem(s)];
    if (s && s !== savedSlug && reserved.includes(s)) return [slug, `‹${s}› is reserved.`];
  }
  if (dateWhenOn && !expires.disabled && !expires.value) return [expires, "Pick the last day the link should work, or switch the expiry off."];
  return null;
}

// Slug part of the "New link" form: a typed slug, or the characters and length to generate one from.
function generatorProblem(form, reserved, source = form.elements.slug_source.value) {
  if (source === "slug") {
    const slug = form.elements.slug, s = slug.value.trim();
    if (!s) return [slug, "Enter a slug, or pick a random one."];
    if (slugProblem(s)) return [slug, slugProblem(s)];
    if (reserved.includes(s)) return [slug, `‹${s}› is reserved.`];
    return null;
  }
  if (source === "chars") {
    const field = form.elements.alphabet_custom, chars = [...field.value];
    const bad = [...new Set(chars.filter((c) => !/[A-Za-z0-9._~-]/.test(c)))];
    if (bad.length) {
      const names = bad.slice(0, 6).map((c) => (c === " " ? "space" : `'${c}'`));
      const shown = bad.length > 6 ? `${names.join(", ")}, …`                                              // too many: cut
        : names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;   // "and" before the last
      return [field, `Characters: ${shown} can't be used. Allowed are letters, digits and - _ . ~`];
    }
    if (new Set(chars).size < 2) return [field, "Characters: use at least 2 different ones."];
  }
  const length = form.elements.namedItem("length"), n = Number(length.value);       // (elements.length is the collection's size)
  const min = Number(form.dataset.minLength), max = Number(form.dataset.maxLength);
  if (!Number.isInteger(n) || n < min || n > max) return [length, `Length must be between ${min} and ${max}.`];
  return null;
}

// A slug as it is shown everywhere: in its box, coloured, cut after 20 characters.
function slugBox(slug) {
  const code = document.createElement("code");
  code.className = "slug";
  code.append(coloredSlug(slug.length > 20 ? slug.slice(0, 20) : slug));
  if (slug.length > 20) { code.append("…"); code.title = slug; }
  return code;
}

// Text in which ‹slugs› are marked becomes text with slug boxes.
function setRich(element, text) {
  element.replaceChildren();
  text.split(/‹([^›]*)›/).forEach((part, i) => element.append(i % 2 ? slugBox(part) : part));
}

// Put a message into a card's .notices container (same markup the server renders).
function showNotice(id, message, kind = "error") {          // kind: "error", "warn" or "ok"
  const box = document.getElementById(id);
  if (!box) return;
  const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" }).getAttribute("href").split("#")[0];
  const p = document.createElement("p");
  p.className = kind === "error" ? "form-error" : kind === "warn" ? "form-warn" : "form-ok";
  p.setAttribute("role", kind === "ok" ? "status" : "alert");
  p.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${sprite}#${kind === "ok" ? "check" : "alert"}"/></svg>`;
  const span = document.createElement("span");
  setRich(span, message);
  p.append(span);
  box.replaceChildren(p);
}

// ---- Is this the usual https://domain.tld/path shape? ----
// Returns short reasons why a (valid http/https) URL looks unusual; empty = nothing to warn about.
function unusualUrl(value) {
  const text = value.trim();
  let url;
  try { url = new URL(text); } catch { return []; }          // invalid URLs are errors, handled elsewhere
  const reasons = [];
  const host = url.hostname;
  if (url.protocol === "http:") reasons.push("uses http");
  if (/\s/.test(text)) reasons.push("has spaces");
  if (url.username || url.password) reasons.push("has a login");
  if (host.startsWith("[") || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    reasons.push("is an IP address");
  } else if (!host.includes(".")) {
    reasons.push("has no domain ending");
  } else {
    const tld = host.replace(/\.$/, "").split(".").pop();
    if (!/^(xn--[a-z0-9-]+|[a-z]{2,})$/i.test(tld)) reasons.push("has an odd ending");
  }
  if (url.port) reasons.push("has a port");
  return reasons;
}

const joinList = (items) => (items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0] || "");

// Does another link already point to this address? Asked just before sending (and only for a new or changed address).
function alreadyShortened(slugs, count) {
  if (!slugs.length) return "Target already shortened by someone else.";
  const shown = slugs.slice(0, 3), more = count - shown.length;
  return `Target already shortened: ${shown.map((s) => `‹${s}›`).join(", ")}${more > 0 ? ` and ${more} more` : ""}.`;
}

function needsLookup(form) {
  const target = form.elements.target, url = target.value.trim();
  return Boolean(form.dataset.lookup) && url !== target.defaultValue.trim() && form.dataset.dupFor !== url;
}

// Asks the server, remembers the answer on the form (keyed by the address) and sends the form again.
// A failed lookup never blocks anything: it just counts as "no duplicate".
async function lookupThenResubmit(form) {
  const url = form.elements.target.value.trim();
  if (form.dataset.lookingUp === url) return;               // already asking (e.g. a double click)
  form.dataset.lookingUp = url;
  let answer = { count: 0, slugs: [] };
  try {
    const query = new URLSearchParams({ target: url });
    if (form.dataset.exclude) query.set("exclude", form.dataset.exclude);
    const res = await fetch(`${form.dataset.lookup}?${query}`, { credentials: "same-origin" });
    if (res.ok) answer = await res.json();
  } catch {}
  delete form.dataset.lookingUp;
  if (form.elements.target.value.trim() !== url) return;     // the user changed it meanwhile
  form.dataset.dupFor = url;
  form.dataset.dupCount = String(answer.count);
  form.dataset.dupSlugs = JSON.stringify(answer.slugs);
  form.requestSubmit();
}

// Things worth a second look but not wrong: an unusual address and an expiry in the past. Unchanged values stay quiet.
function linkWarnings(form) {
  const notes = [], fields = [];
  const target = form.elements.target, expires = form.elements.expires_at;
  const url = target.value.trim();
  if (url !== target.defaultValue.trim() && form.dataset.dupFor === url && Number(form.dataset.dupCount) > 0) {
    notes.push(alreadyShortened(JSON.parse(form.dataset.dupSlugs || "[]"), Number(form.dataset.dupCount)));
    fields.push(target);
  }
  if (url !== target.defaultValue.trim()) {
    const reasons = unusualUrl(url);
    if (reasons.length) { notes.push(`Unusual address: ${joinList(reasons)}.`); fields.push(target); }
  }
  if (!expires.disabled && expires.value && expires.value !== expires.defaultValue && expires.value < new Date().toISOString().slice(0, 10)) {
    notes.push("Expiry date is in the past."); fields.push(expires);
  }
  return { notes, fields };
}

// Warn once per combination of values; sending the same thing again goes through. True = the submit was stopped.
function warnFirst(form, event, verb, show) {
  [...form.elements].forEach((el) => el.removeAttribute("data-warn"));
  const { notes, fields } = linkWarnings(form);
  const signature = JSON.stringify([form.elements.target.value.trim(), form.elements.expires_at.value]);
  if (!notes.length || form.dataset.warned === signature) return false;
  event.preventDefault();
  form.dataset.warned = signature;
  fields.forEach((el) => el.setAttribute("data-warn", ""));
  show(`${notes.join(" ")} Press ${verb} again to continue.`, fields[0]);
  fields[0].focus();
  return true;
}

function forgetWarning(form) {
  delete form.dataset.warned;
  delete form.dataset.dupFor; delete form.dataset.dupCount; delete form.dataset.dupSlugs;
  [...form.elements].forEach((el) => el.removeAttribute("data-warn"));
}

// ---- New link form: check it before it is sent, keep what was typed ----
// The form has `novalidate` so the messages appear inside the "New link" card
// instead of in browser bubbles. The server repeats every check.
(function () {
  const form = document.getElementById("new-link");
  if (!form) return;
  const box = document.getElementById("new-link-error");
  const reserved = (form.dataset.reserved || "").split(",").filter(Boolean);
  const alphabets = JSON.parse(form.dataset.alphabets || "{}");
  const hint = form.querySelector(".alphabet-hint");
  const PREFS = "dero.generator";
  const sourceOf = () => form.elements.slug_source.value;
  const lengthField = () => form.elements.namedItem("length");

  function show(message, kind = "error", field = null) {
    const row = (field && field.closest(".nl-row")) || form.querySelector(".nl-row");   // the message sits in the row of the field it is about
    if (message && box.parentElement !== row) row.append(box);
    box.replaceChildren();
    box.className = kind === "warn" ? "form-warn" : "form-error";
    if (!message) return;
    document.getElementById("new-link-notices")?.replaceChildren();   // an old "Created ..." would read as part of this message
    const icon = document.querySelector("svg.icon use");
    const sprite = icon ? icon.getAttribute("href").split("#")[0] : "";
    box.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${sprite}#alert"/></svg>`;
    const span = document.createElement("span");
    setRich(span, message);
    box.append(span);
  }

  // Random or typed: only the fields that belong to the chosen option are shown, and a line below says what it draws from.
  function syncGenerator() {
    const source = sourceOf();
    form.querySelectorAll("[data-when-source]").forEach((el) => (el.hidden = !el.dataset.whenSource.split(" ").includes(source)));
    let text = "";
    if (source === "chars") {
      const chars = [...form.elements.alphabet_custom.value];
      if (chars.length) text = `${chars.length} characters, ${new Set(chars).size} different: ${chars.join("")}`;
    } else if (alphabets[source]) text = alphabets[source];
    hint.textContent = text;
    hint.title = text;                          // long sets are cut with an ellipsis; the tooltip has all of it
  }

  // Generate: draw a slug of the selected type now, put it into the Custom slug field to look at, edit or create.
  // From Custom it uses the random type that was selected last.
  let lastRandom = sourceOf() === "slug" ? "default" : sourceOf();
  const generate = form.querySelector("#new-link-generate");
  const reservedSet = new Set(reserved);
  function randomSlug(kind) {
    const alphabet = kind === "chars" ? [...form.elements.alphabet_custom.value] : [...(alphabets[kind] || alphabets.default)];
    const length = Number(lengthField().value), pool = new Uint32Array(length);
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
    if (found) { found[0].setAttribute("aria-invalid", "true"); show(found[1], "error", found[0]); found[0].focus(); return; }
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

  function savePrefs() {                       // the choice is remembered in this browser
    try {
      localStorage.setItem(PREFS, JSON.stringify({ source: sourceOf(), custom: form.elements.alphabet_custom.value, length: lengthField().value }));
    } catch {}
  }

  function loadPrefs() {
    try {
      const saved = JSON.parse(localStorage.getItem(PREFS) || "null");
      if (!saved) return;
      const select = form.elements.slug_source;
      if ([...select.options].some((o) => o.value === saved.source)) { select.value = saved.source; refreshSelect(select); }
      form.elements.alphabet_custom.value = saved.custom || "";
      if (saved.length) lengthField().value = saved.length;
    } catch {}
  }

  if (form.dataset.fresh === "yes") loadPrefs();   // after a rejected submit the server's values win
  syncGenerator();

  form.addEventListener("submit", (event) => {
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    const found = linkProblem(form, { reserved, generator: true });
    if (!found) {
      if (needsLookup(form)) { event.preventDefault(); lookupThenResubmit(form); return; }
      if (warnFirst(form, event, "Create", (message, field) => show(message, "warn", field))) return;
      return show("");                    // let the browser send it
    }
    event.preventDefault();               // invalid: nothing is sent, nothing is cleared
    const [field, message] = found;
    field.setAttribute("aria-invalid", "true");
    show(message, "error", field);
    field.focus();
  });

  form.addEventListener("input", (event) => {
    event.target.removeAttribute("aria-invalid");
    show("");
    const name = event.target.name;
    if (name === "target" || name === "expires_at") forgetWarning(form);    // a different value deserves a new look
    if (["slug_source", "alphabet_custom", "length"].includes(name)) { syncGenerator(); savePrefs(); }
  });
  form.addEventListener("change", (event) => {            // the dropdown reports `change`
    if (event.target.name === "slug_source") { if (sourceOf() !== "slug") lastRandom = sourceOf(); syncGenerator(); savePrefs(); }
  });
  form.addEventListener("reset", () => {
    forgetWarning(form);
    setTimeout(() => { loadPrefs(); syncGenerator(); }, 0);   // reset restores the defaults; the remembered choice comes back
  });
})();

// ---- The search language ----
// The server filters (dero/query.py). This is the same tokenizer, used to highlight the search bar and to
// keep the dropdowns and the query text in sync.
const QUERY_KEYS = {
  status: "status", created_by: "creator", creator: "creator", owner: "creator", by: "creator",
  slug: "slug", target: "target", created: "created", expires: "expires", sort_by: "sortby", sortby: "sortby", sort: "sortby", order: "sortby",
};

function unquote(text) {
  if (text.length >= 2 && text[0] === '"' && text.endsWith('"')) return text.slice(1, -1);
  return text.startsWith('"') ? text.slice(1) : text;
}

// "a,b,\"c d\"" -> raw pieces; commas inside quotes stay
function splitRaw(rest) {
  const pieces = [];
  let buf = "", quoted = false;
  for (const ch of rest) {
    if (ch === '"') { quoted = !quoted; buf += ch; }
    else if (ch === "," && !quoted) { pieces.push(buf); buf = ""; }
    else buf += ch;
  }
  pieces.push(buf);
  return pieces;
}

function quoteValue(value) {
  return value === "" || /[\s()"]/.test(value) ? `"${value.replace(/"/g, "")}"` : value;
}

function parseQuery(text) {
  const toks = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    const ch = text[i];
    if (/\s/.test(ch)) {
      let j = i;
      while (j < n && /\s/.test(text[j])) j++;
      toks.push({ kind: "ws", start: i, end: j });
      i = j;
    } else if (ch === "(" || ch === ")") {
      toks.push({ kind: ch === "(" ? "lpar" : "rpar", start: i, end: i + 1 });
      i++;
    } else if (text.startsWith("&&", i)) {
      toks.push({ kind: "and", start: i, end: i + 2 });
      i += 2;
    } else if (text.startsWith("||", i)) {
      toks.push({ kind: "or", start: i, end: i + 2 });
      i += 2;
    } else if (ch === "!") {
      toks.push({ kind: "not", start: i, end: i + 1 });
      i++;
    } else {
      let j = i;
      while (j < n && !/\s/.test(text[j]) && text[j] !== "(" && text[j] !== ")") {
        if (text[j] === '"') { const k = text.indexOf('"', j + 1); j = k === -1 ? n : k + 1; }
        else j++;
      }
      const word = text.slice(i, j), lower = word.toLowerCase();
      if (lower === "and" || lower === "or") {
        toks.push({ kind: lower, start: i, end: j });
      } else {
        const m = /^([A-Za-z_]+)(!?=)([\s\S]*)$/.exec(word);
        const key = m ? QUERY_KEYS[m[1].toLowerCase()] : undefined;
        if (key) {
          toks.push({ kind: "term", start: i, end: j, key, rawKey: m[1], op: m[2], rest: m[3],
                      negated: m[2] === "!=", values: splitRaw(m[3]).map(unquote).filter((v) => v !== "") });
        } else {
          toks.push({ kind: "term", start: i, end: j, key: null, negated: false, values: [unquote(word)] });
        }
      }
      i = j;
    }
  }
  // structure: nesting depth, a top-level "or", and which terms a "!" in front negates
  let depth = 0, topLevelOr = false, nots = [];
  const terms = [];
  for (const t of toks) {
    if (t.kind === "ws") continue;
    if (t.kind === "lpar") { t.depth = depth++; nots = []; }
    else if (t.kind === "rpar") { depth = Math.max(0, depth - 1); t.depth = depth; nots = []; }
    else if (t.kind === "or" || t.kind === "and") { t.depth = depth; if (t.kind === "or" && depth === 0) topLevelOr = true; nots = []; }
    else if (t.kind === "not") nots.push(t);
    else if (t.kind === "term") {
      t.depth = depth;
      t.negated = t.negated !== (nots.length % 2 === 1);
      t.removeStart = nots.length ? nots[0].start : t.start;      // a "!" in front goes with the term
      nots = [];
      if (t.key) terms.push(t);
    }
  }
  return { toks, terms, topLevelOr };
}

// Remove / replace parts of a query text. Each edit: { start, end, text }. Spaces around removed parts are tidied.
function applyEdits(text, edits) {
  for (const e of [...edits].sort((a, b) => b.start - a.start)) {
    let { start, end } = e;
    if (e.text === "") {
      while (end < text.length && /\s/.test(text[end])) end++;
      if (end === text.length) while (start > 0 && /\s/.test(text[start - 1])) start--;
    }
    text = text.slice(0, start) + e.text + text.slice(end);
  }
  return text.trim();
}

const appendTerm = (text, term) => (text.trim() ? `${text.trimEnd()} ${term}` : term);

// Set (values = array) or remove (values = null) the key=... term of a query.
function editQuery(text, key, values, negated = false) {
  const parsed = parseQuery(text);
  const name = { creator: "created_by", sortby: "sort_by" }[key] || key;                 // the dropdowns' names, in snake case
  const term = values && values.length ? `${name}${negated ? "!=" : "="}${values.map(quoteValue).join(",")}` : "";
  if (key === "sortby") {                                          // a directive: replaced wherever it stands
    const edits = parsed.toks.filter((t) => t.kind === "term" && t.key === "sortby").map((t) => ({ start: t.removeStart, end: t.end, text: "" }));
    return appendTerm(applyEdits(text, edits), term).trim();
  }
  if (parsed.topLevelOr) return term ? `(${text.trim()}) ${term}` : text;   // can't edit inside an "or": add on top instead
  const mine = parsed.terms.filter((t) => t.key === key && t.depth === 0);
  if (!mine.length) return term ? appendTerm(text, term) : text;
  const edits = mine.map((t, i) => ({ start: t.removeStart, end: t.end, text: i === 0 ? term : "" }));
  return applyEdits(text, edits);
}

// What a dropdown should show for one key: { set: [...] } = those boxes are checked, { custom: true } = too complex for a dropdown
function deriveSet(parsed, key, all) {
  if (!parsed.terms.some((t) => t.key === key)) return { set: all };                          // this key isn't used at all
  if (parsed.topLevelOr) return { custom: true };                                             // used, but inside an "or"
  if (parsed.terms.some((t) => t.key === key && t.depth > 0)) return { custom: true };      // inside a group: too complex
  const mine = parsed.terms.filter((t) => t.key === key && t.depth === 0);
  if (mine.length === 0) return { set: all };
  if (mine.length > 1) return { custom: true };
  const wanted = mine[0].values.map((v) => v.toLowerCase());
  const hit = all.filter((v) => wanted.includes(v.toLowerCase()));
  const set = mine[0].negated ? all.filter((v) => !hit.includes(v)) : hit;
  return set.length || mine[0].negated ? { set } : { custom: true };        // everything excluded = nothing ticked
}

// The sort the query asks for, as the value of the "Sort by" dropdown ("" = the default, newest first)
function deriveSort(parsed, sortKeys) {
  const mine = parsed.toks.filter((t) => t.kind === "term" && t.key === "sortby" && t.values.length);
  if (!mine.length) return "";
  const raw = mine[mine.length - 1].values[0], name = raw.replace(/^[+-]/, "").toLowerCase();
  if (!sortKeys.includes(name)) return "";
  const value = `${raw.startsWith("-") ? "-" : ""}${name}`;
  return value === "created" ? "" : value;
}

// created=2026 / 2026-11 / 2026-11-25, optionally after < <= > >=; expires also takes none. Same rules as dero/query.py.
function validDate(value, key) {
  if (key === "expires" && /^(none|never)$/i.test(value)) return true;
  const m = /^(<=|>=|<|>)?(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(value.trim());
  if (!m) return false;
  const month = Number(m[3] || 1), day = Number(m[4] || 1), date = new Date(Date.UTC(Number(m[2]), month - 1, day));
  return month >= 1 && month <= 12 && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

// Draw the query with its structure: terms as chips, groups tinted, operators and negations coloured.
// The text of the result is exactly the query text (the highlight sits behind the real input).
function renderQuery(parsed, text, container, { statuses, sortKeys }) {
  container.replaceChildren();
  const stack = [container];
  const top = () => stack[stack.length - 1];
  const span = (cls, str) => {
    const el = document.createElement("span");
    if (cls) el.className = cls;
    el.textContent = str;
    return el;
  };
  parsed.toks.forEach((t, idx) => {
    const raw = text.slice(t.start, t.end);
    if (t.kind === "ws") top().append(document.createTextNode(raw));
    else if (t.kind === "lpar") {
      const group = span("q-group", "");
      group.dataset.from = t.start;
      top().append(group);
      stack.push(group);
      group.append(span("q-paren", "("));
    } else if (t.kind === "rpar") {
      top().append(span("q-paren", ")"));
      if (stack.length > 1) { top().dataset.to = t.end; stack.pop(); }
    } else if (t.kind === "and" || t.kind === "or") {
      // only an operator with space (or the end of the text) on both sides is shown as a pill with its own x;
      // one stuck to a parenthesis, as in (a)or(b), stays plain
      const gap = (other) => !other || other.kind === "ws";
      const apart = gap(parsed.toks[idx - 1]) && gap(parsed.toks[idx + 1]);
      const op = span(apart ? "q-op" : "q-op-tight", raw);
      if (apart) { op.dataset.from = t.start; op.dataset.to = t.end; }
      top().append(op);
    }
    else if (t.kind === "not") top().append(span("q-not", "!"));
    else if (!t.key) {
      const word = span("q-term q-k-text", "");
      word.dataset.from = t.removeStart;
      word.dataset.to = t.end;
      const before = parsed.toks[idx - 1], last = top().lastChild;
      const negated = before && before.kind === "not" && last && last.classList && last.classList.contains("q-not");
      if (negated) { word.classList.add("q-neg"); word.append(last); }        // the "!" belongs to the chip, as with key=value terms
      word.append(raw);
      top().append(word);
    }
    else {
      const pill = span(`q-term q-k-${t.key}${t.negated ? " q-neg" : ""}`, "");
      pill.dataset.from = t.removeStart;
      pill.dataset.to = t.end;
      const before = parsed.toks[idx - 1], last = top().lastChild;
      if (before && before.kind === "not" && last && last.classList && last.classList.contains("q-not")) pill.append(last);
      pill.append(span("q-key", t.rawKey), span("q-eq", t.op));
      splitRaw(t.rest).forEach((piece, i) => {
        if (i) pill.append(span("q-eq", ","));
        const value = unquote(piece);
        const bad = (t.key === "status" && value && !statuses.includes(value.toLowerCase()))
          || ((t.key === "created" || t.key === "expires") && value && !validDate(value, t.key))
          || (t.key === "sortby" && value && !sortKeys.includes(value.replace(/^[+-]/, "").toLowerCase()));
        pill.append(span(bad ? "q-val q-invalid" : "q-val", piece));
      });
      top().append(pill);
    }
  });
  stack.slice(1).forEach((group) => { if (!group.dataset.to) group.dataset.to = text.length; });    // a group that is never closed
}

// Take just an operator (and, or, &&, ||) out; what it joined is then joined by the implicit "and".
function removeOperator(text, from, to) {
  let end = to;
  while (end < text.length && /\s/.test(text[end])) end++;
  let start = from;
  if (end === text.length) while (start > 0 && /\s/.test(text[start - 1])) start--;      // at the end: take the space before it
  return applyEdits(text, [{ start, end, text: "" }]).trim();
}

// Take one part (a term or a group) out of a query, together with the "and"/"or" that joined it to its neighbour.
function removePart(text, from, to) {
  const toks = parseQuery(text).toks.filter((t) => t.kind !== "ws");
  const joins = (t) => t && (t.kind === "and" || t.kind === "or");
  const before = [...toks].reverse().find((t) => t.end <= from), after = toks.find((t) => t.start >= to);
  let start = from, end = to;
  if (joins(before)) start = before.start;
  else if (joins(after)) end = after.end;
  return applyEdits(text, [{ start, end, text: "" }]);
}

// ---- Filters, search and sorting apply by themselves ----
// The search box holds the whole state as one query. The dropdowns show it (and edit it); changing
// either one fetches the list again and swaps only the table, so the page doesn't jump and the
// search box keeps focus. The indicator confirms that something happened.
(function () {
  const form = document.getElementById("filters");
  if (!form) return;
  const input = document.getElementById("q");
  const highlight = form.querySelector(".qhl");
  const sortSelect = document.getElementById("filter-sort");
  const live = document.getElementById("filter-live");
  const clear = document.getElementById("reset-filters");
  const multis = [...form.querySelectorAll("details.multi")];
  const queryMultis = multis.filter((details) => details.dataset.key);          // status, created by
  const columnsMenu = document.getElementById("filter-columns");
  const lists = {
    statuses: JSON.parse(form.dataset.statuses || "[]"),
    sortKeys: JSON.parse(form.dataset.sortKeys || "[]"),
  };
  const SPRITE = live.querySelector("use").getAttribute("href").split("#")[0];
  const IDLE = live.querySelector("span").textContent;
  let seq = 0, typing, resetTimer;

  function indicator(state, text) {
    const use = live.querySelector("use");
    live.classList.toggle("busy", state === "busy");
    live.classList.toggle("updated", state === "done");
    use.setAttribute("href", `${SPRITE}#${state === "done" ? "check" : "refresh"}`);
    live.querySelector("span").textContent = text;
    clearTimeout(resetTimer);
    if (state === "done") resetTimer = setTimeout(() => indicator("idle", IDLE), 1400);
  }

  const hasFilter = (parsed) => parsed.toks.some((t) => t.kind === "term" && t.key !== "sortby");

  const defaultColumns = () => (columnsMenu && columnsMenu.dataset.default ? columnsMenu.dataset.default.split(",") : []);
  const chosenColumns = () => (columnsMenu ? [...columnsMenu.querySelectorAll("input[type=checkbox]:checked")].map((box) => box.value) : []);
  const columnsDiffer = () => chosenColumns().join() !== defaultColumns().join();

  function setClear(active) {            // disabled, never hidden: nothing may move
    clear.setAttribute("aria-disabled", String(!active));
    if (active) clear.removeAttribute("tabindex"); else clear.tabIndex = -1;
  }

  // ---- the highlighted search bar
  const field = form.querySelector(".qfield"), removers = form.querySelector(".qx-layer");

  // one small x after every term, every outermost group and every operator, inside the padding of its chip
  function drawRemovers() {
    removers.replaceChildren();
    const base = field.getBoundingClientRect();
    highlight.querySelectorAll(".q-term, .q-group, .q-op").forEach((el) => {
      if (el.classList.contains("q-group") && el.parentElement.closest(".q-group")) return;
      if (!el.classList.contains("q-group") && el.closest(".q-group")) return;   // a group is removed as a whole
      const x = el.getBoundingClientRect().right - base.left;
      if (x < 6 || x > base.width - 6) return;                              // scrolled out of view
      const label = input.value.slice(Number(el.dataset.from), Number(el.dataset.to)).trim();
      const button = document.createElement("button");
      button.type = "button";
      button.className = "qx";
      button.tabIndex = -1;                                                  // the text itself is the keyboard way to edit
      button.title = `Remove ${label}`;
      button.setAttribute("aria-label", `Remove ${label}`);
      button.dataset.from = el.dataset.from;
      button.dataset.to = el.dataset.to;
      if (el.classList.contains("q-op")) button.dataset.kind = "operator";
      button.style.left = `${x - 11}px`;                                   // inside the chip's right padding, a little after the text
      button.innerHTML = `<svg class="icon" aria-hidden="true"><use href="${SPRITE}#x"/></svg>`;   // an icon sits exactly in the middle
      removers.append(button);
    });
  }

  removers.addEventListener("mousedown", (event) => event.preventDefault());   // keep the focus where it is
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
    drawRemovers();                                                           // the chips moved with the scroll
  }

  function draw() {
    renderQuery(parseQuery(input.value), input.value, highlight, lists);
    syncScroll();
    requestAnimationFrame(syncScroll);   // the caret may have moved the text after the event
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
    queryMultis.forEach((details) => showMulti(details, deriveSet(parsed, details.dataset.key, JSON.parse(details.dataset.all || "[]"))));
    const wanted = deriveSort(parsed, lists.sortKeys);
    sortSelect.value = [...sortSelect.options].some((o) => o.value === wanted) ? wanted : "";
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
      // all = no filter; none = everything excluded (key!=a,b,c), so nothing is shown
      const everything = checked.length === all.length, none = checked.length === 0 && all.length > 0;
      setQuery(editQuery(input.value, details.dataset.key, everything ? null : none ? all : all.filter((v) => checked.includes(v)), none));
    });
  });

  // Columns are a view setting, not part of the query: remembered in a cookie so the server draws them.
  // At least one column stays: the last one that is on can't be switched off (it is disabled until another is on).
  const lockLastColumn = () => {
    if (!columnsMenu) return;
    const on = [...columnsMenu.querySelectorAll("input[type=checkbox]:checked")];
    columnsMenu.querySelectorAll("input[type=checkbox]").forEach((box) => (box.disabled = on.length === 1 && box.checked));
  };
  lockLastColumn();
  if (columnsMenu) {
    columnsMenu.addEventListener("change", (event) => {
      if (!columnsMenu.querySelector("input[type=checkbox]:checked")) { event.target.checked = true; lockLastColumn(); return; }   // (keyboard or script)
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

  sortSelect.addEventListener("change", () => setQuery(editQuery(input.value, "sortby", sortSelect.value ? [sortSelect.value] : null)));

  document.addEventListener("click", (event) => {          // sortable column headers set the sort in the query
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
    const url = form.getAttribute("action") + (q ? "?" + new URLSearchParams({ q }) : "");
    const mine = ++seq;
    indicator("busy", "Updating…");
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      if (mine !== seq) return;            // a newer change already replaced this one
      if (!swapRegion("links-results", doc)) throw new Error("unexpected page");
      const fresh = document.getElementById("links-results");
      history.replaceState(null, "", url);
      const n = Number(fresh.dataset.count), total = Number(fresh.dataset.overall);
      indicator("done", hasFilter(parseQuery(q)) ? `Updated · ${n} of ${total}` : "Updated");
    } catch {
      location.href = url;                 // fall back to a normal page load
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
      const a = toks[i], b = toks[i + 1];
      if (a.end !== b.start || a.kind === "not") continue;       // already apart, or a "!" that belongs to the next term
      if (!special(a) && !special(b)) continue;
      if (paren(a) && paren(b)) continue;                        // ((a)) stays as typed
      at.push(a.end);
    }
    if (!at.length) return false;
    let caret = input.selectionStart, out = "", last = 0;
    for (const p of at) {
      out += text.slice(last, p) + " ";
      last = p;
      if (p <= input.selectionStart) caret++;
    }
    input.value = out + text.slice(last);
    input.setSelectionRange(caret, caret);
    return true;
  }

  input.addEventListener("input", (event) => {
    if (event.inputType && event.inputType.startsWith("insert")) spaceOut();
    draw();
    syncControls();
    clearTimeout(typing);
    typing = setTimeout(update, 250);
  });
  ["keyup", "click", "focus", "select", "scroll"].forEach((name) => input.addEventListener(name, syncScroll));
  document.addEventListener("selectionchange", () => { if (document.activeElement === input) syncScroll(); });
  form.addEventListener("submit", (event) => { event.preventDefault(); clearTimeout(typing); update(); });

  clear.addEventListener("click", (event) => {              // back to the start: no query, no sort, the default columns
    event.preventDefault();
    if (clear.getAttribute("aria-disabled") === "true") return;
    if (columnsMenu) {
      const all = JSON.parse(columnsMenu.dataset.all || "[]"), wanted = defaultColumns();
      columnsMenu.querySelectorAll("input[type=checkbox]").forEach((box) => (box.checked = wanted.includes(box.value)));
      lockLastColumn();
      columnsMenu.querySelector(".multi-label").textContent = `${wanted.length} of ${all.length}`;
      document.cookie = `${columnsMenu.dataset.cookie}=${wanted.join(",")}; path=${columnsMenu.dataset.cookiePath || "/"}; max-age=31536000; SameSite=Lax`;
    }
    setQuery("");
  });

  const helpToggle = document.getElementById("q-help-toggle"), help = document.getElementById("q-help");
  helpToggle.addEventListener("click", () => {
    help.hidden = !help.hidden;
    helpToggle.setAttribute("aria-expanded", String(!help.hidden));
  });

  setQuery(input.value, { fetch: false });    // draw the first time

  // ---- Live visits (an option in the settings): the server pushes a message when a counter goes up (server-sent
  // events). The row of a visited slug lights up and its count is changed in place; the table is only fetched again
  // when the order depends on the visits or links were created or deleted.
  const LIVE_KEY = "dero.live";
  let source = null, hiddenTimer = null, dropped = false;
  const liveOn = () => { try { return localStorage.getItem(LIVE_KEY) === "1"; } catch { return false; } };
  const sortsByVisits = () => /visits$/.test(deriveSort(parseQuery(input.value), lists.sortKeys) || "");

  function flash(row) {
    row.classList.remove("visited");
    void row.offsetWidth;                                            // restart the animation
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
    indicator("done", `${names.length > 1 ? names.length + " slugs" : names[0]} visited`);
  }

  function openStream() {
    if (source || typeof EventSource === "undefined") return;
    source = new EventSource(form.dataset.liveUrl);
    source.addEventListener("visit", (event) => visited(JSON.parse(event.data)));
    source.addEventListener("refresh", () => update());
    source.addEventListener("open", () => { if (dropped) { dropped = false; update(); } });   // after a gap: catch up
    source.addEventListener("error", () => { dropped = true; });                              // the browser reconnects itself
  }

  function closeStream() {
    if (source) source.close();
    source = null;
  }

  function setLive(on) {
    closeStream();
    live.classList.toggle("is-live", on);
    if (on) openStream();
  }

  // a tab nobody looks at gives its connection (a worker thread) back after a while
  document.addEventListener("visibilitychange", () => {
    clearTimeout(hiddenTimer);
    if (!liveOn()) return;
    if (document.visibilityState === "hidden") hiddenTimer = setTimeout(closeStream, 30000);
    else if (!source) { openStream(); dropped = true; }
  });

  document.addEventListener("dero:live", () => setLive(liveOn()));
  setLive(liveOn());
})();

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

(function () {
  const dialog = document.getElementById("settings"), open = document.getElementById("settings-open");
  if (dialog && open && typeof dialog.showModal === "function") {
    open.addEventListener("click", () => dialog.showModal());
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });   // a click outside closes it
  }
  const liveSwitch = document.getElementById("live-switch");
  if (liveSwitch) {
    try { liveSwitch.checked = localStorage.getItem("dero.live") === "1"; } catch {}
    liveSwitch.addEventListener("change", () => {
      try { localStorage.setItem("dero.live", liveSwitch.checked ? "1" : "0"); } catch {}
      document.dispatchEvent(new Event("dero:live"));
    });
  }
  const toggle = document.getElementById("hl-switch");
  if (!toggle) return;
  toggle.addEventListener("change", () => {
    document.documentElement.dataset.hl = toggle.checked ? "on" : "off";
    document.cookie = `dero_hl=${toggle.checked ? 1 : 0}; path=/; max-age=31536000; SameSite=Lax`;
  });
})();

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

// ---- New link: the small switch enables the expiry date (off = never expires) ----
(function () {
  const toggle = document.getElementById("new-expiry-switch");
  if (!toggle) return;
  const date = toggle.form.elements.expires_at;
  const sync = () => { date.disabled = !toggle.checked; };
  toggle.addEventListener("change", () => {
    sync();
    if (toggle.checked) date.focus(); else { date.value = ""; date.removeAttribute("aria-invalid"); }
  });
  toggle.form.addEventListener("reset", () => setTimeout(sync, 0));
  sync();
})();

// ---- Confirmation dialog (replaces window.confirm) ----
// A form with data-confirm-title asks first. The dialog is a native <dialog>:
// Esc and a click outside cancel, focus starts on Cancel, and the confirming
// button sits on the left.
(function () {
  const dialog = document.getElementById("confirm");
  if (!dialog || typeof dialog.showModal !== "function") return;

  function ask(data) {
    dialog.querySelector("#confirm-title").textContent = data.confirmTitle || "Are you sure?";
    // A short link: base address in the normal font, the slug in its coloured box (cut like everywhere else).
    // Anything else (a rule's pattern) is shown as code.
    const name = dialog.querySelector("#confirm-name"), full = data.confirmName || "";
    name.replaceChildren();
    if (/^https?:\/\//.test(full)) {
      const cut = full.lastIndexOf("/") + 1, slugPart = full.slice(cut);
      const base = document.createElement("span"), code = document.createElement("code");
      base.className = "confirm-base";
      base.textContent = full.slice(0, cut);
      code.className = "slug";
      code.append(coloredSlug(slugPart.length > 20 ? slugPart.slice(0, 20) : slugPart));
      if (slugPart.length > 20) { code.append("…"); code.title = slugPart; }
      name.append(base, code);
    } else {
      const code = document.createElement("code");
      code.className = "slug";
      code.textContent = full;
      name.append(code);
    }
    dialog.querySelector("#confirm-detail").textContent = data.confirmDetail || "";
    dialog.querySelector("#confirm-text .icon").hidden = !data.confirmDetail;       // the arrow only makes sense with a second URL
    dialog.querySelector("#confirm-yes span").textContent = data.confirmYes || "Confirm";
    return new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
      dialog.returnValue = "no";
      dialog.showModal();
    });
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.dataset || form.dataset.confirmTitle === undefined || form.dataset.confirmed) return;
    event.preventDefault();
    if (await ask(form.dataset)) {
      form.dataset.confirmed = "1";
      form.requestSubmit();
    }
  });

  dialog.addEventListener("click", (event) => {   // click on the backdrop
    if (event.target === dialog) dialog.close("no");
  });
})();

// ---- Editing a link in its details (target, short link, expiry) ----
// The switch enables the date field (off = never expires). "Update" and
// "Discard" stay disabled until something differs from what is saved. The
// target and slug inputs sit in other places of the row and belong to the
// form through their form="" attribute.
function syncEdit(form) {
  const toggle = form.querySelector(".expiry-switch"), date = form.elements.expires_at;
  const target = form.elements.target, slug = form.elements.slug;
  date.disabled = !toggle.checked;
  date.required = toggle.checked;
  const dirty = toggle.checked !== toggle.defaultChecked || (toggle.checked && date.value !== date.defaultValue)
    || target.value !== target.defaultValue || slug.value !== slug.defaultValue;
  for (const button of document.querySelectorAll(`[form="${form.id}"], [data-discard="${form.id}"]`)) {
    if (button.dataset.discard) button.hidden = false;     // without JavaScript there is nothing to discard
    if (button.tagName === "BUTTON") button.disabled = !dirty;
  }
}

function syncAllEdit() {
  document.querySelectorAll(".edit-form").forEach(syncEdit);
}

function editFormOf(element) {
  const form = element.form;
  return form && form.classList.contains("edit-form") ? form : null;
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
  form.reset();                                            // back to what is saved (reaches the inputs with form="")
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  forgetWarning(form);
  syncEdit(form);
});

// Check the edit form before it is sent; errors go to the "All links" card.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.classList || !form.classList.contains("edit-form")) return;
  document.querySelectorAll(`[form="${form.id}"][aria-invalid]`).forEach((el) => el.removeAttribute("aria-invalid"));
  const found = linkProblem(form, {
    reserved: (form.dataset.reserved || "").split(",").filter(Boolean),
    savedSlug: form.elements.slug.defaultValue,
    slugRequired: true,
    dateWhenOn: true,
  });
  if (!found) {
    if (needsLookup(form)) { event.preventDefault(); lookupThenResubmit(form); return; }
    warnFirst(form, event, "Update", (message) => showNotice(`link-${form.id.slice(1)}-notices`, message, "warn"));
    return;
  }
  event.preventDefault();
  const [field, message] = found;
  field.setAttribute("aria-invalid", "true");
  showNotice(`link-${form.id.slice(1)}-notices`, message);
  field.focus();
});

syncAllEdit();
localizeTimes();


// ---- Row switches submit when flipped ----
document.addEventListener("change", (event) => {
  const toggle = event.target.closest(".row-switch");
  if (toggle) toggle.form.requestSubmit();
});

// ---- Actions without page reloads ----
// Every POST form in <main> is sent with fetch(). The server still answers
// with a redirect and a full page, so that page is used to refresh only what
// changed: the messages, the table and (for "New link") its feedback line.
// Without JavaScript the same forms work as ordinary form posts.
(function () {
  const main = document.querySelector("main");
  if (!main) return;
  // Messages live in the card they belong to (.notices containers, one per scope).
  function refreshNotices(doc) {
    for (const theirs of doc.querySelectorAll(".notices")) {
      const mine = document.getElementById(theirs.id);
      if (mine) mine.innerHTML = theirs.innerHTML;
    }
  }

  function showFailure(form) {
    const box = (form.closest("section") || document).querySelector(".notices");
    if (!box) return;
    const p = document.createElement("p");
    p.className = "form-error";
    p.setAttribute("role", "alert");
    p.textContent = "That didn't work. Reload the page and try again.";
    box.replaceChildren(p);
  }

  async function currentView() {
    const res = await fetch(location.pathname + location.search, { credentials: "same-origin" });
    return new DOMParser().parseFromString(await res.text(), "text/html");
  }

  async function submit(form) {
    const buttons = [...form.elements].filter((el) => el.tagName === "BUTTON");
    buttons.forEach((b) => (b.disabled = true));
    form.setAttribute("aria-busy", "true");
    try {
      const res = await fetch(form.getAttribute("action"), {
        method: "POST", body: new FormData(form), credentials: "same-origin",
      });
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const isCreate = form.id === "new-link";
      if (!doc.querySelector("main")) throw new Error("unexpected answer");   // 403, 404, 500 ...

      refreshNotices(doc);

      if (isCreate) {                                  // keep the typed values on an error, clear them on success
        const box = document.getElementById("new-link-error"), theirs = doc.getElementById("new-link-error");
        if (box && theirs) {
          box.innerHTML = theirs.innerHTML;
          const rows = form.querySelectorAll(".nl-row"), at = [...doc.querySelectorAll("#new-link .nl-row")].findIndex((r) => r.contains(theirs));
          if (at >= 0 && rows[at] && box.parentElement !== rows[at]) rows[at].append(box);
        }
        form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
        if (res.ok) {
          form.reset();
        } else {
          for (const bad of doc.querySelectorAll("#new-link [aria-invalid]")) {
            const mine = form.elements.namedItem(bad.name);       // (not elements[name]: "length" is the collection's size)
            if (mine) { mine.setAttribute("aria-invalid", "true"); mine.focus(); }
          }
          return;
        }
      }

      if (doc.querySelector(".notices .form-error")) return;     // rejected: keep the form exactly as the user left it

      // refresh the list the user is looking at
      let view = doc;
      const same = new URL(res.url).pathname + new URL(res.url).search === location.pathname + location.search;
      if (!same) view = await currentView();            // e.g. a new link: the answer was the unfiltered list
      for (const id of ["links-results", "rules-results"]) swapRegion(id, view);

      if (form.dataset.resetOnSuccess !== undefined && !doc.querySelector(".notices .form-error")) form.reset();
    } catch {
      showFailure(form);
    } finally {
      delete form.dataset.confirmed;
      form.removeAttribute("aria-busy");
      buttons.forEach((b) => { if (b.isConnected) b.disabled = false; });
      if (form.isConnected && form.classList.contains("edit-form")) syncEdit(form);
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.method !== "post" || !main.contains(form)) return;
    if (form.dataset.confirmTitle !== undefined && !form.dataset.confirmed) {
      // Only reached when <dialog> is unsupported: fall back to the browser's own question.
      if (!window.confirm(form.dataset.confirmTitle)) return event.preventDefault();
    }
    event.preventDefault();
    submit(form);
  });
})();

// ---- Dropdowns ----
// Every <select> is upgraded to the same dropdown as the checkbox lists (details/summary + a panel). The
// <select> stays in the page, hidden: it still holds the value, is submitted with its form and fires the
// same change events, so nothing else needs to know. Without JavaScript the plain <select> works.
function refreshSelect(select) {
  select.dispatchEvent(new Event("dero:refresh"));
}

function upgradeSelect(select) {
  if (select.dataset.upgraded) return;
  select.dataset.upgraded = "1";
  select.classList.add("native-hidden");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" }).getAttribute("href").split("#")[0];
  const owner = select.closest("label") || (select.id && document.querySelector(`label[for="${select.id}"]`));
  const name = owner ? [...owner.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim() : "";

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

  details.addEventListener("keydown", (event) => {            // arrow keys move through the options
    const at = buttons.indexOf(document.activeElement);
    const to = { ArrowDown: at + 1, ArrowUp: at < 0 ? buttons.length - 1 : at - 1, Home: 0, End: buttons.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    if (!details.open) { details.open = true; return; }
    buttons[(to + buttons.length) % buttons.length].focus();
  });
}

document.querySelectorAll("select").forEach(upgradeSelect);

// One handler for every dropdown (checkbox lists and the upgraded selects): a click outside or Escape closes it.
document.addEventListener("click", (event) => {
  document.querySelectorAll("details.multi[open]").forEach((d) => { if (!d.contains(event.target)) d.open = false; });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details.multi[open]").forEach((d) => { d.open = false; d.querySelector("summary").focus(); });
});
