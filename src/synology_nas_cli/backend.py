import hashlib
import json
import os
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .protocol import Failure

MAX_JSON = 8 * 1024 * 1024

def encode(params):
    return urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False, separators=(',', ':')) if isinstance(v, (dict, list, bool)) else str(v) for k, v in params.items()}).encode()

def decode_response(result):
    if not isinstance(result, dict) or not isinstance(result.get('success'), bool):
        raise Failure('INVALID_RESPONSE', 'Expected a DSM success/error response')
    if not result['success']:
        error = result.get('error', {})
        codes = [error.get('code')] + [e.get('code') for e in error.get('errors', []) if isinstance(e, dict)]
        code = next((c for c in codes if c in {105, 106, 107, 119, 400, 401, 402, 403, 404, 407, 408}), codes[0])
        if code in {105, 403}: category = 'PERMISSION_DENIED'
        elif code in {106, 107, 119, 400, 401, 402}: category = 'AUTH_FAILED' if code in {106, 107, 119} else 'BACKEND_ERROR'
        elif code == 407: category = 'CONFLICT'
        elif code == 408: category = 'NOT_FOUND'
        elif code in {102, 103, 104}: category = 'UNSUPPORTED'
        else: category = 'BACKEND_ERROR'
        raise Failure(category, 'DSM API rejected the request', details={'dsm_code': error.get('code'), 'errors': error.get('errors', [])})
    return result.get('data', {})

