// Cartridge-only FR rules absent from competitive/link simulator formats.
// Source pokemon.c CalculateBaseDamage; battle_main.c GetWhoStrikesFirst;
// battle_util.c IsMonDisobedient; personal offline duels use link exceptions.
function install(b) {
  if(!b.cartridge || b.cartridge.linkLike)return;
  const p1=b.sides[0], badges=new Set(b.cartridge.badges||[]);
  for(const mon of p1.pokemon) {
    const calculate=mon.calculateStat;
    mon.calculateStat=function(stat,boost,modifier,user) {
      const applies=(stat==='atk'&&badges.has('boulder'))||(stat==='def'&&badges.has('soul'))||(['spa','spd'].includes(stat)&&badges.has('volcano'));
      if(!applies)return calculate.call(this,stat,boost,modifier,user);
      const value=this.storedStats[stat];this.storedStats[stat]=Math.floor(value*110/100);
      try{return calculate.call(this,stat,boost,modifier,user);}finally{this.storedStats[stat]=value;}
    };
    const get=mon.getStat;
    mon.getStat=function(stat,unboosted,unmodified) {
      if(stat!=='spe'||!badges.has('thunder')||unmodified)return get.call(this,stat,unboosted,unmodified);
      const value=Math.floor(get.call(this,stat,unboosted,true)*110/100);
      return b.runEvent('ModifySpe',this,null,null,value);
    };
    mon.updateSpeed();
  }
  const run=b.actions.runMove;
  b.actions.runMove=function(moveOrName,mon,targetLoc,options) {
    if(mon.side!==p1 || options?.externalMove || mon.fainted)return run.call(this,moveOrName,mon,targetLoc,options);
    const origin=b.cartridge.originalOwners[mon.set.name];
    const illegalMew=mon.species.id==='mew'&&!b.cartridge.fateful[mon.set.name];
    if(!illegalMew&&(origin===p1.name||badges.has('earth')))return run.call(this,moveOrName,mon,targetLoc,options);
    let limit=illegalMew?0:badges.has('marsh')?70:badges.has('rainbow')?50:badges.has('cascade')?30:10;
    if(mon.level<=limit || ((mon.level+limit)*b.random(256)>>8)<limit)return run.call(this,moveOrName,mon,targetLoc,options);
    const move=b.dex.moves.get(moveOrName);mon.removeVolatile('rage');
    const record=(outcome,extra={})=>{b.cartridge.events.push({turn:b.turn,pokemon_id:mon.set.name,outcome,...extra});b.add('cant',mon,'disobedience',outcome);};
    if(mon.status==='slp'&&['snore','sleeptalk'].includes(move.id)){record('ignored while asleep');return;}
    if(((mon.level+limit)*b.random(256)>>8)<limit && move.id!=='focuspunch') {
      const usable=mon.getMoves().filter(m=>m.id!==move.id&&!m.disabled&&m.pp>0);
      if(usable.length) {
        let slot;
        do{slot=b.random(4);}while(!mon.moveSlots[slot]||!usable.some(m=>m.id===mon.moveSlots[slot].id));
        const alternative=mon.moveSlots[slot].id;record('used another move',{move:alternative});
        return run.call(this,alternative,mon,0,options);
      }
      record('loafed');b.random(4);return;
    }
    const difference=mon.level-limit;let value=b.random(256);
    if(value<difference&&!mon.status&&!['vitalspirit','insomnia'].includes(mon.ability)&&!b.sides.some(s=>s.active.some(p=>p?.volatiles.uproar))) {
      record('fell asleep');mon.setStatus('slp');return;
    }
    value-=difference;
    if(value<difference) {
      record('hurt itself');mon.removeVolatile('lockedmove');
      // Source CalculateBaseDamage(Pound, self,40) then normal variance.
      let attack=mon.storedStats.atk, defense=mon.storedStats.def;
      if(['hugepower','purepower'].includes(mon.ability))attack*=2;
      if(badges.has('boulder'))attack=Math.floor(attack*110/100);
      if(badges.has('soul'))defense=Math.floor(defense*110/100);
      if(mon.item==='silkscarf')attack=Math.floor(attack*110/100);
      if(mon.item==='choiceband')attack=Math.floor(attack*150/100);
      if(mon.item==='metalpowder'&&mon.species.id==='ditto')defense*=2;
      if(mon.item==='thickclub'&&['cubone','marowak'].includes(mon.species.id))attack*=2;
      if(mon.ability==='hustle'||(mon.ability==='guts'&&mon.status))attack=Math.floor(attack*150/100);
      if(mon.ability==='marvelscale'&&mon.status)defense=Math.floor(defense*150/100);
      if(['explosion','selfdestruct'].includes(move.id))defense=Math.floor(defense/2);
      const stage=(value,n)=>Math.floor(value*(n>=0?2+n:2)/(n>=0?2:2-n));
      attack=stage(attack,mon.boosts.atk);defense=Math.max(1,stage(defense,mon.boosts.def));
      let damage=Math.floor(Math.floor(attack*40*(Math.floor(2*mon.level/5)+2)/defense)/50);
      if(mon.status==='brn'&&mon.ability!=='guts')damage=Math.floor(damage/2);
      damage=Math.max(1,damage)+2;
      b.damage(Math.max(1,Math.floor(damage*(100-b.random(16))/100)),mon,mon,b.dex.conditions.get('confusion'));return;
    }
    record('loafed');b.random(4);
  };
}
module.exports={install};
