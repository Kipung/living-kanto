import {shortcut,createMovement} from './keyboard.mjs';
import {liveContext,refreshWorld,chooseWorld,changeView,watchPerson,cameraControl,panCamera} from '/client/live/live.mjs?v=journeys-5';
const $=id=>document.getElementById(id);let busy=false,tool='settings',frameKey='',speedWorld='',speedTouched=false;
async function request(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));return d;}
function render(){const c=liveContext();if(speedWorld!==c.world){speedWorld=c.world;speedTouched=false;$('playspeed').value='1';}if(c.runtimeInfo?.speed&&!speedTouched&&document.activeElement!==$('playspeed'))$('playspeed').value=String(c.runtimeInfo.speed);$('worldrun').disabled=busy||!c.state||c.status==='running';$('worldpause').disabled=busy||!c.state||c.status==='paused';$('world').disabled=busy;$('worldmode').disabled=busy||!c.state;$('playspeed').disabled=busy;$('worldmode').value=c.state?.world_facts?.interaction_mode||c.state?.mode||'observer';if($('toolbox').open)showTool(tool);renderNavigation();}
async function command(action,body={}){const c=liveContext();if(!c.world)throw Error('Choose a saved world first.');return request('/runs/'+encodeURIComponent(c.world)+'/'+action,body);}
async function perform(fn){if(busy)return;busy=true;render();$('controlnotice').textContent='Working…';try{await fn();await refreshWorld();$('controlnotice').textContent='Saved.';}catch(e){$('controlnotice').textContent=e.message;}finally{busy=false;render();}}
$('worldrun').onclick=()=>perform(()=>command('resume',{speed:$('playspeed').value==='fastest'?'fastest':Number($('playspeed').value)}));
$('worldpause').onclick=()=>perform(()=>command('pause'));
$('playspeed').onchange=()=>{speedTouched=true;if(liveContext().status==='running')$('worldrun').onclick();else $('controlnotice').textContent='Speed will apply when you press Run.';};
$('worldmode').onchange=()=>{const mode=$('worldmode').value;perform(async()=>{await command('mode',{mode,expected_state_version:liveContext().state.state_version});await refreshWorld();if(mode!=='observer'&&!liveContext().state.humans.player){await command('player/create',{expected_state_version:liveContext().state.state_version});await refreshWorld();}if(mode!=='observer')watchPerson('player');});};
const titles={inspect:'Selected person',player:'Your trainer',npcs:'People & NPCs',settings:'World & AI settings',history:'History & saved worlds'};
function showTool(next){tool=next;const c=liveContext();$('tooltitle').textContent=titles[tool];$('toolhint').textContent=(c.world?'World: '+c.world:'Create a world in World & AI settings.')+(tool==='player'&&$('worldmode').value==='observer'?' · Choose Play or Creative to join.':'');document.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===tool)));const key=tool+'|'+c.world+'|'+(c.state?.world_facts?.interaction_mode||'observer');if(key===frameKey)return;frameKey=key;const q=new URLSearchParams({world:c.world,embed:tool,human_id:c.selected||''});$('toolframe').src=(tool==='inspect'?'/client/unified/person.html':tool==='npcs'?'/client/unified/npcs.html':'/client/tools/index.html')+'?'+q;}
function openTools(next='settings'){if(!$('toolbox').open)$('toolbox').showModal();showTool(next);}
$('toolsopen').onclick=()=>openTools();$('toolsclose').onclick=()=>$('toolbox').close();document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>showTool(b.dataset.tool));
window.addEventListener('kanto:context',render);
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==$('toolframe').contentWindow||e.data?.type!=='kanto:world'||typeof e.data.world!=='string')return;if(e.data.world&&e.data.world!==liveContext().world)chooseWorld(e.data.world);});
window.addEventListener('message',e=>{if(e.origin===location.origin&&e.source===$('toolframe').contentWindow&&e.data?.type==='kanto:inspect-person'&&typeof e.data.person==='string'){watchPerson(e.data.person);showTool('inspect');syncSelection();}});
render();

