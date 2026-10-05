#!/usr/bin/env python3
"""Small, co-scheduled live-world capacity measurement; never a release certificate."""
import argparse,collections,hashlib,json,os,resource,statistics,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from living_kanto.runtime import RuntimeController,LocalModelProvider,LocalModelConfig
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore

def fingerprint():
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for base in ['server/living_kanto','content'] for p in sorted((ROOT/base).rglob('*')) if p.is_file() and p.suffix in {'.py','.cjs','.json'} and not any(x in p.parts for x in ['node_modules','__pycache__'])}
def percentile(values,p):
 return sorted(values)[min(len(values)-1,int((len(values)-1)*p))] if values else None
class MeasuredProvider:
 def __init__(self,provider):
  self.provider=provider;self.model_id=provider.model_id;self.protocol=provider.protocol;self.test_provider=False
  self.lock=threading.Lock();self.samples=[];self.inflight=0;self.max_inflight=0
 def complete(self,observation,correction=None):
  start=time.monotonic()
  with self.lock:self.inflight+=1;self.max_inflight=max(self.max_inflight,self.inflight);depth=self.inflight
  failed=False
  try:return self.provider.complete(observation,correction=correction)
  except Exception:failed=True;raise
  finally:
   with self.lock:self.inflight-=1;self.samples.append({'human_id':observation['human_id'],'seconds':time.monotonic()-start,'client_inflight_at_start':depth,'corrective_retry':correction is not None,'failed':failed})
MEMORY_COMMAND=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-i','/Users/kipung/.ssh/jetson_codex','jetson@100.67.203.65',"ssh -o BatchMode=yes -o ConnectTimeout=8 spark-master 'cat /proc/meminfo'"]
def host_memory():
 try:
  proc=subprocess.run(MEMORY_COMMAND,capture_output=True,text=True,timeout=20,check=True)
  values={line.split(':')[0]:int(line.split(':')[1].strip().split()[0])*1024 for line in proc.stdout.splitlines() if ':' in line and line.split(':')[0] in {'MemTotal','MemAvailable','MemFree','SwapTotal','SwapFree'}}
  if len(values)!=5:raise ValueError('missing host memory fields')
  return {'available':True,'bytes':values,'host_used_estimate_bytes':values['MemTotal']-values['MemAvailable'],'swap_used_bytes':values['SwapTotal']-values['SwapFree'],'scope':'Spark host-wide, includes model container and all concurrent workloads; not isolated model allocation'}
 except Exception as exc:return {'available':False,'reason':type(exc).__name__,'scope':'Remote host memory unavailable; no inferred memory values'}
