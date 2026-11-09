import pytest
from fastapi.testclient import TestClient
from app import main as m


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    m.cache.clear(); m.requests_window.clear()
    monkeypatch.delenv('DISCOGS_TOKEN', raising=False)
    monkeypatch.delenv('ENABLE_MARKET_DATA', raising=False)


@pytest.mark.parametrize('value,expected', [('1979',1979),('1979-00-00',1979),(1979,1979),('Unknown',None),('',None),('0000',None),('3000',None)])
def test_real_dates_only(value, expected):
    assert m.release_year(value) == expected


def test_earliest_year_does_not_prefer_repress_or_promo():
    rows, chosen, earliest = m.rank_versions([
        {'id':2,'released':'1979','format':'LP, Repress'},
        {'id':3,'released':'1978','format':'LP, Promo'},
        {'id':4,'released':'','format':'LP'},
        {'id':1,'released':'1979','format':'LP, Album'},
        {'id':5,'released':'1977','format':'CD','major_formats':['CD']},
    ])
    assert chosen['id'] == 1
    assert earliest == 1979
    assert len(rows) == 4


def test_undated_is_not_certified():
    _, _, earliest=m.rank_versions([{'id':1,'format':'LP','released':''}])
    assert earliest is None
    d=m.release_details({'id':1,'formats':[{'name':'Vinyl'}]}, earliest)
    assert d['verdict']=='Prima stampa non determinabile'


def test_notes_and_matrix_are_preserved_without_certifying():
    d=m.release_details({'id':1,'year':1979,'formats':[{'name':'Vinyl','descriptions':['LP']}],
                        'notes':'First issue address differs from [r2].',
                        'identifiers':[{'type':'Matrix / Runout','value':'ABC A1','description':'Side A'}]},1979)
    assert d['identifiers'][0]['value']=='ABC A1'
    assert d['notes'].endswith('[r2].')
    assert d['verdict']=='Candidata più precoce trovata'
    assert d['confidence']=='Da verificare sulla copia'


def test_repress_of_same_year_is_not_an_original():
    d=m.release_details({'id':2,'year':1979,'formats':[{'name':'Vinyl','descriptions':['Repress']}]},1979)
    assert d['verdict']=='Classificata come ristampa / repress'


def test_guide_fetches_catalogue_only_and_applies_country(monkeypatch):
    seen=[]
    async def fake(path, params=None, authenticated=True):
        seen.append((path,params))
        if path=='/database/search':
            assert 'format' not in params
            return {'results':[{'id':10,'title':'Artist - Album','year':1979,'format':['CD']}]}
        if path=='/masters/10': return {'id':10,'title':'Album','year':1979,'artists':[{'name':'Artist'}]}
        if path=='/masters/10/versions':
            assert params['country']=='US'
            return {'versions':[{'id':1,'released':'1979','format':'LP'},{'id':2,'released':'1985','format':'LP, Reissue'}], 'pagination':{'pages':1,'items':2}}
        if path=='/releases/1': return {'id':1,'master_id':10,'title':'Album','country':'US','year':1979,'formats':[{'name':'Vinyl'}], 'notes':'Check address.', 'lowest_price':999}
        raise AssertionError('Unexpected endpoint: '+path)
    monkeypatch.setattr(m,'discogs',fake)
    c=TestClient(m.app)
    d=c.get('/api/guide?q=Artist+Album&country=US').json()
    assert d['found'] and d['guide']['id']==1
    assert d['guide']['price']['available'] is False
    assert 'lowest_price' not in d['guide']
    assert not any('marketplace' in path for path,_ in seen)
    assert d['scope']=='US'


def test_truncated_search_is_visible(monkeypatch):
    async def fake(path, params=None, authenticated=True):
        if path=='/masters/10': return {'title':'Album','year':1979}
        if '/versions' in path: return {'versions':[{'id':params['page'],'format':'LP','released':'1979'}], 'pagination':{'pages':5,'items':240}}
        return {'id':1,'year':1979,'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide?q=A&master_id=10').json()
    # Query minimum length is checked before any Discogs call.
    assert 'detail' in d
    d=TestClient(m.app).get('/api/guide?q=AA&master_id=10').json()
    assert d['partial'] and d['scanned']==3
    assert 'parziale' in d['guide']['explanation']


def test_no_results_and_no_secret_leak(monkeypatch):
    async def fake(*args,**kwargs): return {'results':[]}
    monkeypatch.setattr(m,'discogs',fake)
    c=TestClient(m.app)
    assert c.get('/api/guide?q=Unknown+Album').json()['found'] is False
    assert c.get('/.env').status_code==404
    assert c.post('/api/assess',json={'asking_price':80}).status_code==404
    assert c.get('/api/health').json()['mode']=='first_press_guide'


def test_missing_token_and_whitespace():
    c=TestClient(m.app)
    assert c.get('/api/guide?q=Artist+Album').status_code==503
    assert c.get('/api/guide?q=%20%20').status_code==422


def test_title_match_beats_related_album_notes():
    query='Vasco Rossi Fronte del palco'
    assert m.master_match_score(query,'Vasco Rossi - Fronte Del Palco - Live') > m.master_match_score(query,'Vasco - Vasco Live 10-7-90 San Siro')
    assert m.master_match_score(query,'Vasco - Vasco Live 10-7-90 San Siro') < .55
