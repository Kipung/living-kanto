import test from 'node:test';import assert from 'node:assert/strict';import {sourceResidents,createFieldObjectRenderer} from '../js/field-objects.js';
test('source residents follow authoritative map positions without AI duplicate',()=>{
 const map={map_name:'PalletTown'},npcs={a:{kind:'source_resident',map_id:'PalletTown',x:3,y:10,facing:'west',appearance:{sprite:'woman1'}},b:{kind:'source_resident',map_id:'Route1',appearance:{sprite:'boy'}},c:{kind:'source_resident',map_id:'PalletTown',linked_human:'human-1',appearance:{sprite:'nurse'}}};
 assert.deepEqual(sourceResidents(map,{npcs}).map(n=>[n.sprite,n.x,n.y,n.facing]),[['woman1',3,10,'west']]);
 assert.deepEqual(sourceResidents(map),[]);
});
test('preserved human at source origin hides resident until they step away',()=>{
 const map={map_name:'PalletTown'},npcs=[{kind:'source_resident',map_id:'PalletTown',x:3,y:10,appearance:{sprite:'woman1'}}];
 assert.equal(sourceResidents(map,{npcs,humans:{a:{map_id:'PalletTown',x:3,y:10}}}).length,0);
 assert.equal(sourceResidents(map,{npcs,humans:{a:{map_id:'PalletTown',x:4,y:10}}}).length,1);
});
