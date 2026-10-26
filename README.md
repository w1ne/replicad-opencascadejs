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
| `KernelCAD_XCAF` | Reads copied XCAF product names and sparse child-label tags without exposing generic GUID/attribute handles |
| `GPropWrapper` | inertia tensor + principal axes, see below |
| `HLRBRep_PolyAlgo`, `Handle_HLRBRep_PolyAlgo`, `HLRBRep_PolyHLRToShape` | polygonal hidden-line removal for mesh-derived (STL) parts; exact HLR on 65k facets needs ~1.5 GB per drawing view |

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

`pnpm buildWasm` assumes Docker and a TTY. On Apple Silicon the image is amd64-only;
these are the deltas that make it work:

```sh
# colima only mounts $HOME and /tmp/colima -- building outside those fails with
# a confusing "FileNotFoundError" from inside the container
colima start --vm-type=vz --vz-rosetta --cpu 8 --memory 10 --disk 40

ytt -f build-source/ --output-files build-config
chmod 644 build-config/*.yml   # ytt writes 0700; the -u mapped container user cannot read them

cd build-config
cp ../scripts/fix-destructors.py .
OCCT_IMAGE='docker.io/donalffons/opencascade.js@sha256:3069f4c2e3ab62bb82d81843bad2c0f8552ee92373208f8f655ef9bf71c0524d'
docker pull "$OCCT_IMAGE"
# note: no -it (fails without a TTY); --platform linux/amd64 is needed on Rosetta
docker run --rm --platform linux/amd64 -v "$(pwd)":/src -w /src \
  -u "$(id -u)":"$(id -g)" --entrypoint sh "$OCCT_IMAGE" \
  -c 'python3 /src/fix-destructors.py custom_build_single.yml && /opencascade.js/src/buildFromYaml.py custom_build_single.yml'
docker run --rm --platform linux/amd64 -v "$(pwd)":/src -w /src \
  -u "$(id -u)":"$(id -g)" --entrypoint sh "$OCCT_IMAGE" \
  -c 'python3 /src/fix-destructors.py custom_build_with_exceptions.yml && /opencascade.js/src/buildFromYaml.py custom_build_with_exceptions.yml'
mv replicad_single* replicad_with_exceptions* ../src
```

Build both variants together — shipping a `single` with new symbols next to a stale
`with_exceptions` is silent drift.

Pull requests that change the binding source build both variants and upload the
generated modules as the `replicad-opencascadejs-wasm` workflow artifact. Copy the
six generated files into `src/` and commit them with the source change after checking
the artifact against the runtime API.

The emitted module targets browser ESM. Loading it in node needs `__dirname`,
`require`, and `locateFile` shimmed; that is a property of the build, not a defect.
