(() => {
  const dashboard = document.getElementById('dashboard');
  if (!dashboard) return;

  let payload = null;
  let selectedJobId = '';

  const safe = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const pct = (value, total) => total ? Math.round((value / total) * 100) : 0;

  function candidateSet() {
    if (!payload) return [];
    if (!selectedJobId) return payload.candidates || [];
    return (payload.candidates || []).filter(c => String(c.job_id || '') === String(selectedJobId));
  }

  function metricsFor(candidates) {
    const hired = candidates.filter(c => c.stage === 'Joined').length;
    const dropped = candidates.filter(c => c.stage === 'Rejected').length;
    return {
      profiles_sourced: candidates.length,
      in_pipeline: Math.max(0, candidates.length - hired - dropped),
      l1_cleared: candidates.filter(c => c.l1_status === 'Cleared').length,
      l2_cleared: candidates.filter(c => c.l2_status === 'Cleared').length,
      hired,
      dropped,
      yet_to_schedule_l1: candidates.filter(c => c.l1_status === 'Pending Scheduling' && !['Joined','Rejected'].includes(c.stage)).length,
      yet_to_schedule_l2: candidates.filter(c => c.l1_status === 'Cleared' && c.l2_status === 'Pending Scheduling' && !['Joined','Rejected'].includes(c.stage)).length,
      strong: candidates.filter(c => c.rating === 'Strong').length,
      average: candidates.filter(c => c.rating === 'Average').length,
      weak: candidates.filter(c => c.rating === 'Weak').length,
      ai_screened: candidates.filter(c => c.rating).length,
      offered: candidates.filter(c => ['Offered','Joined'].includes(c.stage)).length,
    };
  }

  function renderShell() {
    dashboard.innerHTML = `
      <div class="dashv2-hidden-legacy" aria-hidden="true">
        <span id="sJobs">0</span><span id="sCandidates">0</span><span id="sInterviews">0</span><span id="sOffers">0</span><span id="sJoined">0</span>
      </div>
      <div class="dashv2">
        <div class="dashv2-top">
          <div>
            <div class="eyebrow">Recruitment command center</div>
            <h1>Hiring Dashboard</h1>
            <p>Track every requirement from sourcing to joining, with AI quality and pending actions in one place.</p>
          </div>
          <div class="dashv2-filter">
            <label for="dashJobFilter">Requirement</label>
            <select id="dashJobFilter"><option value="">All active jobs</option></select>
          </div>
        </div>

        <div id="dashKpis" class="dashv2-kpis"></div>
        <div id="dashActions" class="dashv2-actions"></div>
        <div id="dashDrill" class="dashv2-drill hidden"></div>

        <div class="dashv2-grid">
          <div class="dashv2-card">
            <h3>Recruitment funnel</h3><div class="sub">Click any stage to see the candidates behind the number.</div>
            <div id="dashFunnel" class="dashv2-funnel"></div>
          </div>
          <div class="dashv2-card">
            <h3>AI candidate quality</h3><div class="sub">Strong / Average / Weak distribution for the selected requirement.</div>
            <div id="dashAi" class="dashv2-ai"></div>
          </div>
        </div>

        <div class="dashv2-grid">
          <div class="dashv2-card"><h3>Active jobs</h3><div class="sub">Requirement-level pipeline snapshot.</div><div id="dashJobs" class="dashv2-jobs"></div></div>
          <div class="dashv2-card"><h3>Recent activity</h3><div class="sub">Latest candidate movements and AI outcomes.</div><div id="dashActivity" class="dashv2-activity"></div></div>
        </div>

        <div class="dashv2-card"><h3>Candidate sources</h3><div class="sub">Where your current pipeline is coming from.</div><div id="dashSources" class="dashv2-source"></div></div>
      </div>`;

    const select = document.getElementById('dashJobFilter');
    (payload.jobs || []).forEach(job => {
      const opt = document.createElement('option');
      opt.value = job.id;
      opt.textContent = job.title;
      select.appendChild(opt);
    });
    select.value = selectedJobId;
    select.onchange = () => { selectedJobId = select.value; renderData(); };
  }

  function filterCandidates(type) {
    const all = candidateSet();
    const map = {
      sourced: c => true,
      pipeline: c => !['Joined','Rejected'].includes(c.stage),
      l1: c => c.l1_status === 'Cleared',
      l2: c => c.l2_status === 'Cleared',
      hired: c => c.stage === 'Joined',
      dropped: c => c.stage === 'Rejected',
      scheduleL1: c => c.l1_status === 'Pending Scheduling' && !['Joined','Rejected'].includes(c.stage),
      scheduleL2: c => c.l1_status === 'Cleared' && c.l2_status === 'Pending Scheduling' && !['Joined','Rejected'].includes(c.stage),
      screened: c => Boolean(c.rating),
      offered: c => ['Offered','Joined'].includes(c.stage),
      strong: c => c.rating === 'Strong',
      average: c => c.rating === 'Average',
      weak: c => c.rating === 'Weak',
    };
    return all.filter(map[type] || (() => true));
  }

  function drill(type, title) {
    const list = filterCandidates(type);
    const box = document.getElementById('dashDrill');
    box.innerHTML = `<div class="dashv2-drill-head"><div><b>${safe(title)}</b><div class="sub">${list.length} candidate${list.length === 1 ? '' : 's'}</div></div><button id="dashCloseDrill" class="ghost" type="button">Close</button></div>
      <div class="dashv2-drill-list">${list.length ? list.map(c => `<div class="dashv2-person" data-candidate="${c.id}"><b>${safe(c.name)}</b><small>${safe(c.job_title)} • ${safe(c.stage)}</small><span class="dashv2-badge">${safe(c.rating || 'Not rated')} ${c.ai_score ?? ''}</span></div>`).join('') : '<div class="dashv2-empty">No candidates in this group.</div>'}</div>`;
    box.classList.remove('hidden');
    document.getElementById('dashCloseDrill').onclick = () => box.classList.add('hidden');
    box.querySelectorAll('[data-candidate]').forEach(el => el.onclick = () => window.openCandidate && window.openCandidate(Number(el.dataset.candidate)));
    box.scrollIntoView({behavior:'smooth', block:'nearest'});
  }

  function renderData() {
    const candidates = candidateSet();
    const m = metricsFor(candidates);
    const kpis = [
      ['Profiles sourced', m.profiles_sourced, 'All profiles mapped to this requirement', 'sourced'],
      ['In pipeline', m.in_pipeline, 'Still active in the hiring process', 'pipeline'],
      ['L1 cleared', m.l1_cleared, 'Candidates who passed L1', 'l1'],
      ['L2 cleared', m.l2_cleared, 'Candidates who passed L2', 'l2'],
      ['Hired', m.hired, 'Joined candidates', 'hired'],
      ['Dropped', m.dropped, 'Rejected / closed candidates', 'dropped'],
    ];
    document.getElementById('dashKpis').innerHTML = kpis.map(x => `<button class="dashv2-kpi" data-filter="${x[3]}"><small>${x[0]}</small><b>${x[1]}</b><span>${x[2]}</span></button>`).join('');
    document.querySelectorAll('#dashKpis [data-filter]').forEach(el => el.onclick = () => drill(el.dataset.filter, el.querySelector('small').textContent));

    document.getElementById('dashActions').innerHTML = `
      <div class="dashv2-action" data-filter="scheduleL1"><div class="copy"><b>Yet to schedule L1</b><small>Candidates ready for first-round scheduling</small></div><div class="count">${m.yet_to_schedule_l1}</div></div>
      <div class="dashv2-action" data-filter="scheduleL2"><div class="copy"><b>Yet to schedule L2</b><small>L1-cleared candidates waiting for next round</small></div><div class="count">${m.yet_to_schedule_l2}</div></div>`;
    document.querySelectorAll('#dashActions [data-filter]').forEach(el => el.onclick = () => drill(el.dataset.filter, el.querySelector('b').textContent));

    const funnel = [
      ['Sourced',m.profiles_sourced,'sourced'],['AI Screened',m.ai_screened,'screened'],['L1 Cleared',m.l1_cleared,'l1'],['L2 Cleared',m.l2_cleared,'l2'],['Offer',m.offered,'offered'],['Hired',m.hired,'hired']
    ];
    document.getElementById('dashFunnel').innerHTML = funnel.map(x => `<div class="dashv2-step" data-filter="${x[2]}"><small>${x[0]}</small><b>${x[1]}</b></div>`).join('');
    document.querySelectorAll('#dashFunnel [data-filter]').forEach(el => el.onclick = () => drill(el.dataset.filter, el.querySelector('small').textContent));

    const totalAi = Math.max(1, m.strong + m.average + m.weak);
    document.getElementById('dashAi').innerHTML = [
      ['Strong',m.strong,'strong'],['Average',m.average,'average'],['Weak',m.weak,'weak']
    ].map(([label,value,cls]) => `<div class="dashv2-ai-row ${cls}"><label>${label}</label><div class="dashv2-ai-track"><i style="width:${pct(value,totalAi)}%"></i></div><button data-filter="${cls}">${value}</button></div>`).join('');
    document.querySelectorAll('#dashAi [data-filter]').forEach(el => el.onclick = () => drill(el.dataset.filter, `${el.closest('.dashv2-ai-row').querySelector('label').textContent} candidates`));

    const jobs = payload.jobs || [];
    document.getElementById('dashJobs').innerHTML = jobs.length ? jobs.map(job => {
      const jm = job.metrics || {};
      return `<div class="dashv2-job" data-job="${job.id}"><div class="dashv2-job-top"><div><b>${safe(job.title)}</b><small>${safe(job.department || '')}${job.location ? ' • '+safe(job.location) : ''}</small></div><span class="badge Strong">${safe(job.status || 'Open')}</span></div><div class="dashv2-job-metrics"><span><strong>${jm.profiles_sourced || 0}</strong>Sourced</span><span><strong>${jm.in_pipeline || 0}</strong>Pipeline</span><span><strong>${jm.l2_cleared || 0}</strong>L2 cleared</span><span><strong>${jm.hired || 0}</strong>Hired</span></div></div>`;
    }).join('') : '<div class="dashv2-empty">No jobs yet.</div>';
    document.querySelectorAll('#dashJobs [data-job]').forEach(el => el.onclick = () => {
      selectedJobId = el.dataset.job;
      document.getElementById('dashJobFilter').value = selectedJobId;
      renderData();
      window.scrollTo({top:0,behavior:'smooth'});
    });

    const recent = (payload.recent_activity || []).filter(a => !selectedJobId || String((payload.candidates || []).find(c => c.id === a.candidate_id)?.job_id || '') === String(selectedJobId)).slice(0,6);
    document.getElementById('dashActivity').innerHTML = recent.length ? recent.map(a => `<div class="dashv2-activity-item" data-candidate="${a.candidate_id}"><span class="dashv2-dot"></span><div class="dashv2-activity-copy"><b>${safe(a.candidate)}</b><small>${safe(a.job_title)} • ${safe(a.stage)}${a.rating ? ' • '+safe(a.rating) : ''}</small></div></div>`).join('') : '<div class="dashv2-empty">No recent candidate activity.</div>';
    document.querySelectorAll('#dashActivity [data-candidate]').forEach(el => el.onclick = () => window.openCandidate && window.openCandidate(Number(el.dataset.candidate)));

    const sources = {};
    candidates.forEach(c => { sources[c.source || 'Unknown'] = (sources[c.source || 'Unknown'] || 0) + 1; });
    const max = Math.max(1, ...Object.values(sources));
    document.getElementById('dashSources').innerHTML = Object.keys(sources).length ? Object.entries(sources).sort((a,b)=>b[1]-a[1]).map(([name,value]) => `<div class="dashv2-source-row"><span>${safe(name)}</span><div class="dashv2-source-track"><i style="width:${Math.round(value/max*100)}%"></i></div><b>${value}</b></div>`).join('') : '<div class="dashv2-empty">No source data available.</div>';
  }

  async function boot() {
    try {
      const response = await fetch('/api/dashboard-v2', {cache:'no-store'});
      if (!response.ok) throw new Error('Dashboard data could not be loaded');
      payload = await response.json();
      renderShell();
      renderData();
    } catch (error) {
      console.error(error);
    }
  }

  boot();
})();
