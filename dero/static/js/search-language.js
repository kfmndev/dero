// ---- The search language ----
// The server filters (dero/query.py). This is the same tokenizer, used to highlight the search bar and to
// keep the dropdowns and the query text in sync.
const QUERY_KEYS = {
  status: "status",
  created_by: "creator",
  creator: "creator",
  owner: "creator",
  by: "creator",
  slug: "slug",
  target: "target",
  created: "created",
  expires: "expires",
  sort_by: "sortby",
  sortby: "sortby",
  sort: "sortby",
  order: "sortby",
};

function unquote(text) {
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
        const m = /^([A-Za-z_]+)(!?=)([\s\S]*)$/.exec(word);
        const key = m ? QUERY_KEYS[m[1].toLowerCase()] : undefined;
        if (key) {
          toks.push({
            kind: "term",
            start: i,
            end: j,
            key,
            rawKey: m[1],
            op: m[2],
            rest: m[3],
            negated: m[2] === "!=",
            values: splitRaw(m[3])
              .map(unquote)
              .filter((v) => v !== ""),
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
  const name = { creator: "created_by", sortby: "sort_by" }[key] || key; // the dropdowns' names, in snake case
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

// What a dropdown should show for one key: { set: [...] } = those boxes are checked, { custom: true } = too complex for a dropdown
function deriveSet(parsed, key, all) {
  if (!parsed.terms.some((t) => t.key === key)) return { set: all }; // this key isn't used at all
  if (parsed.topLevelOr) return { custom: true }; // used, but inside an "or"
  if (parsed.terms.some((t) => t.key === key && t.depth > 0)) return { custom: true }; // inside a group: too complex
  const mine = parsed.terms.filter((t) => t.key === key && t.depth === 0);
  if (mine.length === 0) return { set: all };
  if (mine.length > 1) return { custom: true };
  const wanted = mine[0].values.map((v) => v.toLowerCase());
  const hit = all.filter((v) => wanted.includes(v.toLowerCase()));
  const set = mine[0].negated ? all.filter((v) => !hit.includes(v)) : hit;
  return set.length || mine[0].negated ? { set } : { custom: true }; // everything excluded = nothing ticked
}

// The sort the query asks for, as the value of the "Sort by" dropdown ("" = the default, newest first)
function deriveSort(parsed, sortKeys) {
  const mine = parsed.toks.filter((t) => t.kind === "term" && t.key === "sortby" && t.values.length);
  if (!mine.length) return "";
  const raw = mine[mine.length - 1].values[0],
    name = raw.replace(/^[+-]/, "").toLowerCase();
  if (!sortKeys.includes(name)) return "";
  const value = `${raw.startsWith("-") ? "-" : ""}${name}`;
  return value === "created" ? "" : value;
}

// created=2026 / 2026-11 / 2026-11-25, optionally after < <= > >=; expires also takes none. Same rules as dero/query.py.
function validDate(value, key) {
  if (key === "expires" && /^(none|never)$/i.test(value)) return true;
  const m = /^(<=|>=|<|>)?(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(value.trim());
  if (!m) return false;
  const month = Number(m[3] || 1),
    day = Number(m[4] || 1),
    date = new Date(Date.UTC(Number(m[2]), month - 1, day));
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
      if (stack.length > 1) {
        top().dataset.to = t.end;
        stack.pop();
      }
    } else if (t.kind === "and" || t.kind === "or") {
      // only an operator with space (or the end of the text) on both sides is shown as a pill with its own x;
      // one stuck to a parenthesis, as in (a)or(b), stays plain
      const gap = (other) => !other || other.kind === "ws";
      const apart = gap(parsed.toks[idx - 1]) && gap(parsed.toks[idx + 1]);
      const op = span(apart ? "q-op" : "q-op-tight", raw);
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
      const pill = span(`q-term q-k-${t.key}${t.negated ? " q-neg" : ""}`, "");
      pill.dataset.from = t.removeStart;
      pill.dataset.to = t.end;
      const before = parsed.toks[idx - 1],
        last = top().lastChild;
      if (before && before.kind === "not" && last?.classList?.contains("q-not")) pill.append(last);
      pill.append(span("q-key", t.rawKey), span("q-eq", t.op));
      splitRaw(t.rest).forEach((piece, i) => {
        if (i) pill.append(span("q-eq", ","));
        const value = unquote(piece);
        const bad =
          (t.key === "status" && value && !statuses.includes(value.toLowerCase())) ||
          ((t.key === "created" || t.key === "expires") && value && !validDate(value, t.key)) ||
          (t.key === "sortby" && value && !sortKeys.includes(value.replace(/^[+-]/, "").toLowerCase()));
        pill.append(span(bad ? "q-val q-invalid" : "q-val", piece));
      });
      top().append(pill);
    }
  });
  stack.slice(1).forEach((group) => {
    if (!group.dataset.to) group.dataset.to = text.length;
  }); // a group that is never closed
}

// Take just an operator (and, or, &&, ||) out; what it joined is then joined by the implicit "and".
function removeOperator(text, from, to) {
  let end = to;
  while (end < text.length && /\s/.test(text[end])) end++;
  let start = from;
  if (end === text.length) while (start > 0 && /\s/.test(text[start - 1])) start--; // at the end: take the space before it
  return applyEdits(text, [{ start, end, text: "" }]).trim();
}

// Take one part (a term or a group) out of a query, together with the "and"/"or" that joined it to its neighbour.
function removePart(text, from, to) {
  const toks = parseQuery(text).toks.filter((t) => t.kind !== "ws");
  const joins = (t) => t && (t.kind === "and" || t.kind === "or");
  const before = [...toks].reverse().find((t) => t.end <= from),
    after = toks.find((t) => t.start >= to);
  let start = from,
    end = to;
  if (joins(before)) start = before.start;
  else if (joins(after)) end = after.end;
  return applyEdits(text, [{ start, end, text: "" }]);
}
