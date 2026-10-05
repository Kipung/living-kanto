"""Player input uses the same persisted movement clock as autonomous people."""
from test_world_api import world_client,create,snapshot


def test_player_accepts_movement_without_advancing_shared_clock(world_client):
    client,app=world_client;run=create(client,'survival')
    assert client.post(f'/runs/{run}/player/create',json={'expected_state_version':0}).status_code==200
    controller=app.state.get_runtime_controller(run)
    controller.engine.activate_shared_clock(controller.store,run)
    before=snapshot(client,run)
    observation=client.get(f'/runs/{run}/observations/player').json()
    choice=next(action for action in observation['legal_actions'] if action['action']=='walk_to')
    request={'expected_state_version':before['state_version'],'action':choice['action'],'arguments':choice['arguments']}
    accepted=client.post(f'/runs/{run}/player',json=request)
    assert accepted.status_code==200,accepted.text
    pending=snapshot(client,run)
    assert pending['simulated_time']==before['simulated_time']
    assert pending['humans']['player']['movement_intent']
    assert [(pending['humans']['player'][k]) for k in ('map_id','x','y')]==[before['humans']['player'][k] for k in ('map_id','x','y')]
    assert client.post(f'/runs/{run}/player',json=request).status_code==409
    with controller.shared_lock:
        controller.engine.tick_shared_time(controller.store,run,before['simulated_time']+1)
    after=snapshot(client,run)
    assert after['simulated_time']==before['simulated_time']+1
    assert (after['humans']['player']['x'],after['humans']['player']['y'])!=(before['humans']['player']['x'],before['humans']['player']['y'])
    assert controller.store.replay(run).state_hash==after['state_hash']
