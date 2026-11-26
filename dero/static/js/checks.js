// ---- Checks shared by the "New link" form and the edit form in a link's details ----
const SLUG_RE = /^[A-Za-z0-9._~-]{1,64}$/; // what a URL path never needs to escape
const BAD_SLUG = "A slug can use letters, digits and - _ . ~, up to 64 characters.";
const DOTS_ONLY = "A slug needs at least one character that isn't a dot.";
const slugProblem = (value) => (!SLUG_RE.test(value) ? BAD_SLUG : /^\.+$/.test(value) ? DOTS_ONLY : null);
const BAD_URL = "Enter a full web address starting with http:// or https://.";

// Returns [field, message] for the first problem, or null. The server repeats every check.
// `generator` = the "New link" form (slug mode, alphabet and length); otherwise a plain slug field is checked.
function linkProblem(
  form,
  { reserved = [], savedSlug = null, slugRequired = false, dateWhenOn = false, generator = false } = {},
) {
  const target = form.elements.target,
    expires = form.elements.expires_at;
  const url = target.value.trim();
  if (!url) return [target, "Enter the address to shorten."];
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return [target, BAD_URL];
  }
  if (!/^https?:$/.test(parsed.protocol) || !parsed.host || url.length > 2048) return [target, BAD_URL];
  if (generator) {
    const found = generatorProblem(form, reserved);
    if (found) return found;
  } else {
    const slug = form.elements.slug,
      s = slug.value.trim();
    if (!s && slugRequired) return [slug, "Type a slug."];
    if (s && slugProblem(s)) return [slug, slugProblem(s)];
    if (s && s !== savedSlug && reserved.includes(s)) return [slug, `‹${s}› is reserved by dero. Choose another slug.`];
  }
  if (dateWhenOn && !expires.disabled && !expires.value)
    return [expires, "Pick the last day the link works, or switch expiry off."];
  return null;
}

// Slug part of the "New link" form: a typed slug, or the characters and length to generate one from.
function generatorProblem(form, reserved, source = form.elements.slug_source.value) {
  if (source === "slug") {
    const slug = form.elements.slug,
      s = slug.value.trim();
    if (!s) return [slug, "Type a slug, or choose a random one."];
    if (slugProblem(s)) return [slug, slugProblem(s)];
    if (reserved.includes(s)) return [slug, `‹${s}› is reserved by dero. Choose another slug.`];
    return null;
  }
  if (source === "chars") {
    const field = form.elements.alphabet_custom,
      chars = [...field.value];
    const bad = [...new Set(chars.filter((c) => !/[A-Za-z0-9._~-]/.test(c)))];
    if (bad.length) {
      const names = bad.slice(0, 6).map((c) => (c === " " ? "space" : `'${c}'`));
      const shown =
        bad.length > 6
          ? `${names.join(", ")}, …` // too many: cut
          : names.length === 1
            ? names[0]
            : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`; // "and" before the last
      return [field, `${shown} can't be used in a slug. Allowed: letters, digits and - _ . ~`];
    }
    if (new Set(chars).size < 2) return [field, "Use at least 2 different characters."];
  }
  const length = form.elements.namedItem("length"),
    n = Number(length.value); // (elements.length is the collection's size)
  const min = Number(form.dataset.minLength),
    max = Number(form.dataset.maxLength);
  if (!Number.isInteger(n) || n < min || n > max) return [length, `Length must be ${min} to ${max} characters.`];
  return null;
}

// A slug as it is shown everywhere: in its box, coloured, cut after 20 characters.
function slugBox(slug) {
  const code = document.createElement("code");
  code.className = "slug";
  code.append(coloredSlug(slug.length > 20 ? slug.slice(0, 20) : slug));
  if (slug.length > 20) {
    code.append("…");
    code.title = slug;
  }
  return code;
}

