/** Source objects and authoritative source residents; no extra AI minds. */
import {loadActorFrames,drawActorFrame} from './actor-frames.js';
const graphics={OBJ_EVENT_GFX_CUT_TREE:'cut_tree',OBJ_EVENT_GFX_PUSHABLE_BOULDER:'strength_boulder',OBJ_EVENT_GFX_SNORLAX:'snorlax',OBJ_EVENT_GFX_ITEM_BALL:'item_ball',OBJ_EVENT_GFX_FOSSIL:'fossil',OBJ_EVENT_GFX_ARTICUNO:'articuno',OBJ_EVENT_GFX_ZAPDOS:'zapdos',OBJ_EVENT_GFX_MEWTWO:'mewtwo'};
const legends=new Set(['articuno','zapdos','mewtwo']);
export function environmentalObjects(map,{human=null,worldFacts=null}={}){
 const name=map.map_name,field=human?.field||{},out=[];
 for(const [index,obj] of (map.events?.object_events||[]).entries()){
  const sprite=graphics[obj.graphics_id];if(!sprite)continue;
  const key=`${name}:${obj.local_id??index}`,flag=String(obj.flag||'');
  if(sprite==='cut_tree'&&field.cut?.includes(key))continue;
  if(sprite==='snorlax'&&field.snorlax_cleared?.includes(key))continue;
  if(sprite==='strength_boulder'){
   if(field.fallen_boulders?.includes(key))continue;
   const hidden=['FLAG_HIDE_SEAFOAM_B1F','FLAG_HIDE_SEAFOAM_B2F','FLAG_HIDE_SEAFOAM_B4F'].some(p=>flag.startsWith(p))||['FLAG_HIDE_SEAFOAM_B3F_BOULDER_1','FLAG_HIDE_SEAFOAM_B3F_BOULDER_2'].includes(flag);
   if(hidden&&!field.revealed_boulders?.includes(flag))continue;
  }
  if(sprite==='fossil'&&name==='MtMoon_B2F'&&human?.acquisition?.fossil_choice)continue;
  if(sprite==='fossil'&&name==='PewterCity_Museum_1F'&&human?.acquisition?.claims?.includes('old_amber'))continue;
  if(sprite==='item_ball'){
   if(name==='PowerPlant'&&/EventScript_Electrode[12]$/.test(obj.script||'')&&field.electrode_cleared?.includes(obj.script.split('_').at(-1).toLowerCase()))continue;
   if(human?.collected_source_items?.includes(`${key}:${obj.script}`))continue;
   if(name==='CeladonCity_Condominiums_RoofRoom'&&human?.source_gifts?.includes('eevee')&&String(obj.script).includes('Eevee'))continue;
   if(name==='SaffronCity_Dojo'&&human?.source_gifts?.includes('dojo_hitmon')&&/Hitmonlee|Hitmonchan/.test(obj.script||''))continue;
  }
  if(legends.has(sprite)){
   if(!worldFacts?.static_encounters)continue;
   const claim=worldFacts.static_encounters[sprite];if(claim&&claim.status!=='available')continue;
  }
  const [x,y]=sprite==='strength_boulder'?(field.boulders?.[key]||[obj.x,obj.y]):[obj.x,obj.y];
  out.push({key,sprite,x,y,source:obj});
 }
 return out.sort((a,b)=>a.y-b.y||a.x-b.x);
}
export function sourceResidents(map,{npcs=null,worldFacts=null,humans=null}={}){
 const actors=npcs??worldFacts?.source_npcs??[];
 const occupied=Object.values(humans||{}).filter(h=>h.map_id===map.map_name);
 return (Array.isArray(actors)?actors:Object.values(actors)).filter(n=>n.map_id===map.map_name&&!n.linked_human&&(n.kind==='source_resident'||n.source_kind==='source_npc')&&!occupied.some(h=>h.x===n.x&&h.y===n.y)).map(n=>({...n,sprite:n.appearance?.sprite??n.sprite}));
}
function firstFrame(actor){
 const chosen=actor.metadata.anims.ANIM_STD_FACE_SOUTH?.frames?.[0]||Object.values(actor.metadata.anims).find(a=>a.frames?.length)?.frames[0];
 const frame=actor.metadata.pic_frames.find(f=>f.frame===(chosen?.frame??0));if(!frame)return null;
 const stem=frame.sheet.replace('gObjectEventPic_','').toLowerCase();
 const sheet=actor.metadata.sheets.find(s=>s.source_png?.replace(/.*\//,'').replace('.png','').replaceAll('_','')===stem||s.copied_png.includes(frame.sheet.toLowerCase()));if(!sheet)return null;
 const image=actor.sheets.get(sheet.copied_png),width=frame.grid_width*8,height=frame.grid_height*8;
 const index=actor.metadata.pic_frames.filter(f=>f.sheet===frame.sheet).findIndex(f=>f.frame===frame.frame),columns=Math.floor(image.width/width);
 return {image,width,height,sx:index%columns*width,sy:Math.floor(index/columns)*height};
}
export function createFieldObjectRenderer({onReady=()=>{}}={}){
 const ready=new Map(),pending=new Set(),failed=new Set();
 return {draw(ctx,map,{human=null,worldFacts=null,cellSize=16,skipKeys=[],npcs=null,humans=null}={}){
  for(const npc of sourceResidents(map,{npcs,worldFacts,humans})){
   const slug=npc.sprite;if(!slug)continue;
   if(!ready.has(slug)){if(!pending.has(slug)&&!failed.has(slug)){pending.add(slug);loadActorFrames(slug).then(actor=>{ready.set(slug,{actor});pending.delete(slug);onReady()}).catch(()=>{pending.delete(slug);failed.add(slug)})}continue;}
   const loaded=ready.get(slug);if(loaded?.actor)drawActorFrame(ctx,loaded.actor,{x:npc.x*cellSize,y:npc.y*cellSize,facing:npc.facing||'south',moving:false,scale:cellSize/16});
  }
  for(const obj of environmentalObjects(map,{human,worldFacts})){
   if(skipKeys.includes(obj.key))continue;
   if(!ready.has(obj.sprite)){
    if(!pending.has(obj.sprite)&&!failed.has(obj.sprite)){pending.add(obj.sprite);loadActorFrames(obj.sprite).then(actor=>{ready.set(obj.sprite,firstFrame(actor));pending.delete(obj.sprite);onReady()}).catch(()=>{pending.delete(obj.sprite);failed.add(obj.sprite)})}
    continue;
   }
   const f=ready.get(obj.sprite);if(!f)continue;
   const scale=cellSize/16;ctx.drawImage(f.image,f.sx,f.sy,f.width,f.height,obj.x*cellSize+cellSize/2-f.width*scale/2,(obj.y+1)*cellSize-f.height*scale,f.width*scale,f.height*scale);
  }
 },unavailable(){return [...failed]}};
}
