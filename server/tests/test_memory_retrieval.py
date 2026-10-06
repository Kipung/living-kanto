import copy,json
import pytest
from living_kanto.simulation.memory_retrieval import retrieve,build_index
from living_kanto.runtime.context_budget import fit_messages,ContextBudgetError

def human():return {'goal':{'text':'complete field journal'},'map_id':'PalletTown','memories':{},'relationships':{},'individual_life':{'commitment':{'text':'meet Pia for sketching notes'}}}
def test_relevance_obligation_and_archive_preserved():
 h=human();h['memories']={'0':{'text':'I promised to repay Pia tomorrow','other':'pia','time':1},'1':{'text':'Pia explained sketching plants for my field journal','other':'pia','time':2}}
 for n in range(2,60):h['memories'][str(n)]={'text':f'I saw stone number {n}','time':n}
 before=copy.deepcopy(h);m,meta=retrieve(h,10000,['pia'],max_items=4)
 assert any('promised' in x['text'] for x in m)
 assert any('sketching' in x['text'] for x in m)
 assert h==before and meta['stored_memories']==60 and len(m)<=4

def test_repetitions_group_without_inventing_outcomes():
 h=human();h['memories']={str(n):{'text':'Pia could you show me the field sketching notes for my journal?','other':'pia','kind':'subjective','time':n} for n in range(30)}
 m,meta=retrieve(h,31);assert meta['indexed_groups']==1
 assert m[0]['recall']['occurrences']==30
 assert 'not evidence' in m[0]['recall']['note']
 assert 'could you' in m[0]['text']
 h['memories']['30']={'text':'Pia promised to bring field sketching notes for my journal','other':'pia','kind':'subjective','time':30}
 m,meta=retrieve(h,31);assert meta['indexed_groups']==2

def test_people_separate_unknown_time_explicit_and_bytes_bounded():
 h=human();h['memories']={'a':{'text':'Private detail A'},'b':{'text':'Private detail B'}}
 a,_=retrieve(h,100,max_bytes=350);assert sum(len(json.dumps(x,ensure_ascii=False).encode()) for x in a)<=350
 assert all(x['recall']['time_known'] is False for x in a)
 other=human();m,_=retrieve(other,100);assert not m

def test_token_budget_retains_choices_current_commitment_and_source():
 obs={'facts':{'memories':[{'text':'x'*100} for _ in range(20)],'self_state':{'individual_life':{'commitment':{'text':'keep promise'}}}},'options':[{'action':'wait','arguments':{}}]}
 messages=[{'role':'user','content':json.dumps(obs)}];before=copy.deepcopy(messages)
 count=lambda ms:sum(len(x['content']) for x in ms)
 fitted,meta=fit_messages(messages,count,1100,100,target=900)
 doc=json.loads(fitted[0]['content']);assert doc['options']==obs['options']
 assert doc['facts']['self_state']['individual_life']==obs['facts']['self_state']['individual_life']
 assert meta['input_tokens']+100+256<=1100
 assert messages==before and len(doc['facts']['memories'])<20

def test_core_overflow_fails_before_inference():
 with pytest.raises(ContextBudgetError,match='Current facts'):
  fit_messages([{'role':'user','content':json.dumps({'legal_actions':['x'*2000]})}],lambda m:len(m[0]['content']),1000,100)

def test_tokenizer_preflight_uses_actual_limit_and_no_secrets_in_errors(monkeypatch):
 from living_kanto.runtime.providers import LocalModelProvider,LocalModelConfig
 monkeypatch.setenv('LK_TOKENIZER_PREFLIGHT','1')
 p=LocalModelProvider(LocalModelConfig('http://127.0.0.1:1/v1','test'))
 calls=[]
 class Reply:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return json.dumps({'count':80,'max_model_len':8192}).encode()
 class Opener:
  def open(self,request,**kw):calls.append(request.full_url);return Reply()
 p._opener=Opener();messages=[{'role':'user','content':'Private fact'}]
 assert p._count_context(messages)==80 and p._server_context_limit==8192
 assert p._count_context(messages)==80 and len(calls)==1
 assert calls==['http://127.0.0.1:1/tokenize']

def test_cache_invalidates_changed_memory_content():
 h=human();h['memories']['0']={'text':'I promised to repay Pia'}
 a,_=retrieve(h,0);h['memories']['0']['text']='I saw a tree';b,_=retrieve(h,0)
 assert a[0]['text']!=b[0]['text']

def test_consolidation_preserves_negation_questions_and_uncertainty():
 h=human();phrases=['Pia gave me field sketching notes for my journal','Pia did not give me field sketching notes for my journal','Pia gave me field sketching notes for my journal?','I think Pia gave me field sketching notes for my journal']
 h['memories']={str(n):{'text':t,'other':'pia','kind':'subjective','time':n} for n,t in enumerate(phrases)}
 selected,meta=retrieve(h,5)
 assert meta['indexed_groups']==4 and {m['text'] for m in selected}==set(phrases)


def test_consolidation_keeps_heard_spoken_and_legacy_directions_separate():
 h=human();text='Pia gave me field sketching notes for my journal'
 h['memories']={str(n):{'text':text,'other':'pia','kind':'subjective','time':n,
     **({'direction':direction,'source':'recorded_speech'} if direction else {})}
     for n,direction in enumerate(['heard','spoken',None,'heard','spoken',None])}
 before=copy.deepcopy(h); selected,meta=retrieve(h,6)
 assert meta['indexed_groups']==3
 assert {m.get('direction') for m in selected}=={'heard','spoken',None}
 assert all(m['recall']['occurrences']==2 for m in selected)
 assert h==before


def test_current_facts_over_soft_target_fit_actual_safe_boundary():
 messages=[{'role':'user','content':json.dumps({'facts':{'memories':[{'text':'x'*1000}],'self_state':{'current_fact':'y'*900}},'options':[{'action':'wait'}]})}]
 before=copy.deepcopy(messages)
 count=lambda ms:sum(len(m['content']) for m in ms)
 fitted,meta=fit_messages(messages,count,1800,100,target=800)
 doc=json.loads(fitted[0]['content'])
 assert not doc['facts']['memories'] and doc['options']==json.loads(before[0]['content'])['options']
 assert doc['facts']['self_state']['current_fact']=='y'*900
 assert meta['preferred_target_exceeded'] and meta['input_tokens']+100+256<=1800
 assert messages==before

def test_core_still_fails_beyond_actual_safe_boundary_with_soft_target():
 with pytest.raises(ContextBudgetError,match='Current facts'):
  fit_messages([{'role':'user','content':json.dumps({'options':['x'*1500]})}],lambda m:len(m[0]['content']),1800,100,target=800)
