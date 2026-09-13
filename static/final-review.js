(() => {
  const PIPELINE_STAGES = ['Applied','Contacted','Interview Scheduled','L1','L2','Selected','Hired','Dropped'];
  const STAGE_ALIASES = {Sourced:'Applied',Screened:'Contacted',Interview:'Interview Scheduled',Offered:'Selected',Joined:'Hired',Rejected:'Dropped'};
  const BULK_LIMIT = 800;
  const BATCH_SIZE = 40;
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

  const toggle=document.getElementById('viewModeToggle');
  if(toggle){toggle.hidden=false;toggle.style.display='';toggle.title='Manually switch the installed app between Mobile View and Desktop View';}

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
