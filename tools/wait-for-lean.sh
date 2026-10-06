#!/usr/bin/env bash
set -eu
experiment_root=/mnt/data/zhengyang-workspace/fermat-example
while ! test -f "$experiment_root/.humanize/lean-ready"; do
  if test -f "$experiment_root/.humanize/lean-build-failed"; then
    printf '%s\n' 'The pinned Lean dependency build failed; inspect .humanize/mathlib-build.log.' >&2
    exit 1
  fi
  printf '%s\n' 'Waiting for the pinned Lean 4.33.1 mathlib build...'
  sleep 30
done
