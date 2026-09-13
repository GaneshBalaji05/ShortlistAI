(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const pad = value => String(value).padStart(2, '0');

  let candidates = [];
  let interviews = [];
  let editingInterviewId = null;
  let calendarDate = new Date();
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth(), 1);
  let selectedDateKey = dateKey(new Date());

  async function api(url, opt){
    const r = await fetch(url, opt);
    const d = await r.json().catch(() => ({}));
    if(!r.ok) throw new Error(d.detail || 'Request failed');
    return d;
  }

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

  function localDateTimeParts(value){
    const raw = String(value || '');
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? {year:+m[1], month:+m[2], day:+m[3], hour:+m[4], minute:+m[5]} : null;
  }

  function dateFromKey(key){
    const m = String(key || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m ? new Date(Number(m[1]), Number(m[2])-1, Number(m[3])) : new Date();
  }

  function fmtDay(key){
    return dateFromKey(key).toLocaleDateString([], {weekday:'long', month:'long', day:'numeric', year:'numeric'});
  }

  function fmtTime(value){
    const p = localDateTimeParts(value);
    if(p){
      const d = new Date(2000, 0, 1, p.hour, p.minute);
      return d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
    }
    if(!value) return 'Time not set';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 'Time not set' : d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
  }

  function fmtWhen(value){
    const p = localDateTimeParts(value);
    if(p){
      const d = new Date(p.year, p.month-1, p.day, p.hour, p.minute);
      return d.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
    }
    if(!value) return 'Time not set';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
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
            <div class="iv-card-title"><div><h3 id="ivFormTitle">Schedule interview</h3><small id="ivFormSubtitle">Manual scheduling</small></div><span class="iv-mode-pill" id="ivModePill">Manual</span></div>
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
            <div class="row" style="gap:8px">
              <button id="ivCreate" class="btn" type="button" style="flex:1">Schedule interview</button>
              <button id="ivCancelEdit" class="ghost hidden" type="button">Cancel edit</button>
            </div>
            <div class="iv-help">Tap a date to prefill the form. Tap an existing interview to view it, then use Edit / Reschedule if needed.</div>
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

    main.insertBefore(section, $('shortlist') || null);
    $('ivCreate').onclick = saveInterview;
    $('ivCancelEdit').onclick = resetForm;
    $('ivPrevMonth').onclick = () => moveMonth(-1);
    $('ivNextMonth').onclick = () => moveMonth(1);
    $('ivToday').onclick = goToday;
    $('ivUseDate').onclick = () => setManualDate(selectedDateKey, true);
    $('ivWhen').addEventListener('change', () => {
      const key = interviewDateKey($('ivWhen').value);
      if(!key) return;
      selectedDateKey = key;
      const d = dateFromKey(key);
      calendarDate = new Date(d.getFullYear(), d.getMonth(), 1);
      renderCalendar();
      renderAgenda();
    });
  }

  function monthLabel(){
    return calendarDate.toLocaleDateString([], {month:'long', year:'numeric'});
  }

  function moveMonth(delta){
    calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth()+delta, 1);
    renderCalendar();
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

  function openInterviewFromCalendar(interviewId){
    const item = interviews.find(x => String(x.id) === String(interviewId));
    if(!item) return;
    selectCalendarDate(interviewDateKey(item.scheduled_at), false);
    requestAnimationFrame(() => {
      const target = document.querySelector(`[data-agenda-id="${item.id}"]`);
      target?.scrollIntoView({behavior:'smooth', block:'nearest'});
      target?.classList.add('selected');
      setTimeout(() => target?.classList.remove('selected'), 900);
    });
  }

  function interviewMap(){
    const map = new Map();
    interviews.forEach(item => {
      const key = interviewDateKey(item.scheduled_at);
      if(!key) return;
      if(!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    });
    map.forEach(list => list.sort((a,b) => String(a.scheduled_at).localeCompare(String(b.scheduled_at))));
    return map;
  }

  function renderCalendar(){
    const el = $('ivCalendar');
    if(!el) return;
    $('ivCalendarLabel').textContent = monthLabel();
    const map = interviewMap();
    const today = dateKey(new Date());
    const year = calendarDate.getFullYear();
    const month = calendarDate.getMonth();
    const first = new Date(year, month, 1);
    const gridStart = new Date(year, month, 1-first.getDay());
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
        <div class="iv-day-events">${visible.map(x => `<button type="button" class="iv-event ${String(x.status||'').toLowerCase()}" data-interview-id="${x.id}" title="${esc(x.candidate_name)} · ${esc(x.round_name)} · ${esc(fmtTime(x.scheduled_at))}"><span>${esc(fmtTime(x.scheduled_at))}</span>${esc(x.candidate_name)}</button>`).join('')}${dayInterviews.length>2 ? `<button type="button" class="iv-more" data-event-date="${key}">+${dayInterviews.length-2} more</button>` : ''}</div>
      </div>`);
    }

    el.innerHTML = cells.join('');
    el.querySelectorAll('[data-select-date]').forEach(button => button.onclick = () => selectCalendarDate(button.dataset.selectDate, true));
    el.querySelectorAll('[data-interview-id]').forEach(button => button.onclick = () => openInterviewFromCalendar(button.dataset.interviewId));
    el.querySelectorAll('[data-event-date]').forEach(button => button.onclick = () => selectCalendarDate(button.dataset.eventDate, false));
  }

  function agendaItem(x){
    return `<div class="iv-item" data-agenda-id="${x.id}">
      <div class="iv-item-head"><div><b>${esc(x.candidate_name)}</b><small>${esc(x.job_title || 'Unassigned')} • ${esc(x.round_name)} • ${esc(fmtWhen(x.scheduled_at))}</small></div><span class="iv-pill ${String(x.status||'').toLowerCase()}">${esc(x.status)}</span></div>
      <div class="iv-badges"><span class="iv-pill">${esc(x.interviewer_name || 'Interviewer TBD')}</span><span class="iv-pill">${esc(x.outcome || 'Pending')}</span><span class="iv-pill">${esc(x.timezone || 'Asia/Kolkata')}</span></div>
      <div class="iv-actions">
        ${x.meeting_url ? `<a class="primary" href="${esc(x.meeting_url)}" target="_blank" rel="noopener">Join meeting</a>` : ''}
        <a href="/api/interviews/${x.id}/calendar.ics">Calendar invite</a>
        <button data-edit="${x.id}" type="button">Edit / Reschedule</button>
        <button data-complete="${x.id}" type="button">Complete</button>
        <button data-clear="${x.id}" type="button">Mark cleared</button>
        <button data-cancel="${x.id}" type="button">Cancel</button>
      </div>
    </div>`;
  }

  function bindAgendaActions(el){
    el.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => editInterview(b.dataset.edit));
    el.querySelectorAll('[data-complete]').forEach(b => b.onclick = () => patchInterview(b.dataset.complete, {status:'Completed'}));
    el.querySelectorAll('[data-clear]').forEach(b => b.onclick = () => patchInterview(b.dataset.clear, {status:'Completed', outcome:'Cleared'}));
    el.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => patchInterview(b.dataset.cancel, {status:'Cancelled'}));
  }

  function renderAgenda(){
    const el = $('ivList');
    if(!el) return;
    const list = interviews.filter(x => interviewDateKey(x.scheduled_at) === selectedDateKey);
    $('ivAgendaTitle').textContent = fmtDay(selectedDateKey);
    $('ivAgendaCount').textContent = `${list.length} interview${list.length===1?'':'s'}`;
    if(!list.length){
      el.innerHTML = '<div class="iv-empty">No interviews on this date.<br><small>Tap “Use this date” or a calendar day to schedule one.</small></div>';
      return;
    }
    el.innerHTML = list.map(agendaItem).join('');
    bindAgendaActions(el);
  }

  function scheduledTimestamp(item){
    const p = localDateTimeParts(item.scheduled_at);
    if(p) return new Date(p.year, p.month-1, p.day, p.hour, p.minute).getTime();
    return new Date(item.scheduled_at).getTime();
  }

  function setStats(){
    const now = Date.now();
    $('ivScheduled').textContent = interviews.filter(x => x.status === 'Scheduled').length;
    $('ivUpcoming').textContent = interviews.filter(x => x.status === 'Scheduled' && scheduledTimestamp(x) >= now).length;
    $('ivCompleted').textContent = interviews.filter(x => x.status === 'Completed').length;
    $('ivCancelled').textContent = interviews.filter(x => x.status === 'Cancelled').length;
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
        sel.innerHTML = '<option value="">Select candidate</option>' + candidates.map(c => `<option value="${c.id}">${esc(c.name)}${c.job_title ? ' — '+esc(c.job_title) : ''}</option>`).join('');
        if(current) sel.value = current;
      }
      renderList();
    }catch(e){
      window.toast?.(e.message);
    }
  }

  function formPayload(){
    const candidateId = Number($('ivCandidate').value || 0);
    const scheduledAt = $('ivWhen').value;
    if(!candidateId) throw new Error('Select a candidate');
    if(!scheduledAt) throw new Error('Choose interview date and time');
    return {
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
  }

  async function saveInterview(){
    let body;
    try{ body = formPayload(); }
    catch(e){ window.toast?.(e.message); return; }

    try{
      $('ivCreate').disabled = true;
      if(editingInterviewId){
        await api(`/api/interviews/${editingInterviewId}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        window.toast?.('Interview rescheduled');
      }else{
        await api('/api/interviews', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        window.toast?.('Interview scheduled');
      }
      selectedDateKey = interviewDateKey(body.scheduled_at) || selectedDateKey;
      const selected = dateFromKey(selectedDateKey);
      calendarDate = new Date(selected.getFullYear(), selected.getMonth(), 1);
      resetForm(false);
      await loadInterviews();
    }catch(e){
      window.toast?.(e.message);
    }finally{
      $('ivCreate').disabled = false;
    }
  }

  function editInterview(id){
    const item = interviews.find(x => String(x.id) === String(id));
    if(!item) return;
    editingInterviewId = item.id;
    $('ivCandidate').value = String(item.candidate_id);
    $('ivRound').value = item.round_name || 'L1';
    $('ivDuration').value = String(item.duration_minutes || 45);
    $('ivWhen').value = String(item.scheduled_at || '').slice(0,16);
    $('ivTimezone').value = item.timezone || 'Asia/Kolkata';
    $('ivInterviewer').value = item.interviewer_name || '';
    $('ivEmail').value = item.interviewer_email || '';
    $('ivMeeting').value = item.meeting_url || '';
    $('ivNotes').value = item.notes || '';
    $('ivFormTitle').textContent = 'Edit interview';
    $('ivFormSubtitle').textContent = 'Update or reschedule this interview';
    $('ivModePill').textContent = 'Editing';
    $('ivCreate').textContent = 'Save changes';
    $('ivCancelEdit').classList.remove('hidden');
    selectedDateKey = interviewDateKey(item.scheduled_at) || selectedDateKey;
    const d = dateFromKey(selectedDateKey);
    calendarDate = new Date(d.getFullYear(), d.getMonth(), 1);
    renderCalendar();
    renderAgenda();
    document.querySelector('.iv-manual-card')?.scrollIntoView({behavior:'smooth', block:'start'});
    $('ivWhen').focus();
  }

  function resetForm(keepDate=true){
    editingInterviewId = null;
    $('ivCandidate').value = '';
    $('ivRound').value = 'L1';
    $('ivDuration').value = '45';
    $('ivTimezone').value = 'Asia/Kolkata';
    $('ivInterviewer').value = '';
    $('ivEmail').value = '';
    $('ivMeeting').value = '';
    $('ivNotes').value = '';
    $('ivFormTitle').textContent = 'Schedule interview';
    $('ivFormSubtitle').textContent = 'Manual scheduling';
    $('ivModePill').textContent = 'Manual';
    $('ivCreate').textContent = 'Schedule interview';
    $('ivCancelEdit').classList.add('hidden');
    if(keepDate) setManualDate(selectedDateKey, false);
    else $('ivWhen').value = `${selectedDateKey}T10:00`;
  }

  async function patchInterview(id, patch){
    try{
      await api(`/api/interviews/${id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)});
      window.toast?.('Interview updated');
      await loadInterviews();
    }catch(e){
      window.toast?.(e.message);
    }
  }

  function injectCandidateAction(candidateId){
    const body = $('modalBody');
    if(!body || body.querySelector('.iv-candidate-action')) return;
    const firstRow = body.querySelector('.row');
    const btn = document.createElement('button');
    btn.className = 'ghost iv-candidate-action';
    btn.type = 'button';
    btn.textContent = 'Schedule interview';
    btn.onclick = async () => {
      window.closeCandidate?.();
      window.showTab?.('interviews');
      await loadInterviews();
      resetForm();
      $('ivCandidate').value = String(candidateId);
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
  setTimeout(loadInterviews, 300);
})();