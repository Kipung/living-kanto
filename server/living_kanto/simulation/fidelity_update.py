"""Audited, explicit source resident/counter migration; retains ongoing lives."""
from . import workplaces, source_npcs
from ..contracts import CanonicalEvent, StateUpdate
from ..contracts.base import content_hash
POLICY = 'source-residents-and-counters-v1'


def build_migration_event(engine, before, head):
    changes = workplaces.migration_changes(engine, before)
    existing = before.npcs
    additions = source_npcs.initial_actors(engine, before.humans)
    for nid, npc in additions.items():
        if nid not in existing:
            changes.append({'op':'set','path':f'npcs.{nid}','value':npc})
    changes.extend([
        {'op':'set','path':'world_facts.source_npc_policy','value':{'version':'source-residents-v1','population':len(additions),'movement':'source_positions_with_courtesy'}},
        {'op':'set','path':'world_facts.fidelity_policy','value':{'version':POLICY,'applied_at':before.simulated_time}},
        {'op':'set','path':'world_facts.last_intervention','value':{'author':'fidelity-update','kind':'source_residents_and_counters','preserved_ongoing_activities':True}},
    ])
    from .world import expand_entity_sets
    changes=expand_entity_sets(changes)
    after = before.with_advanced_version(changes)
    assert set(after.humans) == set(before.humans) and after.pokemon == before.pokemon
    for hid, human in before.humans.items():
        for key,value in human.items():
            if key not in {'map_id','x','y','facing','workplace','home_location'}:
                assert after.humans[hid].get(key) == value, (hid,key)
    idx = before.state_version; eid=f'evt-{idx}-{content_hash(changes)[:24]}'
    update=StateUpdate(run_id=before.run_id,event_id=eid,event_index=idx,prior_state_version=idx,
        prior_state_hash=before.state_hash,previous_head=head,state_version=after.state_version,
        state_hash=after.state_hash,changes=changes).validate()
    def values(snapshot):
        saved=snapshot.to_dict(); result={}
        for change in changes:
            value=saved
            for part in change['path'].split('.'):
                value=value.get(part) if isinstance(value,dict) else None
            result[change['path']]=value
        return result
    people=sorted({c['path'].split('.')[1] for c in changes if c['path'].startswith('humans.')})
    event=CanonicalEvent(run_id=before.run_id,event_id=eid,event_index=idx,state_version=after.state_version,
        previous_head=head,event_kind='intervention.applied',tick=after.tick,simulated_time=after.simulated_time,
        real_wall_time=engine._wall_time(),causation={'human_id':'user',
            'decision_explanation':'User authorized original residents, source nurse counters and battle venues; preserve existing people and history',
            'provenance':{'kind':'user','author':'fidelity-update'}},
        affected=[{'human_id':hid} for hid in people]+[{'npc_id':nid} for nid in additions if nid not in existing],
        before=values(before),after=values(after),deterministic_inputs={'fidelity_policy':POLICY},
        transaction={'kind':'state_update',**update.to_dict()},visibility={'public':True}).validate()
    return event,after
