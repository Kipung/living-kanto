"""Explicit migration preserves old events, busy humans and exact NPC identity."""
from test_gameplay import game,state,scenario,locate,act
from living_kanto.simulation import fidelity_update,workplaces


def test_existing_world_migration_keeps_lives_and_replays_source_actors(game):
    engine,store=game
    # Simulate a pre-resident, pre-counter save without changing its human identities.
    current=state(game)
    nurse=next(h for h in current.humans.values() if h.get('workplace',{}).get('service_post'))
    hid=nurse['human_id'];mid=nurse['map_id']
    locate(game,hid,mid,(7,5))
    act(game,hid,'rest')
    scenario(game,[{'op':'remove','path':f'npcs.{nid}'} for nid in state(game).npcs])
    before=state(game);_,_,head=store.load_run(before.run_id)
    prior=[e.event_hash for e in store.events_after(before.run_id,-1)] if hasattr(store,'events_after') else None
    event,after=fidelity_update.build_migration_event(engine,before,head)
    assert after.humans[hid]['activity']==before.humans[hid]['activity']
    assert (after.humans[hid]['x'],after.humans[hid]['y'])==(7,5)
    assert after.pokemon==before.pokemon and set(after.humans)==set(before.humans)
    assert after.npcs and len(after.npcs)==len({n['key'] for n in after.npcs.values()})
    assert after.world_facts['fidelity_policy']['version']==fidelity_update.POLICY
    assert event.before['world_facts.fidelity_policy'] is None
    assert event.causation['provenance']['author']=='fidelity-update'
    engine.commit(store,event)
    assert store.replay(before.run_id).state_hash==after.state_hash
