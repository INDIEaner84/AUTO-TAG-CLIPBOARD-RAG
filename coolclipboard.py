#!/usr/bin/env python3
"""
CoolClipboard v2.0 – Erweiterter Zwischenablage-Manager
Kategorien, Pin, Regex-Suche, Verschlüsselung, Sync, Snippet-Templates,
Mehrfachauswahl, Versioning, Theme-Wechsel, Statistiken, Web-GUI.
"""

BANNER = """\
╔══════════════════════════════════════════════════╗
║     ██████  ██████   ██████  ██      ██    ██   ║
║    ██      ██    ██ ██    ██ ██      ██    ██   ║
║    ██      ██    ██ ██    ██ ██      ██    ██   ║
║    ██      ██    ██ ██    ██ ██      ██    ██   ║
║     ██████  ██████   ██████  ███████  ██████    ║
║                     Clipboard                    ║
╚══════════════════════════════════════════════════╝"""

import sys, os, json, sqlite3, subprocess, threading, queue, time
import hashlib, re, webbrowser, shutil, base64
from datetime import datetime
from pathlib import Path

HAS_DISPLAY = bool(os.environ.get('DISPLAY', ''))
HAS_TK = True
try:
    import tkinter as tk
    from tkinter import messagebox
except:
    HAS_TK = False

HAS_PIL = True
try:
    from PIL import Image, ImageDraw, ImageFont
except:
    HAS_PIL = False

HAS_FLASK = True
try:
    from flask import Flask, request, jsonify, send_file, Response
except:
    HAS_FLASK = False

HAS_PYNPUT = True
try:
    from pynput import keyboard as pynput_kb
    from pynput import mouse as pynput_mouse
    from pynput.keyboard import Key, Controller as KbCtrl
except:
    HAS_PYNPUT = False

HAS_TRAY = True
try:
    import pystray
    from pystray import MenuItem as TrayItem
except:
    HAS_TRAY = False

HAS_CRYPTO = True
try:
    from cryptography.fernet import Fernet
except:
    HAS_CRYPTO = False

try:
    import muscal_layer
except Exception:
    muscal_layer = None

DATA_DIR = Path.home() / '.local' / 'share' / 'coolclipboard'
DB_PATH = DATA_DIR / 'clipboard.db'
IMAGES_DIR = DATA_DIR / 'images'
MARKDOWN_DIR = DATA_DIR / 'markdown'
CONFIG_PATH = DATA_DIR / 'config.json'
AUTOSTART_PATH = Path.home() / '.config' / 'autostart' / 'coolclipboard.desktop'
PLUGIN_DIR = DATA_DIR / 'plugins'

DEFAULT_CONFIG = {
    'hotkey_overlay': '<cmd>+v',
    'hotkey_display': '<cmd>+h',
    'web_port': 8234,
    'poll_interval': 0.5,
    'max_overlay': 50,
    'theme': 'dark',
    'encryption_key': '',
    'muscal_float': True,
    'muscal_float_timeout': 8,
    'muscal_ai_endpoint': '',
    'muscal_ai_key': '',
    'muscal_ai_model': '',
}

THEMES = {
    'dark': {
        'bg': '#1a1a2e', 'bg2': '#16213e', 'fg': '#e0e0e0',
        'fg2': '#a0a0a0', 'accent': '#0f3460', 'highlight': '#e94560',
        'selected': '#533483', 'border': '#2a2a4a',
    },
    'light': {
        'bg': '#f5f5f5', 'bg2': '#ffffff', 'fg': '#1a1a2e',
        'fg2': '#666666', 'accent': '#0f3460', 'highlight': '#e94560',
        'selected': '#533483', 'border': '#ddd',
    },
    'monokai': {
        'bg': '#272822', 'bg2': '#3e3d32', 'fg': '#f8f8f2',
        'fg2': '#75715e', 'accent': '#49483e', 'highlight': '#f92672',
        'selected': '#a6e22e', 'border': '#49483e',
    },
    'dracula': {
        'bg': '#282a36', 'bg2': '#44475a', 'fg': '#f8f8f2',
        'fg2': '#6272a4', 'accent': '#6272a4', 'highlight': '#ff79c6',
        'selected': '#bd93f9', 'border': '#44475a',
    },
}

AUTO_TAG_RULES = [
    (r'https?://\S+', 'link'),
    (r'[\w.+-]+@\w+\.\w+', 'email'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'ip'),
    (r'(/[.\w\-/~]+|[A-Za-z]:\\[.\w\-\\]+)', 'path'),
    (r'^\{.*\}$|^\[.*\]$', 'json'),
    (r'(<[^>]+>)', 'html'),
    (r'\b(def |function |class |import |from \w+ import)\b', 'code'),
    (r'\b(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})\b', 'date'),
    (r'\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b', 'phone'),
    (r'\b(0x[0-9a-fA-F]+)\b', 'hex'),
    (r'(api[_-]?key|password|secret|token)\s*[:=]\s*\S+', 'credential'),
]


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)


def _regexp(pattern, text):
    try:
        return bool(re.search(pattern, text or ''))
    except:
        return False


