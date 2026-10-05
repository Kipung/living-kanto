from pathlib import Path
from fastapi.testclient import TestClient
from living_kanto.api.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_modes_preserve_creative_history_and_observer_permissions(tmp_path):
    app = create_app(tmp_path, content_root=ROOT / 'content', client_root=ROOT / 'client')
    with TestClient(app) as client:
        assert client.post('/worlds', json={'run_id':'mode-history'}).status_code == 201
        path='/runs/mode-history'
        assert client.post(path+'/mode',json={'mode':'creative','expected_state_version':0}).status_code == 200
        grant=client.post(path+'/interventions',json={'expected_state_version':1,'kind':'badges','human_id':'human-001','arguments':{'badges':['boulder']}})
        assert grant.status_code == 200,grant.text
        assert client.post(path+'/mode',json={'mode':'survival','expected_state_version':2}).status_code == 200
        assert client.post(path+'/player/create',json={'expected_state_version':3}).status_code == 200
        assert client.post(path+'/mode',json={'mode':'observer','expected_state_version':4}).status_code == 200
        state=client.get(path).json()['state']
        assert state['mode']=='observer'  # Genesis mode remains bound to metadata.
        assert state['world_facts']['interaction_mode']=='observer'
        assert state['world_facts']['creative_modified']
        assert state['humans']['human-001']['achievement_provenance']['boulder']['kind']=='creative'
        assert client.post(path+'/player',json={'expected_state_version':5,'action':'wait','arguments':{}}).status_code==403
        assert client.post(path+'/interventions',json={'expected_state_version':5,'kind':'money','human_id':'human-001','arguments':{'value':999}}).status_code==403
        assert client.post(path+'/mode',json={'mode':'survival','expected_state_version':0}).status_code==409
        replay=client.get(path+'/replay').json()
        assert replay['state']['state_hash']==state['state_hash']
        assert replay['state']['world_facts']['creative_modified']


def test_creative_source_items_normalize_and_retain_save_mode(tmp_path):
    app=create_app(tmp_path,content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(app) as client:
        client.post('/worlds',json={'run_id':'items','mode':'creative'})
        path='/runs/items'
        result=client.post(path+'/interventions',json={'expected_state_version':0,'kind':'item','human_id':'human-001','arguments':{'item':'HM03','quantity':1}})
        assert result.status_code==200,result.text
        result=client.post(path+'/interventions',json={'expected_state_version':1,'kind':'item','human_id':'human-001','arguments':{'item':'ITEM_ULTRA_BALL','quantity':5}})
        assert result.status_code==200,result.text
        client.post(path+'/mode',json={'mode':'survival','expected_state_version':2})
        state=client.get(path).json()['state']
        assert state['world_facts']['interaction_mode']=='survival'
        assert state['humans']['human-001']['inventory']['hm03']['quantity']==1
        assert state['humans']['human-001']['inventory']['ultra_ball']['quantity']==5
        assert next(r for r in client.get('/runs').json() if r['run_id']=='items')['mode']=='survival'
        assert client.get(path+'/export').json()['metadata']['mode']=='creative'


def test_creative_removal_replaces_source_item_case_aliases(tmp_path):
    app=create_app(tmp_path,content_root=ROOT/'content',client_root=ROOT/'client')
    with TestClient(app) as client:
        client.post('/worlds',json={'run_id':'case-removal','mode':'creative'})
        controller=app.state.get_runtime_controller('case-removal')
        controller.engine.commit_changes(controller.store,'case-removal',[
            {'op':'set','path':'humans.human-001.inventory.HM03','value':{'item_id':'HM03','quantity':1}}
        ],kind='intervention.applied',actor='test',explanation='Explicit source-case item fixture',
        provenance={'kind':'creative'},expected_version=0)
        path='/runs/case-removal'
        result=client.post(path+'/interventions',json={'expected_state_version':1,'kind':'item','human_id':'human-001','arguments':{'item':'ITEM_HM03','quantity':0}})
        assert result.status_code==200,result.text
        state=client.get(path).json()['state']
        from living_kanto.simulation.scenarios import quantity
        assert quantity(state['humans']['human-001'],'HM03')==0
        assert state['world_facts']['creative_modified']
        assert client.get(path+'/replay').json()['state']['state_hash']==state['state_hash']
