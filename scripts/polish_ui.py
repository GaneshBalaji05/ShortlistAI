from pathlib import Path

p = Path('static/index.html')
s = p.read_text()

if '/* User-friendly recruiter UI */' in s:
    print('UI already polished')
    raise SystemExit(0)

extra_css = r'''
/* User-friendly recruiter UI */
:root{--shadow:0 16px 45px rgba(0,0,0,.22)}
body{background:radial-gradient(circle at 15% 0%,#17244d 0,#0b1020 35%);line-height:1.45}
.card,.stat,.result,.cand,.modalbox{box-shadow:var(--shadow)}
.btn,.ghost,.nav button{min-height:44px}.btn:active,.ghost:active,.nav button:active{transform:scale(.99)}
.btn{background:linear-gradient(135deg,#5d82ff,#8b6cff);box-shadow:0 8px 24px rgba(101,135,255,.25)}
.btn:disabled{opacity:.55;cursor:not-allowed}.field label{font-size:13px;color:#c4cee4}.field input,.field textarea,.field select{font-size:16px;min-height:46px;border-color:#31405f}.field input:focus,.field textarea:focus,.field select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(124,156,255,.12)}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:900;margin-bottom:6px}.helper{color:var(--muted);font-size:13px;margin-top:7px}.step-title{display:flex;gap:10px;align-items:center;margin-bottom:14px}.step-num{width:30px;height:30px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#6587ff,#8b6cff);font-weight:900}.empty{padding:24px 12px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:12px}.legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.legend span{font-size:12px;color:var(--muted)}
.badge{font-size:12px;padding:6px 10px}.badge.Strong{background:rgba(80,216,144,.12);border-color:rgba(80,216,144,.35)}.badge.Average{background:rgba(255,200,87,.12);border-color:rgba(255,200,87,.35)}.badge.Weak{background:rgba(255,107,122,.12);border-color:rgba(255,107,122,.35)}
.scorebox{display:flex;align-items:center;gap:12px}.scorecircle{width:68px;height:68px;border-radius:50%;display:grid;place-items:center;background:#0d1428;border:4px solid var(--accent);font-size:21px;font-weight:900}.friendly-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}.friendly-metric{padding:13px;background:#0d1428;border:1px solid var(--line);border-radius:12px}.friendly-metric small{display:block;color:var(--muted);margin-bottom:3px}.friendly-metric b{font-size:18px}.progress{height:7px;background:#202b46;border-radius:999px;overflow:hidden;margin-top:8px}.progress i{display:block;height:100%;background:linear-gradient(90deg,#6587ff,#50d890);border-radius:999px}.detailsbox{margin-top:12px;border:1px solid var(--line);border-radius:12px;background:#0d1428}.detailsbox summary{cursor:pointer;padding:12px 14px;font-weight:800}.detailsbox>div{padding:0 14px 14px}.topline{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}.mobile-header{display:none}.nav button::before{display:inline-block;width:25px;color:#c9d4ee}.nav button[data-tab='dashboard']::before{content:'⌂'}.nav button[data-tab='jobs']::before{content:'▣'}.nav button[data-tab='candidates']::before{content:'♟'}.nav button[data-tab='pipeline']::before{content:'⇢'}.nav button[data-tab='shortlist']::before{content:'✦'}
@media(max-width:900px){body{padding-bottom:78px}.app{display:block}.side{position:fixed;z-index:60;bottom:0;left:0;right:0;top:auto;height:72px;padding:6px 5px;background:rgba(14,21,41,.97);backdrop-filter:blur(12px);border-top:1px solid var(--line);border-bottom:0}.brand,.install{display:none!important}.nav{height:100%;display:grid;grid-template-columns:repeat(5,1fr);gap:2px;overflow:visible}.nav button{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4px 2px;font-size:10px;text-align:center;min-height:58px;border-radius:12px}.nav button::before{width:auto;display:block;font-size:20px;line-height:20px;margin-bottom:4px}.main{padding:18px 14px 28px}.mobile-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.mobile-header .brand{display:block!important;margin:0;font-size:21px}.title h1{font-size:26px}.title p{font-size:14px}.stats{grid-template-columns:repeat(2,1fr);gap:10px}.stat{padding:14px}.stat b{font-size:25px}.grid2,.grid3,.eval-grid,.friendly-metrics{grid-template-columns:1fr}.card{padding:15px;border-radius:14px}.top{margin-bottom:16px}.table thead{display:none}.table,.table tbody,.table tr,.table td{display:block;width:100%}.table tr{background:#0d1428;border:1px solid var(--line);border-radius:13px;padding:12px;margin-bottom:10px}.table td{border:0;padding:5px 0}.toolbar input,.toolbar select{width:100%;min-height:44px}.modal{padding:0;align-items:end}.modalbox{width:100%;max-height:94vh;border-radius:22px 22px 0 0;padding:16px}.profile{grid-template-columns:1fr 1fr}.pipeline{grid-template-columns:repeat(6,245px);padding-bottom:8px}.col{min-height:380px}.scorecircle{width:62px;height:62px}.eval-head{align-items:flex-start}.eval-head .right{margin-left:0;width:100%}.result{padding:13px}.result .right{margin-left:0}.row{align-items:stretch}.row>.btn,.row>.ghost{flex:1}.quick-actions .btn,.quick-actions .ghost{width:100%;flex:auto}.shortlist-grid{display:block}.shortlist-grid>.card{margin-bottom:12px}}
'''

