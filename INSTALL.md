# Installing and testing Readback

## What you need

| | For | Check |
|---|---|---|
| Python 3.9 or later | everything | `python3 --version` |
| LuaLaTeX with `latexmk`, and the fonts Libertinus, Inter, JetBrains Mono, STIX Two Math, DejaVu (all in a full TeX Live) | building notes and the book | `latexmk --version`, `lualatex --version` |
| poppler (`pdftocairo`, `pdfinfo`, `pdftotext`) | the pictures of a note's pages on the site, with their marks; without it the PDF is shown in a frame | `pdfinfo -v` |
| the artifact’s own Lean toolchain, plus Lake for a Lake project | confirming compilation and running `check UNIT --lean-ranges` | build the relevant Lake target in the artifact first |
| Claude Code | the writer | `claude --version` |
| Codex | the reader | |

`rb.py` uses the Python standard library only. Without LaTeX everything except notes and the book works.

## Install

```bash
make selftest         # portable checks and the end-to-end example
make selftest-lean    # optional, requires Lake and the example’s pinned Lean toolchain
make install          # the skill for Claude Code (~/.claude/skills/readback) and the two start commands (~/.local/bin)
make install-codex    # optional: the reader's skill for Codex; `readback-codex` installs it when it is missing
```

## Start the two agents

Put the Lean sources in `src/` of a folder of their own. From that folder, in two terminals:

```bash
readback-claude       # terminal 1, the writer
readback-codex        # terminal 2, the reader
```

| | `readback-claude` | `readback-codex` |
|---|---|---|
| Client | Claude Code | Codex |
| Model | the client's default | the client's default |
| Effort | `xhigh` | `max` |
| Skill | `readback` | `readback-reader` |

`make install` writes the two commands into `~/.local/bin` (it makes the folder, and says so when the folder is
not on your `PATH`).

What either command does, in order: it finds the workspace (the folder you are in or one above it, `ws/` in it,
or the workspace whose Lean sources you are standing in); if there is none it makes `ws/` beside `src/`, with a git repository, and takes as root the one module that
no other imports (it says so, and leaves the root open when there are several candidates); it checks that the
client's skill is installed; it starts the client in the workspace with the model, the effort and the first
prompt. A workspace whose mailbox is empty gets the prompt of a first session; later the same command sends the
prompt that continues.

```bash
readback-claude --print                       # make the workspace if there is none, show the command and the prompt, start no client
readback-claude ~/work/thing                  # another folder than the one you are in
readback-claude --root My.Main --name "My theorem"   # when the workspace is made
readback-codex --effort high                  # another effort, for this session only
```

The lasting values are in the workspace's `readback.json` under `agents`. To choose models for every new
workspace, write them in `~/.config/readback/agents.json` (or a file named by `READBACK_CONFIG`):

```json
{"writer": {"model": "your-claude-model"}, "reader": {"model": "your-codex-model", "effort": "max"}}
```

A workspace records these values when it is made; change them later in its `readback.json`. The commands do not change how the
clients ask for permissions: your own settings apply. They do not rebuild the tools of an older workspace: when
those differ from the skill's, the command says so and names `rb.py upgrade`.

## Effort levels

- **Writer (Claude Code): xhigh.** `readback-claude` passes `--effort xhigh`.
- **Reader (Codex): max.** `readback-codex` passes `-c model_reasoning_effort="max"`.

The reader's level matters most: a dossier with a wrong reading costs the writer a whole note. The writer's level
matters for the notes, which are long, careful texts.

## A workspace by hand

The start commands do this for you; by hand it is:

```bash
python3 skills/readback/scripts/rb.py init ~/work/tiny-readback \
        --artifact "$PWD/examples/tiny-lean" --root Tiny.Main --name "Tiny sums"
cd ~/work/tiny-readback && git init
```

