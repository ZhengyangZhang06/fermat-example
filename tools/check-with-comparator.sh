#!/usr/bin/env bash
set -eu
exec /home/ubuntu/.local/bin/python3.12 /mnt/data/zhengyang-workspace/fermat-example/tools/verify-node.py "$@"
