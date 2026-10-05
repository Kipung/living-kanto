"""Optimization must retain canonical hashes, pure source counters and isolation."""
import copy,random
import pytest
from test_gameplay import game,state,scenario,locate
from living_kanto.contracts.base import ContractError
from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.movement_encounters import intercept

def test_checked_event_matches_reference_and_isolates_values(game):
 e,store=game;s=state(game);head=store.load_head('gameplay-test');changes=[{'op':'set','path':'humans.human-001.goal','value':{'text':'independent accepted goal'}}];prior=s.to_dict();reference=s.with_advanced_version(copy.deepcopy(changes))
 event,new=e._shared_event(s,head,changes,kind='world.public_event',causation={'human_id':'engine','provenance':{'kind':'engine'}})
 assert new.to_dict()==reference.to_dict() and new.state_hash==reference.state_hash
 changes[0]['value']['text']='caller mutation'
 assert new.humans['human-001']['goal']['text']=='independent accepted goal'
 assert s.to_dict()==prior
 assert event.transaction['state_hash']==reference.state_hash

def test_checked_event_rejects_tampered_prior_binding(game):
 e,store=game;s=state(game);s.humans['human-001']['money']+=1
 with pytest.raises(ContractError,match='hash mismatch'):e._shared_event(s,store.load_head('gameplay-test'),[],kind='world.public_event',causation={'human_id':'engine','provenance':{'kind':'engine'}})

def test_compact_source_steps_match_existing_friendship_poison_repel_rng(game):
 e,store=game;hid='human-001';locate(game,hid,'PalletTown',(10,10));mon=create_pokemon('PIDGEY',5,hid,random.Random(1),identifier='compact-source-mon');mon['status']='psn';mon['hp']=10
 scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},{'op':'set','path':f'humans.{hid}.party','value':[mon['pokemon_id']]},{'op':'set','path':f'humans.{hid}.field_steps','value':{'happiness':127,'poison':4}},{'op':'set','path':f'humans.{hid}.field_encounter','value':{'map_id':'Route1','repel_steps':10}}])
 s=state(game);intent={'forced_movement':False};cell=e.maps['PalletTown'].cells[(10,11)];evidence={'map_id':'PalletTown','start':[10,10],'steps':[[10,11]],'duration_seconds':1};base=[{'op':'set','path':f'humans.{hid}.y','value':11}];fast_rng=random.Random(17);old_rng=random.Random(17)
 fast_changes,fast_evidence=e._ordinary_tile_effects(s,hid,intent,cell,copy.deepcopy(evidence),copy.deepcopy(base),fast_rng)
 old_changes,_,old_evidence,kind=intercept(e,s,hid,'travel_to',{'x':10,'y':11},{'kind':'user'},'Declared source equivalence',copy.deepcopy(evidence),copy.deepcopy(base),1,rng=old_rng)
 assert kind is None and fast_evidence==old_evidence and fast_rng.getstate()==old_rng.getstate()
 assert s.apply_changes(fast_changes).to_dict()==s.apply_changes(old_changes).to_dict()
 assert s.pokemon[mon['pokemon_id']]['hp']==10
 assert s.apply_changes(fast_changes).pokemon[mon['pokemon_id']]['hp']==9

def test_compact_whiteout_fallback_restores_rng_and_input_changes(game):
 e,store=game;hid='human-001';locate(game,hid,'PalletTown',(10,10));mon=create_pokemon('PIDGEY',5,hid,random.Random(1),identifier='compact-faint-mon');mon['status']='psn';mon['hp']=1
 scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},{'op':'set','path':f'humans.{hid}.party','value':[mon['pokemon_id']]},{'op':'set','path':f'humans.{hid}.field_steps','value':{'happiness':127,'poison':4}}]);s=state(game);rng=random.Random(17);original=rng.getstate();base=[{'op':'set','path':f'humans.{hid}.y','value':11}];before=copy.deepcopy(base)
 result=e._ordinary_tile_effects(s,hid,{},e.maps['PalletTown'].cells[(10,11)],{'steps':[[10,11]],'duration_seconds':1},base,rng)
 assert result is None and rng.getstate()==original and base==before
 assert s.pokemon[mon['pokemon_id']]['hp']==1
