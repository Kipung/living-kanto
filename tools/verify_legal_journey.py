#!/usr/bin/env python3
"""Bounded source-map trainer prefix using identified scripted TEST minds.

Every mutation is an engine-validated action. No Creative edits, badge grants,
spawned trial Pokemon, invented victories, or cloud models. This establishes
mechanical reachability only, never autonomous release evidence.
"""
import argparse,json,sys,hashlib,re,time
from datetime import datetime
from collections import deque
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from living_kanto.simulation.world import WorldEngine
from living_kanto.simulation.field import actor_map
from living_kanto.simulation.pathfinding import shortest_path,PathNotFound
from living_kanto.store import RunStore
from living_kanto.simulation.maps import resolve_transfer,MapLoadError
from living_kanto.simulation.access import transfer_gate,AccessDenied


def source_fingerprints():
    paths=list(Path("server/living_kanto").rglob("*.py"))+list(Path("content").rglob("*.json"))+list(Path("server").rglob("*.cjs"))
    return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths) if "node_modules" not in path.parts}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True);parser.add_argument('--report',required=True)
    parser.add_argument('--run-id',default='legal-prefix-test');parser.add_argument('--wild-battles',type=int,default=3)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--through',choices=['brock','misty','bill-cut','surge','mainland','league'],default='brock');parser.add_argument('--stage-wild-battles',type=int,default=75);parser.add_argument('--stage-target-level',type=int,default=22)
    parser.add_argument('--human-id',default='human-001');parser.add_argument('--league-wild-battles',type=int,default=500);parser.add_argument('--league-target-level',type=int,default=65)
    parser.add_argument('--starter',choices=['Squirtle','Bulbasaur','Charmander'],default='Squirtle');parser.add_argument('--target-level',type=int,default=0);parser.add_argument('--max-events',type=int,default=350);parser.add_argument('--seed',type=int,default=73)
    parser.add_argument('--preparation-until',help='UTC ISO deadline for TEST training; then attempt the actual next gym with earned team')
    parser.add_argument('--stop-after-erika',action='store_true')
    parser.add_argument('--export',help='Portable committed bundle written after final replay, excluding local inference settings')
    args=parser.parse_args();database=Path(args.database)
    preparation_deadline=datetime.fromisoformat(args.preparation_until.replace('Z','+00:00')).timestamp() if args.preparation_until else None
    if database.exists() and not args.resume:parser.error('Use a fresh test database or explicit --resume to append valid history')
    if args.resume and not database.exists():parser.error('Resume requires an existing test save')
    database.parent.mkdir(parents=True,exist_ok=True);engine=WorldEngine('content');store=RunStore(database)
    if not args.resume:engine.initialize(store,args.run_id,seed=args.seed,mode='observer')
    store.set_status(args.run_id,'running')
    fingerprint=source_fingerprints()
    prior=json.loads(Path(args.report).read_text()) if args.resume and Path(args.report).exists() else {}
    if prior:
        archive=Path(args.report).parent/'lineage-sessions';archive.mkdir(exist_ok=True)
        receipt=archive/(Path(args.report).stem+'-checkpoint-'+str(prior.get('event_count',0))+'.json')
        if not receipt.exists():receipt.write_text(json.dumps(prior,indent=2)+'\n')
    hid=args.human_id;stages=list(prior.get('stages',[]));failure=None;count=store.event_count(args.run_id);initial_count=count
    def current():return store.load_run(args.run_id)[1]
    def action(actor,kind,arguments=None):
        nonlocal count
        if count>=args.max_events:raise RuntimeError('Bounded test event limit reached')
        state=current();event,_=engine.build_action_event(store,args.run_id,actor,action=kind,arguments=arguments or {},observation_version=state.state_version,expected_state_version=state.state_version,decision_explanation='Identified scripted source-journey TEST mind; not autonomous evidence',decision_provenance={'kind':'model','model_id':'scripted-source-journey-test-only','test_provider':True})
        engine.commit(store,event);count+=1
    def checkpoint(label):
        snapshot=current();h=snapshot.humans[hid]
        receipt={'stage':label,'event_count':count,'state_hash':snapshot.state_hash,'badges':h['badges'],'map_id':h['map_id'],'party':[{'pokemon_id':p,'species':snapshot.pokemon[p]['species'],'level':snapshot.pokemon[p]['level']} for p in h['party']],'autonomous_evidence':False}
        path=Path(args.report).with_suffix('.checkpoints.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as out:out.write(json.dumps(receipt)+'\n')
    def navigate(goal,goal_point=None):
        for _ in range(500):
            if engine.active_battle(current(),hid):battle()
            for _ in range(20):
                if not current().humans[hid].get('safari',{}).get('encounter'):break
                action(hid,'safari_action',{'choice':'run'})
            state=current();human=state.humans[hid];mid=human['map_id']
            if mid==goal:
                if goal_point is None:return
                try:shortest_path(actor_map(engine.maps[mid],human),(human['x'],human['y']),goal_point)
                except PathNotFound:pass
                else:
                    if (human['x'],human['y'])!=goal_point:action(hid,'travel_to',{'x':goal_point[0],'y':goal_point[1]})
                    now=current().humans[hid]
                    if engine.active_battle(current(),hid) or now['map_id']!=goal or (now['x'],now['y'])!=goal_point:continue
                    return
            initial=(mid,human['x'],human['y']);previous={initial:None};queue=deque([initial]);found=None
            while queue and len(previous)<4000:
                node=queue.popleft();source,x,y=node
                if source==goal and goal_point is None:found=node;break
                projected={**human,'map_id':source,'x':x,'y':y};gm=actor_map(engine.maps[source],projected)
                # Position-aware source movement permits leaving/re-entering a
                # disconnected map (Route 2 through the Viridian Forest gates).
                reached={(x,y)};flood=deque([(x,y)])
                while flood:
                    point=flood.popleft()
                    for direction in ['north','west','east','south']:
                        destination=gm.step_destination(point,direction)
                        if destination is not None and destination not in reached:reached.add(destination);flood.append(destination)
                if source==goal and goal_point in reached:found=node;break
                for cell,target in sorted(gm.exits.items()):
                    if cell not in reached or target not in engine.maps:continue
                    try:
                        transfer_gate(projected,target)
                        destination=resolve_transfer(engine.maps,gm,*cell,target)
                    except (MapLoadError,AccessDenied):continue
                    if destination not in previous:previous[destination]=(node,cell,target);queue.append(destination)
            if found is None:raise RuntimeError(f'No source-position-aware on-foot map journey from {initial} to {goal}; current permissions cannot reach it')
            step=found
            while previous[step][0]!=initial:step=previous[step][0]
            _,cell,target=previous[step]
            if cell!=(human['x'],human['y']):action(hid,'travel_to',{'x':cell[0],'y':cell[1]})
            now=current().humans[hid]
            if engine.active_battle(current(),hid) or now['map_id']!=mid or (now['x'],now['y'])!=cell:continue
            action(hid,'enter_map',{'map_id':target})
        raise RuntimeError('Bounded source navigation limit reached')
    def healing(center='ViridianCity_PokemonCenter_1F'):
        navigate(center);action(hid,'heal_party')
        state=current();staff=next((person for person in state.humans.values() if person['role']=='service_staff' and person['map_id']==state.humans[hid]['map_id'] and engine.service_actions(state,person['human_id'])),None)
        if staff is None:raise RuntimeError('No available human service staff at healing queue')
        serve=engine.service_actions(state,staff['human_id'])[0];action(staff['human_id'],serve.action,serve.arguments)
        # Source medical purchases use actual local shop staff and finite money.
        town=center.split('_')[0];mart=town+'_Mart'
        if mart not in engine.maps and engine.shop_prices(center):mart=center
        if mart in engine.maps and engine.shop_prices(mart):
            prices=engine.shop_prices(mart);wanted=[('antidote',2),('paralyze_heal',1),('potion' if 'potion' in prices else 'super_potion',3)]
            shopping=[]
            for item,quantity in wanted:
                if item not in prices:continue
                existing=current().humans[hid]['inventory'].get(item,{}).get('quantity',0)
                needed=max(0,quantity-existing)
                if needed:shopping.append((item,needed))
            if shopping and current().humans[hid]['money']>500:
                navigate(mart);shopper=next((h for h in current().humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and h['map_id']==mart),None)
                if shopper:
                    for item,needed in shopping:
                        quantity=min(needed,max(0,(current().humans[hid]['money']-500)//prices[item]))
                        for _ in range(quantity):
                            action(hid,'shop_buy',{'item':item,'quantity':1});offer=engine.service_actions(current(),shopper['human_id'])[0];action(shopper['human_id'],offer.action,offer.arguments)
    def maintain_party():
        for pid in list(current().humans[hid]['party']):
            for _ in range(5):
                mon=current().pokemon[pid];status=mon.get('status');items=['revive'] if mon['hp']==0 else ['antidote','paralyze_heal','awakening','burn_heal','ice_heal','full_heal'] if status else ['super_potion','potion','hyper_potion','max_potion','full_restore'] if mon['hp']<mon['stats']['hp']*0.65 else []
                if not items:break
                options=engine.legal_actions(current(),hid)
                choice=next((option for item in items for option in options if option.action=='use_item' and option.arguments.get('pokemon_id')==pid and option.arguments.get('item')==item),None)
                if not choice:break
                action(hid,choice.action,choice.arguments)
    def lifecycle():
        for _ in range(25):
            state=current();choices=engine.legal_actions(state,hid)
            evolution=next((choice for choice in choices if choice.action=='evolve'),None)
            if evolution:action(hid,evolution.action,evolution.arguments);continue
            learning=[choice for choice in choices if choice.action=='learn_move']
            if not learning:return
            def move_power(name):
                move=catalog['moves'].get(normalize(name),{});return move.get('power',0)*move.get('accuracy',100)/100
            proposed=max(learning,key=lambda option:move_power(option.arguments['move']))
            mon=state.pokemon[proposed.arguments['pokemon_id']]
            if len(mon['moves'])<4:preferred=len(mon['moves'])+1
            else:
                replaceable=[(move_power(move['move']),i+1) for i,move in enumerate(mon['moves']) if move['move'] not in {'CUT','SURF','STRENGTH','FLASH','FLY','WATERFALL','ROCK_SMASH'}]
                if not replaceable:return
                weakest,preferred=min(replaceable)
                if move_power(proposed.arguments['move'])<=weakest:return
            choice=next(option for option in learning if option.arguments['pokemon_id']==proposed.arguments['pokemon_id'] and option.arguments['move']==proposed.arguments['move'] and option.arguments['slot']==preferred)
            action(hid,choice.action,choice.arguments)
        raise RuntimeError('Bounded move-learning/evolution limit reached')
    from living_kanto.mechanics.reference import data,normalize,REFERENCE
    catalog=data();effectiveness={(a,b):{'NOT_EFFECTIVE':0.5,'SUPER_EFFECTIVE':2,'NO_EFFECT':0}.get(mult,1) for a,b,mult in re.findall(r'TYPE_(\w+),\s*TYPE_(\w+),\s*TYPE_MUL_(\w+)',(REFERENCE/'src/battle_main.c').read_text())}
    training_target=None
    def battle():
        for _ in range(90):
            state=current();record=engine.active_battle(state,hid)
            if not record:
                lifecycle();maintain_party();return
            actors=[hid]+([] if record['wild'] else [record['opponent']])
            progressed=False
            for actor in actors:
                state=current();choices=engine.battle_actions(state,actor)
                if not choices:continue
                moves=[option for option in choices if option.action=='battle_move']
                choice=None
                if actor==hid and training_target and record['wild']:
                    session=__import__('living_kanto.mechanics',fromlist=['BattleSession']).BattleSession(record['session']);request=session.observation(hid)['request'] or {}
                    side=request.get('side',{}).get('pokemon',[])
                    own=next(s for s in session.record['result']['state']['sides'] if s['name']==hid)['pokemon']
                    active=next((i for i,p in enumerate(side) if p.get('active')),None)
                    target=next((i for i,p in enumerate(own) if p['set']['name']==training_target),None)
                    participated=training_target in record.get('participants',[])
                    if target is not None and target!=active and not participated:choice=next((o for o in choices if o.action=='battle_switch' and o.arguments['slot']==target+1),None)
                    elif target is not None and target==active and participated:
                        # Genuine switch training: expose the learner for an
                        # actual opponent turn, then let a healthy teammate finish.
                        alternatives=[o for o in choices if o.action=='battle_switch']
                        def level_of(option):
                            index=option.arguments['slot']-1
                            return state.pokemon.get(own[index]['set']['name'],{}).get('level',0) if index<len(own) else 0
                        if alternatives:choice=max(alternatives,key=level_of)
                if moves and choice is None:
                    session=__import__('living_kanto.mechanics',fromlist=['BattleSession']).BattleSession(record['session'])
                    revealed=session.observation(actor).get('opponent',{}).get('active',[])
                    foe_types=catalog['species'].get(normalize(revealed[0]['species']) if revealed else '',{}).get('types',[])
                    def strength(option):
                        move=catalog['moves'].get(normalize(option.known_consequences.get('move','')),{});score=move.get('power',0)*move.get('accuracy',100)/100
                        for kind in set(foe_types):score*=effectiveness.get((move.get('type'),kind),1)
                        return score
                    choice=max(moves,key=strength)
                    if actor==hid and not training_target:
                        own_side=next(side for side in session.record['result']['state']['sides'] if side['name']==hid)['pokemon']
                        def candidate_strength(option):
                            index=option.arguments['slot']-1
                            if index>=len(own_side):return 0
                            mon=state.pokemon.get(own_side[index]['set']['name'],{})
                            best=0
                            for entry in mon.get('moves',[]):
                                if entry.get('pp',0)<=0:continue
                                move=catalog['moves'].get(normalize(entry['move']),{});score=move.get('power',0)*move.get('accuracy',100)/100
                                if move.get('type') in catalog['species'].get(normalize(mon.get('species','')),{}).get('types',[]):score*=1.5
                                for kind in set(foe_types):score*=effectiveness.get((move.get('type'),kind),1)
                                best=max(best,score)
                            return best
                        switches=[option for option in choices if option.action=='battle_switch']
                        if switches:
                            candidate=max(switches,key=candidate_strength)
                            if candidate_strength(candidate)>strength(choice)*1.5:choice=candidate
                if choice is None:choice=next((option for option in choices if option.action=='battle_switch'),None)
                if choice is None:raise RuntimeError('No playable move or switch at legal battle boundary')
                action(actor,choice.action,choice.arguments);progressed=True
            if not progressed:raise RuntimeError('No participant is ready at unresolved battle boundary')
        raise RuntimeError('Bounded battle turn limit reached')
    def training(map_id,center,battles,target_level,preferred_species=None):
        nonlocal training_target
        state=current();party=state.humans[hid]['party']
        candidates=[pid for pid in party if not preferred_species or state.pokemon[pid]['species'] in preferred_species]
        if not candidates:raise RuntimeError('No owned individual matches explicit TEST training choice')
        carry=max(candidates,key=lambda pid:state.pokemon[pid]['level'])
        checkpoint('test-training-main-'+carry+'-target-'+str(target_level))
        for index in range(battles):
            if preparation_deadline is not None and time.time()>=preparation_deadline:
                checkpoint('bounded-preparation-deadline-earned-team-only');break
            lifecycle()
            if target_level and current().pokemon[carry]['level']>=target_level:break
            navigate(map_id);state=current();human=state.humans[hid];gm=actor_map(engine.maps[map_id],human)
            raw=json.loads(Path('content/maps',map_id+'.json').read_text());grass=[]
            for cell in raw['cells']:
                if cell.get('encounter_type') not in {1,2}:continue
                try:route=shortest_path(gm,(human['x'],human['y']),(cell['x'],cell['y']))
                except PathNotFound:continue
                grass.append((len(route),cell['x'],cell['y']))
            if not grass:raise RuntimeError(f'{map_id} source encounter grass cannot be reached on foot')
            _,x,y=min(grass)
            if (x,y)!=(human['x'],human['y']):action(hid,'travel_to',{'x':x,'y':y})
            state=current();training_target=carry
            if not engine.active_battle(current(),hid):action(hid,'train')
            battle();training_target=None;stages.append(f'actual-wild-battle-{map_id}-{index+1}')
            state=current();mons=[state.pokemon[p] for p in state.humans[hid]['party']]
            if (index+1)%5==0 or any(p['hp']==0 or p['hp']<p['stats']['hp']*0.4 or p.get('status') for p in mons):healing(center)
            if (index+1)%10==0:checkpoint(f'{map_id}-wild-training-{index+1}')
        lifecycle()
    def gym(name,map_id,badge):
        if badge in current().humans[hid]['badges']:return
        navigate(map_id);leader=next(h for h in current().humans.values() if h['name']==name)
        navigate(map_id,(leader['x'],leader['y']));action(hid,'start_battle',{'human_id':leader['human_id']});battle()
        stages.append('official-'+name.lower().replace(' ','-')+'-battle-completed')
        checkpoint('official-'+name.lower().replace(' ','-')+'-completed')
        if badge not in current().humans[hid]['badges']:raise RuntimeError(f'Actual {name} battle lost; badge remains unearned')
    def station(scenario_id):
        row=next(r for r in json.loads(Path('content/scenarios.json').read_text())['scenarios'] if r['id']==scenario_id)
        if scenario_id in current().humans[hid].get('scenarios',{}).get('completed',[]):return
        navigate(row['map_id']);human=current().humans[hid];gm=actor_map(engine.maps[human['map_id']],human);options=[]
        for x,y in [(row['x']-1,row['y']),(row['x']+1,row['y']),(row['x'],row['y']-1),(row['x'],row['y']+1)]:
            try:route=shortest_path(gm,(human['x'],human['y']),(x,y))
            except PathNotFound:continue
            options.append((len(route),x,y))
        if not options:raise RuntimeError(f'No physically reachable source station {scenario_id}')
        _,x,y=min(options)
        navigate(row['map_id'],(x,y))
        action(hid,'use_scenario',{'scenario_id':scenario_id});stages.append('source-station-'+scenario_id);checkpoint('source-station-'+scenario_id)
    def grass_position(map_id):
        navigate(map_id);human=current().humans[hid];gm=actor_map(engine.maps[map_id],human);options=[]
        for cell in json.loads(Path('content/maps',map_id+'.json').read_text())['cells']:
            if cell.get('encounter_type') not in {1,2}:continue
            try:route=shortest_path(gm,(human['x'],human['y']),(cell['x'],cell['y']))
            except PathNotFound:continue
            options.append((len(route),cell['x'],cell['y']))
        if not options:raise RuntimeError('No reachable encounter terrain in '+map_id)
        _,x,y=min(options)
        if (x,y)!=(human['x'],human['y']):action(hid,'travel_to',{'x':x,'y':y})
    def stock_balls(mart):
        h=current().humans[hid]
        if sum(h['inventory'].get(ball,{}).get('quantity',0) for ball in ('poke_ball','great_ball','ultra_ball'))>=3:return
        navigate(mart);prices=engine.shop_prices(mart)
        balls=[ball for ball in ('poke_ball','great_ball','ultra_ball') if ball in prices]
        if not balls:raise RuntimeError('Source shop has no purchasable capture ball: '+mart)
        ball=min(balls,key=lambda b:prices[b])
        staff=next((p for p in current().humans.values() if p.get('service_assignment',{}).get('kind')=='shop' and p['map_id']==mart),None)
        if not staff:raise RuntimeError('No source shop human available at '+mart)
        for _ in range(3):
            action(hid,'shop_buy',{'item':ball,'quantity':1})
            serve=engine.service_actions(current(),staff['human_id'])[0];action(staff['human_id'],serve.action,serve.arguments)

    def capture(species,map_id,center,mart):
        family={'ODDISH':{'ODDISH','GLOOM','VILEPLUME'},'DIGLETT':{'DIGLETT','DUGTRIO'},'GROWLITHE':{'GROWLITHE','ARCANINE','VULPIX','NINETALES'}}.get(species,{species})
        if any(current().pokemon[p]['species'] in family for p in current().humans[hid]['party']):return
        for attempt in range(25):
            stock_balls(mart)
            grass_position(map_id)
            if not engine.active_battle(current(),hid):action(hid,'train')
            record=engine.active_battle(current(),hid)
            foe=record['session']['teams'][1]['party'][0]['species']
            if foe in family:
                for _ in range(8):
                    choices=engine.battle_actions(current(),hid)
                    catch=next((o for o in choices or [] if o.action=='catch' and o.arguments['ball'] in {'poke_ball','great_ball','ultra_ball'}),None)
                    if catch is None:break
                    action(hid,catch.action,catch.arguments)
                    if not engine.active_battle(current(),hid):break
            if engine.active_battle(current(),hid):battle()
            healing(center);lifecycle()
            if any(current().pokemon[p]['species'] in family for p in current().humans[hid]['party']):stages.append('source-caught-'+species.lower());checkpoint('source-caught-'+species.lower());return
        raise RuntimeError('Bounded real encounter/catch attempts exhausted for '+species)
    def catch_surf_companion():
        if any(any(move['move']=='SURF' for move in current().pokemon[pid]['moves']) for pid in current().humans[hid]['party']) or any(o.action=='teach_machine' and o.known_consequences.get('move')=='SURF' for o in engine.legal_actions(current(),hid)):return
        station('fishing_good_rod')
        map_id='FuchsiaCity';center='FuchsiaCity_PokemonCenter_1F'
        for attempt in range(60):
            stock_balls('FuchsiaCity_Mart');navigate(map_id)
            human=current().humans[hid];gm=actor_map(engine.maps[map_id],human);shore=[]
            for y in range(gm.height):
                for x in range(gm.width):
                    if not gm.is_walkable(x,y) or not engine.near_water(map_id,x,y):continue
                    try:route=shortest_path(gm,(human['x'],human['y']),(x,y))
                    except PathNotFound:continue
                    shore.append((len(route),x,y))
            if not shore:raise RuntimeError('No reachable source fishing shore in FuchsiaCity')
            _,x,y=min(shore);navigate(map_id,(x,y))
            action(hid,'fish',{'rod':'good_rod'});record=engine.active_battle(current(),hid)
            if not record:continue
            foe=record['session']['teams'][1]['party'][0]['species']
            if foe in {'POLIWAG','GOLDEEN','SEAKING','PSYDUCK','SLOWPOKE','GYARADOS'}:
                for _ in range(8):
                    choices=engine.battle_actions(current(),hid);catch=next((o for o in choices if o.action=='catch' and o.arguments['ball'] in {'poke_ball','great_ball','ultra_ball'}),None)
                    if not catch:break
                    action(hid,catch.action,catch.arguments)
                    if not engine.active_battle(current(),hid):break
            if engine.active_battle(current(),hid):battle()
            healing(center);lifecycle()
            if any(o.action=='teach_machine' and o.known_consequences.get('move')=='SURF' for o in engine.legal_actions(current(),hid)):
                stages.append('source-fished-surf-compatible-companion');checkpoint(stages[-1]);return
        raise RuntimeError('Bounded genuine source fishing/capture attempts exhausted')

    def teach(move):
        if any(any(m['move']==move for m in current().pokemon[p]['moves']) for p in current().humans[hid]['party']):return
        choice=next((o for o in engine.legal_actions(current(),hid) if o.action=='teach_machine' and o.known_consequences.get('move')==move),None)
        if choice is None:raise RuntimeError('No owned healthy compatible individual / source machine offered for '+move)
        action(hid,choice.action,choice.arguments);stages.append('source-machine-taught-'+move.lower())
    def mansion_secret_key_route():
        from living_kanto.simulation.pickups import source_items
        navigate('PokemonMansion_1F')
        destination=engine.maps['PokemonMansion_B1F']
        item=next(obj for obj in destination.events.get('object_events',[]) if source_items().get(obj.get('script'),(None,))[0]=='secret_key')
        for _ in range(120):
            if engine.active_battle(current(),hid):battle()
            human=current().humans[hid];initial=(human['map_id'],human['x'],human['y'],bool(human.get('field',{}).get('mansion_switch')))
            if initial[0]=='PokemonMansion_B1F' and abs(initial[1]-item['x'])+abs(initial[2]-item['y'])<=1:return
            views={(mid,on):actor_map(engine.maps[mid],{**human,'map_id':mid,'field':{**human.get('field',{}),'mansion_switch':on}}) for mid in ['PokemonMansion_1F','PokemonMansion_2F','PokemonMansion_3F','PokemonMansion_B1F'] for on in [False,True]}
            todo=deque([initial]);previous={initial:None};goal=None
            while todo and len(previous)<20000:
                node=todo.popleft();mid,x,y,on=node;view=views[(mid,on)]
                if mid=='PokemonMansion_B1F' and abs(x-item['x'])+abs(y-item['y'])<=1:goal=node;break
                successors=[]
                for direction in ['north','west','east','south']:
                    point=view.step_destination((x,y),direction)
                    if point:successors.append(((mid,*point,on),('walk',None)))
                target=view.exit_target(x,y)
                if target and target.startswith('PokemonMansion_'):
                    try:
                        dst,nx,ny=resolve_transfer(engine.maps,view,x,y,target)
                        if views[(dst,on)].is_walkable(nx,ny):successors.append(((dst,nx,ny,on),('transfer',target)))
                    except MapLoadError:pass
                if any((x,y-1)==(bg['x'],bg['y']) for bg in view.events['mansion_switch']['statues']):successors.append(((mid,x,y,not on),('toggle',None)))
                for following,edge in successors:
                    if following not in previous:previous[following]=(node,edge);todo.append(following)
            if goal is None:raise RuntimeError('No source-switch-aware physical route to Mansion Secret Key')
            route=[]
            while goal!=initial:
                previous_node,edge=previous[goal];route.append((goal,edge));goal=previous_node
            route.reverse();last_walk=None
            for following,edge in route:
                if edge[0]=='walk':last_walk=following;continue
                break
            if last_walk:
                action(hid,'travel_to',{'x':last_walk[1],'y':last_walk[2]});continue
            following,edge=route[0]
            if edge[0]=='toggle':
                if human.get('facing')!='north':action(hid,'turn_to',{'direction':'north'})
                action(hid,'toggle_mansion_switch',{})
            elif edge[0]=='transfer':action(hid,'enter_map',{'map_id':edge[1]})
        raise RuntimeError('Bounded physical Mansion switch/encounter route exhausted')

    def source_item(item,map_id=None):
        from living_kanto.simulation.pickups import source_items
        if current().humans[hid]['inventory'].get(item,{}).get('quantity',0)>0:return
        choices=[]
        for mid,gm in engine.maps.items():
            if map_id and mid!=map_id:continue
            for obj in gm.events.get('object_events',[]):
                reward=source_items().get(obj.get('script'))
                if obj.get('graphics_id')=='OBJ_EVENT_GFX_ITEM_BALL' and reward and reward[0]==item:choices.append((mid,obj))
        if not choices:raise RuntimeError('No source physical pickup implemented for '+item)
        errors=[]
        for mid,obj in choices:
            try:
                navigate(mid);h=current().humans[hid];gm=actor_map(engine.maps[mid],h);near=[]
                for x,y in [(obj['x']-1,obj['y']),(obj['x']+1,obj['y']),(obj['x'],obj['y']-1),(obj['x'],obj['y']+1)]:
                    try:route=shortest_path(gm,(h['x'],h['y']),(x,y))
                    except PathNotFound:continue
                    near.append((len(route),x,y))
                if not near:raise RuntimeError('No reachable item interaction tile')
                _,x,y=min(near);navigate(mid,(x,y))
                offer=next(o for o in engine.legal_actions(current(),hid) if o.action=='pick_up_item' and o.known_consequences.get('item')==item)
                action(hid,offer.action,offer.arguments);stages.append('source-pickup-'+item);checkpoint('source-pickup-'+item);return
            except Exception as exc:errors.append(mid+': '+str(exc))
        raise RuntimeError('Source pickup '+item+' physically blocked: '+'; '.join(errors))
    def snorlax(map_id):
        from living_kanto.simulation.field import objects
        navigate(map_id)
        for obj in [o for o in objects(engine.maps[map_id],current().humans[hid]) if o['kind']=='snorlax']:
            h=current().humans[hid];gm=actor_map(engine.maps[map_id],h);near=[]
            for x,y in [(obj['x']-1,obj['y']),(obj['x']+1,obj['y']),(obj['x'],obj['y']-1),(obj['x'],obj['y']+1)]:
                try:route=shortest_path(gm,(h['x'],h['y']),(x,y))
                except PathNotFound:continue
                near.append((len(route),x,y))
            if not near:continue
            _,x,y=min(near);navigate(map_id,(x,y));action(hid,'start_snorlax_battle',{'object_id':obj['key']});battle();stages.append('source-snorlax-battle-'+map_id)
    def start_surf(map_id):
        from living_kanto.simulation.field import WATER,DIRECTIONS
        navigate(map_id);h=current().humans[hid];gm=actor_map(engine.maps[map_id],h);near=[]
        for point,cell in gm.cells.items():
            if int(cell.get('behavior',0)) not in WATER:continue
            for direction,(dx,dy) in DIRECTIONS.items():
                start=(point[0]-2*dx,point[1]-2*dy);adjacent=(point[0]-dx,point[1]-dy)
                if gm.step_destination(start,direction)!=adjacent:continue
                try:route=shortest_path(gm,(h['x'],h['y']),start)
                except PathNotFound:continue
                near.append((len(route),start,direction))
        if not near:raise RuntimeError('No legal shoreline approach from '+map_id)
        _,start,direction=min(near);navigate(map_id,start);action(hid,'walk_to',{'direction':direction});action(hid,'surf')
    def surf_journey(goal):
        for _ in range(500):
            if engine.active_battle(current(),hid):battle()
            if current().humans[hid]['map_id']==goal:return
            action(hid,'journey_to',{'map_id':goal})
        raise RuntimeError('Bounded source surf journey exceeded')
    def cut_trees(map_id):
        from living_kanto.simulation.field import objects,DIRECTIONS
        trees=[o for o in objects(engine.maps[map_id],current().humans[hid]) if o['kind']=='tree']
        if not trees:return
        navigate(map_id)
        for tree in trees:
            h=current().humans[hid];gm=actor_map(engine.maps[map_id],h);options=[]
            for direction,(dx,dy) in DIRECTIONS.items():
                start=(tree['x']-2*dx,tree['y']-2*dy);adjacent=(tree['x']-dx,tree['y']-dy)
                if gm.step_destination(start,direction)!=adjacent:continue
                try:route=shortest_path(gm,(h['x'],h['y']),start)
                except PathNotFound:continue
                options.append((len(route),start,direction))
            if not options:continue
            _,start,direction=min(options)
            navigate(map_id,start)
            action(hid,'walk_to',{'direction':direction});action(hid,'cut',{'object_id':tree['key']});stages.append('source-cut-'+tree['key'])
    try:
        if not current().humans[hid]['party']:
            assert current().humans[hid]['badges']==[] and current().humans[hid]['party']==[]
            navigate('PalletTown_ProfessorOaksLab');action(hid,'choose_starter',{'species':args.starter});stages.append('source-starter-received')
        if args.resume:
            for event in store.iter_events(args.run_id):
                prov=(event.causation or {}).get('provenance',{})
                if prov.get('kind')=='creative' or (prov.get('kind')=='model' and not prov.get('test_provider')):raise RuntimeError('Resume accepts identified scripted mechanical test history only')
        if 'boulder' not in current().humans[hid]['badges']:
            training('Route1','ViridianCity_PokemonCenter_1F',args.wild_battles,args.target_level)
            gym('Brock','PewterCity_Gym','boulder')
        if args.through!='brock':
            if 'cascade' not in current().humans[hid]['badges']:
                navigate('CeruleanCity');stages.append('legal-source-mt-moon-crossing')
                capture('ODDISH','Route24','CeruleanCity_PokemonCenter_1F','CeruleanCity_Mart')
                training('Route24','CeruleanCity_PokemonCenter_1F',args.stage_wild_battles,args.stage_target_level)
                gym('Misty','CeruleanCity_Gym','cascade')
        if args.through in {'bill-cut','surge','mainland','league'} and 'captain_cut' not in current().humans[hid].get('scenarios',{}).get('completed',[]):
            healing('CeruleanCity_PokemonCenter_1F')
            station('bill_cell_separator');station('bill_ticket');station('captain_cut')
        if args.through in {'surge','mainland','league'} and 'thunder' not in current().humans[hid]['badges']:
            capture('ODDISH','Route24','CeruleanCity_PokemonCenter_1F','CeruleanCity_Mart');teach('CUT')
            capture('DIGLETT','DiglettsCave_B1F','VermilionCity_PokemonCenter_1F','VermilionCity_Mart')
            cut_trees('VermilionCity')
            gym('Lt. Surge','VermilionCity_Gym','thunder')
        if args.through in {'mainland','league'}:
            cut_trees('Route9');navigate('LavenderTown');navigate('CeladonCity');cut_trees('CeladonCity')
            if 'rainbow' not in current().humans[hid]['badges']:
                cut_trees('Route8')
                capture('GROWLITHE','Route8','LavenderTown_PokemonCenter_1F','LavenderTown_Mart')
                training('Route8','LavenderTown_PokemonCenter_1F',args.stage_wild_battles,31,{'GROWLITHE','ARCANINE','VULPIX','NINETALES'})
                healing('LavenderTown_PokemonCenter_1F')
                gym('Erika','CeladonCity_Gym','rainbow')
            if args.stop_after_erika:
                checkpoint('bounded-actual-erika-stage-complete');return
            healing('CeladonCity_PokemonCenter_1F')
            station('celadon_tea');source_item('lift_key','RocketHideout_B4F');station('hideout_scope')
            if not current().humans[hid].get('access',{}).get('tower_marowak_defeated'):
                navigate('PokemonTower_6F',(11,15));action(hid,'start_ghost_battle');battle()
                if not current().humans[hid].get('access',{}).get('tower_marowak_defeated'):raise RuntimeError('Actual uncatchable Tower ghost battle lost')
            stages.append('actual-tower-ghost-victory');station('tower_fuji_release');station('fuji_flute')
            snorlax('Route12');navigate('FuchsiaCity')
            if 'soul' not in current().humans[hid]['badges']:
                training('Route15','FuchsiaCity_PokemonCenter_1F',args.stage_wild_battles,40)
                gym('Koga','FuchsiaCity_Gym','soul')
            healing('FuchsiaCity_PokemonCenter_1F')
            completed=current().humans[hid].get('scenarios',{}).get('completed',[])
            if 'safari_surf' not in completed or 'warden_strength' not in completed:
                navigate('FuchsiaCity_SafariZone_Entrance')
                if not current().humans[hid].get('safari',{}).get('active'):action(hid,'safari_enter')
                station('safari_surf')
                if 'warden_strength' not in completed:source_item('gold_teeth','SafariZone_West')
                navigate('FuchsiaCity');station('warden_strength')
            catch_surf_companion();teach('SURF');teach('STRENGTH')
            healing('FuchsiaCity_PokemonCenter_1F');gym('Sabrina','SaffronCity_Gym','marsh');healing('SaffronCity_PokemonCenter_1F')
            if 'volcano' not in current().humans[hid]['badges']:
                if current().humans[hid]['map_id'].startswith(('CinnabarIsland','PokemonMansion')):navigate('CinnabarIsland')
                else:start_surf('PalletTown');surf_journey('CinnabarIsland')
                mansion_secret_key_route();source_item('secret_key','PokemonMansion_B1F');gym('Blaine','CinnabarIsland_Gym','volcano')
                healing('CinnabarIsland_PokemonCenter_1F')
            if current().humans[hid]['map_id'].startswith(('CinnabarIsland','PokemonMansion')):start_surf('CinnabarIsland');surf_journey('PalletTown')
            gym('Giovanni','ViridianCity_Gym','earth')
            stages.append('all-eight-engine-earned-badges');checkpoint('all-eight-engine-earned-badges')
        if args.through=='league':
            training('Route23','IndigoPlateau_PokemonCenter_1F',args.league_wild_battles,args.league_target_level)
            healing('IndigoPlateau_PokemonCenter_1F');navigate('IndigoPlateau_PokemonCenter_1F')
            if not current().humans[hid].get('league',{}).get('active'):
                staff=next(h for h in current().humans.values() if h.get('service_assignment',{}).get('kind')=='shop' and h['map_id']=='IndigoPlateau_PokemonCenter_1F')
                for item,wanted in [('full_restore',3),('revive',2)]:
                    existing=current().humans[hid]['inventory'].get(item,{}).get('quantity',0)
                    for _ in range(max(0,wanted-existing)):
                        if current().humans[hid]['money']<engine.shop_prices(staff['map_id'])[item]:break
                        action(hid,'shop_buy',{'item':item,'quantity':1});serve=engine.service_actions(current(),staff['human_id'])[0];action(staff['human_id'],serve.action,serve.arguments)
                action(hid,'league_enter')
            from living_kanto.mechanics.progression import next_league_opponent
            for _ in range(5):
                if current().world_facts['championship']['current_champion']==hid:break
                expected=next_league_opponent(current().humans[hid])
                if not expected:break
                champion=current().world_facts['championship']['current_champion']
                opponent=next(h for h in current().humans.values() if (h['human_id']==champion if expected=='Champion' else h['name'].replace(' ','').replace('.','')==expected))
                for pid in current().humans[hid]['party']:
                    mon=current().pokemon[pid]
                    item='revive' if mon['hp']==0 else 'full_restore' if mon['hp']<mon['stats']['hp']*0.65 or mon.get('status') else None
                    if item:
                        option=next((o for o in engine.legal_actions(current(),hid) if o.action=='use_item' and o.arguments.get('pokemon_id')==pid and o.arguments.get('item')==item),None)
                        if option:action(hid,option.action,option.arguments)
                navigate(opponent['map_id'],(opponent['x'],opponent['y']))
                action(hid,'start_battle',{'human_id':opponent['human_id']});battle()
                checkpoint('actual-league-'+expected.lower())
                if not current().humans[hid].get('league',{}).get('active') and current().world_facts['championship']['current_champion']!=hid:raise RuntimeError('Actual official league challenge lost at '+expected)
            if current().world_facts['championship']['current_champion']!=hid:raise RuntimeError('Bounded league challenge did not earn championship')
            stages.append('actual-zero-badge-lineage-championship');checkpoint(stages[-1])
    except KeyboardInterrupt:failure={'type':'InterruptedScriptedTest','reason':'Preserved committed checkpoint for verified source update; requested stage not complete','state_version':current().state_version,'map_id':current().humans[hid]['map_id']}
    except Exception as exc:failure={'type':type(exc).__name__,'reason':str(exc),'state_version':current().state_version,'map_id':current().humans[hid]['map_id']}
    finally:
        final=current();metadata,_,head=store.load_run(args.run_id);verified=store.replay(args.run_id);store.set_status(args.run_id,'paused')
        report={'kind':'scripted-source-reachability-test','autonomous_evidence':False,'creative_interventions':0,'run_id':args.run_id,'seed':args.seed,'stages':stages,'failure':failure,'event_count':count,'events_this_session':count-initial_count,'requested_through':args.through,'preparation_deadline':args.preparation_until,'stop_after_erika':args.stop_after_erika,'checkpoint_resumed':args.resume,'final_state_hash':final.state_hash,'replay_verified':verified.state_hash==final.state_hash,'human_id':hid,'trainer':final.humans[hid],'party':[final.pokemon[pid] for pid in final.humans[hid]['party']],'whiteout_receipts':[b['whiteout_respawn'] for b in final.world_facts.get('battles',{}).values() if b.get('whiteout_respawn')],'full_m3_journey_verified':False,'mainland_eight_badge_journey_completed':failure is None and 'all-eight-engine-earned-badges' in stages,'source_fingerprint':fingerprint,'prior_source_fingerprints':prior.get('prior_source_fingerprints',[])+([prior['source_fingerprint']] if prior.get('source_fingerprint') else []),'reference_revision':'037335f4c725d7c9aecdac87066f2002b4bd7e14'}
        if args.export:
            if final.state_hash!=verified.state_hash:raise RuntimeError('Cannot export mismatched replay')
            public_metadata=metadata.to_dict();public_metadata['data_directory']=''
            bundle={'format':'living-kanto-run-v1','metadata':public_metadata,'genesis':store.load_genesis(args.run_id).to_dict(),'events':[event.to_dict() for event in store.iter_events(args.run_id)],'inference_settings_included':False,'state_hash':final.state_hash,'head_hash':head}
            export=Path(args.export);export.parent.mkdir(parents=True,exist_ok=True);temporary=export.with_suffix(export.suffix+'.tmp');temporary.write_text(json.dumps(bundle,separators=(',',':'))+'\n');temporary.replace(export)
            report['portable_export']={'path':str(export),'sha256':hashlib.sha256(export.read_bytes()).hexdigest(),'replay_verified':True,'state_hash':final.state_hash}
        final_fingerprint=source_fingerprints();report['final_source_fingerprint']=final_fingerprint;report['source_changed_during_session']=final_fingerprint!=fingerprint
        target=Path(args.report);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
        archive=target.parent/'lineage-sessions';archive.mkdir(exist_ok=True)
        archived=archive/(target.stem+'-checkpoint-'+str(count)+'-'+hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()[:10]+'.json')
        archived.write_text(json.dumps(report,indent=2)+'\n');store.close()
        print(json.dumps({'report':str(target),'events':count,'stages':stages,'failure':failure,'badges':final.humans[hid]['badges']}))

if __name__=='__main__':main()
