/** Source-coordinate overview. Selection changes the observer camera only. */
export async function mountRegionOverview(container, {onSelect, getSelectedMap = () => null} = {}) {
 const response = await fetch('/content/region_overview.json');
 if (!response.ok) throw new Error('Region overview is unavailable');
 const data = await response.json();
 const sections = new Map(data.sections.map(s => [s.id,s]));
 const heading=document.createElement('p');heading.textContent='Explore Kanto · choose a place to view';
 const grid=document.createElement('div');
 Object.assign(grid.style,{display:'grid',gridTemplateColumns:`repeat(${data.width}, minmax(0,1fr))`,gap:'1px',width:'100%',aspectRatio:`${data.width}/${data.height}`,background:'#203849',padding:'4px',boxSizing:'border-box'});
 const list=document.createElement('select');list.setAttribute('aria-label','Maps in this region');list.style.maxWidth='100%';list.style.width='100%';
 const note=document.createElement('small');note.textContent=data.display_note;
 let selectedSection=null;
 function chooseSection(id,notify=true){
  selectedSection=id;const maps=data.maps.filter(m=>m.section_id===id);list.replaceChildren();
  const prompt=document.createElement('option');prompt.textContent=`View ${sections.get(id)?.name || 'place'}…`;prompt.value='';list.append(prompt);
  for(const m of maps){const o=document.createElement('option');o.value=m.map_id;o.textContent=m.map_id.replaceAll('_',' ').replace(/([a-z])([A-Z])/g,'$1 $2');list.append(o)}
  if(maps.length===1){list.value=maps[0].map_id;if(notify)onSelect?.(maps[0].map_id)}
  for(const b of grid.querySelectorAll('button'))b.style.outline=b.dataset.section===id?'2px solid #ffe680':'';
 }
 for(let y=0;y<data.height;y++)for(let x=0;x<data.width;x++){
  const id=data.layers.LAYER_MAP[y][x],dungeon=data.layers.LAYER_DUNGEON[y][x];
  const available=[id,dungeon].filter(k=>sections.has(k)&&data.maps.some(m=>m.section_id===k));
  if(!available.length){const e=document.createElement('span');e.style.background='#294858';grid.append(e);continue}
  const b=document.createElement('button');const sec=sections.get(available[0]);b.type='button';b.dataset.section=sec.id;b.title=available.map(k=>sections.get(k).name).join(' / ');b.setAttribute('aria-label',`View ${b.title}`);
  const city=/CITY|TOWN|ISLAND|PLATEAU/.test(sec.name)&&!/^ROUTE/.test(sec.name);
  Object.assign(b.style,{padding:'0',minWidth:'0',minHeight:'0',border:'0',borderRadius:city?'50%':'2px',background:city?'#ffd273':'#88b997',cursor:'pointer',fontSize:'8px',color:'#153024'});b.textContent=city?'●':available.length>1?'◆':'';
  b.onclick=()=>chooseSection(available[(available.indexOf(selectedSection)+1)%available.length]);grid.append(b);
 }
 list.onchange=()=>{if(list.value)onSelect?.(list.value)};
 container.replaceChildren(heading,grid,list,note);
 const current=data.maps.find(m=>m.map_id===getSelectedMap());if(current)chooseSection(current.section_id,false);
 return {selectMap(mapId){const m=data.maps.find(m=>m.map_id===mapId);if(m){chooseSection(m.section_id,false);list.value=mapId}},destroy(){container.replaceChildren()}};
}
