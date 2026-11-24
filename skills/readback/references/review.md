# Reviewing what the reader hands over

## A dossier

1. Run `python3 tools/rb.py check UNIT`. Inspect the declaration and step IDs in `check.json` for any
   failures. With the artifact and its dependencies built, add `--lean-ranges` to compare the dossier with
   the declaration boundaries Lean reads. The per-step receipts identify the exact source for your reading.
2. If it fails, answer with a `result` that quotes the problems. Do not start a note.
3. If it passes, look at what a program cannot see, on a sample of steps (take every tenth leaf, and every step
   of the main theorem):
   - Does the `claim` say what the quoted lines do, or only that a tactic was called?
   - Is a cited input kept apart from its proof? A step that applies a lemma proves nothing about the lemma.
   - Are the statements in `text` complete: every hypothesis, every quantifier, the right direction of an "if"?
   - The signature rule: `rb.py signature UNIT` beside the dossier. Does every `text` name each argument that
     `binders` lists, also the implicit ones and the instances? Is a defined function written with all its
     explicit arguments in every `text` and every `claim`, or was one fixed and dropped? Does what stands before
     a "there is" in Lean stand before it in the words? Where `binders_basis` is `lean`, the program could not
     confirm the list: run `#check @Name` yourself when the artifact is built, or say that you did not.
   - Do the words match the definitions? Check the meaning of each structure in its definition, not in its name.
4. Answer with a table: claim, label, how to reproduce. Say what you did not check. Example:

   | Claim | Label | Reproduce |
   |---|---|---|
   | 39 of 39 statements at their lines; 21 proofs, 213 leaves, all quoting | `verified` | `python3 tools/rb.py check 7` |
   | the mathematics of the proofs | not checked: read when the note is written | |

The program check and the reading are different things; keep both sentences in every review.

## A request

There is no form to fill in, but a good request has four parts: what the owner asked (in the owner's words,
marked as such), what exactly you ask for (files, schema, order), what you already know (a table of claims with
labels and how to reproduce each), and what you did not check. Say how you will answer: with which command and
which kind of message.

## A ledger of units

First by program: `python3 tools/rb.py ledger`. It finds members that are no declarations, a declaration in
two units, imports and consumers that do not mirror each other, a wrong count of proof lines; and it lists what
to look at: declarations of the cone in no unit, circles, titles that are module names, imports that names do
not show. A ledger with problems goes back to the reader before anything is read from it.

Then by reading, which no program does: do the titles describe mathematics; are library units (many members,
few arguments) separated from argument units; does each cut follow the argument and not the file; does the
order follow the imports; is every declaration left out of all units left out for a stated reason? Ask how
"used" was decided and record the answer (`basis`). When the basis is a kernel export, ask for the export and
for the command that made it, and recount at least the size of the closure yourself.

## A blind test, once per reader

To learn how much to trust a reader, once, on one unit that you choose at the start and name to the owner:
write its note from the dossier alone, without opening the Lean file of that unit. For this one unit the
comparison of the statements with the Lean text, which is otherwise part of every review and of every note,
comes after the draft instead of before it. Then compare each statement with the Lean text, count how many
agree, and report the count to the reader and in the note, with exactly what you did and did not see. Where the
comparison fails, the dossier's `text` fields were not complete, and the reader should know.

## A release candidate of a site

See `references/map.md`: run the journeys by hand, compare the served files with the commit, recount the data
against the dossier check, scan for private strings. Report what was not tested (phone width, other browsers).

## When upstream moves

A note is pinned to a commit, or to the digest of the files. When the artifact moves, `rb.py status` warns, and
`rb.py census` reads the pin again and writes `reading/census-changes.json`: the declarations that changed, only
moved, went or are new. Then: run `rb.py check` on every unit (a dossier whose member changed fails, and its
unit falls back in the status); tell the reader which dossiers to make again; build every note, which fails on
each cited declaration whose lines or statement changed. Read each such difference and record a one-line verdict
for it in `MEMORY.md` ("named implicit arguments; the same statement"), and only then run `note SLUG --refresh`.
A change inside a proof that leaves lines and statement alone is caught by the check, not by the note: the note's
proof may now describe an argument that is gone, so read the new dossier before trusting the note again.
