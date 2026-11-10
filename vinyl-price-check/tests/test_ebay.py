import asyncio
import base64
import copy
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient
from app import ebay as e
from app import main as m


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    e._token='';e._token_until=0;e._results.clear();m.cache.clear();m.requests_window.clear()
    monkeypatch.delenv('EBAY_CLIENT_ID',raising=False);monkeypatch.delenv('EBAY_CLIENT_SECRET',raising=False)


def edition():
    return {'id':1360042,'artist':'Love (2)','title':'Love','country':'US','year':1966,
            'labels':[{'catno':'EKL-4001'}],'formats':[{'name':'Vinyl','descriptions':['LP','Album','Mono']}]}


def item(ident='123',price='50.00',currency='EUR'):
    return {'itemId':f'v1|{ident}|0','title':'Love Love LP US 1966 EKL 4001 mono',
            'buyingOptions':['FIXED_PRICE'],'price':{'value':price,'currency':currency},
            'itemWebUrl':f'https://www.ebay.it/itm/{ident}','image':{'imageUrl':'https://i.ebayimg.com/test.jpg'},
            'condition':'Used','localizedAspects':[{'name':'Record Grading','value':'Very Good Plus (VG+)'}]}


def test_declared_catalogue_year_country_format_match():
    result=e.assess(item(),edition())
    assert result['compatibility']=='compatible' and result['price']['value']==50
    assert result['id']=='123' and result['record_grading']=='Very Good Plus (VG+)'
    assert result['shipping'] is None


@pytest.mark.parametrize('title',[
 'Love Love CD US 1966 EKL 4001 mono','Love Love LP lot US 1966 EKL 4001 mono',
 'Love Love LP reissue US 1966 EKL 4001 mono','Love Love LP sleeve only US 1966 EKL 4001 mono',
 'Love Love LP US 1966 EKL 4001 stereo','Beatles Help LP US 1966 EKL 4001 mono'])
def test_incompatible_listings_excluded(title):
    data=item();data['title']=title
    assert e.assess(data,edition()) is None


def test_seller_location_and_listing_date_are_not_pressing_evidence():
    data=item();data['title']='Love Love vinyl EKL 4001 mono';data['itemLocation']={'country':'US'}
    data['itemCreationDate']='1966-01-01T00:00:00Z'
    result=e.assess(data,edition())
    assert result['compatibility']=='unverified'
    assert not result['evidence']['country'] and not result['evidence']['year']


def test_explicit_aspect_contradictions_are_excluded():
    data=item();data['localizedAspects']=[{'name':'Release Year','value':'2015'}]
    assert e.assess(data,edition()) is None
    data['localizedAspects']=[{'name':'Country/Region of Manufacture','value':'Japan'}]
    assert e.assess(data,edition()) is None
    data['localizedAspects']=[{'name':'Catalog Number','value':'EKS-74001'}]
    assert e.assess(data,edition()) is None


def test_both_auction_and_fixed_price_excluded():
    data=item();data['buyingOptions']=['AUCTION','FIXED_PRICE']
    assert e.assess(data,edition()) is None


@pytest.mark.parametrize('price',['NaN','Infinity','0','-4',None,True])
def test_invalid_prices_rejected(price):
    assert e.assess(item(price=price),edition()) is None


def test_shipping_zero_and_other_currency_remain_separate():
    data=item();data['shippingOptions']=[{'shippingCost':{'value':'0','currency':'USD'}}]
    result=e.assess(data,edition())
    assert result['shipping']=={'value':0,'currency':'USD'}
    assert result['price']['currency']=='EUR'


def test_insufficient_and_mixed_currencies_do_not_make_a_range():
    data=[e.assess(item('1'),edition()),e.assess(item('2',currency='USD'),edition())]
    assert not e.price_summary(data)['available']
    assert e.price_summary(data)['count']==1


