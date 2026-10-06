"""Explicit authorized migration using full ordinary save verification."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'server'))
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation import fidelity_update
from living_kanto.store import RunStore
run=sys.argv[1];store=RunStore(root/'data'/(run+'.db'))
_,before,head=store.load_run(run)
print(json.dumps({'stage':'verified_history','state_version':before.state_version,'head':head}),flush=True)
if before.world_facts.get('fidelity_policy',{}).get('version')==fidelity_update.POLICY:
    print('Fidelity update already applied',flush=True);sys.exit(0)
if store.get_status(run)!='paused':raise RuntimeError('Pause the world before migration')
engine=WorldEngine(root/'content');event,after=fidelity_update.build_migration_event(engine,before,head)
engine.commit(store,event)
print(json.dumps({'stage':'migration_committed','before_version':before.state_version,'after_version':after.state_version,
    'state_hash':after.state_hash,'event_id':event.event_id,'people':len(after.humans),'source_residents':len(after.npcs),
    'nurse_posts':sum(bool(h.get('workplace',{}).get('service_post')) for h in after.humans.values())}),flush=True)
store.close()
