import os
import tempfile
os.environ['SQLITE_PATH'] = tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
from main import app
from PIL import Image
from io import BytesIO


def test_search_edit_history_and_icons():
    with TestClient(app) as client:
        result = client.post('/api/candidates', json={'name':'Pool QA Candidate','email':'pool-qa@example.test','experience':6,'skills':'Python Pandas NumPy Azure Databricks','notice_period':'30 days','profile_details':{'current_location':'Chennai','custom_field':'preserve'}})
        assert result.status_code == 200, result.text
        candidate_id=result.json()['id']
        matches=client.get('/api/candidates',params={'talent_pool':'Python','min_experience':4,'max_experience':8,'location':'Chennai','notice_period':'30'}).json()
        assert candidate_id in [c['id'] for c in matches]
        assert candidate_id not in [c['id'] for c in client.get('/api/candidates',params={'min_experience':9}).json()]
        response=client.patch(f'/api/candidates/{candidate_id}',json={'talent_pools':[],'profile_details':{'remarks':'Reviewed'}})
        assert response.status_code == 200
        saved=client.get(f'/api/candidates/{candidate_id}').json()
        assert saved['talent_pools']==[]
        assert saved['profile_details']['custom_field']=='preserve'
        assert saved['profile_details']['remarks']=='Reviewed'
        assert len(saved['activity'])>=2
        assert client.get('/api/dashboard-v2').status_code==200
        assert 'talent-pool.js' in client.get('/app').text
        assert client.get('/sw.js').headers['service-worker-allowed']=='/'
        for icon in client.get('/static/manifest.webmanifest').json()['icons']:
            image=Image.open(BytesIO(client.get(icon['src']).content)); image.load()
            assert f'{image.width}x{image.height}' == icon['sizes']
            if icon['purpose']=='maskable':
                assert image.convert('RGBA').getpixel((0,0))[3]==255
