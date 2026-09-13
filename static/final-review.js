(() => {
  const PIPELINE_STAGES = ['Applied','Contacted','Interview Scheduled','L1','L2','Selected','Hired','Dropped'];
  const STAGE_ALIASES = {Sourced:'Applied',Screened:'Contacted',Interview:'Interview Scheduled',Offered:'Selected',Joined:'Hired',Rejected:'Dropped'};
  const BULK_LIMIT = 800;
  const BATCH_SIZE = 40;
  const VIEW_KEY = 'shortlistai-view-mode';
  const style = document.createElement('style');
  style.textContent = `
    .fr-count{display:inline-flex;align-items:center;gap:6px;margin-left:8px;padding:6px 10px;border:1px solid #e4e4e7;border-radius:999px;background:#fff;color:#52525b;font-size:12px;font-weight:800}
    .fr-pipeline-top{display:flex;gap:14px;align-items:end;justify-content:space-between;flex-wrap:wrap;margin-bottom:16px}
    .fr-role{min-width:280px}.fr-role label{display:block;font-size:12px;color:#737373;font-weight:800;margin-bottom:6px}.fr-role select{width:100%;min-height:44px;border:1px solid #dedede;border-radius:10px;background:#fff;padding:9px 11px}
    .fr-stage-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:12px 0 18px}
    .fr-stage{border:1px solid #e5e5e5;border-radius:14px;background:#fff;padding:14px;text-align:left;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.05)}
    .fr-stage:hover,.fr-stage.active{border-color:#ef233c;box-shadow:0 8px 26px rgba(239,35,60,.13)}.fr-stage b{display:block;font-size:25px;color:#111}.fr-stage span{font-size:12px;color:#71717a;font-weight:800}
    .fr-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.fr-candidate{border:1px solid #e7e7e7;background:#fff;border-radius:13px;padding:13px;cursor:pointer}.fr-candidate:hover{border-color:#ef233c}.fr-candidate small{display:block;color:#777;margin-top:4px}
    .fr-bulk-note{margin-top:7px;font-size:12px;color:#71717a}.fr-progress{height:7px;background:#eee;border-radius:999px;overflow:hidden;margin:8px 0}.fr-progress i{display:block;height:100%;background:#ef233c;transition:width .2s ease}
    body.force-desktop .fr-stage-grid{grid-template-columns:repeat(8,minmax(130px,1fr))}
    @media(max-width:900px){.fr-stage-grid{grid-template-columns:repeat(2,1fr)}.fr-list{grid-template-columns:1fr}.fr-role{min-width:100%;}.fr-pipeline-top{align-items:stretch}}

    /* True in-app Mobile View / Desktop View selector */
    .fr-view-switch{position:fixed;right:14px;top:14px;z-index:120;display:flex;gap:4px;padding:4px;border:1px solid #4a2020;border-radius:14px;background:rgba(8,8,9,.96);box-shadow:0 14px 36px rgba(0,0,0,.48);backdrop-filter:blur(14px)}
    .fr-view-switch button{border:0;background:transparent;color:#aaa;padding:9px 11px;border-radius:10px;font-size:12px;font-weight:850;cursor:pointer;min-height:38px;white-space:nowrap}
    .fr-view-switch button:hover{color:#fff;background:#171719}.fr-view-switch button.active{background:linear-gradient(135deg,#ff3b30,#d50000);color:#fff;box-shadow:0 6px 16px rgba(255,45,45,.22)}
    .fr-view-switch button span{margin-right:6px}.fr-view-switch-status{position:fixed;right:16px;top:65px;z-index:119;color:#9a9aa0;font-size:10px;font-weight:750;pointer-events:none}

    /* Mobile View can be chosen manually even on a wide screen. */
    body.force-mobile{padding-bottom:78px!important;overflow-x:hidden!important;max-width:480px!important;margin:0 auto!important;min-height:100vh!important;background:#000!important}
    body.force-mobile .app{display:block!important;grid-template-columns:1fr!important;min-width:0!important;width:100%!important}
    body.force-mobile .side{position:fixed!important;z-index:60!important;bottom:0!important;left:50%!important;right:auto!important;top:auto!important;transform:translateX(-50%)!important;width:min(480px,100vw)!important;height:72px!important;padding:6px 5px!important;background:rgba(5,5,5,.97)!important;backdrop-filter:blur(12px)!important;border-top:1px solid var(--line)!important;border-right:0!important;border-bottom:0!important}
    body.force-mobile .side>.brand,body.force-mobile .install{display:none!important}
    body.force-mobile .nav{height:100%!important;display:grid!important;grid-template-columns:repeat(5,1fr)!important;gap:2px!important;overflow-x:auto!important;overflow-y:hidden!important;flex-direction:row!important}
    body.force-mobile .nav button{display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:center!important;padding:4px 2px!important;font-size:10px!important;text-align:center!important;min-height:58px!important;border-radius:12px!important;white-space:nowrap!important}
    body.force-mobile .nav button::before{width:auto!important;display:block!important;font-size:20px!important;line-height:20px!important;margin:0 0 4px!important}
    body.force-mobile .main{padding:18px 14px 28px!important;max-width:480px!important;width:100%!important;margin:0 auto!important}
    body.force-mobile .mobile-header{display:flex!important;align-items:center!important;justify-content:space-between!important;margin-bottom:18px!important}
    body.force-mobile .mobile-header .brand{display:block!important;margin:0!important;font-size:21px!important}
    body.force-mobile .title h1{font-size:26px!important}.force-mobile .title p{font-size:14px!important}
    body.force-mobile .top{margin-bottom:16px!important;align-items:flex-start!important;flex-direction:column!important}
    body.force-mobile .stats{grid-template-columns:repeat(2,1fr)!important;gap:10px!important}.force-mobile .stat{padding:14px!important}.force-mobile .stat b{font-size:25px!important}
    body.force-mobile .grid2,body.force-mobile .grid3,body.force-mobile .eval-grid,body.force-mobile .friendly-metrics{grid-template-columns:1fr!important}
    body.force-mobile .card{padding:15px!important;border-radius:14px!important}
    body.force-mobile .table thead{display:none!important}.force-mobile .table,.force-mobile .table tbody,.force-mobile .table tr,.force-mobile .table td{display:block!important;width:100%!important}
    body.force-mobile .table tr{background:#0d0d0f!important;border:1px solid var(--line)!important;border-radius:13px!important;padding:12px!important;margin-bottom:10px!important}.force-mobile .table td{border:0!important;padding:5px 0!important}
    body.force-mobile .toolbar input,body.force-mobile .toolbar select{width:100%!important;min-height:44px!important}
    body.force-mobile .modal{padding:0!important;align-items:end!important}.force-mobile .modalbox{width:100%!important;max-height:94vh!important;border-radius:22px 22px 0 0!important;padding:16px!important}
    body.force-mobile .profile{grid-template-columns:1fr 1fr!important}.force-mobile .pipeline{grid-template-columns:repeat(6,245px)!important;padding-bottom:8px!important}.force-mobile .col{min-height:380px!important}
    body.force-mobile .scorecircle{width:62px!important;height:62px!important}.force-mobile .eval-head{align-items:flex-start!important}.force-mobile .eval-head .right{margin-left:0!important;width:100%!important}
    body.force-mobile .result{padding:13px!important}.force-mobile .result .right{margin-left:0!important}.force-mobile .row{align-items:stretch!important}.force-mobile .row>.btn,.force-mobile .row>.ghost{flex:1!important}
    body.force-mobile .quick-actions .btn,body.force-mobile .quick-actions .ghost{width:100%!important;flex:auto!important}.force-mobile .shortlist-grid{display:block!important}.force-mobile .shortlist-grid>.card{margin-bottom:12px!important}
    body.force-mobile .capture-preview{grid-template-columns:1fr!important}.force-mobile .fr-stage-grid{grid-template-columns:repeat(2,1fr)!important}.force-mobile .fr-list{grid-template-columns:1fr!important}.force-mobile .fr-role{min-width:100%!important}.force-mobile .fr-pipeline-top{align-items:stretch!important}
    @media(max-width:520px){.fr-view-switch{right:10px;top:10px}.fr-view-switch button{padding:8px 9px;font-size:11px}.fr-view-switch-status{display:none}}
  `;
  document.head.appendChild(style);

  const safe = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const canonical = value => STAGE_ALIASES[value] || (PIPELINE_STAGES.includes(value) ? value : 'Applied');
  const effective = candidate => {
    const stored = canonical(candidate.stage);
    if (['Hired','Dropped','Selected'].includes(stored)) return stored;
    const p = candidate.profile_details || {};
    if (p.l2_status === 'Cleared') return 'L2';
    if (p.l1_status === 'Cleared') return 'L1';
    if (p.l1_status === 'Scheduled' || p.l2_status === 'Scheduled') return 'Interview Scheduled';
    return stored;
  };

  function setStageOptions(select, includeAll=false){
    if(!select) return;
    const selected = canonical(select.value);
    select.innerHTML = (includeAll ? '<option value="">All stages</option>' : '') + PIPELINE_STAGES.map(s=>`<option value="${s}">${s}</option>`).join('');
    if(includeAll && !select.dataset.hadValue) select.value=''; else select.value=PIPELINE_STAGES.includes(selected)?selected:(includeAll?'':'Applied');
  }

  async function databaseTotal(){
    try{
      const data = await api('/api/stats');
      return Number(data.candidate_total ?? data.candidates ?? 0);
    }catch(_){ return null; }
  }

  async function refreshDatabaseCount(){
    const total = await databaseTotal();
    if(total === null) return;
    let badge = document.getElementById('candidateTotalBadge');
    const heading = document.querySelector('#candidates .card .row h3');
    if(heading && !badge){
      badge=document.createElement('span');badge.id='candidateTotalBadge';badge.className='fr-count';heading.after(badge);
    }
    if(badge) badge.textContent=`${total} total profiles`;
    let talentBadge=document.getElementById('talentTotalBadge');
    const talentTitle=document.querySelector('#talent .top .title h1');
    if(talentTitle && !talentBadge){talentBadge=document.createElement('span');talentBadge.id='talentTotalBadge';talentBadge.className='fr-count';talentTitle.after(talentBadge);}
    if(talentBadge) talentBadge.textContent=`${total} total profiles`;
  }

  const filterStage = document.getElementById('filterStage');
  const candidateStage = document.getElementById('cStage');
  if(filterStage){filterStage.dataset.hadValue='';setStageOptions(filterStage,true);}
  if(candidateStage) setStageOptions(candidateStage,false);

  const talentStage = document.querySelector('#tpFilters select[name="stage"]');
  if(talentStage){talentStage.dataset.hadValue='';setStageOptions(talentStage,true);}
  const talentSearch = document.querySelector('#tpFilters input[name="q"]');
  if(talentSearch) talentSearch.placeholder='Boolean search: Java AND ("Spring Boot" OR Spring) NOT Python';

  function applyViewMode(mode, persist=true){
    const resolved = mode === 'mobile' ? 'mobile' : 'desktop';
    document.body.classList.toggle('force-mobile', resolved === 'mobile');
    document.body.classList.toggle('force-desktop', resolved === 'desktop' && window.matchMedia('(max-width:900px)').matches);
    document.documentElement.dataset.shortlistView = resolved;
    if(persist) localStorage.setItem(VIEW_KEY, resolved);
    const control=document.getElementById('frViewModeControl');
    if(control){
      control.querySelectorAll('[data-view]').forEach(btn=>{
        const active=btn.dataset.view===resolved;
        btn.classList.toggle('active',active);
        btn.setAttribute('aria-pressed',active?'true':'false');
      });
    }
    const status=document.getElementById('frViewModeStatus');
    if(status) status.textContent=`${resolved === 'mobile' ? 'Mobile' : 'Desktop'} View active`;
  }

  function installViewModeControl(){
    const legacy=document.getElementById('viewModeToggle');
    if(legacy){legacy.hidden=true;legacy.style.setProperty('display','none','important');legacy.setAttribute('aria-hidden','true');}
    let control=document.getElementById('frViewModeControl');
    if(!control){
      control=document.createElement('div');
      control.id='frViewModeControl';
      control.className='fr-view-switch';
      control.setAttribute('role','group');
      control.setAttribute('aria-label','App view mode');
      control.innerHTML='<button type="button" data-view="mobile" aria-pressed="false"><span>▯</span>Mobile View</button><button type="button" data-view="desktop" aria-pressed="false"><span>▣</span>Desktop View</button>';
      document.body.appendChild(control);
      const status=document.createElement('div');status.id='frViewModeStatus';status.className='fr-view-switch-status';document.body.appendChild(status);
    }
    control.querySelectorAll('[data-view]').forEach(btn=>btn.onclick=()=>{
      applyViewMode(btn.dataset.view,true);
      window.scrollTo({top:0,left:0,behavior:'smooth'});
      if(typeof toast==='function') toast(`${btn.dataset.view==='mobile'?'Mobile':'Desktop'} View enabled`);
    });
    const stored=localStorage.getItem(VIEW_KEY);
    const initial=(stored==='mobile'||stored==='desktop')?stored:(window.matchMedia('(max-width:900px)').matches?'mobile':'desktop');
    applyViewMode(initial,false);
    window.addEventListener('resize',()=>{
      const chosen=localStorage.getItem(VIEW_KEY)||initial;
      applyViewMode(chosen,false);
    });
  }
  installViewModeControl();

  loadCandidates = async function(){
    jobs = await api('/api/jobs');
    const query = encodeURIComponent(document.getElementById('searchCand').value || '');
    const wanted = document.getElementById('filterStage').value || '';
    let all = await api(`/api/candidates?q=${query}`);
    if(wanted) all = all.filter(c=>effective(c)===wanted);
    candidates = all;
    document.getElementById('candTable').innerHTML = all.length ? all.map(c=>{
      const current=effective(c);
      return `<tr><td><b>${safe(c.name)}</b><div class="muted">${safe(c.email||'')}</div></td><td>${safe(c.job_title||'Unassigned')}</td><td><select onchange="moveCand(${c.id},this.value)">${PIPELINE_STAGES.map(s=>`<option ${s===current?'selected':''}>${s}</option>`).join('')}</select></td><td>${c.ai_score??'—'} ${c.rating?`<span class="badge ${safe(c.rating)}">${safe(c.rating)}</span>`:''}</td><td><div class="row"><button class="ghost" onclick="openCandidate(${c.id})">View</button><button class="ghost danger" onclick="delCand(${c.id})">Delete</button></div></td></tr>`;
    }).join('') : '<tr><td colspan="5" class="muted">No candidates found.</td></tr>';
    document.getElementById('cJob').innerHTML='<option value="">Unassigned</option>'+jobs.map(j=>`<option value="${j.id}">${safe(j.title)}</option>`).join('');
    await refreshDatabaseCount();
  };

  moveCand = async function(id, stage){
    try{
      await api(`/api/candidates/${id}/stage`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage})});
      toast(`Moved to ${stage}`);await loadCandidates();await loadStats();
      if(document.getElementById('pipeline')?.classList.contains('active')) await loadPipeline();
    }catch(e){toast(e.message);}
  };

  let pipelineSelectedStage='Applied';
  let pipelineSelectedJob=null;
  loadPipeline = async function(jobId){
    if(jobId!==undefined && jobId!==null && jobId!=='') pipelineSelectedJob=Number(jobId);
    const url='/api/pipeline-v3'+(pipelineSelectedJob?`?job_id=${pipelineSelectedJob}`:'');
    const data=await api(url);
    pipelineSelectedJob=data.job_id;
    const section=document.getElementById('pipeline');
    section.innerHTML=`<div class="top"><div class="title"><div class="eyebrow">Role-specific hiring progress</div><h1>Pipeline</h1><p>Every count below belongs only to the selected role. Click any stage to open those candidates.</p></div></div><div class="fr-pipeline-top"><div class="fr-role"><label>Requirement / role</label><select id="pipelineRole">${data.jobs.map(j=>`<option value="${j.id}" ${Number(j.id)===Number(data.job_id)?'selected':''}>${safe(j.title)}</option>`).join('')}</select></div><span class="fr-count">${data.total} profiles in this role</span></div><div id="pipelineStageGrid" class="fr-stage-grid"></div><div class="card"><div class="row" style="margin-bottom:12px"><h3 id="pipelineStageTitle" style="margin:0"></h3><span id="pipelineStageCount" class="fr-count"></span></div><div id="pipelineStageList" class="fr-list"></div></div>`;
    const nonZero=PIPELINE_STAGES.find(s=>Number(data.counts[s]||0)>0);
    if(!PIPELINE_STAGES.includes(pipelineSelectedStage)) pipelineSelectedStage=nonZero||'Applied';
    const renderStage=()=>{
      document.getElementById('pipelineStageGrid').innerHTML=PIPELINE_STAGES.map(stage=>`<button class="fr-stage ${stage===pipelineSelectedStage?'active':''}" data-stage="${stage}"><b>${Number(data.counts[stage]||0)}</b><span>${stage}</span></button>`).join('');
      const rows=data.candidates.filter(c=>c.stage===pipelineSelectedStage);
      document.getElementById('pipelineStageTitle').textContent=pipelineSelectedStage;
      document.getElementById('pipelineStageCount').textContent=`${rows.length} candidate${rows.length===1?'':'s'}`;
      document.getElementById('pipelineStageList').innerHTML=rows.length?rows.map(c=>`<div class="fr-candidate" data-id="${c.id}"><div class="row"><div><b>${safe(c.name)}</b><small>${safe(c.email||c.job_title||'')}</small></div><div class="right">${c.ai_score??'—'} ${c.rating?`<span class="badge ${safe(c.rating)}">${safe(c.rating)}</span>`:''}</div></div></div>`).join(''):'<div class="empty" style="grid-column:1/-1">No candidates in this stage for the selected role.</div>';
      document.querySelectorAll('#pipelineStageGrid [data-stage]').forEach(btn=>btn.onclick=()=>{pipelineSelectedStage=btn.dataset.stage;renderStage();});
      document.querySelectorAll('#pipelineStageList [data-id]').forEach(card=>card.onclick=()=>openCandidate(Number(card.dataset.id)));
    };
    renderStage();
    const role=document.getElementById('pipelineRole');if(role)role.onchange=()=>{pipelineSelectedStage='Applied';loadPipeline(role.value);};
  };

  const fileInput=document.getElementById('aiFiles');
  if(fileInput){
    const helper=fileInput.closest('.field')?.nextElementSibling;
    if(helper?.classList.contains('helper')) helper.innerHTML=`PDF, DOCX, TXT or MD • Up to <b>${BULK_LIMIT}</b> profiles • processed safely in batches`;
    fileInput.addEventListener('change',()=>{
      const n=fileInput.files.length;
      if(n>BULK_LIMIT){document.getElementById('status').textContent=`Choose no more than ${BULK_LIMIT} profiles at once.`;fileInput.value='';}
      else if(n) document.getElementById('status').textContent=`${n} profile${n===1?'':'s'} ready. ${n>BATCH_SIZE?'ShortlistAI will process them in batches.':''}`;
    });
  }

  const analyze=document.getElementById('analyze');
  if(analyze) analyze.onclick=async()=>{
    const jd=document.getElementById('aiJD').value.trim();
    const files=[...document.getElementById('aiFiles').files];
    if(jd.length<50){document.getElementById('status').textContent='Paste or select a fuller job description first.';return;}
    if(!files.length){document.getElementById('status').textContent='Upload at least one resume.';return;}
    if(files.length>BULK_LIMIT){document.getElementById('status').textContent=`The bulk limit is ${BULK_LIMIT} profiles.`;return;}
    analyze.disabled=true;analyze.textContent='Analyzing…';
    const combined=[],errors=[];let merged=0;let methodology='';
    try{
      for(let start=0;start<files.length;start+=BATCH_SIZE){
        const batch=files.slice(start,start+BATCH_SIZE),end=Math.min(start+BATCH_SIZE,files.length);
        document.getElementById('status').innerHTML=`Processing ${start+1}–${end} of ${files.length}…<div class="fr-progress"><i style="width:${Math.round((start/files.length)*100)}%"></i></div>`;
        const fd=new FormData();fd.append('jd',jd);batch.forEach(f=>fd.append('resumes',f));
        if(document.getElementById('aiJob').value)fd.append('job_id',document.getElementById('aiJob').value);
        fd.append('save_to_ats',document.getElementById('saveATS').checked?'true':'false');
        const response=await fetch('/analyze',{method:'POST',body:fd});
        const data=await response.json();
        if(!response.ok) throw new Error(data.detail||`Batch ${Math.floor(start/BATCH_SIZE)+1} failed`);
        combined.push(...(data.results||[]));errors.push(...(data.errors||[]));merged+=(data.duplicates_merged||[]).length;methodology=data.methodology||methodology;
      }
      combined.sort((a,b)=>Number(b.score||0)-Number(a.score||0));latest=combined;
      document.getElementById('results').classList.remove('hidden');document.getElementById('export').classList.remove('hidden');
      document.getElementById('method').textContent=methodology;
      const shown=combined.slice(0,100);
      document.getElementById('resultList').innerHTML=shown.map((x,i)=>`<div class="result"><div class="row"><div><b>#${i+1} ${safe(x.candidate)}</b><div class="muted">${safe(x.file||'')}</div></div><div class="right"><span style="font-size:23px;font-weight:900">${x.score}</span> <span class="badge ${safe(x.rating)}">${safe(x.rating)}</span></div></div>${renderEvaluation(x).replace('<div class="card" style="margin-top:14px">','<div style="margin-top:12px">').replace(/<\/div>$/,'</div>')}</div>`).join('')+(combined.length>100?`<div class="empty">Showing the top 100 of ${combined.length} ranked profiles for performance. All ${combined.length} are available in Excel and, when enabled, saved to the ATS.</div>`:'');
      const total=await databaseTotal();
      document.getElementById('status').textContent=`Done — ${combined.length} profile(s) ranked${document.getElementById('saveATS').checked?` and persisted${total!==null?` (${total} total in database)`:''}`:''}.${merged?` ${merged} duplicate profile(s) merged into existing candidates.`:''}${errors.length?` ${errors.length} file(s) could not be read.`:''}`;
      if(document.getElementById('saveATS').checked){toast('Profiles saved to ATS');await loadStats();await refreshDatabaseCount();}
    }catch(e){document.getElementById('status').textContent=e.message;}
    finally{analyze.disabled=false;analyze.textContent='✦ Find best matches';}
  };

  const oldShowTab=showTab;
  showTab=function(id){oldShowTab(id);if(id==='pipeline')loadPipeline();if(id==='candidates'||id==='talent')refreshDatabaseCount();};
  document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));

  refreshDatabaseCount();
})();