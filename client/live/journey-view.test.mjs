import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {followGridLayout,followingCamera,observedMapChanges} from './journey-view.mjs';
const locations=JSON.parse(fs.readFileSync(new URL('../unified/locations.json',import.meta.url))).maps;
test('all 100 cameras fit desktop viewports without dropping anyone',()=>{
 for(const [width,height] of [[1900,840],[1424,660],[1264,560]]){
  const grid=followGridLayout(100,width,height);assert.ok(grid.columns*grid.rows>=100);assert.ok(grid.tileHeight*grid.rows+4*(grid.rows-1)<=height);assert.ok(grid.mapHeight>0);
 }
});
test('small screens keep usable cameras and allow scrolling instead of hiding people',()=>{
 const grid=followGridLayout(100,374,500);assert.ok(grid.tileHeight>=76);assert.ok(grid.columns*grid.rows>=100);
});
test('camera tracks the person and clamps at map edges',()=>{
 const args={width:180,height:110,cell:16,mapWidth:100,mapHeight:100};
 const first=followingCamera({...args,x:5,y:5}),next=followingCamera({...args,x:20,y:20});assert.ok(next.x<first.x);assert.ok(next.y<first.y);
 const edge=followingCamera({...args,x:0,y:0});assert.equal(edge.x,0);assert.equal(edge.y,0);
 const small=followingCamera({...args,mapWidth:2,mapHeight:2,x:0,y:0});assert.ok(small.x>0);assert.ok(small.y>0);
});
test('town navigation connects Pallet Town to the actual lab and house floors',()=>{
 const town=locations.find(row=>row.id==='PalletTown'),lab=locations.find(row=>row.id==='PalletTown_ProfessorOaksLab'),floor=locations.find(row=>row.id==='PalletTown_PlayersHouse_2F');
 assert.ok(town.links.some(row=>row.id===lab.id));assert.equal(lab.exterior,'PalletTown');assert.equal(lab.title,'Pallet Town › Professor Oak’s Lab');assert.match(floor.title,/Player’s House › Floor 2/);
 assert.ok(floor.links.some(row=>row.id==='PalletTown_PlayersHouse_1F'));
});
test('every navigation link points to a real map; buildings remain in their town',()=>{
 const ids=new Set(locations.map(row=>row.id));assert.equal(ids.size,locations.length);
 for(const row of locations){for(const link of row.links)assert.ok(ids.has(link.id));if(row.exterior)assert.ok(ids.has(row.exterior));assert.ok(row.title&&row.groupLabel);}
});
test('location trails reflect observed changes without inventing initial history',()=>{
 const next={state_version:5,simulated_time:12,humans:{a:{human_id:'a',map_id:'PalletTown_ProfessorOaksLab'},b:{human_id:'b',map_id:'Route1'}}};
 assert.deepEqual(observedMapChanges(null,next),[]);
 assert.deepEqual(observedMapChanges({humans:{a:{map_id:'PalletTown'},b:{map_id:'Route1'}}},next),[{human_id:'a',from:'PalletTown',to:'PalletTown_ProfessorOaksLab',at:12,version:5}]);
});
