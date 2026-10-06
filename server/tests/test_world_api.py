"""Independent world lifecycle/player/privacy integration gates."""
import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from living_kanto.api.app import create_app
from living_kanto.runtime import ProviderError
from living_kanto.simulation.world import ROLE_COUNTS

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world_client(tmp_path):
    app = create_app(tmp_path / 'runs', content_root=ROOT / 'content', client_root=ROOT / 'client')
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app


def create(client, mode='observer'):
    result = client.post('/worlds', json={'run_id': 'review-world', 'mode': mode, 'seed': 17})
    assert result.status_code == 201, result.text
    return 'review-world'


def snapshot(client, run):
    return client.get(f'/runs/{run}').json()['state']


def test_world_population_private_identity_and_replay(world_client):
    client, app = world_client
    run = create(client)
    state = snapshot(client, run)
    assert len(state['humans']) == 100
    assert Counter(h['role'] for h in state['humans'].values()) == ROLE_COUNTS
    human = state['humans']['human-001']
    assert human['personality'] and human['biography'] and human['memories'] and human['relationships']
    observation = client.get(f'/runs/{run}/observations/human-001')
    assert observation.status_code == 200, observation.text
    observed = observation.json()
    assert 'seed' not in json.dumps(observed)
    assert observed['self_state']['personality'] == human['personality']
    assert all('memories' not in other and 'relationships' not in other for other in observed['visible_actors'])
    replay = client.get(f'/runs/{run}/replay').json()
    assert replay['verified'] and replay['inference_calls'] == 0
    assert replay['state']['state_hash'] == state['state_hash']
    assert client.get(f'/runs/{run}/runtime').json()['phase'] == 'paused'


def test_paused_survival_input_and_stale_duplicate_rejection(world_client):
    client, app = world_client
    run = create(client, 'survival')
    result = client.post(f'/runs/{run}/player/create', json={'expected_state_version': 0})
    assert result.status_code == 200, result.text
    version = result.json()['state_version']
    request = {'human_id': 'player', 'expected_state_version': version, 'action': 'wait', 'arguments': {}}
    accepted = client.post(f'/runs/{run}/player', json=request)
    assert accepted.status_code == 200, accepted.text
    assert client.post(f'/runs/{run}/player', json=request).status_code == 409
    after = snapshot(client, run)
    assert after['state_version'] == version + 1
    assert after['simulated_time'] == 1
    assert client.get(f'/runs/{run}/runtime').json()['phase'] == 'paused'
    forbidden = dict(request, human_id='human-001', expected_state_version=after['state_version'])
    assert client.post(f'/runs/{run}/player', json=forbidden).status_code == 403
    illegal = dict(request, action='become_champion', expected_state_version=after['state_version'])
    assert client.post(f'/runs/{run}/player', json=illegal).status_code == 400
    assert snapshot(client, run)['state_hash'] == after['state_hash']
    assert client.get(f'/runs/{run}/replay').json()['state']['state_hash'] == after['state_hash']


def test_creative_interventions_permanent_and_stale(world_client):
    client, app = world_client
    run = create(client, 'creative')
    request = {'expected_state_version': 0, 'kind': 'money', 'human_id': 'human-001', 'arguments': {'value': 12345}}
    result = client.post(f'/runs/{run}/interventions', json=request)
    assert result.status_code == 200, result.text
    state = snapshot(client, run)
    assert state['humans']['human-001']['money'] == 12345
    assert state['world_facts']['creative_modified']
    assert client.post(f'/runs/{run}/interventions', json=request).status_code == 409
    assert snapshot(client, run)['state_hash'] == state['state_hash']
    exported = client.get(f'/runs/{run}/export').json()
    event = exported['events'][-1]
    assert event['causation']['before']['money'] != 12345
    assert event['causation']['after']['money'] == 12345
    assert event['causation']['provenance']['kind'] == 'creative'
    assert client.get(f'/runs/{run}/replay').json()['state']['state_hash'] == state['state_hash']


def test_observer_read_only_commands(world_client):
    client, app = world_client
    run = create(client)
    original = snapshot(client, run)
    assert client.get(f'/runs/{run}/observer/humans').status_code == 200
    assert client.post(f'/runs/{run}/player/create', json={'expected_state_version': 0}).status_code == 403
    assert client.post(f'/runs/{run}/interventions', json={'expected_state_version':0,'kind':'money','human_id':'human-001','arguments':{'value':1}}).status_code == 403
    assert snapshot(client, run)['state_hash'] == original['state_hash']


