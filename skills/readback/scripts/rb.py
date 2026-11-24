#!/usr/bin/env python3
"""readback: from a compiled Lean artifact to a map, structured proofs, notes and a book.

    python3 rb.py start writer|reader [FOLDER]   # find or make the workspace and start the agent's client (also: readback-claude, readback-codex)
    python3 rb.py init WORKSPACE --artifact PATH [--root MODULE] [--name NAME] [--url PATTERN]
    python3 rb.py root [MODULE]          # show the root module, or set it and make census, units and status again
    python3 rb.py census                 # read the Lean files: modules, declarations, imports, the cone of the root
    python3 rb.py units                  # propose units (chapters) from the census
    python3 rb.py mail --as NAME inbox | send ... | archive | status | wait | watch [SECONDS] | stop
    python3 rb.py ledger                 # check the reader's ledger of units against the census
    python3 rb.py check UNIT [--lean-ranges]     # check a dossier (statements, structured proofs) against the Lean source
    python3 rb.py note SLUG [--new TITLE] [--unit ID] [--refresh]    # build a note and its checks
    python3 rb.py status                 # STATUS.md and map/MAP.md: what is read, what is not
    python3 rb.py site [--out DIR]       # the reading site: map, units, structured proofs, source, each note's PDF beside its Lean text
    python3 rb.py book                   # assemble the notes into one PDF (experimental)
    python3 rb.py upgrade                # from the installed skill, inside an older workspace: take the skill's tools
    python3 rb.py leakscan [PATH] --patterns FILE    # FILE: one regular expression per line, # for a comment

Every command except `init` and `start` is run inside a workspace (a directory with readback.json, or below one).
Standard library only. Notes need LuaLaTeX with latexmk, the book pdfLaTeX, the pictures of a note's pages on the
site poppler; everything else needs Python 3.9 or later.
"""
from __future__ import annotations

import argparse
import signal
import atexit
import collections
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import signature as sig
import signature_gate as sgate
from proof_steps import validate_proof
from source_ranges import SourceFile, checked_ranges, delimiter, digest, module_path, parsed_ranges, tokens, whole_quote

VERSION = "0.9.0"
HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"

KINDS = "theorem|lemma|def|abbrev|instance|structure|class|inductive|opaque|axiom|example"
MODS = r"(?:(?:private|protected|noncomputable|unsafe|partial|nonrec|public|scoped|local)\s+)*"
NAME = r"(?:«[^»\n]*»|[^\s:({\[⦃|.«]+)(?:\.(?:«[^»\n]*»|[^\s:({\[⦃|.«]+))*"
DECL = re.compile(r"^(?P<attr>(?:@\[[^\]]*\]\s*)*)(?P<mods>" + MODS + r")(?P<kind>class\s+inductive|" + KINDS + r")\b[ \t]*"
                  r"(?:\((?:priority|name)\b[^)]*\)[ \t]*)*(?P<name>" + NAME + r")?")
# `open Nat in theorem …`, `set_option maxRecDepth 600 in theorem …`: a command prefix on the declaration's own line
PREFIX = re.compile(r"^(?:(?:open|set_option|omit|include|variable|universe|local|scoped)\b[^\n]*?\bin[ \t]+)+")
TOP = re.compile(r"^(?:@\[|/--|/-!|/-|--|private |protected |noncomputable |unsafe |partial |nonrec |public |scoped |local |theorem |"
                 r"lemma |def |abbrev |structure |class |inductive |opaque |axiom |instance\b|example\b|namespace |end\b|"
                 r"section\b|variable |open |universe |attribute |set_option |omit |include |alias |export |import |mutual\b|macro |syntax |"
                 r"notation |infix|prefix|postfix|elab |initialize |deriving instance |#)")
IMPORT = re.compile(r"^(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?(\S+)")
TOKEN = re.compile(r"[A-Za-z_][\w.'!?₀-₉]*")


