"""Normal Creative intervention uses the verified store and preserves Observer boundary."""
from test_world_api import world_client,create,snapshot


def test_source_update_obeys_creative_version_and_idempotency(world_client):
    client,app=world_client;run=create(client)
    before=snapshot(client,run)
    body={'kind':'source_fidelity_update','human_id':'human-001','author':'user','expected_state_version':before['state_version'],'arguments':{}}
    assert client.post(f'/runs/{run}/interventions',json=body).status_code==403
    mode=client.post(f'/runs/{run}/mode',json={'mode':'creative','expected_state_version':before['state_version']})
    assert mode.status_code==200
    assert client.post(f'/runs/{run}/interventions',json=body).status_code==409
    current=snapshot(client,run);body['expected_state_version']=current['state_version']
    result=client.post(f'/runs/{run}/interventions',json=body)
    assert result.status_code==200,result.text
    after=snapshot(client,run)
    assert after['pokemon']==current['pokemon'] and set(after['humans'])==set(current['humans'])
    assert after['state_version']==current['state_version']+1
    assert after['world_facts']['creative_modified']
    body['expected_state_version']=after['state_version']
    again=client.post(f'/runs/{run}/interventions',json=body)
    assert again.status_code==200 and again.json()['already_applied']
    assert snapshot(client,run)['state_version']==after['state_version']
    observed=client.post(f'/runs/{run}/mode',json={'mode':'observer','expected_state_version':after['state_version']})
    assert observed.status_code==200
    store=app.state.get_runtime_controller(run).store
    assert store.replay(run).state_hash==snapshot(client,run)['state_hash']


def test_source_update_rejects_bad_author_and_arguments(world_client):
    client,_=world_client;run=create(client)
    before=snapshot(client,run);mode=client.post(f'/runs/{run}/mode',json={'mode':'creative','expected_state_version':before['state_version']}).json()
    body={'kind':'source_fidelity_update','human_id':'human-001','author':'user','expected_state_version':mode['state_version'],'arguments':{'reset':True}}
    assert client.post(f'/runs/{run}/interventions',json=body).status_code==400
    body['arguments']={};body['author']='not-user'
    assert client.post(f'/runs/{run}/interventions',json=body).status_code==400
