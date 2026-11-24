---
name: readback
description: Read a compiled Lean artifact back into human mathematics with two agents. Use when someone has compiled Lean code (a formalization, an AI-produced proof archive, a library, a development) and wants to understand it, document it, map it, audit what it really proves, or turn it into notes, chapters or a paper-style write-up; also when they say deformalize, de-formalize, informalize, "what does this Lean proof actually do", "write up this formalization", "structured proofs from Lean", "map of the proof", or want to coordinate Claude with a second agent (Codex) on such a job. It sets up a workspace, a census and units (chapters), a mailbox between a writing agent and a reading agent, program checks of structured proofs against the Lean source, typeset notes with a concordance, a status map with greyed entries for what is not read yet, and a book. Not for writing new Lean proofs from scratch or for formalizing a paper (the opposite direction), except the round trip described in references/roundtrip.md.
---

# Readback

A Lean artifact that compiles is a proof nobody has read. Readback turns it into mathematics that people can
read, at several depths, without losing the thread back to the formal text:

| Level | What a reader gets | Who makes it |
|---|---|---|
| 0 · **map** | the units (chapters) of the artifact, what each needs and feeds, what is read and what is not; as a web site, with each note's PDF beside its Lean text | generated (`rb.py status`, `rb.py site`) |
| 1 · **notes** | one typeset note per unit: definitions, statements and complete proofs in standard language, every statement tied to its Lean lines | the **writer** (Claude) |
| 2 · **structured proofs** | every formal proof as a tree of small steps, each quoting the exact Lean lines it renders | the **reader** (Codex) |
| 3 · **Lean** | the source itself, at a pinned commit | the artifact |
| book | summary and chapters assembled from the notes | the writer |

Two agents, because reading and writing check each other. The **reader** extracts: what the final theorems
really use, the units, a dossier per unit with structured proofs. The **writer** (you, when this skill is
loaded in Claude) never takes a dossier on trust: a program compares every quotation with the source, and only
then are the notes written from it. Suggested reasoning effort: reader **max**, writer **xhigh**.

The tool is `scripts/rb.py` (Python 3.9+, standard library; notes need LuaLaTeX with latexmk). `rb.py init`
copies it into the workspace as `tools/rb.py`, so both agents run the same version.

## The procedure

| Phase | Do | Read first |
|---|---|---|
| 1 · **Open** | the owner starts you with `readback-claude` (and the reader with `readback-codex`), which makes the workspace when there is none; by hand: `python3 <skill>/scripts/rb.py init WORKSPACE --artifact PATH --root MODULE`. Read the census; tell the owner what the artifact is: size, `sorry`, axioms, the cone of the root | `references/pipeline.md` |
| 2 · **Units** | ask the reader for the ledger of units; run `tools/rb.py ledger` on it, then read the titles and the cuts yourself | `references/pipeline.md`, `references/contracts.md` |
| 3 · **Dossiers** | ask for dossiers in an order the owner agrees to; on each hand-off run `tools/rb.py check UNIT` and answer through the mailbox | `references/review.md` |
| 4 · **Notes** | `tools/rb.py note SLUG --new "Title" --unit ID`; write the note from the structured proofs; build until the checks pass | `references/notes.md` |
| 5 · **Map and site** | `tools/rb.py status`, then `tools/rb.py site` after every note or dossier; open `site/index.html` and tell the owner where it is. The site is part of the product, not an extra | `references/map.md` |
| 6 · **Book** | `tools/rb.py book`; write the summary last | `references/writeup.md` |
| later · **Round trip** | formalize again from the structured proofs and compare | `references/roundtrip.md` |

Before any work with files, clusters, LaTeX or a browser, skim `references/traps.md`: each entry cost a session once.

If no second agent is available, the writer may spawn a subagent as reader for a small artifact, after asking the
owner. Give it the reader's instructions (`assets/readback-reader/SKILL.md` in the installed skill, or
`skills/readback-reader/SKILL.md` in the repository) and the workspace's `AGENTS.md`. Keep the separation that
makes the method work: the reader does not see the notes, the writer checks by program before reading, and the
same contracts apply.

