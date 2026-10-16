// Mass-property accessors for kernelCAD -- exposes the inertia matrix and
// principal properties of a GProp_GProps element-wise. The binding surface
// stays primitive-only: gp_Mat and GProp_PrincipalProps are not registered
// with embind, so returning them directly throws at call time.

class GPropWrapper {
public:
  // Row-major element (i,j) of the 3x3 inertia matrix, 1-based per OCCT convention.
  static Standard_Real MatrixOfInertiaValue(const GProp_GProps& props, const Standard_Integer i, const Standard_Integer j) {
    return props.MatrixOfInertia().Value(i, j);
  }
  // Principal moment of inertia, index 0..2.
  static Standard_Real PrincipalMoment(const GProp_GProps& props, const Standard_Integer index) {
    Standard_Real i1, i2, i3;
    props.PrincipalProperties().Moments(i1, i2, i3);
    return index == 0 ? i1 : (index == 1 ? i2 : i3);
  }
  // Component (0..2 = X/Y/Z) of principal axis `axis` (0..2).
  static Standard_Real PrincipalAxisComponent(const GProp_GProps& props, const Standard_Integer axis, const Standard_Integer component) {
    GProp_PrincipalProps p = props.PrincipalProperties();
    const gp_Vec v = axis == 0 ? p.FirstAxisOfInertia() : (axis == 1 ? p.SecondAxisOfInertia() : p.ThirdAxisOfInertia());
    return component == 0 ? v.X() : (component == 1 ? v.Y() : v.Z());
  }
  static Standard_Boolean HasSymmetryAxis(const GProp_GProps& props) {
    return props.PrincipalProperties().HasSymmetryAxis();
  }
  static Standard_Boolean HasSymmetryPoint(const GProp_GProps& props) {
    return props.PrincipalProperties().HasSymmetryPoint();
  }
};
