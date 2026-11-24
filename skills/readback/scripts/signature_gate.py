"""The signature rule as a gate on a note. Standard library only, no other file of the skill is needed, so that a
project with its own build can carry this one file.

The rule. A function, relation or predicate that the artifact defines is written with every explicit argument of
its Lean definition, in every place. Every argument and every hypothesis of a stated declaration stands inside
its statement, or in a numbered Setting that the statement cites; only ambient objects (implicit and instance
arguments) may stand in the note's conventions. Nothing is fixed and dropped.

What the gate is given (`accounts`, the note's spec):
  declarations   {key: {...}} or a list of entries with "key". Per entry:
      notation   {"macro", "slots", "tex", "symbol", "also"} for a definition with explicit arguments: the macro has
                 one slot for each explicit argument of the Lean definition (`slots`: their Lean names, in the order
                 of the macro's slots; an argument without a name is named by its type); or {"none": reason}
      binders    {Lean name | "#position" | type: the words of the statement that state the argument}
      absorbed   the reason why a small result has no statement of its own
  letters        {Lean name of a variable: how the note writes it}; the letter must stand in the statement
  words          {head of a hypothesis's type, e.g. "GenBy": the words that state it, or a list of alternatives}
  ambient        {Lean name | type: words} for implicit and instance arguments; looked for in the conventions too
  conventions    the label of the note's conventions
  lettered       [[words, label], …]: places named by words ("Theorem A")
A project with several notes keeps one table for all of them (`with_shared`): how each Lean definition is written.
and `conc`: {key: {"kind", "id", "binders": [{"name", "kind", "type", "from", "maybe"}, …]}}.

The words are found as written, white space aside. No program sees whether they say the right thing.
"""
from __future__ import annotations

import re

DEFS = ("def", "abbrev", "structure", "class", "inductive", "opaque")       # declarations that introduce a notion
THMS = ("theorem", "lemma", "axiom")                                        # declarations that assert
BLOCKS = ("theorem", "lemma", "proposition", "corollary", "definition", "remark", "example", "setting", "conventions")
SHARED = ("setting", "conventions")                                         # statements that others may cite for their hypotheses


def norm(s) -> str:
    return " ".join(str(s or "").split())


def explicit(bs) -> list:
    return [b for b in bs or [] if b.get("kind") == "explicit"]


def key(b: dict) -> str:
    """How an argument is named in a table: by its name, or by its type when it has none."""
    return b["name"] if b.get("name") else norm(b.get("type"))


def show(b: dict) -> str:
    o, c = {"explicit": "()", "implicit": "{}", "strict": "⦃⦄", "instance": "[]"}[b["kind"]]
    return o + (b.get("name") or "") + (" : " if b.get("name") and b.get("type") else "") + (b.get("type") or "") + c


def head(typ) -> str:
    """The first name of a type: `GenBy l R X` -> GenBy, `Function.Surjective f` -> Function.Surjective."""
    m = re.match(r"\s*[(¬]*\s*((?:[^\W\d][\w'!?]*)(?:\.[^\W\d][\w'!?]*)*)", str(typ or ""))
    return m.group(1) if m else ""


def group_end(s: str, i: int) -> int:
    """The index of the brace that closes the group opened at s[i] == '{'; -1 when there is none."""
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        depth += (s[j] == "{") - (s[j] == "}")
        if depth == 0:
            return j
        j += 1
    return -1


def flat(s) -> str:
    return " ".join(str(s or "").replace("~", " ").split())