# ------------------------------------------------------------------------------------------------ workspace
def find_ws(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        if (d / "readback.json").exists():
            return d
    sys.exit("readback: no readback.json here or above; run `rb.py init` first, or cd into a workspace")


def cfg_of(ws: Path) -> dict:
    return json.loads((ws / "readback.json").read_text(encoding="utf-8"))


def src_of(ws: Path, cfg: dict) -> Path:
    p = Path(cfg["artifact"]["path"]).expanduser()
    return p if p.is_absolute() else (ws / p).resolve()


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def jload(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as exc:               # written by the other agent, or by hand: never a traceback
        print(f"readback: {path} is not valid JSON ({str(exc)[:70]}); it is treated as missing", file=sys.stderr)
        return default


def dossier_digest(U: Path) -> str:
    """One hash over a unit's dossier and its proof files: what a check record was made of."""
    h = hashlib.sha256()
    for f in [U / "unit.json", *sorted((U / "proofs").glob("*.json"))] if (U / "proofs").is_dir() else [U / "unit.json"]:
        if f.is_file():
            h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def agents_of(cfg: dict) -> dict:
    """The two agents of a workspace, with the defaults for whatever an older readback.json does not say."""
    have = cfg.get("agents") or {}
    return {role: {**CLIENTS[role], "name": {"writer": "fable", "reader": "astra"}[role], **(have.get(role) or {})} for role in ("writer", "reader")}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


# ------------------------------------------------------------------------------------------------ init
def git_pin(art: Path) -> tuple:
    """The commit of the repository that holds the artifact, whether its files there are changed, and the path of
    the artifact inside the repository (with a final slash, or empty). All None when it is in no repository."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(art), *args], capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""
    commit = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return None, None, None
    return commit, bool(git("status", "--porcelain", "--", ".")), git("rev-parse", "--show-prefix")


TOOLS = ("rb.py", "source_ranges.py", "proof_steps.py", "signature.py", "signature_gate.py", "SourceRanges.lean", "site_pages.py")
# The two agents: which client runs each, with which model and effort. A model of None means the client's own
# default model. Your own defaults for new workspaces go in ~/.config/readback/agents.json (or the file named by
# READBACK_CONFIG), e.g. {"writer": {"model": "..."}, "reader": {"model": "..."}}. A workspace records its own values
# in readback.json (agents.writer, agents.reader); `rb.py start` reads them from there, so change them there.
CLIENTS = {"writer": {"client": "claude", "model": None, "effort": "xhigh", "skill": "readback"},
           "reader": {"client": "codex", "model": None, "effort": "max", "skill": "readback-reader"}}


def user_defaults() -> dict:
    """CLIENTS with the user's own defaults (model, effort) laid over them."""
    f = os.environ.get("READBACK_CONFIG") or str(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "readback" / "agents.json")
    try:
        mine = json.loads(Path(f).expanduser().read_text(encoding="utf-8")) if f else {}
    except (OSError, ValueError):
        mine = {}
    return {role: {**CLIENTS[role], **{k: v for k, v in (mine.get(role) or {}).items() if k in ("model", "effort")}}
            for role in CLIENTS}


INSTRUCTIONS = ("CLAUDE.md", "AGENTS.md", "exchange/PROTOCOL.md")   # made from the templates; the records below them belong to the agents


def workspace_texts(cfg: dict, only: tuple = ()) -> dict:
    """The files a workspace starts with, from the templates of this skill."""
    sub = {"<<NAME>>": cfg["name"], "<<WRITER>>": agents_of(cfg)["writer"]["name"], "<<READER>>": agents_of(cfg)["reader"]["name"],
           "<<DATE>>": str(cfg.get("created", now()))[:10], "<<ROOT>>": cfg["artifact"].get("root_module") or "(not set)", "<<VERSION>>": VERSION}
    out = {}
    for src, dst in (("CLAUDE.md", "CLAUDE.md"), ("AGENTS.md", "AGENTS.md"), ("PROTOCOL.md", "exchange/PROTOCOL.md"), ("JOURNAL.md", "JOURNAL.md"),
                     ("PLAN.md", "PLAN.md"), ("MEMORY.md", "MEMORY.md"), ("gitignore", ".gitignore")):
        if only and dst not in only:
            continue
        text = (ASSETS / "workspace" / src).read_text(encoding="utf-8")
        for k, v in sub.items():
            text = text.replace(k, v)
        out[dst] = text
    return out


def carry_tools(ws: Path) -> list[str]:
    """Copy the tools of this skill into a workspace; returns the files that were new or different."""
    changed = []
    pairs = [(HERE / n, ws / "tools" / n) for n in TOOLS]
    pairs += [(f, ws / "tools" / d / f.relative_to(ASSETS / d)) for d in ("note", "site", "repair") for f in sorted((ASSETS / d).rglob("*")) if f.is_file()]
    refs = HERE.parent / "references"                          # the contracts and the method, where both agents can read them
    pairs += [(f, ws / "tools" / "references" / f.name) for f in sorted(refs.glob("*.md"))] if refs.is_dir() else []
    for src, dst in pairs:
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed.append(str(dst.relative_to(ws)))
    return changed


def cmd_upgrade(a) -> int:
    """Bring the tools of a workspace up to this skill. Run the skill's own rb.py from inside the workspace."""
    ws = find_ws()
    if HERE == (ws / "tools").resolve():
        sys.exit("readback: run the rb.py of the installed skill for this, e.g. python3 ~/.claude/skills/readback/scripts/rb.py upgrade")
    cfg = cfg_of(ws)
    changed = carry_tools(ws)
    gi = ws / ".gitignore"                                     # lines the template has gained since the workspace was made
    have = gi.read_text(encoding="utf-8").split("\n") if gi.exists() else []
    new = [ln for ln in (ASSETS / "workspace" / "gitignore").read_text(encoding="utf-8").split("\n") if ln and ln not in have]
    if new:
        gi.write_text("\n".join([ln for ln in have if ln] + new) + "\n", encoding="utf-8")
        changed.append(".gitignore (" + ", ".join(new) + ")")
    old, cfg["version"] = cfg.get("version"), VERSION
    jdump(ws / "readback.json", cfg)
    stale = [dst for dst, text in workspace_texts(cfg, INSTRUCTIONS).items() if not (ws / dst).exists() or (ws / dst).read_text(encoding="utf-8") != text]
    if a.instructions:
        for dst in stale:
            f = ws / dst
            if f.exists():
                f.replace(f.with_name(f.name + ".old"))        # what was there is kept beside it
            f.write_text(workspace_texts(cfg, (dst,))[dst], encoding="utf-8")
            changed.append(dst)
        stale = []
    print(f"upgrade: tools of {ws.name} are now those of readback {VERSION} (the workspace was made with {old}); "
          + (f"{len(changed)} files changed: " + ", ".join(changed) if changed else "no file differed"))
    if stale:
        print(f"  NOTE: {', '.join(stale)} are the instructions of the older version. `upgrade --instructions` writes the present ones "
              "and keeps the old beside them as *.old; tell both agents to read them again.")
    if str(old or "0") < "0.6.0":
        print("  NOTE: since 0.6.0 the signature rule is enforced (tools/references/notes.md, contracts.md). Run `rb.py census` once. "
              "A dossier now accounts for every argument of every member (`binders`; `rb.py signature UNIT` prints them), and a note "
              "needs a `notation` for each definition with explicit arguments and the words that state each argument and hypothesis; "
              "a note also needs the `setting` and `conventions` environments of the present template. Until then `check` and `note` "
              "report problems, and the unit falls back in the status. That is intended: read each statement again.")
    return 0


def cmd_init(a) -> int:
    ws = Path(a.workspace).expanduser().resolve()
    art = Path(a.artifact).expanduser().resolve()
    if not art.is_dir():
        sys.exit(f"readback: the artifact {art} is not a directory")
    if (ws / "readback.json").exists():
        sys.exit(f"readback: {ws} is already a workspace")
    if ws == art or art in ws.parents:
        sys.exit(f"readback: the workspace {ws} would lie inside the artifact {art}, and its own files would be read as Lean sources. Put it beside the artifact.")
    if ws.exists() and any(ws.iterdir()):
        sys.exit(f"readback: {ws} exists and is not empty; a workspace is made in a new or empty folder, so that nothing of yours is overwritten")
    made_here = not ws.exists()
    try:
        return init_workspace(a, ws, art)
    except BaseException:
        if made_here:
            shutil.rmtree(ws, ignore_errors=True)              # nothing half-made stays behind
        raise


def init_workspace(a, ws: Path, art: Path) -> int:
    commit, dirty, prefix = git_pin(art)
    rel = os.path.relpath(art, ws)
    tc = next((d / "lean-toolchain" for d in [art, *art.parents][:4] if (d / "lean-toolchain").is_file()), None)
    cfg = {"schema": "readback/workspace/1", "version": VERSION, "name": a.name or art.name, "created": now(),
           "artifact": {"path": rel if not rel.startswith("../../..") else str(art), "root_module": a.root,
                        "commit": commit, "uncommitted_changes": dirty,      # the commit is the HEAD of the enclosing repository
                        "prefix": prefix,                                    # where the artifact lies in that repository
                        "toolchain": tc.read_text(encoding="utf-8").strip() if tc else None, "url": a.url},
           "agents": {role: dict(name=name, **{k: user_defaults()[role][k] for k in ("client", "model", "effort")})
                      for role, name in (("writer", a.writer), ("reader", a.reader))},
           "leaf_bound": 8}
    for d in ("exchange/to-" + a.writer, "exchange/to-" + a.reader, "exchange/archive", "reading/ledger", "reading/units",
              "reading/lean", "notes", "map", "book", "tools"):
        (ws / d).mkdir(parents=True, exist_ok=True)
        if d != "tools":
            (ws / d / ".gitkeep").touch()                      # so that a clone has the directory
    (ws / "exchange" / "ledger.jsonl").touch()
    jdump(ws / "readback.json", cfg)
    for dst, text in workspace_texts(cfg).items():
        (ws / dst).write_text(text, encoding="utf-8")
    carry_tools(ws)
    print(f"readback {VERSION}: workspace {ws}\n  artifact {art}" + (f" at {commit[:10]}" if commit else " (not a git repository: no commit to pin)"))
    census(ws)
    units(ws)
    cmd_status(None, ws)
    print("next: the reader reads AGENTS.md, the writer reads CLAUDE.md; both run tools/rb.py from the workspace")
    return 0


# ------------------------------------------------------------------------------------------------ census
def plain_name(written: str) -> str:
    """The name as Lean shows it: no universe parameters, and guillemets only where they are needed."""
    parts = re.findall(r"«[^»\n]*»|[^.«]+", written)
    return ".".join(x[1:-1] if x.startswith("«") and re.fullmatch(r"[A-Za-z_][\w'!?]*", x[1:-1]) else x for x in parts)


def read_module(path: Path, module: str, source=None) -> dict:
    """The declarations of one Lean file, read from its text: a line whose first token is a declaration keyword
    (after attributes, modifiers, or a command prefix ending in `in`) starts one, at any indentation. Comments and
    strings are not code. This is a reading of the text, not Lean's parser: `check --lean-ranges` asks Lean."""
    source = source or SourceFile(path.read_bytes())
    lines = source.text.replace("\r\n", "\n").split("\n")
    imports, decls, scopes = [], [], []                  # scopes: (namespace, component) | (section, name or None) | (mutual, None)
    code_lines, first, sorry_rows = set(), {}, []
    for t in tokens(source.text):
        row, col = source.position(t.a)
        first.setdefault(row, col)                       # the column of the first token of each line
        code_lines.update(range(row, source.position(t.b - 1)[0] + 1))
        if t.word == "sorry":
            sorry_rows.append(row)
    variables, waiting = sig.Variables(), ""             # the section variables in force; a command prefix on a line of its own

    def stop_of(i: int, indent: int) -> int:
        """A command that starts in line i+1 runs to the next command at its indentation or further out."""
        b = i + 1
        while b < len(lines):
            raw = lines[b]
            if b + 1 in first and len(raw) - len(raw.lstrip()) <= indent and TOP.match(raw.lstrip()):
                break
            b += 1
        while b > i + 1 and b not in code_lines:
            b -= 1
        return b

    for i, ln in enumerate(lines):
        if i + 1 not in first:
            continue                                     # blank, or a comment only
        lead = first[i + 1] - 1                          # what stands before the first token is white space or a comment
        text = ln[lead:]
        m = IMPORT.match(text)
        if m:
            imports.append(m.group(1).replace("«", "").replace("»", ""))   # `import A.«2d»` names the file A/2d.lean
            continue
        m = re.match(r"namespace\s+(\S+)", text)
        if m:
            scopes += [("namespace", c) for c in m.group(1).split(".")]
            continue
        m = re.match(r"(?:(?:noncomputable|public)\s+)*section\b[ \t]*([^\s-]\S*)?", text)
        if m:
            scopes.append(("section", m.group(1)))
            continue
        if re.match(r"mutual\b", text):
            scopes.append(("mutual", None))
            continue
        m = re.match(r"end\b[ \t]*([^\s-]\S*)?", text)
        if m:
            if m.group(1):                               # `end A.B` closes B, then A
                for comp in reversed(m.group(1).split(".")):
                    if scopes and scopes[-1][0] in ("namespace", "section") and scopes[-1][1] == comp:
                        scopes.pop()
            elif scopes and scopes[-1][1] is None:
                scopes.pop()
            variables.close(len(scopes))
            continue
        pre = PREFIX.match(text)
        off = pre.end() if pre else 0
        indent = len(ln) - len(ln.lstrip())
        m = None if pre else re.match(r"(variable|include|omit)\b", text)
        if m:                                            # section variables: arguments of the declarations that follow
            whole = "\n".join(lines[i:stop_of(i, indent)])[lead + m.end():]
            if re.search(r"\bin\s*$", whole):            # `omit [C] in` on a line of its own: for the next declaration only
                waiting += text[:m.end()] + whole + " "
            else:
                getattr(variables, {"variable": "declare"}.get(m.group(1), m.group(1)))(whole, len(scopes))
            continue
        m = DECL.match(text[off:])
        if not m:
            continue
        b = stop_of(i, indent)                           # the block runs to the next command at this indentation or further out
        block = lines[i:b]
        name = m.group("name")
        ns = [c for k, c in scopes if k == "namespace"]
        if name and name.startswith("_root_."):
            full = plain_name(name[7:])
        elif name:
            full = plain_name(".".join(ns + [name]))     # Lean puts the namespace in front, also of a dotted name
        else:
            full = None
        col = (lead + off + m.start("name") + 1) if name else 1
        kind = "class" if m.group("kind").startswith("class") else m.group("kind")
        body = "\n".join(block)
        mark = delimiter(body)
        se = body.count("\n", 0, mark.a) if mark else len(block) - 1
        if mark and mark.word == "|":
            se = max(0, se - 1)
        value_col = mark.b - body.rfind("\n", 0, mark.b) if mark and mark.word == ":=" else None
        extra, forced, left = sig.prefix(waiting + (pre.group(0) if pre else ""))
        waiting = ""
        args = sig.binders(kind, body, lead + off + (m.end("name") if name else m.end()), mark.a if mark else len(body), variables.now(),
                           forced=set(forced) | {w for w, _ in variables.forced}, omitted=left + [w for w, _ in variables.left], extra=extra)
        decls.append({"id": f"{module}:{i + 1}:{col}", "kind": kind, "name": full, "written": name,
                      "private": "private" in m.group("mods"), "lines": [i + 1, b], "statement_lines": [i + 1, i + 1 + se],
                      "value_col": value_col, "binders": args["binders"] if args["read"] else None,
                      "sha256": digest(body + "\n"), "sorry": sum(1 for r in sorry_rows if i + 1 <= r <= b),
                      "doc": "/--" in ln[:lead] or bool(i and lines[i - 1].rstrip().endswith("-/"))})
    return {"module": module, "lines": len(lines) - (1 if lines and lines[-1] == "" else 0), "imports": imports,
            "file_sha256": source.sha256, "declarations": decls}


UNREADABLE: dict = {}                                       # Lean files of the last scan that are not valid text


def scan_modules(src: Path) -> dict:
    """Every Lean file under the artifact (hidden folders such as .lake aside), read as a module."""
    mods = {}
    UNREADABLE.clear()
    for f in sorted(src.rglob("*.lean")):
        rel = f.relative_to(src)
        if any(part.startswith(".") for part in rel.parts):
            continue
        module = ".".join(rel.with_suffix("").parts)
        try:
            mods[module] = dict(read_module(f, module), file=rel.as_posix(), bytes=f.stat().st_size)
        except (UnicodeDecodeError, ValueError) as exc:        # not UTF-8: said in the census, never a crash
            UNREADABLE[rel.as_posix()] = str(exc)[:80]
    return mods


def census(ws: Path) -> dict:
    cfg = cfg_of(ws)
    src = src_of(ws, cfg)
    mods = scan_modules(src)
    # the import cone of the root
    root = cfg["artifact"].get("root_module")
    cone = []
    if root and root in mods:
        seen, todo = {root}, [root]
        while todo:
            for imp in mods[todo.pop()]["imports"]:
                if imp in mods and imp not in seen:
                    seen.add(imp)
                    todo.append(imp)
        cone = sorted(seen)
    # which declarations of the artifact does each declaration mention? (by name; a kernel export is better)
    # A name can only mean a declaration of the same module or of a module that this one imports, directly or
    # through others: the same short name elsewhere is not a use.
    below = imports_closure(mods) if len(mods) <= 20000 else None
    last = collections.defaultdict(list)
    for m in mods.values():
        for d in m["declarations"]:
            if d["name"]:
                last[d["name"].split(".")[-1]].append((m["module"], d))
    for m in mods.values():
        text = (src / m["file"]).read_text(encoding="utf-8").split("\n")
        visible = below[m["module"]] if below is not None else None
        for d in m["declarations"]:
            a, b = d["lines"]
            toks = {t.rstrip(".") for t in TOKEN.findall("\n".join(text[a - 1:b]))}
            uses = set()
            for t in toks:
                for home, c in last.get(t.split(".")[-1], []):
                    if c["id"] == d["id"] or not (c["name"] == t or c["name"].endswith("." + t)):
                        continue
                    if visible is not None and home not in visible:
                        continue
                    uses.add(c["id"])
            d["uses"] = sorted(uses, key=lambda x: (x.rsplit(":", 2)[0], int(x.rsplit(":", 2)[1]), int(x.rsplit(":", 2)[2])))
    kinds = collections.Counter(d["kind"] for m in mods.values() for d in m["declarations"])
    in_cone = [mods[m] for m in cone]
    out = {"schema": "readback/census/1", "made": now(),
           "artifact": dict({k: v for k, v in cfg["artifact"].items() if k != "path"}, digest=artifact_digest(mods.values())), "root": root,
           "totals": {"modules": len(mods), "lines": sum(m["lines"] for m in mods.values()),
                      "declarations": sum(kinds.values()), "by_kind": dict(sorted(kinds.items())),
                      "sorry": sum(d["sorry"] for m in mods.values() for d in m["declarations"]),
                      "axioms": [d["name"] for m in mods.values() for d in m["declarations"] if d["kind"] == "axiom"],
                      "modules_in_cone": len(cone), "lines_in_cone": sum(m["lines"] for m in in_cone),
                      "declarations_in_cone": sum(len(m["declarations"]) for m in in_cone)},
           "uses_basis": ("names, within what each module imports (syntactic)" if below is not None else "names (syntactic)")
                         + "; replace by a kernel export when the reader has one",
           "cone": cone, "unreadable": sorted(UNREADABLE), "modules": list(mods.values())}
    commit, dirty, prefix = git_pin(src)
    if (commit, dirty) != (cfg["artifact"].get("commit"), cfg["artifact"].get("uncommitted_changes")):
        print(f"census: the artifact's pin changed: commit {str(cfg['artifact'].get('commit'))[:10]} -> {str(commit)[:10]}, "
              f"uncommitted changes {cfg['artifact'].get('uncommitted_changes')} -> {dirty}")
        cfg["artifact"].update(commit=commit, uncommitted_changes=dirty, prefix=prefix)
        jdump(ws / "readback.json", cfg)
        out["artifact"].update(commit=commit, uncommitted_changes=dirty, prefix=prefix)
    old = jload(ws / "reading" / "census.json")
    if isinstance(old, dict) and old.get("artifact", {}).get("digest") not in (None, out["artifact"]["digest"]):
        key = lambda d, m: d["name"] or d["id"]                # noqa: E731  an anonymous declaration is known by its place
        was = {key(d, m): d for m in old["modules"] for d in m["declarations"]}
        is_ = {key(d, m): d for m in mods.values() for d in m["declarations"]}
        diff = {"schema": "readback/census-changes/1", "from": old.get("made"), "to": out["made"],
                "changed": sorted(k for k in was if k in is_ and was[k]["sha256"] != is_[k]["sha256"]),
                "moved": sorted(k for k in was if k in is_ and was[k]["sha256"] == is_[k]["sha256"] and was[k]["id"] != is_[k]["id"]),
                "gone": sorted(k for k in was if k not in is_), "new": sorted(k for k in is_ if k not in was)}
        jdump(ws / "reading" / "census-changes.json", diff)
        print(f"census: since the census of {old.get('made')}: {len(diff['changed'])} declarations changed, {len(diff['moved'])} only moved, "
              f"{len(diff['gone'])} gone, {len(diff['new'])} new (reading/census-changes.json). Check every dossier again and read each change under a note.")
    jdump(ws / "reading" / "census.json", out)
    t = out["totals"]
    print(f"census: {t['modules']} modules, {t['lines']:,} lines, {t['declarations']:,} declarations "
          f"({', '.join(f'{v} {k}' for k, v in t['by_kind'].items())}); sorry: {t['sorry']}; axiom declarations: {len(t['axioms'])}; "
          + (f"cone of {root}: {len(cone)} modules, {t['lines_in_cone']:,} lines, {t['declarations_in_cone']:,} declarations"
             if cone else "no root module set (artifact.root_module)"))
    if UNREADABLE:
        print(f"  WARNING: {len(UNREADABLE)} Lean files are not valid UTF-8 text and were not read: {', '.join(sorted(UNREADABLE)[:5])}")
    return out


def imports_closure(mods: dict) -> dict:
    """For every module, itself and all modules it imports, directly or through others. Without recursion."""
    below: dict = {}
    for start in mods:
        if start in below:
            continue
        stack, path = [(start, iter(mods[start]["imports"]))], {start}
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if nxt in mods and nxt not in below and nxt not in path:
                    path.add(nxt)
                    stack.append((nxt, iter(mods[nxt]["imports"])))
                    break
            else:
                below[node] = {node}.union(*(below[i] for i in mods[node]["imports"] if i in below))
                path.discard(node)
                stack.pop()
    return below


def artifact_digest(modules) -> str:
    """One hash for all Lean files of the artifact: their paths and their hashes."""
    return hashlib.sha256("\n".join(f"{m['file']}\t{m['file_sha256']}" for m in sorted(modules, key=lambda m: m["file"])).encode("utf-8")).hexdigest()


def artifact_changes(ws: Path, cen: dict) -> str:
    """Empty when the Lean files are those of the census; otherwise one sentence saying what differs. Files are
    hashed again; above 256 MB only their sizes are compared."""
    src = src_of(ws, cfg_of(ws))
    known = {m["file"]: m for m in cen["modules"]}
    now_files = {f.relative_to(src).as_posix(): f for f in src.rglob("*.lean")
                 if not any(part.startswith(".") for part in f.relative_to(src).parts)} if src.is_dir() else {}
    full = sum(m.get("bytes", 0) for m in known.values()) <= 256 * 2 ** 20
    changed = []
    for rel in sorted(set(known) & set(now_files)):
        m, f = known[rel], now_files[rel]
        if ("bytes" in m and m["bytes"] != f.stat().st_size) or (full and hashlib.sha256(f.read_bytes()).hexdigest() != m["file_sha256"]):
            changed.append(rel)
    gone, new = sorted(set(known) - set(now_files)), sorted(set(now_files) - set(known))
    if not (changed or gone or new):
        return ""
    first = (changed + gone + new)[:3]
    return (f"the Lean sources are not those of the census of {cen.get('made')}: {len(changed)} files changed, {len(gone)} gone, {len(new)} new "
            f"({', '.join(first)}{', …' if len(changed) + len(gone) + len(new) > 3 else ''}). Run `rb.py census`, check the dossiers again, and tell the other agent")


def decl_index(c: dict) -> dict:
    return {d["id"]: dict(d, module=m["module"], file=m["file"]) for m in c["modules"] for d in m["declarations"]}


# ------------------------------------------------------------------------------------------------ units
def units(ws: Path) -> dict:
    c = jload(ws / "reading" / "census.json") or census(ws)
    mods = {m["module"]: m for m in c["modules"]}
    inside = c["cone"] or sorted(mods)
    by_dir = len(inside) > 80
    group = (lambda m: ".".join(m.split(".")[:-1]) or m) if by_dir else (lambda m: m)
    members = collections.defaultdict(list)
    for m in inside:
        members[group(m)].append(m)
    # reach from the declarations of the root module, along the uses found by name
    idx = decl_index(c)
    reached = set()
    todo = [d["id"] for d in mods[c["root"]]["declarations"]] if c.get("root") in mods else []
    while todo:
        x = todo.pop()
        if x not in reached:
            reached.add(x)
            todo.extend(idx[x]["uses"])
    edges = collections.defaultdict(set)
    for g, ms in members.items():
        for m in ms:
            for imp in mods[m]["imports"]:
                if imp in mods and imp in inside and group(imp) != g:
                    edges[g].add(group(imp))
    where = {d["id"]: group(m) for m in inside for d in mods[m]["declarations"]}
    takes = collections.defaultdict(set)                       # unit -> units whose declarations it names
    for m in inside:
        for d in mods[m]["declarations"]:
            for x in d["uses"]:
                if x in where and where[x] != group(m):
                    takes[group(m)].add(where[x])
    order, mark = [], set()
    for g0 in sorted(members):                         # imports first; a stack, so that a long chain of imports is no trouble
        stack = [(g0, iter(sorted(edges[g0])))]
        if g0 in mark:
            continue
        mark.add(g0)
        while stack:
            g, it = stack[-1]
            for h in it:
                if h not in mark:
                    mark.add(h)
                    stack.append((h, iter(sorted(edges[h]))))
                    break
            else:
                order.append(g)
                stack.pop()
    used_by = collections.defaultdict(set)
    for g, hs in takes.items():
        for h in hs:
            used_by[h].add(g)
    uid = {g: str(i + 1) for i, g in enumerate(order)}
    out = {"schema": "readback/units/1", "made": now(), "root": c.get("root"), "units": [],
           "basis": "units: modules; imports and consumers: declarations that name each other (syntactic); order: module imports"}
    for g in order:
        ds = [d for m in members[g] for d in mods[m]["declarations"]]
        out["units"].append({"id": uid[g], "title": g, "modules": sorted(members[g]), "members": [d["id"] for d in ds],
                             "reached": sum(1 for d in ds if d["id"] in reached),
                             "proof_lines": sum(d["lines"][1] - d["statement_lines"][1] for d in ds if d["kind"] in ("theorem", "lemma")),
                             "imports": sorted((uid[h] for h in takes[g]), key=int),
                             "consumers": sorted((uid[k] for k in used_by[g]), key=int),
                             "module_imports": sorted((uid[h] for h in edges[g]), key=int)})
    jdump(ws / "reading" / "units.proposal.json", out)
    print(f"units: {len(out['units'])} proposed (one per {'directory' if by_dir else 'module'}); "
          f"{len(reached)} declarations reached from the root by name; the reader writes reading/ledger/units.json")
    if c.get("root") in mods and not mods[c["root"]]["declarations"]:
        print(f"  note: the root module {c['root']} declares nothing itself (a file of imports), so nothing is reached from it; "
              "set artifact.root_module in readback.json to the module of the final theorem and run `rb.py units` again")
    return out


def ledger(ws: Path) -> dict:
    return jload(ws / "reading" / "ledger" / "units.json") or jload(ws / "reading" / "units.proposal.json") or units(ws)


def set_root(ws: Path, module: str) -> None:
    cfg = cfg_of(ws)
    mods = scan_modules(src_of(ws, cfg))
    if module not in mods:
        near = [m for m in mods if module.split(".")[-1].lower() in m.lower()][:6]
        sys.exit(f"readback: the artifact has no module {module}" + (f"; did you mean {', '.join(near)}?" if near else ""))
    cfg["artifact"]["root_module"] = module
    jdump(ws / "readback.json", cfg)
    census(ws)
    units(ws)
    cmd_status(None, ws)


def cmd_root(a) -> int:
    """Show the root module, or set it and make the census, the unit proposal and the status again."""
    ws = find_ws()
    cfg = cfg_of(ws)
    if not a.module:
        root, tops = guess_root({"modules": list(scan_modules(src_of(ws, cfg)).values())})
        print(f"root module: {cfg['artifact'].get('root_module') or 'not set'}; modules that no other imports: {', '.join(tops) or 'none'}")
        return 0
    old = cfg["artifact"].get("root_module")
    set_root(ws, a.module)
    print(f"root: {old or 'not set'} -> {a.module}. The census, the unit proposal and the status are made again."
          + (" The reader's ledger and the dossiers were made for the old root: tell the reader, and run `rb.py ledger`."
             if (ws / "reading" / "ledger" / "units.json").exists() else ""))
    return 0


def cmd_ledger(a) -> int:
    """Check the reader's ledger of units against the census: writes reading/ledger/check.json."""
    ws = find_ws()
    path = ws / "reading" / "ledger" / "units.json"
    L = jload(path)
    if not isinstance(L, dict) or not isinstance(L.get("units"), list):
        sys.exit(f"readback: no ledger with a list `units` at {path}")
    cen = jload(ws / "reading" / "census.json") or census(ws)
    idx, cone = decl_index(cen), set(cen.get("cone") or [m["module"] for m in cen["modules"]])
    in_cone = {i for i, d in idx.items() if d["module"] in cone}
    problems, notes, owner, ids = [], [], {}, []
    if L.get("root") != cen.get("root"):
        problems.append(f"the ledger's root is {L.get('root')!r}, the workspace's is {cen.get('root')!r}")
    for u in L["units"]:
        if not isinstance(u, dict) or not isinstance(u.get("id"), str) or not isinstance(u.get("members"), list):
            problems.append(f"a unit needs an `id` that is a string and a list `members`: {str(u)[:80]}")
            continue
        uid = u["id"]
        ids.append(uid)
        if not str(u.get("title") or "").strip():
            problems.append(f"unit {uid} has no title")
        if not u["members"]:
            problems.append(f"unit {uid} has no members")
        for m in u["members"]:
            if m not in idx:
                problems.append(f"unit {uid}: member {m!r} is not a declaration of the census")
            elif m in owner:
                problems.append(f"{idx[m].get('name') or m} is a member of units {owner[m]} and {uid}")
            else:
                owner[m] = uid
        lines = sum(idx[m]["lines"][1] - idx[m]["statement_lines"][1] for m in u["members"] if m in idx and idx[m]["kind"] in ("theorem", "lemma"))
        if isinstance(u.get("proof_lines"), int) and u["proof_lines"] != lines:
            problems.append(f"unit {uid}: proof_lines is {u['proof_lines']}, the census gives {lines}")
    for uid in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"the id {uid} is used by {ids.count(uid)} units")
    units = [u for u in L["units"] if isinstance(u, dict) and isinstance(u.get("id"), str) and isinstance(u.get("members"), list)]
    for u in units:
        for field, other in (("imports", "consumers"), ("consumers", "imports")):
            for v in u.get(field) or []:
                peer = next((w for w in units if w["id"] == str(v)), None)
                if str(v) == u["id"]:
                    problems.append(f"unit {u['id']} lists itself in {field}")
                elif peer is None:
                    problems.append(f"unit {u['id']}: {field} names the unknown unit {v!r}")
                elif u["id"] not in [str(x) for x in peer.get(other) or []]:
                    problems.append(f"unit {u['id']} has {v} in {field}, but unit {v} does not have {u['id']} in {other}")
    # what the census, by names, sees between the units; a ledger on a kernel basis may rightly differ
    by_names = collections.defaultdict(set)
    for m, uid in owner.items():
        for x in idx[m].get("uses", []):
            if x in owner and owner[x] != uid:
                by_names[uid].add(owner[x])
    differ = []
    for u in units:
        mine, theirs = {str(x) for x in u.get("imports") or []}, by_names[u["id"]]
        if mine != theirs:
            differ.append({"unit": u["id"], "only_in_the_ledger": sorted(mine - theirs), "only_by_names": sorted(theirs - mine)})
    if differ:
        notes.append(f"{len(differ)} units import other units than the census finds by names (basis of the ledger: {L.get('basis', 'not stated')}); "
                     "names are a weaker witness than a kernel export, so this is to be looked at, not a fault by itself")
    imp = {u["id"]: [str(x) for x in u.get("imports") or [] if str(x) in ids] for u in units}
    state, loop = {}, []

    def walk(i, trail):                                      # one cycle among the units, if there is one
        if loop or state.get(i) == 2:
            return
        if state.get(i) == 1:
            loop.extend(trail[trail.index(i):] + [i])
            return
        state[i] = 1
        for j in imp.get(i, []):
            walk(j, trail + [i])
        state[i] = 2
    for u in units:
        walk(u["id"], [])
    if loop:
        notes.append("units use each other in a circle (" + " → ".join(loop) + "): there is no order in which each comes after what it takes for granted")
    left = sorted(in_cone - set(owner), key=lambda i: (idx[i]["file"], idx[i]["lines"][0]))
    if left:
        kinds = collections.Counter(idx[i]["kind"] for i in left)
        notes.append(f"{len(left)} declarations of the cone are in no unit ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))}): "
                     + ", ".join(idx[i].get("name") or i for i in left[:8]) + (", …" if len(left) > 8 else "") + "; the ledger should say why")
    outside = [m for m in owner if m not in in_cone]
    if outside:
        notes.append(f"{len(outside)} members lie outside the cone of the root")
    modules = {m["module"] for m in cen["modules"]}
    plain = [u["id"] for u in units if str(u.get("title")) in modules or re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+", str(u.get("title") or ""))]
    if plain:
        notes.append(f"{len(plain)} titles are module names (units {', '.join(plain[:10])}): a title says in mathematical words what the unit holds")
    jdump(path.parent / "check.json", {"schema": "readback/ledger-check/1", "checked": now(), "basis": L.get("basis"),
                                        "counts": {"units": len(units), "members": len(owner), "declarations_in_the_cone": len(in_cone),
                                                   "in_no_unit": len(left), "members_outside_the_cone": len(outside)},
                                        "imports_that_differ_from_names": differ, "notes": notes, "problems": problems})
    print(f"ledger: {len(units)} units, {len(owner)} members, {len(in_cone)} declarations in the cone, {len(left)} of them in no unit; "
          f"{len(problems)} problems, {len(notes)} things to look at (reading/ledger/check.json)")
    for x in problems:
        print("  PROBLEM:", x)
    for x in notes:
        print("  LOOK:", x)
    return 1 if problems else 0


# ------------------------------------------------------------------------------------------------ mailbox
MSG = re.compile(r"^msg-(\d{4,})-[a-z0-9][a-z0-9-]*$")


def mid(name: str) -> str:
    """msg-0007 of msg-0007-some-slug."""
    return re.match(r"msg-\d+", name).group(0)
TYPES = ("handoff", "request", "result", "question", "ack", "update")


def mail_head(folder: Path) -> dict:
    try:
        text = (folder / "MESSAGE.md").read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out = {}
    for ln in (m.group(1).split("\n") if m else []):
        k, sep, v = ln.partition(":")
        if sep:
            out[k.strip()] = v.strip()
    return out


def mail_list(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir() and MSG.match(p.name)) if folder.is_dir() else []


def watcher_of(ws: Path, me: str) -> int | None:
    """The process that watches or waits on the inbox of `me` in this workspace, if it is still alive."""
    f = ws / "exchange" / f".watching-{me}"
    try:
        pid = int(f.read_text(encoding="utf-8").split()[0])
        os.kill(pid, 0)                                        # does it exist?
    except (OSError, ValueError, IndexError):
        f.unlink(missing_ok=True)
        return None
    return pid if pid != os.getpid() else None


def claim_watch(ws: Path, me: str, replace: bool) -> None:
    """One watch or wait per name and workspace. It records its process number in the workspace, which is how it is
    stopped: by number, never by a pattern, because the watch of every workspace has the same command line."""
    old = watcher_of(ws, me)
    if old and not replace:
        sys.exit(f"readback: a watch or wait of {me} is already running in this workspace (process {old}). "
                 f"Stop it with `rb.py mail --as {me} stop`, or start this one with --replace.")
    if old:
        os.kill(old, signal.SIGTERM)
    f = ws / "exchange" / f".watching-{me}"
    f.write_text(f"{os.getpid()}\n", encoding="utf-8")
    atexit.register(lambda: f.unlink(missing_ok=True) if f.exists() and f.read_text(encoding="utf-8").split()[:1] == [str(os.getpid())] else None)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # so that the record is removed when it is stopped


def cmd_mail(a) -> int:
    ws = find_ws()
    cfg = cfg_of(ws)
    names = [agents_of(cfg)["writer"]["name"], agents_of(cfg)["reader"]["name"]]
    if a.as_ not in names:
        sys.exit(f"readback: --as must be one of {names}")
    me, peer = a.as_, next(n for n in names if n != a.as_)
    ex = ws / "exchange"
    out, inn, arch, led = ex / f"to-{peer}", ex / f"to-{me}", ex / "archive", ex / "ledger.jsonl"
    ids = lambda s: re.findall(r"msg-\d{4,}", s or "")                     # noqa: E731
    mine = mail_list(out) + mail_list(arch / me)          # an archived message keeps its number and what it answered
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    answered = {i for m in mine for i in ids(mail_head(m).get("re"))}
    seen_file = ex / f".seen-{me}"                             # the closing messages (type ack) that `inbox` has shown me
    shown = set(seen_file.read_text(encoding="utf-8").split()) if seen_file.exists() else set()
    is_ack = lambda m: mail_head(m).get("type") == "ack"                   # noqa: E731
    def log(folder, box):
        h = mail_head(folder)
        with led.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": mid(folder.name), "dir": box, "from": h.get("from", "?"), "type": h.get("type", "?"),
                                "re": h.get("re", "-"), "date": h.get("date", "?"), "subject": h.get("subject", "")},
                               ensure_ascii=False) + "\n")
    if a.action == "inbox":
        waiting = [m for m in mail_list(inn) if mid(m.name) not in answered and not is_ack(m)]
        closing = [m for m in mail_list(inn) if is_ack(m) and m.name not in shown and mid(m.name) not in answered]
        for m in waiting + closing:
            h = mail_head(m)
            files = sorted(str(p.relative_to(m)) for p in m.rglob("*") if p.is_file() and p.name != "MESSAGE.md")
            print(f"{m.name}  [{h.get('type', '?')}, {h.get('date', '?')}, re {h.get('re', '-')}]  {h.get('subject', '')}"
                  + ("  (closes a thread: read it; it needs no answer and will not be listed again)" if m in closing else ""))
            print(f"    {m / 'MESSAGE.md'}" + (f"\n    payload: {', '.join(files)}" if files else ""))
        if closing:
            seen_file.write_text("\n".join(sorted(shown | {m.name for m in closing})) + "\n", encoding="utf-8")
        if not waiting and not closing:
            print(f"inbox of {me}: nothing waits")
    elif a.action == "send":
        if a.type not in TYPES or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.slug or ""):
            sys.exit("readback: --type must be one of " + ", ".join(TYPES) + "; --slug is lower-case letters, digits, hyphens")
        if not a.body:
            sys.exit("readback: send needs --body FILE (or --body - to read the text from standard input)")
        if a.body != "-" and not Path(a.body).is_file():
            sys.exit(f"readback: the body file {a.body} does not exist")
        body = sys.stdin.read() if a.body == "-" else Path(a.body).read_text(encoding="utf-8")
        a.subject = " ".join((a.subject or "").split())       # one line: a line break would write into the header
        wrong = [x for x in re.split(r"[,\s]+", (a.re or "-").strip()) if x and x != "-" and not re.fullmatch(r"msg-\d{4,}", x)]
        if wrong:
            sys.exit(f"readback: --re takes message numbers like msg-0003, separated by commas; not {', '.join(wrong)}")
        files = [Path(x) for x in a.payload or []]
        bad = [str(x) for x in files if not x.is_file()] + [str(x) for x in files if x.name == "MESSAGE.md"]
        twice = sorted({x.name for x in files if [y.name for y in files].count(x.name) > 1})
        if bad or twice:
            sys.exit("readback: a payload is a file, not a folder, not named MESSAGE.md, and no two payloads share a name: " + ", ".join(bad + twice))
        theirs = {mid(m.name) for m in mail_list(inn) + mail_list(arch / peer)}
        unknown = [i for i in ids(a.re) if i not in theirs]
        if unknown:                                           # numbers count per sender: --re names messages of the peer
            sys.exit(f"readback: --re names {', '.join(unknown)}, and {peer} has sent no such message; "
                     f"--re is for the messages of {peer} that this one answers (your own messages are not named there)")
        gate = ex / f".sending-{me}"                           # one send of mine at a time, so that two never take one number
        for _ in range(200):
            try:
                gate.mkdir()
                break
            except FileExistsError:
                if time.time() - gate.stat().st_mtime > 60:     # left by a send that died
                    shutil.rmtree(gate, ignore_errors=True)
                time.sleep(0.05)
        else:
            sys.exit("readback: another send of yours is still running; try again")
        atexit.register(lambda: shutil.rmtree(gate, ignore_errors=True))
        mine = mail_list(out) + mail_list(arch / me)
        n = 1 + max([int(MSG.match(m.name).group(1)) for m in mine] or [0])
        name = f"msg-{n:04d}-{a.slug}"
        tmp = out / f".tmp-{os.getpid()}-{name}"
        tmp.mkdir(parents=True)
        (tmp / "MESSAGE.md").write_text(f"---\nfrom: {me}\ndate: {stamp}\ntype: {a.type}\nre: {', '.join(ids(a.re)) or '-'}\n"
                                        f"subject: {a.subject}\n---\n\n{body.strip()}\n", encoding="utf-8")
        for p in a.payload or []:
            shutil.copy2(p, tmp / Path(p).name)
        os.rename(tmp, out / name)                      # the message appears at once
        log(out / name, f"to-{peer}")
        print(f"sent {out / name}")
    elif a.action == "archive":
        named = {i for m in mail_list(inn) for i in ids(mail_head(m).get("re"))}
        named |= {i for m in mail_list(arch / peer) for i in ids(mail_head(m).get("re"))}
        peer_seen = set((ex / f".seen-{peer}").read_text(encoding="utf-8").split()) if (ex / f".seen-{peer}").exists() else set()
        moved = [m for m in mail_list(out) if mid(m.name) in named or (is_ack(m) and m.name in peer_seen)]   # answered, or a closing message that was read
        for m in moved:
            (arch / me).mkdir(parents=True, exist_ok=True)
            os.rename(m, arch / me / m.name)
            print(f"archived {m.name}")
        if not moved:
            print("archive: no message of mine has been answered since the last run")
    elif a.action == "status":
        print(f"to-{peer} (mine, waiting for an answer): " + (", ".join(m.name for m in mail_list(out)) or "none"))
        print(f"to-{me} (the peer's, waiting for mine):  " + (", ".join(m.name for m in mail_list(inn) if mid(m.name) not in answered and not is_ack(m)) or "none"))
        unread = [m.name for m in mail_list(inn) if is_ack(m) and m.name not in shown]
        if unread:
            print(f"to-{me} (closing messages not read yet): " + ", ".join(unread))
    elif a.action == "stop":                                  # the watcher of this name in this workspace, and no other process
        pid = watcher_of(ws, me)
        if not pid:
            print(f"stop: no watch or wait of {me} is running in this workspace")
            return 0
        os.kill(pid, signal.SIGTERM)
        (ws / "exchange" / f".watching-{me}").unlink(missing_ok=True)
        print(f"stop: stopped the watch of {me} in this workspace (process {pid})")
    elif a.action == "wait":                                  # like watch, but it ends: for a client that wakes when a command exits
        claim_watch(ws, me, a.replace)
        seen = {m.name for m in mail_list(inn)} if a.skip_present else {m.name for m in mail_list(inn) if mid(m.name) in answered or m.name in shown}
        until = time.time() + a.timeout if a.timeout else None
        while True:
            new = [m for m in mail_list(inn) if m.name not in seen]
            for m in new:
                h = mail_head(m)
                print(f"PEER MESSAGE: {m.name} [{h.get('type', '?')}] {h.get('subject', '')}", flush=True)
            if new:
                return 0
            if until and time.time() >= until:
                print(f"wait: no new message for {me} in {a.timeout} s", flush=True)
                return 2
            time.sleep(a.seconds)
    elif a.action == "watch":
        claim_watch(ws, me, a.replace)
        seen = {m.name for m in mail_list(inn)} if a.skip_present else {m.name for m in mail_list(inn) if mid(m.name) in answered or m.name in shown}
        print(f"watch: inbox of {me}, every {a.seconds} s; a line PEER MESSAGE for each new message; to end it: rb.py mail --as {me} stop", flush=True)
        while True:
            for m in mail_list(inn):
                if m.name not in seen:
                    seen.add(m.name)
                    h = mail_head(m)
                    print(f"PEER MESSAGE: {m.name} [{h.get('type', '?')}] {h.get('subject', '')}", flush=True)
            time.sleep(a.seconds)
    return 0


