"""kernelCAD OCCT 8 port: keep the JavaScript API of the OCCT 7.6 build.

opencascade.js (v2 bindgen) names overloads by position: the n-th C++ overload
of `Foo` is bound as `Foo_n`, the n-th public constructor of `X` as class
`X_n`. OCCT 8 added, removed and reordered overloads, so naive regeneration
renames bindings that replicad and kernelCAD call by their 7.6 names (e.g.
`Bnd_Box.Get` would become `Get_1`).

For every class that the 7.6 build bound, this module matches each OCCT 8
overload against the 7.6 overloads of the same name (argument names, then
normalised argument types, then arity) and reuses the 7.6 suffix. Overloads
and members that did not exist in 7.6 are dropped, so the bound surface of an
existing class never grows. 7.6 overloads with no OCCT 8 counterpart are
reported (compat76-report.txt) so they can be reviewed or shimmed.
"""
import os
import re

import clang.cindex

DTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compat", "replicad_76.d.ts")
REPORT = os.environ.get("OCJS_COMPAT_REPORT", "/opencascade.js/build/compat76-report.txt")
PRIMS = {
  "Standard_Real": "number", "Standard_Integer": "number", "Standard_ShortReal": "number",
  "Standard_Size": "number", "Standard_Byte": "number", "Standard_Character": "number",
  "Standard_ExtCharacter": "number", "Standard_Utf8Char": "number", "Standard_Utf16Char": "number",
  "Standard_Boolean": "boolean", "Standard_CString": "string", "number": "number",
  "boolean": "boolean", "string": "string",
}

_old = None


def _parseOld():
  classes = {}
  enums = set()
  src = open(DTS).read()
  for m in re.finditer(r"export declare type (\w+) = \{", src):
    enums.add(m.group(1))
  blocks = re.finditer(r"export declare class (\w+)(?: extends (\w+))? \{\n(.*?)\n\s*\}\n", src, re.S)
  raw = [(b.group(1), b.group(2), b.group(3)) for b in blocks]
  names = {r[0] for r in raw}
  for name, base, body in raw:
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    # constructor-overload helper class: X_n extends X { constructor(...); }
    cm = re.match(r"^(\w+)_(\d+)$", name)
    if base and cm and cm.group(1) == base and len(lines) == 1 and lines[0].startswith("constructor("):
      classes.setdefault(base, {"methods": {}, "simple": None, "ctors": {}})
      classes[base]["ctors"]["_" + cm.group(2)] = _sig(lines[0][len("constructor"):])
      continue
    c = classes.setdefault(name, {"methods": {}, "simple": None, "ctors": {}})
    c["base"] = base
    for l in lines:
      if l.startswith("constructor("):
        c["simple"] = _sig(l[len("constructor"):])
        continue
      mm = re.match(r"^(static )?(\w+)\((.*)\): .*;$", l)
      if not mm or mm.group(2) == "delete":
        continue
      full = mm.group(2)
      sig = _sig("(" + mm.group(3) + ")")
      c["methods"].setdefault(full, sig)
      if mm.group(1):
        c.setdefault("static", set()).add(full)
  # group methods by base name + suffix
  for name, c in classes.items():
    groups = {}
    for full, sig in c["methods"].items():
      sm = re.match(r"^(\w+?)(_\d+)?$", full)
      groups.setdefault(sm.group(1), []).append((sm.group(2) or "", full, sig))
    # a name like Foo_1 with no siblings could be a real method name ending in _1;
    # treat it as suffixed only if it has a sibling or a plain sibling is absent
    fixed = {}
    for base_name, items in groups.items():
      fixed.setdefault(base_name, []).extend(items)
    c["groups"] = fixed
  return {"classes": classes, "enums": enums, "names": names}


def _sig(argstr):
  argstr = argstr.strip()
  assert argstr.startswith("(")
  inner = argstr[1:argstr.rindex(")")]
  args = []
  if inner.strip():
    for a in inner.split(","):
      n, _, t = a.partition(":")
      args.append((n.strip().rstrip("_"), t.strip()))
  return args


def old():
  global _old
  if _old is None:
    _old = _parseOld()
  return _old


def _normOld(t):
  if t in PRIMS:
    return PRIMS[t]
  o = old()
  if t in o["names"] or t in o["enums"] or t == "any":
    return t
  return "number"  # 7.6 spelled int typedefs with arbitrary aliases (e.g. Graphic3d_ZLayerId)


