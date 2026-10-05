// Presentation helpers: consume accepted engine facts; never create actions.
export const place = value => String(value || '').replaceAll('_', ' / ').replace(/([a-z])([A-Z])/g, '$1 $2');
export const actorId = event => event.causation?.decisions?.[0]?.human_id || event.deterministic_inputs?.routes?.[0]?.human_id || event.causation?.human_id || event.causation?.actor_id;
export function eventActors(event){return [...new Set([...(event.deterministic_inputs?.routes||[]).map(row=>row.human_id),...(event.causation?.decisions||[]).map(row=>row.human_id),actorId(event)].filter(Boolean))];}
export function routeSegments(event,humanId) {
  const route = event.deterministic_inputs?.route;
  const legacy=(!humanId||humanId===actorId(event))?(route?.journey || (route?.map_id ? [route] : [])):[];
  const recorded=(event.deterministic_inputs?.routes||[]).filter(row=>!humanId||row.human_id===humanId).map(row=>row.route||row);
  const rows=[...legacy,...recorded];
  const segments = rows.filter(row => Array.isArray(row.start) && Array.isArray(row.steps) && row.steps.length)
    .map(row => ({map: row.map_id, points: [row.start, ...row.steps].map(p => [p[0], p[1]])}));
  // Single cardinal steps have an explicit source and destination. Never invent
  // a straight route for a distant endpoint or Creative teleport.
  if (!segments.length && (!humanId||humanId===actorId(event)) && event.event_kind === 'human.moved') {
    const a = event.before?.position, b = event.after?.position;
    if (a && b && a.map_id === b.map_id && Math.abs(a.x-b.x)+Math.abs(a.y-b.y) === 1)
      segments.push({map:a.map_id, points:[[a.x,a.y],[b.x,b.y]]});
  }
  return segments;
}
export function activity(human, state, runtime) {
  if(human.battle_id)return {label:runtime?.inflight_actors?.includes(human.human_id)?'Thinking in battle':'Battling',icon:'⚔',kind:'battle'};
  if(human.movement_intent?.paused_for_battle)return {label:'Route paused for battle',icon:'◷',kind:'paused'};
  if(human.movement_intent)return {label:'Moving along an accepted route',icon:'➜',kind:'movement'};
  if(runtime?.inflight_actors?.includes(human.human_id))return {label:'Thinking locally',icon:'◌',kind:'thinking'};
  if (human.battle_id) return {label:'Battling', icon:'⚔', kind:'battle'};
  if (human.service_request) return {label:'Waiting for service', icon:'◷', kind:'queue'};
  if (human.activity) {
    const kind=human.activity.kind || 'busy';
    const left=Math.max(0,(human.activity.ready_at||0)-(state.simulated_time||0));
    return {label:(kind==='work'?'Working':kind==='rest'?'Resting':place(kind))+(left?' · '+Math.ceil(left/60)+' sim min left':''),icon:kind==='rest'?'☾':'⚒',kind};
  }
  if (human.active_plan) return {label:'Travelling to '+place(human.active_plan.destination_map),icon:'➜',kind:'journey'};
  return {label:'Ready',icon:'·',kind:'ready'};
}
export function elapsedWorldTime(seconds){
 if(!Number.isFinite(seconds)||seconds<0)return '—';
 let rest=Math.floor(seconds);const days=Math.floor(rest/86400);rest%=86400;const hours=Math.floor(rest/3600);rest%=3600;const minutes=Math.floor(rest/60);rest%=60;
 return days+'d '+String(hours).padStart(2,'0')+'h '+String(minutes).padStart(2,'0')+'m '+String(rest).padStart(2,'0')+'s';
}
export function worldProgress(state,runtime,status){
 const paused=status==='paused',speed=runtime?.speed,rate=runtime?.actual_simulated_seconds_per_wall_second;
 const request=speed===undefined?'—':speed==='fastest'?'fastest':speed+'×';
 const clock=paused?'Paused · requested '+request:'Requested '+request+' · measured '+(Number.isFinite(rate)?rate.toFixed(2)+'×':'—')+(runtime?.clock_processing_limited?' · processing limited':'');
 const active=paused?0:runtime?.queue_depth,pending=runtime?.pending_requests;const retiring=Number.isFinite(pending)&&Number.isFinite(active)?Math.max(0,pending-active):0;
 return {time:elapsedWorldTime(state?.simulated_time),updates:Number.isFinite(state?.state_version)?String(state.state_version):'—',decisions:Number.isFinite(runtime?.accepted_decisions)?String(runtime.accepted_decisions):'—',clock,thinking:(Number.isFinite(active)?active:'—')+' / '+(runtime?.concurrency??'—')+(retiring?' · '+retiring+' retiring':'')};
}
export function sharedClockLabel(runtime){if(runtime?.clock_mode!=='shared')return '';const requested=runtime.speed==='fastest'?'fastest':(runtime.speed||1)+'×',rate=runtime.actual_simulated_seconds_per_wall_second;return 'Requested '+requested+(Number.isFinite(rate)?' · actual '+rate.toFixed(2)+'×':'')+(runtime.clock_processing_limited?' · processing limits the clock':'');}
export function clockOnly(event){return event.event_kind==='world.shared_tick'&&!event.deterministic_inputs?.activity_completions?.length&&(event.deterministic_inputs?.routes||[]).every(row=>!row.event_kind||['human.moved','human.entered_map'].includes(row.event_kind));}
export function eventText(event, humans) {
  if(event.event_kind==='world.shared_tick'){const ids=(event.deterministic_inputs?.routes||[]).map(row=>row.human_id);return (ids.length?ids.map(id=>humans[id]?.name||id).join(' · ')+' advanced together':'Shared time advanced')+' · '+(event.deterministic_inputs?.shared_time?.elapsed??0)+'s';}
  if(event.causation?.decisions?.length)return event.causation.decisions.map(d=>(humans[d.human_id]?.name||d.human_id)+(d.action==='rest'?' started resting':' started work')).join(' · ');
  const who=humans[actorId(event)]?.name || 'World';
  const action=event.causation?.action || event.event_kind;
  const args=event.causation?.action_arguments || {};
  const target=humans[args.human_id]?.name;
  const words={talk_to:'chatted'+(target?' with '+target:''),work:'started work',rest:'started resting',journey_to:'travelled',travel_to:'walked',walk_to:'walked',enter_map:'entered a building',train:'found a wild encounter',battle_move:'chose a battle move',battle_turn:'chose battle actions',choose_starter:'received a starter',shop_buy:'ordered '+place(args.item),heal_party:'requested healing',serve:'served a customer',remember:'recorded a memory',set_goal:'set a goal'};
  const label=event.event_kind==='battle.started'?'started a battle':event.event_kind==='battle.ended'?'finished a battle':words[action] || String(action).replaceAll('_',' ').replaceAll('.', ' ');
  return who+' '+label+(event.after?.position?' · '+place(event.after.position.map_id):'');
}
export function battleMessages(log, trainers, actorNames={}) {
  const names={},result=[];
  const name=ident=>{const side=/^p([12])[ab]:/.exec(ident||'');const owner=side?trainers[Number(side[1])-1]:null;return (owner?owner+' · ':'')+(names[ident]||(ident||'').split(': ').at(-1));};
  for(let i=0;i<(log||[]).length;i++) {
    let line=log[i];if(line.startsWith('|split|')){line=log[++i];i++;}if(!line)continue;
    const p=line.split('|');if(['switch','drag'].includes(p[1]))names[p[2]]=p[3]?.split(',')[0];
    const messages={turn:()=> 'Turn '+p[2],move:()=>name(p[2])+' used '+p[3]+(p[4]?' → '+name(p[4]):''),'-damage':()=>name(p[2])+' · HP '+p[3],'-heal':()=>name(p[2])+' recovered · HP '+p[3],faint:()=>name(p[2])+' fainted',win:()=>(actorNames[p[2]]||p[2])+' won','-status':()=>name(p[2])+' · '+p[3],'-miss':()=> 'The move missed '+name(p[3]),'-crit':()=> 'Critical hit','-supereffective':()=> 'Super effective','-resisted':()=> 'Not very effective',cant:()=>name(p[2])+' could not act',tie:()=> 'Draw'};
    if(messages[p[1]])result.push({type:p[1],text:messages[p[1]]()});
  }
  return result;
}

export function groupByMap(people) {
  const groups=new Map();
  for(const human of people){const id=human.map_id;if(!groups.has(id))groups.set(id,[]);groups.get(id).push(human);}
  return [...groups].sort((a,b)=>b[1].length-a[1].length||a[0].localeCompare(b[0]));
}
export function walkingDuration(points,{smooth=true}={}) {
  return Math.max(360,(points.length-1)*(smooth?360:145));
}