def recommend_live_capacity(report):
 usable=[level for level in report['levels'] if level.get('complete') and level.get('replay_matches') and level.get('final_population')==100]
 if not usable or not report.get('source_unchanged'):return None
 best=max(level['accepted_decisions_per_wall_minute'] for level in usable)
 return min(level['concurrency'] for level in usable if level['accepted_decisions_per_wall_minute']>=best*.9)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--database-directory',required=True);p.add_argument('--accepted-per-level',type=int,default=8);p.add_argument('--seconds-per-level',type=float,default=300);p.add_argument('--memory-samples',action='store_true');p.add_argument('--cohort',choices=['all','ready-workers'],default='ready-workers');args=p.parse_args()
 directory=Path(args.database_directory);directory.mkdir(parents=True,exist_ok=True);output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
 hashes=fingerprint();report={'scope':'Small live-world capacity measurement with genuine unrestricted local-model choices; co-scheduled with final two-hour soak and legal progression trial. Not an uncontended baseline or broad release certification.','model':'qwen38','concurrency_levels':[1,2,4,8],'cohort':args.cohort,'target_accepted_per_level':args.accepted_per_level,'levels':[],'release_capacity_verified':False,'complete':False,'limitations':['Host-wide memory includes competing workloads; no isolated per-request/model allocation.','GPU unified memory unavailable (earlier NVIDIA unified-memory reporting N/A); CPU host RAM is reported separately.','Client request duration includes endpoint scheduling/inference/network. Server queue wait cannot be separated.','Small fresh-world samples do not establish full 100-human simulation capacity or championship capability.'],'source_fingerprint_sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),'source_file_count':len(hashes)}
 def save():output.write_text(json.dumps(report,indent=2)+'\n')
 save()
 for concurrency in [1,2,4,8]:
  rid=f'live-capacity-c{concurrency}';database=directory/(rid+'.sqlite3')
  if database.exists():raise RuntimeError('Fresh isolated database required; refusing existing save')
  engine=WorldEngine(ROOT/'content');store=RunStore(database);initial=engine.initialize(store,rid,20261005,'observer')
  provider=MeasuredProvider(LocalModelProvider(LocalModelConfig('http://127.0.0.1:18880/v1','qwen38',timeout_seconds=120)))
  actors=None
  if args.cohort=='ready-workers':
   actors=[hid for hid in sorted(initial.humans) if any(a.action=='work' for a in engine.legal_actions(initial,hid))]
   if len(actors)<8:raise RuntimeError('Insufficient existing ready-worker cohort; no seeded eligibility or forced choices')
  runtime=RuntimeController(engine,store,rid,provider,actor_ids=actors,concurrency=concurrency)
  level={'concurrency':concurrency,'run_id':rid,'initial_population':len(initial.humans),'scheduled_actor_ids':list(runtime.actor_ids),'cohort_scope':'Original workers with initially legal work are scheduled to exercise the supported disjoint-activity concurrency path; choices remain unrestricted. Other existing AI people remain in the world.' if actors else 'Default all-human cursor; generic actions remain sequential','initial_state_version':initial.state_version,'memory_samples':[],'step_samples':[],'failures':[],'complete':False,'interference':'Shared Qwen38 endpoint with final-world-soak and legal trial; other activity may vary by configuration.'};report['levels'].append(level)
  stop=threading.Event();start=time.monotonic()
  def sample_memory():
   while not stop.is_set():
    sample=host_memory();sample['elapsed_seconds']=time.monotonic()-start;level['memory_samples'].append(sample)
    if stop.wait(20):break
  sampler=threading.Thread(target=sample_memory,daemon=True) if args.memory_samples else None
  if sampler:sampler.start()
  try:
   while runtime.status()['accepted_decisions']<args.accepted_per_level and time.monotonic()-start<args.seconds_per_level:
    began=time.monotonic();result=runtime.step();level['step_samples'].append({'elapsed_seconds':time.monotonic()-start,'wall_seconds':time.monotonic()-began,**result});save()
    if not result.get('accepted'):level['failures'].append(result);break
    print(json.dumps({'concurrency':concurrency,'accepted':runtime.status()['accepted_decisions'],'discarded':runtime.status()['discarded_uncommitted_responses'],'elapsed_seconds':time.monotonic()-start}),flush=True)
  except Exception as exc:level['failures'].append({'type':type(exc).__name__,'message':str(exc)[:300]})
  finally:
   stop.set()
   if sampler:sampler.join(timeout=22)
   state=store.load_run(rid)[1];elapsed=time.monotonic()-start;status=runtime.status();latencies=[s['seconds'] for s in provider.samples]
   level.update(runtime=status,elapsed_seconds=elapsed,accepted_decisions=status['accepted_decisions'],discarded_uncommitted_responses=status['discarded_uncommitted_responses'],inference_requests=len(provider.samples),inference_samples=provider.samples,max_client_inflight=provider.max_inflight,simulated_seconds=state.simulated_time-initial.simulated_time,simulated_seconds_per_wall_minute=(state.simulated_time-initial.simulated_time)*60/elapsed,accepted_decisions_per_wall_minute=status['accepted_decisions']*60/elapsed,model_request_median_seconds=statistics.median(latencies) if latencies else None,model_request_p95_seconds=percentile(latencies,.95),final_population=len(state.humans),final_state_version=state.state_version,replay_matches=store.replay(rid).state_hash==state.state_hash,benchmark_process_max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,complete=status['accepted_decisions']>=args.accepted_per_level and not level['failures'])
   level['accepted_actions']=dict(collections.Counter(d['action'] for event in store.iter_events(rid) for d in (event.causation.get('decisions') or [event.causation]) if d.get('provenance',{}).get('kind')=='model'))
   runtime.close();store.close();save()
 final=fingerprint();report['source_unchanged']=hashes==final;report['changed_source_files']=[k for k in set(hashes)|set(final) if hashes.get(k)!=final.get(k)];report['complete']=all(l['complete'] for l in report['levels']) and report['source_unchanged'];report['recommended_concurrency_for_this_cohort']=recommend_live_capacity(report);report['recommendation_method']='Lowest measured configuration within10%of best accepted decisions per wall minute among completed replay-matching100-human levels; a descriptive small-sample heuristic, not statistical acceptance.';report['read_only_endpoint_capacity_reference']='capacity.json';report['model_runtime_settings_reference']='model-runtime-settings.json';report['gpu_memory_reference']='live-capacity-gpu-memory.json';save()
 print(json.dumps({'report':str(output),'complete':report['complete'],'source_unchanged':report['source_unchanged']}),flush=True)
if __name__=='__main__':main()
