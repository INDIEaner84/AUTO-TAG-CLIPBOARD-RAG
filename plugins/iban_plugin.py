"""
Beispiel-Plugin für CoolClipboard / MUSCAL:
Erkennt IBAN-Bankkontonummern in der Zwischenablage und taggt sie mit 'iban' und 'finance'.
"""
import re

def register_rules():
    """Gibt zusätzliche Regex-Regeln für den AutoTagger zurück."""
    return [
        (r'\b[A-Z]{2}\d{2}[ \-]?(?:\d{4}[ \-]?){3,6}\d{1,4}\b', 'iban'),
        (r'\b(IBAN|BIC|SWIFT|Kontonr|Kontonummer|Bankleitzahl|BLZ)\b', 'finance'),
    ]

def on_capture(item):
    """Wird nach erfolgreicher Erfassung eines Clips aufgerufen."""
    text = item.get('content', '') if isinstance(item, dict) else ''
    if text and re.search(r'\b[A-Z]{2}\d{2}[ \-]?(?:\d{4}[ \-]?){3,6}\d{1,4}\b', text):
        pass
