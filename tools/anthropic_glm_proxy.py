import argparse, json, os, sys, time, uuid, secrets, threading
import queue
import ssl
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configs.llm_config import ModelSpec, load_model_spec

SPEC: ModelSpec | None = None
UPSTREAM = ""
OPENAI_PROTOCOLS = {"openai_chat_completions", "openai_responses"}
RETRY_DELAYS = (2, 4, 8, 16, 32)
HEARTBEAT_SECONDS = 5
TERMINAL_FAILURES = {}
TERMINAL_FAILURE_TTL = 60
RETRY_HTTP_STATUSES = {403, 429, 500, 502, 503, 504}
KEY_POOL = ()
ACTIVE_KEY = 0
KEY_LOCK = threading.Lock()
CODEX_CLIENT_HEADERS = {
    "originator": "codex_cli_rs",
    "User-Agent": "codex_cli_rs/0.144.4",
    "OpenAI-Beta": "responses=experimental",
    "x-codex-turn-state": "0",
    "x-reasoning-included": "true",
}


def upstream_headers(spec):
    headers = {
        'content-type': 'application/json',
        'Authorization': 'Bearer ' + spec.api_key,
    }
    if str(spec.model).strip().lower().startswith('gpt-'):
        headers.update(CODEX_CLIENT_HEADERS)
    return headers


def configure_key_pool(spec):
    global KEY_POOL, ACTIVE_KEY
    KEY_POOL = tuple(dict.fromkeys(spec.api_keys or (spec.api_key,)))
    ACTIVE_KEY = secrets.randbelow(len(KEY_POOL))
    _retry_log(event='key_selected', key_slot=ACTIVE_KEY + 1, key_count=len(KEY_POOL))


class EmptyUpstreamResponse(ValueError):
    pass


class RetryExhausted(ValueError):
    pass


def _retry_log(**fields):
    try:
        log = ROOT / 'logs' / 'anthropic_glm_proxy.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as handle:
            handle.write(json.dumps({'ts': int(time.time()),
                                     'model': getattr(SPEC, 'name', None),
                                     **fields}) + '\n')
    except OSError:
        pass


def request_with_retries(req, decode, original):
    request_id = uuid.uuid4().hex
    global ACTIVE_KEY
    with KEY_LOCK:
        fingerprint = req.full_url.encode() + b'\0' + (req.data or b'')
        now = time.monotonic()
        for key, (expires, _) in list(TERMINAL_FAILURES.items()):
            if expires <= now:
                del TERMINAL_FAILURES[key]
        if not original.get('stream'):
            previous = TERMINAL_FAILURES.pop(fingerprint, None)
            if previous is not None:
                _retry_log(event='fallback_reuses_exhausted_budget', request_id=request_id)
                raise RetryExhausted(previous[1])
        start = ACTIVE_KEY
        count = len(KEY_POOL) or 1
        for offset in range(count):
            slot = (start + offset) % count
            if KEY_POOL:
                req.add_header('Authorization', 'Bearer ' + KEY_POOL[slot])
                ACTIVE_KEY = slot
            try:
                return _retry_one_key(req, decode, original, request_id, slot)
            except RetryExhausted as error:
                if offset + 1 == count:
                    message = (
                        f'upstream retry budget exhausted for {count} key(s); '
                        f'{error}'
                    )
                    if original.get('stream'):
                        if len(TERMINAL_FAILURES) >= 32:
                            TERMINAL_FAILURES.pop(next(iter(TERMINAL_FAILURES)))
                        TERMINAL_FAILURES[fingerprint] = (time.monotonic() + TERMINAL_FAILURE_TTL, message)
                    raise RetryExhausted(message) from None
                _retry_log(event='key_switch', request_id=request_id,
                           from_key_slot=slot + 1,
                           to_key_slot=(start + offset + 1) % count + 1)


