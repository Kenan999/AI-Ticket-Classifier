/* Customer-support chat interactions; customer records come from the backend. */
(() => {
  const area=document.getElementById('messages');
  const tools=document.querySelector('.tools');
  // Present plain-text LLM output without leaking Markdown markers into chat bubbles.
  function cleanAssistantText(value){
    return String(value||'').replace(/\[([^\]]+)\]\((https?:\/\/[^)]+|\/api\/chat\/invoice\.pdf\?[^)]+)\)/g,'$1')
      .replace(/\*\*([^*]+)\*\*/g,'$1').replace(/(^|\n)\s*#{1,6}\s+/g,'$1')
      .replace(/(^|\n)\s*[-*]\s+/g,'$1• ').replace(/`([^`]+)`/g,'$1').trim();
  }
  window.ChatCloneCleanAssistantText=cleanAssistantText;
  // Progressive, softly animated word reveal for simulated assistant replies.
  let activeReveal=null;
  function revealAssistant(node,text,onComplete){
    text=cleanAssistantText(text);
    if(activeReveal){activeReveal.finish();}
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      node.textContent=text;
      activeReveal=null;
      if(onComplete)onComplete();
      return;
    }
    node.replaceChildren();
    const tokens=text.match(/\S+\s*/gu)||[];
    let position=0;
    let timer=null;
    let finished=false;
    const finish=()=>{
      if(finished)return;
      finished=true;
      if(timer!==null)clearTimeout(timer);
      node.textContent=text;
      if(activeReveal===controller)activeReveal=null;
      if(onComplete&&node.isConnected)onComplete();
    };
    const controller={finish};
    activeReveal=controller;
    const step=()=>{
      if(!node.isConnected){finish();return;}
      if(position>=tokens.length){finish();return;}
      const span=document.createElement('span');
      span.className='ai-reveal-word';
      span.textContent=tokens[position++];
      node.append(span);
      const scroll=document.getElementById('scroll');
      if(scroll)scroll.scrollTop=scroll.scrollHeight;
      timer=setTimeout(step,65);
    };
    step();
  }
  window.ChatCloneReveal=revealAssistant;
  // Initial quick actions are replaced by inline feedback after a completed answer.
  const composer=document.querySelector('.composer-wrap');
  const quickSupport=document.createElement('div');
  quickSupport.className='scenario-quick-support';
  quickSupport.hidden=true;
  quickSupport.setAttribute('role','group');
  quickSupport.setAttribute('aria-label','Customer support available anytime');
  const quickConnect=document.createElement('button');
  quickConnect.type='button';
  quickConnect.className='scenario-quick-option';
  quickConnect.innerHTML='<span aria-hidden="true">🎧</span><span>Connect with a support agent</span><span aria-hidden="true">→</span>';
  const quickResolved=document.createElement('button');
  quickResolved.type='button';
  quickResolved.className='scenario-quick-option';
  quickResolved.innerHTML='<span aria-hidden="true">✓</span><span>Thank you, my issue is resolved</span>';
  quickSupport.append(quickConnect,quickResolved);
  composer.insertBefore(quickSupport,composer.querySelector('.composer'));
  let quickSupportRun=0;
  let handoffActive=false;
  let handoffBlock=null;
  let latestSolutionActions=null;
  let conversationSerial=0;
  let conversation={id:0,queue:[],index:-1,closed:false,feedbackTarget:'AI support'};
  const pendingFeedback=new Map();
  quickConnect.dataset.action='quick-employee';
  quickResolved.dataset.action='quick-resolved';
  function currentConcern(){return conversation.queue[conversation.index]||null;}
  function isCurrentConcern(id,sessionId=conversation.id){
    const concern=currentConcern();
    return isSupportScenario()&&!conversation.closed&&conversation.id===sessionId&&concern?.id===id&&concern.state==='open';
  }
  function syncConversationState(){
    const concern=currentConcern();
    area.dataset.conversationState=isSupportScenario()?(conversation.closed?'closed':'open'):'idle';
    area.dataset.conversationSession=String(conversation.id);
    area.dataset.currentConcernId=concern?.id||'';
    area.dataset.currentConcernKey=concern?.key||'';
    area.dataset.currentConcernPosition=concern?String(conversation.index+1):'';
    area.dataset.currentConcernAwaitingDetails=String(!!concern?.awaitingDetails);
    area.dataset.concernCount=String(conversation.queue.length);
    area.dataset.openConcernCount=String(conversation.queue.filter(item=>item.state==='open').length);
    area.dataset.concernOrder=conversation.queue.map(item=>item.key).join(',');
    composer.dataset.conversationState=area.dataset.conversationState;
    for(const item of conversation.queue){
      if(item.card?.isConnected){
        item.card.dataset.concernState=item.state;
        item.card.classList.toggle('scenario-order-completed',item.state==='completed');
        item.card.classList.toggle('scenario-order-current',item===concern);
        if(item.state==='completed'&&!item.card.querySelector('.scenario-concern-badge')){
          const badge=document.createElement('span');badge.className='scenario-concern-badge';badge.textContent='Completed';item.card.append(badge);
        }
        item.card.setAttribute('aria-label',item.label+(item.state==='completed'?' · completed':item===concern?' · current issue':' · open'));
      }
      area.querySelectorAll('[data-concern-id]').forEach(node=>{if(node.dataset.concernId===item.id)node.dataset.concernState=item.state;});
    }
    const selectionStatus=area.querySelector('.scenario-order-confirmed')?.parentElement?.querySelector('.scenario-order-selection');
    if(selectionStatus&&conversation.queue.length){
      const done=conversation.queue.filter(item=>item.state==='completed').length;
      selectionStatus.textContent=done?done+' of '+conversation.queue.length+' issues resolved':'Confirmed selection';
    }
  }
  function setComposerClosed(closed){
    const input=document.getElementById('input');
    input.disabled=closed;
    input.setAttribute('aria-disabled',String(closed));
    input.placeholder=closed?'Conversation closed':activeScenario===2?'Describe your issue…':'Ask anything';
    if(closed){input.value='';input.style.height='35px';}
    document.getElementById('send').disabled=closed||!input.value.trim();
    for(const id of ['attach','file']){const control=document.getElementById(id);if(control)control.disabled=closed;}
  }
  function resetResponseState(){
    retireSolutionActions();
    handoffActive=false;
    handoffBlock=null;
    latestSolutionActions=null;
    pendingFeedback.clear();
    chatSessionId=null;
    conversation={id:++conversationSerial,queue:[],index:-1,closed:false,feedbackTarget:'AI support'};
    quickResolved.disabled=false;
    quickResolved.removeAttribute('title');
    const input=document.getElementById('input');input.value='';input.style.height='35px';
    setComposerClosed(false);
    syncConversationState();
  }
  function retireSolutionActions(){
    if(!latestSolutionActions?.isConnected)return;
    latestSolutionActions.querySelectorAll('button').forEach(button=>{button.disabled=true;});
  }
  function isSupportScenario(){return activeScenario===1||activeScenario===2;}
  function appendSupportMessage(){
    const block=document.createElement('div');
    block.className='scenario-support-result';
    block.setAttribute('aria-live','polite');
    area.append(block);
    const scroll=document.getElementById('scroll');
    scroll.scrollTop=scroll.scrollHeight;
    return block;
  }
  function cancelPendingAnswers(){
    ++scenarioMessageRun;
    area.querySelectorAll('.scenario-pending-answer').forEach(node=>node.remove());
    if(activeReveal)activeReveal.finish();
    retireSolutionActions();
  }
  function beginConcernQueue(entries){
    if(conversation.closed||conversation.queue.length)return false;
    conversation.queue=entries.map((entry,index)=>({
      id:'concern-'+conversation.id+'-'+(index+1),
      key:entry.id||'free-text',
      kind:entry.status?'order':entry.id==='other'?'other':'text',
      label:entry.label||'Support issue',
      orderStatus:entry.status||'',
      image:entry.image||'',alt:entry.alt||'',card:entry.card||null,
      details:entry.details?[...entry.details]:[],
      awaitingDetails:entry.id==='other'&&!entry.details?.length,
      state:'open',hasAnswer:false,lastAnswer:''
    }));
    conversation.index=conversation.queue.length?0:-1;
    quickResolved.disabled=false;
    quickResolved.removeAttribute('title');
    syncConversationState();
    return true;
  }
  function closeConversation(){
    if(!isSupportScenario()||conversation.closed||conversation.queue.some(item=>item.state==='open'))return;
    conversation.closed=true;
    conversation.index=-1;
    cancelPendingAnswers();
    ++quickSupportRun;
    handoffActive=false;
    handoffBlock=null;
    quickSupport.hidden=true;
    setComposerClosed(true);
    syncConversationState();
    const message=document.createElement('div');
    message.className='message assistant scenario-conversation-closed';
    message.setAttribute('role','status');
    const heading=document.createElement('strong');heading.textContent='Conversation closed';
    const detail=document.createElement('p');
    detail.textContent=conversation.queue.length?'All your issues are resolved. Thank you!':'Thank you!';
    message.append(heading,detail);area.append(message);
    // Show the optional rating immediately after the final concern is closed.
    showQuickFeedback(conversation.feedbackTarget);
  }
  function orderStatusExplanation(concern){
    if(concern.orderStatus==='processing')return 'Order '+concern.label+' is processing. No shipping or delivery date is available.';
    if(concern.orderStatus==='shipped')return 'Order '+concern.label+' has shipped but is not marked delivered. No tracking number or delivery date is available.';
    return 'Order '+concern.label+' has status '+concern.orderStatus+'. No further shipping details are available.';
  }
  function orderStatusExplanationEnglish(concern){
    const status=String(concern.orderStatus||'').toLowerCase();
    if(status==='processing')return 'Your order is being processed. No shipping or delivery date is available.';
    if(status==='shipped')return 'Your order has shipped but is not marked as delivered. No tracking number or delivery date is available.';
    if(status==='active')return 'Your order is active. No further shipping information is available.';
    return 'Order status: '+(status||'unknown')+'. No further shipping information is available.';
  }
  function scenarioExplanation(concern=currentConcern()){
    if(!concern)return '';
    const description=concern.details[0];
    const latest=concern.details.length>1?concern.details[concern.details.length-1]:'';
    const context=description?'Your issue is: „'+description+'“.'+(latest?' You added: „'+latest+'“.':'')+' ':'';
    if(concern.kind==='order')return context+'I can check this order for you. What would you like to know?';
    return context+'I do not have additional verified information about this issue. What would you like to clarify?';
  }
  function recordedConcernAnswer(concern,text,isFirst){
    if(concern.kind==='order')return 'You asked about '+concern.label+': “'+text+'”.';
    return (isFirst?'Thank you. Your issue is: “':'Thank you for the additional details: „')+text+'“.';
  }
  function renderCurrentConcern(first=false){
    const concern=currentConcern();
    if(!concern||!isCurrentConcern(concern.id))return;
    const sessionId=conversation.id;
    const run=scenarioMessageRun;
    retireSolutionActions();
    latestSolutionActions=null;
    quickSupport.hidden=!concern.awaitingDetails;
    quickConnect.hidden=handoffActive;
    const message=document.createElement('div');message.className='message assistant scenario-step-response';
    message.dataset.concernId=concern.id;message.dataset.concernKey=concern.key;message.dataset.concernPosition=String(conversation.index+1);
    const intro=document.createElement('div');
    const focus=document.createElement('div');focus.className='scenario-current-concern';focus.hidden=true;
    if(conversation.queue.length>1){
      const title=document.createElement('strong');title.textContent='Issue '+(conversation.index+1)+' of '+conversation.queue.length;
      const position=document.createElement('p');position.className='scenario-concern-position';position.textContent=concern.label;
      focus.append(title,position);
    }
    const card=document.createElement('div');card.className='scenario-focus-card';
    if(concern.image){const image=document.createElement('img');image.src=concern.image;image.alt=concern.alt;card.append(image);}
    else{const icon=document.createElement('span');icon.className='scenario-focus-icon';icon.textContent='💬';icon.setAttribute('aria-hidden','true');card.append(icon);}
    const name=document.createElement('span');name.textContent=concern.label;card.append(name);focus.append(card);
    const detail=document.createElement('p');detail.className='scenario-order-detail';
    detail.textContent=concern.kind==='order'?'Ask the AI assistant for the latest order status.':concern.awaitingDetails?'Please describe your issue.':recordedConcernAnswer(concern,concern.details[concern.details.length-1]||'',true);
    focus.append(detail);message.append(intro,focus);area.append(message);
    const revealFocus=()=>{
      if(run!==scenarioMessageRun||!message.isConnected||!isCurrentConcern(concern.id,sessionId))return;
      focus.hidden=false;
      concern.hasAnswer=!concern.awaitingDetails;
      concern.lastAnswer=detail.textContent;
      syncConversationState();
      if(concern.hasAnswer)showSolutionActions(message,concern.id,sessionId);
      else{quickSupport.hidden=false;document.getElementById('input').placeholder='Describe this issue…';document.getElementById('input').focus();}
      const scroll=document.getElementById('scroll');scroll.scrollTop=scroll.scrollHeight;
    };
    const introText=conversation.queue.length>1?(first?'We will go through your issues one at a time. Starting with the first:':'Let us continue with your next open issue:'):'';
    if(introText)requestAnimationFrame(()=>{if(run===scenarioMessageRun&&isCurrentConcern(concern.id,sessionId)&&message.isConnected)revealAssistant(intro,introText,revealFocus);});
    else revealFocus();
    syncConversationState();
  }
  let supportSession=null;
  let supportPoll=null;
  let lastSupportMessage=0;
  async function supportRequest(path,body){
    const response=await fetch(window.ChatCloneApiBase+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'Support service unavailable');
    return data;
  }
  function stopSupportPolling(){if(supportPoll)clearInterval(supportPoll);supportPoll=null;}
  async function pollSupport(){
    if(!supportSession)return;
    try{
      const url=new URL('/api/support/session',window.ChatCloneApiBase);
      url.searchParams.set('id',supportSession.id);
      url.searchParams.set('customer_token',supportSession.customer_token);
      const response=await fetch(url,{cache:'no-store'});
      if(!response.ok)throw new Error('Support session unavailable');
      const data=await response.json();
      if(data.status==='active'&&handoffBlock?.isConnected){
        const waiting=handoffBlock.querySelector('.scenario-quick-wait');
        if(waiting)waiting.textContent='Connected to '+(data.employee||'support')+'. You can now type your message below.';
      }
      for(const message of data.messages){
        if(message.id<=lastSupportMessage)continue;
        lastSupportMessage=message.id;
        if(message.sender==='employee'){
          const bubble=document.createElement('div');bubble.className='message assistant human-agent';bubble.dataset.agentName=data.employee||'Anna';
          const agentHeader=document.createElement('div');agentHeader.className='human-agent-header';
          const avatar=document.createElement('img');avatar.className='human-agent-avatar';avatar.src='./assets/avatars/service-agent-avatar.svg';avatar.alt='Anna profile picture';
          const name=document.createElement('strong');name.textContent=data.employee||'Anna';
          agentHeader.append(avatar,name);
          const body=document.createElement('div');body.textContent=message.content;
          bubble.append(agentHeader,body);
          area.append(bubble);document.getElementById('scroll').scrollTop=document.getElementById('scroll').scrollHeight;
        }
      }
      if(data.status==='closed'){
        stopSupportPolling();handoffActive=false;supportSession=null;
        if(handoffBlock?.isConnected)handoffBlock.textContent='The support conversation has ended.';
        quickConnect.hidden=false;
      }
    }catch(error){console.warn('Support polling:',error.message);}
  }
  async function connectToEmployee(){
    if(handoffActive)return;
    cancelPendingAnswers();handoffActive=true;quickConnect.hidden=true;quickSupport.hidden=false;
    retireSolutionActions();
    const block=appendSupportMessage();handoffBlock=block;
    block.innerHTML='<div class="scenario-quick-wait"><span class="demo-spinner" aria-hidden="true"></span><span>Waiting for a support employee to accept your chat…</span></div>';
    try{
      // Include the conversation so the employee sees what happened before handoff.
      const history=Array.from(area.querySelectorAll('.message.user, .message.assistant'))
        .filter(node=>node!==block && !node.classList.contains('scenario-conversation-closed'))
        .map(node=>({sender:node.classList.contains('user')?'customer':'ai',
          content:(node.querySelector('.scenario-answer-text')?.textContent||node.textContent||'').trim()}))
        .filter(item=>item.content).slice(-100);
      supportSession=await supportRequest('/api/support/request',{request:true,history});lastSupportMessage=0;
      stopSupportPolling();supportPoll=setInterval(pollSupport,1200);await pollSupport();
      const end=document.createElement('button');end.type='button';end.className='demo-btn';end.textContent='End support conversation';
      end.onclick=async()=>{if(!supportSession)return;await supportRequest('/api/support/close',supportSession);await pollSupport();};
      block.append(end);
    }catch(error){handoffActive=false;quickConnect.hidden=false;block.textContent='Unable to connect: '+error.message;}
  }
  window.ChatCloneSendSupportMessage=async text=>{
    if(!supportSession)return false;
    const url=new URL('/api/support/session',window.ChatCloneApiBase);
    url.searchParams.set('id',supportSession.id);url.searchParams.set('customer_token',supportSession.customer_token);
    const state=await (await fetch(url,{cache:'no-store'})).json();
    if(state.status!=='active')return true;
    await supportRequest('/api/support/message',{id:supportSession.id,customer_token:supportSession.customer_token,sender:'customer',message:text});
    const bubble=document.createElement('div');bubble.className='message user';bubble.textContent=text;area.append(bubble);
    document.getElementById('scroll').scrollTop=document.getElementById('scroll').scrollHeight;
    return true;
  };
  // Close the customer's session on refresh or tab close, including while waiting.
  window.addEventListener('pagehide',()=>{
    if(!supportSession)return;
    const payload=JSON.stringify({id:supportSession.id,customer_token:supportSession.customer_token});
    navigator.sendBeacon?.(window.ChatCloneApiBase+'/api/support/close',
      new Blob([payload],{type:'application/json'}));
    stopSupportPolling();
  });
  window.ChatCloneIsSupportActive=()=>Boolean(supportSession);
  quickConnect.addEventListener('click',connectToEmployee);
  function showQuickFeedback(target){
    const existing=pendingFeedback.get(target);
    if(existing?.isConnected){
      existing.scrollIntoView({block:'nearest'});
      existing.querySelector('button')?.focus();
      return;
    }
    const block=appendSupportMessage();
    pendingFeedback.set(target,block);
    const form=document.createElement('form');
    form.className='demo-feedback-form';
    const heading=document.createElement('h3');
    heading.textContent='How satisfied are you with '+target+'?';
    const rating=document.createElement('div');
    rating.className='demo-rating-stars';
    let stars=0;
    const ratingButtons=[];
    for(let n=1;n<=5;n++){
      const b=document.createElement('button');
      b.type='button';b.className='demo-star';b.textContent='★';
      b.setAttribute('aria-label',n+' of 5 Sternen');
      b.onclick=()=>{stars=n;ratingButtons.forEach((item,i)=>item.classList.toggle('selected',i<n))};
      ratingButtons.push(b);rating.append(b);
    }
    const question=document.createElement('p');
    question.textContent='Was your issue resolved?';
    const status=document.createElement('select');
    status.className='demo-select';
    status.setAttribute('aria-label','Issue resolved');
    for(const [v,l] of [['','Please select'],['yes','Yes'],['partly','Partially'],['no','No']]){
      const opt=document.createElement('option');opt.value=v;opt.textContent=l;status.append(opt);
    }
    const note=document.createElement('textarea');
    note.className='demo-feedback-note';
    note.placeholder='Optional comment';
    note.maxLength=1000;
    const submit=document.createElement('button');
    submit.type='submit';submit.className='demo-btn demo-feedback-submit';submit.textContent='Bewertung absenden';
    const error=document.createElement('p');error.className='demo-status';error.setAttribute('role','status');
    form.append(heading,rating,question,status,note,submit,error);
    form.addEventListener('submit',e=>{
      e.preventDefault();
      if(!stars||!status.value){error.textContent='Please select a star rating and resolution status.';return;}
      try{
        const data=JSON.parse(localStorage.getItem('chatCloneDemoFeedback')||'[]');
        if(!Array.isArray(data))throw new Error('invalid history');
        data.push({target:target.startsWith('KI')?'ai':'agent',stars,solved:status.value,comment:note.value,createdAt:new Date().toISOString()});
        localStorage.setItem('chatCloneDemoFeedback',JSON.stringify(data));
        block.textContent='✓ Danke! Deine Bewertung wurde lokal gespeichert.';
        pendingFeedback.delete(target);
      }catch(err){error.textContent='Die Bewertung konnte nicht gespeichert werden.'}
    });
    block.append(form);
    ratingButtons[0]?.focus({preventScroll:true});
    const scroll=document.getElementById('scroll');scroll.scrollTop=scroll.scrollHeight;
  }
  function acceptHelpfulAnswer(concernId,sessionId=conversation.id){
    if(!isCurrentConcern(concernId,sessionId))return;
    const concern=currentConcern();
    concern.state='completed';
    concern.completedAt=new Date().toISOString();
    retireSolutionActions();
    cancelPendingAnswers();
    if(handoffActive){
      ++quickSupportRun;handoffActive=false;
      if(handoffBlock?.isConnected)handoffBlock.textContent='Der Mitarbeiterkontakt zu diesem Anliegen wurde beendet.';
      handoffBlock=null;
    }
    conversation.index=conversation.queue.findIndex(item=>item.state==='open');
    syncConversationState();
    if(conversation.index<0)closeConversation();
    else renderCurrentConcern();
  }
  quickResolved.addEventListener('click',()=>{
    if(!isSupportScenario()||conversation.closed||quickResolved.disabled)return;
    const concern=currentConcern();
    if(concern)acceptHelpfulAnswer(concern.id,conversation.id);
    else closeConversation();
  });
  function showSolutionActions(message,concernId=currentConcern()?.id,sessionId=conversation.id){
    if(!isCurrentConcern(concernId,sessionId)||handoffActive||!message.isConnected)return;
    if(message.querySelector('.scenario-solution-feedback'))return;
    retireSolutionActions();
    quickSupport.hidden=true;
    const feedback=document.createElement('div');
    feedback.className='scenario-solution-feedback';
    feedback.dataset.concernId=concernId;feedback.dataset.sessionId=String(sessionId);
    const prompt=document.createElement('p');prompt.className='scenario-solution-prompt';prompt.textContent='Was this helpful?';
    const options=document.createElement('div');options.className='scenario-solution-options';options.setAttribute('role','group');options.setAttribute('aria-label','Was this helpful?');
    const actions=[['helpful','Yes, helpful'],['explain','I need more explanation'],['employee','Contact support agent']];
    for(const [action,label] of actions){
      const button=document.createElement('button');button.type='button';button.className='scenario-quick-option';button.dataset.action=action;button.textContent=label;
      button.addEventListener('click',()=>{
        if(button.disabled||latestSolutionActions!==feedback||!isCurrentConcern(concernId,sessionId))return;
        retireSolutionActions();button.classList.add('selected');button.setAttribute('aria-pressed','true');
        if(action==='helpful')acceptHelpfulAnswer(concernId,sessionId);
        else if(action==='employee')connectToEmployee();
        else queueScenarioAnswer('I need more explanation.',scenarioExplanation(currentConcern()),concernId,sessionId);
      });
      options.append(button);
    }
    feedback.append(prompt,options);message.append(feedback);latestSolutionActions=feedback;
    const scroll=document.getElementById('scroll');scroll.scrollTop=scroll.scrollHeight;
  }
  async function queueScenarioAnswer(userText,answerText,concernId=currentConcern()?.id,sessionId=conversation.id){
    if(!isCurrentConcern(concernId,sessionId))return;
    cancelPendingAnswers();
    const run=scenarioMessageRun;
    if(!handoffActive)quickSupport.hidden=true;
    const userMessage=document.createElement('div');userMessage.className='message user';userMessage.textContent=userText;
    const thinking=document.createElement('div');thinking.className='thinking scenario-pending-answer';
    thinking.innerHTML='<span class="spark">✦</span><span class="word">Thinking…</span>';
    area.append(userMessage,thinking);
    const scroll=document.getElementById('scroll');scroll.scrollTop=scroll.scrollHeight;
    let attachments=[];
    try{const result=await askGemini(userText,currentConcern());answerText=result.answer;attachments=result.attachments||[];}
    catch(error){console.error('Chat reply failed',error);answerText='The AI service is temporarily unavailable. Please try again.';}
    {
      if(run!==scenarioMessageRun||!thinking.isConnected||!isCurrentConcern(concernId,sessionId))return;
      const concern=currentConcern();
      const reply=document.createElement('div');reply.className='message assistant scenario-answer-message';
      reply.dataset.concernId=concernId;reply.dataset.concernKey=concern.key;reply.dataset.concernPosition=String(conversation.index+1);
      const text=document.createElement('div');text.className='scenario-answer-text';reply.append(text);
      for(const attachment of attachments){
        const apiBase=window.ChatCloneApiBase;
        const url=new URL(attachment.url,apiBase).href;
        const card=document.createElement('div');card.className='scenario-invoice-card';
        const name=document.createElement('strong');name.textContent='📄 '+attachment.name;
        const actions=document.createElement('div');actions.className='scenario-invoice-actions';
        const open=document.createElement('a');open.href=url;open.target='_top';
        open.textContent='Open PDF';open.className='scenario-invoice-link';
        const download=document.createElement('a');download.href=url+(url.includes('?')?'&':'?')+'download=1';download.download=attachment.name;
        download.textContent='Download PDF';download.className='scenario-invoice-link';
        actions.append(open,download);card.append(name,actions);reply.append(card);
      }
      thinking.replaceWith(reply);
      revealAssistant(text,answerText,()=>{
        if(run!==scenarioMessageRun||!isCurrentConcern(concernId,sessionId))return;
        concern.hasAnswer=true;concern.lastAnswer=answerText;syncConversationState();showSolutionActions(reply,concernId,sessionId);
      });
      scroll.scrollTop=scroll.scrollHeight;
    }
  }
  // Product choices and active orders are retrieved from SQLite via the local API.
  const OPEN_ORDER_STATUSES=new Set(['active','processing','shipped']);
  const isActiveOrder=order=>OPEN_ORDER_STATUSES.has(order.status);
  let demoOrders=[];
  let chatSessionId=null;
  window.ChatCloneApiBase=window.APP_CONFIG?.chatApiBase || (location.port==='8015'?'http://127.0.0.1:8016':location.origin);
  window.ChatCloneAskGemini=message=>askGemini(message,null);
  window.ChatCloneResetGeminiSession=()=>{chatSessionId=null;};
  async function askGemini(message, concern){
    const apiBase=window.ChatCloneApiBase;
    const response=await fetch(apiBase+'/api/chat/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:chatSessionId,message,order_number:concern?.kind==='order'?concern.key:null})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'AI request failed');
    chatSessionId=data.session_id;
    return data;
  }
  async function fetchCustomerOrders(){
    const apiBase=window.ChatCloneApiBase;
    const response=await fetch(apiBase+'/api/chat/me/orders',{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const data=await response.json();
    if(!Array.isArray(data.orders))throw new Error('Invalid orders response');
    return data.orders.map(order=>({
      id:order.order_number,
      status:order.status,
      label:order.order_number+' · '+order.product_name,
      image:order.image_url ? new URL(order.image_url.replace(/^\/+/,''),location.origin+'/').href : '',
      alt:'Product image: '+order.product_name
    }));
  }
  const scenarioLabels=['User has an active order','User has no active order'];
  const scenarioButtons=[];
  let activeScenario=0;
  let scenarioMessageRun=0;
  function updateScenarioButtons(){
    scenarioButtons.forEach((button,index)=>{
      const active=activeScenario===index+1;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',String(active));
    });
  }
  function resetScenario(){
    ++scenarioMessageRun;
    activeScenario=0;
    quickSupport.hidden=true;
    quickConnect.hidden=false;
    ++quickSupportRun;
    resetResponseState();
    document.getElementById('input').placeholder='Ask anything';
    window.ChatCloneCancelPendingReplies?.();
    updateScenarioButtons();
  }
  window.ChatCloneResetScenario=resetScenario;
  async function showScenario(number){
    const requestRun=++scenarioMessageRun;
    activeScenario=number;
    updateScenarioButtons();
    if(number===1){
      area.replaceChildren();
      const loading=document.createElement('div');loading.className='message assistant';
      loading.textContent='Loading your orders…';area.append(loading);
      try {
        const orders=await fetchCustomerOrders();
        if(requestRun!==scenarioMessageRun)return;
        demoOrders=orders;
      } catch(error) {
        if(requestRun!==scenarioMessageRun)return;
        loading.textContent='Unable to load your orders. Please check the local API connection.';
        console.error('Customer order lookup failed',error);
        return;
      }
    }
    const openOrders=demoOrders.filter(isActiveOrder);
    if(number===1&&openOrders.length===0)number=2;
    ++scenarioMessageRun;
    window.ChatCloneCancelPendingReplies?.();
    activeScenario=number;
    document.getElementById('input').placeholder=number===2?'Describe your issue…':'Ask anything';
    ++quickSupportRun;
    resetResponseState();
    quickSupport.hidden=!isSupportScenario();
    // A newly opened scenario starts with both support actions available.
    quickConnect.hidden=false;
    updateScenarioButtons();
    // Start a clean scenario view without deleting the locally saved chat history.
    area.replaceChildren();
    const message=document.createElement('div');
    message.className='message assistant';
    message.id='scenario-message';
    if(number===1){
      const greeting='Hello! How can I help you? Is your question about one of your orders or something else? Please choose.';
      const greetingText=document.createElement('div');
      message.append(greetingText);
      const showOrderOptions=()=>{
        if(!message.isConnected||activeScenario!==1||conversation.closed||conversation.queue.length)return;
        message.querySelector('.scenario-order-choices')?.remove();
        const options=document.createElement('div');
        options.className='scenario-order-choices';
        options.setAttribute('role','group');
        options.setAttribute('aria-label','Choose an order or another issue');
        const orders=[
          ...openOrders,
          {id:'other',label:'Something else (describe your issue)'}
        ];
        const hint=document.createElement('p');
        hint.className='scenario-order-hint';
        hint.textContent=orders.length===3?'You can select one, two, or all three options.':'You can select one or more options.';
        const status=document.createElement('p');
        status.className='scenario-order-selection';
        status.setAttribute('aria-live','polite');
        const nextButton=document.createElement('button');
        nextButton.type='button';
        nextButton.className='scenario-next-button';
        nextButton.textContent='Continue →';
        nextButton.hidden=true;
        const selected=new Set();
        const selectionOrder=[];
        const buttons=[];
        for(const order of orders){
          const b=document.createElement('button');
          b.type='button';
          b.className='scenario-order-card'+(order.image?'':' scenario-other-card');
          b.dataset.orderId=order.id;
          if(order.status)b.dataset.orderStatus=order.status;
          b.setAttribute('aria-pressed','false');
          if(order.image){
            const img=document.createElement('img');
            img.src=order.image;
            img.alt=order.alt;
            img.loading='lazy';
            b.append(img);
          }else{
            const icon=document.createElement('span');
            icon.className='scenario-other-icon';
            icon.textContent='💬';
            icon.setAttribute('aria-hidden','true');
            b.append(icon);
          }
          const name=document.createElement('span');
          name.className='scenario-order-name';
          name.textContent=order.label;
          b.append(name);
          const check=document.createElement('span');
          check.className='scenario-order-check';
          check.textContent='✓';
          check.setAttribute('aria-hidden','true');
          b.append(check);
          b.addEventListener('click',()=>{
            if(b.disabled||conversation.closed||conversation.queue.length||activeScenario!==1)return;
            // Every choice is independent: any one, any pair, or all three.
            if(selected.has(order.id)){
              selected.delete(order.id);
              selectionOrder.splice(selectionOrder.indexOf(order.id),1);
            }else{
              selected.add(order.id);
              selectionOrder.push(order.id);
            }
            for(const [id,button] of buttons){
              button.setAttribute('aria-pressed',String(selected.has(id)));
            }
            const names=orders.filter(item=>selected.has(item.id)).map(item=>item.label);
            status.textContent=names.length?'Selected ('+selected.size+'): '+names.join(' and '):'';
            nextButton.hidden=selected.size===0;
            quickResolved.disabled=selected.size>0;
            if(selected.size)quickResolved.title='Confirm your selection with Continue first.';else quickResolved.removeAttribute('title');
          });
          buttons.push([order.id,b]);
          options.append(b);
        }
        nextButton.addEventListener('click',()=>{
          if(selected.size===0||activeScenario!==1||conversation.closed||conversation.queue.length||nextButton.disabled||!nextButton.isConnected)return;
          nextButton.disabled=true;
          const answers=Object.fromEntries(orders.map(order=>[order.id,order.label]));
          for(const [id,button] of buttons){
            if(!selected.has(id))button.remove();
            else{button.disabled=true;button.setAttribute('aria-pressed','true');}
          }
          options.classList.add('scenario-order-confirmed');options.setAttribute('aria-label','Confirmed selection');status.textContent='Confirmed selection';nextButton.remove();
          const entries=selectionOrder.map(id=>({...orders.find(order=>order.id===id),card:buttons.find(([key])=>key===id)?.[1]}));
          if(!beginConcernQueue(entries))return;
          const userMessage=document.createElement('div');userMessage.className='message user';userMessage.textContent=selectionOrder.map(id=>answers[id]||id).join(' and ');area.append(userMessage);
          renderCurrentConcern(true);
        });
        message.append(hint,options,status,nextButton);
        const scroll=document.getElementById('scroll');
        if(scroll)scroll.scrollTop=scroll.scrollHeight;
      };
      // Wait until the smooth AI greeting finishes before revealing the choices.
      requestAnimationFrame(()=>{if(message.isConnected&&activeScenario===1)revealAssistant(greetingText,greeting,showOrderOptions)});
    }else{
      // Categories and historical orders are background context, never a menu here.
      const greetingText=document.createElement('div');
      message.append(greetingText);
      requestAnimationFrame(()=>{
        if(message.isConnected&&activeScenario===2){
          revealAssistant(greetingText,'Hallo! Wie kann ich dir helfen? Beschreibe bitte kurz dein Anliegen.');
        }
      });
    }
    area.append(message);
    const scroll=document.getElementById('scroll');
    scroll.scrollTop=scroll.scrollHeight;
  }
  // Free text belongs to the current concern; it never silently advances the queue.
  window.ChatCloneHandleScenarioMessage=text=>{
    if(!isSupportScenario())return false;
    if(conversation.closed)return true;
    const value=text.trim();if(!value)return true;
    let concern=currentConcern();
    if(!concern){
      beginConcernQueue([{id:'free-text',label:'Support issue',details:[]}]);
      concern=currentConcern();
      // A free-text start replaces the unconfirmed card choice, not an existing queue.
      const pending=area.querySelector('.scenario-order-choices:not(.scenario-order-confirmed)');
      if(pending){
        pending.querySelectorAll('button').forEach(button=>{button.disabled=true;});
        const host=pending.parentElement;host.querySelector('.scenario-next-button')?.remove();
        const status=host.querySelector('.scenario-order-selection');if(status)status.textContent='Issue described in chat';
      }
    }
    const first=concern.details.length===0;
    concern.details.push(value);concern.awaitingDetails=false;
    syncConversationState();
    queueScenarioAnswer(value,recordedConcernAnswer(concern,value,first),concern.id,conversation.id);
    return true;
  };
  document.getElementById('form').addEventListener('submit',event=>{
    if(isSupportScenario()&&conversation.closed){event.preventDefault();event.stopImmediatePropagation();}
  },true);
  document.getElementById('input').addEventListener('input',()=>{
    if(isSupportScenario()&&conversation.closed)document.getElementById('send').disabled=true;
  });
  // Scenario test controls are hidden; load the signed-in customer's orders directly.
  showScenario(1);
  syncConversationState();
})();
