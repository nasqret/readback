# Data contracts

Everything the two agents exchange is JSON with a `schema` field. Line numbers are 1-based and inclusive. A
declaration id is `MODULE:LINE:COLUMN` of its name (column 1 for an anonymous declaration).

## `reading/census.json` — `readback/census/1` (generated)
`made`, `root`, `artifact` (commit of the enclosing repository, `uncommitted_changes`, `toolchain`, link
pattern, and `digest`: one SHA-256 over the paths and hashes of all Lean files, the pin of an artifact that has
no commit; not the path), `uses_basis`, `totals` (modules, lines, declarations, by_kind, sorry, `axioms`: the names
of `axiom` declarations in the source, modules_in_cone, lines_in_cone, declarations_in_cone), `cone` (modules
reachable from the root by imports), `modules[]`: `module`, `file`, `lines`, `bytes`, `imports`, `file_sha256`,
`declarations[]` (also `written`, the name as typed, and `doc`, whether a doc comment precedes):
`id`, `kind`, `name`, `private`, `lines [a,b]`, `statement_lines [a,c]`, `value_col` (the column just after the declaration-level
`:=` in the line census, when present), `sha256` (of the text of lines a–b plus a newline), `sorry`,
`binders` (the arguments, in Lean's order, each with `name`, `kind`: `explicit`, `implicit`, `strict` or `instance`,
`type`, and `from`: `variable` for a section variable that the declaration takes, `signature` for a binder before
the colon, `type` for what the type itself binds in front of its conclusion, `∀ x,` and each premise `P →`; an
instance or a premise has no name; `maybe: true` marks an instance variable of a definition, which Lean takes
only when the definition's term uses it; `null` when the text could not be read. This is a reading of the text:
which section variables Lean includes, and what it binds by itself, only Lean knows),
`uses` (ids of declarations whose names occur in its text, among those of its own module and of the modules it
imports directly or through others: syntactic, not the kernel's; a local name that repeats a library name is
still mistaken for it).

