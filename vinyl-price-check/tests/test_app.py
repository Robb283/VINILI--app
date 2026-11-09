import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import main as m


@pytest.fixture(autouse=True)
def clear(monkeypatch):
    m.cache.clear()
    m.requests_window.clear()
    monkeypatch.delenv('DISCOGS_TOKEN', raising=False)
    monkeypatch.delenv('ENABLE_MARKET_DATA', raising=False)


def body(price=20, condition='VG+'):
    return m.Assessment(release_id=1, asking_price=price, condition=condition, confirmed=True)


@pytest.mark.parametrize('price,verdict', [(15,'Conveniente'),(16,'Corretto'),(24,'Corretto'),(25,'Troppo alto')])
def test_thresholds(price, verdict):
    d=m.evaluate(body(price), {'Very Good Plus (VG+)':{'value':20,'currency':'EUR'}}, {})
    assert d['verdict']==verdict
    assert d['confidence']=='Bassa'
    assert d['market_value_range'] is None


def test_lowest_listing_is_never_a_valuation():
    d=m.evaluate(body(), {}, {'lowest_price':{'value':1,'currency':'EUR'}})
    assert d['verdict']=='Non valutabile'
    assert d['reference'] is None


def test_no_currency_confusion():
    d=m.evaluate(body(), {'Very Good Plus (VG+)':{'value':20,'currency':'USD'}}, {})
    assert d['verdict']=='Non valutabile'
    assert d['suggestions_range'] is None


@pytest.mark.parametrize('v', [None, -1, 0, float('nan'), float('inf'), '25', True])
def test_bad_money(v):
    assert m.positive_eur({'value':v,'currency':'EUR'}) is None


def test_missing_condition():
    d=m.evaluate(body(condition=None), {'Very Good Plus (VG+)':{'value':20,'currency':'EUR'}}, {})
    assert d['verdict']=='Non valutabile'


def test_blocked_release():
    d=m.evaluate(body(), {'Very Good Plus (VG+)':{'value':20,'currency':'EUR'}}, {'blocked_from_sale':True})
    assert d['verdict']=='Non valutabile'


def test_no_secrets_and_validation():
    c=TestClient(m.app)
    assert c.get('/').status_code==200
    assert c.get('/api/health').json()['search_configured'] is False
    assert c.get('/api/search?artist=Pink+Floyd&title=Animals').status_code==503
    assert c.post('/api/assess',json={'release_id':1,'asking_price':-1}).status_code==422
    assert c.post('/api/assess',json={'release_id':1,'asking_price':25}).status_code==422
    assert c.get('/.env').status_code==404


def test_unavailable_suggestions_keep_real_stats(monkeypatch):
    monkeypatch.setenv('ENABLE_MARKET_DATA','true')
    async def fake(path, params=None, authenticated=True):
        if path.startswith('/releases/'): return {'formats':[{'name':'Vinyl'}], 'title':'Test fixture'}
        if 'stats' in path: return {'lowest_price':{'value':2,'currency':'EUR'}}
        raise HTTPException(503,'Seller settings unavailable')
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).post('/api/assess',json=body().model_dump()).json()
    assert d['verdict']=='Non valutabile'
    assert d['lowest_listing']==2
    assert len(d['warnings'])==1


def test_market_disabled(monkeypatch):
    paths=[]
    async def fake(path, params=None, authenticated=True):
        paths.append(path)
        return {'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).post('/api/assess',json=body().model_dump()).json()
    assert d['verdict']=='Non valutabile'
    assert paths==['/releases/1']


def test_reissue_filter_and_first_press_warning(monkeypatch):
    async def fake(*args,**kwargs):
        return {'results':[{'id':1,'format':['Vinyl','Reissue']},{'id':2,'format':['Vinyl']}], 'pagination':{'pages':2}}
    monkeypatch.setattr(m,'discogs',fake)
    c=TestClient(m.app)
    d=c.get('/api/search?artist=A&title=B&pressing=reissue').json()
    assert [r['id'] for r in d['results']]==[1]
    assert c.get('/api/search?artist=A&title=B&pressing=first').json()['warning']


def test_single_query_for_typed_or_photo_text(monkeypatch):
    seen = []
    async def fake(path, params=None, authenticated=True):
        seen.append(params)
        return {'results': [], 'pagination': {}}
    monkeypatch.setattr(m, 'discogs', fake)
    c = TestClient(m.app)
    assert c.get('/api/search?q=Terry+Allen+Lubbock+on+Everything').status_code == 200
    assert seen[0]['q'] == 'Terry Allen Lubbock on Everything'
    assert 'artist' not in seen[0]
    assert seen[0]['format'] == 'Vinyl'
    assert c.get('/api/search?q=%20%20').status_code == 422
    assert c.get('/api/search?q=' + 'a' * 221).status_code == 422
