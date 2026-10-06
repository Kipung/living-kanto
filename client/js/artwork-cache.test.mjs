import test from 'node:test';
import assert from 'node:assert/strict';
import {cachedJSON} from './artwork-cache.mjs';

test('artwork is reused across loads and fetch failures do not poison the cache',async()=>{
 const entries=new Map();let requests=0;
 globalThis.caches={open:async()=>({match:async key=>entries.get(key)?.clone(),put:async(key,value)=>entries.set(key,value)})};
 globalThis.fetch=async()=>{requests++;return new Response(JSON.stringify({width:32}),{status:200});};
 assert.deepEqual(await cachedJSON('/map.json'),{width:32});
 assert.deepEqual(await cachedJSON('/map.json'),{width:32});assert.equal(requests,1);
 globalThis.fetch=async()=>new Response('missing',{status:404});
 await assert.rejects(cachedJSON('/missing.json'));assert.equal(entries.has('/missing.json'),false);
});
test('artwork still loads when persistent browser storage is unavailable',async()=>{
 globalThis.caches={open:async()=>{throw Error('storage unavailable');}};
 globalThis.fetch=async()=>new Response(JSON.stringify({width:16}));
 assert.deepEqual(await cachedJSON('/uncached.json'),{width:16});
});
