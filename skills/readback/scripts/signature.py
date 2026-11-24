"""The arguments of a Lean declaration, read from its text.

A declaration takes the binders written in its own signature, before the colon of its type, and those section
`variable`s that Lean includes. The first part is certain: it is what the file says. The second is a reading of
Lean's rule from the text (a variable is included when the declaration mentions it, or when it is an instance
argument all of whose variables are included; a theorem counts only its statement, a definition its body too),
so it can differ from what Lean does: a definition takes only the instances its elaborated term really uses (such
an argument is marked `maybe` here), and an argument that Lean binds by itself (`autoImplicit`) is not in the text
at all. Lean decides: `#check @Name`. Compared with Lean 4.35 on a file without imports: theorems agree; a
definition whose term does not use an instance variable has that argument less than this reading gives.

Kinds: `explicit` (x : T), `implicit` {x : T}, `strict` ⦃x : T⦄, `instance` [C x].
"""
from __future__ import annotations

import re

from signature_gate import explicit, key, norm, show     # noqa: F401  (used by callers of this module)
from source_ranges import tokens

KIND = {"(": "explicit", "{": "implicit", "⦃": "strict", "[": "instance"}
CLOSE = {"(": ")", "{": "}", "⦃": "⦄", "[": "]"}
KINDS = ("explicit", "implicit", "strict", "instance")
STOP = {":", ":=", "where", "|", "extends", "deriving"}
IDENT = re.compile(r"[^\W\d][\w'!?]*|_")
NOT_NAMES = {"fun", "λ", "Π", "Σ", "∀", "∃", "by", "let", "have", "show", "from", "at", "with", "in", "do", "if", "then", "else", "match"}


def idents(text: str) -> set:
    """The identifiers of a piece of Lean text; `l.Prime` counts as `l` and as `Prime`."""
    return {t.word for t in tokens(text or "") if IDENT.fullmatch(t.word)} - NOT_NAMES


def _group(inner: str, kind: str) -> list:
    """The binders of one bracket group, from the text between its brackets."""
    toks = list(tokens(inner))
    colon = next((t for t in toks if t.depth == 0 and t.word == ":"), None)
    typ = default = None
    if colon:
        left, right = inner[:colon.a], inner[colon.b:]
        dflt = next((t for t in tokens(right) if t.depth == 0 and t.word == ":="), None)
        typ, default = norm(right[:dflt.a] if dflt else right), bool(dflt)
    else:
        dflt = next((t for t in toks if t.depth == 0 and t.word == ":="), None)
        left, default = (inner[:dflt.a] if dflt else inner), bool(dflt)
    if kind == "instance":                                  # [C x] or [name : C x]
        return [{"name": norm(left) if colon else None, "kind": kind, "type": typ if colon else norm(inner)}]
    names = [t.word for t in tokens(left)]
    if not names:
        return []
    if not all(IDENT.fullmatch(n) for n in names):          # a pattern such as ⟨a, b⟩: one binder, shown as written
        names = [norm(left)]
    return [dict({"name": n, "kind": kind, "type": typ}, **({"default": True} if default else {})) for n in names]


def read_binders(text: str, start: int = 0) -> tuple:
    """The binder groups of `text` from `start` up to the colon of the type (or `:=`, `where`, `|`).
    Returns the binders, the offset where reading stopped, and whether the text was understood."""
    toks = list(tokens(text, start))
    out, i = [], 0
    if len(toks) > 1 and toks[0].word == "." and toks[1].word == "{":      # universe parameters: name.{u v}
        i = next((j for j in range(2, len(toks)) if toks[j].depth == 0 and toks[j].word == "}"), len(toks) - 1) + 1
    while i < len(toks):
        t = toks[i]
        if t.word in STOP:
            return out, t.a, True
        if t.word in KIND:
            j = next((k for k in range(i + 1, len(toks)) if toks[k].depth == t.depth and toks[k].word == CLOSE[t.word]), None)
            if j is None:
                return out, t.a, False
            inner, kind = text[t.b:toks[j].a], KIND[t.word]
            if kind == "implicit" and inner.strip().startswith("{") and inner.strip().endswith("}"):
                inner, kind = inner.strip()[1:-1], "strict"                 # {{x : T}}
            out += _group(inner, kind)
            i = j + 1
        elif IDENT.fullmatch(t.word) and t.word not in NOT_NAMES:           # a bare binder: `def f x y := …`
            out.append({"name": t.word, "kind": "explicit", "type": None})
            i += 1
        else:
            return out, t.a, False
    return out, len(text), True