def test_runtime_failure_and_export_no_local_settings(world_client):
    client, app = world_client
    run = create(client)
    controller = app.state.get_runtime_controller(run)
    class FailingLocalProvider:
        model_id = 'private-local-test'
        protocol = 'test'
        test_provider = True
        def complete(self, observation, correction=None):
            raise ProviderError('Endpoint unavailable')
    controller.provider = FailingLocalProvider()
    before = snapshot(client, run)
    result = client.post(f'/runs/{run}/step', json={})
    assert result.status_code == 200, result.text
    assert not result.json()['accepted']
    assert controller.status()['failure']['human_id'] == 'human-001'
    assert snapshot(client, run)['state_hash'] == before['state_hash']
    exported = client.get(f'/runs/{run}/export')
    assert exported.status_code == 200
    assert exported.json()['inference_settings_included'] is False
    assert all(secret not in exported.text for secret in ('api_key', 'base_url', '127.0.0.1', 'LIVING_KANTO_MODEL_ENDPOINT'))

def test_starter_persistent_individual_and_private_observation(world_client):
    client, app = world_client
    run = create(client, 'creative')
    assert client.post(f'/runs/{run}/player/create', json={'expected_state_version': 0}).status_code == 200
    controller = app.state.get_runtime_controller(run)
    lab = controller.engine.maps['PalletTown_ProfessorOaksLab']
    x, y = lab.first_open_cell((5, 5))
    teleport = client.post(f'/runs/{run}/interventions', json={'expected_state_version':1,'kind':'teleport','human_id':'player','arguments':{'map_id':'PalletTown_ProfessorOaksLab','x':x,'y':y}})
    assert teleport.status_code == 200, teleport.text
    starter = client.post(f'/runs/{run}/player', json={'expected_state_version':2,'action':'choose_starter','arguments':{'species':'Bulbasaur'}})
    assert starter.status_code == 200, starter.text
    state = snapshot(client, run)
    pokemon_id = state['humans']['player']['party'][0]
    assert pokemon_id in state['pokemon']
    assert state['pokemon'][pokemon_id]['owner_id'] == 'player'
    observed = client.get(f'/runs/{run}/observations/player')
    assert observed.status_code == 200, observed.text
    assert observed.json()['party'][0]['pokemon_id'] == pokemon_id
    assert not any(action['action'] == 'choose_starter' for action in observed.json()['legal_actions'])
    assert client.get(f'/runs/{run}/replay').json()['state']['state_hash'] == state['state_hash']

def test_official_team_separate_from_personal_party(world_client):
    client,app=world_client
    run=create(client)
    current=snapshot(client,run)
    for human in current['humans'].values():
        official=human.get('official_challenge_team',[])
        if official:
            assert set(official).isdisjoint(human['party'])
            assert all(current['pokemon'][pid]['owner_id']==human['human_id'] for pid in official+human['party'])
            observed=client.get(f'/runs/{run}/observations/{human["human_id"]}')
            assert observed.status_code==200,observed.text
            assert {p['pokemon_id'] for p in observed.json()['party']}==set(human['party'])


