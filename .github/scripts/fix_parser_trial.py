from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

start = s.index('def detect_name(')
end = s.index('\ndef detect_email(', start)
new_name = r'''def detect_name(text: str, filename: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    for line in lines[:14]:
        candidate = re.split(r"(?:📍|📞|✉|☎|\||\s{2,})", line, maxsplit=1)[0].strip(" ,-|")
        candidate = re.sub(r"\b(?:resume|curriculum vitae|cv)\b", "", candidate, flags=re.I).strip(" ,-|")
        if 1 < len(candidate.split()) <= 5 and len(candidate) < 60 and re.fullmatch(r"[A-Za-z .'-]+", candidate):
            return candidate.title()
        m = re.match(r"^\s*([A-Za-z][A-Za-z .'-]{2,50}?)(?=\s*(?:\+?91|[6-9]\d{9}|[A-Za-z0-9._%+-]+@|📍|📞|✉))", line)
        if m:
            candidate = m.group(1).strip(" ,-|")
            if 1 < len(candidate.split()) <= 5:
                return candidate.title()
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"(?i)\b(?:resume|cv|profile)\b|\(\d+\)|\[\d+[^\]]*\]", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title() or "Candidate"
'''
s = s[:start] + new_name + s[end:]

start = s.index('def _latest_experience(')
end = s.index('\ndef extract_profile_details(', start)
new_latest = r'''def _latest_experience(text: str) -> Dict[str,str]:
    date_re = re.compile(r"(?i)\b(?:0?[1-9]|1[0-2])[/\-.](?:19|20)\d{2}\s*(?:-|–|to)\s*(?:(?:0?[1-9]|1[0-2])[/\-.](?:19|20)\d{2}|present|current)\b")
    m = date_re.search(text)
    if not m:
        return {"current_designation":"", "current_organization":"", "current_location":""}
    before = text[max(0, m.start() - 180):m.start()]
    before = re.split(r"(?:\n|•|●|▪|◦)", before)[-1]
    before = re.sub(r"(?i)^.*\b(?:experience|employment|work history)\b\s*", "", before).strip(" ,-–|\t")
    title = before[-100:].strip(" ,-–|\t")
    after = text[m.end():m.end() + 180]
    company_line = re.split(r"(?:\n|•|●|▪|◦)", after, maxsplit=1)[0].strip(" ,-–|\t")
    company_line = re.split(r"(?i)\s+(?=manage(?:d|s)?\b|partner(?:ed|s)?\b|develop(?:ed|s)?\b|source(?:d|s)?\b|coordinate(?:d|s)?\b|work(?:ed|s)?\b|recruit(?:ed|s)?\b|build(?:t|s)?\b|handle(?:d|s)?\b)", company_line, maxsplit=1)[0].strip(" ,-–|\t")
    company, location = company_line, ""
    if company_line and "," in company_line:
        parts = [x.strip() for x in company_line.split(",") if x.strip()]
        if parts:
            company = parts[0]
            if len(parts) > 1:
                location = parts[-1]
    return {"current_designation": title, "current_organization": company, "current_location": location}
'''
s = s[:start] + new_latest + s[end:]

p.write_text(s, encoding='utf-8')
