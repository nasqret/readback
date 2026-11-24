"""The static site of a Readback workspace. Called by `rb.py site`.

Pages: the map of units; a page per unit; a page per structured proof (every step beside the Lean lines it
renders); the Lean source with line anchors; and, for every note, a reader with the pages of the PDF on the left
and the Lean text of the chosen statement on the right.

Standard library only. No page asks the network for anything. The pictures of the PDF pages and the places of
the statements on them come from poppler (`pdftocairo`, `pdfinfo`, `pdftotext`); without poppler the reader shows
the PDF in a frame and still moves it to the page of the chosen statement.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

STATE = {"note": "note and structured proofs", "proofs": "structured proofs, checked",
         "dossier": "dossier, not yet checked", "unread": "not read yet"}
KEYWORDS = set("""theorem lemma def abbrev instance structure inductive class where namespace end open import mutual
private protected noncomputable by have show suffices obtain intro intros exact apply cases rcases induction with fun
match at simp simpa rw rewrite omega decide constructor refine rfl example variable section deriving if then else let
do return in from calc termination_by decreasing_by unfold exists use rename_i trivial contradiction exfalso next case
all_goals any_goals first try repeat set_option attribute macro syntax notation infix infixl infixr prefix postfix
universe axiom opaque partial unsafe native_decide classical""".split())
TOKEN = re.compile(r'(?P<lc>--.*)|(?P<st>"(?:\\.|[^"\\])*"?)|(?P<id>[^\W\d][\w\'!?]*(?:\.[^\W\d][\w\'!?]*)*)|(?P<o>.)', re.S)
A4 = (595.276, 841.89)
esc = html.escape


def jload(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def slug(s) -> str:
    return re.sub(r"[^\w.-]+", "-", str(s)).strip("-") or "x"         # letters of any alphabet stay


def distinct(names) -> dict:
    """A slug for each name, no two alike: `case one` and `case-one` must not share an anchor or a file."""
    taken, out = set(), {}
    for n in names:
        base = k = slug(n)
        i = 2
        while k in taken:
            k, i = f"{base}-{i}", i + 1
        taken.add(k)
        out[n] = k
    return out


def text(x) -> str:
    return x if isinstance(x, str) else ""


def pair(x):
    """Two line numbers, first not after last; anything else is None."""
    ok = isinstance(x, list) and len(x) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in x) and 1 <= x[0] <= x[1]
    return [x[0], x[1]] if ok else None


def clean_unit(D):
    """A dossier as the pages may use it: the fields they read, each of the type they expect. What a dossier holds
    is written by another agent; a field of the wrong shape is dropped here and cannot break a page."""
    if not isinstance(D, dict):
        return None
    rows = lambda key: [x for x in D.get(key) if isinstance(x, dict)] if isinstance(D.get(key), list) else []   # noqa: E731
    return {"summary": text(D.get("summary")),
            "members": [{"id": m["id"], "text": text(m.get("text")), "triage": text(m.get("triage")),
                         "case_readings": [{"lean": text(c.get("lean")), "text": text(c.get("text"))} for c in m["case_readings"] if isinstance(c, dict)]
                         if isinstance(m.get("case_readings"), list) else []} for m in rows("members") if isinstance(m.get("id"), str)],
            "imports": [{"id": text(i.get("id")), "name": text(i.get("name")), "unit": text(i.get("unit")) if not isinstance(i.get("unit"), int) else str(i["unit"]),
                         "text": text(i.get("text"))} for i in rows("imports")],
            "ambient_inputs": [{"name": text(x.get("name")), "text": text(x.get("text"))} for x in rows("ambient_inputs")]}


def clean_proof(P):
    if not isinstance(P, dict) or not isinstance(P.get("declaration"), str) or not isinstance(P.get("steps"), list):
        return None
    steps = []
    for st in P["steps"]:
        if not isinstance(st, dict) or not isinstance(st.get("id"), str) or pair(st.get("lines")) is None:
            continue
        sr = st.get("simp_reading")
        steps.append({"id": st["id"], "parent": st.get("parent") if isinstance(st.get("parent"), str) else None, "kind": text(st.get("kind")) or "step",
                      "claim": text(st.get("claim")), "lines": pair(st["lines"]), "head_lines": pair(st.get("head_lines")), "typed_fact": text(st.get("typed_fact")),
                      "uses": [x for x in st["uses"] if isinstance(x, str) or (isinstance(x, dict) and isinstance(x.get("step") or x.get("decl"), str))]
                      if isinstance(st.get("uses"), list) else [],
                      "ambient_uses": [x for x in st["ambient_uses"] if isinstance(x, str)] if isinstance(st.get("ambient_uses"), list) else [],
                      "simp_reading": {"text": text(sr.get("text")), "label": text(sr.get("label")) or "heuristic"} if isinstance(sr, dict) else None})
    return {"declaration": P["declaration"], "summary": text(P.get("summary")), "steps": steps, "dropped": len(P["steps"]) - len(steps)}


def name_html(name: str) -> str:
    """A Lean name that may break after a dot and nowhere else."""
    return esc(name).replace(".", ".<wbr>")


def many(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def span(a: int, b: int) -> str:
    return f"lines {a}–{b}" if b > a else f"line {a}"


def highlight(lines: list[str]) -> list[str]:
    """Lean lines as HTML: comments (also over several lines), strings, keywords, `sorry`. The text is never changed."""
    out, depth = [], 0
    for ln in lines:
        parts, i = [], 0
        while i < len(ln):
            if depth or ln.startswith("/-", i):
                j = i
                while j < len(ln):
                    if ln.startswith("/-", j):
                        depth, j = depth + 1, j + 2
                    elif ln.startswith("-/", j):
                        depth, j = depth - 1, j + 2
                        if not depth:
                            break
                    else:
                        j += 1
                parts.append(f'<span class="cm">{esc(ln[i:j])}</span>')
                i = j
                continue
            m = TOKEN.match(ln, i)
            t, kind = m.group(0), m.lastgroup
            if kind == "id":
                parts.append(f'<span class="sr">{t}</span>' if t == "sorry" else f'<span class="kw">{t}</span>' if t in KEYWORDS else esc(t))
            elif kind in ("lc", "st"):
                parts.append(f'<span class="{"cm" if kind == "lc" else "st"}">{esc(t)}</span>')
            else:
                parts.append(esc(t))
            i = m.end()
        out.append("".join(parts))
    return out


class Source:
    """The Lean files of the artifact, read once, with their highlighted lines."""

    def __init__(self, root: Path):
        self.root, self.raw, self.hl = root, {}, {}

    def lines(self, file: str) -> list[str]:
        if file not in self.raw:
            p = self.root / file
            rows = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n") if p.is_file() else []
            if rows and rows[-1] == "":
                rows.pop()
            self.raw[file], self.hl[file] = rows, highlight(rows)
        return self.raw[file]

    def box(self, file: str, a: int, b: int, prefix: str = "", caption: str = "", label: str = "") -> str:
        """Lines a to b of a file, numbered. The numbers are drawn by the style sheet, so a copy does not take them."""
        raw = self.lines(file)
        a, b = max(1, a), min(b, len(raw))
        rows = []
        for n in range(a, b + 1):
            ind = len(raw[n - 1]) - len(raw[n - 1].lstrip(" "))
            rows.append(f'<span class="ln" id="{prefix}L{n}" data-n="{n}"' + (f' style="--ind:{ind}"' if ind else "") + f'>{self.hl[file][n - 1]}</span>')
        cap = caption or f"{file}, {span(a, b)}"
        return (f'<figure class="code"><figcaption><span>{esc(cap)}</span><button type="button" data-copy>Copy</button></figcaption>'
                f'<pre class="lean" tabindex="0" aria-label="{esc(label or cap)}"><code>{"".join(rows)}</code></pre></figure>')


def tool(*cmd: str) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def pdf_geometry(pdf: Path, tex: Path) -> dict:
    """Page sizes, named destinations and the LEAN lines of a note: what the reader needs to mark the pages.

    A LEAN line is found as the small word LEAN at the left edge of the text; the k-th one on the pages is the
    k-th `\\leanline` of the LaTeX source. When the two counts differ, no LEAN line is marked."""
    geo = {"sizes": {}, "dests": {}, "lean_lines": [], "lean_lines_in_tex": 0, "words": []}
    for m in re.finditer(r"Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+) pts", tool("pdfinfo", "-f", "1", "-l", "100000", str(pdf)) or ""):
        geo["sizes"][int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    num = lambda s: float(s) if re.fullmatch(r"-?[\d.]+", s) else None           # noqa: E731
    for m in re.finditer(r'^\s*(\d+) \[ (\w+)\s+([^\]]*?)\s*\] "(.*)"\s*$', tool("pdfinfo", "-dests", str(pdf)) or "", re.M):
        kind, nums = m.group(2), m.group(3).split()
        x, y = ((num(nums[0]), num(nums[1])) if kind == "XYZ" and len(nums) >= 2 else
                (None, num(nums[0])) if kind in ("FitH", "FitBH") and nums else (None, None))
        geo["dests"][m.group(4)] = {"page": int(m.group(1)), "x": x, "y": y}
    body = tex.read_text(encoding="utf-8", errors="replace").partition(r"\begin{document}")[2] if tex.is_file() else ""
    wanted = []
    for m in re.finditer(r"\\leanline\{", body):
        depth, j = 1, m.end()
        while j < len(body) and depth:
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            j += 1
        wanted.append(re.findall(r"\\lean\{(\w+)\}", body[m.end():j]))
    geo["lean_lines_in_tex"] = len(wanted)
    pages = [[(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in
              re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', pm)]
             for pm in re.findall(r"<page [^>]*>(.*?)</page>", tool("pdftotext", "-bbox", str(pdf), "-") or "", re.S)]
    geo["words"] = pages
    tags = [(p, i) for p, words in enumerate(pages) for i, w in enumerate(words) if w[4] == "LEAN" and w[3] - w[1] < 7]
    if tags:
        edge = min(pages[p][i][0] for p, i in tags)
        tags = [(p, i) for p, i in tags if pages[p][i][0] - edge < 2]
    if wanted and len(tags) == len(wanted):
        for (p, i), keys in zip(tags, wanted):
            words = pages[p]
            x0, top, right, bottom = words[i][0], words[i][1], words[i][2], words[i][3]
            for w in words[i + 1:]:
                if w[1] > bottom + 5.5 or w[3] - w[1] > 11 or w[3] < top - 8:
                    break
                top, right, bottom = min(top, w[1]), max(right, w[2]), max(bottom, w[3])
            geo["lean_lines"].append({"page": p + 1, "keys": keys, "box": [x0 - 4, top - 3, right + 4, bottom + 3]})
    return geo


def page(title: str, trail: list[tuple[str, str]], body: str, meta: dict, cls: str = "") -> str:
    crumbs = "".join(f'<li><a href="{h}">{esc(t)}</a></li>' if h else f'<li aria-current="page">{esc(t)}</li>' for t, h in trail)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(meta['name'])}</title><link rel="stylesheet" href="assets/site.css"></head>
<body{f' class="{cls}"' if cls else ''}><a class="skip" href="#main">Skip to content</a>
<header class="top"><a class="brand" href="index.html"><b>{esc(meta['name'])}</b><span>read back into mathematics</span></a>
<nav aria-label="Site"><a href="index.html">Map</a><a href="index.html#units">Units</a><a href="index.html#notes">Notes</a><a href="index.html#proofs">Structured proofs</a><a href="index.html#source">Lean source</a></nav></header>
<nav class="trail" aria-label="You are here"><ol>{crumbs}</ol></nav>
<main id="main">{body}</main>
<footer>Built {esc(meta['made'])} by readback {esc(meta['version'])} · artifact {esc(meta['pin'])} · every number on this site is computed from the workspace · the Lean text belongs to its authors: <a href="index.html#terms">its terms</a>.</footer>
<script src="assets/site.js"></script></body></html>
"""


