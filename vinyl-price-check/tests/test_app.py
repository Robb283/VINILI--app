import asyncio
import pytest
from fastapi.testclient import TestClient
from app import main as m
from app import translate as tr

@pytest.fixture(autouse=True)
def clean(monkeypatch):
    m.cache.clear();m.requests_window.clear();tr._cache.clear();tr._budget_used=0
    monkeypatch.delenv('DISCOGS_TOKEN',raising=False);monkeypatch.delenv('ENABLE_MARKET_DATA',raising=False)


def v(id,country,year,format='LP, Album'):
    return {'id':id,'country':country,'released':str(year),'format':format}

@pytest.mark.parametrize('value,expected',[('1979',1979),('1979-00-00',1979),(1979,1979),('Unknown',None),('',None),('0000',None),('3000',None)])
def test_date(value,expected):assert m.release_year(value)==expected

@pytest.mark.parametrize('primary,rows,expected',[
(v(1,'UK',1970),[v(1,'UK',1970),v(2,'US',1971)],[(1,'world'),(2,'US')]),
(v(1,'US',1970),[v(1,'US',1970),v(2,'UK',1971)],[(1,'world'),(2,'UK')]),
(v(1,'Italy',1970),[v(1,'Italy',1970),v(2,'US',1972),v(3,'UK',1971)],[(1,'world'),(3,'UK'),(2,'US')]),
(v(1,'France',1970),[v(1,'France',1970),v(2,'US',1972)],[(1,'world'),(2,'US')]),
(v(1,'UK & US',1970),[v(1,'UK & US',1970)],[(1,'world')])])
def test_country_rules(primary,rows,expected):
    assert [(r['id'],role) for r,role in m.select_country_companions(m.version_info(primary),rows)]==expected

def test_chronology_before_reissue_flag_and_no_promo():
    _,chosen,earliest=m.rank_versions([v(1,'US',1979,'LP, Repress'),v(2,'US',1985),v(3,'US',1978,'LP, Promo')])
    assert chosen['id']==1 and earliest==1979

def test_specific_cover_urls_are_validated():
    images=m.release_images({'images':[{'uri':'https://evil.example/a','type':'primary'},{'uri':'https://i.discogs.com/back','type':'secondary'},{'uri':'https://i.discogs.com/front','type':'primary'},{'uri':'javascript:alert(1)'}]})
    assert [x['url'] for x in images]==['https://i.discogs.com/front','https://i.discogs.com/back']

def test_unknown_date_and_verbatim_matrices():
    d=m.release_details({'id':1,'formats':[{'name':'Vinyl'}],'identifiers':[{'type':'Matrix / Runout','value':'ABC ❀ A1'}]},None)
    assert d['verdict']=='Prima stampa non determinabile' and d['identifiers'][0]['value']=='ABC ❀ A1'

def test_album_master_and_three_country_cards(monkeypatch):
    calls=[]
    async def fake(path,params=None,authenticated=True):
        calls.append((path,params))
        if path=='/database/search':
            assert 'format' not in params
            return {'results':[{'id':10,'title':'Artist - Album','format':['CD']}]}
        if path=='/masters/10':return {'title':'Album','artists':[{'name':'Artist'}],'year':1970}
        if '/versions' in path:return {'versions':[v(1,'Italy',1970),v(2,'US',1971),v(3,'UK',1972)],'pagination':{'pages':1,'items':3}}
        id=int(path.rsplit('/',1)[1]);return {'id':id,'country':{1:'Italy',2:'US',3:'UK'}[id],'year':1970,'formats':[{'name':'Vinyl'}],'notes':'English source note.','lowest_price':99,'images':[{'uri':f'https://i.discogs.com/{id}','type':'primary'}]}
    async def translated(*args):return {'text':'Nota italiana di prova.','status':'translated','excerpt':False}
    monkeypatch.setattr(m,'discogs',fake);monkeypatch.setattr(m,'translate_notes',translated)
    d=TestClient(m.app).get('/api/guide?q=Artist+Album').json()
    assert [e['id'] for e in d['editions']]==[1,3,2]
    assert all(not e['price']['available'] and 'lowest_price' not in e for e in d['editions'])
    assert not any('marketplace' in path for path,_ in calls)
    assert len([p for p,_ in calls if '/versions' in p])==1
    assert d['editions'][0]['translation']['text']=='Nota italiana di prova.'

