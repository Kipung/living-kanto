"""Own-state feedback, ambiguity boundaries and deterministic audit metadata."""
import copy
from types import SimpleNamespace
from living_kanto.contracts import LegalAction
from living_kanto.simulation.behavior_feedback import observation_view, metrics, accepted_effects, repetition_warnings
from living_kanto.simulation.individual_life import life_action_changes, record_decision


def person():
    return {'human_id':'a','money':100,'badges':[],'pokedex':[],'party':[],'box':[],
            'map_id':'PewterCity','x':3,'y':4,'goal':{'text':'keep a journal'},'field':{'visited_maps':['PewterCity']}}


def view(h, actions=(), facts=None):
    return observation_view(None,SimpleNamespace(humans={'a':h,'b':{'private_secret':'unrevealed'}},
        world_facts=facts or {}),'a',actions)


def test_reworded_talk_and_route_reversals_are_factual_warnings():
    recent=[{'action':'talk_to','arguments':{'human_id':'b','text':str(i)}} for i in range(4)]
    recent += [{'action':'walk_to','arguments':{'direction':d}} for d in ['west','east','west']]
    assert {r['kind'] for r in repetition_warnings(recent)} == {'repeated_conversation_target','direction_reversals'}
    recent=[{'action':'enter_map' if i%2==0 else 'journey_to','arguments':{'map_id':'Gym' if i%2==0 else 'Town'}} for i in range(6)]
    assert repetition_warnings(recent)[0]['kind']=='alternating_map_targets'
    assert not repetition_warnings([{'action':'talk_to','arguments':{'human_id':str(i)}} for i in range(8)])


def test_acceptance_records_pending_intent_not_invented_arrival_or_payment():
    h=person(); changes=[{'op':'set','path':'humans.a.movement_intent','value':{'destination':'Route1'}}]
    result=accepted_effects(h,'a',changes)
    assert result['movement']=='accepted_pending_engine_steps' and result['location_changed'] is False
    changes=[{'op':'set','path':'humans.a.activity','value':{'kind':'work'}}]
    result=accepted_effects(h,'a',changes)
    assert result['activity']=='started_not_completed' and result['money_change']==0
    changes=[{'op':'set','path':'humans.a.service_request','value':{'kind':'healing'}}]
    assert accepted_effects(h,'a',changes)['service']=='queued_not_completed'


def test_new_commitment_baseline_supports_real_ownership_and_visited_map_changes():
    h=person(); h['individual_life']=life_action_changes(h,'a','set_commitment',{'text':'Discover Pokemon'},'Explore',1,{'kind':'user'})[0]['value']
    h['party']=['caught-mon'];h['pokedex']=['PIDGEY'];h['field']['visited_maps'].append('Route1')
    result=view(h)['grounded_progress']['since_commitment']
    assert result['new_owned_pokemon']==['caught-mon'] and result['new_visited_maps']==['Route1']
    assert result['new_caught_species']==['PIDGEY']
    h['individual_life']['commitment']['baseline']={'money':100}
    assert view(h)['grounded_progress']['since_commitment']['new_owned_pokemon'] is None


def test_subjective_completion_remains_subjective_and_does_not_grant_rewards():
    h=person();h['individual_life']=life_action_changes(h,'a','set_commitment',{'text':'Journal'},'why',1,{})[0]['value']
    h['individual_life']=life_action_changes(h,'a','complete_commitment',{'text':'I finished all notes'},'done',2,{})[0]['value']
    before=copy.deepcopy(h);assess=view(h)['grounded_progress']['commitment_assessment']
    assert assess['assessment_source']=='self_report' and assess['verified_goal_completion'] is False
    assert h==before and h['money']==100 and not h['badges']