def badge(state: str) -> str:
    return f'<span class="badge {state}">{STATE[state]}</span>'


def wrap_words(text: str, width: int, rows: int) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > width and cur:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    out.append(cur)
    if len(out) > rows:
        out = out[:rows]
        out[-1] = out[-1][:width - 1].rstrip() + "…"
    return out


def unit_map(units: list[dict], state: dict) -> str:
    """The units as a layered drawing: a unit stands below everything it uses. An arrow that follows from two
    others is not drawn."""
    by = {u["id"]: u for u in units}
    imp = {u["id"]: [i for i in map(str, u.get("imports", [])) if i in by and i != u["id"]] for u in units}
    layer: dict = {}
    reach: dict = {}

    def depth(i):
        if i not in layer:
            layer[i] = 0                                     # a cycle in a hand-made ledger ends here
            layer[i] = 1 + max((depth(j) for j in imp[i]), default=-1)
        return layer[i]

    def below(i):
        if i not in reach:
            reach[i] = set()
            reach[i] = set(imp[i]).union(*(below(j) for j in imp[i]))
        return reach[i]

    for u in units:
        depth(u["id"])
    circle = any(u["id"] in below(u["id"]) for u in units)     # units that use each other: then every arrow is drawn
    rows = []
    for k in sorted(set(layer.values())):
        ids = [u["id"] for u in units if layer[u["id"]] == k]
        rows += [ids[n:n + 5] for n in range(0, len(ids), 5)]
    W, H, GX, GY = 224, 92, 28, 50
    if not rows:
        return ""
    width = max(len(r) for r in rows) * (W + GX) + GX
    height = len(rows) * (H + GY)
    pos = {}
    for k, r in enumerate(rows):
        x0 = (width - (len(r) * (W + GX) - GX)) / 2
        for j, i in enumerate(r):
            pos[i] = (x0 + j * (W + GX), GY / 2 + k * (H + GY))
    out = [f'<svg class="map" viewBox="0 0 {width:.0f} {height:.0f}" style="max-width:{width:.0f}px" role="img" aria-label="The units of the artifact. A unit stands below the units it uses.">'
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker></defs>']
    for u in units:
        x, y = pos[u["id"]]
        for i in imp[u["id"]]:
            if not circle and any(i in below(j) for j in imp[u["id"]] if j != i):
                continue
            a, b = pos[i]
            out.append(f'<path class="edge" marker-end="url(#arrow)" d="M{a + W / 2:.0f},{b + H:.0f} C{a + W / 2:.0f},{b + H + GY * .55:.0f} {x + W / 2:.0f},{y - GY * .55:.0f} {x + W / 2:.0f},{y - 2:.0f}"/>')
    for u in units:
        x, y = pos[u["id"]]
        st = state[u["id"]]
        text = "".join(f'<text x="{x + 13:.0f}" y="{y + 41 + 16 * n:.0f}" class="t">{esc(l)}</text>' for n, l in enumerate(wrap_words(u["title"], 30, 3)))
        out.append(f'<a href="unit-{slug(u["id"])}.html"><g class="node {st}"><title>Unit {esc(u["id"])}: {esc(u["title"])}. {STATE[st]}.</title>'
                   f'<rect x="{x:.0f}" y="{y:.0f}" width="{W}" height="{H}" rx="10"/>'
                   f'<text x="{x + 13:.0f}" y="{y + 21:.0f}" class="k">UNIT {esc(u["id"])} · {len(u["members"])} declarations</text>{text}</g></a>')
    out.append("</svg>")
    return "".join(out)


def build_site(ws: Path, out: Path, cfg: dict, census: dict, ledger: dict, state: dict, src_root: Path, version: str, made: str,
               notice_dirs: tuple = ()) -> dict:
    (out / "assets").mkdir(parents=True)                     # `out` is new: the caller swaps it in when all pages are written
    (out / "notes").mkdir()
    here = Path(__file__).resolve().parent
    assets = next(d for d in (here.parent / "assets" / "site", here / "site") if d.is_dir())
    for f in ("site.css", "site.js"):
        shutil.copy2(assets / f, out / "assets" / f)
    art = cfg["artifact"]
    meta = {"name": cfg["name"], "version": version, "made": made,
            "pin": ("commit " + art["commit"][:12] if art.get("commit") else "not pinned to a commit")
                   + (f", toolchain {art['toolchain']}" if art.get("toolchain") else "")}
    src = Source(src_root)
    idx = {d["id"]: dict(d, module=m["module"], file=m["file"]) for m in census["modules"] for d in m["declarations"]}
    by_name = {d["name"]: d for d in idx.values() if d.get("name")}
    units = [dict(u, id=str(u["id"])) for u in ledger["units"]]
    state = {str(k): v for k, v in state.items()}
    title = {u["id"]: u["title"] for u in units}
    owner = {mid: u["id"] for u in units for mid in u["members"]}
    count = {"units": len(units), "unit_pages": 0, "proof_pages": 0, "steps": 0, "source_pages": 0, "note_pages": 0, "pdf_pages": 0,
             "statements_marked": 0, "lean_lines_marked": 0, "lean_lines_in_notes": 0,
             "states": {k: sum(1 for u in units if state[u["id"]] == k) for k in STATE}}

    src_name = distinct([m["module"] for m in census["modules"]])
    module_of = {m["file"]: m["module"] for m in census["modules"]}
    cone = set(census.get("cone") or [])

    def src_href(file: str, line: int | None = None) -> str:
        return f"src-{src_name.get(module_of.get(file), slug(file))}.html" + (f"#L{line}" if line else "")

    def unit_link(i: str, with_state: bool = True) -> str:
        return f'<a href="unit-{slug(i)}.html">Unit {esc(i)} · {esc(title.get(i, ""))}</a>' + (f" {badge(state[i])}" if with_state and i in state else "")

    # ------------------------------------------------------------------ what exists
    doss, checks, proofs, english, hidden = {}, {}, {}, {}, {}
    for u in units:
        U = ws / "reading" / "units" / u["id"]
        chk = jload(U / "check.json")
        checks[u["id"]], proofs[u["id"]] = chk if isinstance(chk, dict) else None, {}
        # Only a dossier that passes the check on the present sources is shown: the site repeats what was checked.
        shown = state[u["id"]] in ("note", "proofs")
        hidden[u["id"]] = (U / "unit.json").exists() and not shown
        doss[u["id"]] = clean_unit(jload(U / "unit.json")) if shown else None
        files = sorted((U / "proofs").glob("*.json")) if shown and (U / "proofs").is_dir() else []
        names = distinct([pf.stem for pf in files])
        for pf in files:
            P = clean_proof(jload(pf))
            if P and P["declaration"] in idx:
                proofs[u["id"]][P["declaration"]] = (f"proof-{slug(u['id'])}-{names[pf.stem]}.html", P)
        for i in (doss[u["id"]] or {}).get("imports", []):
            if i.get("text") and i.get("id"):
                english.setdefault(i["id"], i["text"])
    for u in units:
        for m in (doss[u["id"]] or {}).get("members", []):
            if m.get("text"):
                english[m["id"]] = m["text"]                 # the unit's own reading wins over a consumer's
    proof_of = {mid: v for u in units for mid, v in proofs[u["id"]].items()}
    notes = []
    for rj in sorted((ws / "notes").glob("*/reader.json")):
        r = jload(rj)
        if (rj.parent / r.get("pdf", "")).is_file():
            notes.append((rj.parent, r))
    in_note: dict = {}                                        # declaration id -> where a note treats it
    for N, r in notes:
        for d in r.get("declarations", []):
            in_note.setdefault(d["id"], []).append((r, d))

    def note_links(mid: str) -> str:
        return " ".join(f'<a class="go" href="note-{slug(r["note"])}.html#at=i-{esc(d["item"])}">{esc(d["where"])} of the note, page {d["page"]}</a>'
                        for r, d in in_note.get(mid, []))

    cases_of = {m["id"]: m["case_readings"] for u in units for m in (doss[u["id"]] or {}).get("members", [])
                if isinstance(m.get("case_readings"), list) and m["case_readings"]}

    def cases_html(mid: str) -> str:
        """The reader's reading of each case of a definition (a constructor, a clause), when the dossier has them."""
        rows = "".join(f'<li><code>{esc(" ".join(str(c.get("lean", "")).split()))}</code><span class="claim">{esc(str(c.get("text", "")))}</span></li>'
                       for c in cases_of.get(mid, []) if isinstance(c, dict))
        return f'<details class="own cases"><summary>Its {many(len(cases_of[mid]), "case")}, read one by one</summary><ul class="plain">{rows}</ul></details>' if rows else ""

    def decl_link(ref: str) -> str:
        d = idx.get(ref) or by_name.get(ref)
        if not d:
            return f"<code>{name_html(ref)}</code>"
        u = owner.get(d["id"])
        return (f'<a href="{src_href(d["file"], d["lines"][0])}"><code>{name_html(d.get("name") or ref)}</code></a>'
                + (f' <a class="in" href="unit-{slug(u)}.html">unit {esc(u)}</a>' if u else ""))

    # ------------------------------------------------------------------ source pages
    for m in census["modules"]:
        n = len(src.lines(m["file"]))
        decls = "".join(f'<li><a href="#L{d["lines"][0]}"><code>{name_html(d.get("name") or "(" + d["kind"] + ")")}</code></a> '
                        f'<span class="dim">{d["kind"]}, {span(*d["lines"])}</span></li>' for d in m["declarations"])
        body = (f'<p class="eyebrow">Lean source</p><h1><code>{name_html(m["module"])}</code></h1>'
                f'<p class="lede">{esc(m["file"])} · {n} lines · {len(m["declarations"])} declarations · '
                + ("in the cone of the root module" if m["module"] in cone else "outside the cone of the root module") + "</p>"
                f'<details class="list"><summary>Its {len(m["declarations"])} declarations</summary><ul class="plain cols">{decls}</ul></details>'
                '<p class="tools"><button type="button" data-wrap aria-pressed="false">Wrap long lines</button></p>'
                + (src.box(m["file"], 1, n, "", f"{m['file']}, all {n} lines", m["module"]) if n else '<p class="grey">The file is empty or missing.</p>'))
        (out / src_href(m["file"])).write_text(page(m["module"], [("Map", "index.html"), ("Lean source", "index.html#source"), (m["module"], "")], body, meta), encoding="utf-8")
        count["source_pages"] += 1

    # ------------------------------------------------------------------ proof pages
    for u in units:
        members = {m["id"]: m for m in (doss[u["id"]] or {}).get("members", [])}
        for mid, (href, P) in proofs[u["id"]].items():
            d, steps = idx[mid], P.get("steps", [])
            ids = {s["id"] for s in steps}
            anchor = distinct([s["id"] for s in steps])
            kids: dict = {}
            for s in steps:
                kids.setdefault(s.get("parent") if s.get("parent") in ids else None, []).append(s)

            def render(s) -> str:
                count["steps"] += 1
                own = s.get("head_lines") if s["id"] in kids else s.get("lines")
                uses = []
                for x in s.get("uses", []):
                    step = x.get("step") if isinstance(x, dict) else (x if x in ids else None)
                    step = step if step in ids else None
                    ref = step or (x.get("decl") if isinstance(x, dict) else x)
                    uses.append(f'<a href="#s-{anchor[step]}" data-step>step {esc(str(step))}</a>' if step else decl_link(str(ref)))
                uses += [f"<code>{name_html(str(x))}</code>" for x in s.get("ambient_uses", [])]
                a, b = s["lines"]
                h = [f'<div class="step" id="s-{anchor[s["id"]]}" data-lines="{a}-{b}" tabindex="0">'
                     f'<p class="sh"><span class="sid">{esc(s["id"])}</span><span class="kind">{esc(s.get("kind", "step"))}</span>'
                     f'<span class="dim">{span(a, b)}</span></p><p class="claim">{esc(s.get("claim", ""))}</p>']
                if s.get("typed_fact"):
                    h.append(f'<p class="fact"><span class="lab">The fact, as Lean states it</span><code>{esc(s["typed_fact"])}</code></p>')
                sr = s.get("simp_reading")
                if isinstance(sr, dict) and sr.get("text"):
                    h.append(f'<p class="second"><span class="lab">A reading of the automation ({esc(str(sr.get("label", "heuristic")))})</span>{esc(sr["text"])}</p>')
                if uses:
                    h.append('<p class="uses"><span class="lab">Uses</span>' + ", ".join(uses) + "</p>")
                if own:
                    h.append(f'<details class="own"><summary>Its Lean {span(*own)}</summary>' + src.box(d["file"], own[0], own[1], f"p{slug(s['id'])}-") + "</details>")
                h.append("</div>")
                inner = "".join(render(c) for c in kids.get(s["id"], []))
                return "<li>" + "".join(h) + (f"<ol>{inner}</ol>" if inner else "") + "</li>"

            tree = "".join(render(s) for s in kids.get(None, []))
            a, b = d["lines"]
            leaves = sum(1 for s in steps if s["id"] not in kids)
            body = (f'<p class="eyebrow">Structured proof · {unit_link(u["id"], False)}</p><h1><code>{name_html(d["name"])}</code></h1>'
                    + (f'<p class="lede">{esc(members[mid]["text"])}</p>' if members.get(mid, {}).get("text") else "")
                    + (f'<p class="summary"><span class="lab">The argument in brief</span>{esc(P["summary"])}</p>' if P.get("summary") else "")
                    + f'<p class="dim">{many(len(steps), "step")}, {leaves} of them leaves. Every step names the Lean lines it renders; choose a step to see them marked in the declaration. '
                      'The Lean text is the authority.</p>'
                    + (f'<p class="links">{note_links(mid)}</p>' if in_note.get(mid) else "")
                    + '<p class="tools"><button type="button" data-wrap aria-pressed="false">Wrap long lines</button></p>'
                    f'<div class="two"><section aria-label="The steps of the proof"><ol class="steps">{tree}</ol></section>'
                    f'<aside aria-label="The Lean declaration">{src.box(d["file"], a, b, "", "", d["name"])}'
                    f'<p class="dim"><a href="{src_href(d["file"], a)}">The declaration in its file</a></p></aside></div>')
            (out / href).write_text(page("Proof of " + d["name"], [("Map", "index.html"), (f"Unit {u['id']}", f"unit-{slug(u['id'])}.html"),
                                                                  ("Proof of " + d["name"].rsplit(".", 1)[-1], "")], body, meta, "wide"), encoding="utf-8")
            count["proof_pages"] += 1

    # ------------------------------------------------------------------ unit pages
    for u in units:
        D, chk, st = doss[u["id"]], checks[u["id"]], state[u["id"]]
        members = {m["id"]: m for m in (D or {}).get("members", [])}
        rows = []
        for mid in u["members"]:
            d = idx.get(mid)
            if not d:
                continue
            m, pr = members.get(mid, {}), proofs[u["id"]].get(mid)
            a, c = d.get("statement_lines") or d["lines"]
            rows.append(f'<li class="decl"><p class="dh"><span class="kind">{d["kind"]}</span><a href="{src_href(d["file"], d["lines"][0])}"><code>{name_html(d.get("name") or "(anonymous)")}</code></a>'
                        f'<span class="dim">{span(*d["lines"])}</span>' + (f'<span class="dim">{esc(m["triage"])}</span>' if m.get("triage") else "") + "</p>"
                        + (f'<p class="claim">{esc(m["text"])}</p>' if m.get("text") else "")
                        + ('<p class="links">' + (f'<a class="go" href="{pr[0]}">Structured proof, {many(len(pr[1].get("steps", [])), "step")}</a>' if pr else "") + note_links(mid) + "</p>"
                           if pr or in_note.get(mid) else "")
                        + cases_html(mid)
                        + f'<details class="own"><summary>The Lean statement</summary>{src.box(d["file"], a, c, f"u{slug(mid)}-")}</details></li>')
        inputs = ""
        if D and D.get("imports"):
            groups: dict = {}
            for i in D["imports"]:
                groups.setdefault(str(i.get("unit") or owner.get(i.get("id")) or ""), []).append(i)
            for g, items in groups.items():
                lis = "".join(f'<li><p class="dh">{decl_link(i.get("id") or i.get("name", ""))}</p>' + (f'<p class="claim">{esc(i["text"])}</p>' if i.get("text") else "") + "</li>" for i in items)
                inputs += f'<details class="list"><summary>{unit_link(g) if g in title else "Outside the units"} <span class="dim">· {many(len(items), "declaration")}</span></summary><ul class="plain">{lis}</ul></details>'
        ambient = [x for x in (D or {}).get("ambient_inputs", []) if isinstance(x, dict)]
        amb = "".join(f'<li><p class="dh"><code>{name_html(str(x.get("name", "")))}</code></p><p class="claim">{esc(str(x.get("text", "")))}</p></li>' for x in ambient)
        takes = ", ".join(unit_link(str(c)) for c in u.get("imports", []) if str(c) in title) or "nothing in the ledger"
        used_by = ", ".join(unit_link(str(c)) for c in u.get("consumers", []) if str(c) in title) or "nothing in the ledger"
        nts = "".join(f'<li><a class="go" href="note-{slug(r["note"])}.html">{esc(r["title"])}</a> <span class="dim">{r.get("pages", "?")} pages; the PDF beside the Lean text</span></li>'
                      for N, r in notes if str(r.get("unit")) == u["id"])
        cnt = (chk or {}).get("counts", {})
        check = ('<p class="grey">A dossier of this unit exists and does not pass the check on the present sources, so nothing of it is shown here. '
                 + esc("; ".join(str(x) for x in (chk or {}).get("problems", [])[:3])[:400]) + "</p>" if hidden[u["id"]] else
                 '<p class="grey">No program check has been run on this unit.</p>' if not chk else
                 f'<p>{cnt.get("statements_at_their_lines", 0)} of {cnt.get("members", 0)} statements stand at the lines the dossier gives; '
                 f'{cnt.get("proofs", 0)} structured proofs with {cnt.get("steps", 0)} steps, {cnt.get("leaves", 0)} of them leaves, the longest of {cnt.get("longest_leaf", 0)} lines; '
                 f'{cnt.get("steps_quoting_their_lines", 0)} steps quote exactly their lines. Checked {esc(str(chk.get("checked", "")))}.</p>'
                 + "".join(f'<p class="bad">Problem: {esc(str(p))}</p>' for p in chk.get("problems", [])))
        body = (f'<p class="eyebrow">Unit {esc(u["id"])} · {esc(", ".join(u.get("modules", [])))}</p><h1>{esc(u["title"])}</h1><p>{badge(st)}</p>'
                + (f'<p class="lede">{esc(D["summary"])}</p>' if D and D.get("summary") else
                   "" if D else '<p class="lede grey">This unit has not been read yet. Below are its declarations as the census sees them: names, kinds and places, without a reading.</p>')
                + (f'<section><h2>Notes</h2><ul class="plain">{nts}</ul></section>' if nts else "")
                + f'<section><h2>What it holds <span class="dim">· {many(len(rows), "declaration")}</span></h2><ul class="plain decls">{"".join(rows)}</ul></section>'
                + f'<section><h2>What it takes for granted</h2><p>{takes}</p>{inputs}'
                + (f'<details class="list"><summary>From Lean\'s own library <span class="dim">· {many(len(ambient), "fact")}</span></summary><ul class="plain">{amb}</ul></details>' if ambient else "") + "</section>"
                + f'<section><h2>Where it is used</h2><p>{used_by}</p></section>'
                + f'<section><h2>The program check</h2>{check}<p class="dim">The check shows that the dossier describes the lines it cites. Whether the English is right is read when a note is written.</p></section>')
        (out / f"unit-{slug(u['id'])}.html").write_text(page(f"Unit {u['id']}: {u['title']}", [("Map", "index.html"), (f"Unit {u['id']}", "")], body, meta), encoding="utf-8")
        count["unit_pages"] += 1

    # ------------------------------------------------------------------ note readers: the PDF beside the Lean text
    for N, r in notes:
        pdf, ns = N / r["pdf"], slug(r["note"])
        shutil.copy2(pdf, out / "notes" / pdf.name)
        geo = pdf_geometry(pdf, N / f"{r['note']}.tex")
        size = lambda p: geo["sizes"].get(p, A4)                # noqa: E731
        pictures = []
        if geo["sizes"] and tool("pdftocairo", "-png", "-r", "144", str(pdf), str(out / "notes" / f"{ns}-p")) is not None:
            for n, f in enumerate(sorted((out / "notes").glob(f"{ns}-p-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1])), 1):
                f.rename(out / "notes" / f"{ns}-{n}.png")
                pictures.append(f"notes/{ns}-{n}.png")
        decl = {d["key"]: d for d in r.get("declarations", [])}
        marks, place = {}, {}

        def first_line(p: int, top: float) -> float:
            """The mark stands at the first line of body text at or below the anchor: an anchor sits a little above
            its statement, and well above a section heading."""
            rows = sorted(w[1] for w in (geo["words"][p - 1] if p <= len(geo["words"]) else []) if w[1] >= top - 6 and w[3] - w[1] > 10.5)
            return rows[0] - 1.3 if rows and rows[0] - top < 40 else top + 3.5

        for n, it in enumerate(r.get("items", [])):
            g = geo["dests"].get(it.get("dest") or "") or {}
            p = g.get("page") or it.get("page") or 1
            place[it["item"]] = (p, first_line(p, size(p)[1] - g["y"]) if g.get("y") is not None else 40.0 + 20 * n, g["x"] if g.get("x") is not None else 99.0)
        items = sorted(r.get("items", []), key=lambda it: place[it["item"]][:2])
        for it in items:                                        # a round mark in the margin, at the statement
            keys = [k for k in it.get("declarations", []) if k in decl]
            p, top, x = place[it["item"]]
            W, H = size(p)
            marks.setdefault(p, []).append(
                f'<a class="mark at" href="#d-{esc(keys[0]) if keys else ""}" data-at="i-{esc(it["item"])}" data-keys="{esc(" ".join(keys))}" data-title="{esc(it["title"])}" '
                f'style="left:{(x - 31) / W * 100:.3f}%;top:{top / H * 100:.3f}%;width:{15 / W * 100:.3f}%" aria-label="{esc(it["title"])}: show the Lean text"><span aria-hidden="true">L</span></a>')
            count["statements_marked"] += 1
        count["lean_lines_in_notes"] += geo["lean_lines_in_tex"]
        for n, ll in enumerate(geo["lean_lines"], 1):           # the LEAN lines of the note, each one a link
            keys = [k for k in ll["keys"] if k in decl]
            if not keys:
                continue
            W, H = size(ll["page"])
            x0, y0, x1, y1 = ll["box"]
            marks.setdefault(ll["page"], []).append(
                f'<a class="mark band" href="#d-{esc(keys[0])}" data-at="l-{n}" data-keys="{esc(" ".join(keys))}" data-title="LEAN line on page {ll["page"]}" '
                f'style="left:{x0 / W * 100:.3f}%;top:{y0 / H * 100:.3f}%;width:{(x1 - x0) / W * 100:.3f}%;height:{(y1 - y0) / H * 100:.3f}%" '
                f'aria-label="LEAN line: {esc(", ".join(decl[k]["name"] for k in keys))}"></a>')
            count["lean_lines_marked"] += 1
        if pictures:
            left = "".join(
                f'<div class="pg" id="pg-{n}" style="aspect-ratio:{size(n)[0]:.2f}/{size(n)[1]:.2f}">'
                f'<img src="{f}" alt="Page {n} of the note" width="{size(n)[0] * 2:.0f}" height="{size(n)[1] * 2:.0f}"' + (' loading="lazy" decoding="async"' if n > 2 else "")
                + f'>{"".join(marks.get(n, []))}</div>' for n, f in enumerate(pictures, 1))
            count["pdf_pages"] += len(pictures)
        else:
            left = f'<iframe class="pdfframe" src="notes/{esc(pdf.name)}" title="The note as a PDF" data-pdf="notes/{esc(pdf.name)}"></iframe>'
        chips = "".join(f'<li><a href="#d-{esc(next((k for k in it.get("declarations", []) if k in decl), ""))}" data-at="i-{esc(it["item"])}" data-page="{it.get("page", 1)}" '
                        f'data-keys="{esc(" ".join(k for k in it.get("declarations", []) if k in decl))}" data-title="{esc(it["title"])}">{esc(it["title"])}<small>p. {it.get("page", "?")}</small></a></li>'
                        for it in items)
        cards = []
        for k, d in decl.items():
            c = idx.get(d.get("id"))                             # only what the census knows: a note's index cannot point elsewhere
            if c is None:
                continue
            a, b = c["lines"]
            sa, sb = c.get("statement_lines") or c["lines"]
            u, pr = owner.get(d["id"]), proof_of.get(d["id"])
            cards.append(
                f'<article class="card" id="d-{esc(k)}" data-key="{esc(k)}"><p class="dh"><span class="kind">{esc(d["kind"])}</span><code class="name">{name_html(d["name"])}</code></p>'
                f'<p class="dim">{esc(d["where"])} of the note, page {d["page"]} · ' + ("a declaration of the unit this note reads" if d.get("in_unit") else "taken from another unit") + "</p>"
                + (f'<p class="claim">{esc(english[d["id"]])}</p>' if english.get(d["id"]) else "")
                + src.box(c["file"], sa, sb, f"k{slug(k)}-s", "", d["name"] + ", the statement") + cases_html(d["id"])
                + (f'<details class="own"><summary>The whole declaration, lines {a}–{b} ({b - a + 1} lines)</summary>{src.box(c["file"], a, b, f"k{slug(k)}-f")}</details>' if (a, b) != (sa, sb) else "")
                + '<p class="links">' + (f'<a class="go" href="{pr[0]}">Structured proof, {many(len(pr[1].get("steps", [])), "step")}</a>' if pr else "")
                + (f'<span><a href="unit-{slug(u)}.html">Unit {esc(u)}</a> {badge(state[u])}</span>' if u else "") + f'<a href="{src_href(c["file"], a)}">In its file</a></p></article>')
        body = (f'<div class="reader"><section class="pdfpane" aria-label="The note, page by page" tabindex="0">{left}</section>'
                '<section class="leanpane" aria-label="The Lean text of the chosen statement"><div class="lp-head">'
                '<p class="eyebrow">Note' + (f' on <a href="unit-{slug(r["unit"])}.html">unit {esc(str(r["unit"]))}</a>' if r.get("unit") and str(r["unit"]) in title else "") + f'</p><h1>{esc(r["title"])}</h1>'
                f'<p class="tools"><a class="go" href="notes/{esc(pdf.name)}">Open the PDF</a><span class="dim">{r.get("pages", "?")} pages · SHA-256 {esc(str(r.get("pdf_sha256", ""))[:12])}…</span>'
                '<button type="button" data-wrap aria-pressed="false">Wrap long lines</button></p>'
                f'<nav aria-label="Statements of the note"><ol class="chips">{chips}</ol></nav>'
                '<p class="now" aria-live="polite"></p></div>'
                f'<div class="cards">{"".join(cards)}</div></section></div>')
        (out / f"note-{ns}.html").write_text(page(r["title"], [("Map", "index.html"), ("Notes", "index.html#notes"), (r["title"], "")], body, meta, "wide reading"), encoding="utf-8")
        count["note_pages"] += 1

    # ------------------------------------------------------------------ the map
    t, n = census["totals"], count["states"]
    table = "".join(f'<tr><td>{esc(u["id"])}</td><td><a href="unit-{slug(u["id"])}.html">{esc(u["title"])}</a></td><td class="num">{len(u["members"])}</td>'
                    f'<td>{badge(state[u["id"]])}</td><td class="num">{len(proofs[u["id"]]) or ""}</td>'
                    f'<td class="num">{(checks[u["id"]] or {}).get("counts", {}).get("leaves", "")}</td></tr>' for u in units)
    plist = "".join(f'<tr><td><a href="{href}"><code>{name_html(idx[mid]["name"])}</code></a></td><td>{unit_link(u["id"], False)}</td>'
                    f'<td class="num">{len(P.get("steps", []))}</td><td class="num">{idx[mid]["lines"][1] - idx[mid]["lines"][0] + 1}</td><td>{note_links(mid)}</td></tr>'
                    for u in units for mid, (href, P) in proofs[u["id"]].items())
    nlist = "".join(f'<li><a class="go" href="note-{slug(r["note"])}.html">{esc(r["title"])}</a> <span class="dim">{r.get("pages", "?")} pages'
                    + (f', unit {esc(str(r["unit"]))}' if r.get("unit") else "") + f', {len(r.get("declarations", []))} declarations in its concordance</span></li>' for N, r in notes)
    slist = "".join(f'<li><a href="{src_href(m["file"])}"><code>{name_html(m["module"])}</code></a> <span class="dim">{m["lines"]} lines, {len(m["declarations"])} declarations</span></li>' for m in census["modules"])
    # the artifact's own licence and notices: the site republishes its Lean text
    terms = []
    for d in notice_dirs or (src_root,):
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            if f.is_file() and re.match(r"(?i)^(licen[cs]e|copying|notice|authors|copyright)([.-].*)?$", f.name) and f.stat().st_size <= 300000 and f.name not in terms:
                (out / "terms").mkdir(exist_ok=True)
                (out / "terms" / (f.name + ".txt")).write_bytes(f.read_bytes())
                terms.append(f.name)
    terms_html = ('<section id="terms"><h2>The artifact\'s own terms</h2>'
                  + ('<p class="dim">Found with the Lean sources and copied here unchanged. The Lean text on this site belongs to its authors and is shown under these terms.</p>'
                     '<ul class="plain">' + "".join(f'<li><a href="terms/{esc(n)}.txt">{esc(n)}</a></li>' for n in terms) + "</ul>" if terms else
                     '<p class="grey">No licence or notice file was found with the Lean sources. The Lean text shown on this site belongs to its authors: '
                     'find out its terms before this site is published anywhere.</p>') + "</section>")
    count["terms_files"] = len(terms)
    proposal = not (ws / "reading" / "ledger" / "units.json").exists()
    reach = jload(ws / "reading" / "ledger" / "kernel-reach.json")
    rests = ""
    if isinstance(reach, dict) and isinstance(reach.get("root_axioms"), dict) and reach["root_axioms"]:
        trs = "".join(f'<tr><td>{decl_link(str(n))}</td><td>{", ".join(f"<code>{esc(str(x))}</code>" for x in ax) if ax else "no axiom"}</td></tr>'
                      for n, ax in sorted(reach["root_axioms"].items()) if isinstance(ax, list))
        rests = ('<section id="axioms"><h2>What the final theorems rest on</h2><p class="dim">From the reading agent\'s export of Lean\'s kernel'
                 + (f' (Lean {esc(str(reach["lean_version"]))})' if reach.get("lean_version") else "")
                 + ': the axioms each theorem depends on. This site repeats the record; it does not run Lean.</p>'
                 f'<div class="scroll"><table><thead><tr><th>Theorem</th><th>Axioms</th></tr></thead><tbody>{trs}</tbody></table></div></section>')
    body = ('<p class="eyebrow">A Lean artifact, read back into mathematics</p>' f'<h1>{esc(cfg["name"])}</h1>'
            f'<p class="lede">{t["modules"]} modules, {t["lines"]:,} lines, {t["declarations"]:,} declarations'
            + (f'; {t.get("declarations_in_cone", "?")} of them in the cone of <code>{name_html(census["root"])}</code>' if census.get("root") else "")
            + f'. <code>sorry</code> in the source: {t["sorry"]}. <code>axiom</code> declarations in the source: {len(t["axioms"])}.</p>'
            f'<p class="counts"><span class="badge note">{n["note"]} with a note</span><span class="badge proofs">{n["proofs"]} with checked structured proofs</span>'
            f'<span class="badge dossier">{n["dossier"]} with a dossier</span><span class="badge unread">{n["unread"]} not read yet</span></p>'
            + ('<p class="grey">The units shown are the proposal made from names and imports. The reading agent has not written its ledger yet.</p>' if proposal else "")
            + '<section><h2>The map</h2><p class="dim">A unit stands below the units it uses; an arrow that follows from two others is left out. Grey and dashed means not read yet. Choose a unit.</p>'
            + (f'<div class="mapbox">{unit_map(units, state)}</div>' if len(units) <= 80 else '<p class="grey">There are too many units to draw. The table below lists them.</p>') + "</section>"
            '<section id="units"><h2>Units</h2><div class="scroll"><table><thead><tr><th>Unit</th><th>Title</th><th class="num">Declarations</th><th>State</th><th class="num">Proofs</th>'
            f'<th class="num">Leaf steps</th></tr></thead><tbody>{table}</tbody></table></div></section>'
            '<section id="notes"><h2>Notes</h2><p class="dim">A note is the mathematics of a unit in ordinary language. Its reader shows the PDF beside the Lean text.</p>'
            f'<ul class="plain">{nlist or "<li class=grey>No note has been built yet.</li>"}</ul></section>'
            '<section id="proofs"><h2>Structured proofs</h2><p class="dim">A structured proof is a tree of steps; each step says one thing and names the Lean lines that prove it.</p>'
            + ('<div class="scroll"><table><thead><tr><th>Declaration</th><th>Unit</th><th class="num">Steps</th><th class="num">Lean lines</th><th>In a note</th></tr></thead>'
               f'<tbody>{plist}</tbody></table></div>' if plist else '<p class="grey">No structured proof has been written yet.</p>') + "</section>"
            + rests + f'<section id="source"><h2>Lean source</h2><ul class="plain cols">{slist}</ul></section>' + terms_html + ''
            '<section><h2>How far to trust this site</h2><p>A program compared every quotation and every line range with the Lean source. That shows the dossiers describe the lines they cite; '
            'it does not show that the English is right. A note says what its author read and what was taken for granted. Whether the artifact compiles, and on which axioms its theorems rest, '
            'is said by Lean and recorded in the notes, not by this site.</p></section>')
    (out / "index.html").write_text(page("Map", [("Map", "")], body, meta), encoding="utf-8")
    (out / "site.json").write_text(json.dumps({"schema": "readback/site/1", "made": made, "version": version, "counts": count}, indent=1) + "\n", encoding="utf-8")
    return count