def _retry_one_key(req, decode, original, request_id, slot):
    for attempt in range(len(RETRY_DELAYS) + 1):
        status = None
        usage = None
        try:
            with urlopen(req, timeout=7200) as response:
                raw = _unwrap_upstream(read_upstream_response(response))
            usage = raw.get('usage')
            return decode(raw, original)
        except HTTPError as error:
            status = error.code
            error.close()
            if status not in RETRY_HTTP_STATUSES:
                raise
            reason = 'upstream_http_error'
        except EmptyUpstreamResponse:
            reason = 'empty_upstream_response'
        except (URLError, TimeoutError, ConnectionError, HTTPException, ssl.SSLError) as error:
            reason = 'upstream_transport_error:' + type(error).__name__
        delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else None
        _retry_log(event='upstream_retry' if delay is not None else 'retry_exhausted',
                   request_id=request_id, key_slot=slot + 1, attempt=attempt + 1,
                   upstream_status=status, reason=reason, delay_seconds=delay,
                   discarded_usage=usage)
        if delay is None:
            raise RetryExhausted(
                f'upstream retry budget exhausted after 5 retries; '
                f'last_status={status}; reason={reason}; request_id={request_id}'
            )
        time.sleep(delay)


def read_upstream_response(response):
    content_type = response.headers.get('Content-Type', '')
    if 'text/event-stream' not in content_type.lower():
        return json.load(response)

    output = []
    terminal = None
    for line in response:
        if not line.startswith(b'data: '):
            continue
        data = line[6:].strip()
        if data == b'[DONE]':
            continue
        event = json.loads(data)
        kind = event.get('type')
        if kind == 'response.output_item.done':
            output.append(event['item'])
        elif kind in {'response.completed', 'response.failed', 'response.incomplete'}:
            terminal = event.get('response') or {}
            if kind != 'response.completed':
                error = terminal.get('error') or {}
                raise EmptyUpstreamResponse(
                    error.get('message') or f'upstream {kind}'
                )
    if terminal is None:
        raise EmptyUpstreamResponse('upstream SSE missing response.completed')
    if not terminal.get('output'):
        terminal['output'] = output
    return terminal


def _maybe_json(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _looks_like_completion(data):
    return isinstance(data, dict) and (
        data.get("choices") is not None or data.get("output") is not None
    )


def _unwrap_upstream(data):
    if not isinstance(data, dict):
        raise ValueError(f"upstream body is {type(data).__name__}")
    code = data.get("code")
    if code not in (None, 0, "0", 200, "200", "success", "ok", "OK"):
        msg = data.get("msg") or data.get("message") or data.get("error")
        raise ValueError(f"upstream code={code}: {msg}")
    for key in ("detail", "response", "data", "result"):
        inner = _maybe_json(data.get(key))
        if _looks_like_completion(inner):
            return inner
    if _looks_like_completion(data):
        return data
    raise ValueError("upstream missing completion; keys=" + ",".join(sorted(data)[:20]))


def _upstream_url(spec):
    base = (spec.api_base or "").rstrip("/")
    if spec.api_protocol == "openai_responses":
        if base.endswith("/responses"):
            return base
        return base + "/responses"
    if base.endswith("/chat_completions") or base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _nonneg_int(value, default=0):
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def openai_usage_to_anthropic(usage):
    payload = usage if isinstance(usage, dict) else {}
    if payload.get("prompt_tokens") is not None:
        prompt = _nonneg_int(payload.get("prompt_tokens"))
    else:
        prompt = _nonneg_int(payload.get("input_tokens"))
    completion = _nonneg_int(
        payload.get("completion_tokens") if payload.get("completion_tokens") is not None
        else payload.get("output_tokens")
    )
    details = payload.get("prompt_tokens_details") or payload.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}

    cache_read = 0
    for candidate in (
        payload.get("prompt_cache_hit_tokens"),
        details.get("cached_tokens"),
        payload.get("cached_tokens"),
        payload.get("cache_read_input_tokens"),
    ):
        if candidate is not None:
            cache_read = _nonneg_int(candidate)
            break

    cache_creation = 0
    for candidate in (
        payload.get("cache_creation_input_tokens"),
        details.get("cache_write_tokens"),
        payload.get("prompt_cache_write_tokens"),
    ):
        if candidate is not None:
            cache_creation = _nonneg_int(candidate)
            break

    if cache_read > prompt:
        cache_read = prompt
    if cache_read + cache_creation > prompt:
        cache_creation = max(0, prompt - cache_read)
    input_tokens = max(0, prompt - cache_read - cache_creation)
    return {
        "input_tokens": input_tokens,
        "output_tokens": completion,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
    }


