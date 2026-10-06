"""Real canonical shared movement; fixtures are declared Creative test setup."""
import copy,random
import pytest
from test_gameplay import game,state,scenario,locate,act
from living_kanto.simulation.engine import EngineError,StaleActionError
from living_kanto.mechanics import create_pokemon

def activate(game):
 game[1].set_status('gameplay-test','running');game[0].activate_shared_clock(game[1],'gameplay-test')
def choose(game,hid,action,args,token=None,version=None):
 e,store=game;s=state(game)
 if token is None:_,token=e.capture_decision_boundary(s,hid)
 event,new=e.build_revalidated_action_event(store,'gameplay-test',hid,{'action':action,'arguments':args,'decision_explanation':'Explicit test human intention'},s.state_version if version is None else version,token,{'kind':'user','author':'test'})
 e.commit(store,event);return new

def test_simultaneous_paths_elapsed_once_persistence_replay(game):
 e,store=game
 for hid in ('human-001','human-002'):locate(game,hid,'PalletTown',(10,10))
 activate(game);start=state(game).simulated_time
 # These intents are accepted at the same shared time despite separate commits.
 choose(game,'human-001','travel_to',{'x':10,'y':12});choose(game,'human-002','travel_to',{'x':12,'y':10})
 assert state(game).simulated_time==start
 event=e.tick_shared_time(store,'gameplay-test',start+1);s=state(game)
 assert s.simulated_time==start+1
 assert (s.humans['human-001']['x'],s.humans['human-001']['y'])==(10,11)
 assert (s.humans['human-002']['x'],s.humans['human-002']['y'])==(11,10)
 assert len(event.deterministic_inputs['routes'])==2
 assert store.replay('gameplay-test').state_hash==s.state_hash
 e.tick_shared_time(store,'gameplay-test',start+2);s=state(game)
 assert not s.humans['human-001']['movement_intent'] and not s.humans['human-002']['movement_intent']
 assert s.simulated_time==start+2
 assert store.replay('gameplay-test').state_hash==s.state_hash

def test_unrelated_clock_and_actor_commits_preserve_private_boundary(game):
 e,store=game;activate(game);s=state(game);obs,token=e.capture_decision_boundary(s,'human-001')
 choose(game,'human-002','remember',{'text':'Other accepted thought'})
 e.tick_shared_time(store,'gameplay-test',s.simulated_time+5)
 after=choose(game,'human-001','remember',{'text':'My original private thought'},token=token,version=obs.state_version)
 assert after.humans['human-001']['last_decision']['provenance']['original_observation_version']==obs.state_version
 assert after.humans['human-001']['last_decision']['provenance']['validation_boundary_version']>obs.state_version

def test_local_actor_change_rejects_stale_intent_without_mutation(game):
 e,store=game;activate(game);s=state(game);obs,token=e.capture_decision_boundary(s,'human-001')
 scenario(game,[{'op':'set','path':'humans.human-001.money','value':999}]);before=state(game)
 with pytest.raises(StaleActionError):choose(game,'human-001','remember',{'text':'stale'},token=token,version=obs.state_version)
 assert state(game).state_hash==before.state_hash

def test_scheduled_work_and_movement_share_global_clock(game):
 e,store=game;locate(game,'human-001','PalletTown',(10,10));activate(game);start=state(game).simulated_time
 choose(game,'human-045','work',{});choose(game,'human-001','travel_to',{'x':10,'y':12})
 e.tick_shared_time(store,'gameplay-test',start+1);s=state(game)
 assert s.humans['human-045']['activity']['ready_at']==start+3600
 assert s.simulated_time==start+1 and s.humans['human-001']['y']==11

def test_acceptance_has_no_field_steps_until_actual_tick_and_cancel(game):
 e,store=game;locate(game,'human-001','PalletTown',(10,10));activate(game);start=state(game)
 choose(game,'human-001','travel_to',{'x':10,'y':12});s=state(game)
 assert (s.humans['human-001']['x'],s.humans['human-001']['y'])==(10,10)
 assert s.humans['human-001'].get('field_steps')==start.humans['human-001'].get('field_steps')
 e.tick_shared_time(store,'gameplay-test',s.simulated_time+1);s=state(game)
 assert s.humans['human-001']['field_steps']['poison']==1
 choose(game,'human-001','cancel_movement',{});s=state(game)
 assert s.humans['human-001']['y']==11 and s.humans['human-001']['movement_intent'] is None

