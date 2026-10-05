#!/usr/bin/env python3
"""Bounded actual-local-model continuation after a completed, frozen-source soak.

Schedules a declared zero-badge trainer and required human battle/service peers.
Every human action and explanation comes from the configured local model. No
manual goals, location changes, item gifts, scripted moves, or fabricated wins.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from living_kanto.runtime import LocalModelConfig,LocalModelProvider,RuntimeController
from living_kanto.simulation.world import WorldEngine
from living_kanto.store import RunStore
try:
    from .soak_runtime import fingerprints
except ImportError:
    from soak_runtime import fingerprints


def eligible_candidates(genesis,current):
    result=[]
    for hid,human in sorted(genesis.humans.items()):
        if human.get('role')!='aspiring_trainer' or human.get('badges') or not human.get('party'):continue
        mons=[genesis.pokemon[pid] for pid in human['party']]
        if not all(mon['level']==5 and mon.get('origin',{}).get('kind')=='declared_initial_setup' for mon in mons):continue
        if not current.humans[hid].get('badges'):result.append(hid)
    return result


def required_actor(engine,state,focal):
    """Select a ready participant, never select their action."""
    battle=engine.active_battle(state,focal)
    if battle:
        if engine.battle_actions(state,focal):return focal,'focal_battle_decision'
        opponent=battle['opponent']
        if not battle['wild'] and opponent in state.humans and engine.battle_actions(state,opponent):return opponent,'required_opponent_decision'
        return None,'unresolved_battle_boundary'
    if state.humans[focal].get('service_request'):
        mid=state.humans[focal]['service_request']['map_id']
        for hid,human in sorted(state.humans.items()):
            if human.get('map_id')==mid and human.get('role') in {'service_staff','shop_staff'} and any(a.action=='serve_customer' for a in engine.legal_actions(state,hid)):
                return hid,'local_service_staff_decision'
        # Controller may drain an already accepted daily activity boundary.
        return focal,'waiting_for_local_service'
    if state.humans[focal].get('activity'):return focal,'focal_deferred_activity_boundary'
    return focal,'focal_decision'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--soak-report',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--human-id');parser.add_argument('--decisions',type=int,choices=[30,50],default=50)
    parser.add_argument('--seconds',type=float,default=600)
    args=parser.parse_args()
    if not 0<args.seconds<=600:parser.error('Focused trial duration must be positive and at most600seconds')
    soak=json.loads(Path(args.soak_report).read_text())
    if soak.get('run_id')!=args.run_id or not soak.get('complete') or not soak.get('current_source_soak_verified'):
        parser.error('Run only after the matching completed, unchanged-source actual-model soak')
    initial_source=fingerprints()
    if initial_source!=soak.get('final_source_files_sha256'):
        parser.error('Current backend/content differs from the completed soak; do not mix source versions')
    if not Path(args.database).is_file():parser.error('Continue the existing final-world save; do not create a new database')
    store=RunStore(args.database);engine=WorldEngine(ROOT/'content')
    genesis=store.load_genesis(args.run_id);_,initial,_=store.load_run(args.run_id)
    events=store.iter_events(args.run_id)
    for event in events:
        if event.event_index<soak['state_version']:continue
        causes=event.causation.get('decisions',[event.causation])
        if any(cause.get('provenance',{}).get('kind') not in {'model','engine'} or cause.get('provenance',{}).get('test_provider') for cause in causes):
            parser.error('Post-soak history contains manual or scripted changes; preserve unmodified autonomy')
    candidates=eligible_candidates(genesis,initial)
    focal=args.human_id or (candidates[0] if candidates else None)
    if focal not in candidates:parser.error('Choose an originally declared level5, zero-badge aspiring trainer who still has no badges')
    provider=LocalModelProvider(LocalModelConfig.from_env())
    if provider.model_id!=soak.get('model'):parser.error('Keep the same local model as the completed soak')
    controller=RuntimeController(engine,store,args.run_id,provider,concurrency=1)
    start=time.monotonic();accepted=[];continuations=0;failure=None;histogram=Counter()
    report={'kind':'actual-local-model-focused-progression','autonomous_evidence':True,'run_id':args.run_id,
        'focal_human_id':focal,'initial_declaration':genesis.humans[focal],
        'declared_party':[genesis.pokemon[pid] for pid in genesis.humans[focal]['party']],
        'initial_state_hash':initial.state_hash,'initial_state_version':initial.state_version,
        'initial_badges':initial.humans[focal]['badges'],'model':provider.model_id,
        'requested_model_decisions':args.decisions,'requested_seconds':args.seconds,
        'manual_progress_changes':0,'scripted_human_decisions':0,'release_verified':False,
        'boundary_interpretation':'A deferred activity or unavailable service boundary can stop focused scheduling while other humans remain ready; this is not evidence that championship progression is mechanically impossible.',
        'scheduling_protocol':'One declared focal trainer and required human battle/service peers; hundred-human fairness is evaluated separately by the completed soak.'}
    try:
        while len(accepted)<args.decisions and time.monotonic()-start<args.seconds:
            state=store.load_run(args.run_id)[1];actor,boundary=required_actor(engine,state,focal)
            if actor is None:failure={'reason':boundary,'state_version':state.state_version};break
            before=state.state_version;result=controller.step(actor)
            if not result.get('accepted'):failure={'boundary':boundary,**result};break
            event=store.iter_events(args.run_id)[-1];cause=event.causation
            if result.get('engine_continuation'):
                continuations+=1;continue
            provenance=cause['provenance']
            if provenance.get('kind')!='model' or provenance.get('test_provider'):raise RuntimeError('Accepted human choice was not an actual-model decision')
            row={'actor':actor,'boundary':boundary,'event_id':event.event_id,'observed_state_version':before,
                 'action':cause['action'],'arguments':cause.get('action_arguments',{}),
                 'decision_explanation':cause['decision_explanation'],'provenance':provenance}
            accepted.append(row);histogram[(actor,cause['action'])]+=1
            print(json.dumps({'accepted_model_decisions':len(accepted),'actor':actor,'action':cause['action'],'elapsed_seconds':round(time.monotonic()-start,2)}),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        failure={'type':type(exc).__name__,'reason':str(exc)}
    finally:
        controller.close();final=store.load_run(args.run_id)[1];replay=store.replay(args.run_id)
        report.update(accepted_model_decisions=len(accepted),engine_continuations=continuations,
            elapsed_seconds=time.monotonic()-start,failure=failure,accepted_decisions=accepted,
            action_counts=[{'actor':actor,'action':action,'count':count} for (actor,action),count in sorted(histogram.items())],
            final_state_version=final.state_version,final_state_hash=final.state_hash,replay_matches=final.state_hash==replay.state_hash,
            final_human=final.humans[focal],final_party=[final.pokemon[pid] for pid in final.humans[focal]['party']],
            final_badges=final.humans[focal]['badges'],badges_earned_during_focus=sorted(set(final.humans[focal]['badges'])-set(initial.humans[focal]['badges'])),
            source_changed_during_trial=fingerprints()!=initial_source,
            bounded_outcome='paused_at_rejected_or_unresolved_boundary' if failure else 'earned_badge' if final.humans[focal]['badges'] else 'no_badge_within_bounded_actual_model_decisions',
            runtime=controller.status())
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(output);store.close()
    print(json.dumps({'output':str(args.output),'accepted_model_decisions':len(accepted),'failure':failure,'badges':report['final_badges']}),flush=True)


if __name__=='__main__':main()
