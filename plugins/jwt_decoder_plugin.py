"""
Plugin: JWT Token Analyzer & Decoder
Erkennt JWT-Tokens (Header.Payload.Signature) in der Zwischenablage,
dekodiert die Header- und Payload-Claims und vergibt 'jwt' und 'auth'-Tags.
"""
import re
import json
import base64

def register_rules():
    return [
        (r'\beyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]+\b', 'jwt'),
    ]

def _b64decode(s):
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s).decode('utf-8', errors='replace')

def on_capture(item):
    text = (item.get('content') or '') if isinstance(item, dict) else ''
    match = re.search(r'\b(eyJ[A-Za-z0-9-_=]+)\.(eyJ[A-Za-z0-9-_=]+)\.([A-Za-z0-9-_.+/=]+)\b', text)
    if match:
        try:
            h_json = json.loads(_b64decode(match.group(1)))
            p_json = json.loads(_b64decode(match.group(2)))
            print(f"[Plugin JWT] JWT erkannt! Alg: {h_json.get('alg', '?')}, Sub: {p_json.get('sub', '?')}")
        except Exception:
            pass