function syncSelection(){if($('toolbox').open&&tool==='inspect')$('toolframe').contentWindow?.postMessage({type:'kanto:selection',human_id:liveContext().selected},location.origin);}
$('toolframe').onload=syncSelection;window.addEventListener('kanto:selection',syncSelection);

const secondaryControls=['world','location'];
for(const id of secondaryControls)$(id).closest('label').classList.add('secondary-control');
for(const id of ['smooth','replaywalk','follow','spotlight'])$(id).classList.add('secondary-control');
$('viewoptions').onclick=()=>{const open=document.body.classList.toggle('show-view-options');$('viewoptions').setAttribute('aria-expanded',String(open));$('viewoptions').textContent=open?'Less controls':'More controls';window.dispatchEvent(new Event('resize'));};
if(!document.fullscreenEnabled)$('fullscreen').hidden=true;
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(error){$('controlnotice').textContent='Fullscreen unavailable: '+error.message;}};
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'Exit fullscreen':'Fullscreen';$('fullscreen').setAttribute('aria-pressed',String(!!document.fullscreenElement));window.dispatchEvent(new Event('resize'));});

function setPanel(open){document.body.classList.toggle('panel-open',open);$('paneltoggle').setAttribute('aria-expanded',String(open));window.dispatchEvent(new Event('resize'));}
$('paneltoggle').onclick=()=>setPanel(!document.body.classList.contains('panel-open'));
$('panelclose').onclick=()=>{setPanel(false);$('paneltoggle').focus();};
$('watchperson').onclick=()=>{watchPerson();setPanel(false);$('scene').focus();};
$('inspectperson').onclick=()=>openTools('inspect');
$('mytrainer').onclick=()=>{watchPerson('player');$('scene').focus();};
$('playeractions').onclick=()=>openTools('player');
function renderNavigation(){
 const c=liveContext(),playing=c.mode!=='observer',player=c.state?.humans?.player;
 for(const button of document.querySelectorAll('[data-view]'))button.setAttribute('aria-pressed',String(button.dataset.view===c.view));
 $('mytrainer').disabled=!player||!playing;$('mytrainer').title=playing?'Follow your trainer':'Choose Play or Creative to control your trainer';
 $('playeractions').hidden=!playing||!player;
 $('playerpad').hidden=!playing||!player||c.view!=='area'||c.selected!=='player';
 $('watchperson').disabled=!c.selected;$('inspectperson').disabled=!c.selected;
 $('camerafollow').textContent=c.selected==='player'?'Follow trainer':'Follow person';
 document.body.classList.toggle('playing',playing);
}
for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>changeView(button.dataset.view);
window.addEventListener('kanto:view',renderNavigation);
window.addEventListener('kanto:selection',renderNavigation);
window.addEventListener('kanto:inspect',()=>setPanel(true));
for(const [id,action] of [['zoomin','in'],['zoomout','out'],['zoomfit','fit'],['camerafollow','follow']])$(id).onclick=()=>cameraControl(action);
$('helpopen').onclick=()=>{if(!$('shortcuthelp').open)$('shortcuthelp').showModal();};
$('helpclose').onclick=()=>$('shortcuthelp').close();
const moveTrainer=createMovement({context:liveContext,request,refresh:refreshWorld,onMessage:text=>$('controlnotice').textContent=text});
for(const button of document.querySelectorAll('[data-direction]'))button.onclick=()=>moveTrainer(button.dataset.direction);
window.addEventListener('keydown',event=>{
 if(document.querySelector('dialog[open]'))return;
 const c=liveContext(),action=shortcut(event,{mapFocused:document.activeElement===$('scene'),playing:c.mode!=='observer'&&c.selected==='player'});
 if(!action)return;if(action.type==='camera'&&c.view!=='area')return;
 event.preventDefault();
 if(action.type==='view')changeView(action.view);
 else if(action.type==='camera')cameraControl(action.action);
 else if(action.type==='pan')panCamera(action.direction);
 else if(action.type==='move')moveTrainer(action.direction);
 else if(action.type==='search'){setPanel(true);$('search').focus();}
 else if(action.type==='fullscreen')$('fullscreen').click();
 else if(action.type==='help')$('helpopen').click();
});
renderNavigation();
