#!/usr/bin/env bash
# Compare this fork's build-source against upstream replicad-opencascadejs.
#
# Upstream is NOT a standalone repo and this is NOT a GitHub fork, so there is no
# `git fetch upstream` path. Upstream lives inside the replicad monorepo at
# sgenoud/replicad -> packages/replicad-opencascadejs/. This script is the only
# thing that will tell you the two have drifted.
#
# Exit 0 = no upstream symbols missing. Exit 1 = we are behind on something.
# Symbols we add that upstream lacks are expected and reported, not failed on.

set -euo pipefail

UPSTREAM_PATH="packages/replicad-opencascadejs/build-source/defaults.yml"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OURS="$REPO_ROOT/build-source/defaults.yml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v gh >/dev/null || { echo "error: gh CLI required" >&2; exit 2; }

gh api "repos/sgenoud/replicad/contents/$UPSTREAM_PATH" --jq '.content' \
  | base64 -d > "$TMP/upstream.yml"

syms() { grep -oE 'symbol: [A-Za-z0-9_]+' "$1" | sort -u; }

missing="$(comm -23 <(syms "$TMP/upstream.yml") <(syms "$OURS") || true)"
extra="$(comm -13 <(syms "$TMP/upstream.yml") <(syms "$OURS") || true)"

echo "upstream symbols: $(syms "$TMP/upstream.yml" | wc -l | tr -d ' ')"
echo "ours:             $(syms "$OURS" | wc -l | tr -d ' ')"
echo

if [ -n "$extra" ]; then
  echo "ours-only (intentional divergence -- keep these across any upstream merge):"
  echo "$extra" | sed 's/^/  + /'
  echo
fi

# buildFlags and additionalCppCode drift silently and matter as much as symbols:
# a changed -O level or a reworked wrapper class will not show up in a symbol diff.
extract() { # $1=file $2=section -- buildFlags stops at additionalCppCode, which runs to EOF
  if [ "$2" = "buildFlags" ]; then
    sed -n '/buildFlags:/,/additionalCppCode:/p' "$1"
  else
    sed -n '/additionalCppCode:/,$p' "$1"
  fi
}

for section in buildFlags additionalCppCode; do
  if ! diff -q <(extract "$TMP/upstream.yml" "$section") \
               <(extract "$OURS" "$section") >/dev/null 2>&1; then
    echo "NOTE: '$section' differs from upstream -- review manually:"
    diff <(extract "$TMP/upstream.yml" "$section") \
         <(extract "$OURS" "$section") | head -40 | sed 's/^/  /' || true
    echo
  fi
done

if [ -n "$missing" ]; then
  echo "BEHIND UPSTREAM -- these symbols exist upstream but not here:"
  echo "$missing" | sed 's/^/  - /'
  echo
  echo "Add them to build-source/defaults.yml, then rebuild (see README)."
  exit 1
fi

echo "OK: not missing any upstream symbol."