## `reading/ledger/units.json` — `readback/units/1` (the reader)
`basis` (how "used" was decided: `kernel export` or `modules and names (syntactic)`), `root`, `units[]`:
`id` (a string), `title`, `modules`, `members` (declaration ids), `reached` (how many the root reaches),
`proof_lines` (lines of its theorems after their statement lines; a proof on the statement's line counts 0),
`imports` and `consumers` (unit ids: a unit imports another when one of its declarations uses one of the
other's), `module_imports` (from the `import` lines). Same shape as `units.proposal.json`.

A unit's `id` is a string; it does not change once a dossier or a note exists for the unit. `basis` is free text
that says how use was decided; the proposal says "modules and names", a ledger from Lean's kernel says so and
names the toolchain.

`rb.py ledger` checks it and writes `reading/ledger/check.json` (`readback/ledger-check/1`: `counts`, `problems`,
`notes`, `imports_that_differ_from_names`). Problems: a member that is no declaration of the census, a
declaration in two units, a unit without members or title, a repeated id, `imports` and `consumers` that do not
mirror each other or name an unknown unit, `proof_lines` that the census does not give, a root other than the
workspace's. Things to look at, not faults: declarations of the cone in no unit, units that use each other in a
circle, imports that names do not show, titles that are module names.

## `reading/units/<id>/unit.json` — `readback/unit/1` (the reader)
```json
{"schema": "readback/unit/1", "unit": "3", "title": "Gauss's sum", "summary": "two or three sentences",
 "members": [{"id": "Tiny.Gauss:13:9", "name": "Tiny.two_mul_sumTo_id", "kind": "theorem",
              "file": "Tiny/Gauss.lean", "lines": [13, 18], "sha256": "…",
              "text": "For every natural number n: 2·(0+1+…+n) = n(n+1).",
              "triage": "argument"}],
 "imports": [{"name": "Tiny.sumTo_succ", "file": "Tiny/Basic.lean", "lines": [5, 5], "unit": "2",
              "lean": "the quoted line(s)", "text": "what it says, in words"}],
 "out_of_scope": [{"id": "…", "reason": "not reached by the root"}]}
```
In a member, `binders` is the account of its arguments: one entry per argument, in Lean's order, each with
`name` (null for an instance or a premise without one), `kind`, `reads` (what the argument is, in words) and,
optionally, `type`. The check compares names and kinds with the census, entry by entry; an entry that the census
marks `maybe` may be left out. When Lean's own
signature differs from the reading of the text, the member says `"binders_basis": "lean"` and quotes what
`#check @Name` printed in `binders_lean`; the check then only requires that no argument which the declaration
itself writes is left out, and says in its summary how many members stand on Lean's word. A member without
arguments needs no `binders`.

Optional in a member: `statement_lines`; `statement_lean` (the statement as quoted from those lines; the check
compares it with the source, white space aside, and lets it stop before `:=`, `where`, `|` or `by`);
`file_sha256`; `source_ranges` (byte-exact ranges from Lean's parser); `unit`. The check ignores other fields.

Records that the reader of the first two-agent test added of its own accord, kept here as optional and shown on
the site when present: in a member, `case_readings` (for a definition by cases: a list of `lines`, `lean`,
`text`, one per constructor or clause); in the dossier, `ambient_inputs` (facts of Lean's own library that the
proofs use: `name`, `file`, `lines`, `lean`, `text`, `basis`); in an import, `role` and `quote_sha256`; in a
step, `ambient_uses` (library names) and `simp_reading` (what an automation step did, as `text` with its
evidence `label`, and `possible_rules`). Beside the ledger: `reading/ledger/kernel-reach.json`, the export of
Lean's kernel (`roots`, `nodes[]` with `name`, `module`, `kind`, `range`, `selection`, `type`; `root_axioms`:
for each root theorem the axioms it depends on; `lean_version`), and `accounting.json` (the root theorems, the
hashes of the source files, and for every declaration left outside the units the reason). These two have no
fixed schema yet: the reader owns them, and the site reads only `root_axioms` and `lean_version`.

Required by the check: `schema`, `unit` equal to the folder's name, `title`, `summary`; in every member `id`,
`file`, `lines`, `binders` (when the declaration has arguments), `sha256` (of the text of its lines joined by line feeds, plus a final line feed: the census
gives it) and `text`; in every import `file`, `lines`, `lean` (the quoted lines) and `text`; in every
`out_of_scope` entry `id` and `reason`. An import is a declaration of the artifact; a fact of Lean's own library
is not an import but an `ambient_inputs` entry. A declaration's `lines` begin at the line of its keyword:
attributes, options and a doc comment on earlier lines are not part of them, nor of the hash.

`text` is the statement in ordinary mathematical words, complete with its hypotheses: it names every argument
that `binders` lists, and it writes a defined function with all its explicit arguments (the signature rule). `triage` is one of
`argument`, `assembly`, `computation`, `automation`, `one-step`, `restatement`, `alias`; a theorem or lemma
with more than one line after its statement lines needs a structured proof unless its triage is one of the last
five. Proofs inside an `instance`, a `def` or a `structure` are not held to this by the check: treat them by
judgment and say so.

## `reading/units/<id>/proofs/<name>.json` — `readback/proof/1` (the reader)
The file name is free (the short name of the theorem is a good one); the `declaration` field binds the file to
its member.
```json
{"schema": "readback/proof/1", "declaration": "Tiny.Gauss:13:9", "summary": "Induction on n.",
 "intro_lines": [],
 "steps": [{"id": "1", "parent": null, "kind": "setup", "claim": "Induction on n.",
            "lines": [14, 18], "head_lines": [14, 14], "lean": "exact text of lines 14–18"},
           {"id": "1.2.2", "parent": "1.2", "kind": "deduction",
            "claim": "This equals (k+1)(k+2) by the identity for k.",
            "lines": [18, 18], "lean": "    exact aux_step k", "uses": ["Tiny.aux_step"],
            "typed_fact": null}]}
```
- A step with children is a **parent**: its `lines` span its children and `head_lines` are its own lines (the
  `induction … with`, the `have … := by`). A step without children is a **leaf**; a leaf has at most 8 lines.
  One command that cannot be split may be longer if the leaf carries `"indivisible": "the reason"`.
- The branches of a case split or an induction are children of kind `case`, one per branch; every branch is
  covered.
- `lean` quotes the inclusive `lines`, preserving indentation. This original format accepts LF and CRLF and
  ignores trailing spaces and tabs on each line. An optional `span: [line, col, endLine, endCol]` selects a
  nonempty, half-open range. Columns count Unicode code points from 1. With a span, `lean` must reproduce the
  selected UTF-8 bytes including trailing spaces and internal line endings. `lines` still names the touched
  physical lines. Two steps on the same line can use disjoint spans. A parent may delimit its own part with
  `head_lines` and `head_span`.
- `claim` states the mathematical fact established. Each type-stating `have`, `obtain`, `suffices` or `show`
  has its own step. Copy the complete intermediate type into `typed_fact`, including its internal whitespace.
  The type must be in the part of the step that it owns. The checker reports the type's range and hash.
- `uses` lists what the step relies on: `{"step": "1.2"}` for a step of the same proof, `{"decl": "<id or name>"}`
  for a member or an import (a bare string is read as a step if such a step exists, else as a declaration). A
  referenced step must be **in scope**: earlier, and a sibling of the step or of one of its ancestors; a branch
  of kind `case` is not in scope of its sibling branches.
- Each source token in the value belongs to exactly one leaf, parent head or initial `intro_lines` range,
  apart from the opening `by`. An inline proof on the signature line also needs coverage. Sibling ranges must
  be disjoint and each child lies within its parent. Local uses must also precede the consumer in the source.
  A declaration reference must resolve to one member or listed import, by name or id.

**Checking exact declaration ranges.** From the workspace, run `python3 tools/rb.py check UNIT --lean-ranges`.
Build the relevant Lake target in the artifact first (for the example, run `lake build Tiny` inside
`examples/tiny-lean`). The checker uses `lake env lean` to find that package’s compiled imports. If
`lake-manifest.json` is missing, the check stops before starting Lake. A package with a Lean lakefile also
needs its existing `.lake/` directory. In an initialized package, Lake can create or refresh metadata under
`.lake/` while loading the configuration and dependencies. When a compiled import is missing, the diagnostic
identifies the import and asks for a build. A standalone source directory without a Lake configuration uses
`lean` directly with its selected toolchain and import search path.

The checker reads original syntax positions for the declaration statement and value. The statement starts at the core
declaration keyword and ends at the last token of the signature. The value begins at its first token after
`:=`, or at the first `|` or `where` for an equation or structure-valued definition. Its end excludes
trailing trivia. For an axiom or a supported declaration without a separate value, `value` is null. A module
error or an unsupported declaration in the requested unit makes this mode fail.

`check.json` records each member under `sources[declaration_id]`, with `file`, `file_sha256`, `basis` and,
when available, `source_ranges`. Each range contains a four-coordinate `span` and the SHA-256 of the UTF-8
slice, with the original line endings. Copy `file_sha256` and the complete `source_ranges` object onto a
member to pin a dossier. A later source-only check independently slices and hashes the current file. With
`--lean-ranges` it also compares both spans with fresh Lean syntax.

In a step: `kind` is required and is a free word (`setup`, `induction`, `case`, `deduction`, `fact`,
`reduction`, `witness`, `identity`, `interpretation` have been used); only `case` has a meaning for the check
(the branches of a split are children of kind `case`, and a step cannot use a fact of a sibling case).
`typed_fact` is required when the step's first line is a `have`, `obtain`, `suffices` or `show` with a type.
`uses` names earlier steps in scope (`{"step": "1.2"}`) and declarations of the artifact (`{"decl": "Name"}`,
a member or an import of the dossier); a step cannot name a step that contains it. Facts of Lean's own library
go in `ambient_uses`, local hypotheses in the claim. `intro_lines`, the opening lines that belong to no step,
hold at most `leaf_bound` lines in all.

The basis is `lean-parser` for a fresh Lean run, `recorded-source-ranges` for a rechecked pair of supplied
spans, or `line-census` for a source-only dossier without spans. The line census recognizes common top-level
commands and declaration delimiters. It does not certify exact syntax boundaries. The optional unit-level
`commit` is compared to the configured workspace edition. A member's optional `file_sha256` binds the
entire file, including line endings, in either mode.

## `notes/<slug>/spec.json` — `readback/note/1` (the writer)
`title`, `number`, `unit`, `conventions` (the label of the note's `conventions` environment), `ambient` (for
implicit and instance arguments, by Lean name or by type: the words of the conventions that state them),
`letters` (Lean name of a variable: how the note writes it), `words` (first name of a hypothesis's type: the
words that state it, or a list of wordings),
`declarations[]` (`key`, `name` as shown, `id`; for a definition with explicit arguments `notation`: `macro`,
`slots`, `tex`, `symbol`, `also`, or `none` with a reason; `binders`: for each argument that no slot shows, the
words of the statement that state it, by Lean name, by `#position` or by type; `absorbed`: the reason why a
small result has no statement of its own), `quoted` (keys whose statement is
printed in the appendix), `lettered` (pairs such as `["Theorem A", "t:A"]`: a place named by words and its
label), `outline` (nodes `id`, `title`, `about`, `keys`), `elsewhere` (ids of members of the unit that another
note treats).

## `notes/notation.json` (the writer; optional)
One table for all notes of the workspace: `notations` (by Lean name or its last part: a `notation` as in a spec),
`letters`, `words`, `ambient`. `rb.py note` lays each note's spec over it; what the note says for itself wins.

## Generated beside a note
`concordance.json` (`readback/concordance/1`: per key the name, id, file, lines, file hash, statement, and
`binders` with `binders_basis`: from the dossier when it stands on Lean's word, else from the text),
`data.tex` (macros), `reader.json` (`readback/reader/1`: where every declaration is treated — item, page, named
destination — and the outline with its edges; the index a site reads), `problems.json`.

## `reading/units/<id>/check.json` — `readback/check/1` (generated by the writer's check)
The existing `counts` and `problems` summarize the unit. `dossier_sha256` is one hash over `unit.json` and the
proof files as they were checked: the status compares it, so a dossier edited after its check counts as not
checked until the check is run again. The check exits 0 with no problem, 1 with problems, and 2 when
`--lean-ranges` was asked and Lean could not answer (an artifact that is not built, or does not compile): then
nothing is recorded and the last record stays. `proof_checks[]` identifies the declaration and
dossier file, source lines with code, leaf count, sum of leaf line lengths, mean lines per leaf, exceptions
and problems. Its `steps[]` gives each id, the quotation comparison mode (`exact-utf8` or `line-text`), a range and hash for the quotation and, when present, for the
written intermediate type, plus step-specific problems. The physical-line statistic counts a shared line once
per leaf touching it. Ownership is checked on source tokens, so sharing a line does not double-count its text.

Step validation inspects written Lean tokens and layout. It skips comments, strings and quoted identifiers
when looking for commands, and recognizes written arms of standard induction, case and match layouts.
Custom tactic expansions and goals created without written branches require a reader. A long leaf needs a
nonempty reason and cannot bundle an evident sequence of sibling commands. A reviewer checks the reason
and whether the English claim follows. These comparisons supply source evidence for that review.

## `reading/census-changes.json` — `readback/census-changes/1` (generated)
Written by `rb.py census` when the Lean files differ from those of the census before: `from`, `to` (the two
times), and the names of the declarations that `changed` (another text), only `moved` (the same text at another
place), are `gone` or are `new`.

## Proposed for the next revision of the contracts

From the review by the reader of the first large case (22 November 2026). Not yet in `rb.py`:

- an **owning declaration id** on every record, and the pinned source edition on every file of a dossier;
- **second readings** recorded per step (who compared it with the source, when), apart from the first reading;
- **binders**: which hypotheses a proof mentions in the source (observed), apart from which the kernel term uses
  (unknown until tested);
- per **input**: its premises, its direct users in the unit, and candidates when the owning unit is unresolved;
- a **note-coverage register** over the union of the published notes of a unit;
- dependency closure for **types and values separately**, with labelled edges;
- the reader's own loop: extract a source packet, generate the records, check them independently against the
  pin, correct the generator, emit again.

## Mailbox
`exchange/PROTOCOL.md` in every workspace, with the definitions of the evidence labels (`kernel-verified`,
`verified`, `computed-once`, `heuristic`). Message types: `handoff`, `request`, `result`, `question`, `ack`,
`update`. Numbers count per sender; `re:` names only messages of the other agent; answered messages are
archived under `archive/<sender>/`.
