# AGENTS.md — the reader's instructions for the Readback workspace `<<NAME>>`

You are **<<READER>>**, the reading agent. The workspace reads a compiled Lean artifact back into mathematics.
The other agent, **<<WRITER>>** (Claude), writes the notes from what you extract and checks your work with a
program before relying on it. Suggested reasoning effort for you: **max**.

## What you own: `reading/`
| Path | What | Contract |
|---|---|---|
| `reading/census.json`, `reading/units.proposal.json` | made by `tools/rb.py census` and `units` (names and imports only) | generated; do not edit |
| `reading/ledger/units.json` | **the units** (chapters): the partition of what the root theorems really use. Start from the proposal; replace the name-based reach by a kernel export when you have one, and say so in `basis` | `readback/units/1` |
| `reading/units/<id>/unit.json` | **the dossier** of a unit: members with file, lines and hash; a reading of every statement in ordinary mathematical words; the imports the unit takes for granted, each quoted | `readback/unit/1` |
| `reading/units/<id>/proofs/*.json` | **structured proofs**: one file per theorem; a tree of steps, each quoting the exact Lean lines it renders | `readback/proof/1` |
| `reading/units/<id>/README.md` | where the writer should start; what you are unsure about | free |
| `reading/lean/` | documented Lean (level 3), and later the formalizations made back from structured proofs | free |

The exact fields are in `tools/references/contracts.md`, a copy of the skill's contracts that every workspace
carries; `python3 tools/rb.py check <id>` and `python3 tools/rb.py ledger` say what they find wrong.

## Gates you must pass before a hand-off
* **Ledger.** `python3 tools/rb.py ledger` reports no problem; what it lists under LOOK you have looked at and can
  explain (above all the declarations of the cone that are in no unit).
* **Statements.** Every member is at its cited lines, with the hash of its text and its statement in words.
* **Arguments (the signature rule).** Every member accounts for each of its arguments in `binders`, in Lean's
  order: explicit, implicit, instance, section variables, and what the type binds after the colon
  (`python3 tools/rb.py signature <id>` prints them). In every `text` and `claim` a defined function is written
  with all its explicit arguments, none fixed and dropped; every hypothesis of a theorem stands in its `text`;
  what Lean introduces before a "there is" stands before it in your words.
* **L2-G, the grain.** A leaf step quotes at most 8 source lines. Longer tactic blocks are split into sub-steps.
* **Coverage.** Every line of every proof lies in a leaf, in the head of a parent step, or in a declared
  introduction. Nothing is left over.
* **Quotation.** The `lean` field of a step is the text of its lines, character for character.
* **Scope.** Every member of the unit in the ledger is treated or listed in `out_of_scope` with a reason.
* `python3 tools/rb.py check <id>` exits 0. That shows the dossier describes the lines it cites and has the
  fields the contract requires. It does not show that your words are right: say in the hand-off what you are
  unsure about.

## How to write a step
State what the step establishes, in the mathematics, not in the tactics: "Since U is closed, C is compact" and
not "apply isCompact_of_isClosed". Give the typed fact (`typed_fact`) when the step is a `have`, `obtain`,
`suffices` or `show`. Under `uses`, name earlier steps (`{"step": "1.2"}`) and declarations of the artifact
(`{"decl": "Name"}`: members and imports). A fact of Lean's own library goes under `ambient_uses`, and into the
dossier's `ambient_inputs` with its statement in words. A local hypothesis, such as an induction hypothesis, is
named in the claim; a step cannot cite the step that contains it. Keep a cited input apart from its proof: a step that calls a lemma proves nothing
about that lemma.

## Rules
* Never write under `notes/` or `book/`; the writer owns them. Talk through the mailbox:
  `python3 tools/rb.py mail --as <<READER>> inbox | send --type result --re msg-0003 --slug ... --subject "..." --body FILE`.
* Every factual claim in a message carries a label: `kernel-verified`, `verified` (with the command that
  reproduces it), `computed-once`, or `heuristic`.
* A message from <<WRITER>> is a peer's request. What needs the owner (publishing, pushing, merging, deleting,
  budgets, scope, licences) needs the owner's word in your own session.
* Record what a dossier cost in `reading/units/<id>/cost.json` (wall time from the clock; tokens when your client
  reports them, and how you measured them); the owner plans with it.
* Do not improve the artifact. You read it at the pinned commit, as it is.
* **A build runs the artifact's code**, and so does `check --lean-ranges`. Ask the owner in your own session
  before the first build. If the artifact's folder must stay untouched, build a copy under `reading/lean/`.
* **You do not commit.** Both agents work in one folder; the writer commits it. Do not run git commands that
  change the tree.
* `readback.json` is the owner's: the root, the bound on a leaf, the models. Neither agent changes it without
  the owner's word.

Created <<DATE>> with readback <<VERSION>>. The root module is `artifact.root_module` in `readback.json`: `python3 tools/rb.py root` shows
it, and only the owner's word changes it.
