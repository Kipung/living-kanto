// stdin/stdout JSON boundary; no networking and no evaluated choice text.
const fs = require('node:fs');
const {Battle} = require('pokemon-showdown');
const cartridge=require('./cartridge.cjs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const clean = x => x.replaceAll('_', ' ').toLowerCase();
const speciesName = x => ({NIDORAN_F:'Nidoran-F',NIDORAN_M:'Nidoran-M',MR_MIME:'Mr. Mime',FARFETCHD:"Farfetch'd"}[x] || clean(x));
function snapshot(b) {
  b.log = b.log.filter(line => !line.startsWith('|t:|'));
  const players = {};
  for (const side of b.sides) {
    const foe = side.foe;
    const publicLog = [];
    for(let i=0;i<b.log.length;i++) {
      const line = b.log[i];
      if(line.startsWith('|split|')) {const owner=line.split('|')[2]; publicLog.push(b.log[i+(owner===side.id?1:2)]); i+=2;} else publicLog.push(line);
    }
    players[side.name] = {turn:b.turn,request:side.activeRequest || null, opponent: {name:foe.name,active:foe.active.filter(Boolean).map(p=>({species:p.species.name,level:p.level,condition:p.getHealth().shared,status:p.status,fainted:p.fainted}))}, log:publicLog.slice(-200)};
  }
  return {engine:'pokemon-showdown@0.11.11/gen3',turn:b.turn,ended:b.ended,winner:b.winner||null,state:b.toJSON(),observations:players,pokemon:b.sides.flatMap(s=>s.pokemon.map(p=>({owner_id:s.name,pokemon_id:p.set.name,hp:p.hp,max_hp:p.maxhp,status:p.status,held_item:p.item?(b.cartridge?.sourceItemNames?.[p.item]||b.dex.items.get(p.item).name).toUpperCase().replaceAll(' ', '_').replaceAll('-', '_').replaceAll("'", '').replaceAll('.', ''):'',moves:p.moveSlots.map(m=>({id:m.id,move:m.move.toUpperCase().replaceAll(' ', '_').replaceAll('-', '_'),pp:m.pp,max_pp:m.maxpp}))}))),log:b.log.slice(-200)};
}
try {
  let b;
  if (input.operation==='start') {
    const teams=input.teams;
    if(teams.length!==2) throw Error('Exactly two trainers required');
    const players={};
    teams.forEach((t,i)=>{
      if(t.party.length<1||t.party.length>6) throw Error('Party size must be 1..6');
      if(input.doubles && (t.party.length<2 || t.party[1].hp<=0)) throw Error('Doubles require two healthy leading Pokemon');
      if(t.party[0].hp<=0) throw Error('Party lead has fainted; choose a healthy lead');
      for(const p of t.party) {
        if(p.owner_id!==t.actor_id) throw Error('Party ownership mismatch');
        if(p.moves.length<1||p.moves.length>4||p.level<1||p.level>100) throw Error('Illegal Pokemon');
      }
      players['p'+(i+1)]={name:t.actor_id,team:t.party.map(p=>({name:p.pokemon_id,species:speciesName(p.species),level:p.level,ability:clean(p.ability),nature:p.nature,gender:p.gender,happiness:p.friendship,ivs:p.ivs,evs:p.evs,item:clean(p.held_item||''),moves:p.moves.map(m=>clean(m.move))}))};
    });
    const ids=teams.flatMap(t=>t.party.map(p=>p.pokemon_id));
    if(new Set(ids).size!==ids.length) throw Error('Duplicate Pokemon individual');
    b=new Battle({formatid:input.doubles?'gen3doublescustomgame':'gen3customgame',seed:input.seed});
    b.reportExactHP=false; b.reportPercentages=true;
    b.setPlayer('p1', players.p1); b.setPlayer('p2', players.p2);
    b.cartridge={sourceItemNames:Object.fromEntries(teams.flatMap(t=>t.party).filter(p=>p.held_item).map(p=>[p.held_item.toLowerCase().replace(/[^a-z0-9]/g,''),p.held_item])),linkLike:!!input.link_like,badges:teams[0].badge_ids||[],originalOwners:Object.fromEntries(teams[0].party.map(p=>[p.pokemon_id,p.original_trainer_id||p.ownership_history?.[0]||teams[0].actor_id])),fateful:Object.fromEntries(teams[0].party.map(p=>[p.pokemon_id,!!p.modern_fateful_encounter])),events:[]};
    teams.forEach((t,i)=>t.party.forEach((p,j)=>{
      const mon=b.sides[i].pokemon[j];
      // Cartridge defaults have zero PP Ups; Showdown defaults have three.
      mon.hp=Math.min(mon.maxhp,p.hp);
      for(let k=0;k<p.moves.length;k++) {
        mon.moveSlots[k].maxpp=p.moves[k].max_pp; mon.moveSlots[k].pp=p.moves[k].pp;
        mon.baseMoveSlots[k].maxpp=p.moves[k].max_pp; mon.baseMoveSlots[k].pp=p.moves[k].pp;
      }
      if(p.status) mon.setStatus(p.status);
    }));
    cartridge.install(b);b.makeRequest('move');
  } else if(input.operation==='sync') {
    b=Battle.fromJSON(input.state);cartridge.install(b);
    for(const updated of input.pokemon) {
      const side=b.sides.find(s=>s.name===updated.owner_id);
      const mon=side?.pokemon.find(p=>p.set.name===updated.pokemon_id);
      if(!mon || updated.level<mon.level || updated.level>100)throw Error('Invalid individual synchronization');
      const previousLevel=mon.level;
      mon.set.happiness=updated.friendship;mon.happiness=updated.friendship;
      mon.set.level=updated.level;mon.level=updated.level;mon.set.evs=updated.evs;mon.set.ivs=updated.ivs;
      const stats={...updated.stats};mon.baseStoredStats=stats;
      if(!mon.transformed)for(const stat of ['atk','def','spa','spd','spe'])mon.storedStats[stat]=stats[stat];
      mon.baseMaxhp=stats.hp;mon.maxhp=stats.hp;mon.hp=updated.hp;
      mon.details=mon.getUpdatedDetails();mon.updateSpeed();
      if(mon.level!==previousLevel)b.add('-levelup',mon,mon.level);
    }
    if(!b.ended)b.makeRequest(b.requestState||'move');
  } else if(input.operation==='cartridge_context') {
    b=Battle.fromJSON(input.state);cartridge.install(b);const side=b.sides.find(s=>s.name===input.actor_id);
    process.stdout.write(JSON.stringify(side.pokemon.map(p=>({pokemon_id:p.set.name,stats:Object.fromEntries(['atk','def','spa','spd'].map(s=>[s,p.calculateStat(s,p.boosts[s])])),speed:p.getStat('spe')}))));process.exit(0);
  } else if(input.operation==='item_context') {
    b=Battle.fromJSON(input.state);cartridge.install(b);
    const side=b.sides.find(s=>s.name===input.actor_id);
    const mon=side?.pokemon.find(p=>p.set.name===input.pokemon_id);
    if(!mon) throw Error('Item target is not owned');
    process.stdout.write(JSON.stringify({active:mon.isActive,boosts:mon.boosts,confusion:!!mon.volatiles.confusion,infatuation:!!mon.volatiles.attract,focusenergy:!!mon.volatiles.focusenergy,mist:!!side.sideConditions.mist}));
    process.exit(0);
  } else if(input.operation==='validate') {
    b=Battle.fromJSON(input.state);cartridge.install(b);
    const side=b.sides.find(s=>s.name===input.actor_id);
    if(!side || !/^(move [1-4](?: -?[12])?|switch [1-6]|pass)(, (move [1-4](?: -?[12])?|switch [1-6]|pass))?$/.test(input.choice)) throw Error('Unsupported choice');
    if(!side.choose(input.choice)) throw Error(side.choice.error||'Illegal action');
    if(!side.isChoiceDone()) throw Error('Incomplete doubles choice');
    process.stdout.write(JSON.stringify({valid:true}));
    process.exit(0);
  } else if(input.operation==='resolve') {
    b=Battle.fromJSON(input.state);cartridge.install(b);
    // Validate all actions before submitting either; no side ever gets the other's choice.
    const actions=input.actions;
    for(const a of actions) {
      if(!a.item) continue;
      const side=b.sides.find(s=>s.name===a.actor_id);
      const mon=side?.pokemon.find(p=>p.set.name===a.item.pokemon.pokemon_id);
      if(!mon || a.item.pokemon.owner_id!==a.actor_id) throw Error('Illegal item ownership');
      const updated=a.item.pokemon, effects=a.item.effects;
      mon.hp=Math.min(mon.maxhp,updated.hp);
      if(mon.hp>0 && mon.fainted){mon.fainted=false;side.pokemonLeft++;}
      if(!updated.status && mon.status)mon.cureStatus();
      mon.moveSlots.forEach((m,i)=>{m.pp=updated.moves[i].pp;m.maxpp=updated.moves[i].max_pp;});
      if(effects.cure_confusion)mon.removeVolatile('confusion');
      if(effects.cure_infatuation)mon.removeVolatile('attract');
      if(effects.boost)b.boost(effects.boost,mon);
      if(effects.focusenergy)mon.addVolatile('focusenergy');
      if(effects.mist)side.addSideCondition('mist');
      b.add('-item',mon,a.item.name,'[from] trainer');
    }
    if(actions.length!==2) throw Error('Both trainer decisions required');
    for(let i=0;i<2;i++) {
      const side=b.sides[i], a=actions.find(a=>a.actor_id===side.name);
      if(!a) throw Error('Missing actor choice');
      if(!side.requestState) {
        if(a.choice!=='pass') throw Error('Waiting participant cannot act');
        continue;
      }
      if(input.item_actor===side.name || a.item) {
        if(!side.activeRequest?.active || side.activeRequest.wait) throw Error('Item turn unavailable');
        if(!side.choose(a.item && side.active.length>1?a.choice:'default')) throw Error(side.choice.error||'Illegal item turn');
        const slot=(a.item?.acting_slot||1)-1;
        if(!side.active[slot]||side.active[slot].fainted)throw Error('Item acting slot unavailable');
        side.choice.actions[slot]={choice:'pass',pokemon:side.active[slot]};
        continue;
      }
      if(!/^(move [1-4](?: -?[12])?|switch [1-6]|pass)(, (move [1-4](?: -?[12])?|switch [1-6]|pass))*$/.test(a.choice)) throw Error('Unsupported choice');
      if(!side.choose(a.choice)) throw Error(side.choice.error||'Illegal action');
      if(!side.isChoiceDone()) throw Error('Incomplete doubles choice');
    }
    b.commitChoices();
  } else throw Error('Unknown operation');
  process.stdout.write(JSON.stringify(snapshot(b)));
} catch(error) {process.stdout.write(JSON.stringify({error:error.message})); process.exitCode=1;}
