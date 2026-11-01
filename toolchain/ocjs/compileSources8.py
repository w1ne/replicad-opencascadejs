#!/usr/bin/python3
"""kernelCAD: compile OCCT 8 sources (src/<Module>/<Toolkit>/<Package>/) with
the opencascade.js v2 toolchain (emsdk 3.1.14) into one static archive per
toolkit under /opencascade.js/build/occt-libs.

Flags are opencascade.js's 7.6 ones plus -std=c++17 (OCCT 8 minimum), except the
optimisation level: -O3 instead of -Os (OCJS_OPT overrides). LTO keeps the
per-function optsize attribute from -Os objects, which roughly halved the
speed of OCCT 8 Booleans/fillets/meshing in wasm at a +3 MB gzip cost
(README, "OCCT 8.0.1")."""
import os, re, subprocess, sys, multiprocessing

SRC = "/occt/src"
OUT = os.environ.get("OCJS_SOURCES_OUT", "/opencascade.js/build/sources")
LIBS = os.environ.get("OCJS_LIBS_OUT", "/opencascade.js/build/occt-libs")
MODULES = ["FoundationClasses", "ModelingData", "ModelingAlgorithms", "Visualization",
           "ApplicationFramework", "DataExchange"]
# Toolkits providing the bound classes; their EXTERNLIB.cmake dependency closure
# is compiled (IGES, VRML, glTF, OBJ, PLY, the Xml/Bin/Std persistence drivers,
# TObj and the OpenGL/VTK viewers are not needed by any binding).
SEED_TK = ["TKernel", "TKMath", "TKG2d", "TKG3d", "TKGeomBase", "TKBRep", "TKGeomAlgo",
           "TKTopAlgo", "TKPrim", "TKBO", "TKBool", "TKFeat", "TKFillet", "TKOffset",
           "TKShHealing", "TKMesh", "TKHLR", "TKV3d", "TKXSBase", "TKDE", "TKDESTEP",
           "TKDESTL", "TKXCAF", "TKLCAF", "TKCAF", "TKCDF"]

def toolkitClosure():
  deps = {}
  for m in MODULES:
    for tk in os.listdir(os.path.join(SRC, m)):
      f = os.path.join(SRC, m, tk, "EXTERNLIB.cmake")
      if os.path.isfile(f):
        deps[tk] = [x for x in re.findall(r"\b(TK\w+)\b", open(f).read()) if x != tk]
  seen = set()
  def visit(tk):
    if tk not in seen:
      seen.add(tk)
      for d in deps.get(tk, []):
        visit(d)
  for tk in SEED_TK:
    visit(tk)
  return seen

TOOLKITS = toolkitClosure()
FLAGS = ["-std=c++17", "-flto", "-fexceptions", "-sDISABLE_EXCEPTION_CATCHING=0",
         "-DIGNORE_NO_ATOMICS=1", "-DOCCT_NO_PLUGINS", "-frtti", "-DHAVE_RAPIDJSON", os.environ.get("OCJS_OPT", "-O3"),
         "-Wno-deprecated-declarations"]

def includeDirs():
  dirs = []
  for dirpath, dirnames, filenames in os.walk(SRC):
    dirnames[:] = [d for d in dirnames if d != "GTests" and not (dirpath == SRC and d == "Draw")]
    if any(f.endswith((".hxx", ".lxx", ".gxx", ".pxx", ".h")) for f in filenames):
      dirs.append(dirpath)
  return sorted(dirs) + ["/rapidjson/include", "/freetype/include/freetype", "/freetype/include"]

INC = ["-I" + d for d in includeDirs()]

def packages(tkdir):
  txt = open(os.path.join(tkdir, "PACKAGES.cmake")).read()
  body = re.search(r"LIST_OF_PACKAGES\s*(.*?)\)", txt, re.S).group(1)
  return body.split()

def jobs():
  out = []
  for m in MODULES:
    for tk in sorted(os.listdir(os.path.join(SRC, m))):
      tkdir = os.path.join(SRC, m, tk)
      if tk not in TOOLKITS or not os.path.isfile(os.path.join(tkdir, "PACKAGES.cmake")):
        continue
      for p in packages(tkdir):
        pdir = os.path.join(tkdir, p)
        if not os.path.isdir(pdir):
          continue
        for f in sorted(os.listdir(pdir)):
          if f.endswith((".cxx", ".cpp", ".c")):
            out.append((tk, os.path.join(pdir, f)))
  return out

def build(job):
  tk, f = job
  rel = os.path.relpath(f, SRC)
  o = os.path.join(OUT, rel + ".o")
  if os.path.exists(o):
    return (tk, o, True)
  os.makedirs(os.path.dirname(o), exist_ok=True)
  flags = [x for x in FLAGS if not (f.endswith(".c") and x in ("-std=c++17", "-frtti"))]
  cmd = ["emcc", *flags, *INC, "-c", f, "-o", o + ".tmp"]
  r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
  if r.returncode != 0:
    sys.stdout.write("FAILED " + rel + "\n" + r.stdout[-3000:] + "\n")
    sys.stdout.flush()
    return (tk, o, False)
  os.rename(o + ".tmp", o)
  return (tk, o, True)

if __name__ == "__main__":
  js = jobs()
  if len(sys.argv) > 1:
    js = [j for j in js if any(a in j[1] for a in sys.argv[1:])]
  print(f"{len(js)} source files", flush=True)
  done = 0
  res = []
  with multiprocessing.Pool(multiprocessing.cpu_count()) as p:
    for r in p.imap_unordered(build, js, chunksize=4):
      res.append(r); done += 1
      if done % 200 == 0:
        print(f"progress {done}/{len(js)}", flush=True)
  failed = [r for r in res if not r[2]]
  print(f"compiled {len(res)-len(failed)}, failed {len(failed)}", flush=True)
  for r in failed:
    print("  failed:", os.path.relpath(r[1], OUT))
  if failed:
    sys.exit(1)
  if len(sys.argv) == 1:
    os.makedirs(LIBS, exist_ok=True)
    bytk = {}
    for tk, o, ok in res:
      if ok: bytk.setdefault(tk, []).append(o)
    for tk, objs in bytk.items():
      a = os.path.join(LIBS, "lib" + tk + ".a")
      if os.path.exists(a): os.remove(a)
      subprocess.check_call(["emar", "rcs", a, *sorted(objs)])
    print("archives:", len(bytk), flush=True)
