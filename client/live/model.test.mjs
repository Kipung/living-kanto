import test from 'node:test';
import assert from 'node:assert/strict';
import {routeSegments,activity,battleMessages,eventText,actorId,groupByMap,walkingDuration,clockOnly,sharedClockLabel,elapsedWorldTime,worldProgress} from './model.mjs';
test('accepted journey preserves map boundaries and every path tile',()=>{
 const e={deterministic_inputs:{route:{journey:[{map_id:'PalletTown',start:[6,8],steps:[[7,8],[8,8]]},{map_id:'Route1',start:[12,39],steps:[[12,38],[11,38]]}]}}};
 assert.deepEqual(routeSegments(e),[{map:'PalletTown',points:[[6,8],[7,8],[8,8]]},{map:'Route1',points:[[12,39],[12,38],[11,38]]}]);
});
test('distant jumps and Creative teleports never fabricate walking',()=>{
 const e={event_kind:'human.moved',before:{position:{map_id:'A',x:1,y:1}},after:{position:{map_id:'A',x:20,y:20}}};assert.deepEqual(routeSegments(e),[]);
 assert.deepEqual(routeSegments({...e,event_kind:'intervention.applied',after:{position:{map_id:'A',x:2,y:1}}}),[]);
 assert.deepEqual(routeSegments({...e,after:{position:{map_id:'A',x:2,y:1}}}),[{map:'A',points:[[1,1],[2,1]]}]);
});
test('activity countdown uses simulated time, not elapsed browser time',()=>{
 assert.equal(activity({activity:{kind:'work',ready_at:3700}},{simulated_time:100}).label,'Working · 60 sim min left');
 assert.equal(activity({battle_id:'b'},{}).kind,'battle');
});
test('split battle logs show exact damage once and distinguish trainers',()=>{
 const messages=battleMessages(['|switch|p1a: a|Pikachu, L25|58/58','|switch|p2a: b|Pikachu, L25|58/58','|move|p1a: a|Quick Attack|p2a: b','|split|p2','|-damage|p2a: b|28/58','|-damage|p2a: b|49/100'],['You','Ari']);
 assert.equal(messages.filter(m=>m.type==='-damage').length,1);assert.match(messages[0].text,/You · Pikachu/);assert.match(messages.at(-1).text,/Ari · Pikachu · HP 28\/58/);
});
test('chat feed identifies actual recipient without inventing utterances',()=>{
 assert.equal(eventText({causation:{human_id:'a',action:'talk_to',action_arguments:{human_id:'b'}}},{a:{name:'Ari'},b:{name:'Bea'}}),'Ari chatted with Bea');
});

test('atomic daily activity batches retain every individual name',()=>{const e={causation:{human_id:'engine',decisions:[{human_id:'a',action:'work'},{human_id:'b',action:'rest'}]}};assert.equal(actorId(e),'a');assert.equal(eventText(e,{a:{name:'Ari'},b:{name:'Bea'}}),'Ari started work · Bea started resting');});

test('overview accounts for all100 humans across interiors and routes',()=>{const people=Array.from({length:100},(_,i)=>({human_id:'h'+i,map_id:i<35?'PalletTown':i<60?'PalletTown_ProfessorOaksLab':'Route1'}));const groups=groupByMap(people);assert.equal(groups.length,3);assert.equal(groups.reduce((n,[,members])=>n+members.length,0),100);assert.equal(new Set(groups.flatMap(([,members])=>members.map(h=>h.human_id))).size,100);});
test('smooth walking retains duration of long recorded routes instead of six-second bursts',()=>{const points=Array.from({length:101},(_,i)=>[i,0]);assert.equal(walkingDuration(points),36000);assert.equal(walkingDuration(points,{smooth:false}),14500);assert.equal(walkingDuration([[0,0],[1,0]]),360);});