TRIAGE = ("argument", "assembly", "computation", "automation", "one-step", "restatement", "alias")


# ------------------------------------------------------------------------------------------------ fresh reads
class Source:
    """The Lean files as they are now (the census may be older)."""
    def __init__(self, ws: Path):
        self.ws, self.cfg = ws, cfg_of(ws)
        self.src = src_of(ws, self.cfg)
        self.mods, self.files = {}, {}

    def file(self, file: str) -> SourceFile:
        if file not in self.files:
            self.files[file] = SourceFile(module_path(self.src, file).read_bytes())
        return self.files[file]

    def module(self, file: str) -> dict:
        if file not in self.mods:
            source = self.file(file)
            self.mods[file] = read_module(self.src / file, ".".join(Path(file).with_suffix("").parts), source)
        return self.mods[file]

    def decl(self, file: str, did: str | None = None, name: str | None = None) -> dict | None:
        try:
            m = self.module(file)
        except (OSError, ValueError):
            return None
        decls = (m or {}).get("declarations", [])
        if did:
            return next((d for d in decls if d["id"] == did), None)
        matches = [d for d in decls if name and d["name"] == name]
        return matches[0] if len(matches) == 1 else None

    def lines(self, file: str, a: int, b: int) -> str:
        source = self.file(file)
        start, stop = source.line_range([a, b])
        return whole_quote(source.text[start:stop])

    def url(self, file: str, a: int, b: int) -> str | None:
        pat = self.cfg["artifact"].get("url")
        art = self.cfg["artifact"]                          # {file} is relative to the artifact, {path} to its repository
        return pat.replace("{path}", (art.get("prefix") or "") + file).replace("{file}", file).replace("{a}", str(a)).replace("{b}", str(b)).replace(
            "{commit}", art.get("commit") or "main") if pat else None


