#!/usr/bin/env python3
"""Self-test of readback: runs the whole chain on examples/tiny-lean in a temporary directory.

    python3 tests/selftest.py            # exit 0 when every stage passes; LaTeX stages are skipped without latexmk
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RB = ROOT / "skills" / "readback" / "scripts" / "rb.py"
fails, skipped = [], []


def run(ws, *args, expect=0):
    r = subprocess.run([sys.executable, str(ws / "tools" / "rb.py") if (ws / "tools" / "rb.py").exists() else str(RB), *args],
                       cwd=ws if ws.exists() else None, capture_output=True, text=True)
    ok = r.returncode == expect and "Traceback (most recent call last)" not in r.stderr
    print(("PASS" if ok else "FAIL"), "rb.py", " ".join(args[:4]), "" if ok else f"(exit {r.returncode}, expected {expect})\n{r.stdout[-600:]}{r.stderr[-600:]}")
    if not ok:
        fails.append(args)
    return r


def expect(name, cond):
    print("PASS" if cond else "FAIL", name)
    if not cond:
        fails.append(name)


sys.path.insert(0, str(RB.parent))
import rb as _rb                                           # noqa: E402
import os                                                  # noqa: E402
os.environ["READBACK_CONFIG"] = os.devnull                # the tests never read the user's own defaults
import signature as _sig                                   # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    lean = Path(tmp) / "Args.lean"
    lean.write_text("namespace T\n"
                    "variable (l : Nat) [Fact (0 < l)]\n"
                    "def lev (u : Nat) (c : Nat) : Prop := u = c + l\n"
                    "abbrev jz (l R : Nat) : Nat := l + R\n"
                    "variable {l} {X : Type}\n  [Inhabited X]\n"
                    "def tw (g : X → X) (u : Nat) (e m : Nat) : Nat := l + u + e + m\n"
                    "theorem a {R : Nat} (g : X → X) (hu : lev l 1 R) : ∀ e : Nat, tw g 1 e 0 = tw g 1 e 0 := fun _ => rfl\n"
                    "theorem b : ∀ (n : Nat) [Inhabited Nat], n = n → ∀ m ∈ [n], m = m := sorry\n"
                    "theorem p : ∀ (D : Type) (f : D → D), (∀ φ : D, ∃ k : Nat, f φ = φ) → (y : D) → f y = y := sorry\n"
                    "omit [Inhabited X] in\n"
                    "theorem c (x : X) : x = x := rfl\n"
                    "end T\n"
                    "theorem d (x : Nat) (h : x = x := by rfl) : x = x := rfl\n", encoding="utf-8")
    got = {d["name"]: " ".join(_sig.show(b) + {"variable": "v", "signature": "", "type": "t"}[b["from"]] for b in d["binders"])
           for d in _rb.read_module(lean, "Args")["declarations"]}
    expect("arguments: a definition takes its own binders and the section variables it mentions",
           got["T.lev"] == "(l : Nat)v [Fact (0 < l)]v (u : Nat) (c : Nat)" and got["T.jz"] == "(l : Nat) (R : Nat)")
    expect("arguments: a later `variable {l}` changes how l is bound, and four explicit arguments stay four",
           got["T.tw"] == "{l : Nat}v [Fact (0 < l)]v {X : Type}v [Inhabited X]v (g : X → X) (u : Nat) (e : Nat) (m : Nat)")
    tw = next(d for d in _rb.read_module(lean, "Args")["declarations"] if d["name"] == "T.tw")["binders"]
    expect("arguments: an instance variable of a definition may be left out of an account (Lean takes it only when the term uses it), an explicit argument never",
           [b.get("maybe", False) for b in tw] == [False, True, False, True, False, False, False, False]
           and _sig.matches([b for b in tw if not b.get("maybe")], tw) and not _sig.matches([b for b in tw if b["name"] != "u"], tw))
    expect("arguments: what the type binds after the colon counts, also a premise and a bounded quantifier",
           got["T.a"].endswith("{R : Nat} (g : X → X) (hu : lev l 1 R) (e : Nat)t")
           and got["T.b"] == "(n : Nat)t [Inhabited Nat]t (n = n)t (m)t (m ∈ [n])t")
    expect("arguments: a premise in brackets that begins with a quantifier is a premise, not an argument named by it",
           got["T.p"] == "(D : Type)t (f : D → D)t ((∀ φ : D, ∃ k : Nat, f φ = φ))t (y : D)t")
    expect("arguments: `omit … in` leaves an instance out, and a closed namespace takes its variables along",
           got["T.c"] == "{X : Type}v (x : X)" and got["d"] == "(x : Nat) (h : x = x)")

# the case that made the rule: a hypothesis in a sentence before the theorem, and a function with two of its four arguments
import signature_gate as _gate                             # noqa: E402

_conc = {"tw": {"kind": "def", "id": "A:1:5", "binders": [{"name": n, "kind": "explicit", "type": "T", "from": "signature"} for n in "γuem"]},
         "centres": {"kind": "theorem", "id": "A:2:9", "binders": [
             {"name": "γ", "kind": "implicit", "type": "End X", "from": "signature"}, {"name": "u", "kind": "implicit", "type": "ℤ_[l]", "from": "signature"},
             {"name": "hγ", "kind": "explicit", "type": "Unip γ", "from": "signature"}]}}
_acc = {"declarations": {"tw": {"notation": {"macro": "tw", "slots": ["γ", "u", "e", "m"], "tex": "\\tau(#1,#2;#3,#4)", "symbol": "\\tau"}}, "centres": {}},
        "letters": {"γ": "\\gamma", "u": "u"}, "words": {"Unip": "unipotent"}, "lettered": [["Theorem A", "t:A"]]}
_tex = ("\\cs{tw}{Def.~\\ref{d:tau}} \\cs{centres}{Theorem A}\n\\begin{document}\n\\begin{definition}\\label{d:tau} For $\\gamma$, $u$, $h$, $m$ put "
        "$\\tw{\\gamma}{u}{h}{m}$.\\end{definition}\n%s\n\\statement{c}{\\label{t:A}\\textbf{Theorem A.} %s there are centres with "
        "$\\tw{\\gamma}{u}{h}{m}\\le 1$.}\n\\end{document}\n")
good = _gate.gate(_acc, _conc, _tex % ("", "If $\\gamma$ is unipotent,"))[0]
before = _gate.gate(_acc, _conc, _tex % ("In the next statement $\\gamma$ is unipotent.", "For this $\\gamma$ and $u$"))[0]
short = _gate.gate(_acc, _conc, (_tex % ("", "If $\\gamma$ is unipotent,")).replace("$\\tw{\\gamma}{u}{h}{m}\\le 1$", "$\\tau(h,m)\\le 1$"))[0]
expect("the gate: the statement that names its hypothesis and writes all four arguments passes", good == [])
expect("the gate: a hypothesis in a sentence before the theorem is a problem", len(before) == 1 and "hγ" in before[0] and "never in a sentence before it" in before[0])
expect("the gate: the function written with two of its four arguments is a problem", any("written by hand" in x for x in short))
_own = {"declarations": {"centres": {}}, "letters": {"u": "u"}, "lettered": [["Theorem A", "t:A"]]}
_table = {"notations": {"twLen": _acc["declarations"]["tw"]["notation"]}, "letters": {"γ": "\\gamma", "u": "w"}, "words": {"Unip": "unipotent"}}
_merged = _gate.with_shared(_own, _table, {"tw": "A.B.twLen", "centres": "A.B.exists_centres"})
expect("the gate: one table for all notes gives a note its notations, letters and words; what the note says for itself wins",
       _merged["declarations"]["tw"]["notation"]["macro"] == "tw" and _merged["letters"] == {"γ": "\\gamma", "u": "u"}
       and _gate.gate(_merged, _conc, _tex % ("", "If $\\gamma$ is unipotent,"))[0] == [] and "notation" not in _own["declarations"].get("tw", {}))
_tab2 = dict(_table, notations=dict(_table["notations"], Dinf={"macro": "Dinf", "slots": ["l", "N", "U"], "tex": "D_\\infty(#1,#2,#3)", "symbol": "D_\\infty"}))
_m2 = _gate.with_shared(_own, _tab2, {"tw": "A.B.twLen", "centres": "A.B.exists_centres"})
_use = (_tex % ("", "If $\\gamma$ is unipotent,")).replace("\\end{document}", "The module $\\Dinf{\\ell}{N}{U}$.\n\\end{document}")
expect("the gate: a notation of the shared table that the note uses without citing its definition is held to the rule too",
       _gate.gate(_m2, _conc, _use)[0] == [] and any("\\newcommand{\\Dinf}[3]" in m for m in _gate.gate(_m2, _conc, _use)[2])
       and any("Dinf (shared table): \\Dinf in line" in x for x in _gate.gate(_m2, _conc, _use.replace("\\Dinf{\\ell}{N}{U}", "\\Dinf{\\ell}{N}"))[0])
       and any("written by hand" in x for x in _gate.gate(_m2, _conc, _use.replace("\\end{document}", "$D_\\infty$\n\\end{document}"))[0])
       and _gate.broken_copies(_m2, _conc, _use) == (4, []))
_m3 = _gate.with_shared({"declarations": {}}, {"notations": {"centres": {"macro": "cen", "slots": ["x"], "tex": "c(#1)", "symbol": ["c(", "\\centre"]}}},
                        {"tw": "A.B.twLen", "centres": "A.B.centres"}, {"tw": "def", "centres": "theorem"})
expect("the gate: a shared notation is not given to a theorem that has the name of the definition; a notation may have several bare symbols",
       "notation" not in _m3["declarations"].get("centres", {}) and "centres" in _m3["shared"]
       and _gate.bare("a $\\centre$ b c(x)", _gate.symbols(_m3["shared"]["centres"])) == 2)
expect("the gate: it catches the copies of the good text that are broken on purpose", _gate.broken_copies(_acc, _conc, _tex % ("", "If $\\gamma$ is unipotent,")) == (2, []))

with tempfile.TemporaryDirectory() as tmp:
    ws = Path(tmp) / "ws"
    run(Path(tmp), "init", str(ws), "--artifact", str(ROOT / "examples" / "tiny-lean"), "--root", "Tiny.Main", "--name", "Tiny sums")
    version = run(ws, "--version").stdout.strip()
    cfg = json.loads((ws / "readback.json").read_text(encoding="utf-8"))
    expect("workspace records the installed Readback version",
           version == cfg["version"] and f"badge/version-{version}-" in (ROOT / "README.md").read_text(encoding="utf-8")
           and f'version: "{version}"' in (ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    c = json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))
    t = c["totals"]
    expect("census: 7 modules, 16 declarations, cone of 5, no sorry", (t["modules"], t["declarations"], t["modules_in_cone"], t["sorry"]) == (7, 16, 5, 0))
    u = json.loads((ws / "reading" / "units.proposal.json").read_text(encoding="utf-8"))
    expect("units: 5 proposed, the root last", len(u["units"]) == 5 and u["units"][-1]["title"] == "Tiny.Main")
    shutil.copytree(ROOT / "examples" / "tiny-sample" / "units" / "3", ws / "reading" / "units" / "3")
    run(ws, "check", "3")
    k = json.loads((ws / "reading" / "units" / "3" / "check.json").read_text(encoding="utf-8"))["counts"]
    expect("check: 2 proofs, 6 leaves, all steps quoting", (k["proofs"], k["leaves"], k["steps_quoting_their_lines"]) == (2, 6, k["steps"]))
    fields = ("typed_facts_in_source", "typed_steps", "step_references", "declaration_references")
    expect("check: both intermediate types, two local and two declaration references",
           tuple(k.get(f) for f in fields) == (2, 2, 2, 2))
    p = ws / "reading" / "units" / "3" / "proofs" / "aux_step.json"
    good = p.read_text(encoding="utf-8")
    p.write_text(good.replace("omega", "simp"), encoding="utf-8")
    run(ws, "check", "3", expect=1)                      # a quotation that is not the source must fail
    p.write_text(good, encoding="utf-8")
    p2 = ws / "reading" / "units" / "3" / "proofs" / "two_mul_sumTo_id.json"
    good2 = p2.read_text(encoding="utf-8")
    assert '"Tiny.aux_step"' in good2
    p2.write_text(good2.replace('"Tiny.aux_step"', '"1.1"'), encoding="utf-8")
    run(ws, "check", "3", expect=1)                      # a step may not use a fact of another branch
    p2.write_text(good2, encoding="utf-8")
    run(ws, "check", "3")
    body = ws / "body.md"
    body.write_text("**verified** · unit 3 passes `python3 tools/rb.py check 3`.\n", encoding="utf-8")
    run(ws, "mail", "--as", "astra", "send", "--type", "handoff", "--slug", "unit-3", "--subject", "Unit 3", "--body", str(body))
    r = run(ws, "mail", "--as", "fable", "inbox")
    expect("mailbox: the hand-off waits in the writer's inbox", "msg-0001-unit-3" in r.stdout)
    run(ws, "mail", "--as", "fable", "send", "--type", "result", "--re", "msg-0001", "--slug", "unit-3-checked", "--subject", "Checked", "--body", str(body))
    r = run(ws, "mail", "--as", "astra", "archive")
    expect("mailbox: the answered message is archived", "archived msg-0001-unit-3" in r.stdout)
    r = run(ws, "mail", "--as", "astra", "send", "--type", "request", "--slug", "question", "--subject", "A question", "--body", str(body))
    expect("mailbox: numbering goes on after an archived message", "msg-0002-question" in r.stdout)
    run(ws, "mail", "--as", "fable", "send", "--type", "result", "--re", "msg-0002", "--slug", "answer", "--subject", "An answer", "--body", str(body))
    run(ws, "mail", "--as", "astra", "send", "--type", "ack", "--re", "msg-0002", "--slug", "thanks", "--subject", "Thanks", "--body", str(body))
    run(ws, "mail", "--as", "fable", "archive")
    r = run(ws, "mail", "--as", "fable", "inbox")
    expect("mailbox: an answered message does not come back when its answer is archived", "msg-0002-question" not in r.stdout and "msg-0003-thanks" in r.stdout)
    run(ws, "mail", "--as", "fable", "send", "--type", "ack", "--re", "msg-0009", "--slug", "nothing", "--subject", "x", "--body", str(body), expect=1)
    r = run(ws, "mail", "--as", "fable", "send", "--type", "ack", "--slug", "nobody", "--subject", "x", expect=1)
    expect("mailbox: a missing body is refused in words, not with a traceback", "Traceback" not in r.stderr and "--body" in r.stderr)
    r = run(ws, "site")                                    # without a note: map, units, proofs, source
    site = ws / "site"
    made = json.loads((site / "site.json").read_text(encoding="utf-8"))["counts"]
    expect("site: a page for each of the 5 units, 2 structured proofs with their 8 steps, 7 source files",
           (made["unit_pages"], made["proof_pages"], made["steps"], made["source_pages"]) == (5, 2, 8, 7) and (site / "index.html").exists())
    pages = {f.name: f.read_text(encoding="utf-8") for f in site.glob("*.html")}
    expect("site: no page asks another host for anything", not any(re.search(r'(?:src|href)="(?:https?:)?//', t) for t in pages.values()))
    proof = next(t for n, t in pages.items() if n.startswith("proof-3-"))
    expect("site: a proof page shows its steps beside the numbered lines of the declaration", 'class="step"' in proof and 'data-lines="' in proof and 'class="ln" id="L' in proof)
    expect("site: an unread unit is shown as not read yet, with its declarations", "not read yet" in pages["unit-1.html"] and 'class="decl"' in pages["unit-1.html"])
    other = Path(tmp) / "elsewhere"
    other.mkdir()
    (other / "keep.txt").write_text("not a site\n", encoding="utf-8")
    run(ws, "site", "--out", str(other), expect=1)           # a directory that is not a site is never replaced
    expect("site: a directory that is not a site is left alone", (other / "keep.txt").exists())
    if shutil.which("latexmk") and shutil.which("lualatex"):
        shutil.copytree(ROOT / "examples" / "tiny-sample" / "notes" / "gauss", ws / "notes" / "gauss")
        for f in ("gauss.pdf", "reader.json", "concordance.json"):
            (ws / "notes" / "gauss" / f).unlink()
        r = run(ws, "note", "gauss")
        probs = json.loads((ws / "notes" / "gauss" / "problems.json").read_text(encoding="utf-8"))["problems"]
        expect("note: built, no problem reported, 6 declarations in the concordance", not probs and "concordance of 6" in r.stdout)
        # the signature rule: no argument of a defined function is dropped, no hypothesis stands outside its statement
        nd = ws / "notes" / "gauss"
        tex0, spec0 = (nd / "gauss.tex").read_text(encoding="utf-8"), (nd / "spec.json").read_text(encoding="utf-8")

        def broken(what, word, tex=None, spec=None):
            sp = json.loads(spec0)
            if spec:
                spec({e["key"]: e for e in sp["declarations"]})
            (nd / "spec.json").write_text(json.dumps(sp), encoding="utf-8")
            (nd / "gauss.tex").write_text(tex(tex0) if tex else tex0, encoding="utf-8")
            run(ws, "note", "gauss", expect=1)
            found = json.loads((nd / "problems.json").read_text(encoding="utf-8"))["problems"]
            expect(f"note: {what} is a problem", any(word in x for x in found))

        broken("a notation with an argument of the Lean definition dropped", "never changed",
               spec=lambda e: e["sumTo"]["notation"].update(slots=["f"], tex="S_{#1}"))
        broken("a notation that does not display one of its arguments", "does not display its argument #2",
               spec=lambda e: e["sumTo"]["notation"].update(tex="S_{#1}"))
        broken("a defined function written with fewer arguments than it has", "with 1 of its 2 arguments",
               tex=lambda t: t.replace("\\tri{n}=\\sumTo{f}{n+1}", "\\tri{n}=\\sumTo{f}"))
        broken("a defined function written by hand, past its notation", "written by hand",
               tex=lambda t: t.replace("The sum in Theorem~A is", "Here $S_f(n)$ is short for the sum; the sum in Theorem~A is"))
        broken("a definition with explicit arguments and no notation", "and no `notation`", spec=lambda e: e["tri"].pop("notation"))
        broken("an argument of a theorem that the note does not account for", "is not accounted for", spec=lambda e: e["auxStep"].pop("binders"))
        broken("a hypothesis whose words are not inside the statement", "neither in the statement", spec=lambda e: e["gauss"]["binders"].update(n="prime number"))
        broken("a declaration stated in running text", "not a statement of its own",
               tex=lambda t: t.replace("\\cs{tri}{Def.~\\ref{d:tri}}", "\\cs{tri}{§\\ref{s:setting}}"))
        # repairing an existing note: the accounts are prepared, a symbol is replaced without touching a definition
        sp = json.loads(spec0)
        for e in sp["declarations"]:
            e.pop("notation", None), e.pop("binders", None)
        (nd / "spec.json").write_text(json.dumps(sp), encoding="utf-8")
        (nd / "gauss.tex").write_text(tex0.replace("\\tri{n}", "T_n").replace("\\begin{document}", "\\newcommand{\\short}{T_n}\n\\begin{document}"),
                                      encoding="utf-8")
        r = run(ws, "note", "gauss", "--account", expect=1)
        sp = {e["key"]: e for e in json.loads((nd / "spec.json").read_text(encoding="utf-8"))["declarations"]}
        expect("repair: --account gives every definition its place for a notation, with Lean's explicit arguments as slots",
               sp["sumTo"]["notation"]["slots"] == ["f", "Nat"] and sp["tri"]["notation"]["slots"] == ["n"] and "TO DO:" in r.stdout)
        r = run(ws, "note", "gauss", "--rewrite", "T_n", "\\\\tri{n}")
        fixed = (nd / "gauss.tex").read_text(encoding="utf-8")
        expect("repair: --rewrite replaces the symbol in the text, leaves the line that defines a macro alone and keeps the old text",
               "\\newcommand{\\short}{T_n}" in fixed and fixed.count("T_n") == 1 and fixed.count("\\tri{n}") == tex0.count("\\tri{n}")
               and (nd / "gauss.tex.before").exists())
        (nd / "gauss.tex.before").unlink()
        # a variable may stand in `letters`; then the note builds, and the gate is tried on copies broken on purpose
        sp = json.loads(spec0)
        next(e for e in sp["declarations"] if e["key"] == "auxStep").pop("binders")
        sp["letters"] = {"k": "integer \\m{k\\ge0}"}
        (nd / "gauss.tex").write_text(tex0, encoding="utf-8")
        (nd / "spec.json").write_text(json.dumps(sp), encoding="utf-8")
        r = run(ws, "note", "gauss")
        expect("note: a variable accounted for by the note's letters; the gate catches all 4 copies broken on purpose", "caught all 4 copies" in r.stdout)
        stamp = (nd / "gauss.pdf").stat().st_mtime_ns
        r = run(ws, "note", "gauss", "--check")
        expect("note: --check reads the text alone and builds nothing", "checked and not built" in r.stdout and (nd / "gauss.pdf").stat().st_mtime_ns == stamp)
        (nd / "spec.json").write_text(spec0, encoding="utf-8")
        broken("a label after a heading, whose link would open the item before it", "share one destination",
               tex=lambda t: t.replace("\\leanline{\\lean{auxStep}}", "\\leanline{\\lean{auxStep}}\n\\subhead{An aside.}\\label{x:aside}", 1)
                              .replace("\\cs{tri}{Def.~\\ref{d:tri}}", "\\cs{tri}{§\\ref{x:aside}}"))
        (ws / "tools" / "repair" / "BRIEF.md").read_text(encoding="utf-8")       # the worker's brief travels with the workspace
        (nd / "gauss.tex").write_text(tex0, encoding="utf-8")
        (nd / "spec.json").write_text(spec0, encoding="utf-8")
        run(ws, "note", "gauss")
        r = run(ws, "status")
        expect("status: one unit has its note, four are not read yet", "1 note and structured proofs" in r.stdout and "4 not read yet" in r.stdout)
        rows = {l.split("|")[1].strip(): l for l in (ws / "STATUS.md").read_text(encoding="utf-8").split("\n") if l.startswith("| ") and l.split("|")[1].strip().isdigit()}
        expect("status: a definition cited by the note of another unit does not count as read", "| 0 of 3 |" in rows["1"] and "| 3 of 3 |" in rows["3"])
        run(ws, "book")
        expect("book: assembled", (ws / "book" / "book.pdf").exists())
        counts = (ws / "book" / "counts.tex").read_text(encoding="utf-8")
        expect("book: the counts of the workspace are there as macros for the summary",
               "\\newcommand{\\rbNotes}{1}" in counts and "\\newcommand{\\rbUnits}{5}" in counts and "\\newcommand{\\rbStructuredProofs}{2}" in counts)
        run(ws, "site")
        made = json.loads((ws / "site" / "site.json").read_text(encoding="utf-8"))["counts"]
        reader = (ws / "site" / "note-gauss.html").read_text(encoding="utf-8")
        expect("site: the note has a reader with a card for each of its 6 declarations", made["note_pages"] == 1 and reader.count('class="card"') == 6)
        if shutil.which("pdftocairo") and shutil.which("pdfinfo") and shutil.which("pdftotext"):
            n_pages = json.loads((ws / "notes" / "gauss" / "reader.json").read_text(encoding="utf-8"))["pages"]
            expect("site: the pages of the note stand beside the Lean text, every statement and every LEAN line marked on them",
                   made["pdf_pages"] == n_pages and made["statements_marked"] >= 1 and made["lean_lines_in_notes"] >= 1
                   and made["lean_lines_marked"] == made["lean_lines_in_notes"] and reader.count('class="mark band"') == made["lean_lines_marked"])
        else:
            print("SKIP marks on the pages of the note: poppler not found")
            skipped.append("the marks on a note's pages (no poppler)")
    else:
        print("SKIP note, status with a note, book: latexmk or lualatex not found")
        skipped.append("building a note, the state of a unit with a note, the book, a note's reader (no LaTeX)")
        run(ws, "status")
with tempfile.TemporaryDirectory() as tmp:               # an older workspace takes the tools of this skill
    ws = Path(tmp) / "ws"
    subprocess.run([sys.executable, str(RB), "init", str(ws), "--artifact", str(ROOT / "examples" / "tiny-lean"), "--root", "Tiny.Main"], capture_output=True, text=True)
    (ws / "tools" / "site_pages.py").unlink()
    (ws / ".gitignore").write_text("build/\n", encoding="utf-8")
    (ws / "tools" / "rb.py").write_text("# an older tool\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(RB), "upgrade"], cwd=ws, capture_output=True, text=True)
    expect("upgrade: the workspace gets the tools of this skill and says which files changed",
           r.returncode == 0 and "tools/rb.py" in r.stdout and "tools/site_pages.py" in r.stdout
           and (ws / "tools" / "rb.py").read_bytes() == RB.read_bytes()
           and "site/" in (ws / ".gitignore").read_text(encoding="utf-8").split("\n"))
    r = subprocess.run([sys.executable, str(ws / "tools" / "rb.py"), "upgrade"], cwd=ws, capture_output=True, text=True)
    expect("upgrade: the workspace's own copy refuses to upgrade from itself", r.returncode != 0 and "installed skill" in r.stderr)

with tempfile.TemporaryDirectory() as tmp:               # the ledger check, the quoted statement, waiting for mail, sources that change
    ws = Path(tmp) / "ws"
    art = Path(tmp) / "art"
    shutil.copytree(ROOT / "examples" / "tiny-lean", art)
    run(Path(tmp), "init", str(ws), "--artifact", str(art), "--root", "Tiny.Main")
    shutil.copytree(ROOT / "examples" / "tiny-sample" / "units" / "3", ws / "reading" / "units" / "3")
    L = json.loads((ws / "reading" / "units.proposal.json").read_text(encoding="utf-8"))
    led = ws / "reading" / "ledger" / "units.json"
    led.write_text(json.dumps(L), encoding="utf-8")
    r = run(ws, "ledger")
    expect("ledger: the proposal passes as a ledger, and its module names as titles are pointed out", "0 problems" in r.stdout and "titles are module names" in r.stdout)
    bad = json.loads(json.dumps(L))
    bad["units"][1]["members"].append(bad["units"][0]["members"][0])
    bad["units"][0]["proof_lines"] = 99
    bad["units"][2]["imports"] = bad["units"][2]["imports"] + ["77"]
    led.write_text(json.dumps(bad), encoding="utf-8")
    r = run(ws, "ledger", expect=1)
    expect("ledger: a declaration in two units, a wrong count of proof lines and an unknown unit are problems",
           "is a member of units" in r.stdout and "proof_lines is 99" in r.stdout and "unknown unit '77'" in r.stdout)
    led.write_text(json.dumps(L), encoding="utf-8")
    up = ws / "reading" / "units" / "3" / "unit.json"
    good0 = up.read_text(encoding="utf-8")
    unit = json.loads(good0)
    lines = (art / unit["members"][0]["file"]).read_text(encoding="utf-8").split("\n")
    c = json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))
    d = next(d for m in c["modules"] for d in m["declarations"] if d["id"] == unit["members"][0]["id"])
    unit["members"][0]["statement_lean"] = "\n".join(lines[d["statement_lines"][0] - 1:d["statement_lines"][1]])
    up.write_text(json.dumps(unit), encoding="utf-8")
    run(ws, "check", "3")
    unit["members"][0]["statement_lean"] = "theorem something_else : True"
    up.write_text(json.dumps(unit), encoding="utf-8")
    r = run(ws, "check", "3", expect=1)
    expect("check: a quoted statement that is not the source's is a problem", "statement_lean is not the text" in r.stdout)
    del unit["members"][0]["statement_lean"]
    up.write_text(json.dumps(unit), encoding="utf-8")
    r = run(ws, "mail", "--as", "fable", "wait", "1", "--timeout", "1", expect=2)
    expect("mailbox: waiting ends with a word when nothing arrives", "no new message" in r.stdout)
    body = ws / "body.md"
    body.write_text("**verified** · a hand-off.\n", encoding="utf-8")
    run(ws, "mail", "--as", "astra", "send", "--type", "handoff", "--slug", "unit-3", "--subject", "Unit 3", "--body", str(body))
    r = run(ws, "mail", "--as", "fable", "wait", "1", "--timeout", "5")
    expect("mailbox: waiting ends at once when a message is there, and names it", "PEER MESSAGE: msg-0001-unit-3" in r.stdout)
    w = subprocess.Popen([sys.executable, str(ws / "tools" / "rb.py"), "mail", "--as", "fable", "watch", "1", "--skip-present"], cwd=ws,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(50):
        if (ws / "exchange" / ".watching-fable").exists():
            break
        time.sleep(0.1)
    r = run(ws, "mail", "--as", "fable", "wait", "1", "--timeout", "1", expect=1)
    expect("mailbox: a second watch for the same name in the same workspace is refused", "already running" in r.stderr)
    r = run(ws, "mail", "--as", "fable", "stop")
    w.wait(timeout=10)
    expect("mailbox: stop ends this workspace's watch by its process number and removes its record",
           f"process {w.pid}" in r.stdout and w.returncode is not None and not (ws / "exchange" / ".watching-fable").exists())
    r = run(ws, "mail", "--as", "fable", "stop")
    expect("mailbox: stop with nothing running says so", "no watch or wait" in r.stdout)
    r = run(ws, "status")
    expect("status: silent about the sources while they are those of the census", "WARNING" not in r.stdout)
    f = art / "Tiny" / "Gauss.lean"
    f.write_text(f.read_text(encoding="utf-8") + "\n-- a line added after the census\n", encoding="utf-8")
    r = run(ws, "status")
    expect("status: says so when a Lean file changed after the census", "WARNING" in r.stdout and "1 files changed" in r.stdout and "Tiny/Gauss.lean" in r.stdout
           and "WARNING" in (ws / "STATUS.md").read_text(encoding="utf-8"))
    r = run(ws, "site", expect=1)
    expect("site: not built on sources that changed after the census", "not those of the census" in r.stderr)
    run(ws, "census")
    r = run(ws, "status")
    expect("status: quiet again after a new census", "WARNING" not in r.stdout)
    expect("workspace: the contracts are in the workspace, where the reader can find them", (ws / "tools" / "references" / "contracts.md").exists())
    # the state of a unit follows its check and its sources
    run(ws, "check", "3")
    row3 = lambda: next(l for l in (ws / "STATUS.md").read_text(encoding="utf-8").split("\n") if l.startswith("| 3 |"))
    run(ws, "status")
    expect("status: a unit whose dossier passes the check and has no note is 'structured proofs, checked'", "structured proofs, checked" in row3())
    (ws / "reading" / "units" / "3" / "check.json").rename(ws / "reading" / "units" / "3" / "check.kept")
    run(ws, "status")
    expect("status: without a check record the unit is only a dossier, not checked yet", "dossier: not checked yet" in row3())
    (ws / "reading" / "units" / "3" / "check.kept").rename(ws / "reading" / "units" / "3" / "check.json")
    before = f.read_text(encoding="utf-8")
    line = next(l for l in before.split("\n") if "omega" in l or "simp" in l or "rw" in l)
    f.write_text(before.replace(line, line + "  -- changed", 1), encoding="utf-8")
    r = run(ws, "census")
    changes = json.loads((ws / "reading" / "census-changes.json").read_text(encoding="utf-8"))
    expect("census: what changed since the last census is listed by name", "1 declarations changed" in r.stdout and len(changed := changes["changed"]) == 1)
    run(ws, "status")
    expect("status: a unit whose source changed under its dossier falls back, and says why", "dossier: the source of 1 members changed since the dossier" in row3())
    f.write_text(before, encoding="utf-8")
    run(ws, "census")
    run(ws, "status")
    expect("status: with the source restored the unit is checked again", "structured proofs, checked" in row3())
    pfile = next((ws / "reading" / "units" / "3" / "proofs").glob("*.json"))
    kept = pfile.read_text(encoding="utf-8")
    pfile.write_text(kept.replace('"claim": "', '"claim": "EDITED ', 1), encoding="utf-8")
    run(ws, "status")
    expect("status: a dossier edited after its check is not 'checked' any more", "dossier: the dossier was edited after its check" in row3())
    pfile.write_text(kept, encoding="utf-8")
    (ws / "reading" / "units" / "2").mkdir(parents=True, exist_ok=True)
    (ws / "reading" / "units" / "2" / "check.json").write_text('{"problems": [], "counts": {"proofs": 99}}', encoding="utf-8")
    run(ws, "status")
    row2 = next(l for l in (ws / "STATUS.md").read_text(encoding="utf-8").split("\n") if l.startswith("| 2 |"))
    expect("status: a check record without a dossier counts for nothing", "not read yet" in row2)
    shutil.rmtree(ws / "reading" / "units" / "2")
    up.write_text("{not json", encoding="utf-8")
    r = run(ws, "check", "3", expect=1)
    expect("check: a dossier that is not JSON is refused in words", "Traceback" not in r.stderr and "not valid JSON" in r.stderr)
    up.write_text(json.dumps(dict(json.loads(good0), members=7, imports=7)), encoding="utf-8")
    r = run(ws, "check", "3", expect=1)
    expect("check: fields of the wrong shape are problems, not a crash", "Traceback" not in r.stderr and "`members` must be a list" in r.stdout)
    up.write_text(good0, encoding="utf-8")
    run(ws, "check", "3")
    # the root
    r = run(ws, "root")
    expect("root: shown with the modules that no other imports", "root module: Tiny.Main" in r.stdout and "Tiny.Scratch" in r.stdout)
    r = run(ws, "root", "Tiny.Gauss")
    expect("root: set, with census, proposal and status made again", "Tiny.Main -> Tiny.Gauss" in r.stdout and json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))["root"] == "Tiny.Gauss")
    run(ws, "root", "Tiny.Nowhere", expect=1)
    run(ws, "root", "Tiny.Main")
    led.write_text(json.dumps(json.loads((ws / "reading" / "units.proposal.json").read_text(encoding="utf-8"))), encoding="utf-8")
    # what the contract requires of a dossier
    good = up.read_text(encoding="utf-8")
    for what, edit, word in (("a member without its statement in words", lambda u: u["members"][0].pop("text"), "no statement in words"),
                             ("a member without a hash", lambda u: u["members"][0].pop("sha256"), "no sha256"),
                             ("an import that is not quoted", lambda u: u["imports"][0].pop("lean"), "not quoted"),
                             ("a dossier without a summary", lambda u: u.pop("summary"), "has no summary"),
                             ("a dossier that names another unit", lambda u: u.update(unit="99"), "its folder is unit 3"),
                             ("a triage word that does not exist", lambda u: u["members"][0].update(triage="hard"), "is none of"),
                             ("a member whose arguments are not accounted for", lambda u: u["members"][0].pop("binders"), "no account of its arguments"),
                             ("a member with an argument left out", lambda u: u["members"][0].update(binders=[]), "are not the arguments of the declaration"),
                             ("an argument without its reading in words", lambda u: u["members"][0]["binders"][0].pop("reads"), "its reading in words"),
                             ("an argument of the declaration left out under Lean's name",
                              lambda u: u["members"][0].update(binders=[], binders_basis="lean", binders_lean="@Tiny.aux_step : True"), "leave out an argument")):
        u = json.loads(good)
        edit(u)
        up.write_text(json.dumps(u), encoding="utf-8")
        r = run(ws, "check", "3", expect=1)
        expect(f"check: {what} is a problem", word in r.stdout)
    u = json.loads(good)                                   # Lean's own signature may hold more than the text shows, never less
    u["members"][0].update(binders=[{"name": "α", "kind": "implicit", "reads": "a type that Lean binds by itself"}] + u["members"][0]["binders"],
                           binders_basis="lean", binders_lean="@Tiny.aux_step : {α : Type} → (k : Nat) → …")
    up.write_text(json.dumps(u), encoding="utf-8")
    r = run(ws, "check", "3")
    expect("check: arguments taken from Lean's own signature are accepted when they hold those of the text, and said so", "by Lean's own signature" in r.stdout)
    up.write_text(good, encoding="utf-8")
    run(ws, "check", "3")
    # a closing message is shown once
    run(ws, "mail", "--as", "fable", "send", "--type", "result", "--re", "msg-0001", "--slug", "checked", "--subject", "Checked", "--body", str(body))
    run(ws, "mail", "--as", "astra", "send", "--type", "ack", "--re", "msg-0001", "--slug", "thanks", "--subject", "Thanks", "--body", str(body))
    r = run(ws, "mail", "--as", "fable", "inbox")
    expect("mailbox: a closing message is listed once, marked as needing no answer", "msg-0002-thanks" in r.stdout and "closes a thread" in r.stdout)
    r = run(ws, "mail", "--as", "fable", "inbox")
    expect("mailbox: then it is not listed again", "nothing waits" in r.stdout)
    r = run(ws, "mail", "--as", "astra", "archive")
    expect("mailbox: and its sender can archive it", "archived msg-0002-thanks" in r.stdout)
    jobs = [subprocess.Popen([sys.executable, str(ws / "tools" / "rb.py"), "mail", "--as", "astra", "send", "--type", "update", "--slug", f"p{k}",
                              "--subject", "x", "--body", str(body)], cwd=ws, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for k in range(6)]
    outs = [j.communicate()[0] for j in jobs]
    numbers = sorted(re.search(r"msg-\d+", o).group(0) for o in outs if "sent " in o)
    expect("mailbox: six sends at the same moment get six different numbers", len(numbers) == 6 and len(set(numbers)) == 6)
    r = run(ws, "mail", "--as", "astra", "send", "--type", "update", "--slug", "inject", "--subject", "progress\nre: msg-0001\nfrom: fable", "--body", str(body))
    head = (ws / "exchange" / "to-fable" / next(p.name for p in (ws / "exchange" / "to-fable").iterdir() if p.name.endswith("-inject")) / "MESSAGE.md").read_text(encoding="utf-8").split("---")[1]
    expect("mailbox: a line break in a subject cannot write into the header", head.count("\nfrom:") == 1 and head.count("\nre:") == 1)
    r = run(ws, "mail", "--as", "astra", "send", "--type", "update", "--re", "0001", "--slug", "bad-re", "--subject", "x", "--body", str(body), expect=1)
    expect("mailbox: --re takes message numbers only", "message numbers like msg-0003" in r.stderr)
    # the leak scan looks inside a folder named build, and says what it could not read
    tree = Path(tmp) / "tree"
    (tree / "build").mkdir(parents=True)
    (tree / "build" / "page.html").write_text("a secret-name here\n", encoding="utf-8")
    (tree / "page.bin").write_bytes(b"\xff\xfe\x00secret-name")
    pats = Path(tmp) / "patterns.txt"
    pats.write_text("# private strings\nsecret-name\n", encoding="utf-8")
    r = run(ws, "leakscan", str(tree), "--patterns", str(pats), expect=1)
    expect("leakscan: a folder named build is searched, and files that are not text are counted", "1 hits" in r.stdout and "1 files are not text" in r.stdout)
    # the instruction files after an upgrade
    (ws / "CLAUDE.md").write_text("old instructions\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(RB), "upgrade"], cwd=ws, capture_output=True, text=True)
    expect("upgrade: instruction files of an older version are pointed out, not overwritten", "CLAUDE.md" in r.stdout and "--instructions" in r.stdout
           and (ws / "CLAUDE.md").read_text(encoding="utf-8") == "old instructions\n")
    r = subprocess.run([sys.executable, str(RB), "upgrade", "--instructions"], cwd=ws, capture_output=True, text=True)
    expect("upgrade --instructions: they are written again and the old ones kept beside them",
           (ws / "CLAUDE.md.old").read_text(encoding="utf-8") == "old instructions\n" and "Readback" in (ws / "CLAUDE.md").read_text(encoding="utf-8"))
    # a note that is still the template
    run(ws, "note", "odd", "--new", "The odd numbers", "--unit", "4")
    r = run(ws, "note", "odd", expect=1)
    expect("note: the untouched template does not pass: its unwritten places are counted", "places of the template are not written yet" in r.stdout)
    run(ws, "status")
    row4 = next(l for l in (ws / "STATUS.md").read_text(encoding="utf-8").split("\n") if l.startswith("| 4 |"))
    expect("status: a unit with only such a note is not read", "not read yet" in row4)
    r = run(ws, "note", "ghost", "--new", "No such unit", "--unit", "99", expect=1)
    expect("note: a note for a unit that does not exist leaves nothing behind", not (ws / "notes" / "ghost").exists())
    run(ws, "site")
    expect("site: it says when no licence came with the Lean sources", "No licence or notice file was found" in (ws / "site" / "index.html").read_text(encoding="utf-8"))
    # what does not pass the check is not shown, and nothing from a dossier reaches a page as markup
    pfile.write_text(kept.replace('"lines": [', '"lines": ["\\"><script>alert(1)</script>", ', 1), encoding="utf-8")
    run(ws, "check", "3", expect=1)
    run(ws, "site")
    pages = "".join(f.read_text(encoding="utf-8") for f in (ws / "site").glob("*.html"))
    expect("site: a dossier that fails its check is not shown, and its text reaches no page", "<script>alert(1)" not in pages
           and "does not pass the check" in (ws / "site" / "unit-3.html").read_text(encoding="utf-8") and not list((ws / "site").glob("proof-3-*")))
    pfile.write_text(kept, encoding="utf-8")
    u = json.loads(good0)
    u["summary"] = "A <b>bold</b> claim & more"
    up.write_text(json.dumps(u), encoding="utf-8")
    run(ws, "check", "3")
    run(ws, "site")
    expect("site: text of a checked dossier is shown as text", "A &lt;b&gt;bold&lt;/b&gt; claim &amp; more" in (ws / "site" / "unit-3.html").read_text(encoding="utf-8"))
    up.write_text(good0, encoding="utf-8")
    run(ws, "check", "3")
    (ws / "site" / "site.json").unlink()
    r = run(ws, "site", expect=1)
    expect("site: a folder without this command's mark is not replaced", "not a site made by this command" in r.stderr and (ws / "site" / "index.html").exists())
    shutil.rmtree(ws / "site")

with tempfile.TemporaryDirectory() as tmp:               # a short name that also exists in a module this one does not import
    art = Path(tmp) / "art"
    art.mkdir()
    (art / "A.lean").write_text("def helper : Nat := 1\n", encoding="utf-8")
    (art / "B.lean").write_text("def helper : Nat := 2\n\ntheorem b_two : helper = 2 := rfl\n", encoding="utf-8")
    (art / "C.lean").write_text("import A\n\ntheorem c_one : helper = 1 := rfl\n", encoding="utf-8")
    ws = Path(tmp) / "ws"
    run(Path(tmp), "init", str(ws), "--artifact", str(art), "--root", "C")
    c = json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))
    use = {d["name"]: d["uses"] for m in c["modules"] for d in m["declarations"]}
    expect("census: a name means a declaration of the same module or of an imported one, not of a module out of sight",
           use["b_two"] == ["B:1:5"] and use["c_one"] == ["A:1:5"])
    expect("census: the artifact has one digest", len(c["artifact"]["digest"]) == 64)

with tempfile.TemporaryDirectory() as tmp:               # one command per agent: finds or makes the workspace, shows the client's command
    def start(where, *args):
        return subprocess.run([sys.executable, str(RB), "start", *args, "--print"], cwd=where, capture_output=True, text=True)
    proj = Path(tmp) / "gauss"
    (proj / "src" / "Sum").mkdir(parents=True)
    (proj / "src" / "Sum" / "Defs.lean").write_text("def two : Nat := 2\n", encoding="utf-8")
    (proj / "src" / "Sum" / "Main.lean").write_text("import Sum.Defs\n\ntheorem two_eq : two = 2 := rfl\n", encoding="utf-8")
    (proj / "src" / "Sum.lean").write_text("import Sum.Main\n", encoding="utf-8")
    r = start(proj, "writer")
    cfg = json.loads((proj / "ws" / "readback.json").read_text(encoding="utf-8"))
    expect("start: the writer's command makes the workspace beside src and finds the root through a file of imports",
           r.returncode == 0 and cfg["artifact"]["root_module"] == "Sum.Main" and cfg["name"] == "gauss")
    expect("start: Claude Code is given its model, its effort and a first prompt that names the artifact",
           "claude --effort xhigh" in r.stdout and "--model" not in r.stdout and 'Lean artifact "gauss"' in r.stdout and "a first session" in r.stdout)
    r = start(proj / "ws" / "notes", "reader")
    expect("start: the reader's command finds the same workspace from inside it and gives Codex its model and effort",
           r.returncode == 0 and "codex -c 'model_reasoning_effort=\"max\"'" in r.stdout and f"-C {(proj / 'ws').resolve()}" in r.stdout
           and "your name is astra" in r.stdout)
    cfg["agents"]["writer"]["effort"] = "high"
    (proj / "ws" / "readback.json").write_text(json.dumps(cfg), encoding="utf-8")
    (proj / "ws" / "exchange" / "ledger.jsonl").write_text('{"id": "msg-0001"}\n', encoding="utf-8")
    r = start(proj, "writer")
    expect("start: the workspace's own effort is used, and a workspace with messages gets the prompt that continues",
           "--effort high" in r.stdout and "Continue in this Readback workspace" in r.stdout and "a session that continues" in r.stdout)
    r = start(proj, "writer", "--model", "opus", "--effort", "max")
    expect("start: a model and an effort given on the command line win for that session", "claude --model opus --effort max" in r.stdout)
    mine = Path(tmp) / "agents.json"
    mine.write_text(json.dumps({"writer": {"model": "my-writer-model"}, "reader": {"model": "my-reader-model", "effort": "high"}}), encoding="utf-8")
    other = Path(tmp) / "mine"
    (other / "src").mkdir(parents=True)
    (other / "src" / "Main.lean").write_text("theorem t : 1 = 1 := rfl\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(RB), "start", "writer", "--print"], cwd=other, capture_output=True, text=True,
                       env={**os.environ, "READBACK_CONFIG": str(mine)})
    got = json.loads((other / "ws" / "readback.json").read_text(encoding="utf-8"))["agents"]
    expect("start: the user's own defaults file sets the models and efforts recorded in a new workspace",
           r.returncode == 0 and "claude --model my-writer-model --effort xhigh" in r.stdout
           and got["reader"]["model"] == "my-reader-model" and got["reader"]["effort"] == "high")
    shutil.copytree(proj / "ws", proj / "ws-other")
    r = start(proj, "reader")
    expect("start: a second workspace in the folder is named, and the one called ws is taken", "ws-other" in r.stdout and f"-C {(proj / 'ws').resolve()}" in r.stdout)
    r = start(Path(tmp), "reader")                           # a folder that only contains a project further down
    expect("start: a folder with nothing to start from is refused in words, and nothing is made",
           r.returncode != 0 and "no Lean files" in r.stderr and "Traceback" not in r.stderr and not Path(str(Path(tmp).resolve()) + "-readback").exists())
    lone = Path(tmp) / "lone"
    shutil.copytree(ROOT / "examples" / "tiny-lean", lone)
    r = start(lone, "writer", "--root", "Tiny.Main")
    expect("start: a Lean project given directly gets its workspace beside it", r.returncode == 0 and (Path(tmp) / "lone-readback" / "readback.json").exists())
    r = start(lone, "reader")
    expect("start: the second agent, started in the same project, finds that workspace", r.returncode == 0 and f"-C {(Path(tmp) / 'lone-readback').resolve()}" in r.stdout)
    r = start(proj / "src" / "Sum", "reader")
    expect("start: with two workspaces on the same sources it asks which, and makes nothing", r.returncode != 0 and "ws-other" in r.stderr
           and not list((proj / "src").rglob("readback.json")))
    shutil.rmtree(proj / "ws-other")
    r = start(proj / "src" / "Sum", "reader")
    expect("start: from inside the sources the workspace beside them is found, and none is made there",
           r.returncode == 0 and f"-C {(proj / 'ws').resolve()}" in r.stdout and not list((proj / "src").rglob("readback.json")))
    r = subprocess.run([sys.executable, str(RB), "init", str(lone / "inside"), "--artifact", str(lone)], capture_output=True, text=True)
    expect("init: a workspace inside the artifact is refused", r.returncode != 0 and "inside the artifact" in r.stderr and not (lone / "inside").exists())
    full = Path(tmp) / "full"
    full.mkdir()
    (full / "CLAUDE.md").write_text("mine\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(RB), "init", str(full), "--artifact", str(lone)], capture_output=True, text=True)
    expect("init: a folder that holds files is not overwritten", r.returncode != 0 and (full / "CLAUDE.md").read_text(encoding="utf-8") == "mine\n")
    two = Path(tmp) / "two"
    shutil.copytree(ROOT / "examples" / "tiny-lean", two / "src")
    r = start(two, "writer")
    expect("start: with two candidates no root is guessed, and the writer is told to settle it first",
           json.loads((two / "ws" / "readback.json").read_text(encoding="utf-8"))["artifact"]["root_module"] is None
           and "Tiny.Main, Tiny.Scratch" in r.stdout and "propose one and settle it with me" in r.stdout)

with tempfile.TemporaryDirectory() as tmp:               # a module whose name needs guillemets in an import
    art = Path(tmp) / "art"
    (art / "Lib").mkdir(parents=True)
    (art / "Lib" / "2d.lean").write_text("def two : Nat := 2\n", encoding="utf-8")
    (art / "Main.lean").write_text("import Lib.«2d»\n\ntheorem two_eq : two = 2 := rfl\n", encoding="utf-8")
    ws = Path(tmp) / "ws"
    run(Path(tmp), "init", str(ws), "--artifact", str(art), "--root", "Main")
    c = json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))
    expect("census: an import written with guillemets reaches its file", sorted(c["cone"]) == ["Lib.2d", "Main"])

with tempfile.TemporaryDirectory() as tmp:               # declarations written indented inside `mutual … end`
    art = Path(tmp) / "art"
    art.mkdir()
    (art / "M.lean").write_text("mutual\n\n  /-- even -/\n  def isEven : Nat → Bool\n    | 0 => true\n    | n + 1 => isOdd n\n\n"
                                "  def isOdd : Nat → Bool\n    | 0 => false\n    | n + 1 => isEven n\n\nend\n\n"
                                "theorem isEven_zero : isEven 0 = true := rfl\n", encoding="utf-8")
    ws = Path(tmp) / "ws"
    run(Path(tmp), "init", str(ws), "--artifact", str(art), "--root", "M")
    ds = json.loads((ws / "reading" / "census.json").read_text(encoding="utf-8"))["modules"][0]["declarations"]
    expect("census: the two definitions of a mutual block and the theorem after it are read",
           [(d["name"], d["lines"]) for d in ds] == [("isEven", [4, 6]), ("isOdd", [8, 10]), ("isEven_zero", [14, 14])])
print("\nselftest:", ("all stages pass" if not skipped else "every stage that ran passes; NOT TESTED on this machine: " + "; ".join(skipped))
      if not fails else f"{len(fails)} failures")
sys.exit(1 if fails else 0)
