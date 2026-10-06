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
import itertools
import json
from typing import Any

TEXT_PLACEHOLDERS=frozenset({'<non-empty text, <=200 chars>','<message, <=200 chars>','<letter text: 1–200 characters>'})

def option_text_limit(option):
    limit=option.get('known_consequences',{}).get('max_name_characters',200)
    if type(limit) is not int or not 1<=limit<=200:raise DecisionWireError('Invalid offered text limit')
    return limit
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
        schema={'type':'object','properties':{'option':{'type':'integer','enum':list(range(1,len(self._offered)+1)),'minimum':1,'maximum':len(self._offered)},'text':{'type':'string','minLength':0,'maxLength':200},'decision_explanation':{'type':'string','minLength':1,'maxLength':2000}},'required':['option','text','decision_explanation'],'additionalProperties':False}
        text_options=[];nontext_options=[]
        for number,offered in enumerate(self._offered,1):
            text=offered['arguments'].get('text')
            (text_options if isinstance(text,str) and text in TEXT_PLACEHOLDERS else nontext_options).append(number)
        if not text_options:schema['properties']['text']['const']=''
        elif not nontext_options:schema['properties']['text']['minLength']=1
        else:
            # anyOf is supported by the pilot's constrained-generation grammar;
            # if/then is deliberately unnecessary. These branches cover the
            # complete menu without constraining which intention is chosen.
            schema['anyOf']=[{'properties':{'option':{'enum':nontext_options},'text':{'const':''}}},{'properties':{'option':{'enum':text_options},'text':{'minLength':1}}}]
        return schema

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
            if len(text)>option_text_limit(selected):raise DecisionWireError('Text exceeds this option’s character limit')
            arguments['text']=text
        elif text:raise DecisionWireError('This option does not offer a text placeholder')
        return {'action':selected['action'],'arguments':arguments,'decision_explanation':reason}

def build_decision_wire(observation, *, expand_battle_pairs=False):
    if not isinstance(observation,dict):raise DecisionWireError('Private observation must be a dictionary')
    offered=observation.get('legal_actions')
    if not isinstance(offered,list) or not offered:raise DecisionWireError('A non-empty offered legal-action menu is required')
    for action in offered:
        if not isinstance(action,dict) or not isinstance(action.get('action'),str) or not action['action'].strip() or not isinstance(action.get('arguments'),dict) or not isinstance(action.get('known_consequences'),dict):raise DecisionWireError('Each option must retain its complete offered action, arguments and consequences')
        if 'option' in action:raise DecisionWireError('An offered action cannot contain a reserved option field')
    original=copy.deepcopy(observation)
    try:_compact(original)
    except (TypeError,ValueError) as error:raise DecisionWireError('Observation facts must be finite JSON data') from error
    expanded=[]
    for action in offered:
        choices=action['known_consequences'].get('available_items')
        if action['action']=='give_held_item' and action['known_consequences'].get('validated_item_selection') and choices:
            if not isinstance(choices,list) or len(choices)>512 or any(not isinstance(item,str) for item in choices):
                raise DecisionWireError('Invalid offered held-item choices')
            for item in choices:
                option=copy.deepcopy(action);option['arguments']['item']=item
                option['known_consequences'].pop('available_items',None)
                expanded.append(option)
        else:expanded.append(copy.deepcopy(action))
    if expand_battle_pairs:
        base=expanded;expanded=[]
        for action in base:
            slots=action['known_consequences'].get('active_slot_options')
            if action['action']!='battle_turn' or slots is None:
                expanded.append(copy.deepcopy(action));continue
            if not isinstance(slots,list) or len(slots)!=2 or any(not isinstance(slot,list) or not slot for slot in slots):
                raise DecisionWireError('Battle turn requires two non-empty active-slot menus')
            if len(slots[0])*len(slots[1])>4096:
                raise DecisionWireError('Battle active-slot menu exceeds bounded pair limit')
            for pair in itertools.product(*slots):
                if any(not isinstance(choice,dict) or choice.get('type') not in {'move','switch','pass'} for choice in pair):
                    raise DecisionWireError('Battle active-slot menu contains unsupported choices')
                if pair[0]['type']==pair[1]['type']=='switch' and pair[0].get('slot')==pair[1].get('slot'):continue
                item=copy.deepcopy(action)
                item['arguments']={'choices':copy.deepcopy(list(pair))}
                expanded.append(item)
        if not expanded:raise DecisionWireError('Battle active-slot menu has no valid pairs')
    return DecisionWire(original,tuple(expanded))
