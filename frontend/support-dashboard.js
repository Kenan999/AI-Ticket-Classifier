/* Support-team queue and customer chat; separate from ticket classification. */
(()=>{
  const base=window.APP_CONFIG?.chatApiBase||(location.port==='8015'?'http://127.0.0.1:8016':location.origin);
  const tickets=document.getElementById('staff-ticket-sections');
  const panel=document.getElementById('staff-chat-panel');
  const count=document.getElementById('staff-chat-count');
  const queue=document.getElementById('staff-chat-queue');
  const conversation=document.getElementById('staff-chat-conversation');
  const messages=document.getElementById('staff-chat-messages');
  const form=document.getElementById('staff-chat-form');
  const input=document.getElementById('staff-chat-input');
  let selected=null;let lastMessage=0;
  function view(){
    document.getElementById('staff-settings-panel').hidden=true;
    tickets.hidden=false;panel.hidden=false;
  }
  async function api(path,data){
    const response=await fetch(base+path,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{cache:'no-store'});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Support request failed');return result;
  }
  function addMessage(item){
    const isCustomer=item.sender==='customer';
    const bubble=document.createElement('div');
    bubble.className='staff-chat-message '+(isCustomer?'customer':item.sender==='ai'?'assistant ai':'assistant employee');
    if(!isCustomer){
      const label=document.createElement('div');label.className='staff-chat-speaker';
      label.textContent=item.sender==='ai'?'✦ AI Assistant':'🎧 Customer service · Anna';
      bubble.append(label);
    }
    const content=document.createElement('div');content.className='staff-chat-content';
    content.textContent=item.content;
    bubble.append(content);messages.append(bubble);
    messages.scrollTop=messages.scrollHeight;
  }
  async function refresh(){
    try{
      const data=await api('/api/support/queue');
      count.textContent=String(data.waiting);count.hidden=!data.waiting;
      queue.replaceChildren();
      if(!data.requests.length)queue.textContent='No waiting or active chats.';
      for(const item of data.requests){
        const row=document.createElement('div');row.className='staff-chat-request';
        const label=document.createElement('span');label.textContent='Customer '+item.id.slice(0,8)+' · '+(item.status==='waiting'?'Waiting':'Connected');
        const button=document.createElement('button');button.type='button';button.textContent=item.status==='waiting'?'Accept Chat':'Open Chat';
        button.onclick=async()=>{try{if(item.status==='waiting')await api('/api/support/accept',{id:item.id});selected=item.id;lastMessage=0;messages.replaceChildren();conversation.hidden=false;document.getElementById('staff-chat-heading').textContent='Customer '+item.id.slice(0,8);view();await refresh()}catch(err){alert(err.message)}};
        row.append(label,button);queue.append(row);
      }
      if(selected){
        const session=await api('/api/support/session?id='+encodeURIComponent(selected)+'&staff=1');
        for(const item of session.messages){if(item.id>lastMessage){lastMessage=item.id;addMessage(item)}}
        if(session.status==='closed'){selected=null;conversation.hidden=true;}
      }
    }catch(err){queue.textContent='Support service unavailable: '+err.message}
  }
  form.onsubmit=async event=>{event.preventDefault();if(!selected||!input.value.trim())return;const message=input.value.trim();input.disabled=true;try{await api('/api/support/message',{id:selected,sender:'employee',message});input.value='';await refresh()}catch(err){alert(err.message)}finally{input.disabled=false;input.focus()}};
  document.getElementById('staff-chat-end').onclick=async()=>{if(!selected)return;await api('/api/support/close',{id:selected,staff:true});selected=null;conversation.hidden=true;await refresh()};
  // A browser reload ends demo conversations rather than leaving ghost "Connected" rows.
  const navigation=performance.getEntriesByType('navigation')[0];
  const start=navigation?.type==='reload'
    ? api('/api/support/reset-demo',{reset:true}).catch(error=>console.warn('Could not close demo chats:',error))
    : Promise.resolve();
  // The shared Classified Tickets / Human Review lists own chat-ticket rendering.
  // Keep the original support conversation queue and employee chat UI.
  start.then(refresh);
  setInterval(refresh,1500);
})();