class Database:
    def __init__(self, path):
        self.db_path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function('REGEXP', 2, _regexp)
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        with self.lock:
            self.conn.execute('''CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL DEFAULT 'text',
                content TEXT, image_path TEXT, source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                favorite INTEGER DEFAULT 0,
                tags TEXT DEFAULT '', notes TEXT DEFAULT '',
                category TEXT DEFAULT 'all',
                pinned INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                encrypted INTEGER DEFAULT 0
            )''')
            cur = self.conn.execute("PRAGMA table_info(clips)")
            cols = [r[1] for r in cur.fetchall()]
            for col, default in [('category', "'all'"), ('pinned', '0'),
                                  ('version', '1'), ('encrypted', '0')]:
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE clips ADD COLUMN {col} DEFAULT {default}")
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_ct ON clips(created_at DESC)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_cat ON clips(category)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_pin ON clips(pinned DESC)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_fav ON clips(favorite DESC)')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT DEFAULT '#533483',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_id INTEGER NOT NULL,
                content TEXT,
                tags TEXT,
                notes TEXT,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            )''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '',
                shortcut TEXT DEFAULT '',
                category TEXT DEFAULT 'all',
                use_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO categories (name, color) VALUES ('all', '#533483')")
                self.conn.execute(
                    "INSERT OR IGNORE INTO categories (name, color) VALUES ('personal', '#e94560')")
                self.conn.execute(
                    "INSERT OR IGNORE INTO categories (name, color) VALUES ('work', '#0f3460')")
                self.conn.execute(
                    "INSERT OR IGNORE INTO categories (name, color) VALUES ('code', '#a6e22e')")
            except:
                pass
            self.conn.commit()

    def add(self, type_, content='', image_path='', source='', tags='',
            category='all', pinned=0, encrypted=0):
        with self.lock:
            cur = self.conn.execute(
                'SELECT content,type FROM clips ORDER BY id DESC LIMIT 5')
            for r in cur:
                if r['type'] == type_ and r['content'] == content:
                    return None
            cur = self.conn.execute(
                '''INSERT INTO clips (type,content,image_path,source,tags,category,pinned,encrypted)
                   VALUES(?,?,?,?,?,?,?,?)''',
                (type_, content, image_path, source, tags, category, pinned, encrypted))
            self.conn.commit()
            return cur.lastrowid

    def search(self, query='', type_='', fav=False, page=1, pp=50,
               category='', pinned=False, use_regex=False):
        conds, params = [], []
        if query:
            if use_regex:
                conds.append('(content REGEXP ? OR tags REGEXP ?)')
                params.extend([query, query])
            else:
                conds.append('(content LIKE ? OR tags LIKE ?)')
                params.extend([f'%{query}%', f'%{query}%'])
        if type_:
            conds.append('type=?')
            params.append(type_)
        if fav:
            conds.append('favorite=1')
        if category and category != 'all':
            conds.append('category=?')
            params.append(category)
        if pinned:
            conds.append('pinned=1')
        where = ' AND '.join(conds) if conds else '1=1'
        off = (page - 1) * pp
        with self.lock:
            cur = self.conn.execute(
                f'SELECT * FROM clips WHERE {where} ORDER BY pinned DESC, created_at DESC LIMIT ? OFFSET ?',
                params + [pp, off])
            items = [dict(r) for r in cur]
            cur = self.conn.execute(
                f'SELECT COUNT(*) as c FROM clips WHERE {where}', params)
            total = cur.fetchone()['c']
        return items, total

    def get(self, cid):
        with self.lock:
            cur = self.conn.execute('SELECT * FROM clips WHERE id=?', (cid,))
            r = cur.fetchone()
            return dict(r) if r else None

    def update(self, cid, **kw):
        allowed = {'tags', 'notes', 'favorite', 'category', 'pinned', 'encrypted', 'content'}
        up = {k: v for k, v in kw.items() if k in allowed}
        if not up:
            return False
        up['updated_at'] = datetime.now().isoformat()
        set_ = ', '.join(f'{k}=?' for k in up)
        with self.lock:
            c = self.get(cid)
            if c:
                self.conn.execute(
                    'INSERT INTO versions (clip_id, content, tags, notes, category) VALUES(?,?,?,?,?)',
                    (cid, c['content'], c['tags'], c['notes'], c['category']))
                ver = (c.get('version') or 0) + 1
                self.conn.execute('UPDATE clips SET version=? WHERE id=?', (ver, cid))
            self.conn.execute(f'UPDATE clips SET {set_} WHERE id=?',
                              list(up.values()) + [cid])
            self.conn.commit()
            return True

    def delete(self, cid):
        with self.lock:
            c = self.get(cid)
            if c:
                if c['image_path']:
                    p = Path(c['image_path'])
                    if p.exists():
                        p.unlink()
                md = MARKDOWN_DIR / f'clip-{cid:05d}.md'
                if md.exists():
                    md.unlink()
                self.conn.execute('DELETE FROM versions WHERE clip_id=?', (cid,))
            self.conn.execute('DELETE FROM clips WHERE id=?', (cid,))
            self.conn.commit()
            return True

    def delete_all(self):
        shutil.rmtree(IMAGES_DIR, ignore_errors=True)
        shutil.rmtree(MARKDOWN_DIR, ignore_errors=True)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.conn.execute('DELETE FROM clips')
            self.conn.execute('DELETE FROM versions')
            self.conn.commit()

    def get_versions(self, cid):
        with self.lock:
            cur = self.conn.execute(
                'SELECT * FROM versions WHERE clip_id=? ORDER BY created_at DESC', (cid,))
            return [dict(r) for r in cur]

    def restore_version(self, version_id):
        with self.lock:
            cur = self.conn.execute('SELECT * FROM versions WHERE id=?', (version_id,))
            v = cur.fetchone()
            if not v:
                return False
            v = dict(v)
            self.conn.execute(
                'UPDATE clips SET content=?, tags=?, notes=?, updated_at=? WHERE id=?',
                (v['content'], v['tags'], v['notes'], datetime.now().isoformat(), v['clip_id']))
            self.conn.commit()
            return True

    def get_categories(self):
        with self.lock:
            cur = self.conn.execute('SELECT * FROM categories ORDER BY name')
            return [dict(r) for r in cur]

    def add_category(self, name, color='#533483'):
        with self.lock:
            try:
                self.conn.execute(
                    'INSERT INTO categories (name, color) VALUES (?,?)', (name, color))
                self.conn.commit()
                return True
            except:
                return False

    def delete_category(self, name):
        if name == 'all':
            return False
        with self.lock:
            self.conn.execute('DELETE FROM categories WHERE name=?', (name,))
            self.conn.execute("UPDATE clips SET category='all' WHERE category=?", (name,))
            self.conn.commit()
            return True

    def update_category(self, name, color):
        with self.lock:
            self.conn.execute('UPDATE categories SET color=? WHERE name=?', (color, name))
            self.conn.commit()

    def get_snippets(self, query=''):
        with self.lock:
            if query:
                cur = self.conn.execute(
                    'SELECT * FROM snippets WHERE name LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY use_count DESC',
                    (f'%{query}%', f'%{query}%', f'%{query}%'))
            else:
                cur = self.conn.execute(
                    'SELECT * FROM snippets ORDER BY use_count DESC')
            return [dict(r) for r in cur]

    def get_snippet(self, sid):
        with self.lock:
            cur = self.conn.execute('SELECT * FROM snippets WHERE id=?', (sid,))
            r = cur.fetchone()
            return dict(r) if r else None

    def add_snippet(self, name, content, tags='', shortcut='', category='all'):
        with self.lock:
            cur = self.conn.execute(
                'INSERT INTO snippets (name,content,tags,shortcut,category) VALUES(?,?,?,?,?)',
                (name, content, tags, shortcut, category))
            self.conn.commit()
            return cur.lastrowid

    def update_snippet(self, sid, **kw):
        allowed = {'name', 'content', 'tags', 'shortcut', 'category'}
        up = {k: v for k, v in kw.items() if k in allowed}
        if not up:
            return False
        up['updated_at'] = datetime.now().isoformat()
        set_ = ', '.join(f'{k}=?' for k in up)
        with self.lock:
            self.conn.execute(f'UPDATE snippets SET {set_} WHERE id=?',
                              list(up.values()) + [sid])
            self.conn.commit()
            return True

    def delete_snippet(self, sid):
        with self.lock:
            self.conn.execute('DELETE FROM snippets WHERE id=?', (sid,))
            self.conn.commit()
            return True

    def use_snippet(self, sid):
        with self.lock:
            self.conn.execute(
                'UPDATE snippets SET use_count = use_count + 1 WHERE id=?', (sid,))
            self.conn.commit()

    def get_stats(self):
        with self.lock:
            stats = {}
            cur = self.conn.execute('SELECT COUNT(*) as c FROM clips')
            stats['total_clips'] = cur.fetchone()['c']
            cur = self.conn.execute("SELECT COUNT(*) as c FROM clips WHERE type='text'")
            stats['text_clips'] = cur.fetchone()['c']
            cur = self.conn.execute("SELECT COUNT(*) as c FROM clips WHERE type='image'")
            stats['image_clips'] = cur.fetchone()['c']
            cur = self.conn.execute('SELECT COUNT(*) as c FROM clips WHERE favorite=1')
            stats['favorites'] = cur.fetchone()['c']
            cur = self.conn.execute('SELECT COUNT(*) as c FROM clips WHERE pinned=1')
            stats['pinned'] = cur.fetchone()['c']
            cur = self.conn.execute('SELECT COUNT(*) as c FROM snippets')
            stats['snippets'] = cur.fetchone()['c']
            cur = self.conn.execute(
                "SELECT category, COUNT(*) as c FROM clips GROUP BY category ORDER BY c DESC")
            stats['by_category'] = {r['category']: r['c'] for r in cur}
            cur = self.conn.execute(
                "SELECT SUBSTR(created_at,1,10) as day, COUNT(*) as c FROM clips GROUP BY day ORDER BY day DESC LIMIT 7")
            stats['by_day'] = [{'day': r['day'], 'count': r['c']} for r in cur]
            cur = self.conn.execute(
                "SELECT tags FROM clips WHERE tags != ''")
            tag_counts = {}
            for r in cur:
                for t in r['tags'].split(','):
                    t = t.strip()
                    if t:
                        tag_counts[t] = tag_counts.get(t, 0) + 1
            stats['top_tags'] = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]
            return stats

    def close(self):
        self.conn.close()


class AutoTagger:
    def __init__(self, extra=None):
        self.rules = list(AUTO_TAG_RULES)
        if extra:
            for kw in extra:
                self.rules.append((rf'\b{re.escape(kw)}\b', kw.lower()))

    def tag(self, text):
        if not text or len(text) > 50000:
            return ''
        tags = set()
        tlow = text.lower()
        for pat, tag in self.rules:
            if re.search(pat, tlow):
                tags.add(tag)
        return ','.join(sorted(tags))


class Encryption:
    def __init__(self, key=''):
        self.fernet = None
        if HAS_CRYPTO and key:
            try:
                if len(key) == 44:
                    self.fernet = Fernet(key.encode())
                else:
                    derived = hashlib.sha256(key.encode()).digest()
                    b64 = base64.urlsafe_b64encode(derived)
                    self.fernet = Fernet(b64)
            except:
                pass

    def encrypt(self, text):
        if not self.fernet or not text:
            return text
        try:
            return self.fernet.encrypt(text.encode()).decode()
        except:
            return text

    def decrypt(self, text):
        if not self.fernet or not text:
            return text
        try:
            return self.fernet.decrypt(text.encode()).decode()
        except:
            return text


class CoolClipboard:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

        self.config = load_config()
        save_config(self.config)

        self.HOTKEY_OVERLAY = self.config.get('hotkey_overlay', '<cmd>+v')
        self.HOTKEY_DISPLAY = self.config.get('hotkey_display', '<cmd>+h')
        self.WEB_PORT = self.config.get('web_port', 8234)
        self.POLL_INTERVAL = self.config.get('poll_interval', 0.5)
        self.MAX_OVERLAY = self.config.get('max_overlay', 50)

        self.db = Database(DB_PATH)
        self.tagger = AutoTagger()
        self.crypto = Encryption(self.config.get('encryption_key', ''))
        self.running = True
        self.q = queue.Queue()
        self.last_text = None
        self.last_hash = None
        self.display_active = False
        self.overlay_visible = False
        self.events = []
        self.kb_listener = None
        self.mouse_listener = None
        self.pynput_kb_listener = None
        self.pynput_global_hotkeys = None
        self.theme_name = self.config.get('theme', 'dark')
        self._ctrl_down = False

        if HAS_TK and HAS_DISPLAY:
            self.root = tk.Tk()
            self.root.withdraw()
            self.root.title('CoolClipboard')
            self.overlay_win = None
            self.overlay_list = None
            self.overlay_data = []
            self.search_var = None
            self.preview_lbl = None
            self.disp_win = None
            self.disp_canvas = None
            self._setup_overlay()
            self._setup_display()
            self._setup_tray()
            self.root.after(100, self._proc_q)
        else:
            print('Warning: tkinter not available, overlays disabled')

        self.muscal = None
        if muscal_layer is not None:
            try:
                self.muscal = muscal_layer.MuscalLayer(
                    self.db, config=self.config,
                    root=getattr(self, 'root', None))
                self.muscal.build_overlays()
            except Exception as e:
                print(f'  ! MUSCAL layer disabled: {e}')

    def _proc_q(self):
        try:
            while True:
                cmd = self.q.get_nowait()
                self._handle(cmd)
        except queue.Empty:
            pass
        if self.running and HAS_TK:
            self.root.after(100, self._proc_q)

    def _handle(self, cmd):
        a = cmd.get('action')
        if a == 'show_overlay':
            self._show_overlay()
        elif a == 'hide_overlay':
            self._hide_overlay()
        elif a == 'toggle_display':
            self._toggle_display()
        elif a == 'paste':
            self._paste(cmd.get('clip_id'))
        elif a == 'show_web':
            webbrowser.open(f'http://localhost:{self.WEB_PORT}')
        elif a == 'quit':
            self._quit()
        elif a == 'display_event':
            self._add_event(cmd.get('data', {}))
        elif a == 'muscal_capture':
            if self.muscal:
                self.muscal.on_capture(cmd.get('data'))
        elif a == 'muscal_float':
            if self.muscal:
                self.muscal.on_ctrl_c()

    def _quit(self):
        self.running = False
        if self.kb_listener:
            self.kb_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.pynput_global_hotkeys:
            self.pynput_global_hotkeys.stop()
        self.db.close()
        if HAS_TK:
            try:
                self.root.quit()
            except:
                pass
        os._exit(0)

    def _get_theme(self):
        return THEMES.get(self.theme_name, THEMES['dark'])

