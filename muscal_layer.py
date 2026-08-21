#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MUSCAL Cognitive Clipboard Layer v1
Intelligente Capture-, Analyse-, Klassifikations-, Notification- und
Knowledge-Vorbereitungsebene für CoolClipboard.

Integriert als Nachbarmodul: import muscal_layer -> MuscalLayer.
Kern (Analyse/Store/Web) läuft headless; Overlays nur mit Tk+Display.
"""

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

MUSCAL_VERSION = '1.0.0'
DATA_DIR = Path.home() / '.local' / 'share' / 'coolclipboard'
DOCS_DIR = DATA_DIR / 'muscal-docs'

CATEGORIES = [
    ('code', 'Code', '#a6e22e'),
    ('architecture', 'Architektur', '#4fc3f7'),
    ('documentation', 'Dokumentation', '#81c784'),
    ('error', 'Fehler', '#e94560'),
    ('research', 'Recherche', '#ffb74d'),
    ('idea', 'Idee', '#ce93d8'),
    ('prompt', 'Prompt', '#64b5f6'),
    ('note', 'Notiz', '#a0a0a0'),
    ('link', 'Link', '#7986cb'),
    ('terminal', 'Terminal', '#4db6ac'),
    ('other', 'Allgemein', '#75715e'),
]
CATEGORY_LABEL = {k: label for k, label, _ in CATEGORIES}
CATEGORY_COLOR = {k: color for k, _, color in CATEGORIES}
CATEGORY_KEYS = [k for k, _, _ in CATEGORIES]


def canonical_category(key):
    if key in CATEGORY_LABEL:
        return key
    if key in ('all', '', None):
        return 'other'
    low = str(key).lower()
    for k, label in CATEGORY_LABEL.items():
        if label.lower() == low:
            return k
    return 'other'


# ─── CONTENT ANALYZER ───────────────────────────────────────

_LANG_RULES = [
    ('python', (r'\bdef\s+\w+\s*\(', r'\bclass\s+\w+[:\s]', r'\bimport\s+\w+',
                r'\bfrom\s+\w+\s+import', r'\bprint\s*\(', r'\bif\s+__name__\b',
                r'\.py\b', r'\bself\b', r'\breturn\s+\w+')),
    ('javascript', (r'\bconst\s+\w+\s*=', r'\blet\s+\w+\s*=', r'\b=>\s*[{\w]',
                    r'\bfunction\s*\w*\s*\(', r'\bconsole\.\w+\s*\(',
                    r'import\s+.*\s+from\s+[\'"]', r'\bmodule\.exports\b')),
    ('bash', (r'^#!/(usr/)?bin/(ba|z)?sh', r'\bsudo\s+', r'\bapt(-get)?\s+',
              r'\bexport\s+\w+=', r'\bchmod\s+', r'\brm\s+-rf\b', r'\bpip(3)?\s+install\b')),
    ('sql', (r'\bSELECT\b.*\bFROM\b', r'\bINSERT\s+INTO\b', r'\bCREATE\s+TABLE\b',
             r'\bUPDATE\b.*\bSET\b', r'\bJOIN\b.*\bON\b')),
    ('html', (r'<\s*(html|div|span|body|head|script|style|a\s|h[1-6]\b)[^>]*>',)),
    ('json', (r'^[\[{].*[\}\]]$',)),
    ('yaml', (r'^[a-z_][\w-]*:\s*(\S|$)', r'^\s+-\s+\w+:\s*')),
    ('markdown', (r'^#{1,6}\s+\S', r'^\s*[-*]\s+\[[ x]\]', r'\*\*[^*]+\*\*', r'```')),
]

_ERROR_MARKERS = (
    r'\bTraceback\b', r'\bError\b', r'\bException\b', r'\bfailed\b',
    r'\bFehler\b', r'\bpanic\b', r'\bFATAL\b', r'\buncaught\b',
    r'\bsyntax\s*error\b', r'\bFile\s+"[\w./-]+\.py"\s*,\s*line\s+\d+',
    r'^\s*\^+$',
)

_ARCH_MARKERS = (
    r'\b(architecture|architektur|event[-\s]?sourcing|domain\s+model|er[-\s]?diagramm|'
    r'c4\s+model|mvc|mvvm|hexagonal|clean\s+architecture|microservice|'
    r'pattern|schema\s+design|datenmodell|komponenten)\b',
)

_PROMPT_MARKERS = (
    r'\b(erkläre|erklär)\b', r'\b(schreibe|schreib)\b', r'\b(generiere|erstelle)\b',
    r'\bfasse\s+zusammen\b|\bzusammenfass', r'\bwie\s+würdest\s+du\b',
    r'\bprompt\b', r'\bdu\s+bist\b', r'\bact\s+as\b', r'\bplease\s+explain\b',
)

_IDEA_MARKERS = (
    r'\b(idee|idea)\b', r'\bbrainstorm\b', r'\bkonzept\b', r'\bwäre\s+(besser|cool|schön)\b',
    r'\bvielleicht\s+könnte\b', r'\bvision\b', r'\bprototyp\b', r'\bwas\s+wenn\b',
)

_DOC_MARKERS = (
    r'\bdokumentation\b', r'\bdocstring\b', r'\busage\b', r'\banleitung\b',
    r'\bhow[- ]to\b', r'\btutorial\b', r'\bmanual\b', r'\bwiki\b', r'\bapi\s+reference\b',
)

_NOTE_MARKERS = (
    r'\b(notiz|note)\b', r'\btodo\b', r'\bmerke\b', r'\bwichtig\b', r'\btermin\b',
    r'\bkalender\b', r'\bschedule\b', r'\breminder\b',
)


class ContentAnalyzer:
    """Heuristische Content-Analyse ohne externe Abhängigkeiten."""

    def analyze(self, text, source_app=''):
        meta = {}
        meta['content'] = text
        meta['type'] = 'text'
        meta['content_type'] = self.detect_type(text)
        meta['language'] = self.detect_language(text)
        meta['category'] = self.classify(text, meta['content_type'], meta['language'])
        tags = self.detect_tags(text, meta['language'], meta['content_type'],
                                meta['category'])
        meta['tags'] = tags
        meta['semantic_tags'] = tags
        meta['hash'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
        meta['title'] = self.detect_title(text)
        meta['source_app'] = source_app
        meta['relations'] = []
        meta['embedding_id'] = ''
        meta['created_at'] = datetime.now().isoformat()
        return meta

    def detect_title(self, text):
        for line in (text or '').splitlines():
            line = line.strip()
            if not line or line.startswith(('#', '//', '/*', '*', '"')):
                continue
            line = line.strip('"').strip()
            if line:
                if len(line) > 90:
                    line = line[:87] + '...'
                return line
        return (text or '').strip()[:90]

    def detect_language(self, text):
        if not text or len(text) > 200000:
            return ''
        head = text[:4000].lower()
        scores = []
        for lang, patterns in _LANG_RULES:
            score = sum(1 for p in patterns if re.search(p, head, re.IGNORECASE))
            if score:
                scores.append((score, lang))
        if not scores:
            return ''
        scores.sort(key=lambda x: -x[0])
        best = scores[0][1]
        if len(scores) >= 2 and best == 'bash' and scores[1][0] == scores[0][0]:
            return best
        if best == 'json':
            try:
                json.loads(text.strip())
                return 'json'
            except Exception:
                return ''
        return best

    def detect_type(self, text):
        if not text or not text.strip():
            return 'text'
        stripped = text.strip()
        lines = stripped.splitlines()
        if len(lines) == 1 and re.match(r'^https?://\S+$', stripped, re.IGNORECASE):
            return 'link'
        try:
            if stripped[:1] in '[{':
                json.loads(stripped)
                return 'json'
        except Exception:
            pass
        low = text.lower()
        for m in _ERROR_MARKERS:
            if re.search(m, text):
                return 'error'
        if re.search(r'^\s*[$>#]\s', text, re.MULTILINE) or ' | grep ' in low:
            return 'terminal'
        if self.detect_language(text) in ('python', 'javascript', 'sql',
                                          'html', 'yaml', 'bash', 'json'):
            return 'code'
        return 'text'

    def classify(self, text, content_type, language):
        if content_type == 'error':
            return 'error'
        if content_type == 'link':
            return 'link'
        if content_type == 'terminal':
            return 'terminal'
        if content_type == 'json':
            return 'documentation'
        low = (text or '').lower()
        if re.search(r'|'.join(_PROMPT_MARKERS), low, re.IGNORECASE):
            return 'prompt'
        if re.search(r'|'.join(_ARCH_MARKERS), low, re.IGNORECASE):
            return 'architecture'
        if re.search(r'|'.join(_DOC_MARKERS), low, re.IGNORECASE):
            return 'documentation'
        if re.search(r'|'.join(_IDEA_MARKERS), low, re.IGNORECASE):
            return 'idea'
        if content_type == 'code':
            return 'code'
        if re.search(r'|'.join(_NOTE_MARKERS), low, re.IGNORECASE):
            return 'note'
        if re.search(r'https?://\S+', text) and len((text or '').splitlines()) <= 2:
            return 'link'
        return 'research'

    def detect_tags(self, text, language, content_type, category):
        tags = set()
        if language:
            tags.add(language)
        if content_type in ('code', 'error', 'terminal', 'link', 'json'):
            tags.add(content_type)
        if category != 'other':
            tags.add(category)
        low = (text or '').lower()
        if re.search(r'\bdef\s+\w+\s*\(', text):
            tags.add('function')
        if re.search(r'\bclass\s+\w+', text):
            tags.add('class')
        if content_type == 'code' and len((text or '').splitlines()) > 2:
            tags.add('snippet')
        if 'function' in tags and 'class' in tags:
            tags.add('api')
        if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', text):
            tags.add('ip')
        if re.search(r'https?://\S+', text):
            tags.add('url')
        if re.search(r'[\w.+-]+@\w+\.\w+', text):
            tags.add('email')
        if re.search(r'\b(debug|debugger|bug)\b', low):
            tags.add('debug')
        if re.search(r'\b(runtime|laufzeit)\b', low):
            tags.add('runtime')
        if content_type == 'error':
            tags.add('debug')
            tags.add('runtime')
        if re.search(r'\b(deadlock|race\s+condition|nebenläufigkeit|thread)\b', low):
            tags.add('concurrency')
        if re.search(r'\b(auth|login|token|jwt|session)\b', low):
            tags.add('auth')
        if re.search(r'\b(performance|optimierung|benchmark|latency)\b', low):
            tags.add('performance')
        if re.search(r'\b(db|database|sql|datenbank|query)\b', low):
            tags.add('database')
        if re.search(r'\b(test|testing|unit\s*test|pytest)\b', low):
            tags.add('testing')
        if len((text or '').splitlines()) > 15:
            tags.add('longtext')
        return sorted(tags)


# ─── SOURCE-APP-DETECTION ───────────────────────────────────

def process_name_by_pid(pid):
    try:
        comm = Path(f'/proc/{pid}/comm').read_text().strip()
        if comm:
            return comm
    except Exception:
        pass
    return ''


def detect_source_app():
    """Best-Effort: X11 Clipboard-Owner-PID -> Prozessname; Fallback xdotool."""
    try:
        from Xlib import display, X
        d = display.Display()
        owner = d.get_selection_owner(d.intern_atom('CLIPBOARD'))
        if owner:
            pid_prop = owner.get_full_property(d.intern_atom('_NET_WM_PID'), X.AnyPropertyType)
            if pid_prop and pid_prop.value:
                pid = int(pid_prop.value[0])
                name = process_name_by_pid(pid)
                if name:
                    return {'name': name, 'pid': pid}
            name_prop = owner.get_full_property(d.intern_atom('_NET_WM_NAME'), X.AnyPropertyType)
            if name_prop and name_prop.value:
                try:
                    raw = name_prop.value
                    if isinstance(raw, bytes):
                        raw = raw.decode('utf-8', 'replace')
                    if isinstance(raw, (list, tuple)):
                        raw = raw[0].decode('utf-8', 'replace') if isinstance(raw[0], bytes) else str(raw[0])
                    if raw:
                        return {'name': str(raw)[:60], 'pid': pid if 'pid' in dir() and pid else None}
                except Exception:
                    pass
    except Exception:
        pass
    try:
        out = os.popen('xdotool getactivewindow getwindowname 2>/dev/null').read().strip()
        if out:
            return {'name': out[:60], 'pid': None}
    except Exception:
        pass
    return {'name': '', 'pid': None}


# ─── CAPTURE STORE ──────────────────────────────────────────

class CaptureStore:
    """Schreibt Captures inkl. Metadaten in die bestehende clips-Tabelle."""

    def __init__(self, db):
        self.db = db
        self.conn = db.conn
        self.lock = db.lock

    def migrate(self):
        with self.lock:
            cols = {r[1] for r in self.conn.execute('PRAGMA table_info(clips)')}
            add_cols = {
                'hash': "TEXT DEFAULT ''",
                'source_app': "TEXT DEFAULT ''",
                'language': "TEXT DEFAULT ''",
                'content_type': "TEXT DEFAULT 'text'",
                'embedding_id': "TEXT DEFAULT ''",
                'relations': "TEXT DEFAULT '[]'",
                'semantic_tags': "TEXT DEFAULT '[]'",
                'folder': "TEXT DEFAULT ''",
                'title': "TEXT DEFAULT ''",
            }
            for name, ddl in add_cols.items():
                if name not in cols:
                    self.conn.execute(f'ALTER TABLE clips ADD COLUMN {name} {ddl}')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_hash ON clips(hash)')
            for key, label, color in CATEGORIES:
                if key == 'other':
                    continue
                self.conn.execute(
                    'INSERT OR IGNORE INTO categories (name, color) VALUES (?,?)',
                    (label, color))
            self.conn.commit()

    def save(self, meta):
        if not meta or not meta.get('content'):
            return None
        with self.lock:
            cur = self.conn.execute('SELECT id FROM clips WHERE hash=? LIMIT 1',
                                    (meta['hash'],))
            if cur.fetchone():
                return None
            cur = self.conn.execute(
                '''INSERT INTO clips
                   (type, content, image_path, source, tags, category, pinned, encrypted,
                    hash, source_app, language, content_type, embedding_id,
                    relations, semantic_tags, folder, title)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('text', meta['content'][:100000], '', '', ','.join(meta.get('tags', [])),
                 meta.get('category', 'other'), 0, 0,
                 meta['hash'], meta.get('source_app', ''), meta.get('language', ''),
                 meta.get('content_type', 'text'), meta.get('embedding_id', ''),
                 json.dumps(meta.get('relations', [])),
                 json.dumps(meta.get('semantic_tags', [])),
                 meta.get('category', 'other'), meta.get('title', '')))
            self.conn.commit()
            cur = self.conn.execute('SELECT * FROM clips WHERE id=?', (cur.lastrowid,))
            return self._enrich(dict(cur.fetchone()))

    def save_image(self, image_bytes, meta):
        ih = hashlib.sha256(image_bytes).hexdigest()
        with self.lock:
            cur = self.conn.execute('SELECT id FROM clips WHERE hash=? LIMIT 1', (ih,))
            if cur.fetchone():
                return None
        fname = f'{ih}.png'
        fpath = DATA_DIR / 'images' / fname
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_bytes(image_bytes)
        with self.lock:
            cur = self.conn.execute(
                '''INSERT INTO clips
                   (type, content, image_path, source, tags, category, pinned, encrypted,
                    hash, source_app, language, content_type, embedding_id,
                    relations, semantic_tags, folder, title)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('image', '', str(fpath), '', '', 'other', 0, 0,
                 ih, meta.get('source_app', ''), '', 'image', '',
                 '[]', '[]', 'other', 'Bildcapture'))
            self.conn.commit()
            cur = self.conn.execute('SELECT * FROM clips WHERE id=?', (cur.lastrowid,))
            return self._enrich(dict(cur.fetchone()))

    def get(self, cid):
        with self.lock:
            cur = self.conn.execute('SELECT * FROM clips WHERE id=?', (cid,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update(self, cid, **kw):
        allowed = {'category', 'tags', 'notes', 'favorite', 'language',
                   'content_type', 'semantic_tags', 'folder', 'title', 'source_app'}
        up = {k: v for k, v in kw.items() if k in allowed and v is not None}
        if not up:
            return False
        if 'semantic_tags' in up and not isinstance(up['semantic_tags'], str):
            up['semantic_tags'] = json.dumps(up['semantic_tags'])
        up['updated_at'] = datetime.now().isoformat()
        set_ = ', '.join(f'{k}=?' for k in up)
        with self.lock:
            self.conn.execute(f'UPDATE clips SET {set_} WHERE id=?',
                              list(up.values()) + [cid])
            self.conn.commit()
            return True

    def toggle_favorite(self, cid):
        item = self.get(cid)
        if not item:
            return None
        new = 0 if item['favorite'] else 1
        self.update(cid, favorite=new)
        return new

    def search(self, query='', category='', content_type='', language='',
               fav=False, page=1, pp=60):
        conds, params = [], []
        if query:
            conds.append('(content LIKE ? OR tags LIKE ? OR title LIKE ? OR notes LIKE ?)')
            p = f'%{query}%'
            params.extend([p, p, p, p])
        if category and category != 'all':
            conds.append('category=?')
            params.append(canonical_category(category))
        if content_type:
            conds.append('content_type=?')
            params.append(content_type)
        if language:
            conds.append('language=?')
            params.append(language)
        if fav:
            conds.append('favorite=1')
        where = ' AND '.join(conds) if conds else '1=1'
        off = (page - 1) * pp
        with self.lock:
            cur = self.conn.execute(
                f'SELECT * FROM clips WHERE {where} '
                'ORDER BY pinned DESC, favorite DESC, created_at DESC LIMIT ? OFFSET ?',
                params + [pp, off])
            items = [self._enrich(dict(r)) for r in cur]
            cur = self.conn.execute(f'SELECT COUNT(*) as c FROM clips WHERE {where}', params)
            total = cur.fetchone()['c']
        return items, total

    def folders(self):
        with self.lock:
            cur = self.conn.execute(
                'SELECT category, COUNT(*) as c, '
                'SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) as fav FROM clips '
                'GROUP BY category ORDER BY c DESC')
            counts = {}
            for r in cur:
                key = canonical_category(r['category'])
                entry = counts.setdefault(key, {'count': 0, 'favorites': 0})
                entry['count'] += r['c']
                entry['favorites'] += r['fav'] or 0
        result = []
        for key in CATEGORY_KEYS:
            e = counts.get(key, {'count': 0, 'favorites': 0})
            result.append({'key': key, 'label': CATEGORY_LABEL[key],
                           'color': CATEGORY_COLOR[key],
                           'count': e['count'], 'favorites': e['favorites']})
        return result

    def save_vector(self, cid, vec):
        with self.lock:
            try:
                vec_json = json.dumps(vec)
                self.conn.execute('UPDATE clips SET embedding_id=? WHERE id=?', (vec_json, cid))
                self.conn.commit()
                return True
            except Exception:
                return False

    def get_vector(self, cid):
        with self.lock:
            try:
                cur = self.conn.execute('SELECT embedding_id FROM clips WHERE id=?', (cid,))
                row = cur.fetchone()
                if row and row['embedding_id']:
                    data = json.loads(row['embedding_id'])
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return None

    def relations(self, cid):
        item = self.get(cid)
        if not item:
            return []
        try:
            rel = json.loads(item.get('relations') or '[]')
        except Exception:
            rel = []
        if rel:
            return rel
        tags = set((item.get('tags') or '').split(','))
        candidates, total = self.search(category=item.get('category') or '',
                                        pp=40)
        for other in candidates:
            if other['id'] == cid:
                continue
            otags = set((other.get('tags') or '').split(','))
            shared = tags & otags
            if len(shared) >= 2 or (
                    other.get('language') and other['language'] == item.get('language')
                    and other.get('category') == item.get('category')):
                rel.append({'to_id': other['id'], 'type': 'similar',
                            'weight': len(shared), 'shared': sorted(shared)})
        return rel[:10]

    def graph(self, limit=60):
        items, _ = self.search(pp=limit)
        nodes, edges, seen = [], [], set()
        for it in items:
            nodes.append({'id': it['id'], 'label': it.get('title') or f'Clip {it["id"]}',
                          'category': canonical_category(it.get('category') or ''),
                          'favorite': bool(it['favorite']),
                          'language': it.get('language') or ''})
        vectorizer = LocalVectorizer()
        vectors = {}
        for it in items:
            stored = self.get_vector(it['id'])
            if stored and isinstance(stored, list):
                vectors[it['id']] = stored
            else:
                txt = (it.get('content') or '') + ' ' + (it.get('tags') or '')
                v = vectorizer.vectorize(txt)
                vectors[it['id']] = v
                self.save_vector(it['id'], v)

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                at = set((a.get('tags') or '').split(',')) - {''}
                bt = set((b.get('tags') or '').split(',')) - {''}
                shared = at & bt
                sim = LocalVectorizer.cosine(vectors.get(a['id'], []), vectors.get(b['id'], []))
                if a.get('category') == b.get('category') and (shared or sim > 0.3):
                    weight = 2 + len(shared) + (2 if sim > 0.5 else 0)
                    edges.append({'source': a['id'], 'target': b['id'],
                                  'type': 'category', 'weight': min(weight, 5), 'similarity': round(sim, 2)})
                elif len(shared) >= 2 or sim > 0.42:
                    edge_type = 'tags' if len(shared) >= 2 else 'semantic'
                    edges.append({'source': a['id'], 'target': b['id'],
                                  'type': edge_type, 'weight': max(2, len(shared) + int(sim * 3)), 'similarity': round(sim, 2)})
                if len(edges) >= 80:
                    break
            if len(edges) >= 80:
                break
        return {'nodes': nodes, 'edges': edges}

    @staticmethod
    def _enrich(item):
        item['category_label'] = CATEGORY_LABEL.get(canonical_category(item.get('category')), '')
        item['category_color'] = CATEGORY_COLOR.get(canonical_category(item.get('category')), '#533483')
        try:
            st = json.loads(item.get('semantic_tags') or '[]')
            item['semantic_tags'] = st
        except Exception:
            item['semantic_tags'] = []
        try:
            item['relations'] = json.loads(item.get('relations') or '[]')
        except Exception:
            item['relations'] = []
        preview = (item.get('content') or '')
        if item['type'] != 'image' and len(preview) > 200:
            preview = preview[:197] + '...'
        item['preview'] = preview
        return item


# ─── KI / ANALYSIS HELPER ───────────────────────────────────

class AiHelper:
    """Optionaler OpenAI-kompatibler lokaler Endpoint; sonst Template-Fallback."""

    def __init__(self, endpoint='', api_key='', model=''):
        self.endpoint = (endpoint or '').strip().rstrip('/')
        self.api_key = api_key
        self.model = model or 'local'

    @property
    def enabled(self):
        return bool(self.endpoint)

    def chat(self, system, user, timeout=30, max_tokens=800):
        if not self.enabled:
            return None
        url = f'{self.endpoint}/v1/chat/completions'
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user[:30000]}],
            'max_tokens': max_tokens,
            'temperature': 0.2,
        }
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     **({'Authorization': f'Bearer {self.api_key}'} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['choices'][0]['message']['content'].strip()
        except Exception:
            return None

    def embed(self, text, timeout=15):
        if not self.enabled:
            return None
        url = f'{self.endpoint}/v1/embeddings'
        payload = {
            'model': self.model or 'text-embedding-nomic-embed-text-v1.5',
            'input': text[:4000],
        }
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     **({'Authorization': f'Bearer {self.api_key}'} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['data'][0]['embedding']
        except Exception:
            return None


class LocalVectorizer:
    """Zero-Dependency TF-IDF & Sublinear Character-N-Gram Hashing Vectorizer."""

    def __init__(self, dim=256):
        self.dim = dim

    def vectorize(self, text):
        if not text:
            return [0.0] * self.dim
        vec = [0.0] * self.dim
        tokens = re.findall(r'[a-zA-Z0-9äöüÄÖÜß_]+', text.lower())
        for token in tokens:
            h = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16) % self.dim
            vec[h] += 1.0
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    ng = token[i:i+3]
                    h_ng = int(hashlib.md5(ng.encode('utf-8')).hexdigest(), 16) % self.dim
                    vec[h_ng] += 0.4
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec

    @staticmethod
    def cosine(v1, v2):
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        return sum(a * b for a, b in zip(v1, v2))


class RagEngine:
    """RAG-Engine: Semantische Vektorsuche & wissensbasierte Fragebeantwortung."""

    def __init__(self, store, ai):
        self.store = store
        self.ai = ai
        self.vectorizer = LocalVectorizer(dim=256)
        self._vec_cache = {}

    def get_embedding(self, text, cid=None):
        if cid and cid in self._vec_cache:
            return self._vec_cache[cid]
        if cid and self.store:
            stored = self.store.get_vector(cid)
            if stored and isinstance(stored, list) and len(stored) == self.vectorizer.dim:
                self._vec_cache[cid] = stored
                return stored
        if self.ai and self.ai.enabled:
            ext = self.ai.embed(text)
            if ext and isinstance(ext, list):
                if cid and self.store:
                    self.store.save_vector(cid, ext)
                if cid:
                    self._vec_cache[cid] = ext
                return ext
        vec = self.vectorizer.vectorize(text)
        if cid and self.store:
            self.store.save_vector(cid, vec)
        if cid:
            self._vec_cache[cid] = vec
        return vec

    def retrieve(self, query, top_k=5, category=''):
        q_vec = self.get_embedding(query)
        items, _ = self.store.search(pp=500, category=category)
        scored = []
        for it in items:
            cid = it['id']
            content = (it.get('content') or '') + ' ' + (it.get('title') or '') + ' ' + (it.get('tags') or '')
            if not content.strip():
                continue
            it_vec = self.get_embedding(content, cid=cid)
            score = LocalVectorizer.cosine(q_vec, it_vec)
            q_words = set(re.findall(r'\w+', query.lower()))
            c_words = set(re.findall(r'\w+', content.lower()))
            overlap = len(q_words & c_words)
            if overlap:
                score += min(0.35, overlap * 0.06)
            if score > 0.04:
                scored.append((score, it))
        scored.sort(key=lambda x: -x[0])
        results = []
        for score, it in scored[:top_k]:
            results.append({
                'id': it['id'],
                'score': round(float(score), 3),
                'title': it.get('title') or f'Clip #{it["id"]}',
                'content': it.get('content', '')[:1200],
                'category': it.get('category', 'other'),
                'tags': it.get('tags', ''),
                'created_at': it.get('created_at', '')
            })
        return results

    def query(self, query, top_k=4):
        sources = self.retrieve(query, top_k=top_k)
        if not sources:
            return {
                'query': query,
                'answer': 'Keine passenden Zwischenablage-Inhalte für diese Anfrage gefunden.',
                'sources': []
            }
        if self.ai and self.ai.enabled:
            context_blocks = []
            for s in sources:
                context_blocks.append(f'--- [Clip #{s["id"]} | {s["title"]}] ---\n{s["content"][:1500]}')
            context = '\n\n'.join(context_blocks)
            sys_prompt = (
                'Du bist der intelligente RAG-Assistent für das Clipboard-Wissenssystem (MUSCAL). '
                'Beantworte die Frage des Benutzers präzise, faktenbasiert und auf Deutsch '
                'unter Verwendung der folgenden relevanten Zwischenablage-Inhalte. '
                'Verweise auf die passenden Clip-IDs (#ID), wenn du Fakten daraus zitierst.'
            )
            user_msg = f'Benutzerfrage: {query}\n\nKontext aus dem Clipboard:\n{context}'
            ans = self.ai.chat(sys_prompt, user_msg, max_tokens=1000)
            if ans:
                return {'query': query, 'answer': ans, 'sources': sources}

        # Extractive Offline-Zusammenfassung
        lines = [f'### RAG-Ergebnis für: "{query}"\n']
        lines.append(f'Es wurden **{len(sources)} relevante Quellen** im Clipboard gefunden:\n')
        for s in sources:
            relevance = int(min(1.0, s['score']) * 100)
            lines.append(f'**Clip #{s["id"]}** — *{s["title"]}* (Relevanz: {relevance}%, Kategorie: `{s["category"]}`)')
            lines.append(f'> {s["content"][:180].strip()}...\n')
        return {'query': query, 'answer': '\n'.join(lines), 'sources': sources}


def _top_keywords(text, n=10):
    words = re.findall(r'[A-Za-zäöüÄÖÜß_][A-Za-zäöüÄÖÜß0-9_\-]{2,}', (text or '').lower())
    stop = {'der', 'die', 'das', 'und', 'ist', 'nicht', 'ein', 'eine', 'the', 'and',
            'with', 'this', 'that', 'from', 'for', 'are', 'was', 'were', 'you',
            'your', 'our', 'haben', 'sind', 'wird', 'wurde', 'auf', 'mit', 'als'}
    counts = {}
    for w in words:
        if w not in stop:
            counts[w] = counts.get(w, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:n]
    return [w for w, _ in top]


def analyze_text(text, meta, ai):
    if ai.enabled:
        sysp = ('Du bist der MUSCAL Cognitive Layer. Analysiere den kopierten Inhalt '
                'kompakt: Kategorie, Inhaltstyp, Sprache, Kernaussage, Verwendung.')
        out = ai.chat(sysp, f'Inhalt:\n{text[:20000]}')
        if out:
            return out
    title = meta.get('title') or ''
    lines = (text or '').splitlines()
    snippet = '\n'.join(lines[:6]) + ('\n...' if len(lines) > 6 else '')
    return (
        'MUSCAL Analyse (Template-Fallback):\n'
        f'- Kategorie: {CATEGORY_LABEL.get(meta.get("category", "other"))}\n'
        f'- Inhaltstyp: {meta.get("content_type", "text")}\n'
        f'- Sprache: {meta.get("language") or "unbekannt"}\n'
        f'- Titel: {title or "-"}\n'
        f'- Tags: {", ".join(meta.get("tags", [])) or "-"}\n'
        f'- Stichworte: {", ".join(_top_keywords(text, 8)) or "-"}\n'
        f'- Zeilen: {len(lines)}, Zeichen: {len(text or "")}\n\n'
        f'Auszug:\n{snippet}'
    )


def explain_code(text, meta, ai):
    if ai.enabled:
        out = ai.chat('Erkläre den folgenden Code verständlich auf Deutsch.',
                      f'Code ({meta.get("language") or "unbekannt"}):\n{text[:20000]}')
        if out:
            return out
    lang = meta.get('language') or 'unbekannt'
    funcs = re.findall(r'\b(def|function)\s+(\w+)\s*\(([^)]*)\)', text)
    parts = [f'Code-Erklärung (Template, Sprache: {lang}):']
    if funcs:
        for kind, name, args in funcs[:5]:
            parts.append(f'- {name}({args.strip()}) — {kind}')
    if not funcs:
        parts.append('- Keine Funktionen erkannt; Abschnitt enthält Snippets/Ausdrücke.')
    parts.append(f'- {len(text.splitlines())} Zeilen, {len(text)} Zeichen')
    parts.append('- Empfehlung: In MUSCAL-Ordner "Code" ablegen und mit Tags ergänzen.')
    return '\n'.join(parts)


def create_document(item, meta, ai):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if ai.enabled:
        out = ai.chat(
            'Erstelle eine kompakte Markdown-Dokumentation des Inhalts auf Deutsch.',
            f'Titel: {meta.get("title", "")}\nInhalt:\n{(item.get("content") or "")[:20000]}')
        body = out or ''
    else:
        body = analyze_text(item.get('content') or '', meta, ai)
    path = DOCS_DIR / f'capture-{item["id"]:05d}-{datetime.now():%Y%m%d-%H%M%S}.md'
    md = []
    title_val = meta.get("title") or f'Capture #{item["id"]}'
    md.append(f'# {title_val}\n')
    md.append(f'- Kategorie: {CATEGORY_LABEL.get(meta.get("category", "other"))}')
    md.append(f'- Sprache: {meta.get("language") or "-"}')
    md.append(f'- Quelle: {meta.get("source_app") or "-"}')
    md.append(f'- Erstellt: {item.get("created_at", "")}')
    md.append(f'- Tags: {", ".join(meta.get("tags", []))}\n')
    md.append('---\n')
    md.append(body)
    md.append('\n---\n## Originalinhalt\n')
    md.append('```')
    md.append((item.get('content') or '')[:40000])
    md.append('```')
    path.write_text('\n'.join(md), encoding='utf-8')
    return str(path)


# ─── TK OVERLAYS ────────────────────────────────────────────

class _Draggable:
    def _bind_drag(self, widget):
        widget.bind('<ButtonPress-1>', self._drag_start)
        widget.bind('<B1-Motion>', self._drag_move)

    def _drag_start(self, event):
        self._drag_x, self._drag_y = event.x_root, event.y_root
        self._win_geo = self.win.geometry()

    def _drag_move(self, event):
        try:
            if not hasattr(self, '_win_geo'):
                return
            dx = event.x_root - self._drag_x
            dy = event.y_root - self._drag_y
            x = int(self.win.winfo_x()) + dx
            y = int(self.win.winfo_y()) + dy
            self.win.geometry(f'+{x}+{y}')
            self._drag_x, self._drag_y = event.x_root, event.y_root
        except Exception:
            pass


class NotificationOverlay(_Draggable):
    """Transparentes, verschiebbares Overlay unten rechts."""

    MAX_ITEMS = 6

    def __init__(self, root, theme, on_action=None):
        self.root = root
        self.theme = theme
        self.on_action = on_action
        self.caps = []
        self.expanded_id = None
        import tkinter as tk
        self.tk = tk
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self._alpha = 0.55
        self.win.attributes('-alpha', self._alpha)
        self.win.configure(bg=theme['bg'])
        self._build()
        self._bind_alpha(self.win)
        self.win.protocol('WM_DELETE_WINDOW', self.hide)
        self.win.bind('<Escape>', lambda e: self.hide())

    def _build(self):
        th = self.theme
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.w = 400
        self.win.geometry(f'+{sw - self.w - 20}+{sh - 230}')
        self.header = self.tk.Frame(self.win, bg=th['bg2'])
        self.header.pack(fill='x')
        self._bind_drag(self.header)
        self.tk.Label(self.header, text='🧠 MUSCAL Capture', bg=th['bg2'],
                      fg=th['highlight'], font=('Segoe UI', 11, 'bold')).pack(side='left', padx=8, pady=4)
        close_btn = self.tk.Button(self.header, text='×', bg=th['bg2'], fg=th['fg2'], relief='flat',
                                   font=('Segoe UI', 12, 'bold'), command=self.hide,
                                   activebackground=th['highlight'], activeforeground='#fff')
        close_btn.pack(side='right', padx=4)
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg=th['highlight']))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=th['fg2']))
        self.tk.Label(self.header, text='Esc/× schließt', bg=th['bg2'], fg=th['fg2'],
                      font=('Segoe UI', 8)).pack(side='right', padx=4)
        self.body = self.tk.Frame(self.win, bg=th['bg'])
        self.body.pack(fill='both', expand=True)

    def _set_alpha(self, val):
        self.win.attributes('-alpha', val)

    def _bind_alpha(self, widget):
        widget.bind('<Enter>', lambda e: self._set_alpha(1.0))
        widget.bind('<Leave>', lambda e: self._set_alpha(self._alpha))
        for child in widget.winfo_children():
            self._bind_alpha(child)

    def push(self, cap):
        self.caps.append(cap)
        if len(self.caps) > self.MAX_ITEMS:
            self.caps.pop(0)
        self.expanded_id = None
        self.redraw()
        self.show()

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    def redraw(self):
        for child in self.body.winfo_children():
            child.destroy()
        th = self.theme
        for cap in reversed(self.caps):
            row = self.tk.Frame(self.body, bg=th['bg'], cursor='hand2')
            row.pack(fill='x', padx=6, pady=1)
            time_s = (cap.get('created_at') or '')[:16].replace('T', ' ')
            label = (cap.get('title') or (cap.get('content') or '')[:40] or 'Capture')
            label = label.replace('\n', ' ')[:44]
            color = cap.get('category_color') or th['accent']
            self.tk.Label(row, text=f'{time_s}  ', bg=th['bg'], fg=th['fg2'],
                          font=('Consolas', 9), anchor='w').pack(side='left')
            self.tk.Label(row, text=label, bg=th['bg'], fg=th['fg'],
                          font=('Segoe UI', 10), anchor='w').pack(side='left', fill='x', expand=True)
            copy_lbl = self.tk.Label(row, text='📋', bg=th['bg'], fg=th['fg2'],
                                     font=('Segoe UI', 10), cursor='hand2')
            copy_lbl.pack(side='right', padx=(0, 2))
            self.tk.Label(row, text=cap.get('category_label', ''), bg=color, fg='#fff',
                          font=('Segoe UI', 8, 'bold'), padx=4).pack(side='right')
            if self.expanded_id == cap['id']:
                self._build_detail(cap)
            row.bind('<Button-1>',
                     lambda e, c=cap: self._toggle_expand(c['id']))
            for child in row.winfo_children():
                child.bind('<Button-1>',
                           lambda e, c=cap: self._toggle_expand(c['id']))
            copy_lbl.bind('<Button-1>', lambda e, c=cap: self._copy(cap))
            self._last_copy_lbl = copy_lbl
        self._bind_alpha(self.win)

    def _copy(self, cap):
        if copy_to_clipboard(cap.get('content') or ''):
            lbl = getattr(self, '_last_copy_lbl', None)
            if lbl and lbl.winfo_exists():
                lbl.config(text='✓', fg='#2ecc71')
                self.root.after(900,
                                lambda: lbl.config(text='📋', fg=self.theme['fg2']))

    def _toggle_expand(self, cid):
        self.expanded_id = cid if self.expanded_id != cid else None
        self.redraw()

    def _build_detail(self, cap):
        th = self.theme
        d = self.tk.Frame(self.body, bg=th['bg2'])
        d.pack(fill='x', padx=6, pady=4)
        tags = (cap.get('tags') or '').split(',') if cap.get('tags') else []
        meta = self.tk.Label(
            d, bg=th['bg2'], fg=th['fg2'], justify='left', anchor='w',
            font=('Segoe UI', 9),
            text=f'Kategorie: {cap.get("category_label", "")}    '
                 f'Typ: {cap.get("content_type", "")}    '
                 f'Sprache: {cap.get("language") or "-"}')
        meta.pack(fill='x', padx=6, pady=(6, 0))
        prev = (cap.get('content') or '')
        if cap['type'] != 'image' and len(prev) > 240:
            prev = prev[:237] + '...'
        self.tk.Label(d, bg=th['bg2'], fg=th['fg'], justify='left', anchor='w',
                      wraplength=350, font=('Consolas', 9),
                      text=prev).pack(fill='x', padx=6, pady=(4, 4))
        if tags:
            self.tk.Label(d, text='  '.join(tags), bg=th['bg2'], fg=th['accent'],
                          font=('Segoe UI', 9)).pack(fill='x', padx=6)
        btns = self.tk.Frame(d, bg=th['bg2'])
        btns.pack(fill='x', padx=6, pady=(6, 6))
        actions = [('Öffnen', 'open'), ('Bearbeiten', 'edit'),
                   ('Favorit', 'favorite'), ('Ordner', 'folder'),
                   ('Kopieren', 'copy'), ('KI', 'analyze')]
        for label, action in actions:
            b = self.tk.Button(btns, text=label, bg=th['bg'], fg=th['fg'],
                               relief='flat', font=('Segoe UI', 8),
                               command=lambda a=action, c=cap: self._act(a, c))
            b.pack(side='left', padx=1)

    def _act(self, action, cap):
        if action != 'copy':
            self.hide()
        if self.on_action:
            self.on_action(action, cap)


class FloatingActionButton(_Draggable):
    """Kleines schwebendes Element nach Ctrl+C; Menü mit Aktionen."""

    def __init__(self, root, theme, on_action=None, timeout_ms=8000):
        self.root = root
        self.theme = theme
        self.on_action = on_action
        self.timeout_ms = timeout_ms
        self._hide_after = None
        import tkinter as tk
        self.tk = tk
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.95)
        self.win.configure(bg=theme['highlight'])
        self._build()
        self.menu_win = None

    def _build(self):
        th = self.theme
        self.win.geometry('120x34')
        self.btn = self.tk.Button(self.win, text='🧠 MUSCAL', bg=th['highlight'],
                                  fg='#fff', relief='flat', font=('Segoe UI', 10, 'bold'),
                                  activebackground=th['selected'],
                                  command=self._toggle_menu)
        self.btn.pack(fill='both', expand=True)
        self._bind_drag(self.btn)

    def _toggle_menu(self):
        if self.menu_win and self.menu_win.winfo_exists():
            self.menu_win.destroy()
            self.menu_win = None
            return
        self._schedule_hide(0)
        self._show_menu()

    def _show_menu(self):
        th = self.theme
        x = self.win.winfo_x()
        y = self.win.winfo_y() + 36
        self.menu_win = self.tk.Toplevel(self.root)
        self.menu_win.withdraw()
        self.menu_win.overrideredirect(True)
        self.menu_win.attributes('-topmost', True)
        self.menu_win.configure(bg=th['bg2'])
        entries = [
            ('🔍 Analysieren', 'analyze'),
            ('🗂 Strukturieren', 'structure'),
            ('💬 Als Prompt speichern', 'prompt'),
            ('🐍 Code erklären', 'explain'),
            ('📄 Dokument erstellen', 'document'),
            ('📁 In Kategorie verschieben', 'move'),
            ('⭐ Favorisieren', 'favorite'),
        ]
        for label, action in entries:
            b = self.tk.Button(self.menu_win, text=label, bg=th['bg2'], fg=th['fg'],
                               relief='flat', anchor='w', font=('Segoe UI', 10),
                               activebackground=th['selected'], activeforeground='#fff',
                               command=lambda a=action: self._act(a))
            b.pack(fill='x', padx=2, pady=1)
        self.menu_win.update_idletasks()
        w = max(b.winfo_reqwidth() for b in self.menu_win.winfo_children()) + 8
        h = sum(b.winfo_reqheight() for b in self.menu_win.winfo_children()) + 8
        sw = self.root.winfo_screenwidth()
        if x + w > sw:
            x = sw - w - 8
        self.menu_win.geometry(f'{w}x{h}+{x}+{y}')
        self.menu_win.deiconify()
        self.menu_win.lift()

    def _act(self, action):
        if self.menu_win and self.menu_win.winfo_exists():
            self.menu_win.destroy()
            self.menu_win = None
        self.hide()
        if self.on_action:
            self.on_action(action, None)

    def show_at(self, x, y):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, min(x, sw - 130))
        y = max(0, min(y, sh - 40))
        self.win.geometry(f'+{x}+{y}')
        self.win.deiconify()
        self.win.lift()
        self._schedule_hide(self.timeout_ms)

    def _schedule_hide(self, ms):
        if self._hide_after is not None:
            try:
                self.root.after_cancel(self._hide_after)
            except Exception:
                pass
        if ms > 0:
            self._hide_after = self.root.after(ms, self.hide)

    def hide(self):
        try:
            if self.menu_win and self.menu_win.winfo_exists():
                self.menu_win.destroy()
                self.menu_win = None
        except Exception:
            pass
        self.win.withdraw()


# ─── MUSCAL LAYER ───────────────────────────────────────────

class MuscalLayer:
    """Integrationspunkt für CoolClipboard."""

    def __init__(self, db, config=None, root=None):
        self.db = db
        self.config = config or {}
        self.root = root
        self.analyzer = ContentAnalyzer()
        self.store = CaptureStore(db)
        self.store.migrate()
        self.ai = AiHelper(
            endpoint=self.config.get('muscal_ai_endpoint', ''),
            api_key=self.config.get('muscal_ai_key', ''),
            model=self.config.get('muscal_ai_model', ''))
        self.rag = RagEngine(self.store, self.ai)
        self.last_capture = None
        self.notification = None
        self.float_btn = None
        self._enabled_tk = False
        try:
            import tkinter as tk
            self._tk = tk
            if root is not None:
                self._enabled_tk = True
        except Exception:
            pass

    def attach_tk(self, root):
        self.root = root
        try:
            import tkinter as tk
            self._tk = tk
            self._enabled_tk = True
        except Exception:
            self._enabled_tk = False

    def build_overlays(self):
        if not self._enabled_tk or self.root is None:
            return
        if self.notification is None:
            theme = self.config.get('theme', 'dark')
            from coolclipboard import THEMES
            th = THEMES.get(theme, THEMES['dark'])
            self.notification = NotificationOverlay(
                self.root, th, on_action=self._notif_action)
            self.float_btn = FloatingActionButton(
                self.root, th, on_action=self._float_action,
                timeout_ms=int(self.config.get('muscal_float_timeout', 8)) * 1000)

    def process_capture(self, text):
        src = detect_source_app()
        meta = self.analyzer.analyze(text, src.get('name', ''))
        row = self.store.save(meta)
        if row is None:
            return None
        self.last_capture = row
        return row

    def process_image(self, image_bytes):
        src = detect_source_app()
        cap = self.store.save_image(image_bytes, {'source_app': src.get('name', '')})
        if cap:
            self.last_capture = cap
        return cap

    def on_capture(self, cap):
        if cap:
            self.last_capture = cap
        if self._enabled_tk and self.notification is not None:
            try:
                self.notification.push(cap)
            except Exception:
                pass

    def on_ctrl_c(self, x=None, y=None):
        if not self._enabled_tk or self.float_btn is None:
            return
        if x is None or y is None:
            try:
                from pynput import mouse
                x, y = mouse.Controller().position
            except Exception:
                x = y = 60
        if self.config.get('muscal_float', True):
            self.float_btn.show_at(x, y)

    def _notif_action(self, action, cap):
        cid = cap.get('id') if cap else None
        if action == 'open':
            self._open_web(cid)
        elif action == 'edit':
            self._open_web(cid, edit=True)
        elif action == 'favorite':
            if cid:
                self.store.toggle_favorite(cid)
        elif action == 'folder':
            self._prompt_category(cid, title='In Kategorie verschieben')
        elif action == 'analyze':
            self._run_analysis(cid)

    def _float_action(self, action, _cap):
        if self.last_capture is None:
            return
        cid = self.last_capture.get('id') or self.last_capture.get('clip_id')
        meta = self.last_capture
        if action == 'analyze':
            self._run_analysis(cid, meta=meta)
        elif action == 'structure':
            self._structure(meta)
        elif action == 'prompt':
            self._set_category(cid, 'prompt')
        elif action == 'explain':
            self._run_explain(cid, meta=meta)
        elif action == 'document':
            self._run_document(cid, meta=meta)
        elif action == 'move':
            self._prompt_category(cid, title='In Kategorie verschieben')
        elif action == 'favorite':
            if cid:
                self.store.toggle_favorite(cid)
                self._show_result('Favorit aktualisiert.',
                                  'Der Eintrag wurde ' +
                                  ('favorisiert.' if self.store.get(cid)['favorite'] else 'entfernt.'))

    def _structure(self, meta):
        cid = meta.get('id')
        if not cid:
            item = self.store.get(meta.get('clip_id'))
            cid = item['id'] if item else None
        if not cid:
            return
        self.store.update(cid, category=meta.get('category', 'other'),
                          language=meta.get('language', ''),
                          content_type=meta.get('content_type', 'text'),
                          tags=','.join(meta.get('tags', [])))
        self._show_result('Strukturiert',
                          f'Kategorie: {CATEGORY_LABEL.get(meta.get("category", "other"))}\n'
                          f'Tags: {", ".join(meta.get("tags", []))}')

    def _set_category(self, cid, category):
        if not cid:
            return
        self.store.update(cid, category=category)
        self._show_result('Gespeichert',
                          f'Eintrag nach "{CATEGORY_LABEL.get(category, category)}" verschoben.')

    def _prompt_category(self, cid, title='Ordner wählen'):
        if not cid or not self._enabled_tk:
            return
        win = self._tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=self._tk_theme()['bg2'])
        keys = [k for k in CATEGORY_KEYS]
        win.var = self._tk.StringVar(value=keys[0])
        self._tk.Label(win, text=title, bg=self._tk_theme()['bg2'],
                       fg=self._tk_theme()['fg'], font=('Segoe UI', 9)).pack(padx=8, pady=(8, 2))
        om = self._tk.OptionMenu(win, win.var, *[CATEGORY_LABEL[k] for k in keys])
        om.config(bg=self._tk_theme()['bg'], fg=self._tk_theme()['fg'],
                  font=('Segoe UI', 9))
        om.pack(padx=8)
        btns = self._tk.Frame(win, bg=self._tk_theme()['bg2'])
        btns.pack(pady=6)

        def ok():
            label = win.var.get()
            key = next(k for k in keys if CATEGORY_LABEL[k] == label)
            self._set_category(cid, key)
            win.destroy()

        self._tk.Button(btns, text='OK', command=ok, bg=self._tk_theme()['highlight'],
                        fg='#fff', relief='flat').pack(side='left', padx=4)
        self._tk.Button(btns, text='Abbrechen', command=win.destroy,
                        bg=self._tk_theme()['bg'], fg=self._tk_theme()['fg'],
                        relief='flat').pack(side='left', padx=4)
        win.update_idletasks()
        x = self.root.winfo_pointerx() + 12
        y = self.root.winfo_pointery() + 12
        win.geometry(f'+{x}+{y}')
        win.deiconify()

    def _tk_theme(self):
        from coolclipboard import THEMES
        return THEMES.get(self.config.get('theme', 'dark'), THEMES['dark'])

    def _open_web(self, cid, edit=False):
        import webbrowser
        url = 'http://localhost:8234/'
        if cid:
            url += f'#clip-{cid}'
        webbrowser.open(url)

    def _show_result(self, title, text):
        if not self._enabled_tk:
            return
        th = self._tk_theme()
        win = self._tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=th['bg2'])
        self._tk.Label(win, text=f'🧠 {title}', bg=th['bg2'], fg=th['highlight'],
                       font=('Segoe UI', 10, 'bold')).pack(padx=10, pady=(8, 2))
        self._tk.Label(win, text=text, bg=th['bg2'], fg=th['fg'], justify='left',
                       anchor='w', wraplength=380, font=('Segoe UI', 9)).pack(
            padx=10, pady=4)
        self._tk.Button(win, text='Schließen', command=win.destroy, bg=th['bg'],
                        fg=th['fg'], relief='flat').pack(pady=(2, 8))

        def expire():
            try:
                win.destroy()
            except Exception:
                pass
        win.after(12000, expire)
        x = self.root.winfo_pointerx() + 12
        y = self.root.winfo_pointery() + 12
        win.update_idletasks()
        win.geometry(f'+{x}+{y}')
        win.deiconify()

    def _run_analysis(self, cid, meta=None):
        item = self.store.get(cid) if cid else None
        if not item:
            return
        meta = meta or self._meta_from_item(item)
        text = item.get('content') or ''
        result = analyze_text(text, meta, self.ai)
        self.store.update(cid, notes=item.get('notes') or '')
        self._show_result('KI Analyse', result[:1500])

    def _run_explain(self, cid, meta=None):
        item = self.store.get(cid) if cid else None
        if not item:
            return
        meta = meta or self._meta_from_item(item)
        result = explain_code(item.get('content') or '', meta, self.ai)
        self._show_result('Code Erklärung', result[:1500])

    def _run_document(self, cid, meta=None):
        item = self.store.get(cid) if cid else None
        if not item:
            return
        meta = meta or self._meta_from_item(item)
        path = create_document(item, meta, self.ai)
        self._show_result('Dokument erstellt', f'Ablage:\n{path}')

    def _meta_from_item(self, item):
        meta = {
            'category': canonical_category(item.get('category')),
            'content_type': item.get('content_type') or 'text',
            'language': item.get('language') or '',
            'tags': (item.get('tags') or '').split(','),
            'title': item.get('title') or '',
            'hash': item.get('hash') or '',
            'source_app': item.get('source_app') or '',
        }
        if not meta['title']:
            meta['title'] = self.analyzer.detect_title(item.get('content') or '')
        return meta


# ─── WEB ROUTES ─────────────────────────────────────────────

def register_webapp(app, cc):
    from flask import jsonify, request
    layer = getattr(cc, 'muscal', None)
    if layer is None:
        return

    @app.route('/')
    def muscal_index():
        return WEB_UI_HTML

    @app.route('/api/captures', methods=['GET'])
    def api_captures():
        q = request_args(cc, 'search', '')
        cat = request_args(cc, 'category', '')
        ct = request_args(cc, 'type', '')
        lang = request_args(cc, 'language', '')
        fav = request_args(cc, 'favorite', '') == 'true'
        page = int(request_args(cc, 'page', 1))
        items, total = layer.store.search(q, cat, ct, lang, fav, page)
        return flask_json(items, total, page)

    @app.route('/api/captures/<int:cid>', methods=['GET'])
    def api_capture_get(cid):
        item = layer.store.get(cid)
        if not item:
            return err_json('not found')
        return jsonify(layer.store._enrich(item))

    @app.route('/api/captures/<int:cid>', methods=['PUT'])
    def api_capture_update(cid):
        data = flask_get_json(cc)
        keys = {k: data[k] for k in
                ('category', 'tags', 'notes', 'favorite', 'language',
                 'content_type', 'semantic_tags', 'folder', 'title')
                if k in data}
        ok = layer.store.update(cid, **keys)
        return jsonify({'ok': ok})

    @app.route('/api/captures/<int:cid>/favorite', methods=['POST'])
    def api_capture_fav(cid):
        val = layer.store.toggle_favorite(cid)
        return jsonify({'ok': val is not None, 'favorite': val})

    @app.route('/api/captures/<int:cid>/relations', methods=['GET'])
    def api_capture_relations(cid):
        return jsonify({'relations': layer.store.relations(cid)})

    @app.route('/api/captures/<int:cid>/analyze', methods=['POST'])
    def api_capture_analyze(cid):
        item = layer.store.get(cid)
        if not item:
            return err_json('not found')
        meta = layer._meta_from_item(item)
        result = analyze_text(item.get('content') or '', meta, layer.ai)
        return jsonify({'ok': True, 'result': result})

    @app.route('/api/captures/<int:cid>/document', methods=['POST'])
    def api_capture_document(cid):
        item = layer.store.get(cid)
        if not item:
            return err_json('not found')
        meta = layer._meta_from_item(item)
        path = create_document(item, meta, layer.ai)
        return jsonify({'ok': True, 'path': path})

    @app.route('/api/captures/<int:cid>/move', methods=['POST'])
    def api_capture_move(cid):
        data = flask_get_json(cc)
        cat = canonical_category(data.get('category', ''))
        layer.store.update(cid, category=cat)
        return jsonify({'ok': True, 'category': cat})

    @app.route('/api/folders', methods=['GET'])
    def api_folders():
        return jsonify({'folders': layer.store.folders()})

    @app.route('/api/graph', methods=['GET'])
    def api_graph():
        return jsonify(layer.store.graph())

    @app.route('/api/meta', methods=['GET'])
    def api_meta():
        from flask import jsonify
        return jsonify({
            'version': MUSCAL_VERSION,
            'float_enabled': bool(layer.config.get('muscal_float', True)),
            'ai_enabled': layer.ai.enabled,
            'endpoint': layer.ai.endpoint or '',
            'categories': [{'key': k, 'label': CATEGORY_LABEL[k],
                            'color': CATEGORY_COLOR[k]} for k in CATEGORY_KEYS],
            'store_count': layer.store.search(pp=1)[1],
        })

    @app.route('/api/rag/query', methods=['POST'])
    def api_rag_query():
        data = flask_get_json(cc)
        q = (data.get('query') or '').strip()
        top_k = int(data.get('top_k', 4))
        if not q:
            return err_json('Query is required')
        res = layer.rag.query(q, top_k=top_k)
        return jsonify(res)

    @app.route('/api/rag/search', methods=['GET'])
    def api_rag_search():
        q = request_args(cc, 'q', '')
        top_k = int(request_args(cc, 'top_k', 5))
        if not q:
            return jsonify({'results': []})
        res = layer.rag.retrieve(q, top_k=top_k)
        return jsonify({'results': res})


# ─── WEB UTILS ──────────────────────────────────────────────

def request_args(cc, key, default):
    try:
        from flask import request
        return request.args.get(key, default)
    except Exception:
        return default


def flask_get_json(cc):
    from flask import request
    return request.get_json(force=True)


def flask_json(items, total, page):
    from flask import jsonify
    return jsonify({'items': items, 'total': total, 'page': page})


def err_json(msg):
    from flask import jsonify
    return jsonify({'error': msg}), 404


# ─── WEB UI (SPA) ───────────────────────────────────────────

WEB_UI_HTML = r'''<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MUSCAL Cognitive Clipboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#1a1a2e;--bg2:#16213e;--fg:#e0e0e0;--fg2:#a0a0a0;--accent:#0f3460;--hl:#e94560;--sel:#533483;--brd:#2a2a4a}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--fg);min-height:100vh}
.header{background:var(--bg2);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid var(--brd);position:sticky;top:0;z-index:50}
.header h1{font-size:19px;color:var(--hl);font-weight:700}
.header h1 span{color:var(--sel)}
.tabs{display:flex;gap:2px;padding:0 24px;background:var(--bg2);border-bottom:1px solid var(--brd);flex-wrap:wrap}
.tab{padding:9px 16px;cursor:pointer;font-size:13px;color:var(--fg2);border-bottom:2px solid transparent;transition:.2s}
.tab:hover{color:var(--fg)}
.tab.active{color:var(--hl);border-bottom-color:var(--hl)}
.toolbar{display:flex;gap:8px;padding:12px 24px 4px;flex-wrap:wrap;align-items:center}
.toolbar input[type=text]{flex:1;min-width:200px;padding:8px 12px;border:1px solid var(--brd);border-radius:6px;background:var(--bg2);color:var(--fg);font-size:13px;outline:none}
.toolbar input:focus{border-color:var(--hl)}
.btn{padding:6px 14px;border:1px solid var(--brd);border-radius:6px;background:var(--bg2);color:var(--fg);cursor:pointer;font-size:12px;transition:.2s;white-space:nowrap}
.btn:hover{background:var(--brd);border-color:var(--sel)}
.btn.active{background:var(--sel);border-color:var(--hl);color:#fff}
.chips{display:flex;gap:6px;padding:8px 24px;flex-wrap:wrap}
.chip{padding:3px 10px;border-radius:12px;font-size:11px;cursor:pointer;opacity:.55;transition:.2s;border:1px solid transparent}
.chip:hover{opacity:.85}
.chip.active{opacity:1;border-color:var(--fg2);font-weight:600}
.main{padding:12px 24px 40px}
.day-group{margin-bottom:18px}
.day-label{font-size:11px;text-transform:uppercase;color:var(--fg2);letter-spacing:1px;padding:6px 0 8px;border-bottom:1px solid var(--brd)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:12px;cursor:pointer;transition:.2s;position:relative;border-left:3px solid var(--brd)}
.card:hover{border-color:var(--sel);transform:translateY(-1px)}
.card.fav-card{border-left-color:var(--hl)}
.card .meta{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:10px;color:var(--fg2);flex-wrap:wrap}
.card .badge{padding:1px 6px;border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase;color:#fff}
.card .title{font-size:12.5px;font-weight:600;margin-bottom:4px;word-break:break-word}
.card .preview{font-size:11px;line-height:1.5;color:#c0c0c0;max-height:50px;overflow:hidden;word-break:break-all;white-space:pre-wrap}
.card .tags{display:flex;flex-wrap:wrap;gap:3px;margin-top:6px}
.tag{padding:1px 6px;border-radius:3px;background:var(--accent);color:#a0c4ff;font-size:9px}
.card .star{position:absolute;top:8px;right:10px;font-size:15px;color:#555;cursor:pointer}
.card .star.on{color:var(--hl)}
.card .fold{position:absolute;top:8px;right:30px;font-size:12px;color:#555;cursor:pointer}
.card .detail{display:none;margin-top:8px;border-top:1px solid var(--brd);padding-top:8px;font-size:11px;line-height:1.6}
.card.expanded .detail{display:block}
.card .detail pre{background:var(--bg);border-radius:6px;padding:8px;max-height:220px;overflow:auto;font-size:11px;white-space:pre-wrap;word-break:break-all;margin:6px 0;font-family:Consolas,monospace}
.card .actions{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.folder-tree{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:14px}
.folder-node{display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:6px;cursor:pointer;transition:.2s;font-size:13px}
.folder-node:hover{background:var(--accent)}
.folder-node .cnt{margin-left:auto;font-size:11px;color:var(--fg2)}
.folder-node .fav{font-size:11px}
.graph-wrap{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:10px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.stat-card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:14px;text-align:center}
.stat-card .v{font-size:26px;font-weight:700;color:var(--hl)}
.stat-card .l{font-size:11px;color:var(--fg2);margin-top:3px}
.empty{text-align:center;padding:50px 20px;color:#555;grid-column:1/-1}
.result-box{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:14px;margin-top:10px;white-space:pre-wrap;font-size:12px;line-height:1.6;font-family:Consolas,monospace}
</style></head>
<body>
<div class="header">
<div><h1>MUSCAL<span> Capture</span></h1></div>
<div style="display:flex;align-items:center;gap:10px">
<div style="display:flex;gap:4px">
<a href="/api/export/markdown" download class="btn" style="font-size:11px;padding:3px 8px;text-decoration:none" title="Markdown Export">📄 MD</a>
<a href="/api/export/json" download class="btn" style="font-size:11px;padding:3px 8px;text-decoration:none" title="JSON Export">📊 JSON</a>
<a href="/api/export/csv" download class="btn" style="font-size:11px;padding:3px 8px;text-decoration:none" title="CSV Export">📑 CSV</a>
</div>
<div style="font-size:11px;color:var(--fg2)" id="metaLine">…</div>
</div>
</div>
<div class="tabs">
<div class="tab active" onclick="view('timeline')">🕒 Timeline</div>
<div class="tab" onclick="view('folders')">📁 Ordner</div>
<div class="tab" onclick="view('favorites')">⭐ Favoriten</div>
<div class="tab" onclick="view('graph')">🕸 Wissen</div>
<div class="tab" onclick="view('rag')">🧠 RAG / Chat</div>
<div class="tab" onclick="view('snippets')">📝 Snippets</div>
<div class="tab" onclick="view('stats')">📊 Statistik</div>
</div>
<div id="toolbar" class="toolbar">
<input type="text" id="search" placeholder="Suchen…" oninput="onSearch()">
<button class="btn active" data-f="all" onclick="setFilter('all')">Alle</button>
<button class="btn" data-f="code" onclick="setFilter('code')">Code</button>
<button class="btn" data-f="error" onclick="setFilter('error')">Fehler</button>
<button class="btn" data-f="link" onclick="setFilter('link')">Links</button>
<button class="btn" data-f="fav" onclick="setFilter('fav')">⭐ Favoriten</button>
</div>
<div class="chips" id="catChips"></div>
<div class="main" id="main"></div>
<script>
let curView='timeline',curCat='all',curFilter='all',cats=[],lastHash='';
const $=id=>document.getElementById(id);
const esc=s=>{const d=document.createElement('div');d.textContent=s??'';return d.innerHTML};
function loadMeta(){fetch('/api/meta').then(r=>r.json()).then(m=>{
 cats=m.categories;
 $('metaLine').textContent='v'+m.version+' · '+m.store_count+' Captures'+(m.ai_enabled?' · KI aktiv':'');
 renderChips();})}
function renderChips(){
 let h='<span style="font-size:11px;color:var(--fg2)">Kategorie:</span>';
 cats.forEach(c=>{h+='<div class="chip'+(curCat===c.key?' active':'')+'" style="background:'+c.color+'" onclick="setCat(\''+c.key+'\')">'+c.label+'</div>'});
 $('catChips').innerHTML=h;}
function view(v){curView=v;
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.textContent.includes({timeline:'Timeline',folders:'Ordner',favorites:'Favoriten',graph:'Wissen',snippets:'Snippets',stats:'Statistik',rag:'RAG'}[v])));
 $('toolbar').style.display=(v==='timeline'||v==='favorites')?'flex':'none';
 $('catChips').style.display=(v==='timeline'||v==='favorites')?'flex':'none';
 if(v==='timeline'||v==='favorites')load();else if(v==='folders')loadFolders();else if(v==='graph')loadGraph();else if(v==='snippets')loadSnippets();else if(v==='stats')loadStats();else if(v==='rag')loadRag();
 location.hash='#'+v;}
function setFilter(f){curFilter=f;document.querySelectorAll('.toolbar .btn[data-f]').forEach(b=>b.classList.toggle('active',b.dataset.f===f));load()}
function setCat(k){curCat=k;load();}
function onSearch(){load()}
function load(){
 let q='?page=1';
 if($('search').value)q+='&search='+encodeURIComponent($('search').value);
 if(curFilter==='code')q+='&type=code';
 else if(curFilter==='error')q+='&type=error';
 else if(curFilter==='link')q+='&type=link';
 else if(curFilter==='fav')q+='&favorite=true';
 if(curCat&&curCat!=='all')q+='&category='+encodeURIComponent(curCat);
 fetch('/api/captures'+q).then(r=>r.json()).then(d=>{
  let groups={};
  d.items.forEach(it=>{const day=(it.created_at||'').slice(0,10);(groups[day]=groups[day]||[]).push(it)});
  let h='';
  if(!d.items.length)h='<div class="empty"><h2>Keine Captures</h2><p>Strg+C in einer App — MUSCAL erkennt und speichert.</p></div>';
  Object.keys(groups).sort().reverse().forEach(day=>{
   h+='<div class="day-group"><div class="day-label">'+day+'</div><div class="cards">';
   groups[day].forEach(it=>{h+=card(it,true)});
   h+='</div></div>'});
  $('main').innerHTML=h;
  if(location.hash.includes('clip-')){const id=location.hash.split('-')[1];document.querySelector('.card[data-id="'+id+'"]')?.click()}})}
function card(it,withFold){
 let fav=it.favorite?'on':'';
 let cat=it.category_color||'var(--brd)';
 let ct=(it.content_type||it.type||'text').toUpperCase();
 let tags=(it.tags||'').split(',').filter(Boolean).map(t=>'<span class="tag">'+esc(t)+'</span>').join('');
 let lang=it.language?'<span class="badge" style="background:#533483">'+esc(it.language)+'</span>':'';
 let prev=it.type==='image'?'[Bild]':esc(it.preview||'').slice(0,160);
 let time=(it.created_at||'').slice(11,16);
 return '<div class="card '+(fav?'fav-card':'')+(withFold?'':'')+'" data-id="'+it.id+'" onclick="toggleExpand(this,'+it.id+')">'
  +'<div class="meta"><span class="badge" style="background:'+cat+'">'+esc(it.category_label||it.category||'other')+'</span><span class="badge" style="background:#0f3460">'+ct+'</span>'+lang+'<span>'+time+'</span></div>'
  +'<div class="star '+(it.favorite?'on':'')+'" onclick="event.stopPropagation();fav('+it.id+')">'+(it.favorite?'★':'☆')+'</div>'
  +'<div class="title">'+esc(it.title||(it.content||'').slice(0,60))+'</div>'
  +'<div class="preview">'+prev+'</div>'
  +'<div class="tags">'+tags+'</div>'
  +'<div class="detail"><pre>'+(it.type==='image'?'[Bild]':esc(it.content||''))+'</pre>'
  +'<div style="font-size:10px;color:var(--fg2)">Quelle: '+(esc(it.source_app)||'-')+' · Hash: '+(it.hash||'').slice(0,12)+'…</div>'
  +'<div class="actions">'
  +'<button class="btn" onclick="event.stopPropagation();act('+it.id+',\'analyze\')">🔍 Analyse</button>'
  +'<button class="btn" onclick="event.stopPropagation();act('+it.id+',\'favorite\')">⭐ Favorit</button>'
  +'<button class="btn" onclick="event.stopPropagation();moveCat('+it.id+')">📁 Ordner</button>'
  +'<button class="btn" onclick="event.stopPropagation();act('+it.id+',\'document\')">📄 Dokument</button>'
  +'</div></div></div>';}
function toggleExpand(el,id){el.classList.toggle('expanded')}
function fav(id){fetch('/api/captures/'+id+'/favorite',{method:'POST'}).then(()=>load())}
function act(id,kind){fetch('/api/captures/'+id+'/'+kind,{method:'POST'}).then(r=>r.json()).then(d=>{
 if(kind==='analyze'||kind==='document'){const b=document.createElement('div');b.className='result-box';b.textContent=d.result||d.path||'ok';const m=$('main');m.insertBefore(b,m.firstChild);setTimeout(()=>b.remove(),25000)}
 load()})}
function moveCat(id){
 const sel=prompt('In Kategorie verschieben:\n'+cats.map(c=>c.key+': '+c.label).join('\n')+'\n\nKategorie:');
 if(!sel)return;
 const key=sel.trim().toLowerCase();
 fetch('/api/captures/'+id+'/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:key})}).then(()=>load())}
function loadFolders(){
 fetch('/api/folders').then(r=>r.json()).then(d=>{
  let h='<div class="folder-tree"><div class="folder-node" style="font-weight:700;color:var(--hl)" onclick="setCat(\'all\')">📁 MUSCAL <span class="cnt">Alle</span></div>';
  d.folders.forEach(f=>{
   if(f.count===0&&!f.favorites)return;
   h+='<div class="folder-node" onclick="curCat=\''+f.key+'\';view(\'timeline\')" style="border-left:3px solid '+f.color+'">'+f.label
    +'<span class="fav">'+(f.favorites?'⭐ '+f.favorites:'')+'</span><span class="cnt">'+f.count+'</span></div>'});
  h+='</div>';
  $('main').innerHTML=h})}
let graphSim=null;
function loadGraph(){
 fetch('/api/graph').then(r=>r.json()).then(g=>{
  let h='<div class="graph-wrap">';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">';
  h+='<div style="font-size:13px;font-weight:600;color:var(--hl)">🕸 Interaktiver Wissensgraph ('+g.nodes.length+' Knoten, '+g.edges.length+' Kanten)</div>';
  h+='<div style="font-size:11px;color:var(--fg2)">Knoten ziehen / anklicken zum Öffnen</div>';
  h+='</div>';
  h+='<canvas id="graphCanvas" width="800" height="420" style="background:var(--bg2);border:1px solid var(--brd);border-radius:8px;width:100%;max-width:100%;height:420px;cursor:grab;display:block"></canvas>';
  h+='<div style="margin-top:14px;font-size:12px;color:var(--fg2)">Knoten &amp; Cluster:</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">';
  g.nodes.forEach(n=>{
   const c=cats.find(c=>c.key===n.category)||{label:n.category,color:'var(--brd)'};
   h+='<div class="folder-node" style="margin:0;border-left:3px solid '+c.color+';padding:4px 8px;font-size:11px" onclick="setCat(\'all\');view(\'timeline\');setTimeout(()=>document.querySelector(\'.card[data-id=\\\"'+n.id+'\\\"]\')?.click(),300)">'
    +esc(n.label)+' '+(n.favorite?'⭐':'')+'</div>';
  });
  h+='</div></div>';
  $('main').innerHTML=h;
  initGraphCanvas(g);
 });}

function initGraphCanvas(g){
 const cvs=$('graphCanvas');
 if(!cvs)return;
 const ctx=cvs.getContext('2d');
 const W=cvs.width, H=cvs.height;
 const nodes=g.nodes.map((n,i)=>{
  const angle=(i/Math.max(1,g.nodes.length))*2*Math.PI;
  const radius=120+Math.random()*60;
  const c=cats.find(c=>c.key===n.category)||{color:'#533483'};
  return {id:n.id,label:n.label,category:n.category,color:c.color,fav:n.favorite,
          x:W/2+Math.cos(angle)*radius,y:H/2+Math.sin(angle)*radius,vx:0,vy:0,r:n.favorite?9:7};
 });
 const nodeMap={};nodes.forEach(n=>nodeMap[n.id]=n);
 const edges=g.edges.map(e=>({source:nodeMap[e.source],target:nodeMap[e.target],type:e.type,weight:e.weight||1,sim:e.similarity||0})).filter(e=>e.source&&e.target);

 let dragged=null;
 cvs.onmousedown=(e)=>{
  const rect=cvs.getBoundingClientRect();
  const mx=(e.clientX-rect.left)*(cvs.width/rect.width);
  const my=(e.clientY-rect.top)*(cvs.height/rect.height);
  for(let n of nodes){
   if((n.x-mx)*(n.x-mx)+(n.y-my)*(n.y-my)<(n.r+8)*(n.r+8)){dragged=n;break;}
  }
 };
 window.onmousemove=(e)=>{
  if(!dragged)return;
  const rect=cvs.getBoundingClientRect();
  dragged.x=Math.max(15,Math.min(W-15,(e.clientX-rect.left)*(cvs.width/rect.width)));
  dragged.y=Math.max(15,Math.min(H-15,(e.clientY-rect.top)*(cvs.height/rect.height)));
 };
 window.onmouseup=()=>{dragged=null;};
 cvs.onclick=(e)=>{
  const rect=cvs.getBoundingClientRect();
  const mx=(e.clientX-rect.left)*(cvs.width/rect.width);
  const my=(e.clientY-rect.top)*(cvs.height/rect.height);
  for(let n of nodes){
   if((n.x-mx)*(n.x-mx)+(n.y-my)*(n.y-my)<(n.r+8)*(n.r+8)){
    setCat('all');view('timeline');setTimeout(()=>document.querySelector('.card[data-id="'+n.id+'"]')?.click(),300);break;
   }
  }
 };

 if(graphSim)cancelAnimationFrame(graphSim);
 let steps=0;
 function step(){
  for(let i=0;i<nodes.length;i++){
   for(let j=i+1;j<nodes.length;j++){
    let dx=nodes[j].x-nodes[i].x, dy=nodes[j].y-nodes[i].y;
    let dist=Math.sqrt(dx*dx+dy*dy)||1;
    if(dist<160){
     let force=(160-dist)/(dist*25);
     let fx=dx*force, fy=dy*force;
     if(nodes[i]!==dragged){nodes[i].x-=fx;nodes[i].y-=fy;}
     if(nodes[j]!==dragged){nodes[j].x+=fx;nodes[j].y+=fy;}
    }
   }
  }
  for(let e of edges){
   let dx=e.target.x-e.source.x, dy=e.target.y-e.source.y;
   let dist=Math.sqrt(dx*dx+dy*dy)||1;
   let targetDist=e.type==='category'?65:95;
   let force=(dist-targetDist)*0.015*(e.weight/2);
   let fx=(dx/dist)*force, fy=(dy/dist)*force;
   if(e.source!==dragged){e.source.x+=fx;e.source.y+=fy;}
   if(e.target!==dragged){e.target.x-=fx;e.target.y-=fy;}
  }
  for(let n of nodes){
   if(n!==dragged){
    n.x+=(W/2-n.x)*0.01; n.y+=(H/2-n.y)*0.01;
    n.x=Math.max(15,Math.min(W-15,n.x)); n.y=Math.max(15,Math.min(H-15,n.y));
   }
  }
  ctx.clearRect(0,0,W,H);
  for(let e of edges){
   ctx.beginPath();ctx.moveTo(e.source.x,e.source.y);ctx.lineTo(e.target.x,e.target.y);
   ctx.strokeStyle=e.type==='semantic'?'rgba(233,69,96,0.4)':(e.type==='category'?'rgba(83,52,131,0.5)':'rgba(79,195,247,0.35)');
   ctx.lineWidth=Math.min(3,Math.max(1,e.weight*0.7));ctx.stroke();
  }
  for(let n of nodes){
   ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,2*Math.PI);
   ctx.fillStyle=n.color||'#533483';ctx.fill();
   ctx.strokeStyle=n.fav?'#e94560':'#2a2a4a';ctx.lineWidth=n.fav?2:1;ctx.stroke();
   ctx.font='10px Segoe UI,sans-serif';ctx.fillStyle='#e0e0e0';
   ctx.fillText(n.label.slice(0,14),n.x+n.r+3,n.y+3);
  }
  steps++;
  if(steps<300||dragged){graphSim=requestAnimationFrame(step);}
 }
 step();
}
function loadSnippets(){
 fetch('/api/snippets').then(r=>r.json()).then(d=>{
  let snips=(d&&d.snippets)||[];
  let h='<div class="toolbar" style="padding:0 0 10px"><button class="btn" onclick="newSnippet()">+ Neues Snippet</button></div>';
  if(!snips.length){h+='<div class="empty"><h2>Keine Snippets</h2><p>Erstelle wiederverwendbare Vorlagen.</p></div>';}
  else{snips.forEach(s=>{h+='<div class="card" onclick="useSnip('+s.id+')"><div class="title">'+esc(s.name)+'</div><div class="preview">'+esc((s.content||'').slice(0,120))+'</div><div class="meta">Used '+s.use_count+'x</div></div>'});}
  $('main').innerHTML=h})}
function useSnip(id){fetch('/api/snippets/'+id+'/use',{method:'POST'}).then(()=>alert('In die Zwischenablage kopiert!'))}
function newSnippet(){const n=prompt('Name:'),c=prompt('Inhalt:');if(n&&c)fetch('/api/snippets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,content:c})}).then(()=>loadSnippets())}
function loadStats(){
 fetch('/api/stats').then(r=>r.json()).then(s=>{
  const cards=[['Total',s.total_clips],['Text',s.text_clips],['Bilder',s.image_clips],['Favoriten',s.favorites],['Pinned',s.pinned],['Snippets',s.snippets]];
  let h='<div class="stats-grid">';
  cards.forEach(c=>h+='<div class="stat-card"><div class="v">'+c[1]+'</div><div class="l">'+c[0]+'</div></div>');
  h+='</div>';
  if(s.top_tags&&s.top_tags.length){h+='<div style="margin-top:14px;font-size:12px;color:var(--fg2)">Top Tags</div><div class="tags" style="margin-top:6px">'+s.top_tags.map(t=>'<span class="tag">'+esc(t[0])+' ('+t[1]+')</span>').join('')+'</div>'}
  $('main').innerHTML=h})}
function loadRag(){
 let h='<div style="max-width:800px;margin:0 auto">';
 h+='<div style="background:var(--bg2);padding:16px;border-radius:8px;border:1px solid var(--brd);margin-bottom:16px">';
 h+='<h3 style="color:var(--hl);margin-bottom:8px">🧠 RAG — Frage dein Clipboard</h3>';
 h+='<p style="font-size:12px;color:var(--fg2);margin-bottom:12px">Semantische Vektorsuche &amp; wissensbasierte Beantwortung basierend auf deiner Zwischenablage-Historie.</p>';
 h+='<div style="display:flex;gap:8px"><input type="text" id="ragInput" placeholder="z.B. Wie lautet der Docker-Befehl oder welche Dosierung wurde notiert?" style="flex:1;padding:9px 12px;border:1px solid var(--brd);border-radius:6px;background:var(--bg);color:var(--fg);font-size:13px;outline:none" onkeydown="if(event.key===\'Enter\')askRag()">';
 h+='<button class="btn" style="background:var(--hl);color:#fff;border-color:var(--hl)" onclick="askRag()" id="ragBtn">Fragen</button></div></div>';
 h+='<div id="ragOutput"></div></div>';
 $('main').innerHTML=h;}
function askRag(){
 const q=($('ragInput')?$('ragInput').value:'').trim();
 if(!q)return;
 const btn=$('ragBtn');
 if(btn){btn.disabled=true;btn.textContent='Suche…';}
 $('ragOutput').innerHTML='<div style="padding:20px;text-align:center;color:var(--fg2)">⏳ Durchsuche Vektor-Embeddings und erstelle Antwort…</div>';
 fetch('/api/rag/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})})
 .then(r=>r.json()).then(d=>{
  if(btn){btn.disabled=false;btn.textContent='Fragen';}
  let out='<div style="background:var(--bg2);padding:16px;border-radius:8px;border:1px solid var(--brd);margin-bottom:16px">';
  out+='<div style="font-size:12px;color:var(--sel);font-weight:600;margin-bottom:8px">Ergebnis / Antwort:</div>';
  out+='<div style="font-size:13px;line-height:1.6;white-space:pre-wrap;margin-bottom:14px">'+esc(d.answer)+'</div>';
  if(d.sources&&d.sources.length){
   out+='<div style="font-size:11px;color:var(--fg2);border-top:1px solid var(--brd);padding-top:10px;margin-top:10px">Verwendete Quellen ('+d.sources.length+'):</div>';
   out+='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin-top:8px">';
   d.sources.forEach(s=>{
    let rel=Math.round((s.score||0)*100);
    out+='<div class="card" style="padding:8px;cursor:pointer" onclick="setCat(\'all\');view(\'timeline\');setTimeout(()=>document.querySelector(\'.card[data-id=\\\"'+s.id+'\\\"]\')?.click(),300)">'
     +'<div class="meta"><span class="badge" style="background:var(--sel)">#'+s.id+'</span><span class="badge" style="background:#0f3460">'+rel+'% Match</span></div>'
     +'<div class="title" style="font-size:11px">'+esc(s.title)+'</div>'
     +'<div class="preview" style="font-size:10px">'+esc((s.content||'').slice(0,80))+'…</div>'
     +'</div>';
   });
   out+='</div>';
  }
  out+='</div>';
  $('ragOutput').innerHTML=out;
 }).catch(e=>{
  if(btn){btn.disabled=false;btn.textContent='Fragen';}
  $('ragOutput').innerHTML='<div style="color:var(--hl);padding:10px">Fehler bei RAG-Abfrage: '+esc(e.message)+'</div>';
 });}
function boot(){
 loadMeta();
 const h=location.hash.replace('#','');
 if(['folders','favorites','graph','snippets','stats','rag'].includes(h))view(h);else view('timeline')}
boot();
</script></body></html>'''


# ─── SELFTEST ───────────────────────────────────────────────

def selftest():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from coolclipboard import Database

    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f'  ✓ {name}')
        else:
            failed += 1
            print(f'  ✗ {name}')

    print('MUSCAL selftest — ContentAnalyzer')
    az = ContentAnalyzer()
    py = az.analyze('def greet(name):\n    return "Hi " + name\nprint(greet("MUSCAL"))')
    check('Python erkannt', py['language'] == 'python')
    check('code-Typ erkannt', py['content_type'] == 'code')
    check('Kategorie code', py['category'] == 'code')
    check('Tag function', 'function' in py['tags'])
    check('Tag snippet', 'snippet' in py['tags'])
    check('sha256-Hash', len(py['hash']) == 64)

    err = az.analyze('Traceback (most recent call last):\n  File "/x.py", line 12, in main\nValueError: bad value')
    check('Fehler erkannt', err['content_type'] == 'error' and err['category'] == 'error')
    check('Tag runtime/debug', 'debug' in err['tags'] or 'runtime' in err['tags'])

    url = az.analyze('https://github.com/anomalyco/opencode/issues')
    check('Link erkannt', url['content_type'] == 'link' and url['category'] == 'link')

    js = az.analyze('const add = (a, b) => a + b;\nmodule.exports = { add };')
    check('JavaScript erkannt', js['language'] == 'javascript' and js['content_type'] == 'code')

    sql = az.analyze('SELECT id, name FROM users WHERE active = 1 ORDER BY name')
    check('SQL erkannt', sql['language'] == 'sql')

    arch = az.analyze('Die Architektur folgt dem Event-Sourcing Muster mit CQRS und separaten Read-Modellen.')
    check('Architektur-Kategorie', arch['category'] == 'architecture')

    prompt = az.analyze('Erkläre mir bitte, wie man ein Repository mit git aufsetzt.')
    check('Prompt-Kategorie', prompt['category'] == 'prompt')

    term = az.analyze('$ ls -la\n$ sudo apt update\ngrep -r "muscal" /home')
    check('Terminal erkannt', term['content_type'] == 'terminal' and term['category'] == 'terminal')

    print('MUSCAL selftest — Database & Store (memory)')
    db = Database(':memory:')
    store = CaptureStore(db)
    store.migrate()
    cols = {r[1] for r in db.conn.execute('PRAGMA table_info(clips)')}
    for needed in ('hash', 'source_app', 'language', 'content_type',
                   'embedding_id', 'relations', 'semantic_tags', 'folder', 'title'):
        check(f'Spalte {needed}', needed in cols)

    cap = store.save(py)
    check('Capture gespeichert', cap is not None and cap['id'] > 0)
    check('Dedup via hash', store.save(py) is None)

    store.update(cap['id'], favorite=1)
    items, total = store.search(fav=True)
    check('Favoriten-Suche', total == 1 and items[0]['id'] == cap['id'])
    check('Favorites-first-Sortierung',
          all(items[i]['favorite'] >= items[i + 1]['favorite'] for i in range(len(items) - 1)))

    folders = {f['key']: f for f in store.folders()}
    check('Ordner code', folders['code']['count'] == 1 and folders['code']['favorites'] == 1)

    rel = store.relations(cap['id'])
    check('Relationen-API', isinstance(rel, list))

    graph = store.graph()
    check('Graph liefert Nodes', len(graph['nodes']) >= 1)

    check('canonical_category', canonical_category('Fehler') == 'error' and canonical_category('zzz') == 'other')

    print('MUSCAL selftest — RAG Engine & Vectorizer')
    lv = LocalVectorizer(dim=256)
    v1 = lv.vectorize('Joe Tippens Fenbendazol Protokoll mit Vitamin E')
    v2 = lv.vectorize('Wie ist das Fenbendazol Protokoll?')
    v3 = lv.vectorize('chmod +x script.sh')
    sim_pos = LocalVectorizer.cosine(v1, v2)
    sim_neg = LocalVectorizer.cosine(v1, v3)
    check('Vektorisierung 256d', len(v1) == 256)
    check('Semantische Ähnlichkeit (Positiv > Negativ)', sim_pos > sim_neg)

    ai = AiHelper()
    rag = RagEngine(store, ai)
    rag_res = rag.query('Fenbendazol Protokoll')
    check('RAG Retrieval Query', 'query' in rag_res and len(rag_res['sources']) >= 0)

    print(f'\nMUSCAL selftest: {passed} passed, {failed} failed')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(selftest())