test('one shared tick retains both nested canonical actor routes',()=>{
 const e={event_kind:'world.shared_tick',causation:{human_id:'engine'},deterministic_inputs:{shared_time:{from:5,to:6,elapsed:1},routes:[{human_id:'a',route:{map_id:'PalletTown',start:[1,1],steps:[[2,1]]}},{human_id:'b',route:{map_id:'Route1',start:[4,5],steps:[[4,4]]}}]}};
 assert.deepEqual(routeSegments(e,'a'),[{map:'PalletTown',points:[[1,1],[2,1]]}]);
 assert.deepEqual(routeSegments(e,'b'),[{map:'Route1',points:[[4,5],[4,4]]}]);
 assert.equal(routeSegments(e).length,2);assert.equal(actorId(e),'a');
 assert.equal(eventText(e,{a:{name:'Ari'},b:{name:'Bea'}}),'Ari · Bea advanced together · 1s');
});
test('recorded warp never invents walking between its two maps',()=>{
 const e={event_kind:'world.shared_tick',deterministic_inputs:{routes:[{human_id:'a',route:{transfer:{source_map:'PalletTown',source:[1,1],destination_map:'Route1',destination:[3,4]}}}]}};
 assert.deepEqual(routeSegments(e,'a'),[]);
});
test('persisted movement and runtime thinking are different facts',()=>{
 assert.equal(activity({human_id:'a',movement_intent:{kind:'scheduled_movement'}},{simulated_time:9}).kind,'movement');
 assert.equal(activity({human_id:'b'},{simulated_time:9},{inflight_actors:['b']}).kind,'thinking');
 assert.equal(activity({human_id:'c'},{simulated_time:9},{inflight_actors:['b']}).kind,'ready');
});
test('battle interrupts an accepted traveller without showing them moving',()=>{
 assert.equal(activity({battle_id:'b',movement_intent:{paused_for_battle:true}},{},{}).kind,'battle');
});

test('movement-only ticks do not drown real conversations or completion receipts',()=>{
 assert.equal(clockOnly({event_kind:'world.shared_tick',deterministic_inputs:{routes:[{human_id:'a',event_kind:'human.moved'}]}}),true);
 assert.equal(clockOnly({event_kind:'world.shared_tick',deterministic_inputs:{activity_completions:[{human_id:'a'}]}}),false);
 assert.equal(clockOnly({event_kind:'human.talked',causation:{action:'talk_to'}}),false);
});
test('requested and actual shared clock rate remain distinct',()=>{
 assert.equal(sharedClockLabel({clock_mode:'shared',speed:20,actual_simulated_seconds_per_wall_second:3.2,clock_processing_limited:true}),'Requested 20× · actual 3.20× · processing limits the clock');
 assert.equal(sharedClockLabel({clock_mode:'legacy'}),'');
});

test('elapsed world time separates days hours minutes and seconds',()=>{
 assert.equal(elapsedWorldTime(90061),'1d 01h 01m 01s');assert.equal(elapsedWorldTime(0),'0d 00h 00m 00s');assert.equal(elapsedWorldTime(undefined),'—');
});
test('saved updates and AI decisions never stand in for world seconds',()=>{
 const values=worldProgress({simulated_time:17,state_version:800},{accepted_decisions:24,speed:20,actual_simulated_seconds_per_wall_second:3.5,queue_depth:2,concurrency:4},'running');
 assert.equal(values.time,'0d 00h 00m 17s');assert.equal(values.updates,'800');assert.equal(values.decisions,'24');assert.equal(values.thinking,'2 / 4');assert.equal(values.clock,'Requested 20× · measured 3.50×');
});
test('paused progress never claims live advancement or active thinking',()=>{
 const values=worldProgress({simulated_time:60,state_version:99},{accepted_decisions:8,speed:5,actual_simulated_seconds_per_wall_second:4.2,queue_depth:2,pending_requests:2,concurrency:4},'paused');
 assert.equal(values.clock,'Paused · requested 5×');assert.equal(values.thinking,'0 / 4 · 2 retiring');assert.equal(values.decisions,'8');
});