PRED = {"∈", "∉", ">", "≥", "<", "≤", "≠", "⊆", "⊂", "⊇", "⊃"}
GROUPED = re.compile(r"\s*[({\[⦃]")


def type_binders(text: str) -> list:
    """The arguments that the written type itself binds, in front of its conclusion: `∀ x y : T,`, `∀ (x : T) [C x],`,
    `(x : T) →`, and each premise `P →`. A premise is an explicit argument without a name. Reading stops at the
    conclusion, and at anything this reading does not understand."""
    out, pos = [], 0
    while True:
        toks = [t for t in tokens(text, pos)]
        if not toks:
            return out
        top = [t for t in toks if t.depth == 0]
        if toks[0].word == "∀":
            comma = next((t for t in top if t.word == ","), None)
            if comma is None:
                return out
            inner = text[toks[0].b:comma.a]
            bs, stop, ok = read_binders(inner)
            rest = inner[stop:].strip()
            bare = [b for b in bs if b["type"] is None and b["kind"] == "explicit"]
            if rest.startswith(":") and not rest.startswith(":=") and len(bare) == len(bs):   # ∀ x y : T,
                for b in bs:
                    b["type"] = norm(rest[1:])
            elif not ok and bare and len(bare) == len(bs) and rest[:1] in PRED:               # ∀ x ∈ S,  is  ∀ x, x ∈ S →
                bs = bs + [{"name": None, "kind": "explicit", "type": norm(f"{b['name']} {rest}")} for b in bare]
            elif not ok or rest:
                return out
            out += bs
            pos = comma.b
            continue
        arrow = next((t for i, t in enumerate(top) if t.word == "→" or
                      (t.word == "-" and i + 1 < len(top) and top[i + 1].word == ">" and top[i + 1].a == t.b)), None)
        if arrow is None:
            return out
        before = [t.word for t in top if t.a < arrow.a]
        if not before or set(before) & {",", "↔", "=>", ":=", "∃", "fun", "λ"}:
            return out                                      # the arrow lies inside the conclusion
        premise = text[pos:arrow.a]
        group, stop, ok = read_binders(premise) if GROUPED.match(premise) else ([], 0, False)
        if ok and group and stop == len(premise) and all(
                b["kind"] == "instance" or (b["type"] and IDENT.fullmatch(b["name"] or "")) for b in group):
            out += group                                    # (x : T) → …: a named argument
        else:
            out.append({"name": None, "kind": "explicit", "type": norm(premise)})
        pos = arrow.b + (1 if arrow.word == "-" else 0)


def omitted(text: str) -> list:
    """What an `omit` names: variables by name, instance arguments by their type."""
    bs, _, _ = read_binders(text)
    return [norm(b["type"]) if b["kind"] == "instance" and not b["name"] else b["name"] for b in bs]


PART = re.compile(r"\b(variable|include|omit)\b(.*?)\bin(?=\s|$)", re.S)


def prefix(text: str) -> tuple:
    """The parts of a command prefix (`variable (x : T) in`, `include h in`, `omit [C] in`) that change the
    arguments of the one declaration after it: extra variables, names to include, what to leave out."""
    extra, forced, left = [], [], []
    for word, rest in PART.findall(text or ""):
        if word == "variable":
            extra += read_binders(rest)[0]
        elif word == "include":
            forced += sorted(idents(rest))
        else:
            left += omitted(rest)
    return extra, forced, left


