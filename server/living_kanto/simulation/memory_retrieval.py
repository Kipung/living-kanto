"""Deterministic private recall; raw episodic memories are never edited."""
import copy,json,math,re
from functools import lru_cache
STOP=set('i me my we you your the a an to of and is are was in on for it that this do have could please really now with be will'.split())
IMPORTANT=re.compile(r'\b(promise|promised|owe|owed|repay|deadline|agreed|lost|failed|injured|betray|trust|appointment)\b',re.I)
def terms(text):return set(re.findall(r'[a-z0-9]+',str(text).lower()))-STOP

def meaning_signature(text):
    words=set(re.findall(r"[a-z]+",str(text).lower()))
    return (bool(words&{'not','never','no','cannot','didn','hasn','haven','won','isn','wasn'}) or bool(re.search(r"n't\b",str(text).lower().replace('’',"'"))),
            '?' in text or bool(words&{'ask','asked','asking','request','requested','waiting'}),
            tuple(sorted(words&{'maybe','might','perhaps','think','believe','possibly','probably'})))

def build_index(h):
    return copy.deepcopy(_indexed(json.dumps(h.get('memories',{}),sort_keys=True))[0])

@lru_cache(maxsize=128)
def _indexed(serialized):
    records=[]
    for ordinal,(slot,memory) in enumerate(sorted(json.loads(serialized).items(),key=lambda p:(0,int(p[0])) if p[0].isdigit() else (1,p[0]))):
        m=copy.deepcopy(memory);text=str(m.get('text',''));tokens=terms(text)
        records.append({'source_id':str(slot),'ordinal':ordinal,'time':m.get('time'),
          'people':[m['other']] if m.get('other') else [],'topics':sorted(tokens),
          'protected':bool(IMPORTANT.search(text)) or m.get('source')=='declared_setup','memory':m})
    groups=[]
    for rec in records:
        match=None
        for group in reversed(groups):
            old=group[-1]
            if rec['protected'] or old['protected'] or rec['memory'].get('direction') != old['memory'].get('direction') or rec['memory'].get('source') != old['memory'].get('source') or rec['people']!=old['people'] or rec['memory'].get('kind')!=old['memory'].get('kind') or meaning_signature(rec['memory'].get('text',''))!=meaning_signature(old['memory'].get('text','')):continue
            x=set(rec['topics']);y=set(old['topics']);overlap=len(x&y)/max(1,len(x|y))
            if rec['memory'].get('text')==old['memory'].get('text') or (rec['people'] and len(x&y)>=4 and overlap>=0.7):match=group;break
        if match is None:groups.append([rec])
        else:match.append(rec)
    return records,groups

def retrieve(h,now,visible=(),max_items=16,max_bytes=7000):
    records,groups=_indexed(json.dumps(h.get('memories',{}),sort_keys=True))
    life=h.get('individual_life') or {}
    query=terms(' '.join([str(h.get('goal',{}).get('text','')),str(life.get('aspiration',{}).get('text','')),
       str((life.get('commitment') or {}).get('text','')),str(h.get('map_id',''))]))
    visible=set(visible);ranked=[]
    for group in groups:
        rec=group[-1];known_time=rec['time'];age=max(0,now-known_time) if isinstance(known_time,(float,int)) else None
        recency=math.exp(-age/7200) if age is not None else (rec['ordinal']+1)/max(1,len(records))
        relevance=len(query&set(rec['topics']))/max(1,len(query))
        relation=0
        for person in rec['people']:
            relationship=h.get('relationships',{}).get(person,{})
            if isinstance(relationship,dict):
                value=relationship.get('trust',relationship.get('affinity',0))
                if isinstance(value,(int,float)):relation=max(relation,abs(value))
        score=3*recency+4*relevance+4*rec['protected']+min(1,relation/10)+bool(visible&set(rec['people']))
        m=copy.deepcopy(rec['memory']);m['recall']={'source_memory_ids':[r['source_id'] for r in group[-4:]],'occurrences':len(group),'detail':'representative' if len(group)>1 else 'original','time_known':age is not None}
        if len(group)>1:m['recall']['note']='Similar recorded statements; repetition is not evidence of an answer, learning, or success.'
        ranked.append((score,rec['ordinal'],m))
    ranked.sort(key=lambda r:(r[0],r[1]),reverse=True)
    selected=[];used=0
    for score,ordinal,m in ranked:
        size=len(json.dumps(m,ensure_ascii=False).encode())
        if len(selected)<max_items and used+size<=max_bytes:selected.append(m);used+=size
    return tuple(selected),{'policy':'relevance-recency-consequences-v1','stored_memories':len(records),'indexed_groups':len(groups),'recalled_memories':len(selected),'recall_bytes':used,'full_history_preserved':True,'retrieval_is_not_evidence_of_progress':True,'notice':'This is selective recall, not a complete history. Omitted details are unknown; do not invent them or assume an unremembered event never happened.'}