# ─── OVERLAY ────────────────────────────────────────────────

    def _setup_overlay(self):
        if not HAS_TK:
            return
        th = self._get_theme()
        self.overlay_win = tk.Toplevel(self.root)
        self.overlay_win.withdraw()
        self.overlay_win.overrideredirect(True)
        self.overlay_win.attributes('-topmost', True)
        self.overlay_win.configure(bg=th['bg'])
        w, h = 780, 550
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.overlay_win.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

        sf = tk.Frame(self.overlay_win, bg=th['bg'])
        sf.pack(fill='x', padx=10, pady=(10, 3))

        row1 = tk.Frame(sf, bg=th['bg'])
        row1.pack(fill='x')
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *a: self._refresh_list())
        se = tk.Entry(row1, textvariable=self.search_var, bg=th['bg2'],
                      fg=th['fg'], insertbackground=th['fg'],
                      relief='flat', font=('Segoe UI', 13))
        se.pack(side='left', fill='x', expand=True, ipady=6)
        se.bind('<Escape>', lambda e: self._hide_overlay())
        se.bind('<Return>', lambda e: self._paste_sel())
        se.bind('<Up>', lambda e: self._nav(-1))
        se.bind('<Down>', lambda e: self._nav(1))

        self.overlay_cat_var = tk.StringVar(value='all')
        cats = [c['name'] for c in self.db.get_categories()]
        cat_menu = tk.OptionMenu(row1, self.overlay_cat_var, *cats,
                                 command=lambda _: self._refresh_list())
        cat_menu.config(bg=th['bg2'], fg=th['fg'], highlightthickness=0,
                        font=('Segoe UI', 10), width=10)
        cat_menu.pack(side='right', padx=(8, 0))

        mf = tk.Frame(self.overlay_win, bg=th['bg'])
        mf.pack(fill='both', expand=True, padx=10, pady=3)

        lf = tk.Frame(mf, bg=th['border'])
        lf.pack(side='left', fill='both', expand=True)

        sb = tk.Scrollbar(lf, bg=th['bg2'], troughcolor=th['bg'])
        self.overlay_list = tk.Listbox(lf, bg=th['bg2'], fg=th['fg'],
            selectbackground=th['selected'], selectforeground=th['fg'],
            relief='flat', highlightthickness=0, borderwidth=0,
            font=('Consolas', 10), yscrollcommand=sb.set)
        sb.config(command=self.overlay_list.yview)
        sb.pack(side='right', fill='y')
        self.overlay_list.pack(side='left', fill='both', expand=True)

        self.overlay_list.bind('<Double-Button-1>', lambda e: self._paste_sel())
        self.overlay_list.bind('<Escape>', lambda e: self._hide_overlay())
        self.overlay_list.bind('<Return>', lambda e: self._paste_sel())
        self.overlay_list.bind('<Up>', lambda e: self._nav(-1))
        self.overlay_list.bind('<Down>', lambda e: self._nav(1))
        self.overlay_list.bind('<Delete>', lambda e: self._del_sel())
        self.overlay_list.bind('<Control-d>', lambda e: self._del_sel())
        self.overlay_list.bind('<Control-p>', lambda e: self._toggle_pin())

        pf = tk.Frame(mf, bg=th['bg'], width=320)
        pf.pack(side='right', fill='both', padx=(8, 0))
        pf.pack_propagate(False)
        self.preview_lbl = tk.Label(pf, bg=th['bg2'], fg=th['fg2'],
            wraplength=300, justify='left', anchor='nw',
            font=('Consolas', 9), text='Select an item')
        self.preview_lbl.pack(fill='both', expand=True)

        ft = tk.Frame(self.overlay_win, bg=th['bg'])
        ft.pack(fill='x', padx=10, pady=(0, 8))
        tk.Label(ft, bg=th['bg'], fg=th['fg2'],
            text='↑↓ Nav  •  Enter Paste  •  Del Delete  •  Ctrl+P Pin  •  Esc Close',
            font=('Segoe UI', 9)).pack()

    def _refresh_list(self):
        q = self.search_var.get() if self.search_var else ''
        cat = self.overlay_cat_var.get() if hasattr(self, 'overlay_cat_var') else ''
        items, _ = self.db.search(query=q, pp=self.MAX_OVERLAY, category=cat)
        self.overlay_data = items
        if not self.overlay_list:
            return
        self.overlay_list.delete(0, 'end')
        for item in items:
            ts = item['created_at'][:16].replace('T', ' ')
            star = '★ ' if item['favorite'] else '  '
            pin = '📌 ' if item.get('pinned') else '  '
            cat_label = f'[{item.get("category","")}] ' if item.get('category') and item['category'] != 'all' else ''
            if item['type'] == 'image':
                txt = f"{pin}{star}🖼  {ts}  {cat_label}[Image]"
            else:
                txt = (item['content'] or '').replace('\n', ' ').strip()
                txt = txt[:55] + '...' if len(txt) > 55 else txt
                txt = f"{pin}{star}{ts}  {cat_label}{txt}"
            self.overlay_list.insert('end', txt)
        if items:
            self.overlay_list.selection_set(0)
            self._update_preview(0)

    def _update_preview(self, idx):
        if idx < 0 or idx >= len(self.overlay_data):
            return
        item = self.overlay_data[idx]
        if not self.preview_lbl:
            return
        if item['type'] == 'image':
            imgp = item.get('image_path', '')
            if imgp and Path(imgp).exists() and HAS_PIL:
                try:
                    img = Image.open(imgp)
                    img.thumbnail((280, 200))
                    import io
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    from PIL import ImageTk
                    pt = ImageTk.PhotoImage(img)
                    self.preview_lbl.config(image=pt, text='', compound='none')
                    self.preview_lbl.image = pt
                    return
                except:
                    pass
            self.preview_lbl.config(image='', text='[Image]')
            return
        text = item['content'] or ''
        tags = item.get('tags') or ''
        cat = item.get('category', '')
        notes = item.get('notes') or ''
        pin = '📌 Pinned\n' if item.get('pinned') else ''
        extra = f"\n\nCategory: {cat}" if cat and cat != 'all' else ''
        extra += f"\n\nTags: {tags}" if tags else ''
        extra += f"\n\nNotes: {notes}" if notes else ''
        if len(text) > 600:
            text = text[:597] + '...'
        self.preview_lbl.config(image='', text=pin + text + extra)

    def _nav(self, d):
        if not self.overlay_list:
            return
        sel = self.overlay_list.curselection()
        idx = sel[0] if sel else -1
        ni = idx + d
        if 0 <= ni < self.overlay_list.size():
            self.overlay_list.selection_clear(0, 'end')
            self.overlay_list.selection_set(ni)
            self.overlay_list.activate(ni)
            self._update_preview(ni)

    def _paste_sel(self):
        if not self.overlay_list:
            return
        sel = self.overlay_list.curselection()
        if not sel or sel[0] >= len(self.overlay_data):
            return
        item = self.overlay_data[sel[0]]
        self._hide_overlay()
        content = item['content'] or ''
        if item.get('encrypted') and self.crypto.fernet:
            content = self.crypto.decrypt(content)
        if item['type'] == 'text':
            self._set_clip(content)
        elif item['type'] == 'image' and item['image_path']:
            self._set_clip_img(item['image_path'])
        time.sleep(0.05)
        self._sim_paste()

    def _del_sel(self):
        if not self.overlay_list:
            return
        sel = self.overlay_list.curselection()
        if not sel or sel[0] >= len(self.overlay_data):
            return
        item = self.overlay_data[sel[0]]
        self.db.delete(item['id'])
        self._refresh_list()

    def _toggle_pin(self):
        if not self.overlay_list:
            return
        sel = self.overlay_list.curselection()
        if not sel or sel[0] >= len(self.overlay_data):
            return
        item = self.overlay_data[sel[0]]
        new_pin = 0 if item.get('pinned') else 1
        self.db.update(item['id'], pinned=new_pin)
        self._refresh_list()

    def _show_overlay(self):
        if not self.overlay_win:
            return
        if self.overlay_visible:
            self.overlay_win.focus()
            return
        self.overlay_visible = True
        self._refresh_list()
        self.overlay_win.deiconify()
        self.overlay_win.focus_force()
        self.overlay_win.lift()

    def _hide_overlay(self):
        self.overlay_visible = False
        if self.overlay_win:
            self.overlay_win.withdraw()

