import {nativeFlashRadius} from './native-field-sprites.mjs';
/** Visual receipts only; no moves, permissions or puzzle facts are changed. */
const directions={north:[0,-1],south:[0,1],east:[1,0],west:[-1,0]};
const moves={cut:['cut','✂️','Cut'],surf:['surf','🌊','Surf'],stop_surf:['surf','🌊','Leaving water'],push_boulder:['strength','🪨','Strength'],flash:['flash','✨','Flash'],fly_to:['fly','🪽','Fly'],ride_bicycle:['bike','🚲','Cycling'],dismount_bicycle:['bike','🚲','Dismounting']};
export function advanceReceiptPositions(event,positions){
 for(const c of event.transaction?.changes||[]){const m=/^humans\.([^.]+)\.(map_id|x|y|facing)$/.exec(c.path||'');if(m&&c.op==='set'){const p={...positions.get(m[1])};p[m[2]]=c.value;positions.set(m[1],p);}}
}
export function fieldActionEffects(event,{before,after}={}){
 const action=event.causation?.action,args=event.causation?.action_arguments||{},id=event.causation?.human_id;
 const spec=moves[action]||(action==='use_field_move'&&['DIG','TELEPORT'].includes(args.move)?['escape','✨',args.move==='DIG'?'Dig':'Teleport']:action==='use_field_item'&&args.item==='escape_rope'?['escape','✨','Escape Rope']:null);
 if(!spec||!id)return [];
 const source=event.before?.position||before,destination=event.after?.position||after;
 const objectId=args.object_id,objectMap=typeof objectId==='string'?objectId.split(':')[0]:null;
 const base={human_id:id,kind:spec[0],icon:spec[1],label:spec[2],detail:'Recent recorded '+spec[2]+' action',action,objectId,direction:args.direction};
 if(action==='cut'||action==='push_boulder'){
  const changes=event.transaction?.changes||[];let landing;
  for(const c of changes){if(c.path===`humans.${id}.field.boulders`)landing=c.value?.[objectId];if(c.path===`humans.${id}.field.boulders.${objectId}`)landing=c.value;}
  const d=directions[args.direction];const target=landing&&d?{x:landing[0]-d[0],y:landing[1]-d[1]}:null;
  return objectMap?[{...base,map_id:objectMap,position:target}]:[];
 }
 const result=[];
 if(source?.map_id&&Number.isFinite(source.x)&&Number.isFinite(source.y))result.push({...base,map_id:source.map_id,position:{x:source.x,y:source.y}});
 if(destination?.map_id&&Number.isFinite(destination.x)&&Number.isFinite(destination.y)&&(!source||destination.map_id!==source.map_id||destination.x!==source.x||destination.y!==source.y))result.push({...base,map_id:destination.map_id,position:{x:destination.x,y:destination.y}});
 return result;
}
export function fieldEffectPoint(effect,map){
 if(effect.map_id!==map.map_name)return null;
 if(effect.position)return effect.position;
 const object=(map.events?.object_events||[]).find((o,i)=>`${map.map_name}:${o.local_id??i}`===effect.objectId);
 return object?{x:object.x,y:object.y}:null;
}
export function drawFieldEffects(ctx,map,effects,{now,cellSize=16,reducedMotion=false,renderer}={}){
 let active=false;if(!renderer)return false;
 for(const e of effects){if(now>=e.until)continue;const p=fieldEffectPoint(e,map);if(!p)continue;const elapsed=now-e.start,tick=Math.floor(elapsed*60/1000),x=(p.x+.5)*cellSize,y=(p.y+.5)*cellSize,scale=cellSize/16;
  if(e.kind==='cut'){
   const desc=renderer.descriptor('cut_tree'),length=desc?.anims.default.frames.reduce((n,f)=>n+f.duration,0)||24;
   if(tick>=length+32||(!reducedMotion&&tick>=length&&(tick-length)%2))continue;
   active=renderer.draw(ctx,'cut_tree',{x,y,elapsedMs:elapsed,scale,hold:true,reducedMotion})||active;
  }else if(e.kind==='surf')active=renderer.draw(ctx,'splash',{x,y,elapsedMs:elapsed,scale,reducedMotion})||active;
  else if(e.kind==='strength'){
   if(tick>=16&&!reducedMotion)continue;const d=directions[e.direction]||[0,0],u=reducedMotion?1:Math.min(1,tick/16);
   active=renderer.draw(ctx,'strength_boulder',{x:x+d[0]*cellSize*u,y:y+d[1]*cellSize*u,elapsedMs:0,scale,hold:true,reducedMotion})||active;
  }else if(e.kind==='fly')active=renderer.draw(ctx,'fly',{x,y:y-(reducedMotion?0:Math.min(48,tick)*scale),elapsedMs:0,scale,hold:true,reducedMotion})||active;
  // Flash is the original visibility-window expansion below; escape/bicycle
  // use their authoritative position/avatar state, not fabricated particles.
 }
 return active;
}
export function drawTraversalAura(ctx,h,{x,y,cellSize=16,timeMs=0,moving=false,reducedMotion=false,renderer}={}){
 if(!renderer||(!h.status?.surfing&&!h.status?.source_forced_surfing))return false;
 renderer.draw(ctx,'surf',{x:x+cellSize/2,y:y+cellSize/2,elapsedMs:timeMs,scale:cellSize/16,direction:h.facing||'south',reducedMotion});return !reducedMotion;
}
export function drawFlashWindow(ctx,map,h,effects,{now,cellSize=16,reducedMotion=false}={}){
 if(!map.events?.requires_flash||!h||h.map_id!==map.map_name)return false;
 const recent=effects.find(e=>e.human_id===h.human_id&&e.kind==='flash'&&e.map_id===map.map_name&&now<e.until);
 let radius=h.field?.flash_active?200:24;if(recent&&!reducedMotion)radius=nativeFlashRadius(now-recent.start);
 if(radius>=200)return false;
 ctx.save();ctx.beginPath();ctx.rect(0,0,map.width*cellSize,map.height*cellSize);ctx.arc((h.x+.5)*cellSize,(h.y+.5)*cellSize,radius*cellSize/16,0,Math.PI*2,true);ctx.fillStyle='#000';ctx.fill('evenodd');ctx.restore();return !!recent;
}
export function drawMapBadge(ctx,indicator,{x,y,zoom=1,compact=false}={}){
 if(indicator.kind==='ready')return;
 const scale=1/Math.max(.2,zoom),label=compact?indicator.icon:indicator.icon+' '+indicator.label;
 ctx.save();ctx.translate(x,y-23);ctx.scale(scale,scale);ctx.font=(compact?'13':'12')+'px system-ui';const width=ctx.measureText(label).width+10;ctx.fillStyle='#13291ef0';ctx.fillRect(-width/2,-18,width,21);ctx.strokeStyle=indicator.recent?'#ebd18c':'#688773';ctx.lineWidth=1;ctx.strokeRect(-width/2,-18,width,21);ctx.fillStyle='#f2eed5';ctx.fillText(label,-width/2+5,-3);ctx.restore();
}
