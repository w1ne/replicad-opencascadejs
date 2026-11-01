# kernelCAD opencascade.js toolchain: the opencascade.js v2 binding generator
# and emsdk 3.1.14 from donalffons/opencascade.js, rebuilt against OCCT 8.0.1.
#
# The base image ships OCCT 7.6.2 plus ~9000 pregenerated bindings for it. This
# image replaces OCCT with V8_0_1, ports the generator to OCCT 8's
# src/<Module>/<Toolkit>/<Package> layout and API (see ../README.md, "OCCT 8"),
# and compiles OCCT into one static archive per toolkit. Bindings are generated
# per build for exactly the linked symbols (prepareBindings.py), so the build
# commands are:
#
#   python3 /opencascade.js/src/prepareBindings.py <config>.yml
#   python3 /src/fix-destructors.py <config>.yml
#   /opencascade.js/src/buildFromYaml.py <config>.yml
#
# Build: docker build -t kernelcad-ocjs-occt8 toolchain/   (~1-2 h, 4 cores)
FROM docker.io/donalffons/opencascade.js@sha256:3069f4c2e3ab62bb82d81843bad2c0f8552ee92373208f8f655ef9bf71c0524d

ARG OCCT_TAG=V8_0_1
ARG OCCT_COMMIT=b8f597c677811d1f9f4d8a97f5ae2825c0353a42

# Drop OCCT 7.6 and its pregenerated bindings/objects: buildFromYaml links every
# binding object it finds under /opencascade.js/build.
RUN rm -rf /occt /opencascade.js/build \
 && git clone --depth 1 --branch "$OCCT_TAG" https://github.com/Open-Cascade-SAS/OCCT.git /occt \
 && test "$(git -C /occt rev-parse HEAD)" = "$OCCT_COMMIT" \
 && rm -rf /occt/.git /occt/tests /occt/data /occt/dox /occt/samples

# OCCT source patches (kernelCAD JS-API compatibility, see occt8-kernelcad.patch)
COPY occt8-kernelcad.patch gen-occt8-compat.py /tmp/kcad/
RUN cd /occt && patch -p1 < /tmp/kcad/occt8-kernelcad.patch \
 && python3 /tmp/kcad/gen-occt8-compat.py /occt

# Generator port: patch the v2 sources in place and add the new modules.
COPY ocjs-occt8.patch /tmp/kcad/
COPY ocjs/ /opencascade.js/src/
RUN cd /opencascade.js/src && patch -p1 < /tmp/kcad/ocjs-occt8.patch \
 && rm -rf /opencascade.js/src/__pycache__ /opencascade.js/src/*/__pycache__

# Compile OCCT 8: opencascade.js's 7.6 flags plus -std=c++17, at -O3 instead of -Os
# (pass --build-arg OCJS_OPT=-Os for the smaller, ~2x slower module).
ARG OCJS_OPT=-O3
RUN OCJS_OPT="$OCJS_OPT" python3 /opencascade.js/src/compileSources8.py \
 && rm -rf /opencascade.js/build/sources \
 && mkdir -p /opencascade.js/build/bindings \
 && chmod -R a+rwX /opencascade.js/build /opencascade.js/src \
 && ls -la /opencascade.js/build/occt-libs

ENV OCCT_VERSION=8.0.1 OCCT_COMMIT_HASH_FULL=$OCCT_COMMIT
WORKDIR /src/