Expect a line that begins `census: 7 modules, 104 lines, 16 declarations (3 def, 1 example, 12 theorem); sorry: 0;
axiom declarations: 0; cone of Tiny.Main: 5 modules` and a line that begins `units: 5 proposed`.

With the start commands the same example is `readback-claude --root Tiny.Main --name "Tiny sums"` in a folder
that holds the example as `src/`. Without `--root` the command finds two modules that no other imports
(`Tiny.Main`, `Tiny.Scratch`), sets no root, and tells the writer to settle it with you; then
`python3 tools/rb.py root Tiny.Main` in the workspace sets it and makes census, unit proposal and status again.

The workspace holds `CLAUDE.md` (for the writer), `AGENTS.md` (for the reader), `exchange/` (the mailbox),
`reading/` (the reader's), `notes/` and `book/` (the writer's), `tools/rb.py` (the same tool for both).

For an artifact on a code host, add `--url 'https://github.com/OWNER/REPO/blob/{commit}/{path}#L{a}-L{b}'`
(`{path}` is the file's path in its repository; `{file}` is its path inside the artifact folder): every
Lean name in a note then links to its lines.

## The first test: two fresh agents on the example

`readback-claude` and `readback-codex` send prompts of this kind. To do it by hand, open two terminals in the
workspace.

**Terminal 1, the writer** — `claude --effort xhigh`, then:

> Use the readback skill. This is a Readback workspace for the Lean artifact "Tiny sums". Read CLAUDE.md, tell me
> what the census says about the artifact, and ask the reader through the mailbox for the ledger of units and
> then for the dossier of the unit that proves Gauss's sum. Keep a watch on your inbox.

**Terminal 2, the reader** — Codex at its highest effort, then:

> Use the readback-reader skill. Read AGENTS.md and exchange/PROTOCOL.md. You are the reader, your name is astra.
> Check your inbox with `python3 tools/rb.py mail --as astra inbox` and do what is asked, one hand-off at a time.

What should happen, and what to look at:

| Step | Where to look | Passes when |
|---|---|---|
| the reader writes the ledger | `reading/ledger/units.json` | 5 units, titles in mathematical words |
| the reader hands over a dossier | `reading/units/<id>/` | `python3 tools/rb.py check <id>` exits 0 |
| the writer answers | `exchange/to-astra/` | a table of what was verified, with commands |
| the writer writes a note | `notes/<slug>/<slug>.pdf` | `python3 tools/rb.py note <slug>` reports no problem |
| the map turns green | `STATUS.md`, `map/MAP.md` | the unit is "note and structured proofs" |

Then ask the writer:

> Go on with the remaining units in the order of the map until nothing is grey, then assemble the book with
> `rb.py book` and write its summary.

Compare the result for unit 3 with `examples/tiny-sample/` in this repository. The questions worth your judgment:
are the statements complete and in standard language; would you sign the proofs; does the note say honestly
what was read and what was taken for granted; did either agent accept a claim of the other without checking it?

## Three more prompts to try

1. *Opening an unknown artifact:* "Here is a Lean project at PATH. Use readback to tell me what it actually
   proves, how big it is, and how you would read it. Do not start reading yet."
2. *A failing dossier:* change one `lean` quotation in a proof file by hand, then ask the writer to review the
   dossier. It should refuse it, naming the proof file and the step; the lines are in `check.json`.
3. *Honest scale:* "How far are we from having read everything the root theorem uses?" The answer should come
   from `STATUS.md` and the ledger, with numbers, not from an impression.

## Updating and removing

`git pull && make install` updates the writer's skill and the two start commands; `readback-codex` updates the
reader's skill when it starts. A workspace keeps the tools it was made with: inside it,
`python3 ~/.claude/skills/readback/scripts/rb.py upgrade` takes the skill's tools, and `upgrade --instructions`
also writes `CLAUDE.md`, `AGENTS.md` and the protocol again. Never copy single files in by hand: the tools belong
together. `make uninstall` removes both skills and the two commands.
