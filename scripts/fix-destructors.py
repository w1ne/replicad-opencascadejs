#!/usr/bin/python3
"""Give the linked bindings real embind destructors, then recompile them.

opencascade.js's generator (src/bindings.py) emits

    template<> void raw_destructor<T>(T* ptr) { /* do nothing */ }

for every class that declares a two-argument `operator delete`. OCCT's
DEFINE_STANDARD_ALLOC macro declares the placement form on most classes,
TopoDS_Shape included, so `obj.delete()` from JavaScript never ran the C++
destructor: every deleted shape kept its TShape (the whole B-rep) alive, and
every deleted BRepCheck_Analyzer, BRepFilletAPI_MakeFillet or
BRepMesh_IncrementalMesh kept its working data. WASM memory only grows, so
long-lived kernels climbed until they hit their memory cap.

The replacement destroys the object unless that is unsafe:
  - a non-public or deleted destructor (the generator's other reason for the
    no-op) cannot be called;
  - a Standard_Transient subclass belongs to OCCT handles (reference
    counted). A handle may already have freed it, so not even its reference
    count can be read safely here; its handles free it.
  - abstract classes are only ever reached through a base pointer.

Run inside the opencascade.js image, before buildFromYaml.py, with the build
config as argv[1]. Only the bindings the build links are recompiled.
"""
import os
import re
import sys
from functools import partial
from multiprocessing import Pool

import yaml

sys.path.insert(0, "/opencascade.js/src")
from compileBindings import buildOneFile  # noqa: E402

BINDINGS = "/opencascade.js/build/bindings"
NOOP = re.compile(
    r"template<> void raw_destructor<(?P<t>[^>]+(?:<[^>]*>)?)>\((?P=t)\* ptr\) \{ /\* do nothing \*/ \}"
)
HELPER = """
#include <type_traits>
#include <Standard_Transient.hxx>
#ifndef KCAD_RAW_DESTROY
#define KCAD_RAW_DESTROY
// Tag dispatch, not `if constexpr`: the bindings compile as C++14, and only
// the selected overload instantiates `delete ptr`.
template <typename T> inline void kcadRawDestroyImpl(T* ptr, std::true_type) { delete ptr; }
template <typename T> inline void kcadRawDestroyImpl(T*, std::false_type) {}
template <typename T> inline void kcadRawDestroy(T* ptr) {
  kcadRawDestroyImpl(ptr, std::integral_constant<bool,
    std::is_destructible<T>::value && !std::is_abstract<T>::value &&
    !std::is_base_of<Standard_Transient, T>::value>());
}
#endif
"""


def linked_symbols(config_path):
    with open(config_path) as f:
        config = yaml.safe_load(f)
    builds = [config["mainBuild"], *config.get("extraBuilds", [])]
    return {b["symbol"] for build in builds for b in build.get("bindings", [])}


def binding_sources(symbols):
    for dirpath, _, filenames in os.walk(BINDINGS):
        for name in filenames:
            if name.endswith(".cpp") and name[:-4] in symbols:
                yield os.path.join(dirpath, name)


def patch(path):
    with open(path) as f:
        src = f.read()
    if not NOOP.search(src):
        return False
    src = NOOP.sub(lambda m: f"template<> void raw_destructor<{m['t']}>({m['t']}* ptr) {{ kcadRawDestroy(ptr); }}", src)
    # The helper must precede the specializations, which sit after the
    # EMSCRIPTEN_BINDINGS block at the end of the file.
    first = src.index("namespace emscripten { namespace internal { template<> void raw_destructor<")
    src = src[:first] + HELPER + src[first:]
    with open(path, "w") as f:
        f.write(src)
    if os.path.exists(path + ".o"):
        os.remove(path + ".o")
    return True


def main():
    config_path = sys.argv[1]
    threading = "multi-threaded" if "multi" in os.environ.get("OCJS_THREADING", "") else "single-threaded"
    symbols = linked_symbols(config_path)
    patched = [p for p in binding_sources(symbols) if patch(p)]
    print(f"fix-destructors: {len(symbols)} linked symbols, {len(patched)} bindings patched", flush=True)
    with Pool(processes=os.cpu_count()) as pool:
        pool.map(partial(buildOneFile, {"threading": threading}), sorted(patched))
    with open("/src/fix-destructors.txt", "w") as f:
        f.write("\n".join(sorted(os.path.basename(p)[:-4] for p in patched)) + "\n")


if __name__ == "__main__":
    main()
