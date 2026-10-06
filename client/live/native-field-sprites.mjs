/** Pinned FireRed source pixels, palette bindings and60Hz animation commands. */
export function nativeFrame(descriptor,elapsedMs,{direction='south',hold=false,reducedMotion=false}={}){
 const animation=descriptor?.anims?.[direction]||descriptor?.anims?.default;if(!animation?.frames?.length)return null;
 const period=animation.frames.reduce((n,f)=>n+f.duration,0);let tick=reducedMotion?0:Math.floor(Math.max(0,elapsedMs)*60/1000);
 if(animation.loops)tick%=period;else if(tick>=period){if(!hold)return null;tick=period-1;}
 for(const command of animation.frames){if(tick<command.duration){const frame=descriptor.frames.find(f=>f.frame===command.frame);return frame?{...frame,hFlip:!!command.hFlip,vFlip:!!command.vFlip}:null;}tick-=command.duration;}return null;
}
export function createNativeFieldRenderer({onReady=()=>{}}={}){
 let manifest=null;const images=new Map(),failed=new Set();
 fetch('/content/field_effects/manifest.json').then(r=>{if(!r.ok)throw Error('Original field sprite manifest unavailable');return r.json()}).then(data=>{manifest=data;for(const [name,descriptor] of Object.entries(data.effects)){const image=new Image();image.onload=()=>{images.set(name,image);onReady()};image.onerror=()=>failed.add(name);image.src=descriptor.image;}onReady()}).catch(()=>failed.add('manifest'));
 return {draw(ctx,name,{x,y,elapsedMs=0,scale=1,direction='south',hold=false,reducedMotion=false}={}){
  const descriptor=manifest?.effects[name],image=images.get(name),frame=nativeFrame(descriptor,elapsedMs,{direction,hold,reducedMotion});if(!image||!frame)return false;
  ctx.save();ctx.translate(x,y);ctx.scale(frame.hFlip?-scale:scale,frame.vFlip?-scale:scale);ctx.imageSmoothingEnabled=false;ctx.drawImage(image,frame.sx,frame.sy,frame.width,frame.height,-frame.width/2,-frame.height/2,frame.width,frame.height);ctx.restore();return true;
 },descriptor(name){return manifest?.effects[name]},unavailable(){return [...failed]}};
}
export function nativeFlashRadius(elapsedMs){return Math.min(200,24+Math.floor(Math.max(0,elapsedMs)*60/1000)*2);}