# ------------------------------------------------------------------------------------------------ check a dossier
def binder_problems(m: dict, d: dict) -> list:
    """The signature rule in a dossier: every argument of the declaration is accounted for, in Lean's order."""
    src, mine = d.get("binders"), m.get("binders")
    want = "; ".join(sig.show(b) for b in src) if src else "no argument" if src == [] else "(not readable from the text)"
    lean = ("If Lean's own signature differs (an argument Lean binds by itself, a section variable that this reading of the text "
            "judges wrongly), set binders_basis to \"lean\" and quote what `#check @Name` prints in binders_lean")
    if mine is None and src == []:
        return []
    if not isinstance(mine, list):
        return [f"no account of its arguments: `binders` needs one entry per argument, in Lean's order, each with name, kind and "
                f"reads (what the argument is, in words). The text gives: {want}"]
    bad = [str(i + 1) for i, b in enumerate(mine) if not (isinstance(b, dict) and b.get("kind") in sig.KINDS
                                                         and isinstance(b.get("reads"), str) and b["reads"].strip())]
    if bad:
        return [f"argument {', '.join(bad)} of its `binders` lacks a kind ({', '.join(sig.KINDS)}) or its reading in words (reads)"]
    if m.get("binders_basis") == "lean":
        out = [] if str(m.get("binders_lean") or "").strip() else ["binders_basis is \"lean\" and binders_lean, what Lean printed, is empty"]
        if not sig.subsequence([b for b in src or [] if b["from"] != "variable"], mine):
            out.append(f"its `binders` leave out an argument that the declaration itself writes. The text gives: {want}")
        return out
    if src is None:
        return ["its arguments cannot be read from the text: ask Lean (`#check @Name`), list them in `binders`, set binders_basis "
                "to \"lean\" and quote Lean's answer in binders_lean"]
    if not sig.matches(mine, src):
        maybe = sum(1 for b in src if b.get("maybe"))
        return [f"its `binders` are not the arguments of the declaration ({len(mine)} listed). The text gives {len(src)}: {want}"
                + (f" ({maybe} of them instance variables that a definition takes only when its term uses them: those may be left out)" if maybe else "")
                + f". {lean}"]
    return []


