# `replicad-opencascadejs`

An opencascadejs build containing only the APIs necessary to run replicad. You
will need to have docker installed, as well as ytt (in order to generate the
configuration files).

## Usage

```
pnpm buildWasm
```

You need to have a docker instance running and have run
`docker pull donalffons/opencascade.js`

---

## kernelCAD fork notes

This repo is a **copy**, not a GitHub fork — there is no `parent` and therefore no
`git fetch upstream`. Upstream now lives inside the replicad monorepo at
`sgenoud/replicad` → `packages/replicad-opencascadejs/`.

Because nothing links the two, drift is invisible by default. Run:

```
./scripts/check-upstream-drift.sh
```

Exit 1 means upstream has symbols we lack. Symbols we add that upstream lacks are
reported, not failed on — those are the intentional divergence listed below.

### Intentional divergence from upstream

| Symbol | Why |
| --- | --- |
| `BRepBuilderAPI_GTransform` | non-uniform scale |
| `BRepFeat_SplitShape` | curved-surface trims |
| `TColStd_Array2OfReal` | NURBS weight arrays |
| `gp_Lin2d` | **required** by the `Geom2dGcc_Lin2d*` constructors below |
| `GccEnt_Position`, `Geom2dGcc_QualifiedCurve` | tangency qualifiers |
| `Geom2dGcc_Circ2d2TanRad`, `Circ2d2TanOn`, `Circ2d3Tan`, `Circ2dTanCen`, `Circ2dTanOnRad` | tangent-arc construction |
| `Geom2dGcc_Lin2dTanObl`, `Lin2d2Tan` | tangent-line construction |
| `ShapeFix_Shape` | top-level repair (only sub-fixers were bound) |
| `BRepProj_Projection` | curve-on-surface projection |
| `STEPCAFControl_Reader` | STEP import with colors/names/assembly tree |
| `KernelCAD_XCAF` | Reads copied XCAF product names as UTF-8 strings and sparse child-label tags without exposing generic GUID/attribute handles |
| `GPropWrapper` | inertia tensor + principal axes, see below |
| `HLRBRep_PolyAlgo`, `Handle_HLRBRep_PolyAlgo`, `HLRBRep_PolyHLRToShape` | polygonal hidden-line removal for mesh-derived (STL) parts; exact HLR on 65k facets needs ~1.5 GB per drawing view |
| `KernelCAD_OCCT` | `KernelCAD_OCCT.Version()` returns the OCCT version the module was built from (`"8.0.1"`) |
| `GeomAdaptor_TransformedCurve`, `GeomAdaptor_TransformedSurface` | OCCT 8 bases of `BRepAdaptor_Curve`/`_Surface`, which now hold most of their methods; embind cannot register a class whose base is unbound (upstream binds them too) |
| `BRepLib_ToolTriangulatedShape` | OCCT 8 home of `ComputeNormals` (upstream binds it too); `StdPrs_ToolTriangulatedShape` keeps its 7.6 statics |

### OCCT 8.0.1 (toolchain/)

The kernel is **OCCT 8.0.1** (tag `V8_0_1`, commit `b8f597c677811d1f9f4d8a97f5ae2825c0353a42`).
No published opencascade.js image both embeds OCCT 8 and keeps the JavaScript API
replicad 0.23 and kernelCAD call: the maintained taucad/opencascade.js v3 images
(`ghcr.io/taucad/opencascade.js:3.x`, which upstream replicad-opencascadejs 1.x uses)
embed V8_0_1 but ship a rewritten binding generator (suffix-free overloads,
output-parameter envelopes, elided `Handle` outputs, native wasm exceptions), so every
`new oc.gp_Pnt_3(...)`/`{ current: 0 }` call site would break. `toolchain/Dockerfile`
instead keeps the donalffons/opencascade.js v2 generator and emsdk 3.1.14 (the 7.6 base
image, pinned by digest) and swaps OCCT:

- `occt8-kernelcad.patch` — OCCT source patches that keep 7.6 call sites working:
  `TopoDS` is a class of static casts again (OCCT 8 made it a namespace, which embind
  cannot bind); `TopoDS_Shape::HashCode(upper)` (removed in 8; now `std::hash`
  modulo `upper`, plus one — values differ from 7.6, semantics match);
  `StdPrs_ToolTriangulatedShape::Normal` (removed in 8; 7.6 semantics);
  `BRepAlgoAPI_Algo` forwards its `BOPAlgo_Options` methods explicitly (the generator
  ignores `using`; same patch opencascade.js applied to 7.6).
