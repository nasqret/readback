# The pipeline

## 1. Open the artifact

`rb.py init WORKSPACE --artifact PATH --root MODULE [--url PATTERN]` creates the workspace, pins the commit
of the artifact if it is a git repository, and runs the census. `--url` is a link pattern such as
`https://github.com/OWNER/REPO/blob/{commit}/{file}#L{a}-L{b}`; with it every Lean name in a note is a link.

`init` prints the census summary; `reading/census.json` has the rest (`totals` holds the numbers of the cone
too). Tell the owner, in a few lines:

- size: modules, lines, declarations by kind;
- `sorry` and `axiom` declarations in the source (an artifact that "compiles" with either is a different
  object). These two counts come from reading the text and are lower bounds: a `sorry` behind a macro or in a
  declaration the census does not recognize is not counted. The census cannot say which axioms the proofs rest
  on; a kernel export or `#print axioms` can, and the note reports what Lean said;
- the cone of the root module: what the final theorems can reach by imports, and what lies outside it;
- how the code is organized (directories, naming), and whether it looks written for readers or generated;
- whether anyone has built it: the census compiles nothing.

Judge the organization from the census, the directory listing and a file or two. If you mean to make the blind
test of `references/review.md` with this reader, choose its unit now, tell the owner which, and do not open the
Lean file of that unit until the note is drafted.

The census reads names and imports only. It is the neutral ground both agents agree on. It is not the truth
about dependencies: that comes from the kernel (a declaration export of the compiled artifact), which is the
reader's first job on anything large.

## 2. Units

A **unit** is a chapter: a set of declarations read together, small enough for one dossier and usually one
note. `rb.py units` proposes one unit per module (per directory above 80 modules), ordered so that a unit comes
after what it imports. The reader turns the proposal into the ledger `reading/ledger/units.json`:

- restrict to what the root theorems really use (a kernel export; mark `basis`);
- merge modules that make one argument, split a library that serves several;
- give each unit a title in mathematical words;
- record imports and consumers between units.

Review the ledger before any dossier is written: units are the table of contents of everything that follows.
A request for a first dossier may be sent together with the request for the ledger, if it says that it waits
for the ledger's review and names its unit by a member's id; unit numbers are final only in the ledger.

In the proposal, `imports` and `consumers` of a unit come from declarations that name each other, so the map's
arrows mean "uses"; `module_imports` keeps the `import` lines. Both are syntactic until the reader has a kernel
export.

## 3. Order of work

Read **downwards from the statement**, not upwards from the foundations. Take the final theorem, find the units
that carry its argument, and read those first; their inputs are stated and taken for granted. A reader of the
result can then start at the top and descend. Reading foundations first produces notes nobody asked for.

For a large artifact, pick one thread and finish it on all levels (dossiers, notes, map) before widening. One
finished thread shows the method and its cost; ten half-read threads show nothing.

## 4. Dossiers and their check

For each unit the reader writes a dossier (`references/contracts.md`). On hand-off the writer runs
`rb.py check UNIT` and answers through the mailbox with what was verified and what was not
(`references/review.md`). A dossier that fails goes back with the failing lines.

## 5. Notes

One note per unit, or several notes for a large unit (the coverage gate N-C is measured on their union).
`references/notes.md`.

## 6. Map and book

`rb.py status` writes `STATUS.md` and `map/MAP.md` after every change. `rb.py book` assembles the notes.

## Gates

| Gate | Passes when | Checked by |
|---|---|---|
| statements | every member is at its cited lines with the hash of its text, and has its statement in words | `rb.py check` |
| L2-G grain | no leaf step quotes more than 8 source lines | `rb.py check` |
| coverage | every line of every proof lies in a leaf, a parent's head or a declared introduction | `rb.py check` |
| quotation | every step and every import of the artifact quotes its lines exactly | `rb.py check` |
| scope | every member of the unit is treated or listed out of scope with a reason | `rb.py check` |
| ledger | members exist and belong to one unit; imports and consumers mirror each other | `rb.py ledger` |
| N-C | every named member of the unit that is not out of scope is in the concordance of a built note of the unit | `rb.py status` (on the union of the unit's notes); `rb.py note` reports it for one note |
| written | no place of the template is left unwritten | `rb.py note` |
| text | every key cited, every symbol in the notation, no overfull line, no undefined reference | `rb.py note` |
| reading | the writer has read the proofs while writing, and says so in the note | the writer |

## Sizing a job

Measure, do not guess: after the first dossier and the first note, write down in `MEMORY.md` what each cost (wall
time from the clock; tokens when your client reports them, and say so when it does not) and how many proof lines
it covered. Extrapolate by the ledger's `proof_lines`. Report three sizes to the owner: the chosen thread (the
units from the final theorem down that the owner picked), the thread with the units it imports directly, and
everything the root uses. In the first two-agent test a dossier of 4 proofs and 122 proof lines took the reader
about 7 minutes and its note about 20; a large artifact is thousands of such units.

## Records every workspace keeps

`JOURNAL.md` (dated entries, newest first), `PLAN.md` (✅ 🟡 ⬜ ❓), `MEMORY.md` (facts and decisions for the next
session), `STATUS.md` (generated), `exchange/` (the mailbox). End every session by updating them and committing.