def _flatten_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def to_chat(p):
    msgs=[]
    if p.get('system'):
        s=p['system']; s='\n'.join(x.get('text','') if isinstance(x,dict) else str(x) for x in s) if isinstance(s,list) else str(s)
        msgs.append({'role':'system','content':s})
    for m in p.get('messages',[]):
        role=m.get('role','user'); c=m.get('content','')
        if isinstance(c,str): msgs.append({'role':role,'content':c}); continue
        text=[]; tool_calls=[]
        for b in c or []:
            typ=b.get('type')
            if typ=='text': text.append(b.get('text',''))
            elif typ=='tool_result': msgs.append({'role':'tool','tool_call_id':b.get('tool_use_id',''),'content':b.get('content','')})
            elif typ=='tool_use': tool_calls.append({'id':b.get('id'),'type':'function','function':{'name':b.get('name'),'arguments':json.dumps(b.get('input',{}),ensure_ascii=False)}})
        if text or tool_calls: msgs.append({'role':role,'content':'\n'.join(text),**({'tool_calls':tool_calls} if tool_calls else {})})
    spec = SPEC
    if spec.instructions:
        if msgs and msgs[0].get('role') == 'system':
            msgs[0]['content'] = spec.instructions + '\n\n' + (msgs[0].get('content') or '')
        else:
            msgs.insert(0, {'role': 'system', 'content': spec.instructions})
    out={'model':spec.model,'messages':msgs}
    if spec.max_tokens is not None:
        out['max_tokens']=spec.max_tokens
    if spec.temperature is not None:
        out['temperature']=spec.temperature
    if spec.top_p is not None:
        out['top_p']=spec.top_p
    if spec.reasoning_effort:
        out['reasoning_effort']=spec.reasoning_effort
    if spec.thinking:
        out['thinking']=dict(spec.thinking)
    if p.get('tools'):
        out['tools']=[{'type':'function','function':{'name':t.get('name'),'description':t.get('description',''),'parameters':t.get('input_schema',{})}} for t in p['tools']]
    return out


def to_responses(p):
    spec = SPEC
    items = []
    system = p.get("system")
    if system:
        items.append({"role": "system", "content": _flatten_text(system)})
    for message in p.get("messages") or []:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, str):
            if content:
                items.append({"role": role, "content": content})
            continue
        texts = []
        for block in content or []:
            typ = block.get("type")
            if typ == "text":
                texts.append(block.get("text") or "")
            elif typ == "tool_use":
                if texts:
                    items.append({"role": role, "content": "\n".join(texts)})
                    texts = []
                items.append({
                    "type": "function_call",
                    "call_id": block.get("id") or "",
                    "name": block.get("name") or "",
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                })
            elif typ == "tool_result":
                items.append({
                    "type": "function_call_output",
                    "call_id": block.get("tool_use_id") or "",
                    "output": _flatten_text(block.get("content")),
                })
        if texts:
            items.append({"role": role, "content": "\n".join(texts)})
    out = {"model": spec.model, "input": items, "store": False}
    if spec.instructions:
        out["instructions"] = spec.instructions
    if spec.max_tokens is not None:
        out["max_output_tokens"] = spec.max_tokens
    if spec.reasoning_effort:
        out["reasoning"] = {"effort": spec.reasoning_effort}
    if p.get("tools"):
        out["tools"] = [
            {
                "type": "function",
                "name": t.get("name"),
                "description": t.get("description") or "",
                "parameters": t.get("input_schema") or {},
            }
            for t in p["tools"]
        ]
    return out