def test_partial_scan_checks_regional_catalogues(monkeypatch):
    regions=[]
    async def fake(path,params=None,authenticated=True):
        if path=='/masters/10':return {'title':'Album'}
        if '/versions' in path:
            country=params.get('country')
            if country:
                regions.append(country)
                return {'versions':[v(2 if country=='UK' else 3,country,1971)],'pagination':{'pages':1,'items':1}}
            return {'versions':[v(1,'Germany',1970)] if params['page']==1 else [],'pagination':{'pages':9,'items':900}}
        id=int(path.rsplit('/',1)[1]);return {'id':id,'country':{1:'Germany',2:'UK',3:'US'}[id],'year':1970,'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide?q=Album&master_id=10').json()
    assert d['partial'] and set(regions)=={'UK','US'} and len(d['editions'])==3

def test_missing_countries_not_invented(monkeypatch):
    async def fake(path,params=None,authenticated=True):
        if path=='/masters/10':return {'title':'Album'}
        if '/versions' in path:return {'versions':[v(1,'Italy',1970)],'pagination':{'pages':1,'items':1}}
        return {'id':1,'country':'Italy','year':1970,'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide?q=Album&master_id=10').json()
    assert d['missing_regions']==['UK','US']

def test_addresses_and_identifiers_are_not_translated():
    source='First pressing with 63 West Ontario Street address and matrix ABC A1. Compare [r123].'
    encoded,protected=tr.protect_text(source,[{'value':'ABC A1'}])
    assert '63 West Ontario Street' not in encoded and 'ABC A1' not in encoded
    restored=encoded
    for token,value in protected.items():restored=restored.replace(token,value)
    assert restored==source
    assert all(len(x.encode())<=450 for x in tr.split_bytes('è '*800))

def test_translation_failure_is_explicit():
    tr._budget_used=4500
    d=asyncio.run(tr.translate_notes('First pressing with a special label.'))
    assert d['status']=='unavailable' and not d['text']

def test_camera_removed_and_no_secrets():
    c=TestClient(m.app);page=c.get('/').text
    assert 'type="file"' not in page and 'photo.js' not in page
    assert c.get('/.env').status_code==404
    assert c.get('/api/guide?q=%20%20').status_code==422
    assert c.get('/api/guide?q=Artist+Album').status_code==503

def test_title_match():
    q='Vasco Rossi Fronte del palco'
    assert m.master_match_score(q,'Vasco Rossi - Fronte Del Palco - Live')>m.master_match_score(q,'Vasco - Vasco Live 10-7-90 San Siro')

def test_italian_fallback_preserves_distinguishing_features():
    note='First pressing with 63 West Ontario Street address on rear jacket. Later repress of [r1577402] has 215 W. Superior address.\nThis first pressing also has a flower etched in the runouts.'
    d=tr.italian_summary(note)
    assert d['status']=='summary'
    assert 'Prima stampa: indirizzo «63 West Ontario Street»' in d['text']
    assert 'Ristampa successiva: indirizzo «215 W. Superior»' in d['text']
    assert 'fiore inciso' in d['text']
    assert tr.italian_summary('An unrelated note.')['status']=='unavailable'

def test_negative_repress_flower_is_not_presented_as_present():
    d=tr.italian_summary('Repress also does not have a flower etched in the runouts.')
    assert 'La ristampa non presenta' in d['text']
    assert 'La prima stampa presenta' not in d['text']

@pytest.mark.parametrize('country,expected',[('Italy',2),('UK',4)])
def test_requested_country_only_uses_dedicated_scan(monkeypatch,country,expected):
    scans=[]
    async def fake(path,params=None,authenticated=True):
        if path=='/masters/10':return {'title':'Album','artists':[{'name':'Artist'}]}
        if '/versions' in path:
            scans.append(params.get('country'))
            # Includes an unrelated earlier edition to exercise the country boundary.
            return {'versions':[v(1,'US',1960),v(2,'Italy',1970),v(3,'Italy',1980),v(4,'UK & Europe',1971)],'pagination':{'pages':1}}
        ident=int(path.rsplit('/',1)[1]);return {'id':ident,'country':country,'year':1970,'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide',params={'q':'Artist Album','master_id':10,'country':country}).json()
    assert scans==[None,country]
    assert [e['id'] for e in d['editions']]==[expected]
    assert d['country']==country and d['editions'][0]['role']=='country'
    assert not d['missing_regions']


