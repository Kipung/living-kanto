/** Original metatile images selected by engine-owned per-trainer puzzle facts. */
export function terrainPatches(map,human){
 const field=human?.field||{},patches=[];
 for(const door of map.events?.card_key_doors||[])patches.push(...door[(field.doors||[]).includes(door.id)?'opened':'closed']);
 for(const plate of map.events?.strength_switches||[])if(field.switches?.includes(plate.id))patches.push(...plate.barriers);
 const mansion=map.events?.mansion_switch;if(mansion)patches.push(...mansion[field.mansion_switch?'on':'off']);
 return patches.filter(p=>p.image);
}
export function seafoamLayout(map,human){
 const floor=map.map_name?.split('_').at(-1),revealed=human?.field?.revealed_boulders||[];
 if(['SeafoamIslands_B3F','SeafoamIslands_B4F'].includes(map.map_name)&&[1,2].every(n=>revealed.includes(`FLAG_HIDE_SEAFOAM_${floor}_BOULDER_${n}`)))return `/content/layouts/${map.map_name}.png`;
 return null;
}
export function createTerrainOverlayRenderer({onReady=()=>{}}={}){
 const images=new Map(),pending=new Set(),failed=new Set();
 function get(url){if(images.has(url))return images.get(url);if(!pending.has(url)&&!failed.has(url)){pending.add(url);const img=new Image();img.onload=()=>{images.set(url,img);pending.delete(url);onReady()};img.onerror=()=>{pending.delete(url);failed.add(url)};img.src=url}return null}
 return {draw(ctx,map,{human=null,cellSize=16}={}){
  const layout=seafoamLayout(map,human);if(layout){const image=get(layout);if(image)ctx.drawImage(image,0,0,map.width*cellSize,map.height*cellSize)}
  for(const patch of terrainPatches(map,human)){const image=get('/'+patch.image);if(image)ctx.drawImage(image,patch.x*cellSize,patch.y*cellSize,cellSize,cellSize)}
 },unavailable(){return [...failed]}};
}