def _reasoning_text(message):
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = message.get(key)
        if isinstance(value, dict):
            value = value.get("content") or value.get("text") or value.get("summary")
        text = _flatten_text(value)
        if text:
            return text
    return ""


def to_anthropic(r,p):
    choice=(r.get('choices') or [{}])[0]
    m=choice.get('message') or {}; blocks=[]
    text=_flatten_text(m.get('content'))
    if text: blocks.append({'type':'text','text':text})
    reason=_reasoning_text(m)
    if reason and reason != text: blocks.insert(0,{'type':'text','text':reason})
    for tc in m.get('tool_calls') or []:
        fn=tc.get('function') or {}; 
        try: args=json.loads(fn.get('arguments','{}'))
        except Exception: args={}
        blocks.append({'type':'tool_use','id':tc.get('id','toolu_local'),'name':fn.get('name'),'input':args})
    if not blocks:
        raise EmptyUpstreamResponse(
            "upstream empty assistant content finish="
            + str(choice.get('finish_reason'))
        )
    stop = ('max_tokens' if choice.get('finish_reason') == 'length'
            else 'tool_use' if m.get('tool_calls') else 'end_turn')
    return {'id':'msg_local_'+str(int(time.time()*1000)),'type':'message','role':'assistant','model':p.get('model') or SPEC.model,'content':blocks,'stop_reason':stop,'stop_sequence':None,'usage':openai_usage_to_anthropic(r.get('usage'))}


