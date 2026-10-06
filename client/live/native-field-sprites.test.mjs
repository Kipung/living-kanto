import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import crypto from 'node:crypto';
import {nativeFrame,nativeFlashRadius} from './native-field-sprites.mjs';
const manifest=JSON.parse(fs.readFileSync(new URL('../../content/field_effects/manifest.json',import.meta.url)));
test('all eight imported source sprites exist and retain their output digest',()=>{
 assert.equal(Object.keys(manifest.effects).length,8);for(const d of Object.values(manifest.effects)){
 const data=fs.readFileSync(new URL('../..'+d.image.replace('/content','/content'),import.meta.url));
 assert.equal(crypto.createHash('sha256').update(data).digest('hex'),d.output_sha256);
 }
});
test('native ripple uses source durations and ends instead of looping',()=>{
 const d=manifest.effects.ripple;assert.equal(nativeFrame(d,0).frame,0);assert.equal(nativeFrame(d,200).frame,1);
 const duration=d.anims.default.frames.reduce((n,f)=>n+f.duration,0);assert.equal(nativeFrame(d,duration*1000/60+1),null);
});
test('Surf loops its original 48-frame poses and east uses the source flip',()=>{
 const d=manifest.effects.surf;assert.equal(nativeFrame(d,0,{direction:'south'}).frame,0);assert.equal(nativeFrame(d,801,{direction:'south'}).frame,1);assert.equal(nativeFrame(d,1601,{direction:'south'}).frame,0);
 assert.equal(nativeFrame(d,0,{direction:'east'}).hFlip,true);assert.equal(nativeFrame(d,0,{direction:'west'}).hFlip,false);
});
test('reduced motion holds the first original pose; Flash follows source two-pixel increments',()=>{
 assert.deepEqual(nativeFrame(manifest.effects.surf,900,{reducedMotion:true}),nativeFrame(manifest.effects.surf,0));assert.equal(nativeFlashRadius(0),24);assert.equal(nativeFlashRadius(1000/60+1),26);assert.equal(nativeFlashRadius(2000),200);
});
