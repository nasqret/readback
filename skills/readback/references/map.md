# The map

## What exists in every workspace

`rb.py status` writes `STATUS.md` (a table of units with their state and counts) and `map/MAP.md` (a Mermaid
graph: an arrow from a unit to a unit that uses it; green = note and structured proofs, amber = structured
proofs checked, blue = dossier not yet checked, grey and dashed = not read yet) and `map/map.json`. Run it after
every change. Grey entries are a feature: they show the scale of the artifact and what is still to come, with
true numbers. Never hide them, and never colour a unit above what the checks say. A unit turns green only
when its dossier passes the check on the present sources and built notes of its own treat every named member
that the dossier does not set aside; a definition that the note of another unit cites for its setting stays
unread, and so does a unit whose note failed to build or is still the template. When a unit is less than you
expect, the State column of `STATUS.md` says why.

## The site that every workspace builds

This is a **reading site**, not the atlas. The atlas of the large case
([riemann-proof-atlas](https://nasqret.github.io/riemann-proof-atlas/)) puts every declaration on a published map
of the mathematical literature and has an explorer, search and a chapter panel; that is a separate bundle, and it
is not in this skill yet. Do not call the reading site "the atlas"
when you report, and do not tell the owner the atlas exists for a workspace until it does.

Two rules for the atlas are already decided and bind whoever builds it: the
paper map is fetched from its source, at its pinned revision, into a cache on the machine when a site is built,
and is never committed to the skill or to a workspace; and a built site carries its own copy of the paper data
(about 144 MB whatever the size of the artifact). The paper map's repository declares no licence: publishing a
site that carries it is the owner's decision each time.

`rb.py site` writes `site/` (or `--out DIR`): plain files, no server, no network; open `site/index.html`.
Build it after every note and every checked dossier, and tell the owner where it is. It holds:

- **the map** (`index.html`): the units as a drawing, a unit below the units it uses, coloured by state, with
  the tables of units, notes, structured proofs and source files;
- **a page per unit**: what it proves in words, its declarations with their Lean statements, what it takes for
  granted (each input with the state of the unit it comes from), where it is used, the result of the check;
- **a page per structured proof**: the tree of steps on the left, the whole declaration on the right; choosing
  a step marks its lines; a step has an address (`#s-<id>`);
- **the Lean source**, every file with line anchors (`#L33`);
- **a reader per note**: the pages of the PDF on the left, the Lean text on the right. Every labelled statement
  carries a round mark in the margin and every LEAN line of the note is a link; choosing one shows the
  declarations behind it (reading in words, statement, whole declaration, structured proof). The choice is in
  the address (`#at=…`).

How the reader finds its places: the statements from the PDF's named destinations (`pdfinfo -dests`) through
`reader.json`; the LEAN lines by their position in the text of the pages (`pdftotext -bbox`), the k-th one being
the k-th `\leanline` of the LaTeX source. When the counts differ no LEAN line is marked and the command says so:
then a `\leanline` was written by hand without the macro, or the word LEAN stands in small type elsewhere.
Without poppler the PDF is shown in a frame, without marks.

What it does not do yet: text of a page cannot be selected (the pages are pictures; the PDF itself is one link
away), and it has been looked at in one browser at a wide window. Publishing the site anywhere is the owner's
decision; run `rb.py leakscan` on it first.

## A site on three levels, for a large artifact

For an artifact with hundreds of units the built site is the start, not the end. The design that worked:

**Journeys** (test each by hand on every release):
1. *From the statement to a line of Lean.* Final theorems → one theorem → the component or chapter that carries
   it → its note → a lemma → its structured proof → a step → the Lean lines, marked. At most eight choices;
   every screen shows the trail and one control that goes up.
2. *From a line of Lean upwards.* A declaration names its chapter, its place in the note, its structured proof,
   what uses it, up to a final theorem.
3. *Taking for granted.* A chapter lists what it takes for granted, each as a statement in words with its
   state ("proved in chapter N; note published / structured proofs / not read"). The reader goes on without
   opening it, or opens it and returns by the trail.
4. *The whole proof.* A reading order of chapters in which each comes after what it takes for granted.
5. *On the map.* Chapters are regions; choosing one fades the rest and shows its outline: a small graph of what
   it proves and takes for granted.
6. *Nothing rots.* An address made today opens the same thing after the next version, or names its successor.

**Addresses.** Everything a reader sees is in the address (`#chapter=…`, `#theorem=…`, `…&step=…`); back and
forward restore it.

**The reader view.** The note's PDF on one side, the declarations and proof steps on the other, joined by
`reader.json` and by annotation records that pin the PDF by its hash. A step shows its claim, what it uses, the
typed fact and the numbered Lean lines.

**States come from published data**, not from the release being built: whether a note exists is read from the
published reader indexes, so a card never says "no note yet" about a declaration that a note treats.

## Interface rules that prevent "slop"

One shell on every page (same header, same names for the same destinations); one set of values (colours,
type scale, spacing in one file); one implementation of each part, above all **one Lean preview**: the shipped
monospace font, real line numbers, `white-space: pre` with a wrap switch that breaks at spaces and indents the
continuation, never `overflow-wrap: anywhere` on code, the full line range, copy actions. Photograph the pages
before changing them; compare in three browser engines at two widths; allow no changed pixel inside a code box.

## Testing a release candidate

- the journeys, by hand, in a real browser; say which width and browser, and what was not tested;
- the files: list the tree of the published commit, fetch every served file, compare hashes;
- the data: recount proofs, steps, leaves and quoted lines in what is served and compare with `check.json`;
- compare every quoted Lean text with the pinned source;
- a scan for private strings (`rb.py leakscan`);
- verdict through the mailbox with labels; production only after the owner's word.
