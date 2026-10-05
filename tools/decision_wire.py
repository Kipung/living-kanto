"""Read-only numbered decision-wire prototype; no provider or world writes.

wire = build_decision_wire(private_observation_dict)
wire.serialize() supplies every original observation fact and complete offered
option. wire.response_schema constrains {option, text, decision_explanation}.
wire.decode(response_dict_or_json) returns an exact canonical action proposal.
wire.original_observation remains an independent copy for original provenance.
Options are one-based. Only the two existing explicit text placeholders can be
substituted. Engine validation is still required after decoding a real response.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass,field
import hashlib
import json
from typing import Any

TEXT_PLACEHOLDERS=frozenset({'<non-empty text, <=200 chars>','<message, <=200 chars>'})
BOUNDARY_KEYS=frozenset({'state_version','observation_version','simulated_time','tick'})

class DecisionWireError(ValueError):pass

def _compact(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))

def _strict_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise DecisionWireError('Duplicate response key')
        result[key]=value
    return result

@dataclass(frozen=True)
class DecisionWire:
    _original:dict[str,Any]=field(repr=False)
    _offered:tuple[dict[str,Any],...]=field(repr=False)

    @property
    def original_observation(self):return copy.deepcopy(self._original)

    @property
    def options(self):
        result=[]
        for number,offered in enumerate(self._offered,1):
            item=copy.deepcopy(offered)
            if item.get('kind')=='legal_action':item.pop('kind')
            result.append({'option':number,**item})
        return result

    @property
    def stable_prefix(self):
        facts={key:value for key,value in self._original.items() if key!='legal_actions' and key not in BOUNDARY_KEYS}
        return '{"facts":'+_compact(facts)+','

    @property
    def prefix_sha256(self):return hashlib.sha256(self.stable_prefix.encode('utf-8')).hexdigest()

    def serialize(self):
        # Version/clock boundary comes last. Facts retain all private memories,
        # identities, locations, inventories and arbitrary future schema fields.
        boundary={key:self._original[key] for key in BOUNDARY_KEYS if key in self._original}
        return self.stable_prefix+'"options":'+_compact(self.options)+',"boundary":'+_compact(boundary)+'}'

    @property
    def response_schema(self):
        return {'type':'object','properties':{'option':{'type':'integer','enum':list(range(1,len(self._offered)+1)),'minimum':1,'maximum':len(self._offered)},'text':{'type':'string','minLength':0,'maxLength':200},'decision_explanation':{'type':'string','minLength':1,'maxLength':2000}},'required':['option','text','decision_explanation'],'additionalProperties':False}

    def decode(self,response):
        if isinstance(response,str):
            try:response=json.loads(response,object_pairs_hook=_strict_object)
            except (json.JSONDecodeError,TypeError) as error:raise DecisionWireError('Response must be one JSON object') from error
        if not isinstance(response,dict) or set(response)!={'option','text','decision_explanation'}:raise DecisionWireError('Response must contain exactly option, text and decision_explanation')
        number=response['option'];text=response['text'];reason=response['decision_explanation']
        if type(number)is not int or not 1<=number<=len(self._offered):raise DecisionWireError('Option is outside the offered menu')
        if not isinstance(text,str) or len(text)>200:raise DecisionWireError('Text must be a string of at most 200 characters')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise DecisionWireError('A non-empty explanation of at most 2000 characters is required')
        selected=self._offered[number-1];arguments=copy.deepcopy(selected['arguments'])
        offered_text=arguments.get('text')
        if isinstance(offered_text,str) and offered_text in TEXT_PLACEHOLDERS:
            if not text.strip():raise DecisionWireError('The offered text placeholder requires non-empty text')
            arguments['text']=text
        elif text:raise DecisionWireError('This option does not offer a text placeholder')
        return {'action':selected['action'],'arguments':arguments,'decision_explanation':reason}

def build_decision_wire(observation):
    if not isinstance(observation,dict):raise DecisionWireError('Private observation must be a dictionary')
    offered=observation.get('legal_actions')
    if not isinstance(offered,list) or not offered:raise DecisionWireError('A non-empty offered legal-action menu is required')
    for action in offered:
        if not isinstance(action,dict) or not isinstance(action.get('action'),str) or not action['action'].strip() or not isinstance(action.get('arguments'),dict) or not isinstance(action.get('known_consequences'),dict):raise DecisionWireError('Each option must retain its complete offered action, arguments and consequences')
        if 'option' in action:raise DecisionWireError('An offered action cannot contain a reserved option field')
    original=copy.deepcopy(observation)
    try:_compact(original)
    except (TypeError,ValueError) as error:raise DecisionWireError('Observation facts must be finite JSON data') from error
    return DecisionWire(original,tuple(copy.deepcopy(offered)))
