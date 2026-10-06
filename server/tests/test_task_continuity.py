"""Declared user/test choices verify factual task lifecycle, never runtime scripts."""
import copy
import pytest
from test_gameplay import game, state, locate, scenario, act
from test_shared_clock_engine import activate, choose
from living_kanto.simulation.engine import EngineError, StaleActionError
from living_kanto.simulation.task_continuity import view
from living_kanto.simulation.behavior_feedback import repetition_warnings


def plan(game, hid, kind):
    e,_=game
    offered=next(a for a in e.legal_actions(state(game),hid) if a.action=='plan_next_step' and a.arguments['action']==kind)
    args={**offered.arguments,'text':'A concrete next step toward my own purpose'}
    return args


def test_planning_is_not_execution_and_private_replays(game):
    locate(game,'human-001','PalletTown_ProfessorOaksLab',(5,5));activate(game)
    before=state(game);args=plan(game,'human-001','choose_starter')
    after=choose(game,'human-001','plan_next_step',args)
    task=after.humans['human-001']['individual_life']['task']
    assert task['status']=='planned' and after.humans['human-001']['party']==before.humans['human-001']['party']
    private=game[0].observation_for(after,'human-001').self_state['continuity']
    assert 'provenance' not in private['task']
    other=game[0].observation_for(after,'human-002').self_state['continuity']
    assert other['task'] is None
    game[0].tick_shared_time(game[1],'gameplay-test',after.simulated_time+1)
    after=choose(game,'human-001',args['action'],args['arguments'])
    task=after.humans['human-001']['individual_life']['task']
    assert task['status']=='completed' and task['result']['pokemon_ids']==after.humans['human-001']['party']
    assert after.humans['human-001']['badges']==before.humans['human-001']['badges']
    assert game[1].replay('gameplay-test').to_dict()==after.to_dict()


def test_deferred_movement_completion_and_cancel_receipts(game):
    locate(game,'human-001','PalletTown',(10,10));activate(game)
    args=plan(game,'human-001','travel_to');s=choose(game,'human-001','plan_next_step',args)
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,'human-001','travel_to',args['arguments']);assert s.humans['human-001']['individual_life']['task']['status']=='executing'
    intent=s.humans['human-001']['movement_intent'];assert intent
    for _ in intent['steps']:
        game[0].tick_shared_time(game[1],'gameplay-test',state(game).simulated_time+1)
    s=state(game);assert s.humans['human-001']['individual_life']['task']['status']=='completed'
    # A second task's cancelled journey cannot inherit the old completion.
    args=plan(game,'human-001','travel_to');s=choose(game,'human-001','plan_next_step',args)
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,'human-001',args['action'],args['arguments'])
    s=choose(game,'human-001','cancel_movement',{})
    c=game[0].observation_for(s,'human-001').self_state['continuity']
    assert c['task']['status']=='executing' and c['task']['execution_state']=='blocked' and any(x['kind']=='no_running_operation' for x in c['blockers'])
    assert c['task']['last_transition']['action']=='cancel_movement'


def test_task_pause_reason_resume_and_abandon_preserve_commitment(game):
    activate(game);args=plan(game,'human-001','travel_to');s=choose(game,'human-001','plan_next_step',args)
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,'human-001','pause_task',{'text':'Need to rest first'})
    assert s.humans['human-001']['individual_life']['task']['status']=='paused'
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,'human-001','resume_task',{'text':'Ready to continue'})
    assert s.humans['human-001']['individual_life']['task']['status']=='planned'
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,'human-001','abandon_task',{'text':'This destination no longer fits'})
    task=s.humans['human-001']['individual_life']['task'];assert task['status']=='abandoned' and task['execution_state']=='abandoned'
    assert task['last_transition']['reason']=='This destination no longer fits'
    assert game[1].replay('gameplay-test').state_hash==s.state_hash


def test_task_rejects_invented_actions_and_stale_plans(game):
    activate(game);args=plan(game,'human-001','travel_to');s=state(game);_,token=game[0].capture_decision_boundary(s,'human-001')
    with pytest.raises(EngineError): choose(game,'human-001','plan_next_step',{**args,'action':'award_badge'})
    choose(game,'human-001','plan_next_step',args)
    with pytest.raises(StaleActionError):choose(game,'human-001','plan_next_step',args,token=token,version=s.state_version)


