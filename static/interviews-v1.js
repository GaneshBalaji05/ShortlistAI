(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[m]));
  let candidates = [];
  let interviews = [];
  let calendarDate = new Date();
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth(), 1);
  let selectedDateKey = dateKey(new Date());

  async function api(url, opt){
    const r = await fetch(url, opt);
    const d = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.detail || 'Request failed');
    return d;
  }

  function pad(value){ return String(value).padStart(2,'0'); }

  function dateKey(value){
    const d = value instanceof Date ? value : new Date(value);
    if(Number.isNaN(d.getTime())) return '';
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  }

  function interviewDateKey(value){
    const raw = String(value || '');
    const m = raw.match(/^(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : dateKey(raw);
  }

  function dateFromKey(key){
    const m = String(key || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m ? new Date(Number(m[1]), Number(m[2])-1, Number(m[3])) : new Date();
  }

  function fmtDay(key){
    const d = dateFromKey(key);
    return d.toLocaleDateString([], {weekday:'long', month:'long', day:'numeric', year:'numeric'});
  }

  function fmtTime(value){
    if(!value) return 'Time not set';
    const d = new Date(value);
    if(!Number.isNaN(d.getTime())) return d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
    const m = String(value).match(/T(\d{2}:\d{2})/);
    return m ? m[1] : 'Time not set';
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
        <div class="iv-top"><div><div class="eyebrow">Interview operations</div><h1>Interviews</h1><p>Schedule manually or use the interactive calendar to plan and manage every round.</p></div></div>
        <div class="iv-stats">
          <div class="iv-stat"><small>Scheduled</small><b id="ivScheduled">0</b></div>
          <div class="iv-stat"><small>Upcoming</small><b id="ivUpcoming">0</b></div>
          <div class="iv-stat"><small>Completed</small><b id="ivCompleted">0</b></div>
          <div class="iv-stat"><small>Cancelled</small><b id="ivCancelled">0</b></div>
        </div>
        <div class="iv-grid">
          <div class="iv-card iv-manual-card">
            <div class="iv-card-title"><div><h3>Schedule interview</h3><small>Manual scheduling</small></div><span class="iv-mode-pill">Manual</span></div>
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
            <div class="iv-help">Tip: tap any date in the calendar to prefill this form. Zoom auto-creation can be connected later through OAuth.</div>
          </div>
          <div class="iv-card iv-calendar-card">
            <div class="iv-calendar-head">
              <div><h3>Interview calendar</h3><small id="ivCalendarLabel">Calendar</small></div>
              <div class="iv-calendar-controls">
                <button id="ivPrevMonth" type="button" aria-label="Previous month">‹</button>
                <button id="ivToday" type="button">Today</button>
                <button id="ivNextMonth" type="button" aria-label="Next month">›</button>
              </div>
            </div>
            <div class="iv-weekdays" aria-hidden="true"><span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span></div>
            <div id="ivCalendar" class="iv-calendar" aria-label="Interview calendar"></div>
            <div class="iv-agenda-head"><div><h4 id="ivAgendaTitle">Selected day</h4><small id="ivAgendaCount">0 interviews</small></div><button id="ivUseDate" type="button" class="iv-secondary">Use this date</button></div>
            <div id="ivList" class="iv-list"></div>
          </div>
        </div>
      </div>`;
    const shortlist = $('shortlist');
    main.insertBefore(section, shortlist || null);

    $('ivCreate').onclick = createInterview;
    $('ivPrevMonth').onclick = () => moveMonth(-1);
    $('ivNextMonth').onclick = () => moveMonth(1);
    $('ivToday').onclick = goToday;
    $('ivUseDate').onclick = () => setManualDate(selectedDateKey, true);
    $('ivWhen').addEventListener('change', () => {
      const key = interviewDateKey($('ivWhen').value);
      if(key){
        selectedDateKey = key;
        const d = dateFromKey(key);
        calendarDate = new Date(d.getFullYear(), d.getMonth(), 1);
        renderCalendar();
        renderAgenda();
      }
    });
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

  function monthLabel(){
    return calendarDate.toLocaleDateString([], {month:'long', year:'numeric'});
  }

  function moveMonth(delta){
    calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth()+delta, 1);
    selectedDateKey = dateKey(calendarDate);
    renderCalendar();
    renderAgenda();
  }

  function goToday(){
    const now = new Date();
    calendarDate = new Date(now.getFullYear(), now.getMonth(), 1);
    selectedDateKey = dateKey(now);
    renderCalendar();
    renderAgenda();
  }

  function setManualDate(key, focus){
    if(!key || !$('ivWhen')) return;
    const existing = $('ivWhen').value;
    const time = (existing.match(/T(\d{2}:\d{2})/) || [,'10:00'])[1];
    $('ivWhen').value = `${key}T${time}`;
    if(focus) $('ivWhen').focus();
  }

  function selectCalendarDate(key, useInForm){
    selectedDateKey = key;
    const d = dateFromKey(key);
    calendarDate = new Date(d.getFullYear(), d.getMonth(), 1);
    if(useInForm) setManualDate(key, false);
    renderCalendar();
    renderAgenda();
  }

  function interviewMap(){
    const map = new Map();
    interviews.forEach(item => {
      const key = interviewDateKey(item.scheduled_at);
      if(!key) return;
      if(!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    });
    map.forEach(list => list.sort((a,b)=>String(a.scheduled_at).localeCompare(String(b.scheduled_at))));
    return map;
  }

  function renderCalendar(){
    const el = $('ivCalendar'); if(!el) return;
    $('ivCalendarLabel').textContent = monthLabel();
    const map = interviewMap();
    const today = dateKey(new Date());
    const year = calendarDate.getFullYear();
    const month = calendarDate.getMonth();
    const first = new Date(year, month, 1);
    const gridStart = new Date(year, month, 1 - first.getDay());
    const cells = [];

    for(let i=0;i<42;i++){
      const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate()+i);
      const key = dateKey(d);
      const dayInterviews = map.get(key) || [];
      const classes = ['iv-day'];
      if(d.getMonth() !== month) classes.push('outside');
      if(key === today) classes.push('today');
      if(key === selectedDateKey) classes.push('selected');
      const visible = dayInterviews.slice(0,2);
      cells.push(`<div class="${classes.join(' ')}" data-date="${key}">
        <button type="button" class="iv-day-number" data-select-date="${key}" aria-label="Select ${esc(fmtDay(key))}">${d.getDate()}</button>
        <div class="iv-day-events">${visible.map(x=>`<button type="button" class="iv-event ${String(x.status||'').toLowerCase()}" data-event-date="${key}" title="${esc(x.candidate_name)} · ${esc(x.round_name)} · ${esc(fmtTime(x.scheduled_at))}"><span>${esc(fmtTime(x.scheduled_at))}</span>${esc(x.candidate_name)}</button>`).join('')}${dayInterviews.length>2?`<button type="button" class="iv-more" data-event-date="${key}">+${dayInterviews.length-2} more</button>`:''}</div>
      </div>`);
    }
    el.innerHTML = cells.join('');
    el.querySelectorAll('[data-select-date]').forEach(button => button.onclick = () => selectCalendarDate(button.dataset.selectDate, true));
    el.querySelectorAll('[data-event-date]').forEach(button => button.onclick = () => selectCalendarDate(button.dataset.eventDate, false));
  }

  function agendaItem(x){
    return `<div class="iv-item">
      <div class="iv-item-head"><div><b>${esc(x.candidate_name)}</b><small>${esc(x.job_title || 'Unassigned')} • ${esc(x.round_name)} • ${fmtWhen(x.scheduled_at)}</small></div><span class="iv-pill ${String(x.status||'').toLowerCase()}">${esc(x.status)}</span></div>
      <div class="iv-badges"><span class="iv-pill">${esc(x.interviewer_name || 'Interviewer TBD')}</span><span class="iv-pill">${esc(x.outcome || 'Pending')}</span><span class="iv-pill">${esc(x.timezone || '')}</span></div>
      <div class="iv-actions">
        ${x.meeting_url ? `<a class="primary" href="${esc(x.meeting_url)}" target="_blank" rel="noopener">Join meeting</a>` : ''}
        <a href="/api/interviews/${x.id}/calendar.ics">Calendar invite</a>
        <button data-complete="${x.id}" type="button">Complete</button>
        <button data-clear="${x.id}" type="button">Mark cleared</button>
        <button data-cancel="${x.id}" type="button">Cancel</button>
      </div>
    </div>`;
  }

  function bindAgendaActions(el){
    el.querySelectorAll('[data-complete]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.complete,{status:'Completed'}));
    el.querySelectorAll('[data-clear]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.clear,{status:'Completed',outcome:'Cleared'}));
    el.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=()=>patchInterview(b.dataset.cancel,{status:'Cancelled'}));
  }

  function renderAgenda(){
    const el = $('ivList'); if(!el) return;
    const list = interviews.filter(x=>interviewDateKey(x.scheduled_at)===selectedDateKey);
    $('ivAgendaTitle').textContent = fmtDay(selectedDateKey);
    $('ivAgendaCount').textContent = `${list.length} interview${list.length===1?'':'s'}`;
    if(!list.length){
      el.innerHTML='<div class="iv-empty">No interviews on this date.<br><small>Tap “Use this date” or a calendar day to schedule one.</small></div>';
      return;
    }
    el.innerHTML = list.map(agendaItem).join('');
    bindAgendaActions(el);
  }

  function renderList(){
    setStats();
    renderCalendar();
    renderAgenda();
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
      selectedDateKey = interviewDateKey(scheduledAt) || selectedDateKey;
      const selected = dateFromKey(selectedDateKey);
      calendarDate = new Date(selected.getFullYear(), selected.getMonth(), 1);
      $('ivInterviewer').value=$('ivEmail').value=$('ivMeeting').value=$('ivNotes').value='';
      setManualDate(selectedDateKey, false);
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
      setManualDate(selectedDateKey, true);
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
  setManualDate(selectedDateKey, false);
  setTimeout(loadInterviews,300);
})();
