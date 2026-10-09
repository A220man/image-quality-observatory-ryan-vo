import json
import httpx
import pytest
from app.core.config import Settings
from app.services.advisory import explain

ROWS = [{'decision':'reject', 'failures':['blurry'], 'quality_score':40,
         'filename':'private-patient.png', 'created_by':'private-subject', 'batch':'private-batch'}]


def test_offline_summary_does_not_need_network():
    result = explain(Settings(), ROWS)
    assert result['source']=='local' and result['warning'] is None
    assert result['evidence']['failures']=={'blurry':1}
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('provider,path,response', [
    ('openai','/v1/chat/completions',{'choices':[{'message':{'content':'Inspect focus.'}}]}),
    ('openai-compatible','/v1/chat/completions',{'choices':[{'message':{'content':'Inspect focus.'}}]}),
    ('anthropic','/v1/messages',{'content':[{'type':'text','text':'Inspect focus.'}]}),
    ('gemini','/v1/models/test-model:generateContent',{'candidates':[{'content':{'parts':[{'text':'Inspect focus.'}]}}]}),
    ('ollama','/v1/api/chat',{'message':{'content':'Inspect focus.'}}),
])
def test_provider_protocols_send_aggregate_only(provider,path,response):
    def respond(request):
        assert request.url.path==path
        body=json.loads(request.content)
        assert 'private' not in request.content.decode()
        assert 'blurry' in request.content.decode()
        if provider=='anthropic':
            assert request.headers['anthropic-version']=='2023-06-01'
            assert request.headers['x-api-key']=='test-only'
            assert body['max_tokens']==700
        elif provider=='gemini':
            assert request.headers['x-goog-api-key']=='test-only'
            assert not request.url.query
            assert body['generationConfig']['maxOutputTokens']==700
        else:
            assert request.headers['authorization']=='Bearer test-only'
            assert body['stream'] is False
        return httpx.Response(200,json=response)
    settings=Settings(llm_provider=provider,llm_model='test-model',llm_api_key='test-only',llm_base_url='https://provider.example/v1')
    result=explain(settings,ROWS,httpx.MockTransport(respond))
    assert result['source']=='model' and result['text']=='Inspect focus.'
    assert result['advisory_only'] and result['warning'] is None


@pytest.mark.parametrize('status,body',[(429,{'error':'confidential-value'}),(200,{}),(200,{'choices':[]}),
    (200,{'choices':[{'message':{'content':None}}]}),(302,{}), (200,{'padding':'x'*140000})])
def test_provider_failure_has_local_summary_without_error_body(status,body):
    settings=Settings(llm_model='test-model',llm_api_key='test-only',llm_base_url='https://provider.example/v1')
    result=explain(settings,ROWS,httpx.MockTransport(lambda _:httpx.Response(status,json=body)))
    assert result['source']=='local' and result['warning']
    assert 'confidential-value' not in json.dumps(result)


def test_timeout_falls_back():
    def timeout(request):raise httpx.ReadTimeout('private diagnostic',request=request)
    result=explain(Settings(llm_provider='ollama',llm_model='local'),ROWS,httpx.MockTransport(timeout))
    assert result['source']=='local' and result['warning']
    assert 'private diagnostic' not in json.dumps(result)


def test_missing_credentials_does_not_call_provider():
    def unexpected(request):raise AssertionError('Network call with no credential')
    result=explain(Settings(llm_provider='openai',llm_model='test'),ROWS,httpx.MockTransport(unexpected))
    assert result['source']=='local' and result['warning']
