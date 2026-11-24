"""Check the source ownership, written intermediate facts and references of one proof."""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict

from source_ranges import tokens, whole_quote


def typed_sites(src, code):
    """Find written type annotations. Layout and punctuation are measured on the original tokens."""
    for i, head in enumerate(code):
        if head.word not in {"have", "obtain", "suffices", "show"}:
            continue
        line, col = src.position(head.a)
        if i and code[i - 1].word == ".":     # a qualified name is not a command
            continue
        first = None
        # An anonymous suffices takes a proposition; named forms introduce a colon.
        named = head.word == "suffices" and i + 2 < len(code) and code[i + 2].word == ":"
        if head.word == "show" or head.word == "suffices" and not named:
            first = i + 1
        last = i
        # A let expression is itself a type. Its initializer and separator
        # belong to that type, even without parentheses.
        let_bindings = []
        for j in range(i + 1, len(code)):
            t = code[j]
            row, column = src.position(t.a)
            if t.depth < head.depth or (row > line and column <= col and t.depth == head.depth):
                break
            if t.depth == head.depth:
                in_type = first is not None and j >= first
                if in_type and t.word == "let":
                    let_bindings.append("binder")
                elif in_type and t.word == ":=" and let_bindings and let_bindings[-1] == "binder":
                    let_bindings[-1] = "value"
                elif in_type and t.word == ";" and let_bindings and let_bindings[-1] == "value":
                    let_bindings.pop()
                elif t.word in {":=", "from", ";", "<;>"} or (t.word == "by" and
                        not (in_type and (j == first or code[j - 1].word == ":="))):
                    break
                elif first is None and t.word == ":":
                    first = j + 1
            last = j
        if first is not None and first <= last:
            yield head, code[first].a, code[last].b


def branch_families(src, code):
    """Layout-delimited written branches. No inference about goals produced by a tactic."""
    by_line = {}
    for t in code:
        by_line.setdefault(src.position(t.a)[0], []).append(t)
    rows = list(by_line.values())
    # A definition by equations has no split keyword. All outer bars belong to
    # one parent; its children own the bars and the bodies of the equations.
    if rows and rows[0][0].word == "|":
        col = src.position(rows[0][0].a)[1]
        arms = []
        for row in rows:
            if row[0].word == "|" and src.position(row[0].a)[1] == col:
                arms.append((row[0], row[-1].b))
            elif arms:
                arms[-1] = (arms[-1][0], row[-1].b)
        yield None, arms
    for i, row in enumerate(rows):
        start = next((j for j, t in enumerate(row)
                      if t.word in {"induction", "cases", "rcases", "by_cases", "match"}), None)
        if start is None:
            continue
        head = row[start]
        if start and row[start - 1].word == ".":
            continue
        markers, ends = [], []
        # A horizontal “with | ... => ... | ... => ...” has distinct source
        # ranges, too. Alternative patterns sharing a single arrow share a body.
        if any(t.word == "with" for t in row[start + 1:]):
            may_start = True
            previous = head
            for t in row[start + 1:]:
                if t.word == "|" and t.depth == head.depth and may_start:
                    if markers:
                        ends[-1] = previous.b
                    markers.append((src.position(row[0].a)[1], t))
                    ends.append(row[-1].b)
                    may_start = False
                elif t.word == "=>" and t.depth == head.depth:
                    may_start = True
                previous = t
        indent = src.position(row[0].a)[1] + int(row[0].word in {"·", "|", "case"})
        for nxt in rows[i + 1:]:
            first = nxt[0]
            col = src.position(first.a)[1]
            if col < indent or (markers and col < markers[0][0]):
                break
            if first.word in {"|", "case", "·"} and (not markers or col == markers[0][0]):
                markers.append((col, first))
                ends.append(nxt[-1].b)
            elif not markers:
                break
            elif col == markers[0][0]:
                if head.word == "by_cases" and len(markers) == 1 and markers[0][1].word == "·":
                    markers.append((col, first))
                    ends.append(nxt[-1].b)
                break
            else:
                ends[-1] = nxt[-1].b
        if markers:
            yield head, [(t, end) for (_, t), end in zip(markers, ends)]


