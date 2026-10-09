import csv,io
from app.services.export import decisions_csv
from test_api import client,login,picture


def test_spreadsheet_formulas_are_neutralized():
    rows=[{'filename':s,'batch':'ordinary'} for s in ['=1+1','+CMD','-2+3','@SUM(A1)','  =2','\tformula']]
    result=list(csv.DictReader(io.StringIO(decisions_csv(rows))))
    assert all(r['filename'].startswith("'") for r in result)
    assert all(r['batch']=='ordinary' for r in result)


def test_csv_is_authenticated_filtered_and_downloadable(client):
    assert client.get('/api/exports/decisions.csv').status_code==401
    login(client)
    client.post('/api/images',files={'file':('one.png',picture())},data={'batch':'one'})
    client.post('/api/images',files={'file':('two.png',picture())},data={'batch':'two'})
    response=client.get('/api/exports/decisions.csv?batch=one')
    assert response.status_code==200 and 'attachment' in response.headers['content-disposition']
    rows=list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows)==1 and rows[0]['filename']=='one.png' and rows[0]['decision']=='reject'