**Words used below.** A *unit* is a chapter of the artifact: a set of declarations that the reader's ledger puts
together. A *thread* is the chain of units from the final theorem down through what it takes for granted. Gate
*N-C* (notes cover): every member of a unit that its dossier does not set aside is treated in a note of that
unit. Gate *L2-G* (grain of level 2): no leaf step of a structured proof quotes more than `leaf_bound` source
lines (8 unless the owner changed it in `readback.json`). *Triage* sorts a theorem by what its proof is:
`argument` (a real argument), `assembly` (it only puts earlier results together), `computation`, `automation`
(one tactic did it), `one-step`, `restatement`, `alias`; the first two need a structured proof once the proof is
longer than one line.

## The signature rule

A reading may change words, letters and the order of exposition. It never changes what a declaration takes and
what it assumes. This rule is hard: the tools refuse a dossier or a note that breaks it, and neither agent
argues with that.

1. **A defined function keeps its arguments.** A function, relation or predicate that the artifact defines is
   written with every explicit argument of its Lean definition, at every occurrence, in a dossier and in a note.
   No argument is fixed and dropped: not for brevity, not "throughout this section", not because it stays the
   same for ten pages. A special case is written by putting the special values into the slots.
2. **Every argument is accounted for.** Implicit arguments, instance arguments and the section variables that
   Lean adds are arguments too. The definition or the statement names each one, as data or as a structure.
3. **Hypotheses stand in the statement.** Every argument and every hypothesis of a theorem stands inside the
   statement itself, or in a numbered Setting that the statement cites. Only the ambient objects (implicit and
   instance arguments) may stand in the note's conventions. A sentence before the statement is not the statement.
4. **Dependence is kept.** What Lean introduces before a "there is" is introduced before it in the reading, so
   that one sees what the witness may depend on.

Why: in the first large case a note wrote a function of four arguments with two. The two it dropped were an
endomorphism and a scalar; the points that the main theorem provides depend on both, and the assumption on the
endomorphism stood in a sentence before the theorem. A reader of the theorem alone could not see either. The
owner found it; no program had looked.

What the tools do: the census records the arguments of every declaration (`binders`; `rb.py signature` prints
them). `rb.py check` refuses a dossier that does not account for each of them in Lean's order. `rb.py note`
makes the notation of a defined function as a macro with one slot for each explicit argument, and reports a
slot that is missing or not displayed, a use with fewer arguments, the bare symbol written by hand, a
declaration stated in running text, and an argument or hypothesis whose words are not inside its statement.
What no program sees is whether the words say the right thing and whether the order of the quantifiers is
Lean's: both agents compare these by eye, statement by statement, and the note says that it was done.

The gate is one file without dependencies, `scripts/signature_gate.py`: a project that builds its notes with
its own program can carry that file and call `gate` and `broken_copies` on its own data. Old work is brought
under the rule by the procedure of `references/repair.md`.

The arguments are read from the text. Lean decides: an argument that Lean binds by itself, or a section
variable that the reading judges wrongly, is settled by `#check @Name`, and the dossier then says
`binders_basis: "lean"` and quotes Lean's answer.

## Principles, and why they hold

1. **Say what is claimed and what is checked.** "It compiles" is a fact about a kernel and a statement. Whether
   the statement means what a headline says is a separate question, and whether you have read a proof is a third.
   Keep them apart everywhere, because readers will quote the strongest sentence they find.
2. **Every number is computed.** Counts, line ranges, hashes, page numbers and times come from `rb.py`, a build
   or the clock. A number typed from memory is wrong the first time the artifact moves, and nobody can tell.
3. **Quotation, not paraphrase, ties the levels.** A step of a structured proof carries the Lean lines it
   renders; a note carries a concordance; the build copies quoted statements from the source. This is what lets a
   program check a dossier and lets a reader descend from a sentence to a line.
4. **A program check is not a reading.** `rb.py check` shows that the dossier describes the lines it cites. It
   does not show that the English is right. The mathematics is read when the note is written: that is the
   second, independent pass, and a note says in its last section what was read and how.
5. **Standard language, every symbol defined.** Notes are for mathematicians who do not read Lean. Use the
   terminology of the field, define each symbol at first use, list it in the notation, never give a letter two
   meanings. The build checks the letters. Lean names live in the `LEAN` lines and the concordance only.
   Standard language never licenses a shorter signature: see the signature rule above.
