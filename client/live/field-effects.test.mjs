import test from 'node:test';import assert from 'node:assert/strict';
import {fieldActionEffects,advanceReceiptPositions,fieldEffectPoint,drawFieldEffects,drawMapBadge} from './field-effects.mjs';import {activityIndicator} from './model.mjs';
const event=(action,args={},changes=[])=>({causation:{human_id:'a',action,action_arguments:args},transaction:{changes}});
test('Cut targets the exact original object and never a guessed adjacent tile',()=>{
 const fx=fieldActionEffects(event('cut',{object_id:'Route2:7'}),{before:{map_id:'Route2',x:4,y:5}})[0];
 assert.deepEqual(fieldEffectPoint(fx,{map_name:'Route2',events:{object_events:[{local_id:7,x:4,y:4}]}}),{x:4,y:4});
 assert.equal(fieldEffectPoint(fx,{map_name:'Route1'}),null);assert.equal(fieldEffectPoint(fx,{map_name:'Route2',events:{object_events:[]}}),null);
});
test('Strength uses the committed landing and recorded push direction',()=>{
 const fx=fieldActionEffects(event('push_boulder',{object_id:'VictoryRoad_1F:2',direction:'east'},[{op:'set',path:'humans.a.field.boulders',value:{'VictoryRoad_1F:2':[9,3]}}]))[0];assert.deepEqual(fx.position,{x:8,y:3});
});
test('receipt positions follow every actor and map transfer without modifying snapshots',()=>{
 const positions=new Map([['a',{map_id:'Route19',x:5,y:6}],['b',{map_id:'PalletTown',x:1,y:1}]]);const prior=positions.get('a');
 advanceReceiptPositions(event('surf',{},[{op:'set',path:'humans.a.x',value:6},{op:'set',path:'humans.a.y',value:6}]),positions);assert.equal(prior.x,5);assert.equal(positions.get('b').x,1);
 const fx=fieldActionEffects(event('surf'),{before:prior,after:positions.get('a')});assert.deepEqual(fx.map(f=>f.position),[{x:5,y:6},{x:6,y:6}]);
});
test('Fly never invents a flight path between maps',()=>{
 const fx=fieldActionEffects(event('fly_to',{map_id:'PewterCity'}),{before:{map_id:'PalletTown',x:3,y:4},after:{map_id:'PewterCity',x:7,y:8}});assert.deepEqual(fx.map(f=>f.map_id),['PalletTown','PewterCity']);assert.equal(fx[0].route,undefined);
});
test('unrecorded or unlocated actions do not create field effects',()=>{
 assert.deepEqual(fieldActionEffects(event('wait')),[]);assert.deepEqual(fieldActionEffects(event('surf')),[]);assert.deepEqual(fieldActionEffects(event('use_field_move',{move:'SURF'})),[]);
});
test('expired and off-map effects draw nothing',()=>{
 const ctx={save(){throw Error('must not draw');}};const fx={map_id:'Route19',position:{x:1,y:2},start:0,until:10,kind:'surf'};
 assert.equal(drawFieldEffects(ctx,{map_name:'Route19'},[fx],{now:10}),false);assert.equal(drawFieldEffects(ctx,{map_name:'Route1'},[fx],{now:2}),false);
});
test('map badge size remains readable at different map zooms',()=>{
 const scales=[],ctx={save(){},restore(){},translate(){},scale(x){scales.push(x);},measureText(){return {width:20}},fillRect(){},strokeRect(){},fillText(){}};
 for(const zoom of [.5,2])drawMapBadge(ctx,{kind:'battle',icon:'⚔️',label:'Battling'},{x:1,y:2,zoom});assert.deepEqual(scales,[2,.5]);
});
test('Surf and bicycle indicators require recorded traversal status',()=>{
 assert.equal(activityIndicator({status:{surfing:true}},{},{}).kind,'surf');assert.equal(activityIndicator({status:{bicycle:true}},{},{}).kind,'bike');assert.equal(activityIndicator({status:{surfing:false}},{},{}).kind,'ready');assert.equal(activityIndicator({status:{surfing:true},battle_id:'b'},{},{}).kind,'battle');
});