def test_work_task_waits_for_exact_completed_activity(game):
    activate(game);hid='human-090';args=plan(game,hid,'work');s=choose(game,hid,'plan_next_step',args)
    game[0].tick_shared_time(game[1],'gameplay-test',s.simulated_time+1)
    s=choose(game,hid,'work',{});h=s.humans[hid];assert h['individual_life']['task']['status']=='executing'
    game[0].advance_activities(game[1],'gameplay-test',allow_future=True)
    task=state(game).humans[hid]['individual_life']['task'];assert task['status']=='completed' and task['result']['kind']=='activity_completed'


def test_bookkeeping_semantic_variation_and_blocked_duty_are_detached():
    rows=[{'action':'remember','arguments':{'text':f'Different wording {i}'}} for i in range(8)]
    assert repetition_warnings(rows)[0]['kind']=='repeated_bookkeeping'
    h={'individual_life':{'task':{'status':'planned','action':'journey_to','arguments':{'map_id':'PalletTown'}}}}
    original=copy.deepcopy(h);v=view(h,[],{'on_duty':True,'at_workplace':True,'responsibility':'Remain at shop'})
    assert {b['kind'] for b in v['blockers']}=={'workplace_duty','next_step_unavailable'}
    assert h==original


def test_explicit_reply_delivered_privately_and_no_false_answer_claim(game):
    e,store=game;locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    s=act(game,'human-001','talk_to',{'human_id':'human-002','text':'Where is the Center?'})
    option=next(a for a in e.legal_actions(s,'human-002') if a.action=='respond_to' and a.arguments['disposition']=='decline')
    args={**option.arguments,'text':'I do not know; I need to go to work.'}
    s=act(game,'human-002','respond_to',args)
    context=e.observation_for(s,'human-002').self_state['conversation_context']
    assert context['recent_received'][-1]['explicit_reply_recorded']
    assert context['recent_received'][-1]['reply_dispositions']==['decline']
    heard=e.observation_for(s,'human-001').self_state['conversation_context']['recent_received'][-1]
    assert heard['reply_to']==args['speech_id'] and heard['response_disposition']=='decline' and heard['semantic_answer_verified'] is False
    assert not any(a.action=='respond_to' and a.arguments['speech_id']==args['speech_id'] for a in e.legal_actions(s,'human-002'))
    assert store.replay('gameplay-test').state_hash==s.state_hash
    with pytest.raises(EngineError):act(game,'human-002','respond_to',{**args,'speech_id':'invented'})


def test_party_storage_and_empty_healing_constraints_are_grounded():
    from living_kanto.contracts import LegalAction
    from living_kanto.simulation.task_continuity import result_for
    h={'party':[],'service_request':{'kind':'healing'}}
    before=copy.deepcopy(h)
    assert result_for(h,LegalAction(action='store_withdraw',arguments={'pokemon_id':'owned'}))=={'kind':'party_acquisition'}
    assert result_for(h,LegalAction(action='heal_party',arguments={})) is None
    assert view(h,[],{})['blockers'][0]['kind']=='healing_without_party'
    assert h==before


def test_old_and_cancelled_service_receipts_cannot_complete_new_task():
    from types import SimpleNamespace
    from living_kanto.simulation.task_continuity import outcome
    task={'started_at':10,'expected_result':{'kind':'service','role':'customer'},'request_id':'new'}
    assert outcome(SimpleNamespace(),{'last_service':{'request_id':'old','completed_at':11}},task) is None
    assert outcome(SimpleNamespace(),{'last_service':{'request_id':'new','completed_at':11,'outcome':'cancelled'}},task) is None
    assert outcome(SimpleNamespace(),{'last_service':{'request_id':'new','completed_at':11}},task)['request_id']=='new'


def test_unrelated_remote_walking_does_not_discard_a_still_offered_step(game):
    e,store=game;locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','Route1',e.maps['Route1'].first_open_cell((10,10)));activate(game)
    args=plan(game,'human-001','journey_to');s=state(game);obs,token=e.capture_decision_boundary(s,'human-001')
    step=next(a for a in e.legal_actions(s,'human-002') if a.action=='walk_to')
    choose(game,'human-002',step.action,step.arguments)
    e.tick_shared_time(store,'gameplay-test',s.simulated_time+1)
    assert token['movement_occupancy']!=e._movement_occupancy(state(game))
    after=choose(game,'human-001','plan_next_step',args,token=token,version=obs.state_version)
    assert after.humans['human-001']['individual_life']['task']['action']=='journey_to'