class Client:
    def __init__(self, url, *, user=None, password=None, otp=None, insecure=False, ca_file=None, timeout=30, deadline=120):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
            raise Failure('INVALID_INPUT', 'url must be an HTTP(S) origin without path, query or credentials')
        self.url = url.rstrip('/')
        self.user, self.password, self.otp = user, password, otp
        self.timeout = timeout
        self.until = time.monotonic() + deadline
        self.sid = None
        self.mutation_dispatched = False
        self.info = {}
        self.insecure = insecure
        context = ssl.create_default_context(cafile=ca_file)
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def remaining(self):
        remaining = self.until - time.monotonic()
        if remaining <= 0:
            raise Failure('DEADLINE', 'Command deadline reached; no automatic retry')
        return min(self.timeout, remaining)

    def open(self, req, *, mutation=False):
        timeout = self.remaining()
        if mutation:
            self.mutation_dispatched = True
        try:
            return self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            kind = 'AUTH_FAILED' if exc.code in {401, 403} else 'NOT_FOUND' if exc.code == 404 else 'NETWORK_ERROR' if exc.code in {429, 500, 502, 503, 504} else 'BACKEND_ERROR'
            raise Failure(kind, 'NAS HTTP request failed', details={'http_status': exc.code}, outcome='unknown' if mutation else 'not_started') from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, 'reason', exc)
            kind = 'TLS_ERROR' if isinstance(reason, ssl.SSLError) else 'NETWORK_ERROR'
            raise Failure(kind, 'Check LAN connection, NAS origin and CA trust', outcome='unknown' if mutation else 'not_started', next_actions=[{'command': 'synology-nas doctor'}]) from None

    def request(self, cgi, params, *, mutation=False):
        if not isinstance(cgi, str) or cgi.startswith('/') or any(c in cgi for c in ('..', ':', '?', '#', '\\')):
            raise Failure('INVALID_RESPONSE', 'NAS advertised an unsafe CGI path')
        req = urllib.request.Request(self.url + '/webapi/' + cgi, data=encode(params), method='POST', headers={'Cookie':'id='+self.sid} if self.sid else {})
        try:
            with self.open(req, mutation=mutation) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise Failure('INVALID_RESPONSE', 'API response exceeded 8 MiB; narrow the query')
            return decode_response(json.loads(raw))
        except (json.JSONDecodeError, UnicodeError):
            raise Failure('INVALID_RESPONSE', 'NAS returned invalid JSON', outcome='unknown' if mutation else 'not_started') from None
        except (TimeoutError, socket.timeout, OSError):
            raise Failure('NETWORK_ERROR', 'Reading NAS response failed', outcome='unknown' if mutation else 'not_started') from None

    def discover(self):
        self.info = self.request('query.cgi', {'api': 'SYNO.API.Info', 'method': 'query', 'version': 1, 'query': 'all'})
        return self.info

    def fields(self, api, method, params, cap):
        spec = self.info.get(api)
        if not spec:
            raise Failure('UNSUPPORTED', 'API not advertised by this NAS; package may not be installed', details={'api': api})
        version = min(spec['maxVersion'], cap)
        if version < spec['minVersion']:
            raise Failure('UNSUPPORTED', 'No implemented compatible API version', details={'api': api})
        # JSON-format APIs require JSON string literals for scalar business inputs.
        # Routing, session and multipart fields remain ordinary form values.
        values = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, str) and spec.get('requestFormat') == 'JSON' and api not in {'SYNO.API.Auth', 'SYNO.FileStation.Upload'} else v for k, v in params.items()}
        fields = dict(values, api=api, method=method, version=version)
        if self.sid: fields['_sid'] = self.sid
        return spec['path'], fields

    def call(self, api, method, params=None, *, cap=2, mutation=False):
        path, fields = self.fields(api, method, params or {}, cap)
        return self.request(path, fields, mutation=mutation)

    def login(self):
        if not self.url.startswith('https://'):
            raise Failure('INVALID_INPUT', 'Credentials require HTTPS; HTTP is for anonymous discovery only')
        if not self.user or not self.password:
            raise Failure('AUTH_REQUIRED', 'Supply user and password-file/password-stdin or SYNOLOGY_PASSWORD', next_actions=[{'command': 'synology-nas auth status --user USER --password-file PATH'}])
        params = {'account': self.user, 'passwd': self.password, 'session': 'FileStation', 'format': 'sid'}
        if self.otp: params['otp_code'] = self.otp
        try:
            self.sid = self.call('SYNO.API.Auth', 'login', params, cap=6)['sid']
        except Failure as exc:
            if exc.code == 'BACKEND_ERROR' and exc.details.get('dsm_code') in {400, 401, 402, 403, 404, 406, 407, 408, 409, 410}:
                raise Failure('AUTH_FAILED', 'DSM login failed; verify account, password, OTP and account state', details={'dsm_code': exc.details['dsm_code']}) from None
            raise

    def logout(self):
        if not self.sid: return True
        try:
            # A cleanup call has a short independent deadline, even on cancellation.
            self.until = time.monotonic() + min(5, self.timeout)
            self.call('SYNO.API.Auth', 'logout', {'session': 'FileStation'}, cap=6)
            return True
        except Exception:
            return False
        finally:
            self.sid = None

    def stat(self, path):
        data = self.call('SYNO.FileStation.List', 'getinfo', {'path': [path], 'additional': ['size', 'time', 'perm', 'real_path']})
        files = data.get('files', [])
        if not files:
            raise Failure('NOT_FOUND', 'Path does not exist', details={'path': path})
        if 'code' in files[0]:
            decode_response({'success': False, 'error': files[0]})
        return files[0]

    def exists(self, path):
        try: return self.stat(path)
        except Failure as exc:
            if exc.code == 'NOT_FOUND': return None
            raise

    def upload(self, source, folder, name, *, overwrite=False):
        path, fields = self.fields('SYNO.FileStation.Upload', 'upload', {'path': folder, 'create_parents': False, 'overwrite': overwrite}, 2)
        # DSM's multipart parser needs routing fields before upload parameters.
        fields = {k: fields[k] for k in ['api', 'version', 'method', 'path', 'create_parents', 'overwrite', '_sid']}
        boundary = 'nascli' + uuid.uuid4().hex
        preamble = b''.join((f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n' + (json.dumps(v) if isinstance(v, bool) else str(v)) + '\r\n').encode('utf-8') for k, v in fields.items())
        preamble += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode('utf-8')
        ending = f'\r\n--{boundary}--\r\n'.encode()
        size = source.stat().st_size
        def stream():
            yield preamble
            with source.open('rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    self.remaining()
                    yield chunk
            yield ending
        req = urllib.request.Request(self.url + '/webapi/' + path, data=stream(), headers={'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Content-Length': str(len(preamble) + size + len(ending)), 'Cookie': 'id=' + self.sid})
        try:
            with self.open(req, mutation=True) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON: raise ValueError()
            return decode_response(json.loads(raw))
        except (ValueError, UnicodeError, OSError):
            raise Failure('NETWORK_ERROR', 'Upload response unavailable; reconcile destination before retrying', outcome='unknown', next_actions=[{'command': 'synology-nas stat ' + folder + '/' + name}]) from None

    def download(self, api, method, params, destination, *, cap=2, max_bytes=1073741824, overwrite=False):
        destination = Path(destination).absolute()
        if destination.exists() and not overwrite:
            raise Failure('CONFLICT', 'Local destination exists; use --overwrite-local', details={'file': str(destination)})
        if not destination.parent.is_dir():
            raise Failure('INVALID_INPUT', 'Local destination parent must exist')
        path, fields = self.fields(api, method, params, cap)
        req = urllib.request.Request(self.url + '/webapi/' + path, data=encode(fields))
        temporary = None
        try:
            with self.open(req) as response:
                # Error JSON lacks attachment headers. A real .json file is an attachment.
                if 'json' in response.headers.get('Content-Type', '') and not response.headers.get('Content-Disposition'):
                    decode_response(json.loads(response.read(MAX_JSON)))
                    raise Failure('INVALID_RESPONSE', 'Expected binary download')
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.nascli-', delete=False) as target:
                    temporary = Path(target.name)
                    count, digest = 0, hashlib.sha256()
                    while True:
                        self.remaining()
                        chunk = response.read(min(1024 * 1024, max_bytes - count + 1))
                        if not chunk: break
                        count += len(chunk)
                        if count > max_bytes:
                            raise Failure('INVALID_INPUT', 'Download exceeds max-bytes; no local file committed')
                        target.write(chunk)
                        digest.update(chunk)
            if overwrite:
                os.replace(temporary, destination)
            else:
                # Hard link gives atomic no-clobber creation on NTFS/POSIX filesystems.
                os.link(temporary, destination)
                temporary.unlink()
            temporary = None
            return {'file': str(destination), 'bytes': count, 'sha256': digest.hexdigest()}
        except FileExistsError:
            raise Failure('CONFLICT', 'Local destination appeared during download') from None
        finally:
            if temporary and temporary.exists(): temporary.unlink()
