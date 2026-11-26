// ---- The search language ----
// The server filters (dero/query.py). This is the same tokenizer, used to highlight the search bar and to
// keep the dropdowns and the query text in sync.
// each key (the name used in the code) with every spelling that is accepted for it; the first spelling is the
// dropdown's name in snake case, the others are older ones. Same table as KEY_ALIASES in dero/query.py.
const KEY_ALIASES = {
  status: ["status"],
  creator: ["created_by", "creator", "owner", "by"],
  slug: ["slug"],
  target: ["target"],
  created: ["created"],
  expires: ["expires"],
  visits: ["visits"],
  sortby: ["sort_by", "sortby", "sort", "order"],
};
const QUERY_KEYS = Object.fromEntries(
  Object.entries(KEY_ALIASES).flatMap(([key, aliases]) => aliases.map((alias) => [alias, key])),
); // spelling -> key

// keys that can be unset: the key alone means "is set" (expires = expires!=never)
const OPTIONAL_KEYS = ["expires"];
const DATE_KEYS = ["created", "expires"];
const TEXT_KEYS = ["slug", "target", "creator"]; // a * in their values is any text ("==" takes it literally)
// the operators each key understands ("!=" counts as "="); "==" is the exact match. Same table as ALLOWED_OPS in dero/query.py.
const COMPARISONS = ["<=", ">=", "<", ">"];
const ALLOWED_OPS = {
  status: ["=", "=="],
  creator: ["=", "=="],
  slug: ["=", "=="],
  target: ["=", "=="],
  created: ["=", "==", ...COMPARISONS],
  expires: ["=", "==", ...COMPARISONS],
  visits: ["=", "==", ...COMPARISONS],
  sortby: ["="],
};
const SORT_ALIASES = { created_by: "creator" }; // sort_by=created_by, like the key and the dropdown
const DEFAULT_SORT = "-created"; // what no sort term at all means: newest first
const sortName = (raw) => {
  const name = raw.replace(/^[+-]/, "").toLowerCase();
  return SORT_ALIASES[name] || name;
};

// The search box is one <input>, so its CSS word-spacing (the room between terms, for the x of each chip) widens every
// space. Two kinds of space must not be that wide, and are drawn as look-alikes that word-spacing leaves alone, in the
// box and in the coloured copy behind it alike:
//  - a space inside quotes is QUOTED_SPACE, a quarter of an em: as wide as a space;
//  - the space after an opening parenthesis that is closed again is OPEN_SPACE, an em (13px): the parenthesis is a
//    compact pill with no x, so the gap to the next chip is then about as small as between chips (a parenthesis that is
//    not closed has an x and room for it, and keeps the wide space).
// Everything outside the box sees plain spaces: plainQuery() turns them back, and the server reads them as spaces too.
const QUOTED_SPACE = "\u2005";
const OPEN_SPACE = "\u2003";
const plainQuery = (text) => text.replaceAll(QUOTED_SPACE, " ").replaceAll(OPEN_SPACE, " ");
// The text with those spaces as the look-alikes and every other one plain (one character for one: the positions stay).
// A quote opens at one " and closes at the next; an unclosed one runs to the end, as in the tokenizer.
function spaceQuotes(text) {
  const chars = [...text];
  // which opening parentheses are closed again (outside quotes, nested like the parser does)
  const open = [],
    closed = new Set();
  let quoted = false;
  chars.forEach((ch, i) => {
    if (ch === '"') quoted = !quoted;
    else if (!quoted && ch === "(") open.push(i);
    else if (!quoted && ch === ")" && open.length) closed.add(open.pop());
  });
  quoted = false;
  let out = "";
  chars.forEach((ch, i) => {
    if (ch === '"') quoted = !quoted;
    const isSpace = ch === " " || ch === QUOTED_SPACE || ch === OPEN_SPACE;
    if (!isSpace) out += ch;
    else if (quoted) out += QUOTED_SPACE;
    else out += chars[i - 1] === "(" && closed.has(i - 1) ? OPEN_SPACE : " ";
  });
  return out;
}

// Where a space is missing in a query (positions in text): between a parenthesis or an and / or and whatever touches it,
// another parenthesis included, so that every one of them is drawn as a pill and the chips and their x never run into
// it. A "!" stays with the term after it.
function missingSpaces(text) {
  const toks = parseQuery(text).toks.filter((t) => t.kind !== "ws");
  const special = (t) => ["lpar", "rpar", "and", "or"].includes(t.kind);
  const at = [];
  for (let i = 0; i < toks.length - 1; i++) {
    const a = toks[i],
      b = toks[i + 1];
    if (a.end !== b.start || a.kind === "not") continue; // already apart, or a "!" that belongs to the next term
    if (special(a) || special(b)) at.push(a.end);
  }
  return at;
}