def test_missing_requested_country_does_not_fall_back(monkeypatch):
    async def fake(path,params=None,authenticated=True):
        if path=='/masters/10':return {'title':'Album'}
        if '/versions' in path:return {'versions':[v(1,'US',1970)],'pagination':{'pages':1}}
        raise AssertionError('An unrelated release must not be enriched')
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide?q=Album&master_id=10&country=Japan').json()
    assert not d['found'] and d['country']=='Japan'


def test_requested_country_keeps_partial_scan_warning(monkeypatch):
    async def fake(path,params=None,authenticated=True):
        if path=='/masters/10':return {'title':'Album'}
        if '/versions' in path:return {'versions':[v(1,'France',1970)],'pagination':{'pages':3}}
        return {'id':1,'country':'France','year':1970,'formats':[{'name':'Vinyl'}]}
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide?q=Album&master_id=10&country=France').json()
    assert d['partial'] and d['editions'][0]['partial']

@pytest.mark.parametrize('value,region,expected',[
 ('USA & Canada','US',True),('UK & Europe','UK',True),('UK & US','US',True),
 ('Australia','Austria',False),('USSR','US',False),('Europe','Italy',False)])
def test_country_territory_aliases(value,region,expected):
    assert m.country_matches(value,region)==expected


def test_country_facets_include_older_combined_territory(monkeypatch):
    requested=[]
    async def fake(path,params=None,authenticated=True):
        if params.get('per_page')==1:
            return {'filters':{'available':{'country':{'US':3,'USA & Canada':1,'UK':2}}}}
        requested.append(params['country'])
        rows=[v(1,'US',1980),v(2,'USA & Canada',1970)] if params['country']=='USA & Canada' else [v(1,'US',1980)]
        return {'versions':rows,'pagination':{'pages':1,'items':len(rows)}}
    monkeypatch.setattr(m,'discogs',fake)
    d=asyncio.run(m.scan_versions(10,'US'))
    assert requested==['US','USA & Canada']
    assert d['chosen']['id']==2 and d['earliest']==1970
    assert len(d['rows'])==2


def test_absent_country_facets_prevent_false_positive(monkeypatch):
    async def fake(path,params=None,authenticated=True):
        assert params.get('per_page')==1
        return {'filters':{'available':{'country':{'UK':3,'US':5}}}}
    monkeypatch.setattr(m,'discogs',fake)
    d=asyncio.run(m.scan_versions(10,'Italy'))
    assert not d['chosen'] and d['available_countries']==['UK','US']


def test_album_search_prefers_original_over_live_and_tribute(monkeypatch):
    async def fake(path,params=None,authenticated=True):
        if path=='/database/search':return {'results':[
            {'id':2,'title':'Pink Floyd - The Dark Side Of The Moon (Live At Wembley 1974)','year':2023},
            {'id':3,'title':'Various - Return To The Dark Side Of The Moon (A Tribute To Pink Floyd)','year':2006},
            {'id':1,'title':'Pink Floyd - The Dark Side Of The Moon','year':1973}]}
        if path=='/masters/1':return {'title':'The Dark Side Of The Moon','artists':[{'name':'Pink Floyd'}]}
        if path=='/masters/1/versions':return {'versions':[v(10,'Italy',1973)],'pagination':{'pages':1}}
        if path=='/releases/10':return {'id':10,'country':'Italy','year':1973,'formats':[{'name':'Vinyl'}]}
        raise AssertionError('Wrong album selected: '+path)
    monkeypatch.setattr(m,'discogs',fake)
    d=TestClient(m.app).get('/api/guide',params={'q':'Pink Floyd — The Dark Side of the Moon','country':'Italy'}).json()
    assert d['found'] and d['master']['id']==1 and d['editions'][0]['country']=='Italy'
