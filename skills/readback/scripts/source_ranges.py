"""Checked slices of a UTF-8 Lean file. Positions count Unicode code points from one."""
from __future__ import annotations

import bisect
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def whole_quote(text: str) -> str:
    """Line quotations in readback/proof/1 ignore line endings and trailing horizontal space."""
    return "\n".join(line.rstrip(" \t") for line in text.replace("\r\n", "\n").split("\n"))


class SourceFile:
    def __init__(self, data: bytes):
        self.text = data.decode("utf-8")
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.starts = [0] + [m.end() for m in re.finditer("\n", self.text)]
        self.line_count = len(self.starts) - int(self.starts[-1] == len(self.text))

    def position(self, offset):
        line = bisect.bisect_right(self.starts, offset)
        return [line, offset - self.starts[line - 1] + 1]

    def line_stop(self, line):
        if line == len(self.starts):
            return len(self.text)
        end = self.starts[line] - 1
        return end - int(end > self.starts[line - 1] and self.text[end - 1] == "\r")

    def offset(self, line, col):
        if type(line) is not int or not 1 <= line <= len(self.starts) or type(col) is not int:
            raise ValueError("invalid source position")
        start = self.starts[line - 1]
        if not 1 <= col <= self.line_stop(line) - start + 1:
            raise ValueError("column outside source line")
        return start + col - 1

    def offsets(self, span):
        if not isinstance(span, list) or len(span) != 4:
            raise ValueError("span must be [start line, start column, end line, end column]")
        a, b = self.offset(*span[:2]), self.offset(*span[2:])
        if a >= b:
            raise ValueError("empty or reversed source span")
        return a, b

    def line_range(self, lines):
        if not isinstance(lines, list) or len(lines) != 2 or any(type(n) is not int for n in lines):
            raise ValueError("lines must be two integers")
        a, b = lines
        if not 1 <= a <= b <= self.line_count:
            raise ValueError(f"lines {lines} outside the file or reversed")
        return self.starts[a - 1], self.line_stop(b)

    def coordinates(self, a, b):
        return self.position(a) + self.position(b)

    def line_numbers(self, a, b):
        return [self.position(a)[0], self.position(max(a, b - 1))[0]]

    def receipt(self, a, b):
        return {"span": self.coordinates(a, b), "sha256": digest(self.text[a:b])}


@dataclass(frozen=True)
class Token:
    word: str
    a: int
    b: int
    depth: int


# Keep literal contents out of the syntax inventory without changing source offsets.
LEX = re.compile(r"""\s+|--[^\n]*|/-|r(\#*)"|"(?:(?:\\.)|[^"\\])*"|«[^»]*»|'(?:\\.|[^'\\\n])'|[\w][\w'!?]*|:=|=>|<;>|.""", re.S)
COMMENT = re.compile(r"/-|-/")


def tokens(text, start=0, stop=None):
    stop = len(text) if stop is None else stop
    i, depth = start, 0
    while i < stop:
        m = LEX.match(text, i, stop)
        word, j = m[0], m.end()
        if word == "/-":
            level = 1
            for mark in COMMENT.finditer(text, j, stop):
                level += 1 if mark[0] == "/-" else -1
                if level == 0:
                    j = mark.end()
                    break
            else:
                j = stop
        elif m[1] is not None:
            closing = '"' + m[1]
            end = text.find(closing, j, stop)
            j = stop if end < 0 else end + len(closing)
            yield Token(text[i:j], i, j, depth)
        elif not word.isspace() and not word.startswith("--"):
            if word in (")", "]", "}", "⟩", "⦄"):
                depth -= 1
            yield Token(word, i, j, depth)
            if word in ("(", "[", "{", "⟨", "⦃"):
                depth += 1
        i = j


def delimiter(text):
    """Lexical fallback for the line census; syntax extensions require native ranges."""
    for t in tokens(text):
        if t.depth == 0 and (t.word == ":=" or t.word == "where" or
                             (t.word == "|" and not text[text.rfind("\n", 0, t.a) + 1:t.a].strip()
                              and "=>" in text[t.a:(text.find("\n", t.a) + 1 or len(text) + 1) - 1])):     # an alternative `| pat => …`, not `|x| = x`
            return t
    return None