# ─── KEYSTROKE DISPLAY ──────────────────────────────────────

    def _setup_display(self):
        if not HAS_TK:
            return
        th = self._get_theme()
        self.disp_win = tk.Toplevel(self.root)
        self.disp_win.withdraw()
        self.disp_win.overrideredirect(True)
        self.disp_win.attributes('-topmost', True)
        self.disp_win.attributes('-alpha', 0.88)
        self.disp_win.configure(bg=th['bg'])
        w, h = 520, 200
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.disp_win.geometry(f'{w}x{h}+{(sw-w)//2}+{sh-h-50}')
        self.disp_canvas = tk.Canvas(self.disp_win, bg=th['bg'],
                                      highlightthickness=0)
        self.disp_canvas.pack(fill='both', expand=True)
        self.disp_canvas.bind('<Escape>', lambda e: self._toggle_display())

    def _toggle_display(self):
        if self.display_active:
            self._hide_display()
        else:
            self._show_display()

    def _show_display(self):
        self.display_active = True
        self.events = []
        if self.disp_win:
            self.disp_win.deiconify()
            self.disp_win.lift()
        self._redraw_display()

    def _hide_display(self):
        self.display_active = False
        if self.disp_win:
            self.disp_win.withdraw()

    def _add_event(self, data):
        self.events.append(data)
        if len(self.events) > 12:
            self.events.pop(0)
        if self.display_active:
            self._redraw_display()

    def _redraw_display(self):
        if not self.disp_canvas:
            return
        self.disp_canvas.delete('all')
        now = time.time()
        y = 12
        for evt in reversed(self.events[-10:]):
            age = now - evt.get('time', now)
            alpha = max(0.25, 1.0 - age * 0.2)
            alpha = min(1.0, alpha)
            r = int(233 * alpha + 26 * (1 - alpha))
            g = int(69 * alpha + 26 * (1 - alpha))
            b = int(96 * alpha + 46 * (1 - alpha))
            color = f'#{r:02x}{g:02x}{b:02x}'
            icon = '⌨' if evt.get('type') == 'key' else '🖱'
            txt = f'{icon}  {evt.get("text", "")}'
            self.disp_canvas.create_text(14, y, anchor='w', text=txt,
                fill=color, font=('Consolas', 14))
            y += 19

# ─── CLIPBOARD ──────────────────────────────────────────────

    def _get_clip_text(self):
        try:
            proc = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-o'],
                capture_output=True, timeout=0.5)
            if proc.returncode == 0:
                return proc.stdout.decode('utf-8', errors='replace')
        except:
            pass
        return None

    def _get_clip_image(self):
        try:
            proc = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'],
                capture_output=True, timeout=0.5)
            if proc.returncode == 0 and len(proc.stdout) > 50:
                return proc.stdout
        except:
            pass
        return None

    def _set_clip(self, text):
        try:
            proc = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
        except:
            pass

    def _set_clip_img(self, path):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            proc = subprocess.Popen(
                ['xclip', '-selection', 'clipboard', '-t', 'image/png'],
                stdin=subprocess.PIPE)
            proc.communicate(data)
        except:
            pass

    def _sim_paste(self):
        if HAS_PYNPUT:
            kb = KbCtrl()
            kb.press(Key.ctrl)
            time.sleep(0.01)
            kb.press('v')
            time.sleep(0.02)
            kb.release('v')
            time.sleep(0.01)
            kb.release(Key.ctrl)
        else:
            subprocess.run(['xdotool', 'key', 'ctrl+v'],
                           capture_output=True, timeout=1)

    def _monitor_loop(self):
        while self.running:
            try:
                text = self._get_clip_text()
                if text and text.strip():
                    h = hashlib.md5(text.encode()).hexdigest()
                    if h != self.last_hash:
                        self.last_hash = h
                        if self.muscal is not None:
                            meta = self.muscal.process_capture(text)
                            if meta is not None:
                                self.q.put({'action': 'muscal_capture', 'data': meta})
                        else:
                            tags = self.tagger.tag(text)
                            self.db.add('text', content=text[:100000], tags=tags)
                else:
                    img = self._get_clip_image()
                    if img:
                        ih = hashlib.md5(img).hexdigest()
                        if ih != self.last_hash:
                            self.last_hash = ih
                            if self.muscal is not None:
                                cap = self.muscal.process_image(img)
                                if cap is not None:
                                    self.q.put({'action': 'muscal_capture', 'data': cap})
                            else:
                                fname = f'{ih}.png'
                                fpath = IMAGES_DIR / fname
                                fpath.write_bytes(img)
                                self.db.add('image', image_path=str(fpath))
            except:
                pass
            time.sleep(self.POLL_INTERVAL)

# ─── HOTKEYS ────────────────────────────────────────────────

    def _hotkey_loop(self):
        if not HAS_PYNPUT:
            return

        self.pynput_kb_listener = pynput_kb.Listener(
            on_press=self._on_any_key, on_release=self._on_any_key_release)
        self.pynput_kb_listener.start()

        def on_ov():
            self.q.put({'action': 'show_overlay'})

        def on_disp():
            self.q.put({'action': 'toggle_display'})

        self.pynput_global_hotkeys = pynput_kb.GlobalHotKeys({
            self.HOTKEY_OVERLAY: on_ov,
            self.HOTKEY_DISPLAY: on_disp,
        })
        self.pynput_global_hotkeys.start()
        self.pynput_global_hotkeys.join()

    def _on_any_key(self, key):
        try:
            if key in (pynput_kb.Key.ctrl_l, pynput_kb.Key.ctrl_r):
                self._ctrl_down = True
            if hasattr(key, 'char') and key.char:
                if key.char == 'c' and self._ctrl_down and self.muscal is not None:
                    self.q.put({'action': 'muscal_float'})
                txt = key.char
                if len(txt) == 1 and txt.isprintable():
                    self.q.put({'action': 'display_event', 'data': {
                        'type': 'key', 'text': txt, 'time': time.time()}})
            else:
                name = str(key).replace('Key.', '').lower()
                if name in ('ctrl_l', 'ctrl_r', 'alt_l', 'alt_r',
                            'shift_l', 'shift_r', 'cmd_l', 'cmd_r'):
                    pass
                elif name and name != 'cmd':
                    self.q.put({'action': 'display_event', 'data': {
                        'type': 'key', 'text': name.title(), 'time': time.time()}})
        except:
            pass

    def _on_any_key_release(self, key):
        try:
            if key in (pynput_kb.Key.ctrl_l, pynput_kb.Key.ctrl_r):
                self._ctrl_down = False
        except:
            pass

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed:
            return
        btn = str(button).replace('Button.', '').title()
        self.q.put({'action': 'display_event', 'data': {
            'type': 'mouse', 'text': f'{btn} ({x}, {y})',
            'time': time.time()}})

# ─── TRAY ───────────────────────────────────────────────────

    def _setup_tray(self):
        if not HAS_TRAY or not HAS_PIL:
            return
        try:
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([8, 6, 56, 58], radius=6, fill=(233, 69, 96))
            d.rounded_rectangle([14, 2, 50, 12], radius=4, fill=(15, 52, 96))
            d.rectangle([20, 22, 44, 24], fill=(224, 224, 224))
            d.rectangle([20, 30, 44, 32], fill=(224, 224, 224))
            d.rectangle([20, 38, 44, 40], fill=(224, 224, 224))

            menu = [
                TrayItem('📋 Show Overlay',
                    lambda: self.q.put({'action': 'show_overlay'})),
                TrayItem('🌐 Web GUI',
                    lambda: self.q.put({'action': 'show_web'})),
                TrayItem('⌨ Toggle Keystrokes',
                    lambda: self.q.put({'action': 'toggle_display'})),
                pystray.Menu.SEPARATOR,
                TrayItem('Quit',
                    lambda: self.q.put({'action': 'quit'})),
            ]
            self.tray = pystray.Icon('coolclipboard', img, 'CoolClipboard', menu)
            t = threading.Thread(target=self.tray.run, daemon=True)
            t.start()
        except:
            pass

