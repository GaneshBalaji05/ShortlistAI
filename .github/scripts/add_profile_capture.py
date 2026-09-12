from pathlib import Path

p=Path('main.py')
s=p.read_text()

s=s.replace('    _ensure_column(cur, "candidates", "resume_filename", "TEXT")\n', '    _ensure_column(cur, "candidates", "resume_filename", "TEXT")\n    _ensure_column(cur, "candidates", "profile_details", "TEXT")\n', 1)

marker='''def detect_phone(text: str) -> str:\n    compact = re.sub(r"[() ]","", text)\n    m = re.search(r"(?:\\+?91[\\s-]?)?[6-9]\\d{9}", compact)\n    return m.group(0) if m else ""\n'''
addition=r'''

def _label_value(text: str, labels: List[str], max_len: int = 100) -> str:
    for label in labels:
        m = re.search(rf"(?im)^\s*(?:{label})\s*[:\-–|]\s*([^\n\r]{{1,{max_len}}})", text)
        if m:
            value = re.sub(r"\s+", " ", m.group(1)).strip(" |:-")
            if value:
                return value
    return ""

def _money_value(text: str, labels: List[str]) -> str:
    value = _label_value(text, labels, 55)
    if value:
        return value
    label = "|".join(labels)
    m = re.search(rf"(?i)(?:{label})\s*(?:is|of|:|-)?\s*(?:inr|rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lakh|lac|k|pa)?", text)
    if not m:
        return ""
    return (m.group(1) + (" " + m.group(2) if m.group(2) else "")).strip()

def _detect_education(text: str) -> Dict[str,str]:
    degrees = re.findall(r"(?i)\b(?:ph\.?d|m\.?tech|m\.?e\.?|mca|mba|m\.?sc|b\.?tech|b\.?e\.?|bca|b\.?sc|bcom|b\.com|ba|b\.a)\b", text)
    cleaned=[]
    for d in degrees:
        v=re.sub(r"\s+", "", d).upper().replace(".", "")
        if v not in cleaned:
            cleaned.append(v)
    postgraduate = next((d for d in cleaned if d in {"PHD","MTECH","ME","MCA","MBA","MSC"}), "")
    undergraduate = next((d for d in cleaned if d in {"BTECH","BE","BCA","BSC","BCOM","BA"}), "")
    return {"ug": undergraduate, "highest_qualification": postgraduate or undergraduate}

def extract_profile_details(text: str, filename: str) -> Dict[str,Any]:
    edu = _detect_education(text)
    linkedin = ""
    m = re.search(r"(?i)(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_\-%/]+", text)
    if m:
        linkedin = m.group(0)
        if not linkedin.lower().startswith("http"):
            linkedin = "https://" + linkedin
    notice = _label_value(text, [r"notice\s*period", r"np"], 45)
    if not notice and re.search(r"(?i)\bimmediate(?:ly)?\s+(?:available|joiner|joining)\b|\bimmediate joiner\b", text):
        notice = "Immediate"
    details = {
        "candidate_full_name": detect_name(text, filename),
        "contact_no": detect_phone(text),
        "email_id": detect_email(text),
        "total_experience": parse_candidate_years(text),
        "relevant_experience": _label_value(text, [r"relevant\s*(?:experience|exp)"], 40),
        "current_organization": _label_value(text, [r"current\s*(?:organization|organisation|company)", r"present\s*(?:organization|organisation|company)"], 90),
        "current_designation": _label_value(text, [r"current\s*(?:designation|role|title)", r"designation", r"job\s*title"], 90),
        "current_company_experience": _label_value(text, [r"current\s*company\s*(?:experience|exp)"], 40),
        "current_ctc": _money_value(text, [r"current\s*ctc", r"present\s*ctc"]),
        "expected_ctc": _money_value(text, [r"expected\s*ctc", r"expecting\s*ctc"]),
        "holding_offers": _label_value(text, [r"holding\s*offers?", r"offers?\s*in\s*hand", r"offer\s*in\s*hand"], 80),
        "notice_period": notice,
        "lwd": _label_value(text, [r"lwd", r"last\s*working\s*day"], 45),
        "tentative_doj": _label_value(text, [r"tentative\s*doj", r"date\s*of\s*joining", r"doj"], 45),
        "native_location": _label_value(text, [r"native\s*location", r"native\s*place"], 60),
        "current_location": _label_value(text, [r"current\s*location", r"present\s*location"], 60),
        "preferred_location": _label_value(text, [r"preferred\s*location", r"preferred\s*locations"], 100),
        "linkedin_id": linkedin,
        "profile_link": linkedin,
        "ug": edu["ug"],
        "highest_qualification": edu["highest_qualification"],
        "skills": ", ".join(find_skills(text)),
    }
    return details
'''
if 'def extract_profile_details(' not in s:
    assert marker in s
    s=s.replace(marker, marker+addition, 1)

