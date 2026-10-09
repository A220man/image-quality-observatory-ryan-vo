"""Optional, bounded provider advice from aggregate metrics; never sends images or names."""
from collections import Counter
import json
from urllib.parse import quote, urlsplit
import httpx
from app.core.config import Settings

SYSTEM = ('You advise an image-quality reviewer. Use only supplied aggregate measurements. '
          'Explain likely acquisition problems and concrete checks, without asserting causes as facts. '
          'Never claim to see images. Never change thresholds or labels. Keep the answer under 300 words.')
BASES = {'openai': 'https://api.openai.com/v1', 'anthropic': 'https://api.anthropic.com/v1',
         'gemini': 'https://generativelanguage.googleapis.com/v1beta', 'ollama': 'http://127.0.0.1:11434'}


def summarize(rows: list[dict]) -> dict:
    return {'image_count': len(rows), 'decisions': dict(Counter(r['decision'] for r in rows)),
            'failures': dict(Counter(f for r in rows for f in r['failures'])),
            'mean_quality': round(sum(r['quality_score'] for r in rows)/len(rows), 2) if rows else None}


def explain(settings: Settings, rows: list[dict], transport=None) -> dict:
    evidence = summarize(rows)
    result = {'evidence': evidence, 'advisory_only': True, 'source': 'local', 'warning': None,
              'text': f"Reviewed {len(rows)} image measurements. " +
                      ('Most frequent failed checks: '+', '.join(f'{k} ({v})' for k,v in sorted(evidence['failures'].items(), key=lambda x:-x[1]))+'. '
                       if evidence['failures'] else 'No failed checks recorded. ') +
                      'Inspect representative images and acquisition conditions before changing the policy.'}
    if not settings.llm_model or not rows:
        return result
    provider = settings.llm_provider
    if provider not in {*BASES, 'openai-compatible'}:
        result['warning'] = 'Unsupported advisory provider; showing local summary.';return result
    if provider != 'ollama' and not settings.llm_api_key:
        result['warning'] = 'Advisory credential is not configured; showing local summary.';return result
    base = (settings.llm_base_url or BASES.get(provider, '')).rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        result['warning'] = 'Invalid advisory endpoint; showing local summary.';return result
    if parsed.scheme == 'http' and provider != 'ollama' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        result['warning'] = 'Remote advisory endpoints require HTTPS; showing local summary.';return result
    prompt = json.dumps(evidence, sort_keys=True)
    headers = {}
    messages = [{'role':'system', 'content':SYSTEM}, {'role':'user', 'content':prompt}]
    if provider == 'anthropic':
        endpoint = base+'/messages'
        headers = {'x-api-key': settings.llm_api_key, 'anthropic-version':'2023-06-01'}
        payload = {'model':settings.llm_model, 'max_tokens':700, 'system':SYSTEM, 'messages':messages[1:]}
    elif provider == 'gemini':
        endpoint = base+'/models/'+quote(settings.llm_model.removeprefix('models/'), safe='')+':generateContent'
        headers = {'x-goog-api-key':settings.llm_api_key}
        payload = {'systemInstruction':{'parts':[{'text':SYSTEM}]}, 'contents':[{'role':'user','parts':[{'text':prompt}]}],
                   'generationConfig':{'maxOutputTokens':700}}
    elif provider == 'ollama':
        endpoint = base+'/api/chat'
        payload = {'model':settings.llm_model, 'messages':messages, 'stream':False, 'options':{'num_predict':700}}
        if settings.llm_api_key:headers['Authorization'] = 'Bearer '+settings.llm_api_key
    else:
        endpoint = base+'/chat/completions'
        headers = {'Authorization':'Bearer '+settings.llm_api_key}
        payload = {'model':settings.llm_model, 'messages':messages, 'max_tokens':700, 'stream':False}
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds, transport=transport, follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 128*1024:raise ValueError('Response exceeds limit')
                data = json.loads(chunks)
        if provider == 'anthropic':text = '\n'.join(p['text'] for p in data['content'] if p.get('type')=='text')
        elif provider == 'gemini':text = '\n'.join(p['text'] for p in data['candidates'][0]['content']['parts'] if 'text' in p)
        elif provider == 'ollama':text = data['message']['content']
        else:text = data['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():raise ValueError('Empty response')
        result.update(source='model', text=text[:12000])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        # Provider bodies can include credentials or internal URLs; never return them to callers.
        result['warning'] = 'Advisory provider unavailable or returned an invalid response; showing local summary.'
    return result
