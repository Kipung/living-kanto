"""Read-only snapshot comparison. No model calls or world commits.

Usage: PYTHONPATH=server python tools/evaluate_behavior.py before.json after.json
Snapshots are canonical WorldState JSON (or API wrappers with a state field).
"""
import argparse
import json
from pathlib import Path
from living_kanto.contracts import WorldState
from living_kanto.runtime.behavior_evaluation import interval_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before',type=Path)
    parser.add_argument('after',type=Path)
    args=parser.parse_args()
    def read(path):
        payload=json.loads(path.read_text())
        state=WorldState.from_dict(payload.get('state',payload))
        state.verify()
        return state
    print(json.dumps(interval_report(read(args.before),read(args.after)),indent=2))


if __name__=='__main__':main()
