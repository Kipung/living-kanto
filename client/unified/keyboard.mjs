const directions={ArrowUp:'north',ArrowDown:'south',ArrowLeft:'west',ArrowRight:'east',w:'north',s:'south',a:'west',d:'east'};
export function shortcut(event,{mapFocused=false,playing=false}={}){
 if(event.ctrlKey||event.metaKey||event.altKey||event.repeat||event.isComposing)return null;
 if(event.target?.closest?.('input,textarea,select,[contenteditable="true"],dialog'))return null;
 const key=event.key.length===1?event.key.toLowerCase():event.key;
 if(mapFocused&&directions[key])return {type:playing?'move':'pan',direction:directions[key]};
 if(['1','2','3','4'].includes(key))return {type:'view',view:{1:'wall',2:'everyone',3:'area',4:'journeys'}[key]};
 if(['+','=','-','0'].includes(key))return {type:'camera',action:key==='0'?'fit':key==='-'?'out':'in'};
 if(key==='/')return {type:'search'};
 if(key==='f')return {type:'fullscreen'};
 if(key==='?')return {type:'help'};
 return null;
}
// One intent per press; never retry a mutation or queue stale movement commands.
export function createMovement({context,request,refresh,onMessage}){
 let pending=false;
 return async direction=>{
  const initial=context();if(pending||initial.view!=='area'||initial.selected!=='player'||initial.mode==='observer'||!initial.state?.humans?.player)return;
  if(initial.state.humans.player.battle_id){onMessage('You are in battle. Open Actions to choose your next move.');return;}
  pending=true;onMessage('Moving…');
  try{
   const world=initial.world,observation=await request('/runs/'+encodeURIComponent(world)+'/observations/player');
   const latest=context();if(latest.world!==world||latest.mode==='observer'||latest.view!=='area'||latest.selected!=='player')return;
   const legal=(observation.legal_actions||[]).find(a=>a.action==='walk_to'&&a.arguments?.direction===direction);
   if(!legal){onMessage('That way is blocked or you are busy. Open Actions for available choices.');return;}
   await request('/runs/'+encodeURIComponent(world)+'/player',{human_id:'player',expected_state_version:observation.observation_version,action:legal.action,arguments:legal.arguments});
   await refresh();onMessage('');
  }catch(error){onMessage(error.message+' · Try again once the map updates.');}
  finally{pending=false;}
 };
}
