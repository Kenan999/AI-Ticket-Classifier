/* Ticket classifier model selection, based on the backend /providers API. */
(()=>{
  const panel=document.getElementById('staff-settings-panel');
  const toggle=document.getElementById('staff-settings-tab');
  const select=document.getElementById('staff-model-select');
  const current=document.getElementById('staff-model-current');
  const error=document.getElementById('staff-model-error');
  const api=window.APP_CONFIG?.apiBaseUrl||(['localhost','127.0.0.1'].includes(location.hostname)?'http://127.0.0.1:8001':'/api');
  const key='shoply-ticket-provider';
  const tickets=document.getElementById('staff-ticket-sections');
  const chat=document.getElementById('staff-chat-panel');
  function showSettings(){
    const open=panel.hidden;
    panel.hidden=!open;
    tickets.hidden=open;
    chat.hidden=open;
    toggle.setAttribute('aria-expanded',String(open));
  }
  toggle.addEventListener('click',showSettings);
  const thresholdSlider=document.getElementById('review-threshold-slider');
  const thresholdValue=document.getElementById('review-threshold-value');
  const thresholdStatus=document.getElementById('review-threshold-status');
  const thresholdApi=window.APP_CONFIG?.chatApiBase||(['localhost','127.0.0.1'].includes(location.hostname)?'http://127.0.0.1:8016':location.origin);
  fetch(thresholdApi+'/api/review-threshold',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Unavailable');return r.json()}).then(data=>{
    thresholdSlider.value=Math.round(data.threshold*100);
    thresholdValue.textContent=thresholdSlider.value+'%';
  }).catch(()=>{thresholdStatus.textContent='Could not load the current threshold.'});
  thresholdSlider.addEventListener('input',()=>{thresholdValue.textContent=thresholdSlider.value+'%'});
  thresholdSlider.addEventListener('change',async()=>{
    thresholdSlider.disabled=true;
    try{
      const response=await fetch(thresholdApi+'/api/review-threshold',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({threshold:Number(thresholdSlider.value)/100})});
      if(!response.ok)throw Error('Could not save threshold');
      const result=await response.json();
      thresholdStatus.textContent='Saved: '+Math.round(result.threshold*100)+'%';
    }catch(error){thresholdStatus.textContent=error.message}
    finally{thresholdSlider.disabled=false}
  });
  let availableProviders=new Set();
  async function load(){
    select.disabled=true;
    error.hidden=true;
    try{
      const [providersResponse,connectivityResponse]=await Promise.all([
        fetch(api+'/providers',{cache:'no-store'}),
        fetch(thresholdApi+'/api/chat/status',{cache:'no-store',signal:AbortSignal.timeout(15000)})
      ]);
      if(!providersResponse.ok||!connectivityResponse.ok)throw Error('Provider status unavailable');
      const data=await providersResponse.json();
      const connectivity=await connectivityResponse.json();
      availableProviders=new Set(connectivity.providers.filter(p=>p.status==='connected').map(p=>p.id));
      const usable=data.providers.filter(p=>p.configured&&availableProviders.has(p.id));
      const stored=localStorage.getItem(key);
      const chosen=usable.some(p=>p.id===stored)?stored:
        (usable.some(p=>p.id===data.default_provider)?data.default_provider:usable[0]?.id);
      select.replaceChildren();
      for(const provider of data.providers){
        const online=provider.configured&&availableProviders.has(provider.id);
        const option=document.createElement('option');
        option.value=provider.id;
        option.textContent=provider.label+(online?'':' (disconnected)');
        option.disabled=!online;
        select.append(option);
      }
      select.value=chosen||'';
      select.disabled=!chosen;
      window.ShoplyTicketProvider=chosen||null;
      const update=()=>{
        const provider=data.providers.find(p=>p.id===select.value);
        current.textContent='Selected ticket classifier: '+(provider?.label||'No connected model');
      };
      update();
      select.onchange=()=>{
        if(!availableProviders.has(select.value))return;
        window.ShoplyTicketProvider=select.value;
        localStorage.setItem(key,select.value);
        update();
      };
      if(!chosen){error.hidden=false;error.textContent='No classification model is connected.';}
    }catch(e){
      select.disabled=true;window.ShoplyTicketProvider=null;
      current.textContent='Model connectivity could not be verified.';
      error.hidden=false;error.textContent=e.message;
    }
  }
  async function loadChat(){
    const picker=document.getElementById('staff-chat-model-select');
    const status=document.getElementById('staff-chat-model-current');
    const error=document.getElementById('staff-chat-model-error');
    const base=window.APP_CONFIG?.chatApiBase||(['localhost','127.0.0.1'].includes(location.hostname)?'http://127.0.0.1:8016':location.origin);
    try{
      const response=await fetch(base+'/api/chat/provider',{cache:'no-store'});
      if(!response.ok)throw Error('Chat model information unavailable');
      const data=await response.json();
      picker.replaceChildren();
      for(const provider of data.providers){
        const option=document.createElement('option');option.value=provider.id;
        option.textContent=provider.id==='openai'?'OpenAI':provider.id==='local'?'Local Qwen3-4B':'Gemini';
        option.disabled=!provider.configured;
        if(!provider.configured)option.textContent+=' (not configured)';
        picker.append(option);
      }
      picker.value=data.provider;
      picker.disabled=false;
      status.textContent='Current chat agent: '+(data.provider==='openai'?'OpenAI':data.provider==='local'?'Local Qwen3-4B':'Gemini');
      picker.onchange=async()=>{
        picker.disabled=true;error.hidden=true;
        try{
          const saved=await fetch(base+'/api/chat/provider',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:picker.value})});
          if(!saved.ok)throw Error((await saved.json()).error||'Could not update chat provider');
          const result=await saved.json();
          status.textContent='Current chat agent: '+(result.provider==='openai'?'OpenAI':result.provider==='local'?'Local Qwen3-4B':'Gemini');
        }catch(e){error.hidden=false;error.textContent=e.message;picker.value=data.provider;}
        finally{picker.disabled=false;}
      };
    }catch(e){status.textContent='Chat agent unavailable';error.hidden=false;error.textContent=e.message;}
  }
  const statusList=document.getElementById('staff-api-status-list');
  const summary=document.getElementById('staff-api-status-summary');
  const checked=document.getElementById('staff-api-checked');
  const refreshButton=document.getElementById('staff-api-refresh');
  const chatBase=window.APP_CONFIG?.chatApiBase||(['localhost','127.0.0.1'].includes(location.hostname)?'http://127.0.0.1:8016':location.origin);
  const labels={openai:'OpenAI',gemini:'Gemini',local:'Qwen3-4B'};
  const descriptions={openai:'Cloud API',gemini:'Cloud API',local:'Local model'};
  const logos={openai:'openai.svg',gemini:'gemini.svg',local:'qwen.svg'};
  let statusBusy=false;
  async function refreshApiStatus(){
    if(statusBusy||!statusList)return;
    statusBusy=true;
    refreshButton.disabled=true;
    refreshButton.classList.add('is-checking');
    try{
      const response=await fetch(chatBase+'/api/chat/status',{cache:'no-store',signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw Error('Status service unavailable');
      const data=await response.json();
      statusList.replaceChildren();
      let connected=0;
      for(const item of data.providers){
        const online=item.status==='connected';if(online)connected++;
        const row=document.createElement('div');row.className='staff-api-status-row';row.setAttribute('role','listitem');
        const avatar=document.createElement('span');avatar.className='staff-api-avatar';avatar.setAttribute('aria-hidden','true');
        if(logos[item.id]){const img=document.createElement('img');img.src='assets/providers/'+logos[item.id];img.alt='';img.width=36;img.height=36;avatar.append(img);}
        const identity=document.createElement('div');identity.className='staff-api-identity';
        const name=document.createElement('strong');name.textContent=labels[item.id]||item.label;
        const detail=document.createElement('span');detail.textContent=descriptions[item.id]||'API provider';identity.append(name,detail);
        const state=document.createElement('span');state.className='staff-api-state '+(online?'is-connected':'is-disconnected');
        const dot=document.createElement('span');dot.className='staff-api-dot';dot.setAttribute('aria-hidden','true');
        const stateLabel=document.createElement('span');stateLabel.textContent=online?'Connected':item.status==='not_configured'?'Not configured':'Disconnected';
        state.append(dot,stateLabel);row.append(avatar,identity,state);statusList.append(row);
      }
      summary.textContent=connected+' of '+data.providers.length+' models connected';
      await load();
      checked.textContent='Last checked '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    }catch(e){summary.textContent='Unable to check connections';checked.textContent='The status service could not be reached. Try refreshing.';}
    finally{statusBusy=false;refreshButton.disabled=false;refreshButton.classList.remove('is-checking');}
  }
  refreshButton.addEventListener('click',refreshApiStatus);
  toggle.addEventListener('click',()=>{if(!panel.hidden)refreshApiStatus();});
  setInterval(()=>{if(!panel.hidden)refreshApiStatus();},30000);
  load();loadChat();
})();