def test_only_legal_pathways_and_own_battle_results_no_private_leak():
    h=person();actions=[LegalAction(action='remember',arguments={'text':'Observed Pidgey'}),LegalAction(action='choose_starter',arguments={'species':'Bulbasaur'})]
    facts={'battles':{'own':{'battle_id':'battle-10-a','challenger':'a','opponent':'wild','ended':True,'outcome':'caught','last_catch':{'caught':True},'hidden_stats':'not disclosed'},
        'other':{'battle_id':'battle-11-b','challenger':'b','opponent':'c','outcome':'secret'}}}
    before=copy.deepcopy((h,facts));result=view(h,actions,facts)
    assert result['pathways']['get_pokemon'][0]['action']=='choose_starter'
    assert 'earn_money' not in result['pathways']
    assert len(result['grounded_progress']['recent_battle_results'])==1
    assert 'hidden_stats' not in str(result) and 'secret' not in str(result)
    result['grounded_progress']['current']['badges'].append('fake')
    assert (h,facts)==before


def test_feedback_recording_preserves_old_history_and_canonical_effects():
    h=person(); old={'action':'talk_to','arguments':{'human_id':'b'},'reason':'hello','at':0}
    h['individual_life']={'recent_decisions':[old]};changes=[{'op':'set','path':'humans.a.money','value':200}]
    record_decision(h,'a','work',{},'earn',3,changes)
    rows=changes[-1]['value']['recent_decisions']
    assert rows[0]==old and rows[1]['accepted_effects']['money_change']==100
    assert changes[0]=={'op':'set','path':'humans.a.money','value':200}
    assert h['money']==100


def test_conversation_delivery_not_invented_from_old_subjective_sent_memory():
    from living_kanto.simulation.conversation import conversation_view
    h=person();h['memories']={'0':{'kind':'subjective','text':'Can you give me a starter?','other':'oak'}}
    h['individual_life']={'recent_decisions':[{'action':'talk_to','arguments':{'human_id':'oak','text':'Can you give me a starter?'},'at':1}]}
    before=copy.deepcopy(h);result=conversation_view(h)
    assert result['recent_received']==[] and result['recent_sent'][0]['speech_recorded_after_message'] is None
    assert result['legacy_received_messages_reconstructed'] is False and h==before


def test_recorded_response_requires_later_boundary_same_person_not_answer_semantics():
    from living_kanto.simulation.conversation import conversation_view
    h=person();received={'kind':'heard_speech','direction':'heard','source':'recorded_speech',
        'text':'I won a badge','other':'bob','speaker_name':'Bob','source_state_version':10,'speech_id':'speech10'}
    h['memories']={'0':received}
    h['individual_life']={'recent_decisions':[
        {'action':'talk_to','arguments':{'human_id':'bob','text':'Earlier question'},'source_state_version':9},
        {'action':'talk_to','arguments':{'human_id':'bob','text':'Same boundary'},'source_state_version':10},
        {'action':'talk_to','arguments':{'human_id':'other','text':'Other person'},'source_state_version':11}]}
    result=conversation_view(h)
    assert result['recent_received'][0]['response_recorded_after_message'] is False
    assert result['recent_sent'][0]['speech_recorded_after_message'] is True
    h['individual_life']['recent_decisions'].append({'action':'talk_to','arguments':{'human_id':'bob','text':'Unrelated greeting'},'source_state_version':12})
    assert conversation_view(h)['recent_received'][0]['response_recorded_after_message'] is True
    assert h['badges']==[]  # Bob's claim grants nothing.


def test_conversation_bounded_private_detached_and_unknown_legacy_order():
    from living_kanto.simulation.conversation import conversation_view
    h=person();h['memories']={str(n):{'kind':'heard_speech','direction':'heard','source':'recorded_speech','other':'bob','text':str(n),'source_state_version':n} for n in range(20)}
    h['memories']['20']={'kind':'subjective','text':'old reply','other':'bob','direction':'spoken','source':'recorded_speech'}
    original=copy.deepcopy(h);result=conversation_view(h)
    assert len(result['recent_received'])==4
    assert result['recent_received'][-1]['text']=='19'
    assert result['recent_received'][-1]['response_recorded_after_message'] is None
    result['recent_received'][-1]['text']='changed'
    assert h==original


def test_memory_append_never_overwrites_sparse_numeric_or_named_slots():
    from living_kanto.simulation.conversation import next_memory_slot
    assert next_memory_slot({})=='0'
    assert next_memory_slot({'0':{},'2':{},'named':{}})=='3'
    assert next_memory_slot({'100':{},'2':{},'3':{}})=='101'
    assert next_memory_slot({'named':{}})=='0'