old='''def _candidate_dict(row: sqlite3.Row) -> Dict[str,Any]:\n    d = dict(row)\n    d["ai_evaluation"] = _decode_ai_details(d.pop("ai_details", None))\n    return d\n'''
new='''def _candidate_dict(row: sqlite3.Row) -> Dict[str,Any]:\n    d = dict(row)\n    d["ai_evaluation"] = _decode_ai_details(d.pop("ai_details", None))\n    d["profile_details"] = _decode_ai_details(d.get("profile_details")) or {}\n    return d\n'''
assert old in s
s=s.replace(old,new,1)

old='''    current_ctc: str = ""\n    expected_ctc: str = ""\n    job_id: Optional[int] = None\n    stage: str = "Sourced"\n'''
new='''    current_ctc: str = ""\n    expected_ctc: str = ""\n    resume_text: str = ""\n    resume_filename: str = ""\n    profile_details: Optional[Dict[str,Any]] = None\n    job_id: Optional[int] = None\n    stage: str = "Sourced"\n'''
assert old in s
s=s.replace(old,new,1)

endpoint=r'''

@app.post("/api/profile/parse")
async def parse_profile(profile: UploadFile = File(...)):
    name = profile.filename or "resume"
    data = await profile.read()
    try:
        text = extract_text(name, data)
    except Exception as e:
        raise HTTPException(400, str(e))
    if len(text.strip()) < 80:
        raise HTTPException(400, "Very little readable text was found in this profile. Try a text-based PDF or DOCX.")
    details = extract_profile_details(text, name)
    detected = [k for k,v in details.items() if v not in (None, "", [])]
    return {"filename": name,"details": details,"detected_count": len(detected),"detected_fields": detected,"resume_text": text,"message": "Profile details captured. Review the auto-filled fields before saving."}
'''
anchor='''class ExportPayload(BaseModel):\n    results: List[Dict[str,Any]]\n'''
if '@app.post("/api/profile/parse")' not in s:
    assert anchor in s
    s=s.replace(anchor,anchor+endpoint,1)

old='''        """INSERT INTO candidates(name,email,phone,experience,skills,source,notice_period,current_ctc,\n           expected_ctc,job_id,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",\n        (x.name,x.email,x.phone,x.experience,x.skills,x.source,x.notice_period,x.current_ctc,\n         x.expected_ctc,x.job_id,x.stage,now,now)\n'''
new='''        """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,source,notice_period,current_ctc,\n           expected_ctc,profile_details,job_id,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",\n        (x.name,x.email,x.phone,x.experience,x.skills,x.resume_text,x.resume_filename,x.source,x.notice_period,x.current_ctc,\n         x.expected_ctc,json.dumps(x.profile_details or {}),x.job_id,x.stage,now,now)\n'''
assert old in s
s=s.replace(old,new,1)

old='''                """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,\n                   source,job_id,stage,ai_score,rating,ai_details,created_at,updated_at)\n                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",\n                (s["candidate"], detect_email(txt), detect_phone(txt), s["candidate_years"], skills,\n                 txt, name, "Resume upload", job_id, "Sourced", s["score"], s["rating"],\n                 json.dumps(s), now, now)\n'''
new='''                """INSERT INTO candidates(name,email,phone,experience,skills,resume_text,resume_filename,\n                   source,job_id,stage,ai_score,rating,ai_details,profile_details,created_at,updated_at)\n                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",\n                (s["candidate"], detect_email(txt), detect_phone(txt), s["candidate_years"], skills,\n                 txt, name, "Resume upload", job_id, "Sourced", s["score"], s["rating"],\n                 json.dumps(s), json.dumps(extract_profile_details(txt, name)), now, now)\n'''
assert old in s
s=s.replace(old,new,1)
p.write_text(s)

p=Path('static/index.html')
s=p.read_text()
css='''\n.profile-reader{border:1px solid #3a1114;background:#100607;border-radius:14px;padding:14px;margin-bottom:16px}.profile-reader input[type=file]{width:100%;margin:8px 0 10px}.capture-status{font-size:13px;color:var(--muted);margin-top:9px}.capture-status.ok{color:#77e8a9}.capture-preview{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px}.capture-item{background:#080808;border:1px solid #2b2b2b;border-radius:10px;padding:9px}.capture-item small{display:block;color:var(--muted);font-size:11px}.capture-item b{font-size:13px;word-break:break-word}.tracker-details{margin-top:12px;border-top:1px solid var(--line);padding-top:12px}.tracker-details summary{cursor:pointer;font-weight:800;color:#f4f4f4;margin-bottom:12px}@media(max-width:900px){.capture-preview{grid-template-columns:1fr}}\n'''
if '.profile-reader{' not in s:
    s=s.replace('</style>',css+'\n</style>',1)

