"""Exercise the installed workspace tool, including invalid dossiers, using only repository fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "skills/readback/scripts"
sys.path.insert(0, str(TOOLS))
from source_ranges import SourceFile, delimiter

SAMPLE = ROOT / "examples/tiny-sample/units/3"


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def load(path):
    return json.loads(path.read_bytes())


class Workspace(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.art = self.tmp / "artifact"
        self.ws = self.tmp / "workspace"
        shutil.copytree(ROOT / "examples/tiny-lean", self.art,
                        ignore=shutil.ignore_patterns(".lake", "lake-manifest.json"))
        self.rb = self.ws / "tools/rb.py"

    def cli(self, *args, expect=0):
        prog = self.rb if self.rb.exists() else TOOLS / "rb.py"
        r = subprocess.run([sys.executable, "-B", str(prog), *args],
                           cwd=self.ws if self.ws.exists() else self.tmp, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, expect, r.stdout + r.stderr)
        return r.stdout

    def sample(self):
        self.cli("init", str(self.ws), "--artifact", str(self.art), "--root", "Tiny.Main")
        self.unit = self.ws / "reading/units/3"
        shutil.copytree(SAMPLE, self.unit)
        self.aux = self.unit / "proofs/aux_step.json"
        self.gauss = self.unit / "proofs/two_mul_sumTo_id.json"

    def check(self, error=None, *args):
        self.cli("check", self.unit.name, *args, expect=int(error is not None))
        report = load(self.unit / "check.json")
        if error:
            self.assertIn(error, "\n".join(report["problems"]))
        else:
            self.assertEqual([], report["problems"])
        return report

    def fixture(self, raw):
        # These single-file fixtures use only the pinned Lean toolchain.
        self.art = self.tmp / "standalone"
        self.art.mkdir()
        shutil.copyfile(ROOT / "examples/tiny-lean/lean-toolchain", self.art / "lean-toolchain")
        self.file = self.art / "Example.lean"
        self.file.write_bytes(raw)
        self.cli("init", str(self.ws), "--artifact", str(self.art), "--root", "Example")
        census = load(self.ws / "reading/census.json")
        decl = next(m for m in census["modules"] if m["file"] == "Example.lean")["declarations"][0]
        self.unit = self.ws / "reading/units/fixture"
        (self.unit / "proofs").mkdir(parents=True)
        self.pf = self.unit / "proofs/example.json"
        self.mid = decl["id"]
        self.src = SourceFile(raw)
        dump(self.unit / "unit.json", {"schema": "readback/unit/1", "unit": "fixture", "title": "A fixture", "summary": "One declaration.",
                                       "members": [{**decl, "file": "Example.lean", "text": "The proposition holds.",
                                                    "binders": [dict(b, reads="an argument") for b in decl["binders"] or []],
                                                    "file_sha256": hashlib.sha256(raw).hexdigest()}]})
        return decl

    def step(self, name, lines, **fields):
        a, b = self.src.line_range(lines)
        if "span" in fields:
            a, b = self.src.offsets(fields["span"])
        return {"id": name, "kind": "fact", "claim": "The proposition holds.", "lines": lines,
                "lean": self.src.text[a:b], **fields}

    def proof(self, *steps, **fields):
        dump(self.pf, {"declaration": self.mid, "steps": steps, **fields})


class DossierTests(Workspace):
    def test_unbuilt_lake_project_is_left_untouched(self):
        self.sample()

        def snapshot():
            return {p.relative_to(self.art): p.read_bytes() if p.is_file() else None
                    for p in self.art.rglob("*")}

        # A pristine package, followed by a checkout with a committed manifest
        # and an uncompiled Lean lakefile. Both must fail before Lake starts.
        for missing in ("lake-manifest.json", ".lake/"):
            with self.subTest(missing=missing):
                if missing == ".lake/":
                    (self.art / "lakefile.toml").unlink()
                    (self.art / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage tiny\n")
                    (self.art / "lake-manifest.json").write_text('{"version":"1.1.0","packages":[]}\n')
                before = snapshot()
                self.check()                               # a passing check without Lean
                record = (self.unit / "check.json").read_bytes()
                for _ in range(2):
                    # Lean was not there to ask: that says nothing about the dossier. Exit 2, and the
                    # record of the last real check stays as it is.
                    out = self.cli("check", self.unit.name, "--lean-ranges", expect=2)
                    self.assertIn("build the artifact first", out)
                    self.assertIn(missing, out)
                    self.assertEqual(snapshot(), before)
                    self.assertEqual((self.unit / "check.json").read_bytes(), record)
                self.check()

    def test_tree_and_scope(self):
        self.sample()
        base = load(self.gauss)
        cases = [
            ("cyclic parent", lambda s: s[0].update(parent="1.2")),
            ("unknown parent", lambda s: s[1].update(parent="8")),
            ("duplicate step id", lambda s: s[2].update(id="1.1")),
            ("outside parent", lambda s: s[4].update(parent="1.1")),
            ("head outside", lambda s: s[2].update(head_lines=[14, 14])),
            ("distinct case child", lambda s: s[2].update(kind="setup")),
            ("not in scope", lambda s: s[4].update(uses=[{"step": "1.1"}])),
            ("not in scope", lambda s: s[0].update(uses=[{"step": "1.2.2"}])),
            ("not in scope", lambda s: s[2].update(uses=[{"step": "1.2"}])),
            ("unknown or ambiguous declaration", lambda s: s[4].update(uses=[{"decl": "Tiny.typo"}])),
            ("malformed reference", lambda s: s[4].update(uses=[{"decl": "x", "step": "1"}])),
            ("missing claim", lambda s: s[4].update(claim="  ")),
        ]
        for error, mutate in cases:
            with self.subTest(error=error):
                p = copy.deepcopy(base)
                mutate(p["steps"])
                dump(self.gauss, p)
                self.check(error)
        base["steps"][-1]["uses"] = [{"decl": "Tiny.Gauss:5:17"}, {"decl": "Tiny.Basic:5:9"}]
        dump(self.gauss, base)
        r = self.check()
        self.assertEqual(r["counts"]["declaration_references"], 3)

    def test_ownership_and_types(self):
        self.sample()
        base = load(self.aux)
        p = copy.deepcopy(base)
        p["steps"][0]["typed_fact"] = "(k + 1)"
        dump(self.aux, p)
        self.check("complete source type")
        p = copy.deepcopy(base)
        a, b, c = p["steps"]
        a.update(lines=[6, 9], lean=a["lean"] + "\n" + b["lean"])
        c.pop("uses")
        p["steps"].remove(b)
        dump(self.aux, p)
        self.check("each written intermediate type")
        p = copy.deepcopy(base)
        p["intro_lines"] = [[6, 7]]
        dump(self.aux, p)
        self.check("multiply owned")
        p["intro_lines"] = [[0, 7]]
        dump(self.aux, p)
        self.check("outside the file")
        p = copy.deepcopy(base)
        p["steps"][-1].update(lines=[10, 10], lean="  rw [h1, h2]")
        dump(self.aux, p)
        self.check("unowned proof text")
        shutil.copy2(self.aux, self.unit / "proofs/duplicate.json")
        self.check("already treated")

    def test_import_and_edition(self):
        self.sample()
        path = self.unit / "unit.json"
        unit = load(path)
        for update, error in [
            ({"name": "Tiny.tri"}, "does not resolve"),
            ({"lines": [0, 5]}, "outside the file"),
            ({"lean": " " + unit["imports"][0]["lean"]}, "quotation differs"),
            ({"file": "../Example.lean"}, "artifact"),
        ]:
            with self.subTest(change=update):
                u = copy.deepcopy(unit)
                u["imports"][0].update(update)
                dump(path, u)
                self.check(error)
        unit["members"][0]["file_sha256"] = "0" * 64
        dump(path, unit)
        self.check("file hash differs")

    def test_crlf_unicode_source_ranges(self):
        raw = ('theorem δοκιμή (s : String := ":=") : True := by\r\n'
               '  /- have bad : False := by /- show False -/ -/\r\n'
               '  have α : True ∧\r\n'
               '      True := ⟨trivial, trivial⟩  \r\n'
               '  exact α.1').encode("utf-8")
        d = self.fixture(raw)
        self.assertEqual(d["value_col"], raw.decode().splitlines()[0].rindex(":=") + 3)
        h = self.step("a", [3, 4], span=[3, 3, 4, len(self.src.text.splitlines()[3]) + 1],
                      typed_fact="True ∧\r\n      True")
        tail = self.step("b", [5, 5], uses=[{"step": "a"}])
        self.proof(h, tail)
        report = self.check()
        self.assertEqual(report["proof_checks"][0]["steps"][0]["type_source"]["span"], [3, 12, 4, 11])
        self.proof({**h, "lean": h["lean"].replace("\r\n", "\n")}, tail)
        self.check("quotation differs")
        self.proof({**h, "lean": h["lean"].rstrip()}, tail)
        self.check("quotation differs")
        self.proof({**h, "span": [3, 3, 4, 999]}, tail)
        self.check("column outside")
        self.proof(h, tail)
        u = load(self.unit / "unit.json")
        text = self.src.text
        stmt_stop = text.index("True := by") + 4
        value = text.index("by\r\n")
        u["members"][0]["source_ranges"] = {"statement": self.src.receipt(0, stmt_stop),
                                            "value": self.src.receipt(value, len(text))}
        dump(self.unit / "unit.json", u)
        self.assertEqual(self.check()["sources"][self.mid]["basis"], "recorded-source-ranges")
        u["members"][0]["source_ranges"]["value"]["span"][1] += 1
        dump(self.unit / "unit.json", u)
        self.check("range hash differs")

    def test_inline_proof_and_lexical_noise(self):
        raw = ('theorem cité (s : String := "show /- :=") : True := by have h : True := trivial; exact h\n'
               '/- outer /- inner -/\ntheorem fictitious : False := by sorry\n-/\n').encode()
        self.fixture(raw)
        a = self.src.text.index("have h")
        b = self.src.text.index("exact h")
        end = self.src.text.index("\n")
        h = self.step("a", [1, 1], span=self.src.coordinates(self.src.text.index("by have"), b),
                      typed_fact="True")
        tail = self.step("b", [1, 1], span=self.src.coordinates(b, end), uses=["a"])
        self.proof(h, tail)
        self.check()
        self.proof(tail)
        self.check("unowned")
        self.proof({**h, "span": self.src.coordinates(a - 8, b)}, tail)
        self.check("outside proof value")
        self.assertIsNone(delimiter('/- /- := -/ := -/ "x:=y" «:=» r#"abc":="#'))

    def test_show_obtain_and_suffices(self):
        self.fixture(("theorem example₁ (h : True ∧ True) : True := by\n"
                      "  obtain ⟨p, q⟩ : True ∧ True := h\n"
                      "  suffices x : True by exact x\n"
                      "  show True\n"
                      "  exact p\n").encode())
        steps = [self.step(str(i), [i, i], typed_fact=t) for i, t in [(2, "True ∧ True"), (3, "True"), (4, "True")]]
        steps.append(self.step("5", [5, 5]))
        self.proof(*steps)
        self.assertEqual(self.check()["counts"]["typed_facts_in_source"], 3)
        self.proof(*steps[:2], self.step("4", [4, 5]))
        self.check("complete source type")

    def test_local_bindings_in_intermediate_type(self):
        fact = "let x := let y := 0; y; x = x"
        self.fixture(f"theorem t : True := by\n  have h : {fact} := rfl\n  trivial\n".encode())
        tail = self.step("result", [3, 3])
        self.proof(self.step("h", [2, 2], typed_fact=fact), tail)
        self.check()
        self.proof(self.step("h", [2, 2], typed_fact="let x"), tail)
        self.check("complete source type")

    def test_nested_branch_ownership(self):
        self.fixture(("theorem t (x y : Bool) : True := by\n"
                      "  cases x with\n"
                      "  | false =>\n"
                      "    cases y with\n"
                      "    | false => trivial\n"
                      "    | true => trivial\n"
                      "  | true => trivial\n").encode())
        steps = [self.step("outer", [2, 7], head_lines=[2, 2]),
                 self.step("left", [3, 6], kind="case", parent="outer", head_lines=[3, 3]),
                 self.step("inner", [4, 6], parent="left", head_lines=[4, 4]),
                 self.step("f", [5, 5], kind="case", parent="inner"),
                 self.step("t", [6, 6], kind="case", parent="inner"),
                 self.step("right", [7, 7], kind="case", parent="outer")]
        self.proof(*steps)
        self.check()
        steps[-1]["uses"] = [{"step": "f"}]
        self.proof(*steps)
        self.check("not in scope")

    def test_equation_branches(self):
        self.fixture(("theorem t : (b : Bool) → True\n  | false => trivial\n  | true => trivial\n").encode())
        a, b = (self.step(str(i), [i, i], kind="case", parent="equations") for i in (2, 3))
        parent = self.step("equations", [2, 3], kind="cases")
        self.proof(parent, a, b)
        self.check()
        self.proof(parent)
        self.check("distinct case child")

    def test_horizontal_branches(self):
        self.fixture(("theorem t (b : Bool) : True :=\n"
                      "  match b with | false => trivial | true => trivial\n").encode())
        lo = self.src.text.index("match")
        first = self.src.text.index("|")
        second = self.src.text.index("|", first + 1)
        end = self.src.line_stop(2)
        parent = self.step("match", [2, 2], head_lines=[2, 2], head_span=self.src.coordinates(lo, first))
        a = self.step("f", [2, 2], parent="match", kind="case", span=self.src.coordinates(first, second))
        b = self.step("t", [2, 2], parent="match", kind="case", span=self.src.coordinates(second, end))
        self.proof(parent, a, b)
        self.check()
        self.proof(self.step("one", [2, 2]))
        self.check("distinct case child")

    def test_indivisible_leaf(self):
        self.fixture(("theorem t : True := by\n  exact (\n" + "\n" * 7 + "    True.intro)\n").encode())
        self.proof(self.step("a", [2, 10]))
        self.check("without an indivisible reason")
        self.proof(self.step("a", [2, 10], indivisible="One parenthesized exact term."))
        self.assertEqual(self.check()["proof_checks"][0]["exceptions"], ["a"])
        # Rebind the dossier to the changed source to isolate the leaf gate.
        self.file.write_text("theorem t : True := by\n" + "  skip\n" * 8 + "  trivial\n", encoding="utf-8")
        self.src = SourceFile(self.file.read_bytes())
        u = load(self.unit / "unit.json")
        for field in ("sha256", "file_sha256"):
            del u["members"][0][field]
        dump(self.unit / "unit.json", u)
        self.proof(self.step("a", [2, 10], indivisible="One tactic."))
        self.check("several written commands")


@unittest.skipUnless(os.environ.get("READBACK_TEST_LEAN") == "1", "run make selftest-lean with the pinned Lean toolchain")
class NativeRangeTests(Workspace):
    def test_lean_parser_and_independent_recheck(self):
        # A built TOML package can have no .lake/ when its buildDir is custom.
        config = self.art / "lakefile.toml"
        config.write_text('buildDir = "objects"\n' + config.read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run(["lake", "build", "Tiny"], cwd=self.art, check=True, capture_output=True)
        self.sample()
        r = self.check(None, "--lean-ranges")
        for entry in r["sources"].values():
            self.assertEqual(entry["basis"], "lean-parser")
            sf = SourceFile((self.art / entry["file"]).read_bytes())
            v = entry["source_ranges"]["value"]
            a, b = sf.offsets(v["span"])
            self.assertEqual(hashlib.sha256(sf.text[a:b].encode()).hexdigest(), v["sha256"])
        path = self.unit / "unit.json"
        u = load(path)
        for m in u["members"]:
            m["source_ranges"] = r["sources"][m["id"]]["source_ranges"]
        dump(path, u)
        self.check()
        # A shorter, correctly rehashed value still disagrees with the parser.
        m = u["members"][0]
        sf = SourceFile((self.art / m["file"]).read_bytes())
        lo, hi = sf.offsets(m["source_ranges"]["value"]["span"])
        m["source_ranges"]["value"] = sf.receipt(lo, hi - 1)
        dump(path, u)
        self.check("disagree with Lean syntax", "--lean-ranges")

    def test_missing_compiled_import(self):
        subprocess.run(["lake", "build", "+Tiny.Defs"], cwd=self.art, check=True, capture_output=True)
        self.sample()
        # Lean could not be asked: exit 2, the reason in words, and no record of a check
        out = self.cli("check", self.unit.name, "--lean-ranges", expect=2)
        self.assertIn("Build the artifact first", out)
        self.assertIn("error:", out)
        self.assertIn("Tiny.Basic", out)
        self.assertNotIn("info:", out)
        self.assertFalse((self.unit / "check.json").exists())

    def test_equations_structures_and_absent_values(self):
        self.fixture(("axiom fact : True\n"
                      "def toggleBit : Bool → Bool\n  | false => true\n  | true => false\n"
                      "structure Entry where\n  flag : Bool\n"
                      "def entry : Entry where\n  flag := true\n").encode())
        mod = next(m for m in load(self.ws / "reading/census.json")["modules"] if m["file"] == "Example.lean")
        path = self.unit / "unit.json"
        u = load(path)
        u["members"] = [dict(d, file=mod["file"], file_sha256=mod["file_sha256"], text="A declaration.") for d in mod["declarations"]]
        dump(path, u)
        sources = self.check(None, "--lean-ranges")["sources"]
        values = {}
        for d in mod["declarations"]:
            value = sources[d["id"]]["source_ranges"]["value"]
            values[d["name"]] = self.src.text[slice(*self.src.offsets(value["span"]))] if value else None
        self.assertEqual(values, {"fact": None, "toggleBit": "| false => true\n  | true => false",
                                  "Entry": None, "entry": "where\n  flag := true"})

    def test_parser_failure_is_reported(self):
        self.fixture(b'#eval IO.eprintln "info: incidental setup output"\n'
                     b"theorem t : True := by\n  exact (42 : Nat)\n")
        self.proof(self.step("1", [3, 3]))
        self.check()  # a faithful quotation can come from a broken artifact
        record = (self.unit / "check.json").read_bytes()
        out = self.cli("check", self.unit.name, "--lean-ranges", expect=2)       # the artifact does not compile: said, not recorded
        self.assertIn("Lean range extraction failed", out)
        self.assertIn("type mismatch", out.lower())
        self.assertIn("Nat", out)
        self.assertIn("True", out)
        self.assertRegex(out, r"Example\.lean:3:\d+: error")
        self.assertEqual((self.unit / "check.json").read_bytes(), record)
        self.assertNotIn("incidental setup output", out)

    def test_unicode_and_inner_assignment(self):
        fact = "let x := let y := 0; y; x = x"
        self.fixture((f'theorem vérité (s : String := ":=") : True := by\r\n'
                      f'  have h : {fact} := rfl\r\n  exact True.intro\r\n').encode())
        self.proof(self.step("h", [2, 2], typed_fact=fact), self.step("1", [3, 3]))
        r = self.check(None, "--lean-ranges")["sources"][self.mid]["source_ranges"]
        self.assertEqual(self.src.text[slice(*self.src.offsets(r["statement"]["span"]))],
                         'theorem vérité (s : String := ":=") : True')
        self.assertEqual(self.src.text[slice(*self.src.offsets(r["value"]["span"]))],
                         f"by\r\n  have h : {fact} := rfl\r\n  exact True.intro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