def to_anthropic_from_responses(r, p):
    blocks = []
    tool_used = False
    for item in r.get("output") or []:
        typ = item.get("type")
        if typ == "message":
            for content in item.get("content") or []:
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    blocks.append({"type": "text", "text": content["text"]})
        elif typ == "function_call":
            tool_used = True
            raw_args = item.get("arguments") or "{}"
            try:
                parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            blocks.append({
                "type": "tool_use",
                "id": item.get("call_id") or item.get("id") or "toolu_local",
                "name": item.get("name") or "",
                "input": parsed,
            })
    if not blocks:
        raise EmptyUpstreamResponse('upstream empty Responses output')
    return {
        "id": "msg_local_" + str(int(time.time() * 1000)),
        "type": "message",
        "role": "assistant",
        "model": r.get("model") or p.get("model") or SPEC.model,
        "content": blocks,
        "stop_reason": "tool_use" if tool_used else "end_turn",
        "stop_sequence": None,
        "usage": openai_usage_to_anthropic(r.get("usage")),
    }

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def send_event(self, event):
        self.wfile.write(('event: ' + event['type'] + '\ndata: '
                          + json.dumps(event, ensure_ascii=False) + '\n\n').encode())
        self.wfile.flush()

    def stream_message(self, req, decode, p):
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.send_header('cache-control', 'no-cache')
        self.send_header('connection', 'close')
        self.end_headers()
        self.close_connection = True
        message = {'id': 'msg_local_' + uuid.uuid4().hex, 'type': 'message',
                   'role': 'assistant', 'model': p.get('model') or SPEC.model,
                   'content': [], 'stop_reason': None, 'stop_sequence': None,
                   'usage': {'input_tokens': 0, 'output_tokens': 0}}
        self.send_event({'type': 'message_start', 'message': message})
        result = queue.Queue(maxsize=1)

        def infer():
            try:
                result.put((request_with_retries(req, decode, p), None))
            except Exception as error:
                result.put((None, error))

        threading.Thread(target=infer, daemon=True).start()
        while True:
            try:
                answer, error = result.get(timeout=HEARTBEAT_SECONDS)
                break
            except queue.Empty:
                self.send_event({'type': 'ping'})
        if error is not None:
            _retry_log(event='stream_error', error_type=type(error).__name__)
            error_type = ('invalid_request_error' if isinstance(error, RetryExhausted)
                          else 'authentication_error' if isinstance(error, HTTPError) and error.code == 401
                          else 'api_error')
            self.send_event({'type': 'error', 'error': {'type': error_type, 'message': str(error)}})
            return
        for index, block in enumerate(answer['content']):
            if block['type'] == 'tool_use':
                start = {**block, 'input': {}}
                delta = {'type': 'input_json_delta', 'partial_json': json.dumps(block['input'], ensure_ascii=False)}
            else:
                start = {'type': 'text', 'text': ''}
                delta = {'type': 'text_delta', 'text': block['text']}
            self.send_event({'type': 'content_block_start', 'index': index, 'content_block': start})
            self.send_event({'type': 'content_block_delta', 'index': index, 'delta': delta})
            self.send_event({'type': 'content_block_stop', 'index': index})
        self.send_event({'type': 'message_delta', 'delta': {
            'stop_reason': answer['stop_reason'], 'stop_sequence': answer.get('stop_sequence')},
            'usage': answer['usage']})
        self.send_event({'type': 'message_stop'})

    def do_GET(self):
        if self.path.split('?',1)[0].rstrip('/') not in ('/v1/models','/models'):
            self.send_error(404); return
        body=json.dumps({'data':[{'id':SPEC.model,'object':'model'}]}).encode()
        self.send_response(200); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path.split('?',1)[0].rstrip('/') not in ('/v1/messages','/messages'): self.send_error(404); return
        try:
            n=int(self.headers.get('content-length','0')); p=json.loads(self.rfile.read(n))
            headers=upstream_headers(SPEC)
            if SPEC.api_protocol == 'openai_responses':
                payload, decode = to_responses(p), to_anthropic_from_responses
            else:
                payload, decode = to_chat(p), to_anthropic
            req=Request(UPSTREAM,data=json.dumps(payload).encode(),headers=headers)
            if p.get('stream'):
                try:
                    self.stream_message(req, decode, p)
                except (BrokenPipeError, ConnectionResetError):
                    _retry_log(event='downstream_disconnected')
                return
            a=request_with_retries(req,decode,p)
            body=json.dumps(a,ensure_ascii=False).encode(); self.send_response(200); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            try:
                log=ROOT/'logs'/'anthropic_glm_proxy.jsonl'
                log.parent.mkdir(parents=True, exist_ok=True)
                log.open('a').write(json.dumps({
                    'ts': int(time.time()), 'model': getattr(SPEC,'name',None),
                    'protocol': getattr(SPEC,'protocol',None) or getattr(SPEC,'api_protocol',None),
                    'error': str(e)[:300],
                }, ensure_ascii=False)+'\n')
            except Exception:
                pass
            status = 400 if isinstance(e, RetryExhausted) else e.code if isinstance(e, HTTPError) else 502
            error_type = 'invalid_request_error' if status == 400 else 'permission_error' if status == 403 else 'authentication_error' if status == 401 else 'api_error'
            body=json.dumps({'type':'error','error':{'type':error_type,'message':str(e)}}).encode(); self.send_response(status); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(body))); self.end_headers(); self.wfile.write(body)

def main():
    global SPEC, UPSTREAM
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=18086)
    ap.add_argument('--model', required=True,
                    help='logical model name in llm_config.yaml (openai_chat_completions or openai_responses)')
    args = ap.parse_args()
    SPEC = load_model_spec(args.model)
    if SPEC.api_protocol not in OPENAI_PROTOCOLS:
        raise SystemExit(
            f"model {args.model!r} uses protocol {SPEC.api_protocol!r}; this bridge "
            "only serves openai_chat_completions or openai_responses models")
    UPSTREAM = _upstream_url(SPEC)
    configure_key_pool(SPEC)
    ThreadingHTTPServer(('127.0.0.1', args.port),H).serve_forever()

if __name__=='__main__':
    main()
