import {loadActorFrames,drawActorFrame} from '/client/js/actor-frames.js';
import {createFieldObjectRenderer} from '/client/js/field-objects.js';
import {createTerrainOverlayRenderer} from '/client/js/terrain-overlays.js';
import {place,actorId,eventActors,routeSegments,clockOnly,sharedClockLabel,worldProgress,activity,eventText,battleMessages,groupByMap,walkingDuration} from './model.mjs?v=world-progress-1';
const $=id=>document.getElementById(id),M=window.Maps,canvas=$('scene');
const actors=new Map(),pendingActors=new Set(),motions=new Map(),effects=new Map(),battleVersions=new Map();
const field=createFieldObjectRenderer({onReady:draw}),terrain=createTerrainOverlayRenderer({onReady:draw});
let state=null,world='',status='paused',selected=null,following=false,spotlight=false,view='everyone',smooth=true,fitPeople=true,socket=null,generation=0,cursor=-1,events=[],frame=null,lastFrame=0,replaying=false,loadingMap=null,reconnect=null,refreshing=false,runtimeInfo=null,runtimeQuery=0;
async function get(path){const response=await fetch(path,{signal:AbortSignal.timeout(45000)});const d=await response.json();if(!response.ok)throw Error(d.detail||'Could not read world');return d;}
function fail(error){$('error').textContent=error.message||String(error);}
function humans(){return Object.values(state?.humans||{});}
function humanName(id){return state?.humans?.[id]?.name||(String(id).startsWith('wild')?'Wild Pokémon':id||'World');}
function make(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function motionPosition(h,now=performance.now()){
 const q=motions.get(h.human_id);if(!q?.length)return {...h,moving:false};
 while(q.length){const a=q[0];a.start??=now;const t=(now-a.start)/a.duration;
  if(t>=1){q.shift();if(q[0])q[0].start=a.start+a.duration;continue;}
  const n=Math.max(0,t)*(a.points.length-1),i=Math.min(a.points.length-2,Math.floor(n)),u=n-i,p=a.points[i],next=a.points[i+1];
  return {...h,map_id:a.map,x:p[0]+(next[0]-p[0])*u,y:p[1]+(next[1]-p[1])*u,facing:next[0]>p[0]?'east':next[0]<p[0]?'west':next[1]>p[1]?'south':'north',moving:true};
 }
 motions.delete(h.human_id);if(replaying&&!motions.size){replaying=false;updateStatus();}return {...h,moving:false};
}
function animate(event,{saved=false}={}){
 let changed=false;const now=performance.now();for(const id of eventActors(event)){
  const segments=routeSegments(event,id);if(!state?.humans?.[id]||!segments.length)continue;
  const q=motions.get(id)||[];for(const segment of segments)q.push({...segment,duration:event.event_kind==='world.shared_tick'?Math.max(30,1000*(event.deterministic_inputs?.shared_time?.elapsed||1)/(Number(runtimeInfo?.speed)||(runtimeInfo?.actual_simulated_seconds_per_wall_second>0?runtimeInfo.actual_simulated_seconds_per_wall_second:1))):walkingDuration(segment.points,{smooth}),start:q.length?null:now});
  if(q.length>12)q.splice(0,q.length-12);motions.set(id,q);changed=true;
 }
 if(changed){if(saved)replaying=true;ensureFrame();}return changed;
}
function ingest(incoming,{initial=false}={}){
 if(replaying&&!initial&&(incoming||[]).some(e=>e.event_index>cursor)){motions.clear();replaying=false;}
 const map=new Map(events.map(e=>[e.event_index,e]));
 for(const e of incoming||[]){if(e.event_index>=state.state_version)continue;map.set(e.event_index,e);
  if(!initial&&e.event_index>cursor){animate(e);const id=actorId(e),action=e.causation?.action;
   if(state.humans[id]&&action&&e.event_kind!=='world.shared_tick'){effects.set(id,{action,text:action==='talk_to'?e.causation?.action_arguments?.text:null,until:performance.now()+6500});if(spotlight)select(id,true);}
  }
  cursor=Math.max(cursor,e.event_index);
 }
 const ordered=[...map.values()].sort((a,b)=>a.event_index-b.event_index);const keep=new Set([...ordered.filter(e=>!clockOnly(e)).slice(-80),...ordered.filter(clockOnly).slice(-80)]);events=ordered.filter(e=>keep.has(e));renderFeed();ensureFrame();
}
function accept(d){if(!d.state||d.state.state_version<(state?.state_version??-1))return;state=d.state;status=d.status||status;updateStatus();renderPeople();renderPerson();renderBattles();renderOverview();draw();}
function updateStatus(){
 const progress=worldProgress(state,runtimeInfo,status);for(const [id,value] of Object.entries({worldtime:progress.time,worldupdates:progress.updates,worlddecisions:progress.decisions,worldspeed:progress.clock,worldthinking:progress.thinking}))$(id).textContent=value;
 $('controls').href='/?world='+encodeURIComponent(world);
 if(!state){$('connection').textContent=world?'Reading saved world…':'Choose a saved world';$('notice').textContent=world?'Loading saved facts. Longer histories can take a moment to verify.':'';$('population').textContent='';$('replaywalk').disabled=true;return;}
 $('connection').textContent=world?(socket?.readyState===1?'Connected · ':'')+status+' · '+(runtimeInfo?.clock_mode==='shared'?'shared time ':'world time ')+(state?.simulated_time||0)+'s'+(state?.world_facts?.creative_modified?' · Creative history':''):'Choose a saved world';
 $('notice').textContent=runtimeInfo?.clock_mode==='shared'&&!replaying&&status!=='paused'?humans().filter(h=>h.movement_intent&&!h.battle_id&&!h.movement_intent.paused_for_battle).length+' people moving · '+(runtimeInfo.queue_depth||0)+' thinking locally · '+(runtimeInfo.ready_queue_depth||0)+' ready · one shared clock · '+sharedClockLabel(runtimeInfo):replaying?'REPLAYING A SAVED WALK · current world facts remain unchanged':status==='paused'?'World paused. This page does not resume it. Use World controls to run AI; Replay last walk lets you watch a real recorded journey.':'Live accepted decisions · '+(smooth?'walking plays smoothly and can lag behind the latest saved position. ':'')+'AI thinking and idle time still create gaps; no extra actions are invented.';
 $('population').textContent=humans().filter(h=>h.human_id!=='player').length+' AI people';
 $('replaywalk').disabled=!events.some(e=>routeSegments(e).length);
 $('controls').href='/?world='+encodeURIComponent(world);
}
async function loadWorld(id){
 const g=++generation;world=id;socket?.close();socket=null;clearTimeout(reconnect);state=null;runtimeInfo=null;selected=null;cursor=-1;events=[];motions.clear();effects.clear();replaying=false;battleVersions.clear();$('error').textContent='';for(const id of ['people','feed','battles','persondetail'])$(id).replaceChildren();$('now').textContent='Reading saved facts…';canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);overviewCards.clear();areaPanels.clear();$('everyone').replaceChildren();$('areas').replaceChildren();
 const url=new URL(location.href);url.searchParams.set('world',id);history.replaceState(null,'',url);updateStatus();if(!id)return;
 try{const d=await get('/runs/'+encodeURIComponent(id));if(g!==generation)return;accept(d);const historyData=await get('/runs/'+encodeURIComponent(id)+'/events?after='+Math.max(-1,state.state_version-401));if(g!==generation)return;
  ingest(Array.isArray(historyData)?historyData:historyData.events,{initial:true});cursor=state.state_version-1;
  select(state.humans.player?'player':actorId([...events].reverse().find(e=>state.humans[actorId(e)])||{})||humans()[0]?.human_id,false);connect(g);updateStatus();
 }catch(error){if(g===generation){fail(error);reconnect=setTimeout(()=>loadWorld(id),4000);}}
}
function connect(g){
 if(g!==generation||!world)return;const id=world;
 socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/'+encodeURIComponent(id)+'?after='+cursor);
 socket.onopen=()=>{if(g===generation){$('error').textContent='';updateStatus();}};
 socket.onmessage=message=>{if(g!==generation)return;try{const d=JSON.parse(message.data);if(d.type==='error')throw Error(d.detail);if(d.state){accept(d);ingest(d.events);renderPeople();renderPerson();updateStatus();}}catch(error){fail(error);}};
 socket.onclose=()=>{if(g!==generation)return;updateStatus();reconnect=setTimeout(()=>connect(g),4000);};
}
async function map(name){if(!name||name===M.state.name||name===loadingMap)return;loadingMap=name;try{await M.loadMap(name);if(M.state.name!==name)return;$('location').value=name;$('mapname').textContent=place(name);fit();draw();}catch(error){fail(error);}finally{if(loadingMap===name)loadingMap=null;}}
function fit(){if(!M.state.img)return;const v=M.state.view;const fitted=Math.max(.25,Math.min(3,canvas.width/M.state.img.width*.92,canvas.height/M.state.img.height*.92));v.zoom=following?Math.max(1.8,fitted):fitted;v.x=(canvas.width-M.state.img.width*v.zoom)/2;v.y=(canvas.height-M.state.img.height*v.zoom)/2;}
function camera(h){const v=M.state.view,z=v.zoom,w=M.state.img.width*z,height=M.state.img.height*z;v.x=w<=canvas.width?(canvas.width-w)/2:Math.max(canvas.width-w,Math.min(0,canvas.width/2-(h.x*M.state.cell+8)*z));v.y=height<=canvas.height?(canvas.height-height)/2:Math.max(canvas.height-height,Math.min(0,canvas.height/2-h.y*M.state.cell*z));}
function resize(){const box=canvas.parentElement.getBoundingClientRect();canvas.width=Math.round(box.width);canvas.height=Math.round(box.height);fit();draw();}
function select(id,follow=following){if(!state?.humans[id])return;selected=id;following=follow&&view==='area';$('follow').setAttribute('aria-pressed',String(following));const h=motionPosition(state.humans[id]);map(h.map_id);renderPerson();renderPeople();draw();}
function renderPeople(){const search=$('search').value.toLowerCase();$('people').replaceChildren();for(const h of humans().filter(h=>[h.name,place(h.map_id),activity(h,state,runtimeInfo).label,h.role].join(' ').toLowerCase().includes(search)).sort((a,b)=>(b.human_id===selected)-(a.human_id===selected)||(activity(a,state,runtimeInfo).kind==='ready')-(activity(b,state,runtimeInfo).kind==='ready')||a.name.localeCompare(b.name))){const a=activity(h,state,runtimeInfo),button=make('button',undefined,'person-button');button.append(make('strong',h.name),make('span',a.icon+' '+a.label),make('span',place(h.map_id)));button.setAttribute('aria-pressed',String(h.human_id===selected));button.onclick=()=>select(h.human_id,following);$('people').append(button);}}
function renderPerson(){const h=state?.humans?.[selected];$('personname').textContent=h?humanName(selected):'Choose someone to follow';if(!h){$('persondetail').textContent='';return;}const a=activity(h,state,runtimeInfo);$('persondetail').textContent=[a.icon+' '+a.label,place(h.map_id),'Goal: '+(typeof h.goal==='string'?(h.goal||'None recorded'):h.goal?.text||h.goal?.description||'None recorded'),'Badges: '+((h.badges||[]).join(', ')||'none'),'Party: '+(h.party||[]).map(id=>{const p=state.pokemon[id];return p?p.species+' Lv '+p.level+' · HP '+p.hp+'/'+p.stats.hp:id;}).join(' · ')].join('\n');}
function renderFeed(){$('feed').replaceChildren();for(const e of [...events].filter(e=>!clockOnly(e)).reverse().slice(0,35)){const id=actorId(e),b=make('button');b.append(make('strong',eventText(e,state.humans)),make('span','#'+e.event_index+' · '+Math.floor((e.simulated_time||0)/60)+' simulated min','event-time'));const quote=e.causation?.action==='talk_to'?e.causation?.action_arguments?.text:null;if(quote)b.append(make('span','“'+String(quote).slice(0,240)+'”','quote'));b.disabled=!state.humans[id];b.onclick=()=>select(id,following);$('feed').append(b);}}
function renderBattles(){
 const box=$('battles');box.replaceChildren();const records=Object.entries(state.world_facts?.battles||{});const active=records.filter(([,b])=>!b.outcome&&!b.session?.result?.ended);const showing=active.length?active:records.slice(-3);
 if(!showing.length){box.append(make('p','No battles recorded in this world yet.','hint'));return;}
 for(const [id,b] of showing){const section=make('article',undefined,'battle');const stamp=JSON.stringify([b.turn,b.outcome,b.session?.result?.log?.length]);if(battleVersions.has(id)&&battleVersions.get(id)!==stamp)section.classList.add('changed');battleVersions.set(id,stamp);
  section.append(make('h3',humanName(b.challenger)+' vs '+humanName(b.opponent)+' · turn '+b.turn+(b.outcome?' · completed':' · in progress')));
  const fighters=make('div',undefined,'fighters'),session=b.session,results=session?.result?.pokemon||[];
  for(const team of session?.teams||[]){const own=results.filter(p=>p.owner_id===team.actor_id),req=session.result?.observations?.[team.actor_id]?.request?.side?.pokemon||[];let mons=req.flatMap((r,i)=>r.active?[team.party.find(p=>p.pokemon_id===own[i]?.pokemon_id)]:[]).filter(Boolean);if(!mons.length)mons=[team.party.find(p=>results.find(r=>r.pokemon_id===p.pokemon_id)?.hp>0)||team.party[0]].filter(Boolean);
   for(const mon of mons){const p=results.find(r=>r.pokemon_id===mon.pokemon_id)||mon,max=p.max_hp||mon.stats?.hp||1,row=make('div',undefined,'fighter'),img=make('img');img.src='/content/pokemon/'+mon.species.toLowerCase().replaceAll(' ','_').replaceAll('-','_')+'_front.png';img.alt=mon.species;row.append(img,make('strong',humanName(team.actor_id)),make('span',mon.species+' · Lv '+mon.level));const hp=make('div',undefined,'hp'),bar=make('i');bar.style.width=Math.max(0,Math.min(100,p.hp/max*100))+'%';hp.append(bar);row.append(hp,make('span','HP '+p.hp+'/'+max+(p.status?' · '+p.status:'')));fighters.append(row);}
  }
  section.append(fighters);const log=make('div',undefined,'turns');for(const message of battleMessages(session?.result?.log||[],(session?.teams||[]).map(t=>humanName(t.actor_id)),Object.fromEntries(humans().map(h=>[h.human_id,h.name]))).slice(-10))log.append(make('div',message.text,message.type==='move'?'move':''));section.append(log);box.append(section);
 }
}
function draw(now=performance.now()){
 if(state&&view!=='area'){drawOverview(now);if(motions.size||effects.size)ensureFrame();return;}
 if(!state||!M.state.img){M.draw(canvas);return;}const focused=state.humans[selected]?motionPosition(state.humans[selected],now):null;
 if(following&&focused){if(focused.map_id!==M.state.name){map(focused.map_id);}else camera(focused);}
 M.draw(canvas);const ctx=canvas.getContext('2d'),v=M.state.view;ctx.save();ctx.setTransform(v.zoom,0,0,v.zoom,v.x,v.y);ctx.imageSmoothingEnabled=false;
 const facts=state.humans[selected];terrain.draw(ctx,M.state.json,{human:facts,cellSize:M.state.cell});field.draw(ctx,M.state.json,{human:facts,worldFacts:state.world_facts,cellSize:M.state.cell});
 const placedLabels=[];for(const h of humans().sort((a,b)=>(b.human_id===selected)-(a.human_id===selected))){const p=motionPosition(h,now);if(p.map_id!==M.state.name)continue;const slug=h.appearance?.sprite||'red_normal';if(!actors.has(slug)&&!pendingActors.has(slug)){pendingActors.add(slug);loadActorFrames(slug).then(a=>{actors.set(slug,a);draw();}).catch(()=>{});}
  const x=p.x*M.state.cell,y=p.y*M.state.cell,actor=actors.get(slug);if(actor)drawActorFrame(ctx,actor,{x,y,facing:p.facing,moving:p.moving,timeMs:now});
  const a=activity(h,state,runtimeInfo),effect=effects.get(h.human_id);if(effect?.until<now)effects.delete(h.human_id);
  const label=effect?.until>now&&effect.text?'💬 '+String(effect.text).slice(0,28):p.moving?'➜ Walking':a.kind!=='ready'?a.icon+' '+a.label.split(' · ')[0]:h.human_id===selected?h.name:null;
  if(label){ctx.font='7px system-ui';const width=ctx.measureText(label).width+8,lx=x+8-width/2;let ly=y-28,tries=0;const collides=()=>placedLabels.some(r=>lx<r.x+r.w&&lx+width>r.x&&ly<r.y+12&&ly+12>r.y);while(collides()&&tries++<6)ly-=13;if(!collides()){placedLabels.push({x:lx,y:ly,w:width});ctx.fillStyle='rgba(14,30,20,.9)';ctx.fillRect(lx,ly,width,11);ctx.fillStyle=effect?.text?'#ffdfa0':'#edf4de';ctx.fillText(label,lx+4,ly+8);}}
  if(h.human_id===selected){ctx.strokeStyle='#ffe19b';ctx.lineWidth=1/v.zoom;ctx.strokeRect(x-1,y-18,18,35);}
 }
 ctx.restore();$('now').textContent=replaying?'Saved walking route · visual replay only':focused?.moving?humanName(selected)+' is walking through '+place(focused.map_id):focused?humanName(selected)+' · '+activity(state.humans[selected],state,runtimeInfo).label+(status==='paused'?' · world paused':''):status==='paused'?'World paused':'Watching live activity';
 if(motions.size||effects.size)ensureFrame();
}
function ensureFrame(){if(frame!==null)return;frame=requestAnimationFrame(t=>{frame=null;if(t-lastFrame<32){ensureFrame();return;}lastFrame=t;draw(t);});}
const overviewCards=new Map(),areaPanels=new Map(),mapAssets=new Map(),assetQueue=[];let assetLoads=0;
function setView(value){view=value;document.body.classList.toggle('fit-people',value==='everyone'&&fitPeople);$('fitpeople').hidden=value!=='everyone';document.body.dataset.view=value;$('view').value=value;$('overview').hidden=value==='area';document.querySelector('.scene').hidden=value!=='area';$('everyone').hidden=value!=='everyone';$('areas').hidden=value!=='wall';$('overviewtitle').textContent=value==='wall'?'All occupied areas':'Everyone together';if(value!=='area'){following=false;spotlight=false;$('follow').setAttribute('aria-pressed','false');$('spotlight').setAttribute('aria-pressed','false');}else resize();if(state){renderOverview();draw();}}
function getActor(h){const slug=h.appearance?.sprite||'red_normal';if(!actors.has(slug)&&!pendingActors.has(slug)){pendingActors.add(slug);loadActorFrames(slug).then(a=>{actors.set(slug,a);draw();}).catch(()=>{});}return actors.get(slug);}
function renderOverview(){
 if(!state)return;const ids=new Set(humans().map(h=>h.human_id));for(const [id,row] of overviewCards)if(!ids.has(id)){row.button.remove();overviewCards.delete(id);}
 for(const h of humans().sort((a,b)=>a.human_id.localeCompare(b.human_id))){if(overviewCards.has(h.human_id))continue;const button=make('button',undefined,'overview-person'),portrait=make('canvas'),name=make('strong',h.name),label=make('span',undefined,'activity'),location=make('small');portrait.width=48;portrait.height=48;portrait.setAttribute('aria-hidden','true');button.append(portrait,name,label,location);button.onclick=()=>select(h.human_id,false);$('everyone').append(button);overviewCards.set(h.human_id,{button,portrait,label,location});}
 $('overviewcount').textContent=humans().length+' people · all included';if(view!=='area')drawOverview(performance.now());
}
function requestMapAsset(id){if(mapAssets.has(id))return;mapAssets.set(id,null);assetQueue.push(id);drainAssetQueue();}
function drainAssetQueue(){while(assetLoads<4&&assetQueue.length){const id=assetQueue.shift();assetLoads++;Promise.all([get('/content/maps/'+encodeURIComponent(id)+'.json'),new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=reject;img.src='/content/maps/'+encodeURIComponent(id)+'.png';})]).then(([meta,image])=>{mapAssets.set(id,{meta,image,cell:image.width/meta.width});draw();}).catch(()=>mapAssets.set(id,{failed:true})).finally(()=>{assetLoads--;drainAssetQueue();});}}
function ensureArea(id){if(areaPanels.has(id))return areaPanels.get(id);const panel=make('article',undefined,'area-panel'),heading=make('h3'),title=make('span',place(id)),count=make('span'),surface=make('canvas'),members=make('p');surface.width=400;surface.height=220;surface.setAttribute('aria-label',place(id)+' with all people in this area');const open=make('button','Open area');open.onclick=()=>{setView('area');following=false;map(id);};heading.append(title,count);panel.append(heading,surface,members,open);$('areas').append(panel);const row={panel,count,surface,members};areaPanels.set(id,row);requestMapAsset(id);return row;}
function drawOverview(now){
 if(!state)return;if(view==='everyone'&&fitPeople){const grid=$('everyone'),columns=getComputedStyle(grid).gridTemplateColumns.split(' ').length,rows=Math.ceil(humans().length/columns)||1,available=window.innerHeight-(grid.getBoundingClientRect().top+window.scrollY)-12,height=Math.max(46,Math.min(76,Math.floor((available-(rows-1)*4)/rows)));grid.style.setProperty('--card-height',height+'px');grid.style.setProperty('--portrait-size',Math.max(12,Math.min(30,height-34))+'px');}const positions=humans().map(h=>motionPosition(h,now));
 for(const h of positions){const row=overviewCards.get(h.human_id);if(!row)continue;const a=activity(state.humans[h.human_id],state,runtimeInfo),effect=effects.get(h.human_id);if(effect?.until<now)effects.delete(h.human_id);const talking=effect?.until>now&&effect.action==='talk_to';row.button.classList.toggle('walking',h.moving);row.button.classList.toggle('battling',a.kind==='battle');row.button.classList.toggle('chatting',!!talking);row.button.setAttribute('aria-pressed',String(h.human_id===selected));row.label.textContent=h.moving?'➜ Walking':talking?'💬 Chatting':a.icon+' '+({work:'Working',rest:'Resting',battle:'Battling',queue:'Waiting',journey:'Travelling',movement:'Moving',thinking:'Thinking',ready:'Ready'}[a.kind]||a.kind);row.location.textContent=place(h.map_id).split(' / ')[0];row.button.title=h.name+' · '+place(h.map_id)+' · '+(talking?effect.text||'Chatting':a.label);row.button.setAttribute('aria-label',row.button.title);const ctx=row.portrait.getContext('2d');ctx.clearRect(0,0,48,48);ctx.imageSmoothingEnabled=false;const actor=getActor(h);if(actor)drawActorFrame(ctx,actor,{x:16,y:20,facing:h.facing,moving:h.moving,timeMs:now});}
 if(view==='wall'){const groups=groupByMap(positions),visible=new Set(groups.map(([id])=>id));for(const [id,row] of areaPanels)row.panel.hidden=!visible.has(id);for(const [id,members] of groups){const row=ensureArea(id);row.panel.hidden=false;row.count.textContent=members.length+' people';row.members.textContent=members.map(h=>h.name+' '+(h.moving?'➜':activity(state.humans[h.human_id],state,runtimeInfo).icon)).join(' · ');const asset=mapAssets.get(id),ctx=row.surface.getContext('2d');ctx.clearRect(0,0,400,220);if(!asset||asset.failed){ctx.fillStyle='#c1d6b9';ctx.font='12px system-ui';ctx.fillText(asset?.failed?'Artwork unavailable':'Loading original map…',10,25);continue;}
   const xs=members.map(h=>h.x),ys=members.map(h=>h.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),z=Math.min(1.8,400/((maxX-minX+8)*asset.cell),220/((maxY-minY+8)*asset.cell));const width=asset.image.width*z,height=asset.image.height*z;const vx=width<=400?(400-width)/2:Math.max(400-width,Math.min(0,200-((minX+maxX)/2+.5)*asset.cell*z)),vy=height<=220?(220-height)/2:Math.max(220-height,Math.min(0,110-((minY+maxY)/2)*asset.cell*z));ctx.imageSmoothingEnabled=false;ctx.save();ctx.setTransform(z,0,0,z,vx,vy);ctx.drawImage(asset.image,0,0);const anchor=state.humans[members[0].human_id];terrain.draw(ctx,asset.meta,{human:anchor,cellSize:asset.cell});field.draw(ctx,asset.meta,{human:anchor,worldFacts:state.world_facts,cellSize:asset.cell});for(const h of members){const actor=getActor(h);if(actor)drawActorFrame(ctx,actor,{x:h.x*asset.cell,y:h.y*asset.cell,facing:h.facing,moving:h.moving,timeMs:now});if(h.moving||h.battle_id){ctx.fillStyle=h.moving?'#ffe799':'#ffb8a0';ctx.fillRect(h.x*asset.cell+5,h.y*asset.cell-21,5,3);}}ctx.restore();}
   $('overviewcount').textContent=positions.length+' people across '+groups.length+' occupied areas · all included';
 }
}

