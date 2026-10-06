import copy
import pytest
from living_kanto.simulation.individual_life import life_action_changes,life_view,record_decision
from living_kanto.simulation.engine import EngineError
from living_kanto.contracts import LegalAction

def person():return {'goal':{'text':'support family'},'money':100,'badges':[],'pokedex':[],'map_id':'PalletTown'}
def update(h,action,text='Earn enough for supplies'):
 c=life_action_changes(h,'a',action,{'text':text},'I need supplies',10,{'kind':'model','model_id':'test'})
 h['individual_life']=c[0]['value'];return h

def test_persistent_commitment_and_real_progress():
 h=update(person(),'set_commitment');h['money']=150;h['badges']=['boulder'];v=life_view(h)
 assert v['commitment']['text']=='Earn enough for supplies'
 assert v['observed_since_commitment']['money_change']==50
 assert v['observed_since_commitment']['new_badges']==['boulder']
 with pytest.raises(EngineError):update(h,'set_commitment')
 update(h,'complete_commitment','I earned 50')
 assert h['money']==150 and h['individual_life']['commitment']['assessment_source']=='self_report'
 assert h['individual_life']['commitment_history'][-1]['status']=='completed'
 update(h,'set_commitment','Rest before travelling')
 assert len(h['individual_life']['commitment_history'])==1

def test_private_and_detached():
 a=update(person(),'set_aspiration','Become a reliable neighbour');b=person();v=life_view(a);v['aspiration']['text']='changed'
 assert life_view(a)['aspiration']['text']=='Become a reliable neighbour'
 assert life_view(b)['aspiration']['text']=='support family'

def test_bounded_history_and_repetition():
 h=person()
 for n in range(20):
  changes=[];record_decision(h,'a','talk_to',{'human_id':'b'},'Ask again',n,changes);h['individual_life']=changes[-1]['value']
 assert len(life_view(h)['recent_decisions'])==8
 assert life_view(h)['repetition_notice']

def test_no_false_completion_and_bad_types():
 with pytest.raises(EngineError):update(person(),'complete_commitment')
 for x in [None,1,'','x'*201]:
  with pytest.raises(EngineError):life_action_changes(person(),'a','set_commitment',{'text':x},'why',0,{})
 for action in ['set_aspiration','set_commitment','complete_commitment','abandon_commitment']:
  LegalAction.from_dict(LegalAction(action=action,arguments={'text':'<non-empty text, <=200 chars>'}).to_dict())


def test_rephrased_conversation_feedback_does_not_rewrite_choices_or_history():
 import copy
 h=person();h['individual_life']={'recent_decisions':[{'action':'talk_to','arguments':{'human_id':'bob','text':f'Different request {i}'},'reason':'Ask for advice','at':i} for i in range(6)]}
 original=copy.deepcopy(h);view=life_view(h)
 assert 'Rewording' in view['repetition_notice'] and h==original
 h['individual_life']['recent_decisions']=[{'action':'talk_to','arguments':{'human_id':str(i),'text':'Hello'},'reason':'Meet someone','at':i} for i in range(6)]
 assert not life_view(h)['repetition_notice']
