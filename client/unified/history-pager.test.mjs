import test from 'node:test';
import assert from 'node:assert/strict';
import {createHistoryPager} from './history-pager.mjs';
const event = n => ({event_id: 'e' + n, event_index: n});
const context = {world: 'same world', person: 'alice', throughVersion: 20, search: '', category: 'all'};
test('requests bounded pages through captured snapshot and preserves complete traversal', async () => {
 const urls=[], replies=[{events:[event(19),event(15)],next_before:15,has_more:true},
 {events:[event(15),event(10)],next_before:10,has_more:false}];
 const p=createHistoryPager(async url=>{urls.push(url);return replies.shift();});
 await p.reset(context);await p.next();
 assert.deepEqual(p.events.map(e=>e.event_index),[19,15,10]);assert.equal(p.hasMore,false);
 const first=new URL(urls[0],'http://local');assert.equal(first.searchParams.get('limit'),'50');
 assert.equal(first.searchParams.get('before'),'20');assert.equal(first.searchParams.get('human_id'),'alice');
 assert.equal(new URL(urls[1],'http://local').searchParams.get('before'),'15');
});
test('late old selection or filter response cannot replace current page', async()=>{
 let old;const p=createHistoryPager(url=>new URL(url,'http://local').searchParams.get('human_id')==='alice'?
 new Promise(resolve=>old=resolve):Promise.resolve({events:[event(18)],next_before:18,has_more:false}));
 const pending=p.reset(context);await p.reset({...context,person:'bob',search:'reply'});
 old({events:[event(19)],next_before:19,has_more:false});assert.equal(await pending,false);
 assert.deepEqual(p.events.map(e=>e.event_index),[18]);
});
test('failed page remains retryable without advancing or deleting loaded history', async()=>{
 let requests=0;const p=createHistoryPager(async()=>{if(++requests===2)throw Error('offline');
 return requests===1?{events:[event(19)],next_before:19,has_more:true}:{events:[event(17)],next_before:17,has_more:false};});
 await p.reset(context);await assert.rejects(p.next(),/offline/);assert.equal(p.loading,false);
 await p.next();assert.deepEqual(p.events.map(e=>e.event_index),[19,17]);
});
test('non-advancing cursor fails instead of endlessly repeating pages',async()=>{
 const p=createHistoryPager(async()=>({events:[event(19)],next_before:20,has_more:true}));
 await assert.rejects(p.reset(context),/cursor/);
});
