"""Prototype only: exact offered choices and unchanged private provenance."""
import copy,importlib.util,json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('decision_wire',Path(__file__).resolve().parents[2]/'tools/decision_wire.py');module=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=module;spec.loader.exec_module(module)
build=module.build_decision_wire;Error=module.DecisionWireError

def observation():
 return {'kind':'human_observation','schema_version':1,'run_id':'private-world','human_id':'human-001','state_version':7,'observation_version':7,'simulated_time':41,'memories':{'0':{'text':'My private memory: café 🌱','kind':'subjective'}},'party':[{'pokemon_id':'my-pokemon','hp':17,'moves':[{'move':'TACKLE','pp':4}]}],'visible_actors':[{'human_id':'human-002','location':[3,4]}],'self_state':{'goal':{'text':'My private goal'},'status':{'energy':80}},'arbitrary_future_fact':{'numbers':[0,False,None,1.25]},'legal_actions':[{'kind':'legal_action','action':'battle_turn','arguments':{'choices':[{'type':'move','slot':2,'target':1},{'type':'move','slot':3}]},'known_consequences':{'battle_version':4,'active_slot_options':[[{'slot':2}], [{'slot':3}]]}},{'kind':'legal_action','action':'talk_to','arguments':{'human_id':'human-002','text':'<message, <=200 chars>'},'known_consequences':{'duration_seconds':30}},{'kind':'legal_action','action':'remember','arguments':{'text':'<non-empty text, <=200 chars>'},'known_consequences':{'duration_seconds':1}},{'kind':'legal_action','action':'trade_offer','arguments':{'human_id':'human-002','pokemon_id':'my-pokemon','wanted_species':'PIDGEY'},'known_consequences':{'requires_acceptance':True}}]}

def response(option=1,text='',reason='I chose this offered intention.'):
 return {'option':option,'text':text,'decision_explanation':reason}

def test_lossless_private_facts_menu_and_original_provenance():
 obs=observation();prior=copy.deepcopy(obs);wire=build(obs);encoded=wire.serialize();payload=json.loads(encoded)
 reconstructed={**payload['facts'],**payload['boundary'],'legal_actions':[{**{k:v for k,v in item.items() if k!='option'},'kind':'legal_action'} for item in payload['options']]}
 assert reconstructed==prior and obs==prior and wire.original_observation==prior
 assert 'human-099' not in encoded and 'café 🌱' in encoded
 assert all('kind' not in item for item in payload['options'])
 assert len(encoded.encode())<len(json.dumps(obs,indent=2).encode())

def test_prefix_deterministic_per_actor_and_versions_last():
 obs=observation();wire=build(obs);later=copy.deepcopy(obs);later.update(state_version=8,observation_version=8,simulated_time=42)
 assert wire.stable_prefix==build(later).stable_prefix and wire.prefix_sha256==build(later).prefix_sha256
 assert wire.serialize().startswith(wire.stable_prefix) and wire.serialize().rfind('"boundary"')>wire.serialize().rfind('"options"')
 assert build(dict(reversed(list(obs.items())))).serialize()==wire.serialize()
 other=copy.deepcopy(obs);other['human_id']='human-002';assert build(other).prefix_sha256!=wire.prefix_sha256

@pytest.mark.parametrize('option',[1,4])
def test_exact_nontext_argument_mapping_and_deepcopy(option):
 obs=observation();wire=build(obs);choice=wire.decode(response(option))
 assert choice['action']==obs['legal_actions'][option-1]['action'] and choice['arguments']==obs['legal_actions'][option-1]['arguments']
 if option==1:choice['arguments']['choices'][0]['slot']=99
 else:choice['arguments']['human_id']='hidden-person'
 assert wire.decode(response(option))['arguments']==obs['legal_actions'][option-1]['arguments']

@pytest.mark.parametrize('option',[2,3])
def test_only_explicit_text_placeholder_is_substituted(option):
 obs=observation();wire=build(obs);choice=wire.decode(response(option,'A real private message 🌱'))
 expected=copy.deepcopy(obs['legal_actions'][option-1]['arguments']);expected['text']='A real private message 🌱'
 assert choice['arguments']==expected and wire.original_observation==obs