def module_path(root, file):
    if not isinstance(file, str) or not file or Path(file).is_absolute() or Path(file).suffix != ".lean":
        raise ValueError(f"expected an artifact-relative Lean file, got {file!r}")
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing Lean file in the artifact: {file}")
    return path


def lean_diagnostic(output, status):
    """Keep the compiler's error and its continuation, after any Lake setup messages."""
    located = re.search(r"^.+:\d+:\d+:\s*error(?:\([^)]+\))?:", output, re.MULTILINE)
    primary = located or re.search(r"^(?:error(?:\([^)]+\))?|uncaught exception):", output, re.MULTILINE)
    if primary:
        detail = output[primary.start():].strip()
    else:
        detail = "\n".join(line for line in output.splitlines()
                           if not line.startswith(("info:", "warning:"))).strip()
    if not detail:
        return f"process exited with status {status}"
    first, separator, rest = detail.partition("\n")
    if re.search(r"unknown module prefix|object file .* does not exist|missing data file for module", first):
        first += ". Build the artifact first with its normal target or check the import path."
    return first + separator + rest


def parsed_ranges(root, file, source, helper):
    """Run the artifact's Lean frontend only on explicit request, never during a source-only check."""
    path = module_path(root, file)
    module = ".".join(Path(file).with_suffix("").parts)
    command = ["lean"]
    lake_script = (root / "lakefile.lean").is_file()
    if lake_script or (root / "lakefile.toml").is_file():
        # Lake creates a missing manifest on load and compiles a Lean lakefile
        # under .lake/. A TOML package may put all its build outputs elsewhere.
        missing = []
        if not (root / "lake-manifest.json").is_file():
            missing.append("lake-manifest.json")
        if lake_script and not (root / ".lake").is_dir():
            missing.append(".lake/")
        if missing:
            raise ValueError(f"build the artifact first with its Lake target (for example, `lake build`). "
                             f"Missing {', '.join(missing)} in {root}.")
        command = ["lake", "env", "lean"]
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "ranges.json"
        proc = subprocess.run([*command, "--run", str(helper), str(path), module, str(output)],
                              cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode:
            raise ValueError(f"Lean range extraction failed: {lean_diagnostic(proc.stdout, proc.returncode)}")
        rows = json.loads(output.read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256:
        raise ValueError(f"{file} changed during Lean range extraction")
    result = {}
    for row in rows:
        did = f"{module}:{row['name_at'][0]}:{row['name_at'][1]}"
        if did in result:
            raise ValueError(f"ambiguous parser range for {did}")
        result[did] = {key: (source.receipt(*source.offsets(row[key])) if row[key] is not None else None) for key in ("statement", "value")}
    return result


def checked_ranges(src, decl, records):
    """Independently bind supplied statement/value digests to the named declaration and the raw source."""
    if not isinstance(records, dict) or set(records) != {"statement", "value"}:
        raise ValueError("source_ranges must contain statement and value")
    left, right = src.line_range(decl["lines"])
    parts = {}
    for key in ("statement", "value"):
        r = records[key]
        if key == "value" and r is None and decl["kind"] in {"axiom", "opaque", "inductive", "structure", "class"}:
            parts[key] = None
            continue
        if not isinstance(r, dict):
            raise ValueError(f"invalid {key} range")
        a, b = src.offsets(r.get("span"))
        if not left <= a < b <= right:
            raise ValueError(f"{key} range outside declaration")
        if digest(src.text[a:b]) != r.get("sha256"):
            raise ValueError(f"{key} range hash differs from source")
        parts[key] = (a, b)
    a, b = parts["statement"]
    c = parts["value"][0] if parts["value"] is not None else right
    name_line, name_col = map(int, decl["id"].rsplit(":", 2)[1:])
    if b > c or (decl.get("written") and not a <= src.offset(name_line, name_col) < b):
        raise ValueError("statement and value ranges are misordered or miss the declaration name")
    return parts
