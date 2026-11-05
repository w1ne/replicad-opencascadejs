#!/usr/bin/env node
// Smoke-check the generated modules: both variants load in node, report the
// OCCT version they were built from, free C++ memory on delete() (see
// fix-destructors.py), and every kernelCAD-only binding (README, "Intentional
// divergence") is callable -- including the return types, which embind only
// rejects at call time ("the unbound-return-type trap").
//
//   node scripts/check-wasm.mjs [expectedOcctVersion]
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const expected = process.argv[2] ?? '8.0.1';
// The emitted module targets browser ESM; node needs require/__dirname shimmed.
globalThis.require = createRequire(import.meta.url);
globalThis.__dirname = root;

let failures = 0;
const check = (ok, what) => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) failures += 1;
};
const attempt = (what, fn) => {
  try {
    check(fn() !== false, what);
  } catch (error) {
    check(false, `${what}: ${error?.message ?? error}`);
  }
};

async function load(variant) {
  const { default: init } = await import(join(root, `${variant}.js`));
  return init({ wasmBinary: readFileSync(join(root, `${variant}.wasm`)) });
}

function heapBytes(oc) {
  return (oc.HEAPU8 ?? oc.HEAP8)?.length ?? oc.wasmMemory?.buffer.byteLength ?? 0;
}

