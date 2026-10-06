"""Private grounding and ablations; fixtures are explicitly test inputs."""
import copy
import pytest
from living_kanto.simulation.decision_awareness import observation_view, action_view, social_view
from living_kanto.runtime.behavior_evaluation import ablate, interval_report, CONDITIONS
from test_gameplay import game, state, locate, act


def message(text, direction, other, version, **extra):
    return dict(text=text, direction=direction, other=other, source='recorded_speech',
                source_state_version=version, speech_id=f'speech-{version}', **extra)


def test_social_evidence_preserves_claims_declines_and_unanswered_messages():
    h={'memories':{'0':message('Can you trade?', 'spoken', 'b', 1),
                   '1':message('I decline; I am champion.', 'heard', 'b', 2,
                               reply_to='speech-1', response_disposition='decline'),
                   '2':message('Will you help later?', 'heard', 'b', 3)},
       'relationships':{'b':{'familiarity':20,'trust':-2}}}
    original=copy.deepcopy(h);v=social_view(h)['known_people'][0]
    assert v['latest_linked_reply_disposition']=='decline'
    assert v['received_messages_without_linked_own_reply']==2
    assert v['own_relationship_record']=={'familiarity':20,'trust':-2}
    assert v['recent_received_statements'][0]['content_status']=='reported_speech'
    assert not v['recent_received_statements'][0]['intentions_and_feelings_verified']
    assert not v['semantic_answer_verified'] and h==original
    v['own_relationship_record']['trust']=999
    assert h==original


@pytest.mark.parametrize('task,expected', [
    ({'status':'planned'},'planned_not_executed'),
    ({'status':'executing','started_at':0},'accepted_operation_pending'),
    ({'status':'executing','execution_state':'blocked'},'blocked_execution'),
    ({'status':'paused','started_at':0},'paused_choice'),
    ({'status':'abandoned'},'abandoned_choice'),
    ({'status':'completed','result':{'kind':'battle_resolved','outcome':'lost'}},'engine_result_recorded')])
def test_expected_actual_comparison_does_not_invent_success(task,expected):
    task={**task,'expected_result':{'kind':'battle_resolution'},'provenance':{'secret':'endpoint'}}
    h={'individual_life':{'task':task}}
    original=copy.deepcopy(h);v=action_view(h)['step_comparison']
    assert v['evidence_status']==expected and not v['whole_goal_completion_verified']
    assert 'provenance' not in v and h==original


def test_social_view_is_bounded_and_visible_evidence_prioritized():
    h={'memories':{str(i):message('Known statement','heard',f'p{i}',i) for i in range(30)}}
    v=social_view(h,['p0'])['known_people']
    assert len(v)==4 and v[0]['human_id']=='p0'
    assert social_view({'relationships':{'unmet':{'trust':100}}})['known_people']==[]


def test_ablations_are_detached_keep_menu_and_require_true_archive():
    obs={'legal_actions':[{'action':'respond_to','arguments':{'text':'heard'}}],
         'memories':[{'text':'old selected memory','time':1}],
         'self_state':{'decision_awareness':observation_view({}), 'behavior_feedback':{'facts':1},
                       'continuity':{'task':'real task'},'conversation_context':{},'relationships':{},'memory_recall':{}}}
    original=copy.deepcopy(obs)
    for condition in CONDITIONS:
        v=ablate(obs,condition,own_archive={'0':{'text':'recent actual memory','time':20}})
        assert v['legal_actions']==obs['legal_actions'] and v['self_state']['continuity']==obs['self_state']['continuity']
        if condition=='without_action_awareness':
            assert 'behavior_feedback' not in v['self_state'] and 'action' not in v['self_state']['decision_awareness']
        if condition=='without_social_awareness':
            assert 'social' not in v['self_state']['decision_awareness'] and v['memories']==obs['memories']
        if condition=='recent_memory_only':assert v['memories'][0]['text']=='recent actual memory'
    assert obs==original
    with pytest.raises(ValueError):ablate(obs,'recent_memory_only')


def test_live_observation_uses_only_owners_delivered_records_and_keeps_replay(game):
    locate(game,'human-001','PalletTown',(10,10));locate(game,'human-002','PalletTown',(11,10))
    s=act(game,'human-001','talk_to',{'human_id':'human-002','text':'I say I own a legendary.'})
    before=copy.deepcopy(s.to_dict());e,store=game
    owner=e.observation_for(s,'human-002').self_state['decision_awareness']
    stranger=e.observation_for(s,'human-003').self_state['decision_awareness']
    assert owner['social']['known_people'][0]['recent_received_statements'][0]['text']=='I say I own a legendary.'
    assert 'legendary' not in str(stranger)
    assert s.to_dict()==before and store.replay('gameplay-test').state_hash==s.state_hash
    # Changing the speaker's private memories/goals must not change the listener view.
    s.humans['human-001']['goal']={'text':'unrevealed secret'}
    assert observation_view(s.humans['human-002'])==observation_view(before['humans']['human-002'])


def test_interval_counts_only_engine_steps_and_reports_coverage(game):
    a=state(game);b=copy.deepcopy(a);b.state_version+=1;b.simulated_time+=10
    b.humans['human-001']['individual_life']={'commitment':{'status':'completed'},
        'task':{'task_id':'test-step','status':'completed','completed_at':b.simulated_time,
                'result':{'kind':'arrived'}}}
    report=interval_report(a,b);row=next(r for r in report['people'] if r['human_id']=='human-001')
    assert row['completed_steps_retained']==1 and row['facts']['new_badges']==[]
    # Same-clock commits count, but an already-completed retained step does not.
    b.humans['human-001']['individual_life']['task']['completed_at']=a.simulated_time
    assert interval_report(a,b)['people'][0]['completed_steps_retained']==1
    a.humans['human-001']['individual_life']=copy.deepcopy(b.humans['human-001']['individual_life'])
    assert interval_report(a,b)['people'][0]['completed_steps_retained']==0
    a.humans['human-001'].pop('individual_life')
    b.humans['human-001']['individual_life']['task'].pop('result')
    assert interval_report(a,b)['people'][0]['completed_steps_retained']==0
    with pytest.raises(ValueError):interval_report(b,a)