def cmd_signature(a) -> int:
    """The arguments of declarations, as the text gives them: for a unit, or for one declaration by name or id."""
    ws = find_ws()
    cen = jload(ws / "reading" / "census.json") or census(ws)
    idx = decl_index(cen)
    S = Source(ws)
    unit = next((u for u in ledger(ws)["units"] if str(u["id"]) == a.what), None)
    ids = unit["members"] if unit else [k for k, d in idx.items() if a.what in (k, d.get("name")) or (d.get("name") or "").endswith("." + a.what)]
    if not ids:
        sys.exit(f"readback: {a.what} is no unit of the ledger and no declaration of the census")
    out = {}
    for k in ids:
        d0 = idx.get(k)
        d = d0 and (S.decl(d0["file"], did=k) or S.decl(d0["file"], name=d0["name"]))
        if d:
            out[k] = {"name": d["name"], "kind": d["kind"], "binders_read_from": "the text; `#check @Name` is Lean's own answer",
                      "binders": None if d["binders"] is None else [dict(b, reads="") for b in d["binders"]]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_check(a) -> int:
    ws = find_ws()
    S = Source(ws)
    bound = S.cfg.get("leaf_bound", 8)
    U = ws / "reading" / "units" / str(a.unit)
    unit = jload(U / "unit.json")
    if not isinstance(unit, dict):
        sys.exit(f"readback: no dossier at {U / 'unit.json'} (the file is missing, or is not a JSON object)")
    problems, members = [], {}
    for key in ("members", "imports", "out_of_scope", "ambient_inputs"):
        if unit.get(key) is not None and not isinstance(unit[key], list):
            problems.append(f"`{key}` must be a list")
            unit[key] = []
    for key in ("title", "summary"):
        if unit.get(key) is not None and not isinstance(unit[key], str):
            problems.append(f"`{key}` must be text")
            unit[key] = ""
    stat = collections.Counter()
    proof_checks, source_checks, bodies, native = [], {}, {}, {}
    failed_modules = set()
    names = collections.defaultdict(set)
    pin = S.cfg["artifact"].get("commit")
    if unit.get("commit") and unit["commit"] != pin:
        problems.append(f"edition mismatch: dossier {unit['commit']}, workspace {pin}")
    if unit.get("schema") != "readback/unit/1":
        problems.append(f"the dossier's schema is {unit.get('schema')!r}, not 'readback/unit/1'")
    if str(unit.get("unit")) != str(a.unit):
        problems.append(f"the dossier says it is unit {unit.get('unit')!r}; its folder is unit {a.unit}")
    for key in ("title", "summary"):
        if not str(unit.get(key) or "").strip():
            problems.append(f"the dossier has no {key}")
    for x in unit.get("out_of_scope") or []:
        if not (isinstance(x, dict) and isinstance(x.get("id"), str) and str(x.get("reason") or "").strip()):
            problems.append(f"out_of_scope: every entry needs an id and a reason: {str(x)[:60]}")
    for m in unit.get("members", []):
        stat["members"] += 1
        if not isinstance(m, dict) or not all(isinstance(m.get(key), str) for key in ("id", "file")):
            problems.append("member requires a declaration id and source file")
            continue
        mid, file = m["id"], m["file"]
        try:
            if mid in members:
                raise ValueError("duplicate member")
            src = S.file(file)
            d = S.decl(file, did=mid)
            if d is None:
                raise ValueError(f"no such declaration in {file}")
            if (d["lines"] != m.get("lines") or (m.get("name") and m["name"] != d["name"]) or
                    (m.get("kind") and m["kind"] != d["kind"])):
                raise ValueError(f"source has {d['name']} at lines {d['lines']}")
            if m.get("sha256") is not None and m["sha256"] != d["sha256"]:
                raise ValueError("declaration hash differs from source")
            if m.get("file_sha256") is not None and m["file_sha256"] != src.sha256:
                raise ValueError("file hash differs from source")
            if isinstance(m.get("statement_lean"), str):          # optional: the statement as the reader quotes it
                quoted, there = " ".join(m["statement_lean"].split()), " ".join(S.lines(file, *d["statement_lines"]).split())
                rest = there[len(quoted):].lstrip()
                if not there.startswith(quoted) or (rest and not rest.startswith((":=", "where", "|", "by"))):
                    raise ValueError("statement_lean is not the text of the statement lines")
            if not (isinstance(m.get("text"), str) and m["text"].strip()):
                problems.append(f"member {d.get('name') or mid}: no statement in words (text)")
            if not isinstance(m.get("sha256"), str):
                problems.append(f"member {d.get('name') or mid}: no sha256, so the dossier is not bound to the text it describes")
            if m.get("triage") is not None and m["triage"] not in TRIAGE:
                problems.append(f"member {d.get('name') or mid}: triage {m['triage']!r} is none of {', '.join(TRIAGE)}")
            wrong = binder_problems(m, d)                  # the signature rule: no argument and no hypothesis is left out
            problems.extend(f"member {d.get('name') or mid}: {x}" for x in wrong)
            stat["arguments"] += len(m["binders"]) if isinstance(m.get("binders"), list) else 0
            stat["arguments_accounted_for"] += 0 if wrong or not isinstance(m.get("binders"), list) else len(m["binders"])
            stat["members_with_arguments_from_lean"] += m.get("binders_basis") == "lean"
            members[mid] = m, d
            for alias in (mid, d.get("name")):
                if alias:
                    names[alias].add(mid)
            recorded = m.get("source_ranges")
            if a.lean_ranges:
                if file in failed_modules:
                    continue
                if file not in native:
                    try:
                        native[file] = parsed_ranges(S.src, file, src, HERE / "SourceRanges.lean")
                    except (OSError, ValueError) as exc:
                        failed_modules.add(file)
                        problems.append(f"{file}: {exc}")
                        continue
                if mid not in native[file]:
                    raise ValueError("no supported Lean syntax range for this declaration")
                fresh = native[file][mid]
                if recorded is not None and recorded != fresh:
                    raise ValueError("recorded source ranges disagree with Lean syntax")
                records, basis = fresh, "lean-parser"
            else:
                records, basis = recorded, "recorded-source-ranges"
            if records is not None:
                parts = checked_ranges(src, d, records)
                source_checks[mid] = {"basis": basis, "file": file, "file_sha256": src.sha256, "source_ranges": records}
                bodies[mid] = parts["value"]
            else:
                aa, bb = src.line_range(d["lines"])
                mark = delimiter(src.text[aa:bb])
                if mark:
                    bodies[mid] = (aa + (mark.b if mark.word == ":=" else mark.a), bb)
                source_checks[mid] = {"basis": "line-census", "file": file, "file_sha256": src.sha256}
            stat["statements_at_their_lines"] += 1
        except (OSError, ValueError) as exc:
            problems.append(f"member {mid}: {exc}")
    led = next((u for u in ledger(ws)["units"] if str(u["id"]) == str(a.unit)), None)
    if led:
        out = {x.get("id") if isinstance(x, dict) else x for x in unit.get("out_of_scope") or [] if isinstance(x, (dict, str))}
        missing = [x for x in led["members"] if x not in members and x not in out]
        if missing:
            problems.append(f"{len(missing)} members of the unit are neither treated nor listed as out of scope: " + ", ".join(missing[:6]))
        stat["foreign_rows"] = len([x for x in members if x not in led["members"]])
    for imp in unit.get("imports", []):
        stat["imports"] += 1
        if not isinstance(imp, dict) or any(imp.get(k) is not None and not isinstance(imp[k], str)
                                            for k in ("id", "name", "file")):
            problems.append("invalid import id, name or file")
            continue
        if not (isinstance(imp.get("text"), str) and imp["text"].strip()):
            problems.append(f"import {imp.get('name') or imp.get('id')}: no statement in words (text)")
        if not imp.get("file"):
            problems.append(f"import {imp.get('name') or imp.get('id')}: no file of the artifact, so it cannot be checked; "
                            "a fact of Lean's own library belongs in `ambient_inputs`, and in a step's `ambient_uses`")
        elif "lean" not in imp:
            problems.append(f"import {imp.get('name') or imp.get('id')}: not quoted (lean, lines)")
        try:
            key, name, file = imp.get("id"), imp.get("name"), imp.get("file")
            if file:
                src = S.file(file)
                d = S.decl(file, did=key) if key else S.decl(file, name=name)
                if d is None or (name and d["name"] != name):
                    raise ValueError("import does not resolve in its cited file")
                key, name = d["id"], d["name"]
                if "lean" in imp:
                    x, y = src.line_range(imp.get("lines"))
                    lo, hi = src.line_range(d["lines"])
                    if x < lo or y > hi or not isinstance(imp["lean"], str) or whole_quote(imp["lean"]) != whole_quote(src.text[x:y]):
                        raise ValueError("import quotation differs from its declaration and range")
                    stat["imports_quoted_at_their_lines"] += 1
            if not (key or name):
                raise ValueError("import must have a name or id")
            for alias in (key, name):
                if alias:
                    names[alias].add(key or name)
        except (OSError, ValueError) as exc:
            problems.append(f"import {imp.get('name') or imp.get('id')}: {exc}")
    declarations = {alias for alias, ids in names.items() if len(ids) == 1}
    proved = set()
    for pf in sorted((U / "proofs").glob("*.json")):
        try:
            proof = jload(pf)
        except (OSError, ValueError) as exc:
            problems.append(f"{pf.name}: {exc}")
            continue
        if not isinstance(proof, dict) or not isinstance(proof.get("declaration"), str):
            problems.append(f"{pf.name}: proof requires a declaration id")
            continue
        mid = proof["declaration"]
        if mid not in members or mid in proved:
            problems.append(f"{pf.name}: unknown or already treated declaration {mid}")
            continue
        proved.add(mid)
        stat["proofs"] += 1
        if members[mid][0]["file"] in failed_modules:
            continue
        if not bodies.get(mid):
            problems.append(f"{pf.name}: no checked value range for {mid}")
            continue
        m, d = members[mid]
        report, counts = validate_proof(S.file(m["file"]), d, bodies[mid], proof, declarations, bound)
        report["file"] = pf.name
        proof_checks.append(report)
        problems.extend(f"{pf.name}: {p}" for p in report["problems"])
        longest = max(stat["longest_leaf"], counts.pop("longest_leaf", 0))
        stat.update(counts)
        stat["longest_leaf"] = longest
    for mid, (m, d) in members.items():
        after = d["lines"][1] - d["statement_lines"][1]        # the contract: more than one line after the statement
        if d["kind"] in ("theorem", "lemma") and after > 1 and mid not in proved and m.get("triage") not in TRIAGE[2:]:
            problems.append(f"member {m.get('name') or mid}: a proof of {after} lines has no structured proof"
                            + (f" (its triage, {m['triage']}, does not exempt it: only {', '.join(TRIAGE[2:])} do)" if m.get("triage") else " and no triage"))
    if a.lean_ranges and failed_modules:                       # Lean was not there to ask: that says nothing about the dossier
        why = next((x for x in problems if any(x.startswith(f + ":") for f in failed_modules)), "")
        print(f"check: Lean could not give the ranges of {len(failed_modules)} files. Nothing is recorded and check.json is unchanged.\n{why[:3000]}\n"
              "If the artifact is not built yet, that is the owner's decision (a build runs its code). If Lean reports an error in the file itself, "
              "the artifact does not compile as it stands: tell the owner. Without --lean-ranges the check runs on the text alone.")
        return 2
    res = {"schema": "readback/check/1", "unit": str(a.unit), "checked": now(), "commit": S.cfg["artifact"].get("commit"),
           "dossier_sha256": dossier_digest(U),               # the status compares it: a dossier edited after its check is not checked
           "leaf_bound": bound, "counts": dict(stat), "sources": source_checks, "proof_checks": proof_checks, "problems": problems}
    jdump(U / "check.json", res)
    print(f"check: unit {a.unit}: {stat['statements_at_their_lines']} of {stat['members']} statements at their lines; "
          f"{stat['proofs']} structured proofs, {stat['steps']} steps, {stat['leaves']} leaves "
          f"(longest {stat['longest_leaf']} lines, bound {bound}), {stat['steps_quoting_their_lines']} steps quote their lines; "
          f"typed facts in the source: {stat['typed_facts_in_source']} of {stat['typed_steps']}; "
          f"imports quoted: {stat['imports_quoted_at_their_lines']} of {stat['imports']}; "
          f"arguments accounted for: {stat['arguments_accounted_for']} of {stat['arguments']}"
          + (f" ({stat['members_with_arguments_from_lean']} members by Lean's own signature, which this check cannot confirm)"
             if stat["members_with_arguments_from_lean"] else ""))
    for p in problems:
        print("  PROBLEM:", p)
    print("  the program check passes; the mathematics is read when the note is written" if not problems else f"  {len(problems)} problems")
    return 1 if problems else 0


# ------------------------------------------------------------------------------------------------ notes
GREEK = ("alpha|beta|gamma|delta|eps|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|"
         "sigma|tau|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Phi|Psi|Omega|ell")


def _letters(tex: str) -> tuple[set[str], set[str]]:
    """Greek macros and Latin letters that occur in the mathematics of a piece of LaTeX."""
    chunks = re.findall(r"\$([^$]+)\$", tex)
    chunks += re.findall(r"\\m\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}", tex)
    chunks += re.findall(r"\\\[(.*?)\\\]", tex, re.S)
    chunks += re.findall(r"\\begin\{align\*\}(.*?)\\end\{align\*\}", tex, re.S)
    greek, latin = set(), set()
    for c in chunks:
        greek |= set(re.findall(r"\\(" + GREEK + r")(?![a-zA-Z])", c))
        c = re.sub(r"\\(?:text|mathrm|operatorname|emph|textbf|textup|leanfont|kw|mbox|quad|qquad|pmod)\s*\{[^{}]*\}", "", c)
        c = re.sub(r"\\(?:begin|end)\{[A-Za-z*]+\}", "", c)      # the name of an environment is not a formula
        latin |= set(re.findall(r"[A-Za-z]", re.sub(r"\\[a-zA-Z]+", "", c)))
    return greek, latin


def check_notation(tex: str) -> list[str]:
    """Letters used in formulas of the text that the notation list does not mention."""
    body = re.sub(r"(?m)^%.*$", "", tex[tex.index(r"\begin{document}"):])
    if r"\head{Notation}" not in body:
        return ["(no \\head{Notation} section)"]
    cut = body.index(r"\head{Notation}")
    tg, tl = _letters(body[:cut])
    ng, nl = _letters(body[cut:])
    return sorted(tg - ng) + sorted(tl - nl)


def tex_escape(s: str) -> str:
    table = {"\\": r"\textbackslash{}", "_": r"\_", "&": r"\&", "%": r"\%", "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}",
             "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}
    return "".join(table.get(ch, ch) for ch in s)


def lean_escape(s: str) -> str:
    rep = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "_": r"\_", "&": r"\&", "%": r"\%", "#": r"\#",
           "^": r"\textasciicircum{}", "~": r"\textasciitilde{}", "$": r"\$"}
    return "".join(rep.get(ch, ch) for ch in s)


def quote_tex(s: str) -> str:
    out = []
    for ln in s.split("\n"):
        ind = len(ln) - len(ln.lstrip(" "))
        out.append(r"\leanquoteline{%d}{%s}" % (ind, lean_escape(ln.lstrip(" "))))
    return "".join(out)


def statement_text(block: list[str], kind: str) -> str:
    text = "\n".join(block).rstrip()
    if kind in ("def", "abbrev", "structure", "class", "inductive", "opaque", "axiom"):
        return text
    mark = delimiter(text)
    return text[:mark.a].rstrip() if mark and mark.word == ":=" else text


DEFS = sgate.DEFS                                           # declarations that introduce a notion


def note_key(name: str, taken: set) -> str:
    k = re.sub(r"[^A-Za-z]", "", name.split(".")[-1]) or "decl"
    base, i = k, 2
    while k in taken:
        k, i = f"{base}{'abcdefghijklmnopqrstuvwxyz'[i - 2]}", i + 1
    taken.add(k)
    return k


def cmd_note(a) -> int:
    ws = find_ws()
    S = Source(ws)
    N = ws / "notes" / a.slug
    cen = jload(ws / "reading" / "census.json") or census(ws)
    idx = decl_index(cen)
    if a.new:
        if N.exists() and any(N.iterdir()):
            sys.exit(f"readback: {N} exists already and is not empty")
        decls, taken, ambient = [], set(), {}
        if a.unit:
            u = next((x for x in ledger(ws)["units"] if str(x["id"]) == str(a.unit)), None) or sys.exit(f"readback: no unit {a.unit}")
            D = jload(ws / "reading" / "units" / str(a.unit) / "unit.json") or {}
            aside = {x.get("id") if isinstance(x, dict) else x for x in D.get("out_of_scope") or []}
            for mid in u["members"]:
                d = idx.get(mid)
                if d is None:
                    print(f"  note: the ledger's member {mid} is no declaration of the census; left out (run `rb.py ledger`)")
                elif d["name"] and mid not in aside:
                    e = {"key": note_key(d["name"], taken), "name": d["name"], "id": mid}
                    lean = next((m.get("binders") for m in D.get("members") or [] if isinstance(m, dict) and m.get("id") == mid
                                 and m.get("binders_basis") == "lean"), None)
                    bs = lean if isinstance(lean, list) else d.get("binders") or []
                    ex = sig.explicit(bs) if d["kind"] in DEFS else []
                    if ex:                                   # to be written: the notation that shows every explicit argument
                        e["notation"] = {"macro": e["key"], "slots": [sig.key(b) for b in ex], "tex": "", "symbol": ""}
                    e["binders"] = {(b.get("name") or f"#{i}"): "" for i, b in enumerate(bs, 1) if b["kind"] == "explicit" and b not in ex}
                    for b in bs:
                        if b["kind"] != "explicit":
                            ambient.setdefault(sig.key(b), "")
                    decls.append(e)
        N.mkdir(parents=True, exist_ok=True)
        number = len([p for p in (ws / "notes").iterdir() if p.is_dir() and (p / "spec.json").exists()]) + 1
        jdump(N / "spec.json", {"schema": "readback/note/1", "title": a.new, "number": number, "unit": a.unit and str(a.unit),
                                "conventions": "c:conventions", "ambient": ambient,
                                "declarations": decls, "quoted": [], "lettered": [["Theorem A", "t:A"]], "outline": [],
                                "elsewhere": []})
        tpl = (ws / "tools" / "note" / "template.tex").read_text(encoding="utf-8")
        cs = "\n".join(r"\cs{%s}{§\ref{s:setting}}" % d["key"] for d in decls)
        ll = r"\sep ".join(r"\lean{%s}" % d["key"] for d in decls)
        for k, v in (("<<TITLE>>", a.new), ("<<NUMBER>>", str(number)), ("<<NAME>>", S.cfg["name"]), ("<<CS>>", cs), ("<<LEANLINE>>", ll)):
            tpl = tpl.replace(k, v)
        (N / f"{a.slug}.tex").write_text(tpl, encoding="utf-8")
        print(f"note: {N} created with {len(decls)} declarations; write {a.slug}.tex, then `rb.py note {a.slug}`")
        return 0
    spec = jload(N / "spec.json") or sys.exit(f"readback: no {N / 'spec.json'}; start with `rb.py note {a.slug} --new \"Title\"`")
    if a.rewrite:                                           # a replacement in the text that leaves macro definitions and comments alone
        pattern, template = a.rewrite
        f = N / f"{a.slug}.tex"
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            sys.exit(f"readback: the pattern is not a regular expression: {exc}")
        out, n, touched = [], 0, []
        for i, ln in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            cut = re.search(r"(?<!\\)%", ln)
            code, rest = (ln[:cut.start()], ln[cut.start():]) if cut else (ln, "")
            if re.match(r"\s*\\(?:(?:re)?newcommand|providecommand|def|DeclareMathOperator|newtheorem)\b", code):
                out.append(ln)                              # a definition is never rewritten: it would come to call itself
                continue
            fresh, k = rx.subn(template, code)
            if k:
                n += k
                touched.append(i)
            out.append(fresh + rest)
        if not n:
            print(f"note: the pattern occurs nowhere in {f.name} outside comments and macro definitions; nothing changed")
            return 1
        keep = f.with_name(f.name + ".before")
        k = 2
        while keep.exists():
            keep, k = f.with_name(f"{f.name}.before{k}"), k + 1
        shutil.copyfile(f, keep)
        f.write_text("\n".join(out), encoding="utf-8")
        print(f"note: {n} places rewritten in {len(touched)} lines of {f.name} (lines {', '.join(map(str, touched[:12]))}{', …' if len(touched) > 12 else ''}); "
              f"the text as it was is kept in {keep.name}. Comments and lines that define macros were left alone; a formula "
              "that runs over two lines is not found. Read the changed lines, then build the note.")
        return 0
    tex = (N / f"{a.slug}.tex").read_text(encoding="utf-8")
    by_name = {d["name"]: d for d in idx.values() if d["name"]}
    unit = jload(ws / "reading" / "units" / str(spec["unit"]) / "unit.json") if spec.get("unit") else None
    led = next((x for x in ledger(ws)["units"] if x["id"] == str(spec.get("unit"))), None)
    unit_ids = {m["id"] for m in unit["members"]} if unit else set(led["members"]) if led else set()
    problems, conc = [], {}
    for e in spec["declarations"]:
        d0 = idx.get(e.get("id")) or by_name.get(e.get("lean") or e["name"])
        d = d0 and (S.decl(d0["file"], did=d0["id"]) or S.decl(d0["file"], name=d0["name"]))
        if not d:
            problems.append(f"{e['key']}: the declaration {e.get('id') or e['name']} is not in the source")
            continue
        a0, b0 = d["lines"]
        block = S.lines(d0["file"], a0, b0).split("\n")
        mem = next((m for m in (unit or {}).get("members") or [] if isinstance(m, dict) and m.get("id") == d["id"]), {})
        lean = mem.get("binders") if mem.get("binders_basis") == "lean" and isinstance(mem.get("binders"), list) else None
        conc[e["key"]] = {"name": e["name"], "id": d["id"], "kind": d["kind"], "file": d0["file"], "lines": d["lines"],
                          "file_sha256": S.module(d0["file"])["file_sha256"], "statement": statement_text(block, d["kind"]),
                          "in_unit": d["id"] in unit_ids,
                          "binders": [{x: b.get(x) for x in ("name", "kind", "type")} for b in lean] if lean else d.get("binders"),
                          "binders_basis": "lean, by the dossier" if lean else "text"}
    shared = jload(ws / "notes" / "notation.json")           # one table for all notes of the workspace: how each Lean definition is written
    own = spec
    if isinstance(shared, dict):
        spec = sgate.with_shared(spec, shared, {k: v["name"] for k, v in conc.items()}, {k: v["kind"] for k, v in conc.items()})
    if a.account:                                           # an existing note: what the signature rule still needs, as places to fill in
        have = {e["key"] for e in spec["declarations"] if isinstance(e.get("notation"), dict)} - {e["key"] for e in own["declarations"] if isinstance(e.get("notation"), dict)}
        spec, todo = sgate.skeleton(spec, conc, tex)
        for e in spec["declarations"]:                      # what the shared table gives is not copied into the note's own file
            if e["key"] in have:
                e.pop("notation", None)
        if isinstance(shared, dict):
            for name in ("ambient", "letters", "words"):
                spec[name] = {k: v for k, v in spec[name].items() if k not in (shared.get(name) or {}) or (own.get(name) or {}).get(k)}
        jdump(N / "spec.json", spec)
        print(f"note: {a.slug}: spec.json now has a place for everything the signature rule needs (`notation`, `letters`, `words`, "
              f"`ambient`, `binders`; nothing that was there is changed). {len(todo)} things to do:")
        for x in todo:
            print("  TO DO:", x)
        print("  Then: write the notations and the words, bring the text to them (`note SLUG --rewrite` for a symbol that occurs "
              "often), build. The procedure is in tools/references/repair.md.")
        return 1 if todo else 0
    old = jload(N / "concordance.json")
    if old and not a.refresh:
        for k, v in conc.items():
            o = old.get("declarations", {}).get(k)
            if o and (o["lines"], o["statement"]) != (v["lines"], v["statement"]):
                problems.append(f"{k}: the source changed under the note (lines {o['lines']} -> {v['lines']}); read the change, then --refresh")
    if old and not a.refresh and any("binders" not in o for o in old.get("declarations", {}).values()):
        old = None                                          # a concordance from before the signature rule: write it again
    record = {"schema": "readback/concordance/1", "note": a.slug, "commit": S.cfg["artifact"].get("commit"), "declarations": conc}
    if a.refresh or not old:
        jdump(N / "concordance.json", record)
    # data.tex
    out = [r"% generated by rb.py note; do not edit", r"\newcommand{\ConcDecls}{%d}" % len(conc),
           r"\newcommand{\Pin}{%s}" % ((S.cfg["artifact"].get("commit") or "unpinned")[:8]),
           r"\newcommand{\PinText}{%s}" % (r"that of commit {\leanfont %s}" % S.cfg["artifact"]["commit"][:8] if S.cfg["artifact"].get("commit") else
                                           r"that of the files with digest {\leanfont %s} (the workspace pins no commit)" % str(cen.get("artifact", {}).get("digest", "unknown"))[:12]),
           r"\newcommand{\ArtifactName}{%s}" % tex_escape(S.cfg["name"])]
    rows = []
    for k, v in conc.items():
        url = S.url(v["file"], *v["lines"])
        shown = r"{\leanfont %s}" % tex_escape(v["name"]).replace(".", r".\allowbreak{}")
        link = r"\href{%s}{%s}" % (url.replace("%", r"\%").replace("#", r"\#"), shown) if url else shown
        out.append(r"\expandafter\newcommand\csname LN@%s\endcsname{%s}" % (k, link))
        if k in spec.get("quoted", []):
            out.append(r"\expandafter\newcommand\csname LQ@%s\endcsname{%s}" % (k, quote_tex(v["statement"])))
        rows.append(r"\crow{%s}{%s}{%s}{%d--%d}" % (k, link, tex_escape(Path(v["file"]).name), *v["lines"]))
    out.append(r"\newcommand{\ConcordanceRows}{%s}" % "\n".join(rows))
    triage = {m["id"]: m.get("triage") for m in (unit or {}).get("members") or [] if isinstance(m, dict) and m.get("id")}
    wrong, looks, macros, counted = sgate.gate(spec, conc, tex, triage)
    problems += wrong
    out += ["% the notations of the defined functions: one slot for each explicit argument of the Lean declaration"] + macros
    tried, missed = sgate.broken_copies(spec, conc, tex, triage) if not wrong else (0, [])
    problems += [f"the gate did not catch a copy of the note that breaks the rule on purpose: {x}" for x in missed]
    chk = jload(ws / "reading" / "units" / str(spec.get("unit")) / "check.json") if spec.get("unit") else None
    in_note = sum(1 for v in conc.values() if v["in_unit"])
    out += [r"\newcommand{\UnitMembers}{%d}" % len(unit_ids), r"\newcommand{\UnitInNote}{%d}" % in_note,
            r"\newcommand{\UnitProofs}{%d}" % (chk or {}).get("counts", {}).get("proofs", 0),
            r"\newcommand{\UnitSteps}{%d}" % (chk or {}).get("counts", {}).get("leaves", 0),        # leaf steps
            r"\newcommand{\UnitAllSteps}{%d}" % (chk or {}).get("counts", {}).get("steps", 0)]
    (N / "data.tex").write_text("\n".join(out) + "\n", encoding="utf-8")
    # checks on the text
    for k in conc:
        if r"\lean{%s}" % k not in tex:
            problems.append(f"{k}: in the concordance and never cited with \\lean{{{k}}}")
        if not re.search(r"\\cs\{%s\}\{" % re.escape(k), tex):
            problems.append(f"{k}: no \\cs{{{k}}}{{where it is treated}}")
    letters = check_notation(tex)
    if letters:
        problems.append("symbols used in formulas and absent from the notation list: " + ", ".join(letters))
    body = tex.partition(r"\begin{document}")[2]
    left = re.findall(r"\\fillin\{((?:[^{}]|\{[^{}]*\})*)\}", body)
    if left:
        problems.append(f"{len(left)} places of the template are not written yet (\\fillin): first, \"{left[0][:70]}\"")
    elsewhere = set(spec.get("elsewhere", []))
    aside = {x.get("id") if isinstance(x, dict) else x for x in (unit or {}).get("out_of_scope") or []}
    have = {v["id"] for v in conc.values()}
    gap = [x for x in sorted(unit_ids) if x not in have and x not in elsewhere and x not in aside and idx.get(x, {}).get("name")]
    if gap:
        problems.append(f"gate N-C: {len(gap)} members of unit {spec['unit']} are neither in the note nor listed under \"elsewhere\": " + ", ".join(gap[:6]))
    others = {v["id"] for cj in (ws / "notes").glob("*/concordance.json") if cj.parent != N
              for v in (jload(cj) or {}).get("declarations", {}).values() if v.get("in_unit")}
    pending = sorted(x for x in elsewhere if x in unit_ids and x not in others)
    if pending:
        print(f"  LOOK: {len(pending)} members are listed under \"elsewhere\" and no other note treats them yet, so the unit is not read: "
              + ", ".join(idx.get(x, {}).get("name") or x for x in pending[:6]))
    for x in looks:
        print("  LOOK:", x)
    if a.check:                                             # the text alone, in seconds: the working loop of a repair
        print(f"note: {a.slug}: the text was checked and not built; signature rule: {counted['notations']} notations in {counted['uses']} uses, "
              f"{counted['arguments']} arguments of {counted['stated']} stated declarations accounted for, {counted['absorbed']} absorbed"
              + (f"; the gate caught all {tried} copies broken on purpose" if tried and not missed else "")
              + f"; {len(problems)} problems (problems.json is left as the last build wrote it)")
        for x in problems:
            print("  PROBLEM:", x)
        return 1 if problems else 0
    # LaTeX
    build = N / "build"
    build.mkdir(exist_ok=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH="1700000000", FORCE_SOURCE_DATE="1")
    if not (shutil.which("latexmk") and shutil.which("lualatex")):
        problems.append("latexmk or lualatex is not installed: the note was checked as far as possible and not built")
        jdump(N / "problems.json", {"checked": now(), "built": False, "problems": problems})
        for x in problems:
            print("  PROBLEM:", x)
        return 1
    r = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error", "-outdir=build", f"{a.slug}.tex"],
                       cwd=N, capture_output=True, text=True, env=env)
    log = (build / f"{a.slug}.log").read_text(encoding="utf-8", errors="replace") if (build / f"{a.slug}.log").exists() else ""
    if r.returncode != 0:
        errs = re.findall(r"^(?:! .*(?:\n.*){0,2}|.*(?:[Ff]ont .* (?:not found|cannot be found)|not loadable).*)$", log, re.M)[:4]
        print("\n".join(errs) if errs else r.stdout[-3000:])
        problems.append("LaTeX failed: " + (" | ".join(" ".join(e.split()) for e in errs)[:300] if errs else "see notes/%s/build/%s.log" % (a.slug, a.slug)))
        jdump(N / "problems.json", {"checked": now(), "built": False, "problems": problems})
        print("note: LaTeX failed (%d problems; the list is in problems.json)" % len(problems))
        return 1
    shutil.copyfile(build / f"{a.slug}.pdf", N / f"{a.slug}.pdf")
    for pat, what in ((r"Overfull \\hbox \((\d+\.\d+)pt", "overfull line"), (r"Missing character", "missing glyph"),
                      (r"LaTeX Warning: (?:Reference|Citation) `([^']+)'", "undefined reference")):
        hits = [m for m in re.finditer(pat, log) if what != "overfull line" or float(m.group(1)) > 1.0]
        if hits:
            problems.append(f"{len(hits)} {what}(s) in the LaTeX log" + (": " + ", ".join(sorted({m.group(1) for m in hits})[:5]) if what == "undefined reference" else ""))
    # the reader index: where each declaration is treated
    aux = (build / f"{a.slug}.aux").read_text(encoding="utf-8", errors="replace")
    labels = {m.group(1): {"number": m.group(2), "page": int(m.group(3)), "dest": m.group(4)}
              for m in re.finditer(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}\{(\d+)\}\{(?:[^{}]|\{[^{}]*\})*\}\{([^}]*)\}", aux)}
    where = dict(re.findall(r"\\cs\{(\w+)\}\{((?:[^{}]|\{[^{}]*\})*)\}", tex))
    items, decls = {}, []
    for k, v in conc.items():
        raw = where.get(k, "")
        refs = re.findall(r"\\ref\{([^}]+)\}", raw)
        label = next((lab for words, lab in spec.get("lettered", []) if raw.replace("~", " ").startswith(words)), refs[0] if refs else None)
        text = re.sub(r"\\ref\{([^}]+)\}", lambda m: labels.get(m.group(1), {}).get("number", "?"), raw).replace("~", " ")
        if label not in labels:
            problems.append(f"{k}: its place \"{raw}\" names no label of the text")
            continue
        items.setdefault(label, {"item": label, "title": re.split(r"[,(]", text)[0].strip(), "page": labels[label]["page"],
                                 "dest": labels[label]["dest"], "declarations": []})["declarations"].append(k)
        decls.append(dict(key=k, id=v["id"], name=v["name"], kind=v["kind"], file=v["file"], lines=v["lines"],
                          in_unit=v["in_unit"], item=label, where=text, page=labels[label]["page"]))
    shared_dest = collections.defaultdict(list)             # two places with one destination: a link to the second opens the first
    for lab in items:
        shared_dest[labels[lab]["dest"]].append(lab)
    for dest, labs in sorted(shared_dest.items()):
        if len(labs) > 1:
            problems.append(f"the places {', '.join(sorted(labs))} share one destination in the PDF ({dest}): a \\label after a heading or in "
                            "running text has no anchor of its own; write \\phantomsection immediately before it")
    pages = re.search(r"Output written on .*?\((\d+) pages", log)
    key_ids = {k: v["id"] for k, v in conc.items()}
    nodes = [{"id": o["id"], "title": o["title"], "about": o.get("about", ""), "declarations": [key_ids[k] for k in o["keys"] if k in key_ids]}
             for o in spec.get("outline", [])]
    node_of = {d: n["id"] for n in nodes for d in n["declarations"]}
    edges = collections.Counter()
    for n in nodes:
        for d in n["declarations"]:
            for u in idx.get(d, {}).get("uses", []):
                if u in node_of and node_of[u] != n["id"]:
                    edges[(node_of[u], n["id"])] += 1
    jdump(N / "reader.json", {"schema": "readback/reader/1", "note": a.slug, "title": spec["title"], "unit": spec.get("unit"),
                              "commit": S.cfg["artifact"].get("commit"), "pdf": f"{a.slug}.pdf",
                              "pdf_sha256": hashlib.sha256((N / f"{a.slug}.pdf").read_bytes()).hexdigest(),
                              "pages": int(pages.group(1)) if pages else None,
                              "items": sorted(items.values(), key=lambda i: (i["page"], i["item"])),
                              "outline": {"nodes": nodes, "edges": [{"from": x, "to": y, "uses": n} for (x, y), n in sorted(edges.items())]},
                              "declarations": decls})
    jdump(N / "problems.json", {"checked": now(), "built": True, "problems": problems})
    print(f"note: notes/{a.slug}/{a.slug}.pdf, {pages.group(1) if pages else '?'} pages; concordance of {len(conc)} declarations"
          + (f"; unit {spec['unit']}: {in_note} of {len(unit_ids)} members in the note" if spec.get("unit") else "")
          + f"; signature rule: {counted['notations']} notations in {counted['uses']} uses, {counted['arguments']} arguments of "
            f"{counted['stated']} stated declarations accounted for, {counted['absorbed']} declarations absorbed"
          + (f"; the gate caught all {tried} copies broken on purpose" if tried and not missed else ""))
    for p in problems:
        print("  PROBLEM:", p)
    return 1 if problems else 0


