"""Private, model-authored aspirations and commitments; no invented achievements."""
import copy

LIFE_ACTIONS={'set_aspiration','set_commitment','complete_commitment','abandon_commitment'}

def own_metrics(h):
    from .behavior_feedback import metrics
    return metrics(h)

def life_view(h):
    life=copy.deepcopy(h.get('individual_life') or {})
    life.setdefault('aspiration', {'text':h.get('goal',{}).get('text',''), 'source':'existing_goal'})
    life.setdefault('commitment',None)
    life.setdefault('recent_decisions',[])
    commitment=life.get('commitment')
    if commitment:
        baseline=commitment.get('baseline',{});now=own_metrics(h)
        life['observed_since_commitment']={'money_change':now['money']-baseline.get('money',now['money']),
          'new_badges':[x for x in now['badges'] if x not in baseline.get('badges',[])],
          'new_caught_species':[x for x in now['caught_species'] if x not in baseline.get('caught_species',[])],
          'starting_map':baseline.get('map_id'),'current_map':now['map_id']}
    recent=life['recent_decisions'][-6:]
    conversations=[x.get('arguments',{}).get('human_id') for x in recent if x.get('action')=='talk_to']
    repeated_conversation=any(conversations.count(target)>=4 for target in set(conversations))
    life['repetition_notice']=('Recent conversations repeatedly addressed the same person. Rewording a request is not a new result; compare their replies and consider another practical approach if this is not helping.'
        if repeated_conversation else 'Recent decisions repeatedly used the same action and arguments; consider whether they advanced your commitment.'
        if len(recent)>=4 and len({(x['action'],repr(x['arguments'])) for x in recent})<=2 else '')
    # Transport metadata is audit evidence, not autobiographical content.
    def private_content(value):
        if isinstance(value,dict):return {k:private_content(v) for k,v in value.items() if k!='provenance'}
        if isinstance(value,list):return [private_content(v) for v in value]
        return value
    return private_content(life)

def life_action_changes(h,hid,action,args,reason,simulated_time,provenance):
    from .engine import EngineError
    if set(args)!={'text'} or not isinstance(args['text'],str) or not args['text'].strip() or len(args['text'])>200:
        raise EngineError(action+" takes {'text': non-empty string, <=200 chars}")
    life=copy.deepcopy(h.get('individual_life') or {})
    life.setdefault('aspiration',{'text':h.get('goal',{}).get('text',''),'source':'existing_goal'})
    active=life.get('commitment')
    record={'text':args['text'].strip(),'reason':reason,'at':simulated_time,'provenance':copy.deepcopy(provenance)}
    if action=='set_aspiration':
        life['aspiration']={**record,'source':'model' if provenance.get('kind')=='model' else 'user'}
    elif action=='set_commitment':
        if active and active.get('status')=='active':raise EngineError('Reflect on the active commitment before replacing it')
        life['commitment']={**record,'status':'active','baseline':own_metrics(h)}
    else:
        if not active or active.get('status')!='active':raise EngineError('No active commitment to reflect on')
        # Completion is explicitly a person's assessment, not an engine reward.
        active.update(status='completed' if action=='complete_commitment' else 'abandoned',
                      reflection=record,assessment_source='self_report')
        life['commitment_history']=(life.get('commitment_history',[])+[copy.deepcopy(active)])[-8:]
    return [{'op':'set','path':f'humans.{hid}.individual_life','value':life}]

def record_decision(h,hid,action,args,reason,simulated_time,changes,*,source_state_version=None):
    life=copy.deepcopy(h.get('individual_life') or {})
    for c in changes:
        if c.get('path')==f'humans.{hid}.individual_life':life=copy.deepcopy(c['value'])
    life.setdefault('aspiration',{'text':h.get('goal',{}).get('text',''),'source':'existing_goal'})
    from .behavior_feedback import accepted_effects
    life['recent_decisions']=(life.get('recent_decisions',[])+[{'action':action,'arguments':copy.deepcopy(args),'reason':reason,'at':simulated_time,
        'accepted_effects':accepted_effects(h,hid,changes),
        **({'source_state_version':source_state_version} if type(source_state_version) is int else {})}])[-8:]
    from .task_continuity import record_choice
    record_choice(h,life,action,args,reason,simulated_time,source_state_version,changes,hid)
    changes[:]=[c for c in changes if c.get('path')!=f'humans.{hid}.individual_life']
    changes.append({'op':'set','path':f'humans.{hid}.individual_life','value':life})