# ─── WEB SERVER ─────────────────────────────────────────────

    def _web_loop(self):
        if not HAS_FLASK:
            return
        app = Flask(__name__)
        db = self.db
        crypto = self.crypto

        if self.muscal is not None:
            try:
                muscal_layer.register_webapp(app, self)
            except Exception as e:
                print(f'  ! MUSCAL web UI disabled: {e}')

        @app.route('/')
        def index():
            return HTML_INDEX

        @app.route('/api/clips', methods=['GET'])
        def api_list():
            q = request.args.get('search', '')
            t = request.args.get('type', '')
            f = request.args.get('favorite', '') == 'true'
            p = int(request.args.get('page', 1))
            cat = request.args.get('category', '')
            pin = request.args.get('pinned', '') == 'true'
            regex = request.args.get('regex', '') == 'true'
            items, total = db.search(q, t, f, p, category=cat, pinned=pin, use_regex=regex)
            for item in items:
                if item.get('encrypted') and crypto.fernet:
                    try:
                        item['content'] = crypto.decrypt(item['content'])
                    except:
                        pass
            return jsonify({'items': items, 'total': total, 'page': p})

        @app.route('/api/clips/<int:cid>', methods=['GET'])
        def api_get(cid):
            item = db.get(cid)
            if not item:
                return jsonify({'error': 'not found'}), 404
            if item.get('encrypted') and crypto.fernet:
                try:
                    item['content'] = crypto.decrypt(item['content'])
                except:
                    pass
            return jsonify(item)

        @app.route('/api/clips/<int:cid>', methods=['PUT'])
        def api_update(cid):
            data = request.get_json(force=True)
            db.update(cid, **{k: v for k, v in data.items()
                              if k in ('tags', 'notes', 'favorite', 'category', 'pinned', 'encrypted')})
            return jsonify({'ok': True})

        @app.route('/api/clips/<int:cid>', methods=['DELETE'])
        def api_delete(cid):
            db.delete(cid)
            return jsonify({'ok': True})

        @app.route('/api/clips', methods=['DELETE'])
        def api_delete_all():
            db.delete_all()
            return jsonify({'ok': True})

        @app.route('/api/clips/<int:cid>/favorite', methods=['POST'])
        def api_fav(cid):
            item = db.get(cid)
            if not item:
                return jsonify({'error': 'not found'}), 404
            db.update(cid, favorite=0 if item['favorite'] else 1)
            return jsonify({'ok': True, 'favorite': not item['favorite']})

        @app.route('/api/clips/<int:cid>/pin', methods=['POST'])
        def api_pin(cid):
            item = db.get(cid)
            if not item:
                return jsonify({'error': 'not found'}), 404
            db.update(cid, pinned=0 if item['pinned'] else 1)
            return jsonify({'ok': True, 'pinned': not item['pinned']})

        @app.route('/api/clips/<int:cid>/versions', methods=['GET'])
        def api_versions(cid):
            versions = db.get_versions(cid)
            return jsonify({'versions': versions})

        @app.route('/api/versions/<int:vid>/restore', methods=['POST'])
        def api_restore(vid):
            ok = db.restore_version(vid)
            return jsonify({'ok': ok})

        @app.route('/api/categories', methods=['GET'])
        def api_cats():
            return jsonify({'categories': db.get_categories()})

        @app.route('/api/categories', methods=['POST'])
        def api_add_cat():
            data = request.get_json(force=True)
            ok = db.add_category(data.get('name', ''), data.get('color', '#533483'))
            return jsonify({'ok': ok})

        @app.route('/api/categories/<name>', methods=['DELETE'])
        def api_del_cat(name):
            ok = db.delete_category(name)
            return jsonify({'ok': ok})

        @app.route('/api/categories/<name>', methods=['PUT'])
        def api_upd_cat(name):
            data = request.get_json(force=True)
            db.update_category(name, data.get('color', '#533483'))
            return jsonify({'ok': True})

        @app.route('/api/snippets', methods=['GET'])
        def api_snippets():
            q = request.args.get('search', '')
            return jsonify({'snippets': db.get_snippets(q)})

        @app.route('/api/snippets/<int:sid>', methods=['GET'])
        def api_snippet_get(sid):
            s = db.get_snippet(sid)
            if not s:
                return jsonify({'error': 'not found'}), 404
            return jsonify(s)

        @app.route('/api/snippets', methods=['POST'])
        def api_snippet_add():
            data = request.get_json(force=True)
            sid = db.add_snippet(
                data.get('name', ''), data.get('content', ''),
                data.get('tags', ''), data.get('shortcut', ''),
                data.get('category', 'all'))
            return jsonify({'ok': True, 'id': sid})

        @app.route('/api/snippets/<int:sid>', methods=['PUT'])
        def api_snippet_upd(sid):
            data = request.get_json(force=True)
            db.update_snippet(sid, **{k: v for k, v in data.items()
                                      if k in ('name', 'content', 'tags', 'shortcut', 'category')})
            return jsonify({'ok': True})

        @app.route('/api/snippets/<int:sid>', methods=['DELETE'])
        def api_snippet_del(sid):
            db.delete_snippet(sid)
            return jsonify({'ok': True})

        @app.route('/api/snippets/<int:sid>/use', methods=['POST'])
        def api_snippet_use(sid):
            db.use_snippet(sid)
            s = db.get_snippet(sid)
            if s:
                content = s['content']
                if crypto.fernet:
                    try:
                        content = crypto.decrypt(content)
                    except:
                        pass
                self._set_clip(content)
            return jsonify({'ok': True})

        @app.route('/api/stats', methods=['GET'])
        def api_stats():
            return jsonify(db.get_stats())

        @app.route('/api/export/markdown')
        def api_export_md():
            items, _ = db.search(pp=999999)
            lines = ['# CoolClipboard Export\n']
            lines.append(f'*Exported: {datetime.now().isoformat()[:19]}*\n')
            lines.append(f'*Total Clips: {len(items)}*\n\n---\n')
            for item in reversed(items):
                lines.append(f'## Clip #{item["id"]} ({item["type"]})\n')
                lines.append(f'- **Created:** {item["created_at"]}')
                lines.append(f'- **Updated:** {item["updated_at"]}')
                if item.get('category') and item['category'] != 'all':
                    lines.append(f'- **Category:** {item["category"]}')
                if item.get('pinned'):
                    lines.append('- 📌 **Pinned**')
                if item['tags']:
                    lines.append(f'- **Tags:** {item["tags"]}')
                if item['favorite']:
                    lines.append('- ⭐ **Favorite**')
                if item['notes']:
                    lines.append(f'- **Notes:** {item["notes"]}')
                lines.append('')
                if item['type'] == 'image':
                    if item['image_path']:
                        name = Path(item['image_path']).name
                        lines.append(f'![Clipboard Image]({name})')
                else:
                    lines.append('```')
                    lines.append(item['content'] or '')
                    lines.append('```')
                lines.append('\n---\n')
            text = '\n'.join(lines)
            return Response(text, mimetype='text/markdown',
                          headers={'Content-Disposition': 'attachment; filename=coolclipboard-export.md'})

        @app.route('/api/export/json')
        def api_export_json():
            items, _ = db.search(pp=999999)
            return Response(json.dumps(items, indent=2, default=str),
                          mimetype='application/json',
                          headers={'Content-Disposition': 'attachment; filename=coolclipboard-export.json'})

        @app.route('/api/export/csv')
        def api_export_csv():
            items, _ = db.search(pp=999999)
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(['id', 'type', 'content', 'tags', 'category', 'pinned',
                        'favorite', 'created_at', 'updated_at', 'notes'])
            for item in items:
                w.writerow([item['id'], item['type'], item['content'] or '',
                           item['tags'], item.get('category', ''),
                           item.get('pinned', 0), item['favorite'],
                           item['created_at'], item['updated_at'],
                           item.get('notes', '')])
            return Response(buf.getvalue(), mimetype='text/csv',
                          headers={'Content-Disposition': 'attachment; filename=coolclipboard-export.csv'})

        @app.route('/api/settings', methods=['GET'])
        def api_settings():
            return jsonify(self.config)

        @app.route('/api/settings', methods=['PUT'])
        def api_settings_upd():
            data = request.get_json(force=True)
            for k, v in data.items():
                self.config[k] = v
            save_config(self.config)
            return jsonify({'ok': True})

        @app.route('/images/<name>')
        def api_image(name):
            p = IMAGES_DIR / name
            if p.exists():
                return send_file(str(p), mimetype='image/png')
            return '', 404

        app.run(host='127.0.0.1', port=self.WEB_PORT, debug=False)

# ─── RUN ────────────────────────────────────────────────────

    def run(self):
        if HAS_PYNPUT:
            self.mouse_listener = pynput_mouse.Listener(on_click=self._on_mouse_click)
            self.mouse_listener.start()

        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()

        t = threading.Thread(target=self._web_loop, daemon=True)
        t.start()

        t = threading.Thread(target=self._hotkey_loop, daemon=True)
        t.start()

        print(f'  🌐 Web GUI:  http://localhost:{self.WEB_PORT}')
        print(f'  📋 Overlay:  {self.HOTKEY_OVERLAY}')
        print(f'  ⌨  Display:  {self.HOTKEY_DISPLAY}')
        print(f'  📁 Data:     {DATA_DIR}')
        print(f'  🎨 Theme:    {self.theme_name}')
        print(f'  🔄 Monitor:  active\n')

        if HAS_TK:
            self.root.mainloop()
        else:
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self._quit()


# ─── AUTOSTART ──────────────────────────────────────────────