# ------------------------------------------------------------------------------------------------ status and map
def unit_states(ws: Path, L: dict, idx: dict) -> list:
    """The state of every unit, by one rule, for the status, the site and the book.

    `note`: the dossier passes the check, the sources are those it was checked on, and notes of the unit's own,
    built with no problem reported, treat every named member that the dossier does not set aside as out of scope.
    `proofs`: the dossier passes the check on the present sources. `dossier`: there is one. Otherwise `unread`.
    Returns rows (unit, state, check record, named members in notes, named members, notes, why not more)."""
    noted = collections.defaultdict(set)                       # declaration id -> notes that treat it
    for cj in sorted((ws / "notes").glob("*/concordance.json")):
        N, pr = cj.parent, jload(cj.parent / "problems.json")
        r = jload(N / "reader.json")
        if not (isinstance(pr, dict) and not pr.get("problems") and pr.get("built", True) and isinstance(r, dict) and (N / str(r.get("pdf", "-"))).is_file()):
            continue                                           # a note counts when its last build reported no problem
        for v in (jload(cj) or {}).get("declarations", {}).values():
            if v.get("in_unit"):                           # a note counts for its own unit; citing a definition of
                noted[v["id"]].add(N.name)                 # another unit does not make that unit read
    rows = []
    for u in L["units"]:
        U = ws / "reading" / "units" / str(u["id"])
        chk, D = jload(U / "check.json"), jload(U / "unit.json")
        has = isinstance(D, dict)
        aside = {x.get("id") if isinstance(x, dict) else x for x in D.get("out_of_scope") or []} if has else set()
        named = [m for m in u["members"] if idx.get(m, {}).get("name") and m not in aside]
        cov = sum(1 for m in named if m in noted)
        notes = sorted({n for m in named for n in noted.get(m, ())})
        moved = [m.get("name") or m.get("id") for m in (D.get("members") or [] if has else []) if isinstance(m, dict) and (
                 m.get("id") not in idx or (m.get("sha256") and m["sha256"] != idx[m["id"]]["sha256"]) or (m.get("lines") and m["lines"] != idx[m["id"]]["lines"]))]
        edited = has and isinstance(chk, dict) and chk.get("dossier_sha256") not in (None, dossier_digest(U))
        passed = has and isinstance(chk, dict) and isinstance(chk.get("problems"), list) and not chk["problems"] and not moved and not edited
        st = "note" if passed and named and cov == len(named) else "proofs" if passed else "dossier" if has else "unread"
        why = (f"the source of {len(moved)} members changed since the dossier was written ({', '.join(str(x) for x in moved[:3])}{', …' if len(moved) > 3 else ''})" if moved else
               "the dossier was edited after its check" if edited else
               f"the check reports {len(chk['problems'])} problems" if isinstance(chk, dict) and chk.get("problems") else
               "not checked yet" if has and not isinstance(chk, dict) else "")
        rows.append((u, st, chk, cov, len(named), notes, why))
    return rows


