export function followGridLayout(count,width,height){
 count=Math.max(1,count);let best;
 for(let columns=1;columns<=Math.min(count,Math.max(1,Math.floor(width/72)));columns++){
  const rows=Math.ceil(count/columns),tileWidth=(width-(columns-1)*4)/columns,tileHeight=Math.floor((height-(rows-1)*4)/rows),mapHeight=tileHeight-42;
  const score=Math.min(tileWidth,mapHeight*1.7)-Math.abs(tileWidth-mapHeight*1.7)*.08-(width>=800&&tileHeight<76?10000:0);
  if(!best||score>best.score)best={columns,rows,tileWidth,tileHeight,mapHeight,score};
 }
 return {...best,tileHeight:Math.max(76,best.tileHeight),mapHeight:Math.max(34,best.mapHeight)};
}
export function followingCamera({width,height,cell,x,y,mapWidth,mapHeight}){
 const zoom=Math.min(3,Math.max(.35,Math.min(width/(8*cell),height/(5*cell))));
 const clamp=(position,span,size)=>span<=size?(size-span)/2:Math.max(size-span,Math.min(0,position));
 return {zoom,x:clamp(width/2-(x+.5)*cell*zoom,mapWidth*cell*zoom,width),y:clamp(height/2-(y+.5)*cell*zoom,mapHeight*cell*zoom,height)};
}
export function locationTitle(row,fallback='Unknown location'){return row?.title||fallback;}
export function observedMapChanges(previous,next){
 if(!previous)return [];
 return Object.values(next?.humans||{}).flatMap(h=>{
  const before=previous.humans?.[h.human_id];
  return before?.map_id&&h.map_id&&before.map_id!==h.map_id?[{human_id:h.human_id,from:before.map_id,to:h.map_id,at:next.simulated_time,version:next.state_version}]:[];
 });
}
