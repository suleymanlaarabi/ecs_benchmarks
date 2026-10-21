#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <siecs-checkout>" >&2
  exit 2
fi

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
requested_root=$1
siecs_commit=4124e2dcc02758e9dd94d57e71bf3f19240eda18
siecs_url=https://github.com/suleymanlaarabi/siecs.git
cache_root="$repo_root/build/siecs/_deps/siecs-src"

if [[ -f "$requested_root/distr/siecs.c" && -f "$requested_root/distr/siecs.h" ]] &&
  [[ "$(git -C "$requested_root" rev-parse HEAD 2>/dev/null)" == "$siecs_commit" ]] &&
  [[ -z "$(git -C "$requested_root" status --porcelain)" ]]; then
  exit 0
fi

mkdir -p "$(dirname -- "$cache_root")"
if [[ ! -d "$cache_root/.git" ]]; then
  git clone --filter=blob:none "$siecs_url" "$cache_root"
fi
git -C "$cache_root" fetch --depth 1 origin "$siecs_commit"
git -C "$cache_root" checkout --detach "$siecs_commit"