s = s.replace('</style>', extra_css + '\n</style>', 1)
s = s.replace('>Dashboard</button>', '>Home</button>')
s = s.replace('>AI Shortlisting</button>', '>AI Match</button>')
s = s.replace('<main class="main">', '<main class="main"><div class="mobile-header"><div class="brand">Shortlist<span>AI</span></div><span class="badge Strong">ATS</span></div>', 1)

s = s.replace('<div class="top"><div class="title"><h1>Recruitment Dashboard</h1><p>Your ATS overview and hiring activity.</p></div></div>', '<div class="top"><div class="title"><div class="eyebrow">Recruiter workspace</div><h1>Good to see you 👋</h1><p>See what needs attention and move hiring forward.</p></div></div>', 1)
s = s.replace('<div class="card"><h3>Quick actions</h3><div class="row"><button class="btn" onclick="showTab(\'jobs\')">Create job</button><button class="ghost" onclick="showTab(\'candidates\')">Add candidate</button><button class="ghost" onclick="showTab(\'shortlist\')">AI shortlist</button></div></div>', '<div class="card quick-actions"><h3>What do you want to do?</h3><div class="row"><button class="btn" onclick="showTab(\'shortlist\')">✦ Match resumes with AI</button><button class="ghost" onclick="showTab(\'jobs\')">＋ Create a job</button><button class="ghost" onclick="showTab(\'candidates\')">＋ Add candidate</button></div></div>', 1)
s = s.replace('Jobs, candidate database, pipeline tracking, notes and explainable AI evaluation in one recruiter workspace.', 'Start with AI Match when you receive resumes. Save shortlisted candidates, then track them through the hiring pipeline.')

s = s.replace('<h1>Jobs</h1><p>Create and manage hiring requirements.</p>', '<div class="eyebrow">Hiring requirements</div><h1>Jobs</h1><p>Create a role once, then use it for AI matching and candidate tracking.</p>')
s = s.replace('<h3>Create Job</h3>', '<div class="step-title"><span class="step-num">1</span><h3 style="margin:0">Create a job</h3></div>', 1)
s = s.replace('<h3>Open Jobs</h3>', '<h3>Your jobs</h3>', 1)
s = s.replace('<h1>Candidates</h1><p>Search, add, evaluate and manage your talent pool.</p>', '<div class="eyebrow">Talent database</div><h1>Candidates</h1><p>Search people, check AI fit, update stages and keep recruiter notes.</p>')
s = s.replace('<h3>Add Candidate</h3>', '<h3>Add candidate manually</h3><p class="helper">For faster entry, use AI Match and choose “Save candidates to ATS”.</p>', 1)
s = s.replace('<h1>Pipeline</h1><p>Move candidates through each hiring stage.</p>', '<div class="eyebrow">Hiring progress</div><h1>Pipeline</h1><p>Tap a candidate to review them. Update the stage from the Candidates tab.</p>')

s = s.replace('<h1>AI Shortlisting</h1><p>Rank resumes against a JD, inspect the evidence, and save candidates into the ATS.</p>', '<div class="eyebrow">Fast shortlist</div><h1>AI Match</h1><p>Select a job, upload resumes, and see who is worth calling first — with reasons.</p>')
s = s.replace('<div class="grid2">\n    <div class="card">\n      <div class="field"><label>Select ATS job</label>', '<div class="grid2 shortlist-grid">\n    <div class="card">\n      <div class="step-title"><span class="step-num">1</span><h3 style="margin:0">Choose the requirement</h3></div>\n      <div class="field"><label>Select a saved job</label>', 1)
s = s.replace('<div class="field"><label>Job description</label><textarea id="aiJD" style="min-height:260px"></textarea></div>', '<div class="field"><label>Job description</label><textarea id="aiJD" style="min-height:240px" placeholder="Select a saved job above, or paste the JD here..."></textarea><div class="helper">Include must-have skills and minimum experience for the best result.</div></div>', 1)
s = s.replace('<div class="card">\n      <div class="field"><label>Candidate resumes</label>', '<div class="card">\n      <div class="step-title"><span class="step-num">2</span><h3 style="margin:0">Upload resumes</h3></div>\n      <div class="field"><label>Select candidate files</label>', 1)
s = s.replace('<div class="row"><label><input id="saveATS" type="checkbox"/> Save analyzed candidates to ATS</label></div>', '<div class="helper">PDF, DOCX, TXT or MD • Up to 50 resumes at once</div><div class="row" style="margin-top:14px"><label><input id="saveATS" type="checkbox" checked/> Save candidates to ATS after analysis</label></div>', 1)
s = s.replace('>Analyze candidates</button>', '>✦ Find best matches</button>', 1)
s = s.replace('No analysis run yet.', 'Ready when you are.')
s = s.replace('<h3>Ranked shortlist</h3>', '<div class="topline"><div><div class="eyebrow">AI result</div><h3 style="margin:0">Who should you call first?</h3></div><div class="legend"><span><b style="color:var(--good)">Strong</b> 75+</span><span><b style="color:var(--warn)">Average</b> 55–74</span><span><b style="color:var(--bad)">Weak</b> &lt;55</span></div></div>', 1)

