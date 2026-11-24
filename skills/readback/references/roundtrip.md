# The round trip: formalizing back from structured proofs

Status: **design**; not implemented in `rb.py` yet. It is the next step of the project.

## The question

A structured proof claims to carry the whole argument of a Lean proof in small steps with typed facts. If that
is true, a prover who sees only the statement and the structured proof, and not the original proof, can write a
new Lean proof of the same statement. Doing this many times measures two things: whether the structured proofs
are faithful, and whether formalization from them is stable.

## Protocol

1. **Seal by parsed spans.** For each theorem of a unit, replace the proof body by `sorry` using the exact
   source span of the value (a parser's, not a line heuristic), and pin the elaborated target type and its
   context, so that "the same statement" has one meaning.
2. **Isolate the prover.** A fresh checkout is not enough: it still holds the original proofs in object files,
   in the source, in the history and in declarations downstream. The formalizing run gets a separate environment
   with only: the toolchain, the prerequisites the theorem may use, the target statement, and the structured
   proof with its `lean` quotations removed (claims, typed facts and `uses` stay). No compiled target, nothing
   downstream of it, no caches, no history, no network. Record the search paths and a manifest of every input.
   Check for aliases through which the target itself could be retrieved.
3. **Formalize.** One independent run per attempt, several attempts per theorem (start with five), a fixed
   budget per attempt.
4. **Verify separately.** A different process compiles each submitted proof in the pinned environment with the
   target replaced, and compares:
   - the target type with the pinned one;
   - the kernel axiom closure with the original's;
   - the declarations actually used;
   - per step, the intermediate facts with the typed facts of the structured proof, up to definitional
     equality; an alternative valid derivation is recorded as such, not as a failure.
5. **Controls.** Run the same theorems with the statement only, no structured proof, under the same budget.
   The difference between the two success rates is what the structured proofs contribute.
6. **Report per theorem**: attempts, successes, the first failed step, attempts that succeeded outside the
   structure, inconclusive cases. A unit *reconstructs stably* when every theorem succeeds in most attempts
   along its steps and clearly more often than its control.

## What the outcomes mean

- A step that repeatedly fails points to a gap in the structured proof: the claim is too coarse, a `uses` is
  missing, a typed fact is wrong. Send it to the reader as a `result`.
- A theorem that succeeds only by automation says little about the structured proof; mark it.
- A theorem that never succeeds although its steps look complete may be hard for the prover, not badly
  described; compare with the original proof only after the attempts are recorded.

## What to build

`rb.py seal UNIT` (the sealed statements, the stripped structured proofs, the input manifest), an isolated
runner, `rb.py roundtrip UNIT` (the separate verifier: compile, compare, write
`reading/lean/roundtrip/<unit>.json`), and a column in `STATUS.md`. The contracts carry part of what is needed
(`statement_lines` and `value_col` to seal, `typed_fact` and scoped `uses` to guide); exact spans and the pinned
elaborated type need a Lean-side tool, which is the reader's.

The isolation and the controls in this protocol follow the review by the reader of the first large case.
