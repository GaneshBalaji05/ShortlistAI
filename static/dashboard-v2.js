(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  async function getJSON(url){
    const r = await fetch(url, {headers:{'Accept':'application/json'}});
    if(!r.ok) throw new Error('Could not load dashboard data');
    return r.json();
  }

  function stageLabel(stage){
    const map={Sourced:'Sourced',Screened:'Screened',Interview:'Interview',Offered:'Offered',Joined:'Hired',Rejected:'Dropped','L1 Cleared':'L1 Cleared','L2 Cleared':'L2 Cleared'};
    return map[stage] || stage || 'Unknown';
  }

  function ensureShell(){
    const dashboard=$('dashboard');
    if(!dashboard || $('dashV2')) return;
    const stats=dashboard.querySelector('.stats');
    if(!stats) return;
    const wrap=document.createElement('div');
    wrap.id='dashV2';
    wrap.className='dash-v2';
    wrap.innerHTML=`
      <div class="dash-grid dash-grid-main">
        <section class="dash-panel">
          <div class="dash-panel-head"><div><span class="dash-kicker">AI QUALITY</span><h3>Candidate match distribution</h3></div><span class="dash-subtle">Current talent database</span></div>
          <div id="aiDistribution" class="ai-distribution"></div>
        </section>
        <section class="dash-panel">
          <div class="dash-panel-head"><div><span class="dash-kicker">PIPELINE</span><h3>Hiring funnel</h3></div><span class="dash-subtle">Live stage mix</span></div>
          <div id="pipelineSummary" class="pipeline-summary"></div>
        </section>
      </div>
      <div class="dash-grid dash-grid-secondary">
        <section class="dash-panel">
          <div class="dash-panel-head"><div><span class="dash-kicker">ACTIVE REQUIREMENTS</span><h3>Jobs at a glance</h3></div><button class="dash-link" type="button" data-go="jobs">View jobs →</button></div>
          <div id="activeJobs" class="active-jobs"></div>
        </section>
        <section class="dash-panel">
          <div class="dash-panel-head"><div><span class="dash-kicker">ACTIVITY</span><h3>Recent recruiter activity</h3></div><span class="dash-subtle">Latest updates</span></div>
          <div id="recentActivity" class="activity-list"></div>
        </section>
      </div>
      <section class="dash-panel dash-source-panel">
        <div class="dash-panel-head"><div><span class="dash-kicker">SOURCE ANALYTICS</span><h3>Where candidates are coming from</h3></div><span class="dash-subtle">Test + live data</span></div>
        <div id="sourceAnalytics" class="source-bars"></div>
      </section>`;
    stats.insertAdjacentElement('afterend',wrap);
    wrap.querySelectorAll('[data-go]').forEach(btn=>btn.onclick=()=>window.showTab?.(btn.dataset.go));
  }

  function renderDistribution(candidates){
    const counts={Strong:0,Average:0,Weak:0,Unrated:0};
    candidates.forEach(c=>counts[c.rating] !== undefined ? counts[c.rating]++ : counts.Unrated++);
    const total=Math.max(1,candidates.length);
    const el=$('aiDistribution'); if(!el) return;
    el.innerHTML=['Strong','Average','Weak','Unrated'].map(k=>{
      const pct=Math.round((counts[k]/total)*100);
      return `<div class="ai-row ${k.toLowerCase()}"><div class="ai-row-top"><span>${k}</span><b>${counts[k]}</b></div><div class="dash-progress"><i style="width:${pct}%"></i></div><small>${pct}% of candidates</small></div>`;
    }).join('');
  }

  function renderPipeline(candidates){
    const buckets={'Hired':0,'In Pipeline':0,'Dropped':0,'L1 Cleared':0,'L2 Cleared':0};
    candidates.forEach(c=>{
      const s=c.stage||'Sourced';
      if(s==='Joined') buckets.Hired++;
      else if(s==='Rejected') buckets.Dropped++;
      else if(s==='L1 Cleared') buckets['L1 Cleared']++;
      else if(s==='L2 Cleared') buckets['L2 Cleared']++;
      else buckets['In Pipeline']++;
    });
    const el=$('pipelineSummary'); if(!el) return;
    el.innerHTML=Object.entries(buckets).map(([k,v])=>`<div class="pipe-card"><span>${esc(k)}</span><b>${v}</b></div>`).join('');
  }

  function renderJobs(jobs,candidates){
    const el=$('activeJobs'); if(!el) return;
    if(!jobs.length){el.innerHTML='<div class="dash-empty">No jobs yet.</div>';return;}
    el.innerHTML=jobs.slice(0,5).map(j=>{
      const related=candidates.filter(c=>Number(c.job_id)===Number(j.id));
      const strong=related.filter(c=>c.rating==='Strong').length;
      const active=related.filter(c=>!['Joined','Rejected'].includes(c.stage)).length;
      return `<button class="job-row" type="button" data-go="jobs"><div><b>${esc(j.title)}</b><small>${esc(j.department||'General')} ${j.location?'• '+esc(j.location):''}</small></div><div class="job-metrics"><span><b>${related.length}</b> candidates</span><span><b>${strong}</b> strong</span><span><b>${active}</b> active</span></div></button>`;
    }).join('');
    el.querySelectorAll('[data-go]').forEach(btn=>btn.onclick=()=>window.showTab?.('jobs'));
  }

  function renderActivity(candidates){
    const el=$('recentActivity'); if(!el) return;
    const items=[...candidates].sort((a,b)=>String(b.updated_at||b.created_at||'').localeCompare(String(a.updated_at||a.created_at||''))).slice(0,6);
    if(!items.length){el.innerHTML='<div class="dash-empty">No recent activity yet.</div>';return;}
    el.innerHTML=items.map(c=>`<div class="activity-item"><span class="activity-dot"></span><div><b>${esc(c.name)}</b><p>${esc(stageLabel(c.stage))}${c.job_title?' • '+esc(c.job_title):''}</p></div><span class="activity-score ${String(c.rating||'').toLowerCase()}">${c.ai_score??'—'}</span></div>`).join('');
  }

  function renderSources(candidates){
    const counts={}; candidates.forEach(c=>{const s=(c.source||'Unknown').trim()||'Unknown';counts[s]=(counts[s]||0)+1;});
    const rows=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,8);
    const max=Math.max(1,...rows.map(x=>x[1]));
    const el=$('sourceAnalytics'); if(!el) return;
    if(!rows.length){el.innerHTML='<div class="dash-empty">No source data yet.</div>';return;}
    el.innerHTML=rows.map(([s,v])=>`<div class="source-row"><div class="source-label"><span>${esc(s)}</span><b>${v}</b></div><div class="dash-progress"><i style="width:${Math.round(v/max*100)}%"></i></div></div>`).join('');
  }

  async function refreshDashboardV2(){
    try{
      ensureShell();
      const [jobs,candidates]=await Promise.all([getJSON('/api/jobs'),getJSON('/api/candidates')]);
      renderDistribution(candidates);renderPipeline(candidates);renderJobs(jobs,candidates);renderActivity(candidates);renderSources(candidates);
    }catch(err){console.warn('Dashboard v2:',err);}
  }

  const originalShowTab=window.showTab;
  if(typeof originalShowTab==='function'){
    window.showTab=function(id){originalShowTab(id);if(id==='dashboard')setTimeout(refreshDashboardV2,0);};
  }
  document.addEventListener('DOMContentLoaded',()=>setTimeout(refreshDashboardV2,150));
  setTimeout(refreshDashboardV2,500);
})();
