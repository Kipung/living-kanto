"""Budget the final chat template, preserving current facts and legal choices."""
import copy,json
class ContextBudgetError(ValueError):pass

def fit_messages(messages,count_tokens,limit,output_tokens,target=12000):
    result=copy.deepcopy(messages);hard_budget=limit-output_tokens-256;budget=min(target,hard_budget)
    if budget<=0:raise ContextBudgetError('No input budget remains after reserving response tokens')
    while True:
        count=count_tokens(result)
        if count<=budget:return result,{'input_tokens':count,'input_budget':budget,'output_reserved':output_tokens}
        removed=False
        for message in result:
            try:doc=json.loads(message.get('content',''))
            except (ValueError,TypeError):continue
            if not isinstance(doc,dict):continue
            facts=doc.get('facts',doc)
            if not isinstance(facts,dict):continue
            memories=facts.get('memories')
            if isinstance(memories,list) and memories:
                memories.pop();facts.setdefault('self_state',{})['context_notice']='Some lower-priority episodic memories were omitted to fit this decision. Missing details are unknown; do not invent them.'
                message['content']=json.dumps(doc,ensure_ascii=False,separators=(',',':'));removed=True;break
        if not removed:
            # The preferred prompt target is soft; current facts and choices
            # remain intact when they fit the actual model safety boundary.
            if count<=hard_budget:
                return result,{'input_tokens':count,'input_budget':hard_budget,'preferred_input_budget':budget,'output_reserved':output_tokens,'preferred_target_exceeded':True}
            raise ContextBudgetError('Current facts and legal choices exceed the model context budget; reduce core observation size')
