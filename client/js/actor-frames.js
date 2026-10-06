import {cachedJSON,cachedImage} from './artwork-cache.mjs';
/** Original source animation descriptors; no estimated frame numbering. */
const actors=new Map();
export async function loadActorFrames(slug){
 if(actors.has(slug))return actors.get(slug);
 const promise=cachedJSON('/content/actors/'+encodeURIComponent(slug)+'.json').then(async metadata=>{
  const sheets=new Map();await Promise.all(metadata.sheets.map(async sheet=>{const image=await cachedImage('/'+sheet.copied_png);sheets.set(sheet.copied_png,image)}));return {metadata,sheets};
 });actors.set(slug,promise);return promise;
}
export function drawActorFrame(ctx,actor,{x,y,facing='south',moving=false,timeMs=0,scale=1}){
 const key='ANIM_STD_'+(moving?'GO_':'FACE_')+facing.toUpperCase();const animation=actor.metadata.anims[key];if(!animation?.frames?.length)return false;
 const frames=animation.frames,period=frames.reduce((n,f)=>n+f.duration,0);let clock=Math.floor(timeMs*60/1000)%period,chosen=frames[0];for(const f of frames){chosen=f;if(clock<f.duration)break;clock-=f.duration}
 const frame=actor.metadata.pic_frames.find(f=>f.frame===chosen.frame);if(!frame)return false;
 const sheet=actor.metadata.sheets.find(s=>s.source_png?.replace(/.*\//,'').replace('.png','').replaceAll('_','')===frame.sheet.replace('gObjectEventPic_','').toLowerCase() || s.copied_png.includes(frame.sheet.toLowerCase()));if(!sheet)return false;
 const image=actor.sheets.get(sheet.copied_png),width=frame.grid_width*8,height=frame.grid_height*8,localIndex=actor.metadata.pic_frames.filter(f=>f.sheet===frame.sheet).findIndex(f=>f.frame===frame.frame),columns=Math.floor(image.width/width),sx=(localIndex%columns)*width,sy=Math.floor(localIndex/columns)*height;
 ctx.save();ctx.translate(x+(chosen.hFlip?width*scale:0),y-height*scale+16*scale);ctx.scale(chosen.hFlip?-scale:scale,chosen.vFlip?-scale:scale);ctx.drawImage(image,sx,sy,width,height,0,0,width,height);ctx.restore();return true;
}