def test_unverified_copies_excluded_from_price_range():
    data=[e.assess(item(str(i),str(v)),edition()) for i,v in enumerate([40,60,100])]
    unknown=item('9','9999');unknown['title']='Love Love vinyl';data.append(e.assess(unknown,edition()))
    summary=e.price_summary(data)
    assert summary['count']==3 and summary['low']==50 and summary['high']==80 and summary['median']==60
    assert summary['confidence']=='Bassa'


def test_external_urls_are_never_forwarded():
    data=item();data['itemWebUrl']='https://evil.example/steal'
    assert e.assess(data,edition()) is None
    assert e.safe_url('https://www.ebay.it.evil.example/item') is None
    assert e.safe_url('https://i.ebayimg.com.evil.example/img',image=True) is None


def test_oauth_uses_production_and_reuses_token_without_exposure(monkeypatch):
    monkeypatch.setenv('EBAY_CLIENT_ID','example-client');monkeypatch.setenv('EBAY_CLIENT_SECRET','example-secret')
    seen=[]
    def handler(request):
        seen.append(request)
        assert request.url.host=='api.ebay.com' and request.url.path=='/identity/v1/oauth2/token'
        assert request.headers['authorization']=='Basic '+base64.b64encode(b'example-client:example-secret').decode()
        assert b'grant_type=client_credentials' in request.content
        return httpx.Response(200,json={'access_token':'private-token','expires_in':7200})
    real=httpx.AsyncClient
    monkeypatch.setattr(e.httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(handler)))
    async def run():
        assert await e.access_token()=='private-token'
        assert await e.access_token()=='private-token'
    asyncio.run(run());assert len(seen)==1


def test_rejected_credentials_are_sanitized(monkeypatch):
    monkeypatch.setenv('EBAY_CLIENT_ID','example-client');monkeypatch.setenv('EBAY_CLIENT_SECRET','example-secret')
    real=httpx.AsyncClient
    monkeypatch.setattr(e.httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'error_description':'example-secret'}))))
    result=asyncio.run(e.search_offers(edition()))
    assert result['status']=='credentials_rejected'
    assert 'example-secret' not in json.dumps(result) and not result['items']


def test_browse_denied_does_not_produce_fake_listings(monkeypatch):
    monkeypatch.setenv('EBAY_CLIENT_ID','example-client');monkeypatch.setenv('EBAY_CLIENT_SECRET','example-secret')
    async def denied(*args,**kwargs):raise e.EbayError('access_denied','Accesso negato.')
    monkeypatch.setattr(e,'browse',denied)
    result=asyncio.run(e.search_offers(edition()))
    assert result['status']=='access_denied' and not result['items'] and not result['price']['available']


def test_search_deduplicates_listing_variants_and_caches(monkeypatch):
    monkeypatch.setenv('EBAY_CLIENT_ID','example-client');monkeypatch.setenv('EBAY_CLIENT_SECRET','example-secret')
    calls=[]
    async def fake(path,params=None):
        calls.append(path)
        if path=='/item_summary/search':
            items=[item(str(n),str(n*10)) for n in [1,2,3]]
            duplicate=item('1');duplicate['itemId']='v1|1|7';items.append(duplicate)
            return {'itemSummaries':items}
        ident=path.split('%7C')[1]
        return item(ident,str(int(ident)*10))
    monkeypatch.setattr(e,'browse',fake)
    async def run():
        result=await e.search_offers(edition());count=len(calls)
        assert len(result['items'])==3 and result['price']['available']
        assert await e.search_offers(edition())==result
        assert len(calls)==count
    asyncio.run(run())


def test_route_unconfigured_preserves_guide_and_hides_credentials():
    c=TestClient(m.app)
    assert c.get('/api/health').json()['ebay_configured'] is False
    data=c.get('/api/offers/1360042').json()
    assert data['status']=='not_configured'
    assert c.get('/api/offers/-1').status_code==422
    assert 'EBAY_CLIENT_SECRET' not in c.get('/static/app.js').text