def one_command(src, code):
    """Rule out visible sequences under an indivisible exception; the reason still requires review."""
    if not code:
        return False
    head = code[0]
    line, indent = src.position(head.a)
    for t in code[1:]:
        row, col = src.position(t.a)
        if t.depth == head.depth and (t.word in {";", "<;>"} or
                (row > line and col <= indent and t.word not in {")", "]", "}", "⟩", "⦄"})):
            return False
    return True


def interval(src, item, lines_key="lines", span_key="span"):
    line_range = src.line_range(item.get(lines_key))
    if span_key not in item:
        return line_range
    a, b = src.offsets(item[span_key])
    if src.line_numbers(a, b) != item[lines_key]:
        raise ValueError(f"{span_key} disagrees with {lines_key}")
    return a, b


def validate_proof(src, decl, body, proof, declarations, bound):
    problems, reports, stat = [], [], Counter()
    step_by_id, places, ranges, owned, children = {}, {}, {}, {}, defaultdict(list)
    report = {"declaration": decl["id"], "steps": reports}
    lo, hi = body
    code = list(tokens(src.text, lo, hi))
    # The opening 'by' introduces the value; an inline tactic following it still needs an owner.
    if code and code[0].word == "by":
        code = code[1:]
    proof_lines = len({ln for t in code for ln in range(src.position(t.a)[0], src.position(t.b - 1)[0] + 1)})
    stat["proof_lines"] = proof_lines
    starts = [t.a for t in code]
    rows = proof.get("steps")
    if not isinstance(rows, list) or not rows:
        problems.append("expected a nonempty list of steps")
        rows = []

    def fail(sid, msg):
        problems.append(f"step {sid}: {msg}")
        if sid in places:
            reports[places[sid]]["problems"].append(msg)

    def in_body(ab, exact):
        a, b = ab
        # Old line records quote the complete first/last line, including indentation
        # or a same-line signature. Only their intersection with the value is owned.
        if exact:
            if not lo <= a < b <= hi:
                raise ValueError("span outside proof value")
        elif not (src.position(lo)[0] <= src.position(a)[0] and
                  src.position(max(a, b - 1))[0] <= src.line_numbers(lo, hi)[1]):
            raise ValueError("lines outside proof value")
        return max(lo, a), min(hi, b)

    for step in rows:
        stat["steps"] += 1
        sid = step.get("id") if isinstance(step, dict) else None
        if not isinstance(sid, str) or not sid or sid in step_by_id:
            problems.append(f"invalid or duplicate step id {sid!r}")
            continue
        places[sid] = len(reports)
        step_by_id[sid] = step
        reports.append({"id": sid, "problems": []})
        par = step.get("parent")
        if par is not None and not isinstance(par, str):
            fail(sid, "parent must be a step id or null")
            continue
        children[par].append(sid)
        if not isinstance(step.get("kind"), str) or not step["kind"].strip():
            fail(sid, "missing step kind")
        if not isinstance(step.get("claim"), str) or not step["claim"].strip():
            fail(sid, "missing claim")

    owners = []
    for sid, step in step_by_id.items():
        detail = reports[places[sid]]
        try:
            a, b = interval(src, step)
            full = in_body((a, b), "span" in step)
            ranges[sid] = full
            detail["source"] = src.receipt(a, b)
            detail["comparison"] = "exact-utf8" if "span" in step else "line-text"
            text = src.text[a:b]
            quote = step.get("lean")
            if not isinstance(quote, str) or (text != quote if "span" in step else whole_quote(text) != whole_quote(quote)):
                fail(sid, "quotation differs from its source range")
            else:
                stat["steps_quoting_their_lines"] += 1
            if children[sid]:
                if step.get("head_lines") is None and "head_span" not in step:
                    continue
                own = in_body(interval(src, step, "head_lines", "head_span"), "head_span" in step)
                if not full[0] <= own[0] <= own[1] <= full[1]:
                    raise ValueError("head outside its parent step")
            else:
                if step.get("head_lines") is not None or "head_span" in step:
                    fail(sid, "a leaf cannot have a separate head")
                own = full
                n = step["lines"][1] - step["lines"][0] + 1
                stat["leaves"] += 1
                stat["leaf_lines"] += n
                stat["longest_leaf"] = max(stat["longest_leaf"], n)
                if n > bound:
                    reason = step.get("indivisible")
                    if not isinstance(reason, str) or not reason.strip():
                        fail(sid, f"leaf exceeds {bound} lines without an indivisible reason")
                    elif not one_command(src, code[bisect.bisect_left(starts, own[0]):bisect.bisect_left(starts, own[1])]):
                        fail(sid, "indivisible exception covers several written commands")
                    else:
                        detail["indivisible"] = reason
                        stat["indivisible_leaves"] += 1
            owned[sid] = own
            owners.append((*own, sid))
        except ValueError as exc:
            fail(sid, str(exc))

    ancestors = {}
    for sid, step in step_by_id.items():
        seen = set()
        parent = step.get("parent")
        while isinstance(parent, str):
            if parent == sid or parent in seen:
                fail(sid, "cyclic parent chain")
                break
            if parent not in step_by_id:
                fail(sid, f"unknown parent {parent}")
                break
            seen.add(parent)
            parent = step_by_id[parent].get("parent")
        ancestors[sid] = seen
        parent = step.get("parent")
        if isinstance(parent, str) and parent in ranges and sid in ranges:
            a, b = ranges[parent]
            x, y = ranges[sid]
            if not a <= x <= y <= b:
                fail(sid, f"outside parent {parent}")
    # Sibling envelopes may meet, but may not swallow each other's descendants.
    for siblings in children.values():
        ordered = sorted((ranges[s][0], ranges[s][1], s) for s in siblings if s in ranges)
        for (_, previous_end, previous), (start, _, current) in zip(ordered, ordered[1:]):
            if start < previous_end:
                fail(current, f"overlaps sibling {previous}")

    for sid, step in step_by_id.items():
        refs = step.get("uses", [])
        if not isinstance(refs, list):
            fail(sid, "uses must be a list")
            continue
        for use in refs:
            if isinstance(use, str):
                kind, ref = ("step" if use in step_by_id else "decl"), use
            elif isinstance(use, dict) and len(use) == 1 and next(iter(use)) in {"step", "decl"}:
                kind, ref = next(iter(use.items()))
            else:
                fail(sid, f"malformed reference {use!r}")
                continue
            if not isinstance(ref, str) or not ref:
                fail(sid, "reference must be a nonempty string")
            elif kind == "decl":
                stat["declaration_references"] += 1
                if ref not in declarations:
                    fail(sid, f"unknown or ambiguous declaration {ref}")
            else:
                stat["step_references"] += 1
                target = step_by_id.get(ref)
                if not target:
                    fail(sid, f"unknown step {ref}")
                elif not (places[ref] < places[sid] and ref not in ancestors[sid] and
                          (target.get("parent") is None or isinstance(target.get("parent"), str) and target["parent"] in ancestors[sid]) and target.get("kind") != "case" and
                          ref in ranges and sid in ranges and ranges[ref][1] <= ranges[sid][0]):
                    fail(sid, f"step {ref} is not in scope")

    intro = proof.get("intro_lines", [])
    if not isinstance(intro, list):
        problems.append("intro_lines must be a list of line ranges")
        intro = []
    held = sum(x[1] - x[0] + 1 for x in intro if isinstance(x, list) and len(x) == 2 and all(isinstance(y, int) for y in x))
    if held > bound:                                        # an introduction is a few opening lines, not a place to park a proof
        problems.append(f"the introduction holds {held} lines; at most {bound} may stand outside the steps")
    for lines in intro:
        try:
            a, b = in_body(src.line_range(lines), False)
            if ranges and b > min(r[0] for r in ranges.values()):
                problems.append(f"introduction {lines} extends into or beyond the first step")
            owners.append((a, b, None))
        except ValueError as exc:
            problems.append(f"introduction: {exc}")

    # Assign each original token to exactly one leaf, parent head or introduction.
    # The sorted intervals also let the typed-site and branch checks find their owners.
    assignments = [[] for t in code]
    for a, b, sid in owners:
        for k in range(bisect.bisect_left(starts, a), bisect.bisect_left(starts, b)):
            if code[k].b <= b:
                assignments[k].append(sid)
    owner = {}
    gaps, overlaps = set(), set()
    for t, matches in zip(code, assignments):
        if len(matches) == 1:
            owner[t.a] = matches[0]
        else:
            (overlaps if matches else gaps).add(src.position(t.a)[0])
    if gaps:
        problems.append(f"unowned proof text on lines {sorted(gaps)}")
    if overlaps:
        problems.append(f"multiply owned proof text on lines {sorted(overlaps)}")

    sites = defaultdict(list)
    for head, a, b in typed_sites(src, code):
        sid = owner.get(head.a)
        if sid is None:
            problems.append(f"typed {head.word} on line {src.position(head.a)[0]} needs its own step")
            continue
        sites[sid].append((head, a, b))
    for sid, step in step_by_id.items():
        facts = sites[sid]
        if not facts:
            if step.get("typed_fact") is not None:
                fail(sid, "typed_fact has no corresponding written type")
            continue
        stat["typed_steps"] += len(facts)
        head, a, b = facts[0]
        reports[places[sid]]["type_source"] = src.receipt(a, b)
        x, y = owned[sid]
        before = [t for t in code[bisect.bisect_left(starts, x):bisect.bisect_left(starts, head.a)]
                  if t.word not in {"·", "by"}]
        # An inline branch label may precede the command on its first line.
        if before and before[0].word in {"|", "case"} and any(t.word == "=>" for t in before):
            before = before[next(i for i, t in enumerate(before) if t.word == "=>") + 1:]
        if len(facts) != 1 or before or b > y:
            fail(sid, "each written intermediate type needs its own step")
        elif step.get("typed_fact") != src.text[a:b]:
            fail(sid, f"typed_fact differs from the complete source type at {src.coordinates(a, b)}")
        else:
            stat["typed_facts_in_source"] += 1

    for head, markers in branch_families(src, code):
        actual = [owner.get(t.a) for t, _ in markers]
        if head is None:
            first_child = step_by_id.get(actual[0], {})
            sid = first_child.get("parent")
            word, pos = "equations", markers[0][0].a
        else:
            sid = owner.get(head.a)
            word, pos = head.word, head.a
        if (not isinstance(sid, str) or None in actual or set(actual) != set(children[sid]) or
                len(set(actual)) != len(markers) or any(step_by_id[s].get("kind") != "case" or
                ranges[s][1] < end for s, (_, end) in zip(actual, markers))):
            msg = f"{word} on line {src.position(pos)[0]} needs a distinct case child covering each written branch"
            if not isinstance(sid, str):
                problems.append(msg)
            else:
                fail(sid, msg)

    report.update(proof_lines=proof_lines, leaves=stat["leaves"], leaf_lines=stat["leaf_lines"],
                  lines_per_leaf=round(stat["leaf_lines"] / stat["leaves"], 2) if stat["leaves"] else None,
                  exceptions=[s["id"] for s in reports if "indivisible" in s], problems=problems)
    return report, stat