def _normNew(arg):
  t = arg.type.get_canonical()
  while t.kind in (clang.cindex.TypeKind.LVALUEREFERENCE, clang.cindex.TypeKind.RVALUEREFERENCE, clang.cindex.TypeKind.POINTER):
    p = t.get_pointee()
    if t.kind == clang.cindex.TypeKind.POINTER and p.get_canonical().spelling.replace("const ", "") in ("char",):
      return "string"
    t = p
  s = t.spelling.replace("const ", "").replace("volatile ", "").strip()
  if s in ("bool",):
    return "boolean"
  if re.match(r"^(unsigned |signed )?(int|long|short|long long|double|float|char|char16_t|wchar_t|size_t|unsigned)$", s) or t.kind in (
      clang.cindex.TypeKind.INT, clang.cindex.TypeKind.UINT, clang.cindex.TypeKind.DOUBLE, clang.cindex.TypeKind.FLOAT,
      clang.cindex.TypeKind.LONG, clang.cindex.TypeKind.ULONG, clang.cindex.TypeKind.SHORT, clang.cindex.TypeKind.USHORT,
      clang.cindex.TypeKind.CHAR_S, clang.cindex.TypeKind.UCHAR, clang.cindex.TypeKind.CHAR16, clang.cindex.TypeKind.LONGLONG,
      clang.cindex.TypeKind.ULONGLONG):
    return "number"
  if t.kind == clang.cindex.TypeKind.ENUM:
    return s.split("::")[-1]
  hm = re.match(r"^opencascade::handle<(\w+)>$", s)
  if hm:
    return "Handle_" + hm.group(1)
  if "<" in s or "::" in s:
    return "*"
  return s


def _typesEqual(newTypes, oldTypes):
  if len(newTypes) != len(oldTypes):
    return False
  for n, o in zip(newTypes, oldTypes):
    if n == "*" or o == "any":
      continue
    if n != _normOld(o):
      return False
  return True


def _match(newItems, oldItems):
  """newItems: [(key, names, types)], oldItems: [(suffix, names, types)] -> {key: suffix}"""
  result = {}
  usedOld = set()
  passes = [
    lambda n, o: n[1] == o[1] and _typesEqual(n[2], o[2]),
    lambda n, o: n[1] == o[1],
    lambda n, o: _typesEqual(n[2], o[2]),
  ]
  for p in passes:
    for n in newItems:
      if n[0] in result:
        continue
      cands = [o for o in oldItems if o[0] not in usedOld and p(n, o)]
      if len(cands) >= 1:
        # prefer the candidate with most equal arg names
        cands.sort(key=lambda o: -sum(1 for a, b in zip(n[1], o[1]) if a == b))
        result[n[0]] = cands[0][0]
        usedOld.add(cands[0][0])
  # fuzzy argument names (OCCT 8 renamed many parameters to theXxx)
  def fuzzy(a):
    a = a.lower()
    for pre in ("the", "an", "a"):
      if a.startswith(pre) and len(a) > len(pre) + 1:
        return a[len(pre):]
    return a
  for n in newItems:
    if n[0] in result:
      continue
    best = None
    for o in oldItems:
      if o[0] in usedOld or len(o[1]) != len(n[1]) or not n[1]:
        continue
      score = sum(1 for a, b in zip(n[1], o[1]) if fuzzy(a) == fuzzy(b))
      if score > 0 and (best is None or score > best[0]):
        best = (score, o)
    if best is not None:
      result[n[0]] = best[1][0]
      usedOld.add(best[1][0])
  # OCCT 8 appended defaulted parameters (mostly Message_ProgressRange) to some
  # methods. The binding cannot default them, so JS callers must now pass them:
  # keep the 7.6 name and report the arity change for call-site review.
  for n in newItems:
    if n[0] in result or len(n) < 4:
      continue
    for o in oldItems:
      if o[0] in usedOld or len(n[1]) <= len(o[1]):
        continue
      k = len(o[1])
      if n[1][:k] == o[1][:k] or _typesEqual(n[2][:k], o[2][:k]):
        if all(n[3][k:]):
          result[n[0]] = o[0]
          usedOld.add(o[0])
          _truncate[n[0]] = k
          _report(f"ARITY-CHANGED {n[4]}{o[0]}: 7.6({', '.join(o[1])}) -> 8({', '.join(n[1])})")
          break
  # last resort: unique arity on both sides
  for n in newItems:
    if n[0] in result:
      continue
    ar = len(n[1])
    oc = [o for o in oldItems if o[0] not in usedOld and len(o[1]) == ar]
    nc = [x for x in newItems if x[0] not in result and len(x[1]) == ar]
    if len(oc) == 1 and len(nc) == 1:
      result[n[0]] = oc[0][0]
      usedOld.add(oc[0][0])
  return result, [o for o in oldItems if o[0] not in usedOld]


