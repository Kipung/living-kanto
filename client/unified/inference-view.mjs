const node=(tag,text)=>{const result=document.createElement(tag);if(text!==undefined)result.textContent=text;return result;};
export function traceSummary(record){
  return {choice:record.canonical_response,outcome:record.outcome||'proposed',event:record.event_id||null,
    seconds:record.decision_seconds??null,model:record.model_id,
    observationVersion:record.observation_version,retry:!!record.corrective_retry};
}
export function mountInferenceView(target,{world,person,fetcher=fetch}){
  const section=node('section');section.append(node('h2','AI decisions · what the model saw and returned'));
  section.append(node('small','Recent inference records include proposals and rejected choices. Accepted game outcomes are recorded separately. Older inference records expire; full game history remains.'));
  const button=node('button','Load recent AI decisions'),status=node('p'),rows=node('div');
  section.append(node('p'));section.append(button,status,rows);target.append(section);
  button.onclick=async()=>{
    button.disabled=true;status.textContent='Loading recent decisions…';
    try{
      const response=await fetcher('/runs/'+encodeURIComponent(world)+'/observer/inference/'+encodeURIComponent(person)+'?limit=10');
      if(!response.ok)throw Error('Could not load AI decisions ('+response.status+').');
      const data=await response.json();rows.replaceChildren();
      status.textContent=data.audit?.audit_error?'Inference recording problem: '+data.audit.audit_error:
        data.records?.length?'Showing the latest '+data.records.length+' decisions.':'No inference records available yet. Records begin after the logging update.';
      for(const record of data.records||[]){
        const card=node('details');card.className='card';const summary=traceSummary(record);
        card.append(node('summary',(summary.retry?'Retry · ':'')+summary.outcome+' · Observation '+summary.observationVersion));
        card.append(node('p','Model: '+summary.model+(summary.seconds!=null?' · '+Number(summary.seconds).toFixed(2)+' seconds':'')));
        if(record.canonical_response)card.append(node('h3','Proposed game action'),node('pre',typeof record.canonical_response==='string'?record.canonical_response:JSON.stringify(record.canonical_response,null,2)));
        if(record.outcome_reason)card.append(node('p',record.outcome_reason));
        if(summary.event)card.append(node('p','Recorded game event: '+summary.event));
        for(const [index,stage] of (record.stages||[]).entries()){
          const detail=node('details');detail.append(node('summary','Request '+(index+1)+' · exact prompt and response'),node('pre',JSON.stringify(stage,null,2)));card.append(detail);
        }
        if(record.error_type)card.append(node('p',record.error_type));rows.append(card);
      }
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  };
  return section;
}