class Variables:
    """The section variables in force while a file is read from top to bottom."""

    def __init__(self):
        self.rows = []                                      # {"name", "kind", "type", "depth"} or an update of a kind
        self.forced = []                                    # (name, depth): `include x`
        self.left = []                                      # (name or instance type, depth): `omit [C x]`

    def declare(self, text: str, depth: int) -> None:
        binders, _, _ = read_binders(text)
        known = {r["name"] for r in self.rows if r.get("name")}
        for b in binders:
            update = b["type"] is None and b["kind"] != "instance" and b["name"] in known     # `variable {x}` changes how x is bound
            self.rows.append(dict(b, depth=depth, update=update))

    def include(self, text: str, depth: int) -> None:
        self.forced += [(w, depth) for w in idents(text)]

    def omit(self, text: str, depth: int) -> None:
        self.left += [(w, depth) for w in omitted(text)]

    def close(self, depth: int) -> None:
        """A scope ended: what was declared deeper than `depth` is gone."""
        self.rows = [r for r in self.rows if r["depth"] <= depth]
        self.forced = [f for f in self.forced if f[1] <= depth]
        self.left = [f for f in self.left if f[1] <= depth]

    def now(self) -> list:
        out = []
        for r in self.rows:
            if r["update"]:
                for o in out:
                    if o["name"] == r["name"]:
                        o["kind"] = r["kind"]
            else:
                out = [o for o in out if not (o["name"] and o["name"] == r["name"])]          # a later variable of the same name hides the earlier
                out.append({k: r[k] for k in ("name", "kind", "type") if k in r})
        return out


def binders(kind: str, text: str, name_end: int, statement_end: int, variables: list, forced=(), omitted=(), extra=()) -> dict:
    """All arguments of a declaration: the included section variables, then the binders of its signature.

    `text` is the declaration, `name_end` the offset after its name, `statement_end` the offset of `:=`, `where` or
    `|`; `extra` are binders of a `variable … in` prefix; `forced` and `omitted` come from `include` and `omit`."""
    own, stop, ok = read_binders(text[:statement_end], name_end)
    typed = type_binders(text[stop + 1:statement_end]) if ok and text[stop:stop + 1] == ":" and text[stop:stop + 2] != ":=" else []
    variables = list(variables) + list(extra)
    scan = text if kind not in ("theorem", "lemma") else text[name_end:statement_end]
    seen, bound = idents(scan), {b["name"] for b in own + typed if b["name"]}
    left = {norm(o) for o in omitted}
    usable = [v for v in variables if not (v["name"] and v["name"] in bound)                  # the signature binds the name anew
              and norm(v["name"]) not in left and norm(v["type"]) not in left]
    names = {v["name"] for v in variables if v["name"]}     # also those hidden or omitted: an instance over one of them stays out
    inc = [bool(v["name"]) and (v["name"] in seen or v["name"] in forced) for v in usable]
    named = list(inc)                                       # taken because the declaration names them
    changed = True
    while changed:
        changed = False
        have = {v["name"] for i, v in enumerate(usable) if inc[i] and v["name"]}
        for i, v in enumerate(usable):
            deps = idents(v["type"]) & names
            if inc[i]:                                      # what an included variable's type mentions comes along
                for j, w in enumerate(usable):
                    if not inc[j] and w["name"] in deps:
                        inc[j] = changed = True
            elif v["kind"] == "instance" and deps <= have:
                inc[i] = changed = True                     # an instance argument over included variables only
    # A theorem takes every instance variable over its variables. A definition takes one only when its term uses
    # the instance, which the text does not show: such an argument is marked `maybe`.
    unsure = kind not in ("theorem", "lemma")
    took = [dict(v, **{"from": "variable"}, **({"maybe": True} if unsure and v["kind"] == "instance" and not named[i] else {}))
            for i, v in enumerate(usable) if inc[i]]
    return {"binders": took + [dict(b, **{"from": "signature"}) for b in own] + [dict(b, **{"from": "type"}) for b in typed], "read": ok}


def same(a, b) -> bool:
    """Do two binders agree? Kinds must; names must unless one is an instance (Lean names those itself);
    types are compared, white space aside, only when both are given for an instance without a name."""
    if a.get("kind") != b.get("kind"):
        return False
    if a.get("kind") == "instance":
        ta, tb = norm(a.get("type")), norm(b.get("type"))
        return not (ta and tb) or ta == tb or bool(a.get("name") and a.get("name") == b.get("name"))
    return a.get("name") == b.get("name")


def matches(mine, src) -> bool:
    """Is `mine` the list `src`, entry by entry, with some of the entries marked `maybe` left out?"""
    i = 0
    for b in src:
        if i < len(mine) and same(mine[i], b):
            i += 1
        elif not b.get("maybe"):
            return False
    return i == len(mine)


def subsequence(part, whole) -> bool:
    it = iter(whole)
    return all(any(same(p, w) for w in it) for p in part)
