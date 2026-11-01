#!/usr/bin/python3
"""kernelCAD OCCT 8 port: generate the embind/TypeScript sources for exactly
the OCCT symbols a custom build links (the image no longer ships pregenerated
bindings for all ~9000 OCCT classes). Run before fix-destructors.py and
buildFromYaml.py; already generated files are kept."""
import os
import sys
import tempfile

import yaml

config = yaml.safe_load(open(sys.argv[1]))
builds = [config["mainBuild"], *config.get("extraBuilds", [])]
symbols = sorted({b["symbol"] for build in builds for b in build.get("bindings", [])})
with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
  f.write("\n".join(symbols) + "\n")
os.environ["OCJS_SYMBOLS"] = f.name
os.chdir("/opencascade.js/src")
sys.path.insert(0, "/opencascade.js/src")
import generateBindings  # noqa: E402

generateBindings.main()

import compileBindings  # noqa: E402

compileBindings.buildPch({"threading": os.environ.get("threading", "single-threaded")})