old='''      <h3>Add candidate manually</h3><p class="helper">For faster entry, use AI Match and choose “Save candidates to ATS”.</p>\n      <div class="grid2">'''
new='''      <h3>Add candidate</h3><p class="helper">Upload a profile and ShortlistAI will capture the candidate details automatically. Review them before saving.</p>\n      <div class="profile-reader">\n        <b>Auto-fill from profile</b><div class="helper">PDF, DOCX, TXT or MD</div>\n        <input id="profileUpload" type="file" accept=".pdf,.docx,.txt,.md"/>\n        <button id="parseProfile" class="btn" type="button">＋ Upload & capture details</button>\n        <div id="profileParseStatus" class="capture-status">No profile selected.</div>\n        <div id="profilePreview" class="capture-preview hidden"></div>\n      </div>\n      <div class="grid2">'''
assert old in s
s=s.replace(old,new,1)

old='''      <div class="field"><label>Skills</label><input id="cSkills"/></div>\n      <div class="field"><label>Job</label><select id="cJob"><option value="">Unassigned</option></select></div>\n      <button id="addCandidate" class="btn">Add candidate</button>'''
new='''      <div class="field"><label>Skills</label><input id="cSkills"/></div>\n      <details class="tracker-details"><summary>Tracker details</summary>\n        <div class="grid2">\n          <div class="field"><label>Current organization</label><input id="cCurrentOrg"/></div><div class="field"><label>Current designation</label><input id="cDesignation"/></div>\n          <div class="field"><label>Relevant experience</label><input id="cRelExp"/></div><div class="field"><label>Notice period / LWD</label><input id="cNotice"/></div>\n          <div class="field"><label>Current CTC</label><input id="cCurrentCTC"/></div><div class="field"><label>Expected CTC</label><input id="cExpectedCTC"/></div>\n          <div class="field"><label>Offer in hand</label><input id="cOffers"/></div><div class="field"><label>Current location</label><input id="cCurrentLoc"/></div>\n          <div class="field"><label>Preferred location</label><input id="cPreferredLoc"/></div><div class="field"><label>LinkedIn / Profile link</label><input id="cLinkedIn"/></div>\n        </div>\n      </details>\n      <div class="field"><label>Job</label><select id="cJob"><option value="">Unassigned</option></select></div>\n      <button id="addCandidate" class="btn">＋ Add candidate</button>'''
assert old in s
s=s.replace(old,new,1)
s=s.replace('let jobs=[],candidates=[],latest=[];', 'let jobs=[],candidates=[],latest=[],parsedProfile={},parsedResumeText="",parsedResumeFilename="";',1)

helper=r'''
function setv(id,v){const el=$(id);if(el&&v!==undefined&&v!==null&&String(v).trim()!=="")el.value=v}
function profilePreview(d){
  const labels={candidate_full_name:'Name',contact_no:'Phone',email_id:'Email',total_experience:'Total experience',relevant_experience:'Relevant experience',current_organization:'Current organization',current_designation:'Current designation',current_ctc:'Current CTC',expected_ctc:'Expected CTC',notice_period:'Notice period',lwd:'LWD',current_location:'Current location',preferred_location:'Preferred location',linkedin_id:'LinkedIn',highest_qualification:'Qualification'};
  const items=Object.entries(labels).filter(([k])=>d[k]!==undefined&&d[k]!==null&&String(d[k]).trim()!=='').slice(0,14);
  if(!items.length){$('profilePreview').classList.add('hidden');return}
  $('profilePreview').innerHTML=items.map(([k,l])=>`<div class="capture-item"><small>${esc(l)}</small><b>${esc(d[k])}</b></div>`).join('');$('profilePreview').classList.remove('hidden');
}
function mergeTrackerDetails(){return {...parsedProfile,current_organization:$('cCurrentOrg').value,current_designation:$('cDesignation').value,relevant_experience:$('cRelExp').value,notice_period:$('cNotice').value,current_ctc:$('cCurrentCTC').value,expected_ctc:$('cExpectedCTC').value,holding_offers:$('cOffers').value,current_location:$('cCurrentLoc').value,preferred_location:$('cPreferredLoc').value,linkedin_id:$('cLinkedIn').value,profile_link:$('cLinkedIn').value}}
$('parseProfile').onclick=async()=>{
  const f=$('profileUpload').files[0];if(!f){$('profileParseStatus').textContent='Choose a profile first.';return}
  const fd=new FormData();fd.append('profile',f);$('parseProfile').disabled=true;$('parseProfile').textContent='Reading profile…';$('profileParseStatus').classList.remove('ok');$('profileParseStatus').textContent='Capturing candidate details…';
  try{const r=await fetch('/api/profile/parse',{method:'POST',body:fd}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not read profile');parsedProfile=d.details||{};parsedResumeText=d.resume_text||'';parsedResumeFilename=d.filename||f.name;
    setv('cName',parsedProfile.candidate_full_name);setv('cEmail',parsedProfile.email_id);setv('cPhone',parsedProfile.contact_no);setv('cExp',parsedProfile.total_experience);setv('cSkills',parsedProfile.skills);setv('cSource','Profile upload');setv('cCurrentOrg',parsedProfile.current_organization);setv('cDesignation',parsedProfile.current_designation);setv('cRelExp',parsedProfile.relevant_experience);setv('cNotice',parsedProfile.notice_period||parsedProfile.lwd);setv('cCurrentCTC',parsedProfile.current_ctc);setv('cExpectedCTC',parsedProfile.expected_ctc);setv('cOffers',parsedProfile.holding_offers);setv('cCurrentLoc',parsedProfile.current_location);setv('cPreferredLoc',parsedProfile.preferred_location);setv('cLinkedIn',parsedProfile.linkedin_id||parsedProfile.profile_link);profilePreview(parsedProfile);$('profileParseStatus').textContent=`Captured ${d.detected_count||0} details. Please review before saving.`;$('profileParseStatus').classList.add('ok');
  }catch(e){$('profileParseStatus').textContent=e.message;toast(e.message)}finally{$('parseProfile').disabled=false;$('parseProfile').textContent='＋ Upload & capture details'}
};
'''
anchor='''function listItems(arr,empty='None'){return `<ul>${(arr&&arr.length?arr:[empty]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`}\n'''
assert anchor in s
s=s.replace(anchor,anchor+helper,1)