for (const variant of (process.env.VARIANTS ?? 'replicad_single,replicad_with_exceptions').split(',')) {
  console.log(`\n# ${variant}`);
  const oc = await load(variant);
  attempt(`KernelCAD_OCCT.Version() === ${expected}`, () => oc.KernelCAD_OCCT.Version() === expected);

  const box = () => new oc.BRepPrimAPI_MakeBox_2(10, 20, 30);
  attempt('BRepPrimAPI_MakeBox_2 + Shape()', () => {
    const b = box();
    const s = b.Shape();
    const ok = !s.IsNull();
    s.delete();
    b.delete();
    return ok;
  });

  // Real destructors: a steady-state loop of build+fillet+delete must not grow
  // the heap. With the opencascade.js no-op destructors every iteration leaks
  // the whole B-rep and the fillet builder.
  const churn = (n) => {
    for (let i = 0; i < n; i++) {
      const b = box();
      const s = b.Shape();
      const f = new oc.BRepFilletAPI_MakeFillet(s, oc.ChFi3d_FilletShape.ChFi3d_Rational);
      const ex = new oc.TopExp_Explorer_2(s, oc.TopAbs_ShapeEnum.TopAbs_EDGE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
      const e = oc.TopoDS.Edge_1(ex.Current());
      f.Add_2(2, e);
      const r = f.Shape();
      r.delete(); e.delete(); ex.delete(); f.delete(); s.delete(); b.delete();
    }
  };
  churn(100);
  const before = heapBytes(oc);
  churn(1500);
  const after = heapBytes(oc);
  check(after === before, `delete() frees C++ memory (heap ${before} -> ${after} bytes over 1500 fillets)`);

  // 7.6 call sites that OCCT 8 changed (toolchain/ocjs/compat76.py, occt8-kernelcad.patch)
  attempt('7.6 API kept: TopoDS casts, HashCode, Transform_2(S,T,copy), Analyzer(S,g,p), Bnd_Box.Get', () => {
    const b = box(); const s = b.Shape();
    const ex = new oc.TopExp_Explorer_2(s, oc.TopAbs_ShapeEnum.TopAbs_FACE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
    const face = oc.TopoDS.Face_1(ex.Current());
    const h = s.HashCode(2147483647);
    const tr = new oc.gp_Trsf_1(); tr.SetTranslation_1(new oc.gp_Vec_4(1, 2, 3));
    const moved = new oc.BRepBuilderAPI_Transform_2(s, tr, true).Shape();
    const valid = new oc.BRepCheck_Analyzer(moved, true, false).IsValid_2();
    const bb = new oc.Bnd_Box_1(); oc.BRepBndLib.Add(moved, bb, true);
    const r = [0, 0, 0, 0, 0, 0].map(() => ({ current: 0 }));
    bb.Get(...r);
    return h >= 1 && h <= 2147483647 && h === s.HashCode(2147483647) && valid
      && Math.abs(r[0].current - 1) < 1e-6 && Math.abs(r[5].current - 33) < 1e-6 && !face.IsNull();
  });
  attempt('7.6 API kept: StdPrs_ToolTriangulatedShape.Normal, BRepAdaptor_Curve/Surface, GCE2d_*', () => {
    const b = box(); const s = b.Shape();
    new oc.BRepMesh_IncrementalMesh_2(s, 0.5, false, 0.5, false).delete();
    const face = oc.TopoDS.Face_1(new oc.TopExp_Explorer_2(s, oc.TopAbs_ShapeEnum.TopAbs_FACE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE).Current());
    const tri = oc.BRep_Tool.Triangulation(face, new oc.TopLoc_Location_1(), 0);
    const normals = new oc.TColgp_Array1OfDir_2(1, tri.get().NbNodes());
    oc.StdPrs_ToolTriangulatedShape.Normal(face, new oc.Poly_Connect_2(tri), normals);
    const surf = new oc.BRepAdaptor_Surface_2(face, true);
    const edge = oc.TopoDS.Edge_1(new oc.TopExp_Explorer_2(s, oc.TopAbs_ShapeEnum.TopAbs_EDGE, oc.TopAbs_ShapeEnum.TopAbs_SHAPE).Current());
    const curve = new oc.BRepAdaptor_Curve_2(edge);
    const seg = new oc.GCE2d_MakeSegment_1(new oc.gp_Pnt2d_3(0, 0), new oc.gp_Pnt2d_3(1, 0));
    return Math.abs(Math.abs(normals.Value(1).X()) - 1) < 1e-9
      && surf.GetType() === oc.GeomAbs_SurfaceType.GeomAbs_Plane
      && curve.GetType() === oc.GeomAbs_CurveType.GeomAbs_Line && curve.LastParameter() > 0
      && seg.IsDone() && !seg.Value().IsNull() && oc.GCE2d_Root === oc.GC_Root
      && typeof oc.XCAFDoc_ColorTool.prototype.GetColor_5 === 'function';
  });

  // kernelCAD-only bindings
  attempt('BRepBuilderAPI_GTransform', () => {
    const b = box(); const s = b.Shape();
    const g = new oc.gp_GTrsf_1(); g.SetValue(1, 1, 2);
    const t = new oc.BRepBuilderAPI_GTransform_2(s, g, true);
    const ok = !t.Shape().IsNull();
    t.delete(); g.delete(); s.delete(); b.delete();
    return ok;
  });
  attempt('BRepFeat_SplitShape', () => {
    const b = box(); const s = b.Shape();
    const sp = new oc.BRepFeat_SplitShape_2(s);
    sp.delete(); s.delete(); b.delete();
  });
  attempt('TColStd_Array2OfReal', () => {
    const a = new oc.TColStd_Array2OfReal_2(1, 2, 1, 3);
    a.SetValue(2, 3, 4.5);
    const ok = a.Value(2, 3) === 4.5 && a.ColLength() === 2 && a.RowLength() === 3;
    a.delete();
    return ok;
  });
  attempt('Geom2dGcc tangency + GccEnt_Position + gp_Lin2d return', () => {
    const circle = (x, r) => {
      const ax = new oc.gp_Ax2d_2(new oc.gp_Pnt2d_3(x, 0), new oc.gp_Dir2d_4(1, 0));
      const h = new oc.Handle_Geom2d_Curve_2(new oc.Geom2d_Circle_2(ax, r, true));
      return new oc.Geom2dAdaptor_Curve_2(h);
    };
    const q1 = new oc.Geom2dGcc_QualifiedCurve(circle(0, 1), oc.GccEnt_Position.GccEnt_unqualified);
    const q2 = new oc.Geom2dGcc_QualifiedCurve(circle(5, 1), oc.GccEnt_Position.GccEnt_unqualified);
    const lines = new oc.Geom2dGcc_Lin2d2Tan_1(q1, q2, 1e-6);
    const lin = lines.ThisSolution(1); // gp_Lin2d: unbound before kernelCAD bound it
    const arcs = new oc.Geom2dGcc_Circ2d2TanRad_1(q1, q2, 3, 1e-6);
    const c = arcs.ThisSolution(1);
    return lines.IsDone() && lines.NbSolutions() === 4 && Math.abs(lin.Direction().Y()) < 1e-9
      && arcs.IsDone() && arcs.NbSolutions() > 0 && Math.abs(c.Radius() - 3) < 1e-9;
  });
  for (const name of ['Geom2dGcc_Circ2d2TanOn_1', 'Geom2dGcc_Circ2d3Tan_1', 'Geom2dGcc_Circ2dTanCen',
    'Geom2dGcc_Circ2dTanOnRad_1', 'Geom2dGcc_Lin2dTanObl_1']) {
    check(typeof oc[name] === 'function', `${name} bound`);
  }
  attempt('ShapeFix_Shape', () => {
    const b = box(); const s = b.Shape();
    const fx = new oc.ShapeFix_Shape_2(s);
    fx.Perform(new oc.Message_ProgressRange_1());
    const ok = !fx.Shape().IsNull();
    fx.delete(); s.delete(); b.delete();
    return ok;
  });
  check(typeof oc.BRepProj_Projection_1 === 'function', 'BRepProj_Projection bound');
  attempt('STEPCAFControl_Reader + KernelCAD_XCAF + XCAF document', () => {
    const r = new oc.STEPCAFControl_Reader_1();
    const doc = new oc.Handle_TDocStd_Document_2(new oc.TDocStd_Document(new oc.TCollection_ExtendedString_1()));
    const label = doc.get().Main();
    const ok = oc.KernelCAD_XCAF.GetName(label) === '' && typeof oc.KernelCAD_XCAF.GetChildTags(label) === 'string';
    r.delete();
    return ok;
  });
  attempt('IGESControl_Reader exact B-rep face transfer', () => {
    const b = box();
    const shape = b.Shape();
    const path = '/kcad-iges-binding-smoke.igs';
    const writerOk = oc.KernelCAD_IGESWriter.WriteShape(shape, path);
    const reader = new oc.KernelCAD_IGESReader();
    const readStatus = reader.ReadFile(path);
    const transferred = reader.TransferRoots();
    const imported = reader.OneShape();
    const counts = [oc.TopAbs_ShapeEnum.TopAbs_SOLID, oc.TopAbs_ShapeEnum.TopAbs_SHELL, oc.TopAbs_ShapeEnum.TopAbs_FACE].map(kind => {
      const explorer = new oc.TopExp_Explorer_2(imported, kind, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
      let n = 0; while (explorer.More()) { n++; explorer.Next(); } explorer.delete(); return n;
    });
    imported.delete(); reader.delete(); shape.delete(); b.delete();
    oc.FS.unlink(path);
    if (!writerOk) throw new Error('IGESControl_Writer.Write returned false');
    // OCCT's IFSelect_ReturnStatus enum crosses this custom int-returning
    // wrapper as its underlying integer (RetDone == 1).
    if (readStatus !== 1) {
      throw new Error(`ReadFile status ${readStatus} != IFSelect_RetDone (1)`);
    }
    if (transferred <= 0) throw new Error(`TransferRoots returned ${transferred}`);
    // IGESControl_Reader returns this exported box as a compound of six exact
    // faces. The runtime sews/promotes closed face sets into validated solids.
    if (counts[2] !== 6) throw new Error(`OneShape transferred ${counts[2]} faces, expected six`);
    return true;
  });
  attempt('GPropWrapper inertia', () => {
    const b = box(); const s = b.Shape();
    const p = new oc.GProp_GProps_1();
    oc.BRepGProp.VolumeProperties_1(s, p, false, false, false);
    const ixx = oc.GPropWrapper.MatrixOfInertiaValue(p, 1, 1);
    const m0 = oc.GPropWrapper.PrincipalMoment(p, 0);
    const ok = Math.abs(p.Mass() - 6000) < 1e-6 && ixx > 0 && m0 > 0;
    p.delete(); s.delete(); b.delete();
    return ok;
  });
  attempt('HLRBRep_PolyAlgo + Handle + PolyHLRToShape', () => {
    const b = box(); const s = b.Shape();
    new oc.BRepMesh_IncrementalMesh_2(s, 0.5, false, 0.5, false).delete();
    const algo = new oc.HLRBRep_PolyAlgo_1();
    const h = new oc.Handle_HLRBRep_PolyAlgo_2(algo);
    algo.Load(s);
    const ax = new oc.gp_Ax2_3(new oc.gp_Pnt_3(0, 0, 0), new oc.gp_Dir_4(0, 0, 1));
    algo.Projector_2(new oc.HLRAlgo_Projector_2(ax));
    algo.Update();
    const toShape = new oc.HLRBRep_PolyHLRToShape();
    toShape.Update(h);
    const ok = !toShape.VCompound_1().IsNull();
    toShape.delete(); h.delete(); s.delete(); b.delete();
    return ok;
  });
}

console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
process.exit(failures ? 1 : 0);