def test_battle_freezes_only_own_movement_not_other_actor(game):
 e,store=game
 for hid in ('human-001','human-002'):locate(game,hid,'PalletTown',(10,10))
 activate(game);choose(game,'human-001','travel_to',{'x':10,'y':12});choose(game,'human-002','travel_to',{'x':12,'y':10})
 # Persisted battle input prevents own accepted remainder executing overdue.
 scenario(game,[{'op':'set','path':'humans.human-001.battle_id','value':'test-pending-battle'}]);s=state(game)
 e.tick_shared_time(store,'gameplay-test',s.simulated_time+1);after=state(game)
 assert after.humans['human-001']['y']==10 and after.humans['human-002']['x']==11
 assert after.humans['human-001']['movement_intent']['cursor']==0

def test_legacy_manual_walk_remains_instant_and_advances_one_second(game):
 e,store=game;locate(game,'human-001','PalletTown',(10,10));before=state(game)
 after=act(game,'human-001','walk_to',{'direction':'south'})
 assert after.humans['human-001']['y']==11 and after.simulated_time==before.simulated_time+1
 assert not e.shared_clock_enabled(after)

def test_enter_map_transfer_waits_for_shared_due_boundary(game):
 e,store=game;gm=e.maps['PalletTown'];point=next(p for p,t in gm.exits.items() if t=='PalletTown_ProfessorOaksLab');locate(game,'human-001','PalletTown',point);activate(game);before=state(game)
 choose(game,'human-001','enter_map',{'map_id':'PalletTown_ProfessorOaksLab'});assert state(game).humans['human-001']['map_id']=='PalletTown'
 e.tick_shared_time(store,'gameplay-test',before.simulated_time+1);after=state(game)
 assert after.humans['human-001']['map_id']=='PalletTown_ProfessorOaksLab'
 assert after.simulated_time==before.simulated_time+1
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_activation_migrates_accepted_legacy_journey_provenance(game):
 e,store=game;locate(game,'human-001','PalletTown',(10,10));scenario(game,[{'op':'set','path':'humans.human-001.active_plan','value':{'kind':'journey','destination_map':'PalletTown_ProfessorOaksLab','accepted_state_version':1,'explanation':'Existing accepted real intention','provenance':{'kind':'model','model_id':'local-original'}}}])
 activate(game);h=state(game).humans['human-001']
 assert h['active_plan'] is None and h['movement_intent']['accepted_state_version']==1
 assert h['movement_intent']['provenance']['model_id']=='local-original'
 assert h['movement_intent']['steps'] and h['movement_intent']['next_due_at']==state(game).simulated_time+1