def setup_autostart():
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = f'''[Desktop Entry]
Type=Application
Name=CoolClipboard
Comment=Advanced Clipboard Manager
Exec={sys.executable} {os.path.abspath(__file__)}
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
'''
    AUTOSTART_PATH.write_text(entry)
    os.chmod(AUTOSTART_PATH, 0o755)


# ─── INSTALL ────────────────────────────────────────────────

def install():
    print(BANNER)
    print('  Installing CoolClipboard...\n')

    deps = ['xclip', 'python3-tk', 'python3-pil', 'xdotool']
    try:
        r = subprocess.run(['which', 'sudo'], capture_output=True, timeout=5)
        has_sudo = r.returncode == 0
    except:
        has_sudo = False

    if has_sudo:
        try:
            r = subprocess.run(
                ['sudo', '-n', 'true'], capture_output=True, timeout=5)
            can_sudo = r.returncode == 0
        except:
            can_sudo = False
    else:
        can_sudo = False

    if can_sudo:
        try:
            r = subprocess.run(
                ['sudo', 'apt', 'install', '-y'] + deps,
                capture_output=True, timeout=120)
            if r.returncode == 0:
                print('  ✓ System packages installed')
            else:
                print('  ! System packages failed, install manually:')
                print(f'    sudo apt install {" ".join(deps)}')
        except:
            print('  ! Could not install system packages')
    else:
        print(f'     If needed: sudo apt install {" ".join(deps)}')

    pkgs = ['pynput', 'flask', 'pystray', 'cryptography']
    for pkg in pkgs:
        try:
            r = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', pkg, '--break-system-packages'],
                capture_output=True, timeout=60)
            if r.returncode == 0:
                print(f'  ✓ {pkg} installed')
            else:
                r2 = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', pkg],
                    capture_output=True, timeout=60)
                if r2.returncode == 0:
                    print(f'  ✓ {pkg} installed')
                else:
                    print(f'  ! {pkg}: install failed')
        except Exception as e:
            print(f'  ! {pkg}: {e}')

    setup_autostart()
    print('  ✓ Autostart configured\n')
    print('  Starting CoolClipboard...\n')
    main()


def main():
    os.system('clear' if os.name == 'posix' else 'cls')
    print(BANNER)
    print(f'  Starting CoolClipboard...\n')

    cc = CoolClipboard()
    try:
        cc.run()
    except KeyboardInterrupt:
        cc._quit()


# ─── HTML GUI ───────────────────────────────────────────────