_cache = {}
_reported = set()
_truncate = {}
_asInstance = set()


def bindAsInstance(cursor):
  """OCCT 8 made some 7.6 instance methods static (XCAFDoc_ColorTool::GetColor):
  keep binding them as instance methods so `tool.GetColor_5(...)` still works."""
  return key(cursor) in _asInstance


def key(cursor):
  return (cursor.spelling, str(cursor.location.file), cursor.location.line, cursor.location.column)


def args(cursor):
  """Arguments to bind: OCCT 8 overloads matched to a shorter 7.6 overload by
  appending defaulted parameters are bound with the 7.6 arity (C++ fills in
  the defaults)."""
  a = list(cursor.get_arguments())
  k = _truncate.get(key(cursor))
  return a if k is None else a[:k]


def isTruncated(cursor):
  return key(cursor) in _truncate


def _report(line):
  if line in _reported:
    return
  _reported.add(line)
  with open(REPORT, "a") as f:
    f.write(line + "\n")


def _hasDefault(arg):
  return any(t.spelling == "=" for t in arg.get_tokens())


def _newItem(cursor, key, label=""):
  args = list(cursor.get_arguments())
  return (key, [a.spelling for a in args], [_normNew(a) for a in args], [_hasDefault(a) for a in args], label)


def className(theClass, templateDecl):
  return templateDecl.spelling if templateDecl is not None else theClass.spelling


def hadNoBase(name):
  """7.6 bound `name` without a base class, but OCCT 8 gave it one (e.g.
  NCollection_Array2<T> now derives from NCollection_Array1<T>). Keep it
  base-less: a same-named method of different arity on a bound base (Array1's
  2-argument SetValue) breaks embind's per-arity overload dispatch for the
  derived class's own method (`overloadTable` is undefined on the inherited
  function)."""
  return hasOld(name) and old()["classes"][name].get("base") is None


def _boundSymbols():
  f = os.environ.get("OCJS_SYMBOLS")
  return set(l.strip() for l in open(f) if l.strip()) if f else set()


def tsBaseName(name, newBase):
  """TypeScript base-class name: keep the 7.6 one when OCCT 8 renamed the base
  (e.g. GCE2d_Root became an alias of GC_Root2d) and the new name is not bound."""
  if hasOld(name):
    oldBase = old()["classes"][name].get("base")
    if oldBase and oldBase != newBase and newBase not in old()["names"] and newBase not in _boundSymbols():
      return oldBase
  return newBase


# Classes OCCT 8 inserted between a 7.6-bound class and its old base, now
# holding methods the 7.6 class declared itself. They are bound so the derived
# classes register (embind needs every base bound), and their overloads are
# named after the 7.6 class they came from.
OLD_SOURCE = {
  "GeomAdaptor_TransformedCurve": "BRepAdaptor_Curve",
  "GeomAdaptor_TransformedSurface": "BRepAdaptor_Surface",
  "BRepLib_ToolTriangulatedShape": "StdPrs_ToolTriangulatedShape",
}


def hasOld(name):
  return name in old()["classes"]


def methodPostfix(theClass, method, templateDecl=None):
  """Return the 7.6 overload postfix ("" or "_n") for `method`, or None to drop it.
  Returns NotImplemented when the class was not in the 7.6 build (use default)."""
  name = className(theClass, templateDecl)
  source = name if hasOld(name) else OLD_SOURCE.get(name)
  if source is None or not hasOld(source):
    return NotImplemented
  if method.spelling not in old()["classes"][source]["groups"]:
    # A method group the 7.6 class did not have (new in OCCT 8, or moved here
    # from a derived class): bind it under its natural name.
    return NotImplemented
  ck = (name, "m", method.spelling)
  if ck not in _cache:
    oldGroup = old()["classes"][source]["groups"].get(method.spelling, [])
    candidates = [m for m in theClass.get_children()
                  if m.spelling == method.spelling and m.kind == clang.cindex.CursorKind.CXX_METHOD
                  and m.access_specifier == clang.cindex.AccessSpecifier.PUBLIC]
    newItems = [_newItem(m, key(m), name + '.' + method.spelling) for m in candidates]
    res, missing = _match(newItems, [(s, [a[0] for a in sig], [a[1] for a in sig]) for (s, full, sig) in oldGroup])
    _cache[ck] = res
    statics = old()["classes"][source].get("static", set())
    for m in candidates:
      if key(m) in res and m.is_static_method() and (method.spelling + res[key(m)]) not in statics:
        _asInstance.add(key(m))
        _report(f"STATIC-AS-INSTANCE {name}.{method.spelling}{res[key(m)]}")
    for o in missing:
      _report(f"REMOVED {name}.{method.spelling}{o[0]}({', '.join(o[1])})")
    for n in newItems:
      if n[0] not in res:
        _report(f"DROPPED-NEW {name}.{method.spelling}({', '.join(n[1])})")
  return _cache[ck].get(key(method))