- `gen-occt8-compat.py` — writes `Standard_Version.hxx` (normally CMake-generated) and
  `Handle_<Class>` typedefs for every transient class (OCCT 8 dropped them; the
  generator names and binds handles through them).
- `ocjs-occt8.patch` + `ocjs/` — the generator port: OCCT 8's
  `src/<Module>/<Toolkit>/<Package>` layout, `-std=c++17`, `occ::handle` spellings,
  injected-class-name member types, `std::exception` bases, deprecated
  `using Old = New;` class aliases (`GCE2d_*`), template bases (`NCollection_Array2`
  now derives from `NCollection_Array1`), a precompiled header, per-toolkit static
  archives, and generation of only the linked symbols (`prepareBindings.py`).
- `ocjs/compat76.py` — **the 7.6 JS API guard.** The generator names overloads by
  position (`Foo_3`, `X_2`), and OCCT 8 added, removed and reordered overloads. For
  every class the 7.6 build bound, each OCCT 8 overload is matched to a 7.6 overload of
  the same name (`ocjs/compat/replicad_76.d.ts`, the frozen 7.6 declarations) and keeps
  its 7.6 suffix; new overloads in an existing group are dropped. Where OCCT 8 appended
  defaulted parameters (`BRepBuilderAPI_Transform_2(S, T, Copy)` gained `theCopyMesh`)
  the binding keeps the 7.6 arity; 7.6 instance methods that became static
  (`XCAFDoc_ColorTool.GetColor_5`) stay instance methods; statics moved into a base
  class are bound on the derived class again (embind does not inherit class functions);
  a class 7.6 bound without a base stays base-less even if OCCT 8 gave it one
  (`NCollection_Array2` now derives from `NCollection_Array1`, whose 2-argument
  `SetValue` would break embind's arity dispatch of Array2's 3-argument one).
  The build writes every decision to `/opencascade.js/build/compat76-report.txt`.

7.6 API that is gone in this build (none of it is called by replicad 0.23 or
kernelCAD): `BRepCheck_Analyzer.Init(S, geom, parallel)` (use the constructor),
`BRepAdaptor_Surface.ChangeSurface`, `NCollection_Array1.IsAllocated`,
`NCollection_Array2.Init`/`IsDeletable` (moved to the unbound Array1 base),
`TopLoc_Location.HashCode`, static `TCollection_ExtendedString.HashCode`, and
`Standard_Failure`'s `Standard_Transient` API (it derives from `std::exception` in
OCCT 8; `GetMessageString()` remains). `ShapeFix_Face/Wire.Perform`,
`ShapeFix_Wire.FixReorder_1` and `FixConnected_2` now take OCCT 8's extra argument.
BREP text written by this kernel is read by OCCT 7.6 only if it uses a format version
7.6 knows.

Behaviour change that callers must handle: OCCT 8 `BRepOffsetAPI_MakeThickSolid`
can report `IsDone()` where 7.6 raised or left it false — returning the input
solid unchanged (wall too thick, `GeomAbs_Intersection` join on filleted bodies) or
an invalid solid (`GeomAbs_Arc` on filleted bodies). Treat an unchanged volume as a
failure, as well as an invalid result.

Both variants are linked with `-sDISABLE_EXCEPTION_CATCHING=1`: ytt applies
`custom_build_single.yml`'s `buildFlags.extend` to the shared data values, so
`custom_build_with_exceptions.yml` inherits it. That was already true of the 7.6
artifacts (neither `.js` has `invoke_*` trampolines) and is unchanged here.

