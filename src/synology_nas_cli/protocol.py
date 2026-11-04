import json
import sys
import time
import uuid

ERRORS = {
    'INVALID_INPUT': (2, False), 'AUTH_REQUIRED': (3, False),
    'AUTH_FAILED': (3, False), 'PERMISSION_DENIED': (3, False),
    'NOT_FOUND': (3, False), 'UNSUPPORTED': (3, False),
    'TLS_ERROR': (3, False), 'NETWORK_ERROR': (4, True),
    'DEADLINE': (4, True), 'CONFLICT': (5, False),
    'BACKEND_ERROR': (1, False), 'INVALID_RESPONSE': (1, False),
    'INTERNAL_ERROR': (1, False), 'INTERRUPTED': (130, False),
}

class Failure(Exception):
    def __init__(self, code, message, *, details=None, outcome='not_started', next_actions=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.outcome = details or {}, outcome
        self.next_actions = next_actions or []

def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if k.lower() in {'password', 'passwd', 'sid', '_sid', 'synotoken', 'cookie', 'authorization', 'otp_code', 'token', 'secret'} else sanitize(v, secrets) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return value
    return value

def emit(data=None, error=None, *, started=None, output='json', meta=None, secrets=()):
    envelope = {'schema_version': '1.0', 'ok': error is None,
                'type': 'error' if error else 'result',
                'meta': {'request_id': 'req_' + uuid.uuid4().hex,
                         'duration_ms': round((time.monotonic() - started) * 1000) if started else 0,
                         **(meta or {})}}
    if error:
        exit_code, retryable = ERRORS[error.code]
        envelope['error'] = {'code': error.code, 'message': error.message,
                             'retryable': retryable and error.outcome != 'unknown',
                             'outcome': error.outcome, 'details': error.details,
                             'next_actions': error.next_actions}
    else:
        exit_code = 0
        envelope['data'] = data
    # ASCII escaping also neutralizes control, bidi and zero-width terminal text.
    sys.stdout.write(json.dumps(sanitize(envelope, secrets), ensure_ascii=True,
                                indent=2 if output == 'text' else None) + '\n')
    return exit_code
