(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  let candidates = [];
  let interviews = [];

  async function api(url, opt){
    const r = await fetch(url, opt);
    const d = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.detail || 'Request failed');
    return d;
  }

  function addModule(){
    const nav = document.querySelector('.nav');
    const main = document.querySelector('main.main');
    if(!nav || !main || $('interviews')) return;

    const btn = document.createElement('button');
    btn.dataset.tab = 'interviews';
    btn.innerHTML = '<span class="nav-icon">◫</span>Interviews';
    const aiBtn = nav.querySelector('[data-tab="shortlist"]');
    nav.insertBefore(btn, aiBtn || null);
    btn.onclick = () => { window.showTab?.('interviews'); loadInterviews(); };

    const section = document.createElement('section');
    section.id = 'interviews';
    section.className = 'section';
    section.innerHTML = `
      <div class="interviews-v1">
        <div class="iv-top"><div><div class="eyebrow">Interview operations</div><h1>Interviews</h1><p>Schedule rounds, keep Zoom links and download calendar invites from ShortlistAI.</p></div></div>
        <div class="iv-stats">
          <div class="iv-stat"><small>Scheduled</small><b id="ivScheduled">0</b></div>
          <div class="iv-stat"><small>Upcoming</small><b id="ivUpcoming">0</b></div>
          <div class="iv-stat"><small>Completed</small><b id="ivCompleted">0</b></div>
          <div class="iv-stat"><small>Cancelled</small><b id="ivCancelled">0</b></div>
        </div>
        <div class="iv-grid">
          <div class="iv-card">
            <h3>Schedule interview</h3>
            <div class="iv-field"><label>Candidate</label><select id="ivCandidate"><option value="">Select candidate</option></select></div>
            <div class="iv-form-grid">
              <div class="iv-field"><label>Round</label><select id="ivRound"><option>L1</option><option>L2</option><option>Technical</option><option>Hiring Manager</option><option>HR</option><option>Common Discussion</option></select></div>
              <div class="iv-field"><label>Duration</label><select id="ivDuration"><option value="30">30 minutes</option><option value="45" selected>45 minutes</option><option value="60">60 minutes</option><option value="90">90 minutes</option></select></div>
              <div class="iv-field"><label>Date & time</label><input id="ivWhen" type="datetime-local"/></div>
              <div class="iv-field"><label>Timezone</label><select id="ivTimezone"><option>Asia/Kolkata</option><option>UTC</option><option>Asia/Singapore</option><option>Europe/London</option><option>America/New_York</option></select></div>
              <div class="iv-field"><label>Interviewer name</label><input id="ivInterviewer" placeholder="Interviewer name"/></div>
              <div class="iv-field"><label>Interviewer email</label><input id="ivEmail" type="email" placeholder="name@company.com"/></div>
            </div>
            <div class="iv-field"><label>Zoom / meeting link</label><input id="ivMeeting" placeholder="https://zoom.us/j/..."/></div>
            <div class="iv-field"><label>Notes</label><textarea id="ivNotes" placeholder="Round focus, panel details, instructions..."></textarea></div>
            <button id="ivCreate" class="btn" type="button" style="width:100%">Schedule interview</button>
            <div class="iv-help">Zoom auto-creation will be connected later through OAuth. For now, paste the meeting link and ShortlistAI will store it with the interview and calendar invite.</div>
          </div>
          <div class="iv-card"><h3>Interview schedule</h3><div id="ivList" class="iv-list"></div></div>
        </div>
      </div>`;
    const shortlist = $('shortlist');
    main.insertBefore(section, shortlist || null);

    $('ivCreate').onclick = createInterview;
  }

  function fmtWhen(value){
    if(!value) return 'Time not set';
    const d = new Date(value);
    if(Number.isNaN(d.getTime())) return value;
    return d.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
  }

  function setStats(){
    const now = Date.now();
    $('ivScheduled').textContent = interviews.filter(x=>x.status==='Scheduled').length;
    $('ivUpcoming').textContent = interviews.filter(x=>x.status==='Scheduled' && new Date(x.scheduled_at).getTime() >= now).length;
    $('ivCompleted').textContent = interviews.filter(x=>x.status==='Completed').length;
    $('ivCancelled').textContent = interviews.filter(x=>x.status==='Cancelled').length;
  }

  function renderList(){
    const el = $('ivList'); if(!el) return;
    setStats();
    if(!interviews.length){el.innerHTML='<div class="iv-empty">No interviews scheduled yet.</div>';return;}
    el.innerHTML = interviews.map(x => `<div class="iv-item">
      <div class="iv-item-head"><div><b>${esc(x.candidate_name)}</b><small>${esc(x.job_title || 'Unassigned')} • ${esc(x.round_name)} • ${fmtWhen(x.scheduled_at)}</small></div><span class="iv-pill ${String(x.status||'').toLowerCase()}">${esc(x.status)}</span></div>
      <div class="iv-badges"><span class="iv-pill">${esc(x.interviewer_name || 'Interviewer TBD')}</span><span class="iv-pill">${esc(x.outcome || 'Pending')}</span><span class="iv-pill">${esc(x.timezone || '')}</span></div>
      <div class="iv-actions">
        ${x.meeting_url ? `<a class="primary" href="${esc(x.meeting_url)}" target="_blank" rel="noopener">Join meeting</a>` : ''}
        <a href="/api/interviews/${x.id}/calendar.ics">Calendar invite</a>
        <button data-complete="${x.id}" type="button">Complete</button>
        <button data-clear="${x.id}" type="button">Mark cleared</button>
        <button data-cancel="${x.id}" type="button">Cancel</button>
      </div>
    </div>`).join('');
    el.querySelectorAll('[data-complete]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.complete,{status:'Completed'}));
    el.querySelectorAll('[data-clear]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.clear,{status:'Completed',outcome:'Cleared'}));
    el.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.cancel,{status:'Cancelled'}));
  }

  async function loadInterviews(){
    try{
      [candidates, interviews] = await Promise.all([api('/api/candidates'), api('/api/interviews')]);
      const sel = $('ivCandidate');
      if(sel){
        const current = sel.value;
        sel.innerHTML = '<option value="">Select candidate</option>' + candidates.map(c=>`<option value="${c.id}">${esc(c.name)}${c.job_title?' — '+esc(c.job_title):''}</option>`).join('');
        if(current) sel.value = current;
      }
      renderList();
    }catch(e){window.toast?.(e.message);}
  }

  async function createInterview(){
    const candidateId = Number($('ivCandidate').value || 0);
    const scheduledAt = $('ivWhen').value;
    if(!candidateId){window.toast?.('Select a candidate');return;}
    if(!scheduledAt){window.toast?.('Choose interview date and time');return;}
    const body = {
      candidate_id:candidateId,
      round_name:$('ivRound').value,
      duration_minutes:Number($('ivDuration').value || 45),
      scheduled_at:scheduledAt,
      timezone:$('ivTimezone').value,
      interviewer_name:$('ivInterviewer').value,
      interviewer_email:$('ivEmail').value,
      meeting_url:$('ivMeeting').value,
      notes:$('ivNotes').value
    };
    try{
      $('ivCreate').disabled=true;
      await api('/api/interviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      window.toast?.('Interview scheduled');
      $('ivWhen').value=$('ivInterviewer').value=$('ivEmail').value=$('ivMeeting').value=$('ivNotes').value='';
      await loadInterviews();
    }catch(e){window.toast?.(e.message)}finally{$('ivCreate').disabled=false;}
  }

  async function patchInterview(id, patch){
    try{
      await api(`/api/interviews/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
      window.toast?.('Interview updated');
      await loadInterviews();
    }catch(e){window.toast?.(e.message)}
  }

  function injectCandidateAction(candidateId){
    const body = $('modalBody');
    if(!body || body.querySelector('.iv-candidate-action')) return;
    const firstRow = body.querySelector('.row');
    const btn = document.createElement('button');
    btn.className='ghost iv-candidate-action';
    btn.type='button';
    btn.textContent='Schedule interview';
    btn.onclick=async()=>{
      window.closeCandidate?.();
      window.showTab?.('interviews');
      await loadInterviews();
      if($('ivCandidate')) $('ivCandidate').value=String(candidateId);
      $('ivWhen')?.focus();
    };
    (firstRow || body).appendChild(btn);
  }

  addModule();
  const originalOpen = window.openCandidate;
  if(typeof originalOpen === 'function'){
    window.openCandidate = async function(id){
      await originalOpen(id);
      injectCandidateAction(id);
    };
  }
  setTimeout(loadInterviews,300);
})();
