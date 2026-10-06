// Legitimate ledge jumps use the pinned DoJumpSpriteMovement high offsets.
const high=[-4,-6,-8,-10,-11,-12,-12,-12,-11,-10,-9,-8,-6,-4,0,0];
export function interpolateStep(from,to,u,map){
 const dx=to[0]-from[0],dy=to[1]-from[1],distance=Math.abs(dx)+Math.abs(dy);
 const cardinal=dx===0||dy===0;
 if(!cardinal||distance===0||distance>2)return {x:to[0],y:to[1],moving:false,jumpOffset:0};
 let jump=false;
 if(distance===2){
  const mx=from[0]+Math.sign(dx),my=from[1]+Math.sign(dy),cell=map?.cells?.find(c=>c.x===mx&&c.y===my);
  const behavior=dx>0?0x38:dx<0?0x39:dy<0?0x3A:0x3B;
  if(cell?.behavior!==behavior)return {x:to[0],y:to[1],moving:false,jumpOffset:0};jump=true;
 }
 return {x:from[0]+dx*u,y:from[1]+dy*u,moving:true,jumpOffset:jump?high[Math.min(15,Math.floor(Math.max(0,u)*16))]:0};
}