def test_two_source_wild_encounters_same_tick_preserve_both_and_shared_rng(game,monkeypatch):
 import living_kanto.simulation.movement_encounters as movement
 e,store=game;gm=e.maps['Route1'];grass=e.grass_cell;paths=[];used=set()
 from living_kanto.simulation.field import actor_map
 snapshot=state(game);probe={**snapshot.humans['human-001'],'map_id':'Route1'}
 gm=actor_map(gm,probe,snapshot)
 for target,cell in gm.cells.items():
  if not grass('Route1',*target) or target in used:continue
  for direction,(dx,dy) in {'north':(0,-1),'south':(0,1),'east':(1,0),'west':(-1,0)}.items():
   start=(target[0]-dx,target[1]-dy)
   if start not in used and gm.is_walkable(*start) and gm._step_basic(start,direction)==target:
    paths.append((start,target,direction));used.update((start,target));break
  if len(paths)==2:break
 assert len(paths)==2
 for index,hid in enumerate(('human-001','human-002')):
  locate(game,hid,'Route1',paths[index][0]);mon=create_pokemon('PIDGEY',5,hid,random.Random(index),identifier=f'shared-source-mon-{index}')
  scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},{'op':'set','path':f'humans.{hid}.party','value':[mon['pokemon_id']]}])
 row=e.encounter_table('Route1')[0]['land_mons']['mons'][0];draws=[];generators=[]
 def encounter(h,cell,table,party,rng,**kwargs):
  draws.append(rng.randrange(65536));generators.append(rng);return h,{'species':row['species'],'min_level':row['min_level'],'max_level':row['min_level']}
 monkeypatch.setattr(movement,'walking_encounter',encounter)
 activate(game)
 for index,hid in enumerate(('human-001','human-002')):choose(game,hid,'walk_to',{'direction':paths[index][2]})
 before=state(game);e.tick_shared_time(store,'gameplay-test',before.simulated_time+1);after=state(game)
 bids=[after.humans[hid]['battle_id'] for hid in ('human-001','human-002')]
 assert len(set(bids))==2 and all(bid in after.world_facts['battles'] for bid in bids)
 assert all(after.humans[hid]['movement_intent']['paused_for_battle'] for hid in ('human-001','human-002'))
 assert generators[0] is generators[1] and draws[0]!=draws[1]
 assert after.simulated_time==before.simulated_time+1
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_private_same_turn_pending_keeps_opponent_boundary_and_shared_cooldown(game):
 e,store=game
 for index,hid in enumerate(('human-001','human-002')):
  locate(game,hid,'PalletTown',(10,10));mon=create_pokemon('PIDGEY',5,hid,random.Random(index),identifier=f'shared-duel-mon-{index}')
  scenario(game,[{'op':'set','path':f'pokemon.{mon["pokemon_id"]}','value':mon},{'op':'set','path':f'humans.{hid}.party','value':[mon['pokemon_id']]}])
 activate(game);choose(game,'human-001','challenge_trainer',{'human_id':'human-002','doubles':False});e.tick_shared_time(store,'gameplay-test',state(game).simulated_time+1)
 s=state(game);offer=next(a for a in e.legal_actions(s,'human-002') if a.action=='accept_challenge');choose(game,'human-002',offer.action,offer.arguments)
 intro=state(game);assert intro.humans['human-001']['ready_at']==intro.humans['human-002']['ready_at']
 for _ in range(3):e.tick_shared_time(store,'gameplay-test',state(game).simulated_time+10)
 s=state(game);observation,token=e.capture_decision_boundary(s,'human-001')
 choose(game,'human-002','battle_move',{'slot':1})
 assert state(game).simulated_time==s.simulated_time
 after=choose(game,'human-001','battle_move',{'slot':1},token=token,version=observation.state_version)
 assert after.humans['human-001']['ready_at']==after.humans['human-002']['ready_at']==after.simulated_time+30
 assert not e.legal_actions(after,'human-001') and not e.legal_actions(after,'human-002')
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_shared_service_receipt_effective_time_never_claims_future_completion(game):
 e,store=game;staff=next(h for h in state(game).humans.values() if h['role']=='shop_staff' and 'poke_ball' in e.shop_prices(h['map_id']));locate(game,'human-001',staff['map_id']);activate(game)
 choose(game,'human-001','shop_buy',{'item':'poke_ball','quantity':1});s=state(game);request=e.service_actions(s,staff['human_id'])[0];after=choose(game,staff['human_id'],request.action,request.arguments)
 receipt=after.humans['human-001']['last_service']
 assert after.humans['human-001']['ready_at']==after.humans[staff['human_id']]['ready_at']==after.simulated_time+30
 assert receipt['completed_at']==after.simulated_time
 assert receipt['busy_until']==after.simulated_time+30
 assert receipt['effective_at']==after.simulated_time
 assert after.humans['human-001']['inventory']['poke_ball']['quantity']==s.humans['human-001']['inventory'].get('poke_ball',{}).get('quantity',0)+1
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_changed_transfer_interrupts_only_affected_actor(game):
 e,store=game;gm=e.maps['PalletTown'];point=next(p for p,t in gm.exits.items() if t=='PalletTown_ProfessorOaksLab');locate(game,'human-001','PalletTown',point);locate(game,'human-002','PalletTown',(10,10));activate(game)
 choose(game,'human-001','enter_map',{'map_id':'PalletTown_ProfessorOaksLab'});choose(game,'human-002','travel_to',{'x':12,'y':10});locate(game,'human-001','PalletTown',(10,10))
 s=state(game);event=e.tick_shared_time(store,'gameplay-test',s.simulated_time+1);after=state(game)
 assert after.humans['human-001']['movement_intent'] is None
 assert after.humans['human-002']['x']==11
 assert event.deterministic_inputs['routes'][0]['interruption']=='source transfer no longer available'
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_actual_shared_lab_exit_marks_fossil_departure(game):
 from living_kanto.mechanics.acquisition import LAB
 e,store=game;gm=e.maps[LAB];point=next(p for p,t in gm.exits.items() if t=='CinnabarIsland_PokemonLab_Entrance');locate(game,'human-001',LAB,point)
 scenario(game,[{'op':'set','path':'humans.human-001.acquisition','value':{'reviving':{'left_lab':False,'input_item':'helix_fossil','species':'OMANYTE'}}}]);activate(game)
 choose(game,'human-001','enter_map',{'map_id':'CinnabarIsland_PokemonLab_Entrance'});s=state(game);e.tick_shared_time(store,'gameplay-test',s.simulated_time+1)
 assert state(game).humans['human-001']['acquisition']['left_lab'] is True

