import test from 'node:test';
import assert from 'node:assert/strict';
import {shortcut,createMovement} from './keyboard.mjs';
const key=(key,extra={})=>({key,target:{closest:()=>null},...extra});
const context=()=>({world:'world',view:'area',mode:'survival',selected:'player',state:{humans:{player:{}}}});
test('shortcuts do not hijack typing, browser commands, or repeated keys',()=>{
 for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{repeat:true},{isComposing:true},{target:{closest:()=>({})}}])assert.equal(shortcut(key('w',extra),{mapFocused:true,playing:true}),null);
});
test('map movement requires map focus and distinguishes watching from playing',()=>{
 assert.equal(shortcut(key('w')),null);
 assert.deepEqual(shortcut(key('ArrowUp'),{mapFocused:true}),{type:'pan',direction:'north'});
 assert.deepEqual(shortcut(key('w'),{mapFocused:true,playing:true}),{type:'move',direction:'north'});
 assert.deepEqual(shortcut(key('1')),{type:'view',view:'wall'});assert.deepEqual(shortcut(key('4')),{type:'view',view:'journeys'});
});
test('movement accepts only legal walking and uses its observation version',async()=>{
 const calls=[];const move=createMovement({context,request:async(path,body)=>{calls.push({path,body});return {observation_version:42,legal_actions:[{action:'turn_to',arguments:{direction:'north'}},{action:'walk_to',arguments:{direction:'north'}}]};},refresh:async()=>{},onMessage:()=>{}});
 await move('north');assert.equal(calls.length,2);assert.equal(calls[1].body.expected_state_version,42);assert.equal(calls[1].body.action,'walk_to');
});
test('blocked walking never substitutes an unrelated action',async()=>{
 let writes=0;const move=createMovement({context,request:async(_,body)=>{if(body)writes++;return {legal_actions:[{action:'turn_to',arguments:{direction:'north'}}]};},refresh:async()=>{},onMessage:()=>{}});
 await move('north');assert.equal(writes,0);
});
test('one pending movement cannot accumulate more key presses',async()=>{
 let resolve,reads=0,writes=0;
 const move=createMovement({context,request:async(_,body)=>{if(body){writes++;return {};}reads++;return new Promise(r=>{resolve=r;});},refresh:async()=>{},onMessage:()=>{}});
 const pending=move('north');await move('east');assert.equal(reads,1);resolve({observation_version:1,legal_actions:[{action:'walk_to',arguments:{direction:'north'}}]});await pending;assert.equal(writes,1);
});
test('changing world or leaving Play while observing cancels the pending intention',async()=>{
 for(const change of [c=>c.world='other',c=>c.mode='observer',c=>c.selected='npc']){
  const c=context();let writes=0;const move=createMovement({context:()=>c,request:async(_,body)=>{if(body)writes++;else change(c);return {legal_actions:[{action:'walk_to',arguments:{direction:'north'}}]};},refresh:async()=>{},onMessage:()=>{}});await move('north');assert.equal(writes,0);
 }
});
test('stale commands are reported and never automatically repeated',async()=>{
 let writes=0;const messages=[];const move=createMovement({context,request:async(_,body)=>{if(body){writes++;throw Error('Player state changed');}return {observation_version:1,legal_actions:[{action:'walk_to',arguments:{direction:'north'}}]};},refresh:async()=>{},onMessage:m=>messages.push(m)});await move('north');assert.equal(writes,1);assert.match(messages.at(-1),/Player state changed/);
});
test('observer mode and battle state cannot issue walking commands',async()=>{
 for(const c of [{...context(),mode:'observer'},{...context(),state:{humans:{player:{battle_id:'b'}}}}]){
  let requests=0;const move=createMovement({context:()=>c,request:async()=>{requests++;},refresh:async()=>{},onMessage:()=>{}});await move('north');assert.equal(requests,0);
 }
});
