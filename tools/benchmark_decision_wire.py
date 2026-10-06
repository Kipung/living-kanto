#!/usr/bin/env python3
"""Bounded read-only local-model proposal pilot, never commits world actions.

Frozen private observations stay local. Valid means decoded against the exact
original offered menu, not accepted by a live engine or behaviorally evaluated.
"""
import argparse,json,math,statistics,sys,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from living_kanto.runtime.providers import LocalModelConfig,_NoRedirect
from decision_wire import build_decision_wire


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cases',required=True);p.add_argument('--base-url',required=True);p.add_argument('--model',required=True);p.add_argument('--output',required=True);p.add_argument('--requests',type=int,default=8);p.add_argument('--levels',type=int,nargs='+',default=[1,2,4,8]);a=p.parse_args()
 if a.requests<8 or any(n not in [1,2,4,8] for n in a.levels):p.error('At least8 requests/level and bounded1/2/4/8 concurrency required')
 cfg=LocalModelConfig(a.base_url,a.model,timeout_seconds=120,max_tokens=128).validate();cases=[]
 for file in sorted(Path(a.cases).glob('*.json')):
  obs=json.loads(file.read_text())
  if isinstance(obs,dict) and obs.get('legal_actions'):cases.append((file.stem,build_decision_wire(obs)))
 if not cases:p.error('No frozen private observation cases with legal options')
 output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
 report={'scope':'Read-only local model pilot; decoded exact offered menu, no live engine acceptance/quality evaluation, no world mutations','model':cfg.model,'protocol':'numbered_menu_conditional_text_v2','requests_per_level':a.requests,'case_count':len(cases),'battle_case_count':sum(bool(w.original_observation.get('revealed_battle_info')) for _,w in cases),'context_character_range':[min(len(w.serialize()) for _,w in cases),max(len(w.serialize()) for _,w in cases)],'max_output_tokens':128,'thinking':False,'levels':[],'release_capacity_verified':False}
 def save():output.write_text(json.dumps(report,indent=2)+'\n')
 instruction='You are this individual human in Living Kanto. Use only your private facts, memories, personality and goals to choose one useful offered option. Return exactly option (integer), text (string), decision_explanation (one short clause, at most80 characters). text must be empty unless the selected arguments.text explicitly offers a text placeholder; then write your own nonempty text of at most200 characters. All other action arguments are fixed. When a goal is already recorded, choose a useful legal step towards it; update the goal only when facts justify a genuine change, never merely to restate it. Prefer a useful existing journey over tile micromanagement when it serves your goal. Do not invent world facts. Return JSON only.'
 def request(i):
  name,wire=cases[i%len(cases)];began=time.monotonic();retries=0;correction=None;usage={}
  for attempt in range(2):
   messages=[{'role':'system','content':instruction},{'role':'user','content':wire.serialize()}]
   if correction:messages.append({'role':'user','content':'Your proposal was rejected: '+correction+'. Correct it using this same menu.'})
   schema=wire.response_schema;schema['properties']['decision_explanation']['maxLength']=80
   payload={'model':cfg.model,'messages':messages,'temperature':.7,'max_tokens':128,'stream':False,'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_schema','json_schema':{'name':'private_choice','schema':schema}}}
   req=urllib.request.Request(cfg.endpoint.rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    with opener.open(req,timeout=120) as response:
     raw=response.read(1048577)
    if len(raw)>1048576:raise ValueError('Response too large')
    result=json.loads(raw);usage=result.get('usage',{});choice=wire.decode(result['choices'][0]['message']['content'])
    return {'case':name,'valid_offered_proposal':True,'action':choice['action'],'seconds':time.monotonic()-began,'corrective_retries':retries,'output_characters':len(result['choices'][0]['message']['content']),'explanation_characters':len(choice['decision_explanation']),'usage':usage}
   except ValueError as e:
    correction=str(e);retries+=int(attempt==0)
   except Exception as e:return {'case':name,'valid_offered_proposal':False,'seconds':time.monotonic()-began,'corrective_retries':retries,'failure_type':type(e).__name__}
  return {'case':name,'valid_offered_proposal':False,'seconds':time.monotonic()-began,'corrective_retries':retries,'failure_type':'DecisionWireError','usage':usage}
 report['warmup']=[request(i) for i in range(len(cases))];save()
 if not all(r['valid_offered_proposal'] for r in report['warmup']):print('Warmup proposal failure; stopping without increasing load',flush=True);return
 for concurrency in a.levels:
  began=time.monotonic()
  with ThreadPoolExecutor(max_workers=concurrency) as pool:results=list(pool.map(request,range(a.requests)))
  duration=time.monotonic()-began;latencies=sorted(r['seconds'] for r in results);valid=sum(r['valid_offered_proposal'] for r in results)
  level={'concurrency':concurrency,'wall_seconds':duration,'valid_proposals':valid,'valid_proposals_per_minute':60*valid/duration,'median_seconds':statistics.median(latencies),'p95_seconds':latencies[math.ceil(len(latencies)*.95)-1],'corrective_retries':sum(r['corrective_retries'] for r in results),'samples':results};report['levels'].append(level);save();print(json.dumps({k:v for k,v in level.items() if k!='samples'}),flush=True)
  if valid!=a.requests:break

if __name__=='__main__':main()
