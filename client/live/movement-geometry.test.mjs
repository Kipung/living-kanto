import test from 'node:test';import assert from 'node:assert/strict';import {interpolateStep} from './movement-geometry.mjs';
test('ordinary recorded cardinal steps interpolate',()=>{assert.equal(interpolateStep([1,1],[2,1],.5).x,1.5)});
test('diagonal and distant updates snap rather than animate through walls',()=>{for(const p of [[2,2],[5,1],[3,1]])assert.equal(interpolateStep([1,1],p,.5).moving,false)});
test('only a matching source ledge enables the two-tile jump arc',()=>{
 const m={cells:[{x:2,y:1,behavior:0x38}]};assert.equal(interpolateStep([1,1],[3,1],.5,m).jumpOffset,-11);assert.equal(interpolateStep([3,1],[1,1],.5,m).moving,false);
});