// Text in which ‹slugs› are marked becomes text with slug boxes.
function setRich(element, text) {
  element.replaceChildren();
  text.split(/‹([^›]*)›/).forEach((part, i) => element.append(i % 2 ? slugBox(part) : part));
}

// Put a message into a card's .notices container (same markup the server renders).
function showNotice(id, message, kind = "error") {
  // kind: "error", "warn" or "ok"
  const box = document.getElementById(id);
  if (!box) return;
  const sprite = (document.querySelector("svg.icon use") || { getAttribute: () => "" })
    .getAttribute("href")
    .split("#")[0];
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
  try {
    url = new URL(text);
  } catch {
    return [];
  } // invalid URLs are errors, handled elsewhere
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

const joinList = (items) =>
  items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0] || "";

// Does another link already point to this address? Asked just before sending (and only for a new or changed address).
function alreadyShortened(slugs, count) {
  if (!slugs.length) return "Someone else already shortened this address.";
  const shown = slugs.slice(0, 3),
    more = count - shown.length;
  return `This address already has links: ${shown.map((s) => `‹${s}›`).join(", ")}${more > 0 ? ` and ${more} more` : ""}.`;
}

function needsLookup(form) {
  const target = form.elements.target,
    url = target.value.trim();
  return Boolean(form.dataset.lookup) && url !== target.defaultValue.trim() && form.dataset.dupFor !== url;
}

// Asks the server, remembers the answer on the form (keyed by the address) and sends the form again.
// A failed lookup never blocks anything: it just counts as "no duplicate".
async function lookupThenResubmit(form) {
  const url = form.elements.target.value.trim();
  if (form.dataset.lookingUp === url) return; // already asking (e.g. a double click)
  form.dataset.lookingUp = url;
  let answer = { count: 0, slugs: [] };
  try {
    const query = new URLSearchParams({ target: url });
    if (form.dataset.exclude) query.set("exclude", form.dataset.exclude);
    const res = await fetch(`${form.dataset.lookup}?${query}`, { credentials: "same-origin" });
    if (res.ok) answer = await res.json();
  } catch {}
  delete form.dataset.lookingUp;
  if (form.elements.target.value.trim() !== url) return; // the user changed it meanwhile
  form.dataset.dupFor = url;
  form.dataset.dupCount = String(answer.count);
  form.dataset.dupSlugs = JSON.stringify(answer.slugs);
  form.requestSubmit();
}

// Things worth a second look but not wrong: an unusual address and an expiry in the past. Unchanged values stay quiet.
function linkWarnings(form) {
  const notes = [],
    fields = [];
  const target = form.elements.target,
    expires = form.elements.expires_at;
  const url = target.value.trim();
  if (url !== target.defaultValue.trim() && form.dataset.dupFor === url && Number(form.dataset.dupCount) > 0) {
    notes.push(alreadyShortened(JSON.parse(form.dataset.dupSlugs || "[]"), Number(form.dataset.dupCount)));
    fields.push(target);
  }
  if (url !== target.defaultValue.trim()) {
    const reasons = unusualUrl(url);
    if (reasons.length) {
      notes.push(`This address looks unusual: it ${joinList(reasons)}.`);
      fields.push(target);
    }
  }
  if (
    !expires.disabled &&
    expires.value &&
    expires.value !== expires.defaultValue &&
    expires.value < new Date().toISOString().slice(0, 10)
  ) {
    notes.push("This expiry date has already passed, so the link would be expired at once.");
    fields.push(expires);
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
  show(`${notes.join(" ")} Press ${verb} again to ${verb === "Create" ? "create it" : "save it"} anyway.`, fields[0]);
  fields[0].focus();
  return true;
}

function forgetWarning(form) {
  delete form.dataset.warned;
  delete form.dataset.dupFor;
  delete form.dataset.dupCount;
  delete form.dataset.dupSlugs;
  [...form.elements].forEach((el) => el.removeAttribute("data-warn"));
}