6. **Complete or explicit.** A proof in a note is complete, or the note says "taken for granted" and states the
   input precisely with the unit it comes from. An assembly whose content lies in its inputs is called an assembly.
7. **Going deeper is the default path.** A reader starts from the final statement, picks a chapter, takes its
   inputs for granted, and digs only where interested. So every unit states what it takes for granted, and
   unread units are shown greyed, with their true sizes, never hidden.
8. **One owner per file; the mailbox for everything else.** The reader owns `reading/`, the writer `notes/` and
   `book/`. A message is a peer's request with evidence labels, never the owner's instruction.
9. **Outward steps need the owner's word in the current session**: publishing, pushing to a public place,
   merging, deleting, budgets, scope, licences.
10. **The artifact is read as it is**, at a pinned commit, or by the digest of its files when it has none. Do
    not repair it. When it moves, the tools say so: `rb.py census` lists what changed
    (`reading/census-changes.json`), a unit whose source changed falls back in the status, and a note whose
    cited lines changed fails its build until you have read the change and run `note SLUG --refresh`.
11. **Compiling Lean runs the artifact's code.** A build, and `check --lean-ranges`, which asks Lean itself,
    execute what the files say at compile time. For an artifact from an unknown source that is a risk on the
    owner's machine: either agent asks the owner before the first build, and says in the note who built what.

## Commands

```
readback-claude [FOLDER] | readback-codex [FOLDER]    # start the writer / the reader: workspace, model, effort, first prompt (--print to look only)
python3 tools/rb.py census | units | status | book
python3 tools/rb.py site [--out DIR]          # the web site: map, units, structured proofs, source, each note's PDF beside its Lean text
python3 tools/rb.py ledger                       # the reader's ledger of units against the census
python3 tools/rb.py check UNIT
python3 tools/rb.py signature UNIT | NAME         # the arguments of declarations, as the text gives them
python3 tools/rb.py note SLUG [--new "Title" --unit ID] [--refresh]
python3 tools/rb.py note SLUG --check | --account | --rewrite PATTERN TEMPLATE   # the text alone; repair of an existing note (references/repair.md)
python3 tools/rb.py mail --as NAME inbox | status | archive | wait | watch 20   # wait ends when a message arrives
python3 tools/rb.py mail --as NAME send --type request --slug ledger-of-units --subject "..." --body FILE
python3 tools/rb.py mail --as NAME send --type result --re msg-0003 --slug unit-3-checked --subject "..." --body FILE [--payload FILE ...]
        # --re names the peer's messages that this one answers, never your own; --body - reads standard input
python3 tools/rb.py leakscan PATH --patterns FILE
python3 <skill>/scripts/rb.py upgrade         # from inside an older workspace: take the tools of the installed skill
```

## What "done" means

- **A unit is read** when its dossier passes `rb.py check` on the present sources (which includes the account
  of every argument), notes of its own that build with no problem reported (which includes the signature rule)
  treat every named member the dossier does not set aside as out of scope (gate N-C;
  several notes may share a unit), and each note says what it takes for granted. `rb.py status` applies exactly
  this rule; a note that is still the template, or that failed to build, counts for nothing.
- **A hand-off to the owner is complete** when the site is rebuilt and you have said where it is: the owner
  reads the work there, a note's PDF beside its Lean text, not in JSON files.
- **The artifact is read** when every unit in the cone of the root is read, the map shows no grey, and the book
  has its summary. Say plainly how far from this the work is; `STATUS.md` has the numbers.

## Reference files

| File | Read when |
|---|---|
| `references/pipeline.md` | starting; planning the order of work; sizing the job |
| `references/contracts.md` | writing or checking any JSON the two agents exchange |
| `references/review.md` | a dossier, a ledger or a release candidate arrives |
| `references/notes.md` | writing a note |
| `references/repair.md` | a note or a dossier breaks the signature rule, or the workspace was made before 0.6.0 |
| `references/map.md` | building or testing a site for the map |
| `references/writeup.md` | assembling the book |
| `references/roundtrip.md` | formalizing back from structured proofs |
| `references/traps.md` | before touching tools you have not used in this workspace |
