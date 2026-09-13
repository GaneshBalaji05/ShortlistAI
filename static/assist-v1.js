(() => {
  if (document.getElementById('shortlistAssist')) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  let candidates = [];
  let selectedCandidate = null;

  const launch = document.createElement('button');
  launch.className = 'sa-launch';
  launch.type = 'button';
  launch.setAttribute('aria-label','Open ShortlistAI Assist');
  launch.textContent = '✦';

  const panel = document.createElement('aside');
  panel.id = 'shortlistAssist';
  panel.className = 'sa-panel sa-hidden';
  panel.innerHTML = `
    <div class="sa-head"><div class="sa-logo">S</div><div class="sa-head-copy"><b>ShortlistAI Assist</b><small>Recruiter reasoning + product diagnostics</small></div><button class="sa-close" type="button" aria-label="Close">×</button></div>
    <div class="sa-context"><label>Candidate context</label><select id="saCandidate"><option value="">Select a candidate for profile questions</option></select></div>
    <div class="sa-presets"><button class="sa-chip" data-q="choose">Why choose this profile?</button><button class="sa-chip" data-q="reject">Why reject if skills are mentioned?</button><button class="sa-chip" data-q="bug">What's wrong with the app right now?</button></div>
    <div id="saChat" class="sa-chat"><div class="sa-msg bot">Hi — I can explain a candidate decision or run a quick product diagnostic. Select a candidate above for profile-specific answers.</div></div>
    <div class="sa-compose"><textarea id="saInput" placeholder="Ask ShortlistAI Assist…"></textarea><button id="saSend" class="sa-send" type="button">↑</button></div>
    <div class="sa-status">Assist v1 uses live ATS data and stored AI evidence. It does not invent missing resume facts.</div>`;
  document.body.append(launch,panel);

  const $ = id => document.getElementById(id);
  const chat = $('saChat');
  function addMessage(role, html){const d=document.createElement('div');d.className=`sa-msg ${role}`;d.innerHTML=html;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;}
  function textMessage(role, text){addMessage(role, esc(text).replace(/\n/g,'<br>'));}
  function list(items){return `<ul class="sa-points">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;}

  async function api(url){const r=await fetch(url,{cache:'no-store'}),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Request failed');return d;}
  async function loadCandidates(){
    try{
      candidates = await api('/api/candidates');
      const select = $('saCandidate');
      select.innerHTML='<option value="">Select a candidate for profile questions</option>'+candidates.map(c=>`<option value="${c.id}">${esc(c.name)}${c.job_title?' — '+esc(c.job_title):''}</option>`).join('');
    }catch(_){ textMessage('bot','I could not load candidate context. Product diagnostics can still check whether the ATS APIs are responding.'); }
  }
  async function loadCandidate(id){
    if(!id){selectedCandidate=null;return null;}
    try{selectedCandidate=await api(`/api/candidates/${id}`);return selectedCandidate;}catch(e){selectedCandidate=null;textMessage('bot',`Candidate details could not be loaded: ${e.message}`);return null;}
  }

  function evaluation(c){return c?.ai_evaluation || {};}
  function chooseAnswer(c){
    if(!c)return 'Select a candidate first so I can explain the decision using that profile’s stored AI evidence.';
    const e=evaluation(c); if(!Object.keys(e).length)return `${c.name} does not have a stored AI evaluation yet. Run AI evaluation against an assigned job first.`;
    const score=Number(e.score ?? c.ai_score ?? 0),rating=e.rating||c.rating||'Not rated';
    const matched=e.matched_skills||[],recent=e.recent_skills||[],risks=e.risks||[];
    const points=[];
    if(matched.length)points.push(`Matched requirements: ${matched.slice(0,8).join(', ')}.`);
    if(e.experience_fit!=null)points.push(`Experience fit is ${e.experience_fit}%.`);
    if(e.recent_evidence!=null)points.push(`Recent/current evidence is ${e.recent_evidence}%.`);
    if(recent.length)points.push(`Recent evidence includes ${recent.slice(0,6).join(', ')}.`);
    if(risks.length)points.push(`Still verify: ${risks.slice(0,3).join(' ')}`);
    const recommendation=score>=75?'This is a strong screening candidate, not an automatic hire.':score>=55?'This is a review candidate; recruiter validation is important.':'The current evidence does not support prioritising this profile for this JD.';
    return `<strong>${esc(c.name)} — ${esc(rating)} (${score})</strong><br>${esc(recommendation)}${list(points.length?points:['The score exists, but detailed evidence is limited in the stored evaluation.'])}`;
  }

  function rejectAnswer(c){
    if(!c)return 'Select a candidate first. I’ll compare the skills they mention with the actual scoring evidence and explain why the profile may still be weak or rejected.';
    const e=evaluation(c);if(!Object.keys(e).length)return `${c.name} has no stored AI evaluation yet, so I cannot give a reliable rejection explanation.`;
    const rating=e.rating||c.rating||'Not rated',score=Number(e.score ?? c.ai_score ?? 0),missing=e.missing_skills||[],risks=e.risks||[];
    const points=[];
    if(e.skill_coverage!=null)points.push(`Skill coverage: ${e.skill_coverage}%. A skill name appearing in a resume does not by itself prove the required depth or recency.`);
    if(e.experience_fit!=null)points.push(`Experience fit: ${e.experience_fit}%.`);
    if(e.recent_evidence!=null)points.push(`Recent/current evidence: ${e.recent_evidence}%.`);
    if(missing.length)points.push(`Missing or unclear requirements: ${missing.slice(0,8).join(', ')}.`);
    risks.slice(0,3).forEach(x=>points.push(`Verification risk: ${x}`));
    if(c.stage==='Rejected')points.push('The ATS stage is currently Rejected. The stored AI score is decision support; the final rejection may also include recruiter or interview feedback not captured in the score.');
    const intro=(rating==='Weak'||score<55)?'The profile is weak because the model weighs evidence, experience and recency — not only keyword presence.':'This candidate is not currently scored Weak. If they were rejected, the reason may come from pipeline/interview judgment rather than the AI score alone.';
    return `<strong>${esc(c.name)} — ${esc(rating)} (${score})</strong><br>${esc(intro)}${list(points.length?points:['No detailed gap evidence is stored; a recruiter should verify the rejection reason manually.'])}`;
  }

  async function diagnosticAnswer(userText=''){
    const checks=[];
    let stats=null,dash=null,ivs=null;
    try{stats=await api('/api/stats');checks.push(['ok',`Core ATS API is reachable: ${stats.jobs} open jobs, ${stats.candidates} candidates.`]);}catch(e){checks.push(['bad',`Core ATS API failed: ${e.message}`]);}
    try{dash=await api('/api/dashboard-v2');checks.push(['ok',`Dashboard API is reachable: ${(dash.jobs||[]).length} jobs and ${(dash.candidates||[]).length} candidate records returned.`]);}catch(e){checks.push(['bad',`Dashboard API failed: ${e.message}`]);}
    try{ivs=await api('/api/interviews');checks.push(['ok',`Interviews API is reachable: ${ivs.length} interview records.`]);}catch(e){checks.push(['bad',`Interviews API failed: ${e.message}`]);}
    if(stats&&dash&&Number(stats.candidates)!==(dash.candidates||[]).length)checks.push(['warn',`Candidate count mismatch: Home stats says ${stats.candidates}, while Dashboard v2 returned ${(dash.candidates||[]).length}. Refresh/data-query differences should be checked.`]);
    const active=document.querySelector('.section.active')?.id||location.pathname;
    checks.push(['ok',`Current screen detected: ${active}.`]);
    const lower=userText.toLowerCase();
    if(lower.includes('candidate')&&(lower.includes('not show')||lower.includes('not showing')||lower.includes('details')))checks.push(['warn','For candidate-detail issues, first confirm the candidate exists in /api/candidates and that the View action can load /api/candidates/{id}. Missing resume text only affects re-evaluation, not basic profile display.']);
    if(lower.includes('dashboard')&&(lower.includes('0')||lower.includes('not show')||lower.includes('wrong')))checks.push(['warn','If the dashboard looks stale, compare /api/stats with /api/dashboard-v2 and refresh after service-worker/app updates. The dashboard uses live ATS data, while cached UI assets can make an older layout appear briefly.']);
    return `<strong>Live product diagnostic</strong><div class="sa-diagnostic">${checks.map(([kind,msg])=>`<div class="sa-${kind}">• ${esc(msg)}</div>`).join('')}</div>`;
  }

  async function respond(raw){
    const q=raw.trim();if(!q)return;
    textMessage('user',q);
    const lower=q.toLowerCase();
    if(lower.includes('why')&&(lower.includes('choose')||lower.includes('select')||lower.includes('shortlist')||lower.includes('strong'))){addMessage('bot',chooseAnswer(selectedCandidate));return;}
    if(lower.includes('reject')||lower.includes('weak')||(lower.includes('skill')&&lower.includes('mention'))){addMessage('bot',rejectAnswer(selectedCandidate));return;}
    if(lower.includes('bug')||lower.includes('issue')||lower.includes('problem')||lower.includes('not showing')||lower.includes('not show')||lower.includes('dashboard')||lower.includes('error')){addMessage('bot',await diagnosticAnswer(q));return;}
    addMessage('bot','Assist v1 currently focuses on three things:'+list(['Why a profile should be prioritised.','Why a profile can be weak/rejected even when skills are mentioned.','Live ATS/product diagnostics when something is not displaying or behaving correctly.']));
  }

  launch.onclick=()=>{panel.classList.toggle('sa-hidden');if(!panel.classList.contains('sa-hidden'))$('saInput').focus();};
  panel.querySelector('.sa-close').onclick=()=>panel.classList.add('sa-hidden');
  $('saCandidate').onchange=async e=>{const c=await loadCandidate(e.target.value);if(c)textMessage('bot',`Candidate context set to ${c.name}${c.job_title?' for '+c.job_title:''}.`);};
  panel.querySelectorAll('[data-q]').forEach(b=>b.onclick=async()=>{const type=b.dataset.q;if(type==='choose'){textMessage('user','Why are we choosing this profile?');addMessage('bot',chooseAnswer(selectedCandidate));}else if(type==='reject'){textMessage('user','The candidate mentioned the skills. Why are we rejecting this profile?');addMessage('bot',rejectAnswer(selectedCandidate));}else{textMessage('user','What issue is going on in the app right now?');addMessage('bot',await diagnosticAnswer('dashboard candidate details not showing'));}});
  $('saSend').onclick=async()=>{const q=$('saInput').value;$('saInput').value='';await respond(q);};
  $('saInput').addEventListener('keydown',async e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const q=e.target.value;e.target.value='';await respond(q);}});
  loadCandidates();
})();
