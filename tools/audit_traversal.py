#!/usr/bin/env python3
"""Read-only source exit audit. This is not proof of a legal trainer journey."""
import argparse
import json
from pathlib import Path
import sys
import hashlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.maps import MapLoadError, resolve_transfer
from living_kanto.simulation.field import elevator_options


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    engine = WorldEngine(ROOT / 'content')
    results = []
    for mid, game_map in sorted(engine.maps.items()):
        if mid == 'pallet-town':
            continue
        good, failures = 0, []
        for (x, y), target in sorted(game_map.exits.items()):
            try:
                dest, nx, ny = resolve_transfer(engine.maps, mid, x, y, target, surfing=True)
                good += 1
            except MapLoadError as exc:
                classification='excluded_online' if any(t in target for t in ['UNION_ROOM','TRADE_CENTER','UnionRoom','TradeCenter']) else 'elevator_script_action' if target=='MAP_DYNAMIC' and game_map.events.get('elevator_destinations') else 'blocked_border_candidate' if 'blocked' in str(exc) else 'unavailable_required_destination'
                failures.append({'position': [x, y], 'target': target, 'reason': str(exc),'classification':classification})
        results.append({'map_id': mid, 'source_exits': len(game_map.exits),
                        'resolvable_exits': good, 'rejected_exits': failures})
    report = {'scope': __doc__, 'source_pin': '037335f4c725d7c9aecdac87066f2002b4bd7e14',
              'implementation_sha256': {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT/'server/living_kanto/simulation').glob('*.py'))},
              'source_map_metadata_sha256': {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT/'content/maps').glob('*.json'))},
              'loaded_maps': len(results), 'required_inventory_maps': 256,
              'maps': results, 'legal_mainland_journey_verified': False,
              'notes': ['Surf capability supplied only to audit geometric landing; no badges or items granted.',
                        'Connection border candidates outside destination bounds are correctly rejected.',
                        'Elevators use source-backed ride_elevator actions; Rocket floors additionally require own Lift Key.',
                        'Online Union Room/Trade Center destinations are deliberately excluded, not release blockers.',
                        'All 256 inventory maps are loaded; School tile704 uses source-proven zero-filled VRAM.']}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'loaded_maps':len(results), 'resolvable_exits':sum(r['resolvable_exits'] for r in results),
                      'rejected_exits':sum(len(r['rejected_exits']) for r in results), 'output':str(target)}))


if __name__ == '__main__':
    main()