old='''      experience:$('cExp').value?Number($('cExp').value):null,skills:$('cSkills').value,source:$('cSource').value,\n      job_id:$('cJob').value?Number($('cJob').value):null,stage:$('cStage').value\n'''
new='''      experience:$('cExp').value?Number($('cExp').value):null,skills:$('cSkills').value,source:$('cSource').value,\n      notice_period:$('cNotice').value,current_ctc:$('cCurrentCTC').value,expected_ctc:$('cExpectedCTC').value,resume_text:parsedResumeText,resume_filename:parsedResumeFilename,profile_details:mergeTrackerDetails(),\n      job_id:$('cJob').value?Number($('cJob').value):null,stage:$('cStage').value\n'''
assert old in s
s=s.replace(old,new,1)
s=s.replace("    toast('Candidate added');await loadCandidates();await loadStats();\n", "    toast('Candidate added');parsedProfile={};parsedResumeText='';parsedResumeFilename='';$('profileUpload').value='';$('profileParseStatus').textContent='No profile selected.';$('profileParseStatus').classList.remove('ok');$('profilePreview').classList.add('hidden');await loadCandidates();await loadStats();\n",1)

render=r'''
function renderProfileDetails(d){
  if(!d||!Object.keys(d).length)return '';
  const labels={current_organization:'Current organization',current_designation:'Designation',relevant_experience:'Relevant experience',current_ctc:'Current CTC',expected_ctc:'Expected CTC',holding_offers:'Offer in hand',notice_period:'Notice period',lwd:'LWD',current_location:'Current location',preferred_location:'Preferred location',native_location:'Native location',ug:'UG',highest_qualification:'Qualification',linkedin_id:'LinkedIn'};
  const items=Object.entries(labels).filter(([k])=>d[k]!==undefined&&d[k]!==null&&String(d[k]).trim()!=='');if(!items.length)return '';
  return `<div class="card" style="margin-top:14px"><h3>Captured profile details</h3><div class="profile">${items.map(([k,l])=>`<div><small>${esc(l)}</small><b>${esc(d[k])}</b></div>`).join('')}</div><div class="helper">Auto-captured from the uploaded profile. Recruiter review is recommended.</div></div>`;
}
'''
anchor='''function renderEvaluation(e){\n'''
assert anchor in s
s=s.replace(anchor,render+'\n'+anchor,1)
old='''    <div class="row"><button class="btn" onclick="reevaluate(${c.id})">Re-run AI evaluation</button></div>\n    ${renderEvaluation(c.ai_evaluation)}\n'''
new='''    <div class="row"><button class="btn" onclick="reevaluate(${c.id})">Re-run AI evaluation</button></div>\n    ${renderProfileDetails(c.profile_details)}\n    ${renderEvaluation(c.ai_evaluation)}\n'''
assert old in s
s=s.replace(old,new,1)
p.write_text(s)
