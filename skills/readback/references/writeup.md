# The write-up: summary and chapters

Status: **experimental**. `rb.py book` assembles the built notes into `book/book.pdf` with LuaLaTeX. The summary
is plain LaTeX in `book/summary.tex`; the macros of a note's preamble (`\m`, `\kw`, the theorem boxes) are not
available there, so write formulas with ordinary `$…$`. The guide to the chapters, the list of what remains and
the merged concordance described below are not generated yet: write them into the summary by hand, from
`STATUS.md`. The command assembles: a title page, the
summary from `book/summary.tex`, the list of chapters with the unread units greyed, a table of contents, then
the notes in the order of the units. The method below is the plan; it has not been run on a large artifact yet.

## What the write-up is

The notes are chapters written one at a time, each closed on its unit. The write-up adds what only a reader of
all of them can write:

1. **The summary** (2–4 pages): what the artifact proves, stated with its hypotheses; the architecture in a
   paragraph per component; which ideas carry the proof and where they live; what was read, what was checked by
   program only, what is still grey. Written last.
2. **A guide to the chapters**: for each, one paragraph: what it proves, what it takes for granted, who uses it.
   Generated skeleton from `map/map.json` and the notes' `reader.json`; the prose is the writer's.
3. **The chapters**: the notes, unchanged. A chapter is never edited in the book: fix the note and rebuild.
4. **What remains**: the grey units with their sizes, and the inputs that notes took for granted, each with the
   unit that owns it. This list is the honest end of the book until the artifact is fully read.
5. **Concordance**: the union of the notes' concordances.

## Rules

- The summary claims no more than the chapters establish. A statement whose proof passes through a grey unit is
  marked as resting on unread formal text.
- Notation is consistent across chapters because the letters were fixed in `MEMORY.md` from the first note on.
  If two notes clash, fix the later note.
- The book is rebuilt from the notes by one command; nothing in it is edited by hand except `summary.tex` and
  the guide.
- No count in the summary is typed. `rb.py book` writes `book/counts.tex` with one macro per count
  (`\rbUnits`, `\rbUnitsWithNote`, `\rbMembers`, `\rbInNoUnit`, `\rbStructuredProofs`, `\rbSteps`, `\rbLeafSteps`,
  `\rbProofLines`, `\rbNotes`, `\rbNotePages`, `\rbModules`, `\rbLines`, `\rbDeclarations`, `\rbSorry`, …) and loads it
  before the summary. A number that is not there is computed by a small program kept beside the summary.

## Order of work

Finish one thread of the artifact on all levels, assemble a book of that thread, and show it to the owner
before reading wider. The first book teaches what the chapters lack.