$('world').onchange=()=>loadWorld($('world').value);$('location').onchange=()=>{setView('area');following=false;$('follow').setAttribute('aria-pressed','false');map($('location').value);};$('search').oninput=renderPeople;
$('follow').onclick=()=>{if(view!=='area'){setView('area');following=false;}following=!following;$('follow').setAttribute('aria-pressed',String(following));fit();draw();};$('spotlight').onclick=()=>{if(view!=='area')setView('area');spotlight=!spotlight;$('spotlight').setAttribute('aria-pressed',String(spotlight));};
$('replaywalk').onclick=()=>{const event=[...events].reverse().find(e=>eventActors(e).includes(selected)&&routeSegments(e,selected).length)||[...events].reverse().find(e=>state.humans[actorId(e)]&&routeSegments(e).length);if(!event)return;motions.clear();setView('area');select(eventActors(event).includes(selected)?selected:actorId(event),true);animate(event,{saved:true});updateStatus();draw();};
let dragging=false,moved=false,last=null;canvas.onpointerdown=e=>{dragging=true;moved=false;last=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};canvas.onpointermove=e=>{if(!dragging)return;const dx=e.clientX-last[0],dy=e.clientY-last[1];if(Math.abs(dx)+Math.abs(dy)>2)moved=true;following=false;$('follow').setAttribute('aria-pressed','false');M.pan(dx,dy);last=[e.clientX,e.clientY];draw();};canvas.onpointerup=e=>{dragging=false;if(moved)return;const r=canvas.getBoundingClientRect(),cell=M.screenToCell(e.clientX-r.left,e.clientY-r.top);const h=humans().find(h=>{const p=motionPosition(h);return p.map_id===M.state.name&&Math.abs(p.x-cell.x)<=1&&Math.abs(p.y-cell.y)<=1;});if(h)select(h.human_id,true);};canvas.onwheel=e=>{e.preventDefault();const r=canvas.getBoundingClientRect();following=false;M.zoomAt(e.clientX-r.left,e.clientY-r.top,e.deltaY<0?1.15:1/1.15);draw();};
new ResizeObserver(resize).observe(canvas.parentElement);window.addEventListener('resize',()=>{if(view!=='area')draw();});$('view').onchange=()=>setView($('view').value);$('fitpeople').onclick=()=>{fitPeople=!fitPeople;$('fitpeople').setAttribute('aria-pressed',String(fitPeople));setView(view);};$('smooth').onclick=()=>{smooth=!smooth;$('smooth').setAttribute('aria-pressed',String(smooth));updateStatus();};M.onReady=()=>{fit();draw();};
setInterval(async()=>{if(!world||!state||refreshing||socket?.readyState===1)return;refreshing=true;const g=generation;try{const d=await get('/runs/'+encodeURIComponent(world));if(g!==generation)return;accept(d);const history=await get('/runs/'+encodeURIComponent(world)+'/events?after='+cursor);if(g!==generation)return;ingest(Array.isArray(history)?history:history.events);updateStatus();}catch(error){if(g===generation)fail(error);}finally{refreshing=false;}},5000);
const wanted=new URLSearchParams(location.search).get('world');
if(wanted){$('world').add(new Option(wanted,wanted));$('world').value=wanted;loadWorld(wanted);}
get('/runs').then(runs=>{const existing=new Set([...$('world').options].map(o=>o.value));for(const r of Array.isArray(runs)?runs:runs.runs||[]){const id=typeof r==='string'?r:r.run_id;if(!existing.has(id))$('world').add(new Option(id,id));}}).catch(()=>{if(!wanted)fail(Error('Saved-world list is still loading. Retry the page shortly.'));});
get('/content/region.json').then(region=>{for(const m of region.maps)$('location').add(new Option(place(m.id),m.id));if(M.state.name)$('location').value=M.state.name;if(!wanted)map('PalletTown');}).catch(fail);

setView('everyone');

setInterval(async()=>{const id=world,g=generation,q=++runtimeQuery;if(!id)return;try{const info=await get('/runs/'+encodeURIComponent(id)+'/runtime');if(world!==id||generation!==g||runtimeQuery!==q)return;runtimeInfo=info;updateStatus();renderPeople();renderPerson();ensureFrame();}catch(_){}},2000);