def ctorPlan(theClass, templateDecl=None):
  """For a class bound in 7.6, return ("simple", cursor|None) or ("overloaded", {hash: postfix}).
  Returns NotImplemented for classes the 7.6 build did not bind."""
  name = className(theClass, templateDecl)
  if not hasOld(name):
    return NotImplemented
  ck = (name, "c")
  if ck in _cache:
    return _cache[ck]
  oc = old()["classes"][name]
  ctors = [c for c in theClass.get_children()
           if c.kind == clang.cindex.CursorKind.CONSTRUCTOR and c.access_specifier == clang.cindex.AccessSpecifier.PUBLIC
           and not _isCopyOrMove(c, theClass)]
  allPublic = [c for c in theClass.get_children()
               if c.kind == clang.cindex.CursorKind.CONSTRUCTOR and c.access_specifier == clang.cindex.AccessSpecifier.PUBLIC]
  newItems = [_newItem(c, key(c), name) for c in allPublic]
  if oc["ctors"]:
    res, missing = _match(newItems, [(s, [a[0] for a in sig], [a[1] for a in sig]) for s, sig in oc["ctors"].items()])
    plan = ("overloaded", res)
  elif oc["simple"] is not None:
    res, missing = _match(newItems, [("", [a[0] for a in oc["simple"]], [a[1] for a in oc["simple"]])])
    hit = [c for c in allPublic if key(c) in res]
    plan = ("simple", hit[0] if hit else None)
    if not allPublic and not oc["simple"]:
      missing = []
  else:
    res, missing = {}, []
    plan = ("none", None)
  for o in missing:
    _report(f"REMOVED-CTOR {name}{o[0]}({', '.join(o[1])})")
  for n in newItems:
    if n[0] not in res and plan[0] != "none":
      _report(f"DROPPED-NEW-CTOR {name}({', '.join(n[1])})")
  _cache[ck] = plan
  return plan


def _isCopyOrMove(c, theClass):
  return False


def _baseClasses(theClass):
  out = []
  cur = theClass
  while True:
    bases = [c for c in cur.get_children() if c.kind == clang.cindex.CursorKind.CXX_BASE_SPECIFIER
             and c.access_specifier == clang.cindex.AccessSpecifier.PUBLIC]
    if not bases:
      return out
    d = bases[0].type.get_canonical().get_declaration().get_definition()
    if d is None:
      return out
    out.append(d)
    cur = d


def inheritedStatics(theClass, templateDecl=None):
  """7.6 static methods that OCCT 8 moved into a base class. embind does not
  inherit class functions, so they are bound on the derived class again.
  Returns [(method cursor, postfix, numOverloads in its class)]."""
  name = className(theClass, templateDecl)
  if not hasOld(name):
    return []
  oc = old()["classes"][name]
  statics = oc.get("static", set())
  own = {c.spelling for c in theClass.get_children() if c.kind == clang.cindex.CursorKind.CXX_METHOD}
  result = []
  for group, items in oc["groups"].items():
    if group in own or not all(full in statics for (_, full, _) in items):
      continue
    for base in _baseClasses(theClass):
      cands = [m for m in base.get_children() if m.kind == clang.cindex.CursorKind.CXX_METHOD and m.spelling == group
               and m.is_static_method() and m.access_specifier == clang.cindex.AccessSpecifier.PUBLIC]
      if not cands:
        continue
      newItems = [_newItem(m, key(m), name + "." + group) for m in cands]
      res, missing = _match(newItems, [(sfx, [a[0] for a in sig], [a[1] for a in sig]) for (sfx, full, sig) in items])
      allNamed = [m for m in base.get_children() if m.spelling == group]
      for m in cands:
        if key(m) in res:
          result.append((m, res[key(m)], len(allNamed)))
          _report(f"INHERITED-STATIC {name}.{group}{res[key(m)]} from {base.spelling}")
      for o in missing:
        _report(f"REMOVED {name}.{group}{o[0]}({', '.join(o[1])})")
      break
  return result