start = s.index('function renderEvaluation(e){')
end = s.index('\nasync function openCandidate', start)
friendly = r'''function renderEvaluation(e){
  if(!e)return `<div class="card" style="margin-top:14px"><h3>AI evaluation</h3><div class="empty">No AI result yet.<br><small>Upload this resume through AI Match and save it to the ATS.</small></div></div>`;
  const sc=Number(e.score||0), skill=Number(e.skill_coverage||0), exp=Number(e.experience_fit||0), recent=Number(e.recent_evidence||0);
  return `<div class="card" style="margin-top:14px">
    <div class="eval-head"><div class="scorebox"><div class="scorecircle">${sc}</div><div><div class="muted">Overall job match</div><h3 style="margin:2px 0 5px">${esc(e.rating||'Not rated')}</h3><span class="badge ${e.rating||''}">${sc>=75?'Recommended to screen':sc>=55?'Review before screening':'Low match'}</span></div></div><div class="right muted">Experience: ${fmtYears(e.candidate_years)} • JD asks: ${fmtYears(e.required_years)}</div></div>
    <div class="friendly-metrics">
      <div class="friendly-metric"><small>Skills matched</small><b>${skill}%</b><div class="progress"><i style="width:${Math.min(100,skill)}%"></i></div></div>
      <div class="friendly-metric"><small>Experience fit</small><b>${exp}%</b><div class="progress"><i style="width:${Math.min(100,exp)}%"></i></div></div>
      <div class="friendly-metric"><small>Recent proof</small><b>${recent}%</b><div class="progress"><i style="width:${Math.min(100,recent)}%"></i></div></div>
    </div>
    <div class="eval-grid">
      <div class="eval-block"><h4>✓ What matches</h4><div class="chips">${chips(e.matched_skills)}</div><h4 style="margin-top:14px">Recent/current evidence</h4><div class="chips">${chips(e.recent_skills)}</div></div>
      <div class="eval-block"><h4>⚠ What to verify</h4>${listItems(e.risks)}<h4 style="margin-top:14px">Missing / unclear skills</h4><div class="chips">${chips(e.missing_skills,'No major gap detected')}</div></div>
    </div>
    <div class="eval-block" style="margin-top:12px"><h4>Questions for your screening call</h4>${listItems(e.screening_questions)}</div>
    <details class="detailsbox"><summary>How was this score calculated?</summary><div><div class="metrics"><div class="metric"><small>Text similarity</small><b>${e.semantic_similarity??'—'}%</b></div><div class="metric"><small>Calibrated text fit</small><b>${e.semantic_fit??'—'}%</b></div><div class="metric"><small>Skill coverage</small><b>${e.skill_coverage??'—'}%</b></div><div class="metric"><small>Experience fit</small><b>${e.experience_fit??'—'}%</b></div><div class="metric"><small>Recent evidence</small><b>${e.recent_evidence??'—'}%</b></div></div>${listItems(e.evidence)}</div></details>
  </div>`;
}'''
s = s[:start] + friendly + s[end:]

s = s.replace("$('analyze').disabled=true;$('status').textContent=`Analyzing ${files.length} resume(s)…`;", "$('analyze').disabled=true;$('analyze').textContent='Analyzing…';$('status').textContent=`Reading and matching ${files.length} resume(s)…`;")
s = s.replace("$('status').textContent=`Done. Ranked ${d.results.length} candidate(s).${d.errors?.length?' '+d.errors.length+' file(s) skipped.':''}`;", "$('status').textContent=`Done — ${d.results.length} candidate(s) ranked.${d.errors?.length?' '+d.errors.length+' file(s) could not be read.':''}`;")
s = s.replace("}catch(e){$('status').textContent=e.message}finally{$('analyze').disabled=false}", "}catch(e){$('status').textContent=e.message}finally{$('analyze').disabled=false;$('analyze').textContent='✦ Find best matches'}")

p.write_text(s)
print('UI polished')