def test_restart_pending_battle_private_choice_exact_recovery(tmp_path):
    import random
    from living_kanto.mechanics import create_pokemon
    from living_kanto.runtime import RuntimeController
    from test_runtime import TestProvider,action
    base=tmp_path/'runs'
    app=create_app(base,content_root=ROOT/'content',client_root=ROOT/'client')
    run='review-world'
    with TestClient(app) as client:
        create(client,'creative')
        controller=app.state.get_runtime_controller(run);engine=controller.engine;store=controller.store
        _,current,_=store.load_run(run)
        brock=next(h for h in current.humans.values() if h['name']=='Brock')
        mon=create_pokemon('VENUSAUR',100,'human-001',random.Random(11),identifier='pokemon-restart-test')
        mon['moves']=[{'move':'RAZOR_LEAF','pp':25,'max_pp':25}]
        changes=[{'op':'set','path':'pokemon.pokemon-restart-test','value':mon},
                 {'op':'set','path':'humans.human-001.party','value':[mon['pokemon_id']]}]
        changes += [{'op':'set','path':f'humans.human-001.{k}','value':brock[k]} for k in ['map_id','x','y']]
        engine.commit_changes(store,run,changes,kind='intervention.applied',actor='test',
            explanation='Creative restart test fixture, not autonomous evidence',provenance={'kind':'creative'},expected_version=0)
        def commit(actor,name,args):
            version=store.load_run(run)[1].state_version
            event,_=engine.build_action_event(store,run,actor,action=name,arguments=args,observation_version=version,
                expected_state_version=version,decision_explanation='Scripted test input',decision_provenance={'kind':'user'})
            engine.commit(store,event)
        commit('human-001','start_battle',{'human_id':brock['human_id']})
        own_observation=engine.get_observation(store,run,brock['human_id'])
        assert own_observation.self_state['challenge_team_active']
        assert {p['pokemon_id'] for p in own_observation.party}==set(brock['official_challenge_team'])
        assert {p['pokemon_id'] for p in own_observation.party}.isdisjoint(brock['party'])
        defender_before=own_observation.revealed_battle_info
        commit('human-001','battle_move',{'slot':1})
        pending_state=store.load_run(run)[1]
        assert engine.get_observation(store,run,brock['human_id']).revealed_battle_info==defender_before
        version=pending_state.state_version;hash_before=pending_state.state_hash
    restarted=create_app(base,content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(restarted) as client:
        c=restarted.state.get_runtime_controller(run)
        assert c.status()['phase']=='paused'
        recovered=c.store.load_run(run)[1]
        assert recovered.state_hash==hash_before
        assert not c.engine.battle_actions(recovered,'human-001')
        defender=c.engine.get_observation(c.store,run,brock['human_id'])
        assert defender.revealed_battle_info==defender_before
        move=next(option for option in defender.legal_actions if option.action=='battle_move')
        c.provider=TestProvider([action(move.action,move.arguments)])
        result=client.post(f'/runs/{run}/step',json={'human_id':brock['human_id']})
        assert result.status_code==200,result.text
        assert result.json()['accepted']
        assert c.store.load_run(run)[1].state_version==version+1
        assert client.get(f'/runs/{run}/replay').json()['state']['state_hash']==c.store.load_run(run)[1].state_hash

def test_portable_import_preserves_history_and_rejects_tampering(world_client,tmp_path):
    client,app=world_client;run=create(client,'creative')
    assert client.post(f'/runs/{run}/interventions',json={'expected_state_version':0,'kind':'money','human_id':'human-001','arguments':{'value':1234}}).status_code==200
    bundle=client.get(f'/runs/{run}/export').json()
    expected=snapshot(client,run)['state_hash']
    target=create_app(tmp_path/'restored',content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(target,raise_server_exceptions=False) as restored:
        result=restored.post('/runs/import',json=bundle)
        assert result.status_code==201,result.text
        assert result.json()['state_hash']==expected
        assert result.json()['status']=='paused'
        assert restored.get(f'/runs/{run}/replay').json()['state']['state_hash']==expected
        assert restored.get(f'/runs/{run}/export').json()['events']==bundle['events']
        assert restored.post('/runs/import',json=bundle).status_code==409
        assert restored.post(f'/runs/{run}/test_append').status_code==403
    import copy
    damaged=copy.deepcopy(bundle);damaged['events'][0]['transaction']['changes'][0]['value']=9999
    badtarget=create_app(tmp_path/'invalid',content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(badtarget,raise_server_exceptions=False) as invalid:
        assert invalid.post('/runs/import',json=damaged).status_code==400
        assert not (tmp_path/'invalid'/f'{run}.db').exists()
        assert not list((tmp_path/'invalid').glob('.import-*'))
        damaged_receipt=copy.deepcopy(bundle);damaged_receipt['events'][-1]['causation']['decision_explanation']='Forged final receipt'
        assert invalid.post('/runs/import',json=damaged_receipt).status_code==400
        credentials=copy.deepcopy(bundle);credentials['metadata']['api_key']='secret-test'
        assert invalid.post('/runs/import',json=credentials).status_code==400
        assert not (tmp_path/'invalid'/f'{run}.db').exists()


def test_websocket_live_updates_and_cursor_reconnect(world_client):
    client,app=world_client;run=create(client,'creative')
    with client.websocket_connect(f'/ws/{run}') as ws:
        initial=ws.receive_json()
        assert initial['type']=='snapshot' and initial['event_cursor']==-1
        assert initial['events']==[]
        result=client.post(f'/runs/{run}/interventions',json={'expected_state_version':0,'kind':'money','human_id':'human-001','arguments':{'value':2222}})
        assert result.status_code==200
        update=ws.receive_json()
        assert update['type']=='update'
        assert update['event_cursor']==0 and len(update['events'])==1
        assert update['state']['humans']['human-001']['money']==2222
        assert update['state']['state_version']==1
        ws.send_text('ping')
        assert ws.receive_json()['type']=='pong'
    with client.websocket_connect(f'/ws/{run}?after=-1') as ws:
        snapshot=ws.receive_json()
        assert snapshot['event_cursor']==0 and len(snapshot['events'])==1
    with client.websocket_connect(f'/ws/{run}?after=0') as ws:
        snapshot=ws.receive_json()
        assert snapshot['event_cursor']==0 and snapshot['events']==[]
    with client.websocket_connect(f'/ws/{run}?after=1') as ws:
        assert ws.receive_json()['type']=='error'
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as error:ws.receive_json()
        assert error.value.code==4009

def test_declared_initial_companions_no_earned_progress(world_client):
    client,app=world_client;run=create(client)
    current=snapshot(client,run)
    aspiring=[h for h in current['humans'].values() if h['role']=='aspiring_trainer']
    assert len(aspiring)==30 and all(h['badges']==[] for h in aspiring)
    owners=[h for h in aspiring if h['party']]
    assert len(owners)==15
    for human in owners:
        assert human['setup_companion']['earned'] is False
        mon=current['pokemon'][human['party'][0]]
        assert mon['owner_id']==human['human_id'] and mon['level']==5
        assert mon['origin']['kind']=='declared_initial_setup'
        assert mon['origin']['map_id']=='Route1'
        assert human['map_id']=='Route1'
    assert current['state_version']==0
    assert client.get(f'/runs/{run}/replay').json()['event_count']==0

def test_initial_placements_unique_on_foot_clear_of_source_objects(world_client):
    from living_kanto.simulation.field import WATER,actor_map
    client,app=world_client;run=create(client)
    current=snapshot(client,run);engine=app.state.get_runtime_controller(run).engine
    used=set()
    for human in current['humans'].values():
        key=(human['map_id'],human['x'],human['y'])
        assert key not in used;used.add(key)
        source=engine.maps[human['map_id']];position=(human['x'],human['y'])
        assert actor_map(source,human).is_walkable(*position)
        assert int(source.cells.get(position,{}).get('behavior',0)) not in WATER
        assert position not in {(obj['x'],obj['y']) for obj in source.events.get('object_events',[]) if 'x' in obj and 'y' in obj}

def test_own_canonical_facts_are_private_bounded_copies(tmp_path):
    from living_kanto.simulation.world import WorldEngine
    from living_kanto.store import RunStore
    engine=WorldEngine(ROOT/'content');store=RunStore(tmp_path/'facts.sqlite')
    try:
        engine.initialize(store,'private-facts',seed=4,mode='observer')
        current=store.load_run('private-facts')[1]
        a=current.humans['human-001'];b=current.humans['human-002']
        a['last_decision']={'action':'journey_to','arguments':{'map_id':'ViridianCity'},'explanation':'My canonical accepted route','observation_version':10,'provenance':{'model_id':'private-provider-reference'}}
        a['last_service']={'kind':'healing','request_id':'accepted-own-heal'}
        a['access']={'saffron_tea':True};a['field']={'cut':['own-tree-'+str(i) for i in range(100)]}
        b['last_decision']={'action':'remember','explanation':'OTHER-HUMAN-SECRET'}
        b['last_service']={'kind':'shop','request_id':'OTHER-SERVICE-SECRET'}
        b['access']={'secret_personal_permission':True}
        b.update(map_id=a['map_id'],x=a['x'],y=a['y'])
        observation=engine.observation_for(current,'human-001').to_dict()
        own=observation['self_state']
        assert own['last_decision']['explanation']=='My canonical accepted route'
        assert 'provenance' not in own['last_decision']
        assert own['last_service']['request_id']=='accepted-own-heal'
        assert own['access']=={'saffron_tea':True}
        assert len(own['field']['cut'])==32
        encoded=__import__('json').dumps(observation)
        assert 'OTHER-HUMAN-SECRET' not in encoded and 'OTHER-SERVICE-SECRET' not in encoded
        assert 'secret_personal_permission' not in encoded
        own['field']['cut'].append('mutated-caller')
        assert 'mutated-caller' not in a['field']['cut']
    finally:store.close()


def test_runtime_concurrency_local_settings_restart_and_export_exclusion(tmp_path):
    root=tmp_path/'runs'
    app=create_app(root,content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(app) as client:
        run=create(client)
        settings={'base_url':'http://127.0.0.1:18880/v1','model_id':'local-test-no-request','concurrency':32,'response_protocol':'numbered','max_tokens':384}
        configured=client.post(f'/runs/{run}/runtime',json=settings)
        assert configured.status_code==200 and configured.json()['concurrency']==32
        assert client.post(f'/runs/{run}/runtime',json={**settings,'concurrency':True}).status_code==422
        assert client.post(f'/runs/{run}/runtime',json={**settings,'concurrency':33}).status_code==422
        exported=client.get(f'/runs/{run}/export')
        assert '18880' not in exported.text and 'local-test-no-request' not in exported.text
    restarted=create_app(root,content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(restarted) as client:
        restored=client.get(f'/runs/{run}/runtime').json()
        assert restored['concurrency']==32 and restored['model']=='local-test-no-request'
        config=restarted.state.get_runtime_controller(run).provider.config
        assert config.response_protocol=='numbered' and config.max_tokens==384
