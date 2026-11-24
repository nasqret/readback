import Lean

open Lean

/-- Original syntax positions, expressed in one-based Unicode columns. -/
private def point (map : FileMap) (pos : String.Pos.Raw) : Array Nat :=
  let p := map.toPosition pos
  #[p.line, p.column + 1]

private def isValue (s : Syntax) : Bool :=
  [``Parser.Command.declValSimple, ``Parser.Command.declValEqns,
   ``Parser.Command.whereStructInst].contains s.getKind

-- Optional grammar fields have a single, anonymous wrapper.
private def unpack (s : Syntax) : Syntax :=
  if s.getKind == nullKind && s.getNumArgs == 1 then s[0] else s

private def record? (map : FileMap) (stx : Syntax) : Option Json := do
  guard (stx.isOfKind ``Parser.Command.declaration)
  let core := stx[1]
  let start ← core.getPos?
  let args := core.getArgs.map unpack
  let name? := args.find? (·.isOfKind ``Parser.Command.declId) |>.bind (·.getPos?)
  let key := name?.map (point map) |>.getD #[(point map start)[0]!, 1]
  let (stop, valueJson) ← match args.findIdx? isValue with
    | some i => do
      let value := args[i]!
      let stop ← (args.extract 0 i).findSomeRev? (·.getTailPos?)
      let vstart ← if value.isOfKind ``Parser.Command.declValSimple then value[1].getPos? else value.getPos?
      let vstop ← value.getTailPos?
      pure (stop, toJson (point map vstart ++ point map vstop))
    | none => do
      guard ([``Parser.Command.«axiom», ``Parser.Command.«opaque»,
              ``Parser.Command.«structure», ``Parser.Command.«inductive»].contains core.getKind)
      pure (← core.getTailPos?, Json.null)
  return Json.mkObj [("name_at", toJson key),
    ("statement", toJson (point map start ++ point map stop)), ("value", valueJson)]

/-- A `mutual … end` block is one command that holds its declarations: read them one by one. -/
private partial def declarations (stx : Syntax) : Array Syntax :=
  if stx.isOfKind ``Parser.Command.mutual then
    stx[1].getArgs.foldl (fun found inner => found ++ declarations inner) #[]
  else #[stx]

/-- Run in the built artifact's Lake environment. Output goes to a separate file so
    messages printed by a Lean command cannot masquerade as range records. -/
def main (args : List String) : IO Unit := do
  let [file, moduleName, output] := args | throw (IO.userError "SourceRanges FILE MODULE OUTPUT")
  unsafe enableInitializersExecution
  initSearchPath (← findSysroot)
  let ctx := Parser.mkInputContext (← IO.FS.readFile file) file
  let (header, state, messages) ← Parser.parseHeader ctx
  let (env, messages) ← Elab.processHeader header {} messages ctx (mainModule := moduleName.toName)
  if messages.hasErrors then
    for m in messages.toList do IO.eprintln (← m.toString)
    throw (IO.userError "could not load the module header")
  let result ← Elab.IO.processCommands ctx state (Elab.Command.mkState env messages {})
  if result.commandState.messages.hasErrors then
    for m in result.commandState.messages.toList do
      if m.severity == .error then IO.eprintln (← m.toString)
    throw (IO.userError "Lean could not process the module")
  let found := result.commands.foldl (fun found stx => found ++ declarations stx) #[]
  let rows := found.filterMap (record? ctx.fileMap)
  IO.FS.writeFile output (toJson rows).compress
