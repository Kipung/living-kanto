"""Apply an explicitly authorized workplace correction without resetting a run."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation import workplaces
from living_kanto.store import RunStore

root = Path(__file__).resolve().parents[1]
run = sys.argv[1]
store = RunStore(root / 'data' / (run + '.db'))
_, before, head = store.load_run(run)
print(json.dumps({'stage':'verified_history','state_version':before.state_version,'head':head}), flush=True)
if before.world_facts.get('workplace_policy', {}).get('version') == workplaces.POLICY:
    print('Workplace policy already applied', flush=True)
    sys.exit(0)
engine = WorldEngine(root / 'content')
event, after = workplaces.build_migration_event(engine, before, head)
assert set(before.humans) == set(after.humans) and before.pokemon == after.pokemon
for hid, h in before.humans.items():
    for key in h:
        if key not in {'map_id','x','y','workplace','home_location'}:
            assert after.humans[hid].get(key) == h[key], (hid,key)
assert after.state_version == before.state_version + 1
engine.commit(store, event)
print(json.dumps({'stage':'migration_committed','before_version':before.state_version,'after_version':after.state_version,
    'before_head':head,'event_id':event.event_id,'after_hash':after.state_hash,
    'policy':after.world_facts['workplace_policy'],
    'assigned':sum(bool(h.get('workplace')) for h in after.humans.values()),
    'at_workplace':sum(h.get('workplace',{}).get('map_id')==h['map_id'] for h in after.humans.values())}), flush=True)
store.close()
