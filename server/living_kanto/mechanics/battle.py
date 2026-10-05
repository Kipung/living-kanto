"""Serializable turn-by-turn Gen III battle service using a pinned simulator.

The serialized state is engine-private. Only observation(actor_id) is AI-facing.
Choices are collected outside the simulator until every required side has submitted.
"""
import copy
import base64
import zlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent

class BattleError(ValueError):
    pass

def _invoke(payload):
    node = shutil.which('node')
    if not node: raise BattleError('Node.js missing: install Node and run tools/setup_battles.sh')
    try:
        result = subprocess.run([node,str(HERE/'battle_adapter.cjs')],input=json.dumps(payload),text=True,capture_output=True,timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise BattleError('Battle calculation timed out; state remains unchanged') from exc
    try: output = json.loads(result.stdout)
    except ValueError as exc: raise BattleError('Battle simulator unavailable; run tools/setup_battles.sh') from exc
    if result.returncode or 'error' in output: raise BattleError(output.get('error','Battle simulator failed'))
    return output

class BattleSession:
    def __init__(self, record):
        self.record = copy.deepcopy(record)
        state = self.record.get('result',{}).get('state')
        if isinstance(state,dict) and state.get('encoding')=='zlib-base64-json':
            try:
                raw=zlib.decompress(base64.b64decode(state['data'],validate=True))
                self.record['result']['state']=json.loads(raw)
            except (ValueError,KeyError,zlib.error) as exc:
                raise BattleError('Corrupt compressed battle state') from exc

    @classmethod
    def start(cls, teams, seed, *, battle_id='battle', doubles=False, challenge=None):
        if len(seed)!=4 or any(not isinstance(x,int) or not 0<=x<65536 for x in seed): raise BattleError('seed requires four uint16 values')
        result = _invoke({'operation':'start','teams':teams,'seed':seed,'doubles':doubles,'link_like':(challenge or {}).get('kind')=='personal'})
        return cls({'schema_version':1,'battle_id':battle_id,'challenge':copy.deepcopy(challenge),'teams':copy.deepcopy(teams),'seed':seed,'doubles':doubles,'result':result,'pending':{},'history':[],'version':0})

    @property
    def ended(self): return self.record['result']['ended']

    @property
    def winner(self): return self.record['result']['winner']

    @property
    def version(self): return self.record['version']

    def to_dict(self):
        record = copy.deepcopy(self.record)
        record['history']=record.get('history',[])[-20:]
        record['result']['log']=record['result'].get('log',[])[-200:]
        for observation in record['result'].get('observations',{}).values():
            observation['log']=observation.get('log',[])[-200:]
        raw=json.dumps(record['result']['state'],separators=(',',':')).encode()
        record['result']['state']={'encoding':'zlib-base64-json','data':base64.b64encode(zlib.compress(raw,9)).decode('ascii')}
        return record

    def observation(self, actor_id):
        obs = self.record['result']['observations'].get(actor_id)
        if obs is None: raise BattleError('Actor is not a participant')
        result = copy.deepcopy(obs)
        result.update({'battle_id':self.record['battle_id'],'version':self.version,'ended':self.ended,'winner':self.winner,'submitted':actor_id in self.record['pending']})
        return result

    def submit(self, actor_id, action, *, expected_version):
        if self.ended: raise BattleError('Battle has ended')
        if expected_version!=self.version: raise BattleError('Stale battle observation')
        if actor_id not in self.record['result']['observations']: raise BattleError('Actor is not a participant')
        if actor_id in self.record['pending']: raise BattleError('Choice already submitted')
        def encode(choice):
            kind=choice.get('type')
            if kind in ('move','switch'):
                slot=choice.get('slot')
                if type(slot) is not int or not 1<=slot<=(4 if kind=='move' else 6): raise BattleError('Invalid move or party slot')
                text=f'{kind} {slot}'
                if 'target' in choice:
                    target=choice['target']
                    if kind!='move' or not self.record.get('doubles') or type(target) is not int or target not in (-2,-1,1,2): raise BattleError('Invalid doubles move target')
                    text+=f' {target}'
                return text
            if kind=='pass': return 'pass'
            raise BattleError('Unsupported battle action')
        if self.record.get('doubles'):
            if action.get('type')!='turn' or not isinstance(action.get('choices'),list) or len(action['choices'])!=2:
                raise BattleError('Doubles require exactly two ordered active-slot choices')
            choice=', '.join(encode(a) for a in action['choices'])
        else:
            choice=encode(action)
        _invoke({'operation':'validate','state':self.record['result']['state'],'actor_id':actor_id,'choice':choice})
        pending = {**self.record['pending'],actor_id:{'actor_id':actor_id,'choice':choice}}
        # A forced switch can leave the opposing side waiting; that side must pass.
        for other,obs in self.record['result']['observations'].items():
            if other not in pending and (obs['request'] or {}).get('wait'): pending[other]={'actor_id':other,'choice':'pass'}
        if len(pending)<2:
            self.record['pending']=pending
            return {'resolved':False,'version':self.version}
        result = _invoke({'operation':'resolve','state':self.record['result']['state'],'actions':list(pending.values())})
        self.record['history'].append({'version':self.version,'choices':copy.deepcopy(pending)})
        self.record['result']=result; self.record['pending']={}; self.record['version']+=1
        return {'resolved':True,'version':self.version,'ended':self.ended,'winner':self.winner,'pokemon':copy.deepcopy(result['pokemon'])}


    def consume_trainer_turn(self, actor_id, opponent_action, *, expected_version):
        """Engine-only failed capture/item turn: opposite Pokémon still acts.

        The outer engine applies the item effect and inventory mutation atomically
        with this result. This is deliberately absent from model legal choices.
        """
        if self.ended or expected_version!=self.version or self.record['pending']:
            raise BattleError('Item turn unavailable at this boundary')
        if self.record.get('doubles'): raise BattleError('Bag item turns currently require singles')
        actors=list(self.record['result']['observations'])
        if actor_id not in actors: raise BattleError('Actor is not a participant')
        other=next(a for a in actors if a!=actor_id)
        kind=opponent_action.get('type');slot=opponent_action.get('slot')
        if kind not in ('move','switch') or type(slot) is not int or not 1<=slot<=(4 if kind=='move' else 6):
            raise BattleError('Invalid opposite choice')
        actions=[{'actor_id':actor_id,'choice':'pass'},{'actor_id':other,'choice':f'{kind} {slot}'}]
        result=_invoke({'operation':'resolve','state':self.record['result']['state'],'actions':actions,'item_actor':actor_id})
        self.record['history'].append({'version':self.version,'engine_item_actor':actor_id,'choices':copy.deepcopy(actions)})
        self.record['result']=result;self.record['version']+=1
        return {'resolved':True,'version':self.version,'ended':self.ended,'winner':self.winner,'pokemon':copy.deepcopy(result['pokemon'])}


    def item_context(self, actor_id, pokemon_id):
        sides=self.record['result']['state']['sides']
        side=next((s for s in sides if s['name']==actor_id),None)
        mon=next((p for p in side['pokemon'] if p['set']['name']==pokemon_id),None) if side else None
        if not mon:raise BattleError('Item target is not owned')
        volatile=mon.get('volatiles',{})
        return {'active':mon.get('isActive',False),'boosts':copy.deepcopy(mon.get('boosts',{})),'confusion':'confusion' in volatile,'infatuation':'attract' in volatile,'focusenergy':'focusenergy' in volatile,'mist':'mist' in side.get('sideConditions',{})}

    def submit_item(self, actor_id, pokemon, item, effects, *, expected_version, acting_slot=1, partner_choice=None):
        """Engine-only accepted bag action; effect waits for opposing choice."""
        if self.ended or expected_version!=self.version or actor_id in self.record['pending']:
            raise BattleError('Item choice unavailable at this boundary')
        if (self.record.get('challenge') or {}).get('kind')=='personal':raise BattleError('Source link-like battles prohibit bag items')
        obs=self.observation(actor_id)
        if not (obs['request'] or {}).get('active'):raise BattleError('Item use requires normal turn')
        if pokemon['owner_id']!=actor_id:raise BattleError('Item target ownership mismatch')
        if pokemon['pokemon_id'] not in [p['pokemon_id'] for team in self.record['teams'] if team['actor_id']==actor_id for p in team['party']]:raise BattleError('Item target is not in active battle party')
        choice='pass'
        if self.record.get('doubles'):
            if type(acting_slot) is not int or acting_slot not in (1,2) or not isinstance(partner_choice,dict):raise BattleError('Doubles item requires acting slot and partner choice')
            from .challenges import double_turn_choices
            options=double_turn_choices(self,actor_id)
            pair=next((row['choices'] for row in options if row['choices'][2-acting_slot]==partner_choice and row['choices'][acting_slot-1]['type']=='move'),None)
            if not pair:raise BattleError('Invalid doubles item partner choice')
            clone=BattleSession(self.to_dict());clone.record['pending']={}
            clone.submit(actor_id,{'type':'turn','choices':pair},expected_version=clone.version)
            choice=clone.record['pending'][actor_id]['choice']
        elif partner_choice is not None or acting_slot!=1:raise BattleError('Singles item has no partner choice')
        payload={'actor_id':actor_id,'choice':choice,'item':{'name':item,'pokemon':copy.deepcopy(pokemon),'effects':copy.deepcopy(effects),'acting_slot':acting_slot}}
        pending={**self.record['pending'],actor_id:payload}
        if len(pending)<2:
            self.record['pending']=pending
            return {'resolved':False,'version':self.version}
        result=_invoke({'operation':'resolve','state':self.record['result']['state'],'actions':list(pending.values())})
        self.record['history'].append({'version':self.version,'choices':copy.deepcopy(pending)})
        self.record['result']=result;self.record['pending']={};self.record['version']+=1
        return {'resolved':True,'version':self.version,'ended':self.ended,'winner':self.winner,'pokemon':copy.deepcopy(result['pokemon'])}


    def synchronize_individuals(self,pokemon):
        """Engine-only committed EXP level-up reconciliation between turns."""
        if self.record['pending']:raise BattleError('Cannot change stats across unresolved choices')
        if not pokemon:return
        self.record['result']=_invoke({'operation':'sync','state':self.record['result']['state'],'pokemon':pokemon})
