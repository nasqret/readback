# Repairing a note or a dossier that breaks the signature rule

For work that exists already: a note written before the rule, a note the owner or the reader found shortened, a
workspace upgraded from a version before 0.6.0. The rule is in `SKILL.md`; how a new note meets it is in
`notes.md`. This file is the procedure for bringing old work under it, as it was done on the notes of the first
large case, where a function of four Lean arguments had been written with two.

## What to expect

A shortened notation is rarely alone. In the first case the owner found one function; the audit by program found
two more in the same note (a reference layer written without its two arguments, a valuation without its prime),
and the other notes had been written in the same style throughout. Audit every note of the workspace, not only
the one that was reported, and say what you found before you repair.

## The procedure

1. **Facts first.** `python3 tools/rb.py census`, then `python3 tools/rb.py signature UNIT`: what every declaration
   takes, in Lean's order. Read it beside the note. Do not trust your memory of the definitions.
2. **Prepare the accounts.** `python3 tools/rb.py note SLUG --account` adds to `spec.json` a place for everything
   that is missing (a `notation` for each definition with explicit arguments, with Lean's arguments as slots;
   `letters`, `words`, `ambient` with empty entries) and lists what to do. It changes nothing that is there.
3. **Decide the notations**, one table for the whole note before touching the text:

   | Lean definition | explicit arguments | the note wrote | the note will write |
   |---|---|---|---|
   | `twLen γ u e m` | γ, u, e, m | τ(h,m) | τ(γ,u;h,m) |

   Letters may change; the number of arguments may not. An argument that is "always the same" is written all the
   same. When a formula becomes heavy, introduce a letter for the whole value *inside the statement* ("writing
   n = m₀(ℓ,R)"), never a shorter name for the function.
4. **Bring the text to the notations.** Fill in `tex` and `symbol` of each notation; the build then makes the
   macro. Replace the old way of writing with `python3 tools/rb.py note SLUG --rewrite 'PATTERN' 'TEMPLATE'`, which
   leaves comments and the lines that define macros alone and keeps the old text beside the new. Read every changed
   line: an argument that the old text left out has to be the right one in each place (in an example it is a
   number, in an application it is a particular object).
5. **Move the hypotheses.** Every sentence of the kind "in the next three statements X is …", "throughout this
   section", "let … be as above" becomes a numbered `setting` that each statement cites inside its own text, or
   goes into the statements. Ambient objects (the prime, the base ring) go into the `conventions`. Say in words,
   near the main theorem, in which order the data are chosen: what is given before the "there is".
6. **Account for the arguments.** `letters` for variables, `words` for hypotheses by the head of their type,
   `binders` in a declaration for what is special to it, `absorbed` (with the reason) for a small result that the
   note only uses inside a proof.
7. **Build until the list is empty.** `python3 tools/rb.py note SLUG`. On success the build tries the gate on
   copies of the note that break the rule on purpose and says how many it caught. A build that never ends is a
   macro that calls itself: stop it and look at the macro definitions.
8. **Look at the pages**: the definition, the main statements, one application. A reader who opens the main
   theorem alone must see every object it speaks of and every assumption.
9. **Say what changed** in the note itself, in a short paragraph ("Changes in this edition"), in plain words: what
   was hidden, and that no statement or proof changed in content, if that is so. Keep the earlier published PDF
   as an edition; publish the new one only on the owner's word; tell the reader, whose records point at pages.
10. **A dossier.** `rb.py check UNIT` names every member without its `binders`. The reader fills them in (from the
    kernel export where there is one), and corrects any `text` or `claim` that writes a function with fewer
    arguments than it has.

## Several notes

- **One table for all notes, first.** `notes/notation.json` says how each Lean definition is written in every note
  of the workspace (`{"notations": {"<Lean name>": {"macro", "slots", "tex", "symbol", "also"} or {"none": reason}},
  "letters": {…}, "words": {…}, "ambient": {…}}`). A note's own spec may add to it for itself. Write the table for
  every definition that more than one note cites before anyone repairs a note; otherwise two notes come back with
  two notations for one object. The tool's own check catches a table entry whose `symbol` is not in its `tex`.
- **A note uses definitions it does not cite.** The module of another unit, the Galois group, a character: the note
  writes them, and its concordance does not list them. The build makes the macro of every notation of the shared
  table that the note uses and holds each use to the rule; a form typed by hand is outside the gate. So write
  such a definition through its shared macro too. In the first case this was found only when a worker said so.
- **One worker per note, in parallel.** A note is one owner's file. Give each worker the brief
  `tools/repair/BRIEF.md` (a copy of the skill's `assets/repair/BRIEF.md`) with its note's particulars; the workers change only their note and its
  spec and report notations, settings, judgment calls and real differences from Lean. In the first case three
  notes with 696, 123 and 409 reported items were repaired this way.
- **Read what comes back.** The gate says that words stand in a statement, not that they are right. Read every
  statement that changed against `rb.py signature`, look at the pages, and merge notations that the workers
  proposed for shared definitions into the table before the last build.
- **The working loop** is `rb.py note SLUG --check`: the text alone, in seconds. The full build comes when the
  list is empty.

## Traps of this repair

- A replacement over the whole file also rewrites the definition of the macro it introduces, which then calls
  itself; LaTeX loops without a word. `--rewrite` skips definitions; a script of your own must do the same.
- A check that says nothing may be unable to say anything. The first gate compared a symbol as a regular
  expression, in which `\t` is a tab, and could not fire for `\tau`. Break a copy on purpose and watch the gate
  catch it; the build does this for every notation.
- The examples of a note use the notation too. There the special values stand in the slots.
- Pictures and tables hold formulas: a figure in TikZ and the notation list at the end are text like any other.
- A longer notation moves line breaks. Expect overfull lines and a page more; split a display, do not shorten
  the notation.
- A `\label` after a heading has no anchor: its link opens the item before it. The second reader of the first case
  found one in a published index. Write `\phantomsection` before such a label; the build reports two places with
  one destination.
- A symbol check that fires on another object is a fault of the table, not of the note. Two workers of the first
  case met it and both disguised the text (a brace around a letter, a character given by its code) and said so.
  The repair belongs in the table: give the other object a notation of its own, or make the `symbol` more
  specific; `symbol` may be a list, its first entry the one in the notation's TeX. Never spell around a check.
- A shared notation is given to a definition only. A theorem with the same last name as a definition does not
  get it (the tool is told the kinds); name the table's entry by the full Lean name when two definitions clash.
- A formula that runs over two source lines is not found by `--rewrite`. Search for the bare symbol afterwards;
  the build reports every place where it is still written by hand.