def cmd_status(a, ws: Path | None = None) -> int:
    ws = ws or find_ws()
    cfg = cfg_of(ws)
    L = ledger(ws)
    cen = jload(ws / "reading" / "census.json") or census(ws)
    idx = decl_index(cen)
    rows = unit_states(ws, L, idx)
    moved = artifact_changes(ws, cen)
    words = {"note": "note and structured proofs" , "proofs": "structured proofs, checked", "dossier": "dossier, not yet checked", "unread": "not read yet"}
    t = cen["totals"]
    md = [f"# {cfg['name']}: status", "",
          f"Generated by `rb.py status` on {now()}. Artifact: {t['modules']} modules, {t['lines']:,} lines, {t['declarations']:,} declarations"
          + (f", cone of `{cen['root']}`: {t['modules_in_cone']} modules" if cen.get("root") else "") + f"; `sorry`: {t['sorry']}; `axiom` declarations: {len(t['axioms'])} (which axioms the proofs rest on is the kernel's to say, not this count's).", "",
          ("" if (ws / "reading" / "ledger" / "units.json").exists() else
           "**The units below are the proposal** (one per module, from names and imports); the reader's ledger does not exist yet.\n\n") +
          f"Units: {len(rows)}. With a note: {sum(1 for r in rows if r[1] == 'note')}. With checked structured proofs: "
          f"{sum(1 for r in rows if r[1] in ('note', 'proofs'))}. Not read yet: {sum(1 for r in rows if r[1] == 'unread')}.", "",
          "| Unit | Title | Declarations | Reached from the root | State | Proofs | Leaf steps | Named declarations in its notes | Notes |", "|---|---|---|---|---|---|---|---|---|"]
    if moved:
        md[2:2] = [f"**WARNING: {moved}.**", ""]
    for u, st, chk, cov, n, notes, why in rows:
        cnt = (chk or {}).get("counts", {})
        cell = " ".join(str(u.get("title", "")).split()).replace("|", "\\|")
        shown = words[st] if not why else ("dossier: " + why if st == "dossier" else f"{words[st]} ({why})")
        md.append(f"| {u['id']} | {cell} | {len(u['members'])} | {u.get('reached', '')} | {shown} | {cnt.get('proofs', '')} | "
                  f"{cnt.get('leaves', '')} | {cov} of {n} | {', '.join(notes)} |")
    (ws / "STATUS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    mm = ["# Map of the units", "", "An arrow runs from a unit to a unit that uses it. Grey: not read yet.", "", "```mermaid", "flowchart TD"]
    for u, st, *_ in rows:
        label = " ".join(str(u.get("title", "")).split()).replace('"', "#quot;").replace("[", "(").replace("]", ")")
        mm.append(f'  u{u["id"]}["{u["id"]} · {label}<br/>{len(u["members"])} declaration{"" if len(u["members"]) == 1 else "s"}"]:::{st}')
    for u, *_ in rows:
        for i in u.get("imports", []):
            mm.append(f"  u{i} --> u{u['id']}")
    mm += ["  classDef note fill:#d1fae5,stroke:#047857,color:#064e3b", "  classDef proofs fill:#fef3c7,stroke:#b45309,color:#78350f",
           "  classDef dossier fill:#e0e7ff,stroke:#3730a3,color:#1e1b4b", "  classDef unread fill:#f1f5f9,stroke:#94a3b8,color:#94a3b8,stroke-dasharray: 4 3",
           "```", "", "Green: note and structured proofs. Amber: structured proofs, checked. Blue: dossier, not yet checked."]
    (ws / "map").mkdir(exist_ok=True)
    (ws / "map" / "MAP.md").write_text("\n".join(mm) + "\n", encoding="utf-8")
    jdump(ws / "map" / "map.json", {"schema": "readback/map/1", "made": now(), "units": [
        {"id": u["id"], "title": u["title"], "state": st, "declarations": len(u["members"]), "imports": u.get("imports", []),
         "notes": notes, "in_notes": cov, "why_not_more": why} for u, st, chk, cov, n, notes, why in rows]})
    print(f"status: {len(rows)} units: " + "; ".join(f"{sum(1 for r in rows if r[1] == k)} {words[k]}" for k in words) + ". Written: STATUS.md, map/MAP.md, map/map.json")
    if moved:
        print(f"  WARNING: {moved}.")
    return 0


# ------------------------------------------------------------------------------------------------ the book (experimental)
def cmd_site(a) -> int:
    """The web site of the workspace: map, units, structured proofs, Lean source, and each note's PDF beside its Lean text."""
    import site_pages
    ws = find_ws()
    cfg = cfg_of(ws)
    cen = jload(ws / "reading" / "census.json") or census(ws)
    L = ledger(ws)
    idx = decl_index(cen)
    state = {str(u["id"]): st for u, st, *_ in unit_states(ws, L, idx)}
    out = Path(a.out).expanduser().resolve() if a.out else ws / "site"
    if out.exists() and not out.is_dir():
        sys.exit(f"readback: {out} is a file; --out names a folder")
    mine = (jload(out / "site.json") or {}).get("schema") == "readback/site/1" if out.is_dir() else False
    if out.is_dir() and any(out.iterdir()) and (not mine or (out / ".git").exists() or (out / "readback.json").exists()):
        sys.exit(f"readback: {out} exists and is not a site made by this command (or holds a repository); choose another --out")
    moved = artifact_changes(ws, cen)
    if moved:
        sys.exit(f"readback: {moved}. The site would show Lean lines that the dossiers do not describe; it is not built.")
    src = src_of(ws, cfg)                                     # licence and notice files: beside the sources, and up to the top of their repository
    depth = len([x for x in (cfg["artifact"].get("prefix") or "").split("/") if x])
    fresh = out.with_name(f".{out.name}.building")           # written beside the old site and swapped in at the end,
    shutil.rmtree(fresh, ignore_errors=True)                  # so that a failure never leaves half a site
    try:
        c = site_pages.build_site(ws, fresh, cfg, cen, L, state, src, VERSION, now(), notice_dirs=tuple([src, *list(src.parents)[:depth]]))
    except Exception as exc:
        shutil.rmtree(fresh, ignore_errors=True)
        sys.exit(f"readback: the site could not be built ({type(exc).__name__}: {str(exc)[:200]}); the site that was there is unchanged. "
                 "This is a fault of the tool or a record it could not read: please report it.")
    shutil.rmtree(out, ignore_errors=True)
    fresh.rename(out)
    n = c["states"]
    print(f"site: {out / 'index.html'}\n  {c['unit_pages']} unit pages ({n['note']} with a note, {n['proofs']} with checked proofs, {n['dossier']} with a dossier, "
          f"{n['unread']} not read yet), {c['proof_pages']} structured proofs with {c['steps']} steps, {c['source_pages']} source files, "
          f"{c['note_pages']} notes with {c['pdf_pages']} pages beside the Lean text")
    if c["note_pages"] and not c["pdf_pages"]:
        print("  NOTE: poppler (pdftocairo, pdfinfo) was not found; the notes are shown in a frame, without marks on the pages")
    if not c.get("terms_files"):
        print("  NOTE: no licence or notice file was found with the Lean sources; the site says so. Find out the artifact's terms before the site is published.")
    if c["note_pages"] and c["pdf_pages"] and c["lean_lines_marked"] < c["lean_lines_in_notes"]:
        print(f"  NOTE: {c['lean_lines_in_notes'] - c['lean_lines_marked']} of {c['lean_lines_in_notes']} LEAN lines of the notes could not be placed on their pages; the statements are still marked")
    return 0


# ------------------------------------------------------------------------------------------------ starting an agent
def has_lean(d: Path) -> bool:
    return d.is_dir() and any(not any(part.startswith(".") for part in f.relative_to(d).parts) for f in d.rglob("*.lean"))


def is_project(d: Path) -> bool:
    """A folder that is itself a Lean project: project files or Lean files at its top. A folder that merely
    contains projects somewhere below is not one."""
    return d.is_dir() and (any((d / n).is_file() for n in ("lakefile.toml", "lakefile.lean", "lean-toolchain")) or any(d.glob("*.lean")))


def guess_root(cen: dict) -> tuple[str | None, list[str]]:
    """The root module when the imports leave no doubt: the one module that no other module imports. A file that
    declares nothing and only gathers imports is looked through. Returns the root (or None) and the candidates."""
    mods = {m["module"]: m for m in cen["modules"]}
    skip: set = set()
    while True:
        imported = {i for n, m in mods.items() if n not in skip for i in m["imports"]}
        tops = sorted(n for n in mods if n not in skip and n not in imported)
        empty = [n for n in tops if not mods[n]["declarations"]]
        if not empty:
            return (tops[0] if len(tops) == 1 else None), tops
        skip |= set(empty)


def same_tree(a: Path, b: Path) -> bool:
    files = lambda d: {str(f.relative_to(d)): f.read_bytes() for f in d.rglob("*") if f.is_file() and "__pycache__" not in f.parts}  # noqa: E731
    return a.is_dir() and b.is_dir() and files(a) == files(b)


def client_skill(role: str, change: bool) -> str:
    """Is the client's skill installed and the same as this tool's? The reader's is installed when it is not."""
    if role == "writer":
        there = Path.home() / ".claude" / "skills" / "readback"
        if HERE.parent == there or same_tree(HERE.parent / "references", there / "references") and same_tree(HERE, there / "scripts"):
            return ""
        if not (there / "SKILL.md").is_file():
            return f"MISSING: the readback skill is not in {there}. Install it with `make install` in the Readback repository, then start again"
        return f"NOTE: the readback skill in {there} differs from this tool (an older or newer version); `make install` in the Readback repository makes them equal"
    src = next((d for d in (HERE.parent / "assets" / "readback-reader", HERE.parent.parent / "readback-reader") if (d / "SKILL.md").is_file()), None)
    there = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "skills" / "readback-reader"
    if src is None:
        return "" if (there / "SKILL.md").is_file() else f"NOTE: the readback-reader skill is not in {there}; run `make install-codex` in the Readback repository"
    if same_tree(src, there):
        return ""
    if not change:
        return f"the readback-reader skill in {there} is missing or older: starting for real installs it there"
    shutil.rmtree(there, ignore_errors=True)
    shutil.copytree(src, there, ignore=shutil.ignore_patterns("__pycache__"))
    return f"installed the readback-reader skill into {there}"


def cmd_start(a) -> int:
    """Start one of the two agents in a workspace, with its model, its effort and its first prompt. The workspace
    is found from where you are, or made when there is none yet."""
    role = a.role
    base = Path(a.dir or ".").expanduser().resolve()
    ws = next((c for c in (base, base / "ws") if (c / "readback.json").exists()), None) \
        or next((p for p in base.parents if (p / "readback.json").exists()), None)
    said = []
    try:
        here = sorted(p.parent for p in base.glob("*/readback.json")) if base.is_dir() else []
    except OSError:
        here = []
    if ws is None and len(here) == 1:
        ws = here[0]
    elif ws is None and here:
        sys.exit(f"readback: {base} holds {len(here)} workspaces ({', '.join(p.name for p in here)}); go into one of them, or give it as the argument")
    elif ws in here and len(here) > 1:
        said.append(f"NOTE: this folder holds other workspaces too ({', '.join(p.name for p in here if p != ws)}); to start in one of them, go into it or give it as the argument")
    if ws is None:                                           # inside the sources of some workspace? Then that is the one.
        found = []
        for anc in [base, *base.parents][:8]:
            if len(anc.parts) <= 2:                           # never search the top of the file system
                break
            try:
                beside = sorted(anc.parent.glob("*/readback.json"))
            except OSError:
                beside = []
            for cj in beside:
                try:
                    if src_of(cj.parent, cfg_of(cj.parent)).resolve() == anc:
                        found.append(cj.parent)
                except (OSError, KeyError, TypeError, ValueError):
                    pass
            if found:
                break
        if len(found) == 1:
            ws = found[0]
            said.append(f"you are in the Lean sources of the workspace {ws}")
        elif found:
            sys.exit(f"readback: {len(found)} workspaces read these sources ({', '.join(str(x) for x in found)}); go into one of them, or give it as the argument")
    if ws is not None:                                       # the other agent's start may still be making it
        lock = ws.parent / f".readback-init-{ws.name}.lock"
        for _ in range(300):
            if not lock.exists():
                break
            time.sleep(1)
        else:
            sys.exit(f"readback: {ws} is still being made by another start, or a start died and left {lock}; remove that folder if no start is running")
    if ws is None:
        art = base / "src" if has_lean(base / "src") else base if is_project(base) else None
        if art is None:
            sys.exit(f"readback: {base} holds no workspace (readback.json), no workspace named ws, no Lean files in src/, and is not a Lean project itself. "
                     "Go to the folder of your artifact or workspace, or give it as the argument.")
        ws = base / "ws" if art != base else base.parent / (base.name + "-readback")
        lock = ws.parent / f".readback-init-{ws.name}.lock"
        try:
            lock.mkdir()
        except FileExistsError:                                  # the other agent is being started at the same moment
            for _ in range(120):
                if (ws / "readback.json").exists() and not lock.exists():
                    break
                time.sleep(1)
            else:
                sys.exit(f"readback: another start is making {ws} and has not finished; remove {lock} if that is not so")
        else:
            try:
                name = a.name or (base.name if art != base else art.name)
                root = a.root
                if not root:
                    root, tops = guess_root({"modules": list(scan_modules(art).values())})
                    said.append(f"root module: {root}, the only module that no other imports (to change it: rb.py root MODULE)" if root else
                                "no root module is set: " + (f"{len(tops)} modules are imported by no other ({', '.join(tops[:6])}" + (", …" if len(tops) > 6 else "") + ")"
                                                             if tops else "the imports form a cycle") + "; the writer settles it with you first, then: rb.py root MODULE")
                cmd_init(argparse.Namespace(workspace=str(ws), artifact=str(art), root=root, name=name, url=None,
                                            writer=CLIENTS["writer"].get("name", "fable"), reader=CLIENTS["reader"].get("name", "astra")))
                if shutil.which("git") and not (ws / ".git").exists():
                    subprocess.run(["git", "init", "-q"], cwd=ws)
                said.append(f"made the workspace {ws} for the artifact {art}")
            finally:
                lock.rmdir()
    cfg = cfg_of(ws)
    if not any("made the workspace" in x for x in said):       # an existing workspace: an option is applied or refused, never ignored
        if a.root and a.root != cfg["artifact"].get("root_module"):
            old = cfg["artifact"].get("root_module")
            set_root(ws, a.root)
            cfg = cfg_of(ws)
            said.append(f"root module changed: {old or 'not set'} -> {a.root}; census, unit proposal and status are made again")
        if a.name and a.name != cfg["name"]:
            sys.exit(f"readback: this workspace is named \"{cfg['name']}\"; --name applies only when a workspace is made. To rename it, change `name` in {ws / 'readback.json'}.")
    moved = artifact_changes(ws, jload(ws / "reading" / "census.json") or census(ws))
    if moved:
        said.append(f"WARNING: {moved}")
    if HERE != (ws / "tools").resolve() and any((ws / "tools" / n).read_bytes() != (HERE / n).read_bytes() for n in TOOLS if (ws / "tools" / n).exists()):
        said.append(f"NOTE: the tools in this workspace (made with readback {cfg.get('version')}) differ from the skill's ({VERSION}); "
                    f"to take the skill's, run: python3 {HERE / 'rb.py'} upgrade")
    agent = agents_of(cfg)[role]
    model, effort, who, client = a.model or agent["model"], a.effort or agent["effort"], agent.get("name", role), agent["client"]
    if client not in ("claude", "codex"):
        sys.exit(f"readback: readback.json names the client {client!r} for the {role}; this command starts claude or codex")
    fresh = not (ws / "exchange" / "ledger.jsonl").exists() or not (ws / "exchange" / "ledger.jsonl").read_text(encoding="utf-8").strip()
    root = cfg["artifact"].get("root_module")
    inbox = f"python3 tools/rb.py mail --as {who} inbox"
    if a.prompt:
        prompt = a.prompt
    elif role == "writer" and fresh:
        prompt = (f"Use the readback skill. This is a Readback workspace for the Lean artifact \"{cfg['name']}\". Read CLAUDE.md and tell me what the census says "
                  "about the artifact. " + ("" if root else "No root module is set: propose one and settle it with me before anything else. ")
                  + "Then ask the reader through the mailbox for the ledger of units, and after that for the dossier of the unit that holds the final theorem; "
                  "ask me which unit that is if the ledger leaves a doubt. Keep a watch on your inbox.")
    elif role == "writer":
        prompt = (f"Use the readback skill. Continue in this Readback workspace for \"{cfg['name']}\": read CLAUDE.md, the top entry of JOURNAL.md, PLAN.md and "
                  f"MEMORY.md, check your inbox ({inbox}), tell me in a few lines where the work stands, and go on with the next item of the plan. "
                  "Keep a watch on your inbox.")
    elif fresh:
        prompt = (f"Use the readback-reader skill. Read AGENTS.md and exchange/PROTOCOL.md. You are the reader, your name is {who}. Check your inbox with "
                  f"`{inbox}` and do what is asked, one hand-off at a time. Keep a watch on your inbox.")
    else:
        prompt = (f"Use the readback-reader skill. Continue in this Readback workspace: read AGENTS.md, exchange/PROTOCOL.md and your own records under reading/. "
                  f"You are the reader, your name is {who}. Check your inbox with `{inbox}` and go on with what waits, one hand-off at a time. "
                  "Keep a watch on your inbox.")
    if not a.print and not shutil.which(client):
        sys.exit(f"readback: the command `{client}` is not on your PATH; nothing was started or installed")
    note = client_skill(role, change=not a.print)
    if note.startswith("MISSING") and not a.print:
        sys.exit("readback: " + note[9:] + ". The client is not started: without the skill its first prompt would fail.")
    if note:
        said.append(note)
    extra = shlex.split(a.client_args or "")
    pick = (["--model", model] if client == "claude" else ["-m", model]) if model else []      # no model: the client's own default
    argv = (["claude", *pick, "--effort", effort, "--name", f"Readback {role}: {cfg['name']}", *extra, prompt] if client == "claude" else
            ["codex", *pick, "-c", f'model_reasoning_effort="{effort}"', "-C", str(ws), *extra, prompt])
    print(f"readback {VERSION}: the {role} ({who}) of \"{cfg['name']}\"\n  workspace  {ws}\n  client     {client}, model {model or 'the client default'}, effort {effort}\n"
          f"  mailbox    {'empty: a first session' if fresh else 'has messages: a session that continues'}")
    for line in said:
        print("  " + line)
    if a.print:
        print("  first prompt:\n    " + prompt + "\n  command, run in the workspace:\n    " + " ".join(shlex.quote(x) for x in argv))
        return 0
    os.chdir(ws)
    os.environ.pop("NO_COLOR", None)
    os.execvp(client, argv)
    return 0


def cmd_book(a) -> int:
    ws = find_ws()
    cfg = cfg_of(ws)
    L = ledger(ws)
    order = {u["id"]: i for i, u in enumerate(L["units"])}
    notes = []
    for rj in sorted((ws / "notes").glob("*/reader.json")):
        r = jload(rj)
        if (rj.parent / r["pdf"]).exists():
            notes.append((order.get(str(r.get("unit")), 10 ** 6), rj.parent.name, r))
    notes.sort()
    if not notes:
        sys.exit("readback: no built note to put into a book")
    B = ws / "book"
    B.mkdir(exist_ok=True)
    summary = (B / "summary.tex").read_text(encoding="utf-8") if (B / "summary.tex").exists() else \
        (r"\emph{The summary is written last, by the writer, in \texttt{book/summary.tex}: what the artifact proves, how the chapters depend on each other, "
         r"what is read and what is not. Take every count from \texttt{book/counts.tex}: this book has \rbNotes{} notes with \rbNotePages{} pages, "
         r"on \rbUnitsWithNote{} of \rbUnits{} units.}")
    read = {str(r.get("unit")) for _, _, r in notes}
    grey = [u for u in L["units"] if u["id"] not in read]
    cen = jload(ws / "reading" / "census.json") or census(ws)
    idx, t = decl_index(cen), cen["totals"]
    rows = unit_states(ws, L, idx)
    checks = [chk.get("counts", {}) for _, _, chk, *_ in rows if isinstance(chk, dict)]
    members = {m for u in L["units"] for m in u["members"]}
    cone = set(cen.get("cone") or [m["module"] for m in cen["modules"]])
    counts = {"Modules": t["modules"], "Lines": t["lines"], "Declarations": t["declarations"], "ConeModules": len(cone),
              "ConeDeclarations": sum(1 for d in idx.values() if d["module"] in cone), "Sorry": t["sorry"], "AxiomDeclarations": len(t["axioms"]),
              "Units": len(rows), "UnitsWithNote": sum(1 for r in rows if r[1] == "note"), "UnitsChecked": sum(1 for r in rows if r[1] in ("note", "proofs")),
              "UnitsNotRead": sum(1 for r in rows if r[1] == "unread"), "Members": len(members),
              "InNoUnit": sum(1 for i, d in idx.items() if d["module"] in cone and i not in members),
              "MemberTheorems": sum(1 for m in members if idx.get(m, {}).get("kind") in ("theorem", "lemma")),
              "StructuredProofs": sum(c.get("proofs", 0) for c in checks), "Steps": sum(c.get("steps", 0) for c in checks),
              "LeafSteps": sum(c.get("leaves", 0) for c in checks),
              # lines of the members' theorems after their statement lines, as the contract of the ledger defines them
              "ProofLines": sum(idx[m]["lines"][1] - idx[m]["statement_lines"][1] for m in members if idx.get(m, {}).get("kind") in ("theorem", "lemma")),
              "ProofLinesInStructuredProofs": sum(c.get("proof_lines", 0) for c in checks),
              "Notes": len(notes), "NotePages": sum(r.get("pages") or 0 for _, _, r in notes)}
    (B / "counts.tex").write_text("% generated by rb.py book from the records of the workspace; do not edit. Use these in summary.tex.\n"
                                  + "".join("\\newcommand{\\rb%s}{%s}\n" % (k, f"{v:,}".replace(",", "{,}")) for k, v in counts.items()), encoding="utf-8")
    tex = [r"\documentclass[11pt,a4paper]{report}", r"\usepackage{fontspec}\IfFontExistsTF{Libertinus Serif}{\setmainfont{Libertinus Serif}}{}",
           r"\usepackage{pdfpages}\usepackage{xcolor}\usepackage[hidelinks]{hyperref}",
           r"\input{counts.tex}", r"\begin{document}", r"\begin{titlepage}\centering\vspace*{4cm}{\Huge\bfseries %s\par}\vspace{1cm}{\Large read back into mathematics\par}"
           r"\vfill{\small assembled by readback %s}\end{titlepage}" % (tex_escape(cfg["name"]), VERSION),
           r"\chapter*{Summary}", summary, r"\section*{Chapters}", r"\begin{itemize}"]
    tex += [r"\item %s (%s pages)" % (tex_escape(r["title"]), r.get("pages", "?")) for _, _, r in notes]
    tex += [r"\item {\color{gray}%s --- not read yet}" % tex_escape(u["title"]) for u in grey]
    tex += [r"\end{itemize}", r"\tableofcontents"]
    tex += [r"\includepdf[pages=-,addtotoc={1,chapter,0,{%s},ch:%s}]{../notes/%s/%s}" % (tex_escape(r["title"]), s, s, r["pdf"]) for _, s, r in notes]
    tex.append(r"\end{document}")
    (B / "book.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    if not (shutil.which("latexmk") and shutil.which("lualatex")):
        sys.exit("readback: latexmk or lualatex is not installed; book/book.tex and book/counts.tex are written, the PDF is not built")
    r = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error", "-outdir=build", "book.tex"], cwd=B, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        return 1
    shutil.copyfile(B / "build" / "book.pdf", B / "book.pdf")
    print(f"book: book/book.pdf from {len(notes)} notes; {len(grey)} units listed as not read yet (experimental assembly)")
    return 0


# ------------------------------------------------------------------------------------------------ leak scan
def cmd_leakscan(a) -> int:
    pats = []
    for n, l in enumerate(Path(a.patterns).read_text(encoding="utf-8").split("\n"), 1):
        if l.strip() and not l.startswith("#"):
            try:
                pats.append(re.compile(l.strip()))
            except re.error as exc:
                sys.exit(f"readback: line {n} of {a.patterns} is not a regular expression ({exc})")
    root, hits, binary = Path(a.path).resolve(), 0, 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in (".git", ".lake", "__pycache__") for part in p.relative_to(root).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            binary += 1                                        # a PDF, a picture: not searched
            continue
        for rx in pats:
            for m in rx.finditer(text):
                hits += 1
                print(f"LEAK {p.relative_to(root)}: {m.group(0)[:60]!r} (pattern {rx.pattern[:40]})")
    print(f"leakscan: {len(pats)} patterns, {hits} hits under {root}" + (f"; {binary} files are not text and were not searched (PDFs, pictures: look at them yourself)" if binary else ""))
    return 1 if hits else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="rb.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create a workspace for a Lean artifact; runs census, units and status")
    p.add_argument("workspace"); p.add_argument("--artifact", required=True, help="directory of the Lean sources")
    p.add_argument("--root", help="the root module, e.g. My.Main"); p.add_argument("--name", help="a name for the artifact")
    p.add_argument("--url", help="link pattern with {commit} {path} {a} {b}; {path} is the file's path in the artifact's repository, {file} its path in the artifact")
    p.add_argument("--writer", default="fable"); p.add_argument("--reader", default="astra")
    sub.add_parser("census", help="read the Lean files again and rewrite reading/census.json (names and imports; nothing is compiled)")
    sub.add_parser("units", help="rewrite reading/units.proposal.json from the census")
    sub.add_parser("status", help="rewrite STATUS.md, map/MAP.md and map/map.json from the ledger (or the proposal), the checks and the notes")
    sub.add_parser("book", help="assemble the built notes into book/book.pdf (experimental)")
    p = sub.add_parser("start", help="start the writer (Claude Code) or the reader (Codex) in a workspace, with its model, effort and first prompt; "
                                     "makes the workspace when there is none")
    p.add_argument("role", choices=("writer", "reader"))
    p.add_argument("dir", nargs="?", help="a workspace, a folder that holds one named ws, a folder with Lean sources in src/, or a Lean project; default: here")
    p.add_argument("--root", help="when the workspace is made: the root module (otherwise guessed when the imports leave no doubt)")
    p.add_argument("--name", help="when the workspace is made: a name for the artifact (default: the folder's name)")
    p.add_argument("--model", help="for this session only; the default is in readback.json, agents.<role>.model (none: the client's own default)")
    p.add_argument("--effort", help="for this session only; the default is in readback.json, agents.<role>.effort")
    p.add_argument("--prompt", help="your own first prompt in place of the standard one")
    p.add_argument("--client-args", help="more options for the client, as one string")
    p.add_argument("--print", action="store_true", help="prepare the workspace, then show the command and the prompt without starting the client")
    p = sub.add_parser("upgrade", help="copy the tools of this skill into the workspace you are in (run the skill's rb.py, not tools/rb.py)")
    p.add_argument("--instructions", action="store_true", help="also write CLAUDE.md, AGENTS.md and exchange/PROTOCOL.md again from the present templates")
    p = sub.add_parser("site", help="build the web site: map, units, structured proofs, Lean source, each note's PDF beside its Lean text")
    p.add_argument("--out", help="where to write it (default: site/ in the workspace); the directory is replaced")
    p = sub.add_parser("mail", help="the mailbox between the two agents")
    p.add_argument("--as", dest="as_", required=True, help="your agent's name as in readback.json (by default fable for the writer, astra for the reader)")
    p.add_argument("action", choices=("inbox", "send", "archive", "status", "watch", "wait", "stop"))
    p.add_argument("--replace", action="store_true", help="watch, wait: stop the one already running for this name in this workspace first")
    p.add_argument("seconds", nargs="?", type=int, default=20, help="watch, wait: seconds between two looks")
    p.add_argument("--timeout", type=int, help="wait: give up after this many seconds (exit 2)")
    p.add_argument("--type", help="send: " + ", ".join(TYPES))
    p.add_argument("--re", default="-", help="send: the messages of the peer that this one answers, e.g. msg-0003 (never your own)")
    p.add_argument("--slug", help="send: a short name, lower-case letters, digits, hyphens")
    p.add_argument("--subject", default="", help="send: one line")
    p.add_argument("--body", help="send: a file with the text (keep drafts under build/mail/), or - for standard input")
    p.add_argument("--payload", nargs="*", help="send: files to attach")
    p.add_argument("--skip-present", action="store_true", help="watch, wait: do not announce messages that are already there")
    p = sub.add_parser("root", help="show the root module, or set it (the owner's decision) and make census, units and status again")
    p.add_argument("module", nargs="?")
    sub.add_parser("ledger", help="check the reader's ledger of units against the census; writes reading/ledger/check.json")
    p = sub.add_parser("signature", help="print the arguments of the declarations of a unit, or of one declaration, as the text gives them")
    p.add_argument("what", help="a unit id, or the name or id of a declaration")
    p = sub.add_parser("check", help="check the dossier of a unit against the Lean source; writes reading/units/UNIT/check.json")
    p.add_argument("unit")
    p.add_argument("--lean-ranges", action="store_true", help="obtain statement/value spans from Lean (build Lake projects first)")
    p = sub.add_parser("note", help="build a note and check it (keys cited, letters in the notation, places of the template still unwritten, gate N-C, the LaTeX log)")
    p.add_argument("slug")
    p.add_argument("--new", metavar="TITLE", help="make the note's folder from the template")
    p.add_argument("--unit", help="with --new: the unit the note reads")
    p.add_argument("--refresh", action="store_true", help="take the present source lines into the concordance, after reading what changed")
    p.add_argument("--check", action="store_true", help="check the text only (keys, letters, gate N-C, the signature rule), without LaTeX; nothing is recorded")
    p.add_argument("--account", action="store_true", help="an existing note: add to spec.json a place for everything the signature rule needs, and list what to do")
    p.add_argument("--rewrite", nargs=2, metavar=("PATTERN", "TEMPLATE"),
                   help="replace a regular expression in the note's text (Python syntax, \\1 for a group), leaving comments and macro definitions alone; the old text is kept")
    p = sub.add_parser("leakscan", help="search a tree for strings that must not be published")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--patterns", required=True, help="a file with one regular expression per line; lines starting with # are comments")
    a = ap.parse_args()
    if a.cmd == "census":
        census(find_ws()); return 0
    if a.cmd == "units":
        units(find_ws()); return 0
    return {"init": cmd_init, "mail": cmd_mail, "check": cmd_check, "note": cmd_note, "status": cmd_status, "book": cmd_book, "site": cmd_site, "upgrade": cmd_upgrade, "start": cmd_start, "ledger": cmd_ledger, "root": cmd_root,
            "leakscan": cmd_leakscan, "signature": cmd_signature}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