def uncommented(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def tex_blocks(tex: str) -> dict:
    """label -> (kind, text) for every statement of a note: the theorem-like environments, `setting`,
    `conventions`, and the tinted \\statement boxes. A statement is where hypotheses must stand."""
    body = uncommented(tex)
    out = {}
    for m in re.finditer(r"\\begin\{(%s)\}(.*?)\\end\{\1\}" % "|".join(BLOCKS), body, re.S):
        for lab in re.findall(r"\\label\{([^}]+)\}", m.group(2)):
            out[lab] = (m.group(1), m.group(2))
    for m in re.finditer(r"\\statement\s*\{", body):
        a = group_end(body, m.end() - 1)
        b = group_end(body, a + 1) if a > 0 and body[a + 1:a + 2] == "{" else -1
        if b > 0:
            for lab in re.findall(r"\\label\{([^}]+)\}", body[a + 2:b]):
                out.setdefault(lab, ("statement", body[a + 2:b]))
    return out


def places(accounts: dict, tex: str) -> dict:
    """key -> (the words of its \\cs{key}{…}, the label they name or None)."""
    where = dict(re.findall(r"\\cs\{(\w+)\}\{((?:[^{}]|\{[^{}]*\})*)\}", tex))
    out = {}
    for k, raw in where.items():
        refs = re.findall(r"\\ref\{([^}]+)\}", raw)
        out[k] = (raw, next((lab for words, lab in accounts.get("lettered") or [] if raw.replace("~", " ").startswith(words)),
                            refs[0] if refs else None))
    return out


def entries(accounts: dict) -> dict:
    d = accounts.get("declarations") or {}
    return d if isinstance(d, dict) else {e["key"]: e for e in d}


def with_shared(accounts: dict, shared: dict, lean_names: dict, kinds: dict | None = None) -> dict:
    """The accounts of one note over a table that all notes of a project share, so that one Lean definition is
    written in one way everywhere. `shared`: {"notations": {Lean name or its last part: notation}, "letters",
    "words", "ambient"}; `lean_names`: {key: Lean name}; `kinds`: {key: kind}, so that a notation goes to a definition
    and never to a theorem that has the same last name. What the note says for itself wins."""
    acc = dict(accounts)
    for name in ("ambient", "letters", "words"):
        acc[name] = dict((shared or {}).get(name) or {}, **(accounts.get(name) if isinstance(accounts.get(name), dict) else {}))
    table = (shared or {}).get("notations") or {}
    listed = isinstance(accounts.get("declarations"), list)
    ent = {k: dict(e) for k, e in entries(accounts).items()}
    bound = set()
    for k, lean in lean_names.items():
        if kinds is not None and kinds.get(k) not in DEFS:
            continue
        name = lean if lean in table else str(lean).split(".")[-1]
        common = table.get(name)
        if common:
            bound.add(name)
            if "notation" not in ent.setdefault(k, {"key": k}):
                ent[k]["notation"] = common
    acc["declarations"] = list(ent.values()) if listed else ent
    acc["shared"] = {name: nt for name, nt in table.items() if name not in bound and isinstance(nt, dict) and nt.get("macro")}
    return acc


def uses(body: str, name: str, n: int) -> list:
    """Every use of \\name in the text, as (line, how many of its n arguments are written)."""
    out = []
    for m in re.finditer(r"\\%s(?![A-Za-z])" % re.escape(name), body):
        j, got = m.end(), 0
        while got < n:
            j += len(body[j:]) - len(body[j:].lstrip())
            end = group_end(body, j) if body[j:j + 1] == "{" else -1
            if end < 0:
                break
            j, got = end + 1, got + 1
        out.append((body.count("\n", 0, m.start()) + 1, got))
    return out


def symbols(nt: dict) -> list:
    """The bare symbols of a notation: one, or a list whose first is in the notation's own TeX and whose others are
    further ways in which the notion could be written by hand."""
    sym = nt.get("symbol")
    return [str(x).strip() for x in (sym if isinstance(sym, list) else [sym]) if str(x or "").strip()]


def bare(body: str, symbol) -> int:
    """In how many places a bare symbol of a notation is written by hand."""
    return sum(len(re.findall(re.escape(x) + (r"(?![A-Za-z])" if x[-1:].isalpha() else ""), body))
               for x in (symbol if isinstance(symbol, list) else [symbol]) if x)


def gate(accounts: dict, conc: dict, tex: str, triage: dict | None = None) -> tuple:
    """Returns the problems, the things to look at, the TeX of the notation macros, and counts."""
    problems, looks, macros = [], [], []
    count = {"notations": 0, "uses": 0, "arguments": 0, "stated": 0, "absorbed": 0}
    triage = triage or {}
    body = uncommented(tex)
    blocks = tex_blocks(tex)
    place = places(accounts, tex)
    conv_label = accounts.get("conventions")
    conv = flat(blocks[conv_label][1]) if conv_label in blocks else ""
    if conv_label and conv_label not in blocks:
        problems.append(f"the conventions are said to be at \\label{{{conv_label}}}, and no conventions environment or statement has that label")
    table = lambda name: accounts.get(name) if isinstance(accounts.get(name), dict) else {}      # noqa: E731
    ambient, letters, words = table("ambient"), table("letters"), table("words")
    ent, taken = entries(accounts), set()
    for k, v in conc.items():
        e, bs = ent.get(k) or {}, v.get("binders")
        if v["kind"] not in DEFS + THMS:
            continue
        if bs is None:
            problems.append(f"{k}: its arguments cannot be read from the text; the reader records them in the dossier from Lean "
                            "(binders, binders_basis \"lean\"), and the note takes them from there")
            continue
        ex = explicit(bs)
        nt = e.get("notation") if v["kind"] in DEFS else None
        slots, forms, name = [], {}, ""
        if v["kind"] in DEFS and ex:
            want = [key(b) for b in ex]
            if not isinstance(nt, dict):
                problems.append(f"{k}: a definition with {len(ex)} explicit arguments ({', '.join(want)}) and no `notation`. "
                                "A defined function is written through a macro with one slot for each explicit argument")
            elif str(nt.get("none") or "").strip():
                looks.append(f"{k}: no notation of its own ({nt['none']}); its {len(ex)} explicit arguments are accounted for as words of its statement")
            else:
                name, form, slots = str(nt.get("macro") or ""), str(nt.get("tex") or ""), nt.get("slots")
                forms = dict({name: form}, **(nt.get("also") if isinstance(nt.get("also"), dict) else {}))
                bad = [n for n in forms if not re.fullmatch(r"[A-Za-z]+", n) or n in taken]
                if bad or not form.strip() or not isinstance(slots, list):
                    problems.append(f"{k}: its notation needs a macro name of letters that no other notation has, the TeX of the notation (tex) and the slots")
                    slots = []
                elif sorted(map(str, slots)) != sorted(want):
                    problems.append(f"{k}: its notation has the slots {', '.join(map(str, slots)) or 'none'}; Lean's explicit arguments are "
                                    f"{', '.join(want)}. The number of arguments of a defined function is never changed: "
                                    "none is fixed and dropped, also not for a section")
                    slots = []
                else:
                    taken.update(forms)
                    count["notations"] += 1
                    sym = symbols(nt)
                    for n, f in forms.items():
                        hidden = [f"#{i + 1} ({slots[i]})" for i in range(len(slots)) if f"#{i + 1}" not in f]
                        if hidden:
                            problems.append(f"{k}: the notation \\{n} does not display its argument {', '.join(hidden)}")
                        if re.search(r"\\%s(?![A-Za-z])" % n, f):
                            problems.append(f"{k}: the notation \\{n} calls itself")
                        macros.append(r"\newcommand{\%s}[%d]{%s}" % (n, len(slots), f))
                        for line, got in uses(body, n, len(slots)):
                            count["uses"] += 1
                            if got < len(slots):
                                problems.append(f"{k}: \\{n} in line {line} is written with {got} of its {len(slots)} arguments")
                    if sym and sym[0] not in form:
                        problems.append(f"{k}: the symbol {sym[0]} is not in the notation's own TeX, so it could not be recognized when written by hand")
                    elif bare(body, sym):
                        problems.append(f"{k}: the symbol {' or '.join(sym)} is written by hand in {bare(body, sym)} places; write it only through \\{name}, "
                                        "which shows every argument")
        if str(e.get("absorbed") or "").strip():
            if v["kind"] in THMS and triage.get(v.get("id")) in ("argument", "assembly"):
                problems.append(f"{k}: the dossier sorts it as {triage[v['id']]}; such a result is stated in the note with all its hypotheses, not absorbed")
            else:
                count["absorbed"] += 1
                looks.append(f"{k}: not stated on its own ({e['absorbed']}); its arguments are not accounted for")
            continue
        raw, label = place.get(k, ("", None))
        if label not in blocks:
            problems.append(f"{k}: its place \"{raw}\" is not a statement of its own. A declaration is stated in a definition, a theorem-like "
                            "environment or a \\statement box that carries the label, so that its arguments and hypotheses can be found there; "
                            "or it is marked `absorbed` with the reason")
            continue
        count["stated"] += 1
        own = flat(blocks[label][1])
        cited = " ".join(flat(blocks[lab][1]) for lab in re.findall(r"\\ref\{([^}]+)\}", blocks[label][1])
                         if blocks.get(lab, ("",))[0] in SHARED)
        if slots and not any(re.search(r"\\%s(?![A-Za-z])" % n, blocks[label][1]) for n in forms):
            problems.append(f"{k}: the statement at \"{raw}\" never writes its notation \\{name}")
        given = e.get("binders") if isinstance(e.get("binders"), dict) else {}
        rest = list(map(str, slots))
        for i, b in enumerate(bs, 1):
            if b["kind"] == "explicit" and key(b) in rest:
                rest.remove(key(b))                        # shown by the notation, in every place
                count["arguments"] += 1
                continue
            keys = [x for x in (b.get("name"), f"#{i}", norm(b.get("type"))) if x]
            wide = b["kind"] != "explicit"
            phrase = next((given[x] for x in keys if str(given.get(x) or "").strip()), None)
            if phrase is None and b.get("name") and str(letters.get(b["name"]) or "").strip():
                phrase = letters[b["name"]]
            if phrase is None and words.get(head(b.get("type"))):
                phrase = words[head(b.get("type"))]
            if phrase is None and wide:
                phrase = next((ambient[x] for x in keys if str(ambient.get(x) or "").strip()), None)
            if phrase is None and b.get("maybe"):
                continue                                   # an instance that a definition takes only when its term uses it
            hay = own + " " + cited + (" " + conv if wide else "")
            if phrase is None:
                problems.append(f"{k}: argument {i}, {show(b)}, is not accounted for. Give in the declaration's `binders`, under \"{keys[0]}\""
                                + (", or in `ambient`" if wide else "") + ", the words of the statement that state it "
                                "(a variable may stand in `letters`, a hypothesis under the head of its type in `words`)")
            elif not any(flat(x) in hay for x in (phrase if isinstance(phrase, list) else [phrase])):
                said = " or ".join(f"\"{x}\"" for x in (phrase if isinstance(phrase, list) else [phrase]))
                problems.append(f"{k}: argument {i}, {show(b)}, is said to be stated as {said}, and these words are neither in the statement "
                                f"at \"{raw}\" nor in a Setting it cites" + (" nor in the conventions" if wide else "")
                                + (". A hypothesis stands inside the statement, never in a sentence before it" if b["kind"] == "explicit" else ""))
            else:
                count["arguments"] += 1
    # Notations of the shared table for definitions that this note uses without citing them: a use is held to the
    # same rule (every slot written, the bare symbol never by hand). Lean's arguments are those of the table, which
    # the notes that cite the definition have checked.
    for lean, nt in sorted((accounts.get("shared") or {}).items()):
        slots = nt.get("slots") if isinstance(nt.get("slots"), list) else []
        forms = dict({str(nt.get("macro")): str(nt.get("tex") or "")}, **(nt.get("also") if isinstance(nt.get("also"), dict) else {}))
        if set(forms) & taken:
            continue
        found = {n: uses(body, n, len(slots)) for n in forms}
        if not any(found.values()):
            continue                                       # the note does not use this notation
        taken.update(forms)
        count["notations"] += 1
        sym = symbols(nt)
        for n, f in forms.items():
            hidden = [f"#{i + 1} ({slots[i]})" for i in range(len(slots)) if f"#{i + 1}" not in f]
            if hidden or re.search(r"\\%s(?![A-Za-z])" % n, f):
                problems.append(f"{lean} (shared table): the notation \\{n} does not display its argument {', '.join(hidden)} or calls itself")
            macros.append(r"\newcommand{\%s}[%d]{%s}" % (n, len(slots), f))
            for line, got in found[n]:
                count["uses"] += 1
                if got < len(slots):
                    problems.append(f"{lean} (shared table): \\{n} in line {line} is written with {got} of its {len(slots)} arguments")
        if sym and sym[0] not in forms[str(nt.get("macro"))]:
            problems.append(f"{lean} (shared table): the symbol {sym[0]} is not in the notation's own TeX")
        elif bare(body, sym):
            problems.append(f"{lean} (shared table): the symbol {' or '.join(sym)} is written by hand in {bare(body, sym)} places; write it only through "
                            f"\\{nt['macro']}, which shows every argument")
    return problems, looks, macros, count


def broken_copies(accounts: dict, conc: dict, tex: str, triage: dict | None = None) -> tuple:
    """Try the gate on copies of the note that break the rule on purpose: for each notation, one use with its last
    argument removed, and its bare symbol written by hand once. Returns how many copies were tried and the ones that
    the gate did not catch. A gate that says nothing has to be seen saying something."""
    tried, missed = 0, []
    body_at = tex.find(r"\begin{document}")
    rows = [(k, e.get("notation") if isinstance(e.get("notation"), dict) else {}, f"{k}: ") for k, e in entries(accounts).items() if k in conc]
    rows += [(lean, nt, f"{lean} (shared table): ") for lean, nt in (accounts.get("shared") or {}).items()]
    for k, nt, lead in rows:
        name, slots, sym = str(nt.get("macro") or ""), nt.get("slots"), symbols(nt)
        if not name or not isinstance(slots, list):
            continue
        m = re.search(r"\\%s(?![A-Za-z])" % re.escape(name), tex[max(body_at, 0):])
        if m:
            j = max(body_at, 0) + m.end()
            ends = []
            for _ in slots:
                j += len(tex[j:]) - len(tex[j:].lstrip())
                end = group_end(tex, j) if tex[j:j + 1] == "{" else -1
                if end < 0:
                    break
                ends.append((j, end))
                j = end + 1
            if len(ends) == len(slots):
                a, b = ends[-1]
                tried += 1
                if not any(f"{lead}\\{name} in line" in p for p in gate(accounts, conc, tex[:a] + tex[b + 1:] + "\n\\relax ", triage)[0]):
                    missed.append(f"{k}: a use of \\{name} with one argument less")
        elif lead.endswith("(shared table): "):
            continue                                       # a shared notation that this note does not use
        for one in sym:
            tried += 1
            cut = tex.rfind(r"\end{document}")
            copy = tex[:cut] + "\n$" + one + "$\n" + tex[cut:] if cut >= 0 else tex + "\n$" + one + "$\n"
            if not any(f"{lead}the symbol" in p for p in gate(accounts, conc, copy, triage)[0]):
                missed.append(f"{k}: the symbol {one} written by hand")
    return tried, missed


def skeleton(accounts: dict, conc: dict, tex: str) -> tuple:
    """What an existing note still needs under the rule, added to its accounts as empty places to fill in (nothing
    that is there is changed). Returns the accounts and a report in words."""
    ent = entries(accounts)
    listed = isinstance(accounts.get("declarations"), list)
    accounts.setdefault("conventions", "c:conventions")
    for name in ("ambient", "letters", "words"):
        if not isinstance(accounts.get(name), dict):
            accounts[name] = {}
    lines = []
    for k, v in conc.items():
        bs = v.get("binders")
        if v["kind"] not in DEFS + THMS or bs is None:
            continue
        e = ent.get(k)
        if e is None:
            e = {"key": k}
            ent[k] = e
            if listed:
                accounts["declarations"].append(e)
        ex = explicit(bs)
        if v["kind"] in DEFS and ex and not isinstance(e.get("notation"), dict):
            e["notation"] = {"macro": re.sub(r"[^A-Za-z]", "", k) or "notion", "slots": [key(b) for b in ex], "tex": "", "symbol": ""}
            lines.append(f"{k}: a notation is needed for ({', '.join(key(b) for b in ex)})")
        for b in bs:
            if b["kind"] != "explicit" and not b.get("maybe"):
                accounts["ambient"].setdefault(key(b), "")
            elif b["kind"] == "explicit" and b.get("name") and not head(b.get("type"))[:1].isupper():
                accounts["letters"].setdefault(b["name"], "")
            elif b["kind"] == "explicit" and head(b.get("type")):
                accounts["words"].setdefault(head(b.get("type")), "")
    if not listed:
        accounts["declarations"] = ent
    problems = gate(accounts, conc, tex)[0]
    return accounts, lines + problems