HTML_INDEX = r'''<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoolClipboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#1a1a2e;--bg2:#16213e;--fg:#e0e0e0;--fg2:#a0a0a0;--accent:#0f3460;--hl:#e94560;--sel:#533483;--brd:#2a2a4a}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg);min-height:100vh}
.header{background:var(--bg2);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid var(--brd)}
.header h1{font-size:20px;color:var(--hl);font-weight:700}
.header h1 span{color:var(--sel)}
.header-right{display:flex;align-items:center;gap:12px}
.status{font-size:12px;color:var(--fg2)}
.tabs{display:flex;gap:0;padding:0 24px;background:var(--bg2);border-bottom:1px solid var(--brd)}
.tab{padding:10px 20px;cursor:pointer;font-size:13px;color:var(--fg2);border-bottom:2px solid transparent;transition:.2s}
.tab:hover{color:var(--fg)}
.tab.active{color:var(--hl);border-bottom-color:var(--hl)}
.sidebar{position:fixed;left:0;top:52px;bottom:0;width:200px;background:var(--bg2);border-right:1px solid var(--brd);padding:12px 0;overflow-y:auto;z-index:10}
.sidebar h3{padding:8px 16px;font-size:11px;text-transform:uppercase;color:var(--fg2);letter-spacing:1px}
.sidebar .cat{padding:8px 16px;cursor:pointer;font-size:13px;color:var(--fg2);transition:.2s;display:flex;align-items:center;gap:8px}
.sidebar .cat:hover{background:var(--accent);color:var(--fg)}
.sidebar .cat.active{background:var(--sel);color:#fff}
.sidebar .cat .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.sidebar .cat .count{margin-left:auto;font-size:11px;opacity:.6}
.main{margin-left:200px;padding:12px 24px 24px}
.toolbar{display:flex;gap:8px;padding:10px 0;flex-wrap:wrap;align-items:center}
.toolbar input[type=text]{flex:1;min-width:180px;padding:8px 12px;border:1px solid var(--brd);border-radius:6px;background:var(--bg2);color:var(--fg);font-size:13px;outline:none;transition:.2s}
.toolbar input[type=text]:focus{border-color:var(--hl)}
.toolbar .btn{padding:6px 14px;border:1px solid var(--brd);border-radius:6px;background:var(--bg2);color:var(--fg);cursor:pointer;font-size:12px;transition:.2s;white-space:nowrap}
.toolbar .btn:hover{background:var(--brd);border-color:var(--sel)}
.toolbar .btn.active{background:var(--sel);border-color:var(--hl);color:#fff}
.toolbar .btn.danger{color:var(--hl)}
.toolbar .btn.danger:hover{background:#3a1a2e}
.stats{padding:4px 0 8px;font-size:12px;color:var(--fg2)}
.clips{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:12px;cursor:pointer;transition:.2s;position:relative}
.card:hover{border-color:var(--sel);transform:translateY(-1px);box-shadow:0 4px 20px rgba(83,52,131,.15)}
.card.pinned{border-left:3px solid var(--hl)}
.card .meta{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:10px;color:var(--fg2)}
.card .meta .type-badge{padding:1px 6px;border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase}
.card .meta .type-badge.text{background:var(--accent);color:#6ab0ff}
.card .meta .type-badge.image{background:#3a1a2e;color:var(--hl)}
.card .meta .cat-badge{padding:1px 6px;border-radius:3px;font-size:9px;background:var(--sel);color:#fff}
.card .tags{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px}
.card .tag{padding:1px 6px;border-radius:3px;background:var(--accent);color:#a0c4ff;font-size:9px}
.card .favorite{position:absolute;top:8px;right:10px;font-size:16px;cursor:pointer;color:#555;transition:.2s}
.card .favorite.active{color:var(--hl)}
.card .pin-icon{position:absolute;top:8px;right:32px;font-size:12px;cursor:pointer;color:#555;transition:.2s}
.card .pin-icon.active{color:var(--hl)}
.card .preview{font-size:12px;line-height:1.5;color:#c0c0c0;max-height:55px;overflow:hidden;word-break:break-all}
.card .preview img{max-width:100%;max-height:100px;border-radius:4px;object-fit:contain}
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.active{display:flex}
.modal{background:var(--bg2);border:1px solid var(--brd);border-radius:12px;width:92%;max-width:750px;max-height:90vh;overflow-y:auto;padding:24px;position:relative}
.modal h2{font-size:16px;margin-bottom:12px;color:var(--hl)}
.modal .field{margin-bottom:10px}
.modal label{display:block;font-size:11px;color:var(--fg2);margin-bottom:3px}
.modal textarea,.modal input[type=text],.modal select{width:100%;padding:7px 10px;border:1px solid var(--brd);border-radius:6px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:13px;resize:vertical;outline:none}
.modal textarea:focus,.modal input:focus,.modal select:focus{border-color:var(--hl)}
.modal textarea{min-height:80px}
.modal .content-view{background:var(--bg);border:1px solid var(--brd);border-radius:6px;padding:10px;font-size:12px;line-height:1.5;max-height:180px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;margin-bottom:10px;font-family:Consolas,monospace}
.modal .btn-row{display:flex;gap:6px;margin-top:14px;justify-content:flex-end}
.modal .btn-row .btn{padding:6px 16px;border:1px solid var(--brd);border-radius:6px;cursor:pointer;font-size:12px;transition:.2s}
.modal .btn-row .btn.primary{background:var(--hl);border-color:var(--hl);color:#fff}
.modal .btn-row .btn.primary:hover{opacity:.85}
.modal .btn-row .btn.secondary{background:var(--bg);color:var(--fg)}
.modal .btn-row .btn.secondary:hover{background:var(--brd)}
.modal .btn-row .btn.danger{background:#3a1a2e;color:var(--hl);border-color:#3a1a2e}
.modal .btn-row .btn.danger:hover{background:#4a2a3e}
.modal .versions{margin-top:12px}
.modal .version-item{padding:8px;background:var(--bg);border:1px solid var(--brd);border-radius:6px;margin-bottom:6px;font-size:11px;display:flex;justify-content:space-between;align-items:center}
.modal .version-item .vbtn{padding:3px 8px;border:1px solid var(--brd);border-radius:4px;background:var(--bg2);color:var(--fg);cursor:pointer;font-size:10px}
.modal .version-item .vbtn:hover{background:var(--sel);color:#fff}
@keyframes fadeIn{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}
.modal.active{animation:fadeIn .15s ease}
.empty{text-align:center;padding:50px 20px;color:#555;grid-column:1/-1}
.empty h2{font-size:20px;color:var(--brd);margin-bottom:6px}
.empty p{font-size:13px}
.snippet-item{padding:10px;background:var(--bg);border:1px solid var(--brd);border-radius:6px;margin-bottom:6px;cursor:pointer;transition:.2s}
.snippet-item:hover{border-color:var(--sel)}
.snippet-item .sname{font-size:13px;font-weight:600;color:var(--fg)}
.snippet-item .scontent{font-size:11px;color:var(--fg2);margin-top:4px;max-height:40px;overflow:hidden;font-family:Consolas,monospace}
.snippet-item .smeta{font-size:10px;color:var(--fg2);margin-top:4px;display:flex;gap:8px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;padding:16px 0}
.stat-card{background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:16px;text-align:center}
.stat-card .stat-val{font-size:28px;font-weight:700;color:var(--hl)}
.stat-card .stat-label{font-size:11px;color:var(--fg2);margin-top:4px}
.theme-btn{width:24px;height:24px;border-radius:50%;border:2px solid var(--brd);cursor:pointer;transition:.2s}
.theme-btn:hover{transform:scale(1.15)}
.theme-btn.active{border-color:var(--hl)}
</style>
</head>
<body>
<div class="header">
<div><h1>Cool<span>Clipboard</span></h1></div>
<div class="header-right">
<div class="theme-btn" style="background:#1a1a2e" onclick="setTheme('dark')" title="Dark"></div>
<div class="theme-btn" style="background:#f5f5f5" onclick="setTheme('light')" title="Light"></div>
<div class="theme-btn" style="background:#272822" onclick="setTheme('monokai')" title="Monokai"></div>
<div class="theme-btn" style="background:#282a36" onclick="setTheme('dracula')" title="Dracula"></div>
<span class="status" id="status">ready</span>
</div>
</div>
<div class="tabs">
<div class="tab active" onclick="showView('clips')">📋 Clips</div>
<div class="tab" onclick="showView('snippets')">📝 Snippets</div>
<div class="tab" onclick="showView('stats')">📊 Stats</div>
</div>
<div class="sidebar" id="sidebar"></div>
<div class="main" id="mainArea">
<div id="clipsView">
<div class="toolbar">
<input type="text" id="search" placeholder="Search clips..." oninput="doSearch()">
<button class="btn active" data-filter="all" onclick="setFilter('all')">All</button>
<button class="btn" data-filter="text" onclick="setFilter('text')">Text</button>
<button class="btn" data-filter="image" onclick="setFilter('image')">Images</button>
<button class="btn" data-filter="fav" onclick="setFilter('fav')">★ Favorites</button>
<button class="btn" data-filter="pinned" onclick="setFilter('pinned')">📌 Pinned</button>
<button class="btn" onclick="window.open('/api/export/markdown','_blank')">📥 MD</button>
<button class="btn" onclick="window.open('/api/export/json','_blank')">📥 JSON</button>
<button class="btn" onclick="window.open('/api/export/csv','_blank')">📥 CSV</button>
<button class="btn danger" onclick="if(confirm('Delete ALL clips?')){fetch('/api/clips',{method:'DELETE'}).then(()=>load())}">🗑 Clear All</button>
</div>
<div class="stats" id="stats"></div>
<div class="clips" id="clips"></div>
</div>
<div id="snippetsView" style="display:none">
<div class="toolbar">
<input type="text" id="snippetSearch" placeholder="Search snippets..." oninput="loadSnippets()">
<button class="btn primary" onclick="openSnippetModal()">+ New Snippet</button>
</div>
<div id="snippets"></div>
</div>
<div id="statsView" style="display:none">
<div class="stats-grid" id="statsGrid"></div>
</div>
</div>
<div class="modal-overlay" id="modal" onclick="if(event.target==this)closeModal()">
<div class="modal"><h2 id="mTitle">Details</h2>
<div id="mBody"></div></div></div>
<script>
let filter='all',search='',page=1,activeView='clips',activeCat='all',categories=[];
function $(id){return document.getElementById(id)}
function setTheme(t){
 fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:t})})
 .then(()=>location.reload())}
function showView(v){
 activeView=v;
 document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['clips','snippets','stats'][i]===v));
 $('clipsView').style.display=v==='clips'?'':'none';
 $('snippetsView').style.display=v==='snippets'?'':'none';
 $('statsView').style.display=v==='stats'?'':'none';
 if(v==='snippets')loadSnippets();
 if(v==='stats')loadStats();
 if(v==='clips')load();}
function loadCategories(){
 fetch('/api/categories').then(r=>r.json()).then(d=>{
  categories=d.categories;
  let sb=$('sidebar');
  let counts={};
  let items=[];items.push(...(window._lastItems||[]));
  items.forEach(i=>{let c=i.category||'all';counts[c]=(counts[c]||0)+1});
  let h='<h3>Categories</h3>';
  categories.forEach(c=>{
   let cnt=counts[c.name]||0;
   h+='<div class="cat '+(activeCat===c.name?'active':'')+'" onclick="filterCat(\''+c.name+'\')"><div class="dot" style="background:'+c.color+'"></div>'+c.name+'<span class="count">'+cnt+'</span></div>';
  });
  h+='<div style="padding:8px 16px;margin-top:8px"><button class="btn" onclick="openCatModal()" style="width:100%;font-size:11px">+ Add Category</button></div>';
  sb.innerHTML=h;});}
function filterCat(c){activeCat=c;load();}
function load(){
 let q='?page='+page;
 if(search)q+='&search='+encodeURIComponent(search);
 if(filter==='text')q+='&type=text';
 else if(filter==='image')q+='&type=image';
 else if(filter==='fav')q+='&favorite=true';
 else if(filter==='pinned')q+='&pinned=true';
 if(activeCat&&activeCat!=='all')q+='&category='+encodeURIComponent(activeCat);
 fetch('/api/clips'+q).then(r=>r.json()).then(d=>{
  let c=$('clips');c.innerHTML='';
  window._lastItems=d.items;
  $('stats').textContent=d.total+' clips';
  loadCategories();
  if(!d.items.length){c.innerHTML='<div class="empty"><h2>No clips found</h2><p>Copy something to get started!</p></div>';return}
  d.items.forEach(item=>{
   let fav=item.favorite?'active':'';
   let pin=item.pinned?'active':'';
   let pinned=item.pinned?'pinned':'';
   let t=item.type;
   let preview='';
   if(t==='image'){let src=item.image_path?'/images/'+item.image_path.split('/').pop():'';preview='<img src="'+src+'" alt="img">'}
   else{let txt=(item.content||'').substring(0,120);preview=htmlEscape(txt)}
   let tags=(item.tags||'').split(',').filter(Boolean).map(t=>'<span class="tag">'+htmlEscape(t)+'</span>').join('');
   let catBadge=item.category&&item.category!=='all'?'<span class="cat-badge">'+htmlEscape(item.category)+'</span>':'';
   let card=document.createElement('div');card.className='card '+pinned;
   card.innerHTML='<div class="meta"><span class="type-badge '+t+'">'+t+'</span>'+catBadge+'<span>'+item.created_at+'</span></div><div class="pin-icon '+pin+'" onclick="event.stopPropagation();togglePin('+item.id+')" title="Pin">📌</div><div class="favorite '+fav+'" onclick="event.stopPropagation();toggleFav('+item.id+')" title="Favorite">★</div><div class="preview">'+preview+'</div>'+(tags?'<div class="tags">'+tags+'</div>':'');
   card.onclick=()=>openModal(item.id);
   c.appendChild(card)})});}
function setFilter(f){filter=f;document.querySelectorAll('.toolbar .btn[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===f));page=1;load()}
function doSearch(){search=$('search').value;page=1;load()}
function openModal(id){
 fetch('/api/clips/'+id).then(r=>r.json()).then(item=>{
  let body=$('mBody');$('mTitle').textContent='Clip #'+item.id;
  let content='';
  if(item.type==='image'){let src=item.image_path?'/images/'+item.image_path.split('/').pop():'';content='<img src="'+src+'" style="max-width:100%;border-radius:6px">'}
  else{content='<div class="content-view">'+htmlEscape(item.content||'')+'</div>'}
  let catOpts=categories.map(c=>'<option value="'+c.name+'" '+(item.category===c.name?'selected':'')+'>'+c.name+'</option>').join('');
  let versionHtml='';
  fetch('/api/clips/'+id+'/versions').then(r=>r.json()).then(vd=>{
   if(vd.versions.length){
    versionHtml='<div class="versions"><h3 style="font-size:13px;margin-bottom:8px;color:var(--fg2)">Version History</h3>';
    vd.versions.forEach(v=>{
     versionHtml+='<div class="version-item"><span>'+v.created_at+'</span><button class="vbtn" onclick="restoreVersion('+v.id+','+item.id+')">Restore</button></div>';
    });
    versionHtml+='</div>';}
   body.innerHTML=content+
    '<div class="field"><label>Category</label><select id="mCat">'+catOpts+'</select></div>'+
    '<div class="field"><label>Tags</label><input type="text" id="mTags" value="'+htmlEscape(item.tags||'')+'"></div>'+
    '<div class="field"><label>Notes</label><textarea id="mNotes">'+htmlEscape(item.notes||'')+'</textarea></div>'+
    '<div class="field"><label><input type="checkbox" id="mPin" '+(item.pinned?'checked':'')+'"> Pinned</label></div>'+
    versionHtml+
    '<div class="btn-row"><button class="btn danger" onclick="deleteItem('+item.id+')">Delete</button><button class="btn secondary" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="saveItem('+item.id+')">Save</button></div>';
   $('modal').classList.add('active')});})}
function saveItem(id){
 let data={tags:$('mTags').value,notes:$('mNotes').value,category:$('mCat').value,pinned:$('mPin').checked?1:0};
 fetch('/api/clips/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(()=>{closeModal();load()})}
function deleteItem(id){fetch('/api/clips/'+id,{method:'DELETE'}).then(()=>{closeModal();load()})}
function toggleFav(id){fetch('/api/clips/'+id+'/favorite',{method:'POST'}).then(()=>load())}
function togglePin(id){fetch('/api/clips/'+id+'/pin',{method:'POST'}).then(()=>load())}
function restoreVersion(vid,cid){
 fetch('/api/versions/'+vid+'/restore',{method:'POST'}).then(()=>{closeModal();openModal(cid)})}
function closeModal(){$('modal').classList.remove('active')}
function htmlEscape(s){if(!s)return '';const d=document.createElement('div');d.appendChild(document.createTextNode(s));return d.innerHTML}
function openCatModal(){
 $('mTitle').textContent='New Category';$('mBody').innerHTML=
  '<div class="field"><label>Name</label><input type="text" id="cName"></div>'+
  '<div class="field"><label>Color</label><input type="color" id="cColor" value="#533483"></div>'+
  '<div class="btn-row"><button class="btn secondary" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="saveCat()">Create</button></div>';
 $('modal').classList.add('active')}
function saveCat(){
 fetch('/api/categories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('cName').value,color:$('cColor').value})}).then(()=>{closeModal();load()})}
function loadSnippets(){
 let q=$('snippetSearch')?$('snippetSearch').value:'';
 fetch('/api/snippets?search='+encodeURIComponent(q)).then(r=>r.json()).then(d=>{
  let c=$('snippets');c.innerHTML='';
  if(!d.snippets.length){c.innerHTML='<div class="empty"><h2>No snippets</h2><p>Create templates for frequently used text</p></div>';return}
  d.snippets.forEach(s=>{
   let el=document.createElement('div');el.className='snippet-item';
   el.innerHTML='<div class="sname">'+htmlEscape(s.name)+'</div><div class="scontent">'+htmlEscape(s.content.substring(0,150))+'</div><div class="smeta"><span>Used: '+s.use_count+'x</span>'+(s.shortcut?'<span>Shortcut: '+htmlEscape(s.shortcut)+'</span>':'')+(s.tags?'<span>Tags: '+htmlEscape(s.tags)+'</span>':'')+'</div>';
   el.onclick=()=>useSnippet(s.id);
   el.oncontextmenu=(e)=>{e.preventDefault();editSnippet(s.id)};
   c.appendChild(el)})});}
function useSnippet(id){fetch('/api/snippets/'+id+'/use',{method:'POST'}).then(()=>{loadSnippets();alert('Snippet copied to clipboard!')})}
function openSnippetModal(){
 $('mTitle').textContent='New Snippet';$('mBody').innerHTML=
  '<div class="field"><label>Name</label><input type="text" id="sName"></div>'+
  '<div class="field"><label>Content</label><textarea id="sContent"></textarea></div>'+
  '<div class="field"><label>Tags</label><input type="text" id="sTags"></div>'+
  '<div class="field"><label>Shortcut</label><input type="text" id="sShortcut"></div>'+
  '<div class="btn-row"><button class="btn secondary" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="saveSnippet()">Create</button></div>';
 $('modal').classList.add('active')}
function editSnippet(id){
 fetch('/api/snippets/'+id).then(r=>r.json()).then(s=>{
  $('mTitle').textContent='Edit Snippet';$('mBody').innerHTML=
  '<div class="field"><label>Name</label><input type="text" id="sName" value="'+htmlEscape(s.name)+'"></div>'+
  '<div class="field"><label>Content</label><textarea id="sContent">'+htmlEscape(s.content)+'</textarea></div>'+
  '<div class="field"><label>Tags</label><input type="text" id="sTags" value="'+htmlEscape(s.tags||'')+'"></div>'+
  '<div class="field"><label>Shortcut</label><input type="text" id="sShortcut" value="'+htmlEscape(s.shortcut||'')+'"></div>'+
  '<div class="btn-row"><button class="btn danger" onclick="deleteSnippet('+s.id+')">Delete</button><button class="btn secondary" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="updateSnippet('+s.id+')">Save</button></div>';
  $('modal').classList.add('active')})}
function saveSnippet(){
 fetch('/api/snippets',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({name:$('sName').value,content:$('sContent').value,tags:$('sTags').value,shortcut:$('sShortcut').value})}).then(()=>{closeModal();loadSnippets()})}
function updateSnippet(id){
 fetch('/api/snippets/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({name:$('sName').value,content:$('sContent').value,tags:$('sTags').value,shortcut:$('sShortcut').value})}).then(()=>{closeModal();loadSnippets()})}
function deleteSnippet(id){fetch('/api/snippets/'+id,{method:'DELETE'}).then(()=>{closeModal();loadSnippets()})}
function loadStats(){
 fetch('/api/stats').then(r=>r.json()).then(s=>{
  let g=$('statsGrid');g.innerHTML='';
  let cards=[
   {val:s.total_clips,label:'Total Clips'},
   {val:s.text_clips,label:'Text Clips'},
   {val:s.image_clips,label:'Images'},
   {val:s.favorites,label:'Favorites'},
   {val:s.pinned,label:'Pinned'},
   {val:s.snippets,label:'Snippets'},
  ];
  cards.forEach(c=>{let d=document.createElement('div');d.className='stat-card';d.innerHTML='<div class="stat-val">'+c.val+'</div><div class="stat-label">'+c.label+'</div>';g.appendChild(d)});
  if(s.top_tags&&s.top_tags.length){
   let tagCard=document.createElement('div');tagCard.className='stat-card';tagCard.style.gridColumn='1/-1';
   tagCard.innerHTML='<div class="stat-label" style="margin-bottom:8px">Top Tags</div>'+s.top_tags.map(([t,c])=>'<span class="tag" style="font-size:11px;padding:3px 8px;margin:2px">'+htmlEscape(t)+' ('+c+')</span>').join('');
   g.appendChild(tagCard);}
  if(s.by_category&&Object.keys(s.by_category).length){
   let catCard=document.createElement('div');catCard.className='stat-card';catCard.style.gridColumn='1/-1';
   catCard.innerHTML='<div class="stat-label" style="margin-bottom:8px">By Category</div>'+Object.entries(s.by_category).map(([k,v])=>htmlEscape(k)+': '+v).join(' &middot; ');
   g.appendChild(catCard);}});}
load();
</script>
</body>
</html>'''