@pytest.mark.parametrize('bad',[response(0),response(5),response(True),response(1.0),response('1'),response(reason=''),response(reason='   '),response(reason='x'*2001),response(text='unused'),response(2,''),response(2,'  '),response(2,'x'*201),response(2,7),{**response(),'arguments':{'slot':4}},{**response(),'action':'invented_action'}])
def test_invalid_response_rejected_without_fallback(bad):
 with pytest.raises(Error):build(observation()).decode(bad)

def test_unknown_or_literal_text_is_not_a_placeholder():
 obs=observation();obs['legal_actions'][1]['arguments']['text']='<not-an-offered-text-placeholder>';wire=build(obs)
 assert wire.decode(response(2))['arguments']['text']=='<not-an-offered-text-placeholder>'
 with pytest.raises(Error):wire.decode(response(2,'replacement'))

def test_json_duplicate_keys_and_nonobject_rejected():
 wire=build(observation())
 with pytest.raises(Error):wire.decode('{"option":1,"option":2,"text":"","decision_explanation":"why"}')
 for raw in ['[]','not-json','null']:
  with pytest.raises(Error):wire.decode(raw)
 assert wire.decode(json.dumps(response()))==wire.decode(response())

def test_original_and_options_are_independent_of_mutation():
 obs=observation();wire=build(obs);obs['legal_actions'][0]['arguments']['choices'][0]['slot']=99
 external=wire.original_observation;external['memories']['0']['text']='changed';options=wire.options;options[0]['arguments']['choices'][0]['slot']=98
 assert wire.decode(response())['arguments']['choices'][0]['slot']==2
 assert wire.original_observation['memories']['0']['text']=='My private memory: café 🌱'

def test_schema_option_enum_bounds_and_text_reason_contract():
 wire=build(observation());schema=wire.response_schema
 assert schema['properties']['option']=={'type':'integer','enum':[1,2,3,4],'minimum':1,'maximum':4}
 assert schema['properties']['text']['maxLength']==200
 assert schema['properties']['decision_explanation']['minLength']==1 and schema['additionalProperties'] is False
 assert set(schema['required'])=={'option','text','decision_explanation'}

@pytest.mark.parametrize('obs',[{}, {'legal_actions':[]},{'legal_actions':[{'action':'x','arguments':{}}]}])
def test_missing_menu_or_consequences_rejected(obs):
 with pytest.raises(Error):build(obs)

def test_mixed_schema_branches_cover_all_options_with_exact_text_guards():
 schema=build(observation()).response_schema;branches=schema['anyOf']
 assert len(branches)==2
 nontext,textual=(branch['properties'] for branch in branches)
 assert nontext['option']['enum']==[1,4] and nontext['text']=={'const':''}
 assert textual['option']['enum']==[2,3] and textual['text']=={'minLength':1}
 assert sorted(nontext['option']['enum']+textual['option']['enum'])==schema['properties']['option']['enum']
 assert not set(nontext['option']['enum']) & set(textual['option']['enum'])
 assert set(schema['required'])=={'option','text','decision_explanation'} and schema['additionalProperties'] is False
 assert 'if' not in schema and 'then' not in schema

def test_all_nontext_schema_requires_empty_text():
 obs=observation();obs['legal_actions']=[obs['legal_actions'][0],obs['legal_actions'][3]];schema=build(obs).response_schema
 assert schema['properties']['text']['const']=='' and 'anyOf' not in schema
 assert schema['properties']['option']['enum']==[1,2]

def test_all_placeholder_schema_requires_nonempty_text():
 obs=observation();obs['legal_actions']=[obs['legal_actions'][1],obs['legal_actions'][2]];schema=build(obs).response_schema
 assert schema['properties']['text']['minLength']==1 and schema['properties']['text']['maxLength']==200
 assert 'const' not in schema['properties']['text'] and 'anyOf' not in schema
 assert schema['properties']['option']['enum']==[1,2]
