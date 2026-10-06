"""Patients may wait or leave; only a staff decision performs healing."""
import copy,random
import pytest
from test_gameplay import game,act,locate,scenario,state
from living_kanto.mechanics import create_pokemon
from living_kanto.simulation.engine import EngineError,StaleActionError
from test_shared_clock_engine import activate,choose


def queue_patient(game):
 e,_=game;s=state(game);staff=next(h for h in s.humans.values() if h['role']=='service_staff');hid='human-001'
 mon=create_pokemon('PIDGEY',5,hid,random.Random(5),identifier='waiting-patient');mon.update(hp=1,status='psn');mon['moves'][0]['pp']=0
 scenario(game,[{'op':'set','path':'pokemon.waiting-patient','value':mon},{'op':'set','path':f'humans.{hid}.party','value':['waiting-patient']}]);locate(game,hid,staff['map_id'])
 return staff,hid


def test_wait_preserves_position_injuries_and_request_until_staff_serves(game):
 e,store=game;staff,hid=queue_patient(game);before=act(game,hid,'heal_party');request=copy.deepcopy(before.humans[hid]['service_request']);party=copy.deepcopy(before.pokemon)
 assert {a.action for a in e.legal_actions(before,hid)}=={'wait_for_service','cancel_service'}
 waited=act(game,hid,'wait_for_service')
 assert waited.humans[hid]['service_request']==request and waited.pokemon==party
 assert e.service_queue(waited,staff['map_id'])[0]['request_id']==request['request_id']
 assert waited.simulated_time==before.simulated_time+30
 after=act(game,staff['human_id'],'serve_customer',{'request_id':request['request_id']})
 assert after.humans[hid]['service_request'] is None and after.pokemon['waiting-patient']['hp']==after.pokemon['waiting-patient']['stats']['hp']
 assert after.pokemon['waiting-patient']['status']=='' and after.pokemon['waiting-patient']['moves'][0]['pp']==after.pokemon['waiting-patient']['moves'][0]['max_pp']
 assert store.replay('gameplay-test').state_hash==after.state_hash


def test_shared_wait_can_be_cancelled_and_served_response_invalidates_old_wait(game):
 e,store=game;staff,hid=queue_patient(game);activate(game);choose(game,hid,'heal_party',{});s=state(game)
 request=s.humans[hid]['service_request'];obs,token=e.capture_decision_boundary(s,hid)
 waited=choose(game,hid,'wait_for_service',{},token=token,version=obs.state_version)
 assert waited.humans[hid]['service_request']==request and waited.humans[hid]['ready_at']==s.simulated_time+30
 staff_obs,staff_token=e.capture_decision_boundary(waited,staff['human_id'])
 served=choose(game,staff['human_id'],'serve_customer',{'request_id':request['request_id']},token=staff_token,version=staff_obs.state_version)
 with pytest.raises(StaleActionError):choose(game,hid,'wait_for_service',{},token=token,version=obs.state_version)
 assert state(game).state_hash==served.state_hash
 assert store.replay('gameplay-test').state_hash==served.state_hash


def test_wait_without_request_or_with_arguments_fails_without_writing(game):
 staff,hid=queue_patient(game);before=state(game)
 with pytest.raises(EngineError):act(game,hid,'wait_for_service')
 assert state(game).state_hash==before.state_hash
 queued=act(game,hid,'heal_party')
 with pytest.raises(EngineError):act(game,hid,'wait_for_service',{'seconds':30})
 assert state(game).state_hash==queued.state_hash
 cancelled=act(game,hid,'cancel_service')
 assert cancelled.humans[hid]['service_request'] is None