// The query with those spaces put in
function spaced(text) {
  let out = "",
    last = 0;
  for (const p of missingSpaces(text)) {
    out += `${text.slice(last, p)} `;
    last = p;
  }
  return out + text.slice(last);
}

function unquote(raw) {
  const text = plainQuery(raw);
  if (text.length >= 2 && text[0] === '"' && text.endsWith('"')) return text.slice(1, -1);
  return text.startsWith('"') ? text.slice(1) : text;
}

// "a,b,\"c d\"" -> raw pieces; commas inside quotes stay
function splitRaw(rest) {
  const pieces = [];
  let buf = "",
    quoted = false;
  for (const ch of rest) {
    if (ch === '"') {
      quoted = !quoted;
      buf += ch;
    } else if (ch === "," && !quoted) {
      pieces.push(buf);
      buf = "";
    } else buf += ch;
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
        if (text[j] === '"') {
          const k = text.indexOf('"', j + 1);
          j = k === -1 ? n : k + 1;
        } else j++;
      }
      const word = text.slice(i, j),
        lower = word.toLowerCase();
      if (lower === "and" || lower === "or") {
        toks.push({ kind: lower, start: i, end: j });
      } else {
        const m = /^([A-Za-z_]+)(!=|==|<=|>=|=|<|>)([\s\S]*)$/.exec(word);
        const key = m ? QUERY_KEYS[m[1].toLowerCase()] : undefined;
        if (OPTIONAL_KEYS.includes(lower)) {
          toks.push({
            kind: "term",
            start: i,
            end: j,
            key: lower,
            rawKey: word,
            op: "",
            rest: "",
            negated: false,
            values: [],
            empty: false, // the bare key says something: the link has an expiry
          });
        } else if (key) {
          const values = splitRaw(m[3])
            .map(unquote)
            .filter((v) => v !== "");
          toks.push({
            kind: "term",
            start: i,
            end: j,
            key,
            rawKey: m[1],
            op: m[2],
            rest: m[3],
            supported: ALLOWED_OPS[key].includes(m[2] === "!=" ? "=" : m[2]), // false: the server reports it and matches nothing
            negated: m[2] === "!=",
            values,
            empty: values.length === 0, // an operator but no value yet (status=): it filters nothing
          });
        } else {
          toks.push({ kind: "term", start: i, end: j, key: null, negated: false, values: [unquote(word)] });
        }
      }
      i = j;
    }
  }
  // structure: nesting depth, a top-level "or", and which terms a "!" in front negates
  let depth = 0,
    topLevelOr = false,
    nots = [];
  const terms = [];
  for (const t of toks) {
    if (t.kind === "ws") continue;
    if (t.kind === "lpar") {
      t.depth = depth++;
      nots = [];
    } else if (t.kind === "rpar") {
      depth = Math.max(0, depth - 1);
      t.depth = depth;
      nots = [];
    } else if (t.kind === "or" || t.kind === "and") {
      t.depth = depth;
      if (t.kind === "or" && depth === 0) topLevelOr = true;
      nots = [];
    } else if (t.kind === "not") nots.push(t);
    else if (t.kind === "term") {
      t.depth = depth;
      t.negated = t.negated !== (nots.length % 2 === 1);
      t.nots = nots.length; // how many ! stand in front (a sort_by has nothing to negate)
      t.removeStart = nots.length ? nots[0].start : t.start; // a "!" in front goes with the term
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
  const name = KEY_ALIASES[key][0]; // the dropdown's name, in snake case
  const term = values?.length ? `${name}${negated ? "!=" : "="}${values.map(quoteValue).join(",")}` : "";
  if (key === "sortby") {
    // a directive: replaced wherever it stands
    const edits = parsed.toks
      .filter((t) => t.kind === "term" && t.key === "sortby")
      .map((t) => ({ start: t.removeStart, end: t.end, text: "" }));
    return appendTerm(applyEdits(text, edits), term).trim();
  }
  if (parsed.topLevelOr) return term ? `(${text.trim()}) ${term}` : text; // can't edit inside an "or": add on top instead
  const mine = parsed.terms.filter((t) => t.key === key && t.depth === 0);
  if (!mine.length) return term ? appendTerm(text, term) : text;
  const edits = mine.map((t, i) => ({ start: t.removeStart, end: t.end, text: i === 0 ? term : "" }));
  return applyEdits(text, edits);
}

// The values of a sort_by term for the value of the "Sort by" dropdown ("-visits"), or null for no term at all.
// Explicit: always the whole signed value. Otherwise the usual order is left out: no term for newest
// first, the bare key for the other usual orders (sort_by=visits), a sign only where it is the other way (+visits).
function sortTermValues(value, defaultDesc, explicit) {
  if (explicit) return [value];
  if (value === DEFAULT_SORT) return null;
  const name = value.slice(1);
  return [(value[0] === "-") === Boolean(defaultDesc[name]) ? name : value];
}

// What a dropdown should show for one key: { set: [...] } = those boxes are checked, { custom: true } = too complex for a dropdown
function deriveSet(parsed, key, all) {
  const used = parsed.terms.filter((t) => t.key === key && !t.empty); // an empty term (status=) filters nothing
  if (!used.length) return { set: all }; // this key isn't used at all
  if (parsed.topLevelOr) return { custom: true }; // used, but inside an "or"
  if (used.some((t) => t.depth > 0)) return { custom: true }; // inside a group: too complex
  const mine = used.filter((t) => t.depth === 0);
  if (mine.length === 0) return { set: all };
  if (mine.length > 1) return { custom: true };
  if (!mine[0].supported) return { custom: true };
  if (key === "creator" && mine[0].values.includes("*")) return { set: mine[0].negated ? [] : all }; // created_by=* is everyone
  const wanted = mine[0].values.map((v) => v.toLowerCase());
  const hit = all.filter((v) => wanted.includes(v.toLowerCase()));
  const set = mine[0].negated ? all.filter((v) => !hit.includes(v)) : hit;
  return set.length || mine[0].negated ? { set } : { custom: true }; // everything excluded = nothing ticked
}

// The sort the query asks for, as the value of the "Sort by" dropdown ("" = the default, newest first)
// The sort as the value of the "Sort by" dropdown, written like dero/query.py sort_value: always with its sign, a
// missing sign meaning the key's usual order (defaultDesc says which keys go newest or most first)
function deriveSort(parsed, sortKeys, defaultDesc) {
  const mine = parsed.toks.filter((t) => t.kind === "term" && t.key === "sortby" && t.values.length);
  if (!mine.length) return DEFAULT_SORT;
  const raw = mine[mine.length - 1].values[0],
    name = sortName(raw);
  if (!sortKeys.includes(name)) return DEFAULT_SORT;
  const descending = raw[0] === "-" || (raw[0] !== "+" && Boolean(defaultDesc[name]));
  return `${descending ? "-" : "+"}${name}`;
}

// A date: 2026 / 2026-11 / 2026-11-25 (the operator < <= > >= belongs to the key, not the value), or relative to today:
// today, yesterday, tomorrow, -7d, 2w, 3m, -1y. expires=none and expires=never only with = or ==. Same rules as
// dero/query.py (the server is the authority: it also knows when a relative date leaves the calendar).
function validDate(value, key, op) {
  if (OPTIONAL_KEYS.includes(key) && (op === "=" || op === "==" || op === "!=") && /^(none|never)$/i.test(value))
    return true;
  if (/^(today|yesterday|tomorrow|[+-]?\d{1,4}[dwmy])$/i.test(value.trim())) return true;
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(value.trim());
  if (!m) return false;
  const month = Number(m[2] || 1),
    day = Number(m[3] || 1),
    date = new Date(Date.UTC(Number(m[1]), month - 1, day));
  return month >= 1 && month <= 12 && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

const validNumber = (value) => /^\d{1,12}$/.test(value.trim());

// Draw the query with its structure: terms as chips, groups tinted, operators and negations coloured.
// The text of the result is exactly the query text (the highlight sits behind the real input).
const NO_NEGATED_SORT = "A ! has no effect on sort_by: it only says how to sort"; // same text as in dero/query.py
function flagIdle(el) {
  el.classList.add("q-invalid");
  el.title = NO_NEGATED_SORT;
}

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
    // only an operator or a parenthesis with space (or the end of the text) on both sides is shown as a pill; one stuck
    // to another token, as in (a)or(b) or (a or b), stays plain, or its pill would run into its neighbours
    const gap = (other) => !other || other.kind === "ws";
    const apart = gap(parsed.toks[idx - 1]) && gap(parsed.toks[idx + 1]);
    if (t.kind === "ws") top().append(document.createTextNode(raw));
    else if (t.kind === "lpar") {
      const group = span("q-group", "");
      group.dataset.from = t.start;
      top().append(group);
      stack.push(group);
      group.append(span(apart ? "q-paren q-pill q-open" : "q-paren", "(")); // (an opening one never has an x: no room)
    } else if (t.kind === "rpar") {
      const closer = span(apart ? "q-paren q-pill" : "q-paren", ")");
      if (apart && stack.length === 1) {
        // a ) that closes nothing has its own x, which removes just it (like an operator's)
        closer.classList.add("q-stray");
        closer.dataset.from = t.start;
        closer.dataset.to = t.end;
      }
      top().append(closer);
      if (stack.length > 1) {
        top().dataset.to = t.end;
        stack.pop();
      }
    } else if (t.kind === "and" || t.kind === "or") {
      const op = span(apart ? "q-op" : "q-op-tight", raw); // (a pill has its own x)
      if (apart) {
        op.dataset.from = t.start;
        op.dataset.to = t.end;
      }
      top().append(op);
    } else if (t.kind === "not") top().append(span("q-not", "!"));
    else if (!t.key) {
      const word = span("q-term q-k-text", "");
      word.dataset.from = t.removeStart;
      word.dataset.to = t.end;
      const before = parsed.toks[idx - 1],
        last = top().lastChild;
      const negated = before && before.kind === "not" && last?.classList?.contains("q-not");
      if (negated) {
        word.classList.add("q-neg");
        word.append(last);
      } // the "!" belongs to the chip, as with key=value terms
      word.append(raw);
      top().append(word);
    } else {
      // sort_by is a directive, not a filter: a ! in front of it or in != changes nothing, and is marked as such
      const idle = t.key === "sortby" && (t.nots > 0 || t.op === "!=");
      const pill = span(`q-term q-k-${t.key}${t.negated && !idle ? " q-neg" : ""}${t.empty ? " q-empty" : ""}`, "");
      pill.dataset.from = t.removeStart;
      pill.dataset.to = t.end;
      const before = parsed.toks[idx - 1],
        last = top().lastChild;
      if (before && before.kind === "not" && last?.classList?.contains("q-not")) pill.append(last);
      pill.append(span("q-key", t.rawKey));
      // an operator the key does not have (not while the value is still missing: the server says nothing then either)
      if (t.op) {
        const eq = span(t.supported || t.empty ? "q-eq" : "q-eq q-invalid", t.op);
        if (idle && t.op === "!=") flagIdle(eq);
        pill.append(eq);
      }
      const wildcard = TEXT_KEYS.includes(t.key) && t.op !== "=="; // with "==" a * is just a *
      (t.op ? splitRaw(t.rest) : []).forEach((piece, i) => {
        if (i) pill.append(span("q-comma", ","));
        const value = unquote(piece);
        const bad =
          (t.key === "status" && value && !statuses.includes(value.toLowerCase())) ||
          (DATE_KEYS.includes(t.key) && value && !validDate(value, t.key, t.op)) ||
          (t.key === "visits" && value && !validNumber(value)) ||
          (t.key === "sortby" && value && !sortKeys.includes(sortName(value)));
        const shown = span(bad ? "q-val q-invalid" : "q-val", "");
        (wildcard ? piece.split("*") : [piece]).forEach((part, n) => {
          if (n) shown.append(span("q-star", "*")); // the wildcards of a value, in blue
          shown.append(part);
        });
        pill.append(shown);
      });
      top().append(pill);
      if (idle) {
        // every ! in front of it: the one in the chip and any before the chip
        const marks = [...pill.querySelectorAll(":scope > .q-not")];
        for (let prev = pill.previousSibling; prev?.classList?.contains("q-not"); prev = prev.previousSibling)
          marks.push(prev);
        marks.forEach(flagIdle);
      }
    }
  });
  stack.slice(1).forEach((group) => {
    if (!group.dataset.to) group.dataset.to = text.length;
    // a group that is never closed has no x of its own (it would sit on the x of its last term): its ( has room for
    // one that removes just it, like a stray ")"
    group.classList.add("q-unclosed");
    const open = group.firstElementChild;
    if (open?.classList.contains("q-pill")) {
      open.classList.replace("q-open", "q-stray");
      open.dataset.from = group.dataset.from;
      open.dataset.to = String(Number(group.dataset.from) + 1);
    }
  });
}

// Take just an operator (and, or, &&, ||) out; what it joined is then joined by the implicit "and".
function removeOperator(text, from, to) {
  let end = to;
  while (end < text.length && /\s/.test(text[end])) end++;
  let start = from;
  if (end === text.length) while (start > 0 && /\s/.test(text[start - 1])) start--; // at the end: take the space before it
  return applyEdits(text, [{ start, end, text: "" }]).trim();
}

// What taking one part (a term or a group) out of a query removes: the part and the "and"/"or" that joined it to its
// neighbour, as { start, end }.
function partRange(text, from, to) {
  const toks = parseQuery(text).toks.filter((t) => t.kind !== "ws");
  const joins = (t) => t && (t.kind === "and" || t.kind === "or");
  const before = [...toks].reverse().find((t) => t.end <= from),
    after = toks.find((t) => t.start >= to);
  let start = from,
    end = to;
  if (joins(before)) start = before.start;
  else if (joins(after)) end = after.end;
  return { start, end };
}

// Take one part out of a query (see partRange).
function removePart(text, from, to) {
  const { start, end } = partRange(text, from, to);
  return applyEdits(text, [{ start, end, text: "" }]);
}
