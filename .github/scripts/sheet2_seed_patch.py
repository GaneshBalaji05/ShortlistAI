from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

imp = 'from sklearn.metrics.pairwise import cosine_similarity\n'
if 'from shortlistai_test_seed import seed_test_candidate' not in s:
    s = s.replace(imp, imp + 'from shortlistai_test_seed import seed_test_candidate\n', 1)

old = '@app.on_event("startup")\ndef startup():\n    init_db()\n'
new = '@app.on_event("startup")\ndef startup():\n    init_db()\n    seed_test_candidate(DB_PATH)\n'
if 'seed_test_candidate(DB_PATH)' not in s:
    s = s.replace(old, new, 1)

pairs = [
    ('"Recruiter"', '"Recruter"'),
    ('"Contact Number"', '"Number"'),
    ('"Email"', '"Mail-id"'),
    ('"Total Experience"', '"Tot Exp (In Years)"'),
    ('"Relevant Experience"', '"Rel Exp (In Years)"'),
    ('"Current Company Experience"', '"Current company Exp (In Years)"'),
    ('"Current CTC"', '"CTC (In LPA)"'),
    ('"Expected CTC"', '"ECTC (In LPA)"'),
    ('"Offer in Hand"', '"Offer In hand (if any)"'),
    ('"Last Appraisal"', '"Last Appraisal & Month"'),
    ('"DOJ"', '"D.O.J"'),
]
for a, b in pairs:
    s = s.replace(a, b)

p.write_text(s, encoding='utf-8')
print('Sheet2 master + test seed patch applied')
