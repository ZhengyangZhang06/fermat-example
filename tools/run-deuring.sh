#!/usr/bin/env bash
set -euo pipefail
experiment_root=/mnt/data/zhengyang-workspace/fermat-example
cd "$experiment_root"
export CODEX_HOME=/home/ubuntu/.codex
export PATH="$experiment_root/.humanize/toolchains/lean-4.33.1-linux/bin:/home/ubuntu/.local/bin:$PATH"
export PYTHONPATH=/mnt/data/zhengyang-workspace/humanize2/src:/mnt/data/zhengyang-workspace/humanize2/.venv/lib/python3.12/site-packages
export PYTHONUNBUFFERED=1
agent_spec=$(/home/ubuntu/.local/bin/python3.12 - <<'PY'
import os, tomllib
from pathlib import Path
config = tomllib.loads((Path(os.environ['CODEX_HOME']) / 'config.toml').read_text())
provider = config.get('model_provider', '')
endpoint = config.get('model_providers', {}).get(provider, {}).get('base_url', '')
if 'rust.cat' in endpoint.lower():
    raise SystemExit('Forbidden provider endpoint')
model = config['model']
effort = config['model_reasoning_effort']
print(f'cli=codex,model={model},effort={effort},permission=auto,web_search=off')
PY
)
exec /home/ubuntu/.local/bin/python3.12 -m hmz exec \
  -f "$experiment_root/.humanize/flows/math-lean-flow:github-theorem-prover" \
  -c github-theorems.yaml -a "$agent_spec" -a "$agent_spec" "$(<PROBLEM.md)"
