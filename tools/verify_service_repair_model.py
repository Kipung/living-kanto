#!/usr/bin/env python3
"""One actual local-model follow-on at an already queued service boundary.

Run only after the completed pre-repair soak and focused trial are closed.
This chooses an actor, never a response or cancellation action.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from living_kanto.runtime import LocalModelConfig,LocalModelProvider,RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
from soak_runtime import fingerprints


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--soak-report',required=True)
    parser.add_argument('--focused-report',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--human-id',default='human-069')
    args=parser.parse_args()
    soak=json.loads(Path(args.soak_report).read_text())
    focus=json.loads(Path(args.focused_report).read_text())
    if soak.get('run_id')!=args.run_id or not soak.get('complete') or not soak.get('replay_matches'):
        raise RuntimeError('The actual pre-repair soak must complete first')
    if focus.get('run_id')!=args.run_id or not focus.get('replay_matches'):
        raise RuntimeError('The actual focused follow-on must finish and replay first')
    if not Path(args.database).is_file():raise RuntimeError('An existing append-only save is required')
    engine=WorldEngine(ROOT/'content');store=RunStore(args.database)
    _,initial,_=store.load_run(args.run_id)
    human=initial.humans[args.human_id]
    if not human.get('service_request'):raise RuntimeError('Target no longer has a queued service request')
    if not any(a.action=='cancel_service' for a in engine.legal_actions(initial,args.human_id)):
        raise RuntimeError('The repaired legal cancellation boundary is unavailable')
    baseline=fingerprints();provider=LocalModelProvider(LocalModelConfig.from_env())
    if provider.model_id!=soak.get('model'):raise RuntimeError('Keep the same actual local model as the completed soak')
    controller=RuntimeController(engine,store,args.run_id,provider,concurrency=1)
    start=time.monotonic();receipt=None;failure=None;continuations=[]
    try:
        for _ in range(8):
            result=controller.step(args.human_id)
            if not result.get('accepted'):failure=result;break
            if result.get('engine_continuation'):continuations.append(result);continue
            event=store.iter_events(args.run_id)[-1]
            provenance=event.causation.get('provenance',{})
            if provenance.get('kind')!='model' or provenance.get('test_provider'):
                raise RuntimeError('Accepted choice did not come from the actual local model')
            receipt=event.to_dict();break
        if receipt is None and failure is None:failure={'reason':'No human decision within bounded completion drains'}
    except (Exception,KeyboardInterrupt) as exc:
        failure={'type':type(exc).__name__,'reason':str(exc)}
    finally:
        controller.close();final=store.load_run(args.run_id)[1];replay=store.replay(args.run_id)
        report={'kind':'actual-model-service-repair-follow-on','run_id':args.run_id,
            'human_id':args.human_id,'model':provider.model_id,'manual_decisions':0,
            'initial_state_version':initial.state_version,'final_state_version':final.state_version,
            'initial_human':human,'final_human':final.humans[args.human_id],
            'money_delta':final.humans[args.human_id]['money']-human['money'],
            'reserved_payment':human['service_request'].get('reserved_payment',0),
            'cancellation_refund_matches':bool(receipt and receipt.get('causation',{}).get('action')=='cancel_service' and not final.humans[args.human_id].get('service_request') and final.humans[args.human_id]['money']-human['money']==human['service_request'].get('reserved_payment',0)),
            'accepted_model_decision':receipt,'engine_continuations':continuations,
            'failure':failure,'elapsed_seconds':time.monotonic()-start,
            'replay_matches':final.state_hash==replay.state_hash,'final_state_hash':final.state_hash,
            'pre_repair_soak_source':soak.get('final_source_files_sha256',soak.get('source_files_sha256')),
            'repair_source_fingerprint':baseline,'source_changed_during_follow_on':fingerprints()!=baseline,
            'original_soak_predates_repair':True,'release_verified':False}
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(path)
        store.close()
    print(json.dumps({'output':str(path),'actual_model_choice':receipt is not None,'failure':failure,'money_delta':report['money_delta']}))


if __name__=='__main__':main()
