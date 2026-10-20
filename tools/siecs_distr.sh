#!/usr/bin/env bash
# usage: siecs_distr.sh <siecs-tree> <out-root>
# Regenerates <out-root>/distr/siecs.{c,h} from a Siecs source tree with the
# tree's own tools/rebuild_distr.sh, inside a throwaway BAKE_HOME. Running that
# script against the real BAKE_HOME re-registers the `siecs` package to its
# temporary copy, leaving dangling include links behind once it is deleted.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <siecs-tree> <out-root>" >&2
  exit 2
fi

tree=$(cd -- "$1" && pwd)
mkdir -p "$2"
out=$(cd -- "$2" && pwd)
bake_bin=${BAKE:-bake}
host_home=$("$bake_bin" env | sed -n 's/^BAKE_HOME=//p')
home=$(mktemp -d "${TMPDIR:-/tmp}/siecs-distr-home.XXXXXX")
trap 'rm -rf "$home"' EXIT

cp -R "$host_home/include" "$host_home/lib" "$host_home/meta" "$home/"
BAKE_HOME=$home sh "$tree/tools/rebuild_distr.sh" "$out"