Compile level: OCCT is compiled at `-O3` (opencascade.js used `-Os`; LTO keeps
`-Os`'s per-function size attribute). Measured on one 4-core machine against the
7.6 build (kernelCAD CLI `evaluate`, best of 2): tendon-driven hand 73.97 s -> 38.81 s,
hand-coffee-grinder 183.6 s -> 79.7 s, gearfinity planetary stage 15.6 s -> 9.1 s;
raw OCCT micro-benchmarks (144 sequential cuts, 60 fuses, fillets, meshing, BRepCheck)
2.0-2.3x faster with identical volumes. Cost: `replicad_single.wasm` 11.4 MB -> 24.7 MB
(gzip 4.75 MB -> 7.78 MB) and ~60-180 MB more peak RSS. At `-Os`
(`docker build --build-arg OCJS_OPT=-Os`) OCCT 8.0.1 is the same speed and size as 7.6.

`scripts/check-wasm.mjs` loads both modules in node and checks the version, real
destructors (a 1500-fillet churn must not grow the heap) and every symbol in the
divergence table, including return types.

### Real destructors (`scripts/fix-destructors.py`)

opencascade.js emits a no-op embind destructor for every class that declares a
two-argument `operator delete`, which OCCT's `DEFINE_STANDARD_ALLOC` does on
`TopoDS_Shape` and most value and algorithm classes. Built as-is, `obj.delete()`
from JavaScript never runs the C++ destructor: a deleted shape keeps its whole
B-rep alive, and a deleted `BRepCheck_Analyzer` or `BRepFilletAPI_MakeFillet`
keeps its working data. The WASM heap only grows, so long-lived kernels climb to
their memory cap.

`buildSingle` / `buildWithExceptions` run `scripts/fix-destructors.py` inside the
image before `buildFromYaml.py`. It rewrites the no-op for the linked bindings to
`delete` the object unless its destructor is not public, the class is abstract,
or it is a `Standard_Transient` (owned by OCCT handles, which free it; reading its
reference count from JavaScript could touch memory a handle already freed), then
recompiles only those bindings. Do not build without it.

### The unbound-return-type trap

A symbol can be *declared* in the generated `.d.ts` and still be uncallable: if its
return type is not itself registered with embind, the call throws
`BindingError: unbound types` at **runtime**, not at build time.

`GProp_GProps::MatrixOfInertia()` was exactly this — declared, returning an unbound
`gp_Mat`. `gp_Lin2d` would have reproduced it for the `Geom2dGcc_Lin2d*`
constructors had it not been added alongside them.

When adding any symbol, check what its methods *return*, not just that the class
appears in the `.d.ts`.

`GPropWrapper` exists to sidestep this class of problem rather than pay for it: it
exposes the inertia tensor element-wise as `Standard_Real`, so the binding surface
stays primitive-only and neither `gp_Mat` nor `GProp_PrincipalProps` needs binding.
This mirrors the existing `BRepToolsWrapper`, which constructs a `BRep_Builder`
internally so that type never needs to be exposed either.

### Rebuild recipe

`pnpm buildWasm` assumes Docker and a TTY. On Apple Silicon the image is amd64-only
(add `--platform linux/amd64`; colima only mounts `$HOME` and `/tmp/colima`).

```sh
# toolchain image: OCCT 8.0.1 + the ported generator; compiles OCCT (~1-2 h, 4 cores)
docker build -t kernelcad-ocjs-occt8 toolchain/

ytt -f build-source/ --output-files build-config
chmod 644 build-config/*.yml   # ytt writes 0700; the -u mapped container user cannot read them

cd build-config
cp ../scripts/fix-destructors.py .
for cfg in custom_build_single custom_build_with_exceptions; do
  # note: no -it (fails without a TTY)
  docker run --rm -v "$(pwd)":/src -w /src -u "$(id -u)":"$(id -g)" \
    --entrypoint sh kernelcad-ocjs-occt8 \
    -c "python3 /opencascade.js/src/prepareBindings.py $cfg.yml && python3 /src/fix-destructors.py $cfg.yml && /opencascade.js/src/buildFromYaml.py $cfg.yml"
done
mv replicad_single* replicad_with_exceptions* ../src
cd .. && node scripts/check-wasm.mjs
```

Build both variants together — shipping a `single` with new symbols next to a stale
`with_exceptions` is silent drift.

Pull requests that change the binding source build both variants and upload the
generated modules as the `replicad-opencascadejs-wasm` workflow artifact. Copy the
six generated files into `src/` and commit them with the source change after checking
the artifact against the runtime API.

The emitted module targets browser ESM. Loading it in node needs `__dirname`,
`require`, and `locateFile` shimmed; that is a property of the build, not a defect.