if __name__ == '__main__':
    if '--selftest' in sys.argv:
        if muscal_layer is not None:
            raise SystemExit(muscal_layer.selftest())
        print('MUSCAL layer not available')
        raise SystemExit(1)
    if '--install' in sys.argv:
        install()
    elif '--export' in sys.argv:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        db = Database(DB_PATH)
        items, total = db.search(pp=999999)
        print(BANNER)
        print(f'  Exporting {total} clips to markdown...')
        export_path = DATA_DIR / f'coolclipboard-export-{datetime.now():%Y%m%d-%H%M%S}.md'
        lines = ['# CoolClipboard Export\n']
        lines.append(f'*Exported: {datetime.now().isoformat()[:19]}*\n')
        lines.append(f'*Total Clips: {total}*\n\n---\n')
        for item in reversed(items):
            lines.append(f'## Clip #{item["id"]} ({item["type"]})\n')
            lines.append(f'- **Created:** {item["created_at"]}')
            lines.append(f'- **Updated:** {item["updated_at"]}')
            if item.get('category') and item['category'] != 'all':
                lines.append(f'- **Category:** {item["category"]}')
            if item.get('pinned'):
                lines.append('- 📌 **Pinned**')
            if item['tags']:
                lines.append(f'- **Tags:** {item["tags"]}')
            if item['favorite']:
                lines.append('- ⭐ **Favorite**')
            if item['notes']:
                lines.append(f'- **Notes:** {item["notes"]}')
            lines.append('')
            if item['type'] == 'image' and item['image_path']:
                lines.append(f'![Image]({Path(item["image_path"]).name})')
            else:
                lines.append('```')
                lines.append(item['content'] or '')
                lines.append('```')
            lines.append('\n---\n')
        export_path.write_text('\n'.join(lines))
        print(f'  ✓ Exported to: {export_path}')
        db.close()
    elif '--help' in sys.argv or '-h' in sys.argv:
        print(BANNER)
        print('  Usage:')
        print('    python3 coolclipboard.py               Start CoolClipboard')
        print('    python3 coolclipboard.py --install      Install + start')
        print('    python3 coolclipboard.py --export       Export all clips as markdown')
        print('    python3 coolclipboard.py --help         Show this help\n')
        print('  Hotkeys:')
        print(f'    {DEFAULT_CONFIG["hotkey_overlay"]}    Show clipboard history overlay')
        print(f'    {DEFAULT_CONFIG["hotkey_display"]}    Toggle keystroke/mouse display\n')
        print(f'  Web GUI: http://localhost:{DEFAULT_CONFIG["web_port"]}')
    else:
        main()
