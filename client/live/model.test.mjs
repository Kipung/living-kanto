import test from 'node:test';
import assert from 'node:assert/strict';
import {routeSegments,activity,battleMessages,eventText,actorId,groupByMap,walkingDuration} from './model.mjs';
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