def test_source_forced_spin_path_cannot_be_cancelled_mid_motion(game):
 e,store=game;gm=e.maps['RocketHideout_B2F'];candidate=None
 for point,cell in gm.cells.items():
  if not gm.is_walkable(*point):continue
  for direction in ('north','south','east','west'):
   path=gm.step_path(point,direction)
   if path and len(path)>1 and int(gm.cells.get(path[0],{}).get('behavior',0)) in range(0x54,0x58):candidate=(point,direction,path);break
  if candidate:break
 assert candidate;point,direction,path=candidate;locate(game,'human-001','RocketHideout_B2F',point);activate(game);choose(game,'human-001','walk_to',{'direction':direction})
 s=state(game);e.tick_shared_time(store,'gameplay-test',s.simulated_time+1);s=state(game)
 assert s.humans['human-001']['movement_intent']['forced_movement'] is True
 assert not e.legal_actions(s,'human-001')
 with pytest.raises(EngineError):choose(game,'human-001','cancel_movement',{})
 assert state(game).state_hash==s.state_hash

def test_traversal_status_change_invalidates_local_boundary(game):
 e,store=game;activate(game);s=state(game);obs,token=e.capture_decision_boundary(s,'human-001')
 scenario(game,[{'op':'set','path':'humans.human-001.status.surfing','value':True}]);before=state(game)
 with pytest.raises(StaleActionError):choose(game,'human-001','remember',{'text':'Obsolete traversal context'},token=token,version=obs.state_version)
 assert state(game).state_hash==before.state_hash

def test_other_customer_append_does_not_invalidate_staff_head_or_purchase(game):
 e,store=game;staff=next(h for h in state(game).humans.values() if h['role']=='shop_staff' and 'poke_ball' in e.shop_prices(h['map_id']))
 for hid in ('human-001','human-002'):locate(game,hid,staff['map_id'])
 activate(game);s=state(game);second_obs,second_token=e.capture_decision_boundary(s,'human-002')
 choose(game,'human-001','shop_buy',{'item':'poke_ball','quantity':1})
 s=state(game);staff_obs,staff_token=e.capture_decision_boundary(s,staff['human_id']);head=e.service_actions(s,staff['human_id'])[0]
 choose(game,'human-002','shop_buy',{'item':'poke_ball','quantity':1},token=second_token,version=second_obs.state_version)
 after=choose(game,staff['human_id'],head.action,head.arguments,token=staff_token,version=staff_obs.state_version)
 queue=e.service_queue(after,staff['map_id']);assert len(queue)==1 and queue[0]['human_id']=='human-002'
 assert after.humans['human-001']['service_request'] is None
 assert store.replay('gameplay-test').state_hash==after.state_hash

def test_same_tick_competing_destination_waits_without_overlap_and_replays(game):
 e,store=game
 locate(game,'human-001','PalletTown',(9,10));locate(game,'human-002','PalletTown',(11,10));activate(game)
 choose(game,'human-001','travel_to',{'x':10,'y':10});choose(game,'human-002','travel_to',{'x':10,'y':10})
 before=state(game);e.tick_shared_time(store,'gameplay-test',before.simulated_time+1);after=state(game)
 assert (after.humans['human-001']['x'],after.humans['human-001']['y'])==(10,10)
 assert (after.humans['human-002']['x'],after.humans['human-002']['y'])==(11,10)
 assert after.humans['human-002']['movement_intent']['collision_waits']==1
 assert store.replay('gameplay-test').state_hash==after.state_hash
