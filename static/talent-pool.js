(() => {
  const root = document.getElementById('talent');
  if (!root) return;
  const safe = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  let requestId = 0;
  root.innerHTML = `<div class="top"><div class="title"><h1>Talent Pool</h1><p>Search your master candidate database and keep profiles ready for the next requirement.</p></div><button class="ghost" id="tpRefresh">Refresh</button></div>
    <div id="tpPools" class="tp-pools" aria-label="Talent pools"></div>
    <form id="tpFilters" class="card tp-filters">
      <label class="tp-search">Search candidates<input name="q" placeholder="Name, skill, email or keyword"/></label>
      <label>Location<input name="location" placeholder="e.g. Chennai"/></label>
      <label>Minimum experience<input name="min_experience" type="number" min="0" step="0.1" placeholder="Years"/></label>
      <label>Maximum experience<input name="max_experience" type="number" min="0" step="0.1" placeholder="Years"/></label>
      <label>Notice period<input name="notice_period" placeholder="e.g. 30 days"/></label>
      <label>Stage<select name="stage"><option value="">All stages</option>${['Sourced','Screened','Interview','Offered','Joined','Rejected'].map(s=>`<option>${s}</option>`).join('')}</select></label>
      <label>Talent pool<select name="talent_pool" id="tpPoolSelect"><option value="">All candidates</option></select></label>
      <div class="row"><button class="btn" type="submit">Search</button><button class="ghost" type="reset">Clear</button></div>
    </form><p id="tpStatus" role="status" aria-live="polite"></p><div id="tpResults"></div>`;
  const form = document.getElementById('tpFilters');
  const status = document.getElementById('tpStatus');
  const results = document.getElementById('tpResults');
  async function read(url, options) {
    const response = await fetch(url, {cache:'no-store', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not complete this request. Please retry.');
    return data;
  }
  async function search() {
    const current = ++requestId;
    const params = new URLSearchParams();
    for (const [key,value] of new FormData(form)) if (value.trim()) params.set(key,value.trim());
    if (params.has('min_experience') && params.has('max_experience') && +params.get('min_experience') > +params.get('max_experience')) { status.textContent='Minimum experience must be less than or equal to maximum experience.'; results.replaceChildren(); return; }
    status.textContent='Loading candidates…'; results.replaceChildren();
    try {
      const list = await read('/api/candidates?'+params);
      if (current !== requestId) return;
      status.textContent=`${list.length} candidate${list.length===1?'':'s'} found${params.get('talent_pool')?' in '+params.get('talent_pool'):''}. Candidates can belong to multiple pools.`;
      results.innerHTML=list.length?`<div class="tp-table-wrap"><table class="tp-table"><thead><tr><th>Candidate</th><th>Experience / location</th><th>Skills / pools</th><th>Notice / stage</th><th>Actions</th></tr></thead><tbody>${list.map(c=>`<tr><td><b>${safe(c.name)}</b><small>${safe(c.email||c.phone||'No contact added')}</small></td><td>${safe(c.experience??'—')}${c.experience!=null?' years':''}<small>${safe(c.profile_details?.current_location||'Location not added')}</small></td><td><div class="tp-skills">${safe(c.skills||'Skills not added')}</div><small>${(c.talent_pools||[]).map(safe).join(' · ')||'Unassigned'}</small></td><td>${safe(c.notice_period||'Not added')}<small>${safe(c.stage)}</small></td><td><div class="row"><button class="ghost" data-view="${c.id}">View</button><button class="ghost" data-edit="${c.id}">Edit</button></div></td></tr>`).join('')}</tbody></table></div>`:'<div class="card">No candidates match these filters. Try another skill or clear the filters.</div>';
      results.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>window.openCandidate(Number(b.dataset.view)));
      results.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>edit(Number(b.dataset.edit)));
      document.querySelectorAll('#tpPools button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.pool===form.elements.talent_pool.value)));
    } catch(e) { if(current===requestId) status.textContent=e.message; }
  }
  async function load() {
    try {
      const pools=await read('/api/talent-pools');
      const selected=form.elements.talent_pool.value;
      const names=pools.map(p=>p.name); if(selected&&!names.includes(selected)) names.push(selected);
      form.elements.talent_pool.innerHTML='<option value="">All candidates</option>'+names.map(n=>`<option value="${safe(n)}">${safe(n)}</option>`).join('');
      form.elements.talent_pool.value=selected;
      document.getElementById('tpPools').innerHTML=`<button class="ghost" data-pool="">All candidates</button>`+pools.map(p=>`<button class="ghost" data-pool="${safe(p.name)}">${safe(p.name)} <b>${p.count}</b></button>`).join('');
      document.querySelectorAll('#tpPools button').forEach(b=>b.onclick=()=>{form.elements.talent_pool.value=b.dataset.pool;search();});
      await search();
    }catch(e){status.textContent=e.message;}
  }
  async function edit(id) {
    try {
      const c=await read('/api/candidates/'+id), p=c.profile_details||{};
      document.getElementById('modalName').textContent='Edit '+c.name;
      document.getElementById('modalSub').textContent='Update the master profile across all talent pools.';
      const fields=[['name','Name',c.name],['email','Email',c.email],['phone','Phone',c.phone],['experience','Experience (years)',c.experience],['skills','Skills',c.skills],['notice_period','Notice period',c.notice_period],['current_ctc','Current CTC',c.current_ctc],['expected_ctc','Expected CTC',c.expected_ctc],['current_location','Current location',p.current_location],['preferred_location','Preferred location',p.preferred_location],['lwd','Last working day',p.lwd],['holding_offers','Offers',p.holding_offers],['remarks','Remarks',p.remarks],['talent_pools','Talent pools (comma separated)',(c.talent_pools||[]).join(', ')]];
      document.getElementById('modalBody').innerHTML=`<form id="tpEdit"><div class="tp-edit-grid">${fields.map(([key,label,value])=>`<label>${label}<input name="${key}" value="${safe(value)}" ${key==='name'?'required':''} ${key==='experience'?'type="number" min="0" step="0.1"':''}/></label>`).join('')}<label>Stage<select name="stage">${['Sourced','Screened','Interview','Offered','Joined','Rejected'].map(s=>`<option ${c.stage===s?'selected':''}>${s}</option>`).join('')}</select></label></div><p id="tpEditStatus" role="status"></p><div class="row"><button class="btn" type="submit">Save changes</button><button class="ghost" type="button" id="tpCancel">Cancel</button></div></form><details class="tp-history"><summary>Activity history</summary>${(c.activity||[]).map(a=>`<p><b>${safe(a.action)}</b> · ${safe(a.created_at)}<br/>${safe(a.details)}</p>`).join('')||'<p>No activity yet.</p>'}</details>`;
      document.getElementById('candidateModal').classList.remove('hidden');
      document.getElementById('tpCancel').onclick=window.closeCandidate;
      document.getElementById('tpEdit').onsubmit=async e=>{
        e.preventDefault(); const button=e.target.querySelector('[type=submit]'); button.disabled=true;
        const values=Object.fromEntries(new FormData(e.target));
        const body={...values,experience:values.experience===''?null:Number(values.experience),talent_pools:values.talent_pools.split(',').map(s=>s.trim()).filter(Boolean),profile_details:{}};
        for(const key of ['current_location','preferred_location','lwd','holding_offers','remarks']) {body.profile_details[key]=values[key];delete body[key];}
        for(const key of ['notice_period','current_ctc','expected_ctc']) body.profile_details[key]=values[key];
        try {await read('/api/candidates/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});window.closeCandidate();window.toast('Candidate updated');await load();}catch(error){document.getElementById('tpEditStatus').textContent=error.message;}finally{button.disabled=false;}
      };
    }catch(e){status.textContent=e.message;}
  }
  form.onsubmit=e=>{e.preventDefault();search();};
  form.onreset=()=>setTimeout(search,0);
  document.getElementById('tpRefresh').onclick=load;
  window.loadTalentPool=load;
})();
