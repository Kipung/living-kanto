/** Display only canonical tile paths. Never infer a route from two positions. */
const same=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a[0]===b[0]&&a[1]===b[1];
export function joinRecordedPaths(paths){
 const joined=new Map();
 for(const path of paths){
  if(!path?.human_id||!path.map_id||!Array.isArray(path.points)||path.points.length<2||path.points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)))continue;
  const previous=joined.get(path.human_id);
  if(previous?.map_id===path.map_id&&same(previous.points.at(-1),path.points[0]))previous.points.push(...path.points.slice(1));
  else joined.set(path.human_id,{...path,points:path.points.map(p=>p.slice())});
 }
 return [...joined.values()];
}
export function recordedEventPaths(event){
 const inputs=event.deterministic_inputs||{},routes=Array.isArray(inputs.routes)?inputs.routes:[],out=[];
 for(const entry of routes){const route=entry.route||entry;if(entry.human_id&&route.map_id&&route.start&&route.steps?.length)out.push({human_id:entry.human_id,map_id:route.map_id,points:[route.start,...route.steps]});}
 const legacy=inputs.route,id=event.causation?.human_id;
 if(legacy&&id){
  const segments=legacy.journey||[legacy];
  for(const segment of segments)if(segment.map_id&&segment.start&&segment.steps?.length)out.push({human_id:id,map_id:segment.map_id,points:[segment.start,...segment.steps]});
 }
 return out;
}
export function matchingCurrentPaths(events,inspectHuman){
 return joinRecordedPaths(events.flatMap(recordedEventPaths)).filter(path=>{const h=inspectHuman(path.human_id);return h&&h.map_id===path.map_id&&same(path.points.at(-1),[h.x,h.y]);});
}
