"""Transfer UTF-8 source bytes to the two named Mock containers, independent of PS codecs."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bootstrap(mode, label=None, as_of=None):
    if mode not in ('core', 'expanded'):
        raise ValueError('unknown data mode')
    script = 'prepare_demo.py' if mode == 'core' else 'generate_demo_data.py'
    args = ['--run-label', label] if mode == 'core' else ['--as-of', as_of or datetime.now(timezone.utc).isoformat()]
    if mode == 'core' and not label:
        raise ValueError('explicit named core run required')
    source = (ROOT / 'scripts' / script).read_bytes()
    state = {}
    for stage in ('C', 'D'):
        response = subprocess.run(['docker', 'exec', '-i', 'fde-stage-' + stage.lower() + '-api-1', 'python', '-', *args],
                                  input=source, capture_output=True, check=True)
        state[stage] = json.loads(response.stdout.decode('utf-8'))
    filename = 'demo-state.json' if mode == 'core' else 'stage-f-demo-state.json'
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'data' / filename).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Fresh fictional ' + mode + ' run saved; existing source records retained.')
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['core', 'expanded'], required=True)
    parser.add_argument('--label')
    parser.add_argument('--as-of')
    opts = parser.parse_args()
    bootstrap(opts.mode, opts.label, opts.as_of)
