"""Five-minute signed entity references, no facts or model conversation memory."""
import base64
import hashlib
import hmac
import json
import os
import time
from app.analysis.generation_nodes import strict_json


class Context:
    def __init__(self, key=None, clock=time.time):
        self.key = key or os.urandom(32)
        self.clock = clock

    def issue(self, entities):
        if not entities:
            return None
        payload = json.dumps({'entities': entities, 'expires': int(self.clock()) + 300}, sort_keys=True, separators=(',', ':')).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
        mac = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
        return encoded + '.' + mac

    def verify(self, token):
        if not token or len(token) > 2000:
            return {}
        try:
            encoded, mac = token.split('.')
            expected = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, expected):
                return {}
            value = strict_json(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode())
            if set(value) != {'entities', 'expires'} or type(value['expires']) is not int or not self.clock() < value['expires'] <= self.clock() + 300:
                return {}
            entities = value['entities']
            if not isinstance(entities, dict) or set(entities) - {'heat', 'order', 'batch'}:
                return {}
            if any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in entities.values()):
                return {}
            return entities
        except (ValueError, TypeError, KeyError):
            return {}
