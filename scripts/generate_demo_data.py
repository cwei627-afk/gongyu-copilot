"""Run inside an existing Mock container or choose an independent local directory."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import data_directory
from app.demo_dataset.generate import generate
from app.demo_dataset.display_ids import provision

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True, help='Explicit ISO timestamp with timezone; same timestamp + seed is idempotent')
    parser.add_argument('--directory', default=None)
    parser.add_argument('--seed', type=int, default=20261003)
    args = parser.parse_args()
    directory = Path(args.directory) if args.directory else data_directory()
    result = generate(directory, datetime.fromisoformat(args.as_of), args.seed, include_frozen=True)
    provision(directory)
    print(json.dumps(result, ensure_ascii=False))
