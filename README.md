# COOL_CLIPBOARD

Erweiterter Zwischenablage-Manager (Clipboard Manager) für Linux (X11) mit Web-GUI,
Overlays, Snippets, Versionierung, Verschlüsselung und intelligentem Analyse-Layer (MUSCAL).

## Features

- 📋 **Clipboard-Überwachung** – Text- und Bildcaptures automatisch speichern
- 🗂 **Kategorien & Tags** – automatische Tag-Erkennung (Links, E-Mails, IPs, Code, …)
- 📌 **Pinned & Favoriten** – wichtige Einträge oben anheften
- 🔍 **Regex-Suche** – Suche in Inhalten, Tags und Notizen
- 🔒 **Verschlüsselung** – optionale Fernet-Verschlüsselung einzelner Clips
- 📝 **Snippets** – wiederverwendbare Textbausteine mit Shortcuts
- 🕑 **Versionierung** – History pro Clip mit Wiederherstellung
- 🎨 **Themes** – Dark, Light, Monokai, Dracula
- 🌐 **Web-GUI** – Bedienung im Browser (localhost:8234)
- 🧠 **MUSCAL Layer & RAG Engine** – intelligente Klassifikation, Analyse (optional mit lokalem LLM),
  Kategorie-Ordner, Wissensgraph, semantische Vektorsuche & wissensbasierte RAG-Fragebeantwortung, Markdown-Dokument-Erstellung
- 🔌 **Plugin-System** – Erweiterbar durch benutzerdefinierte Python-Plugins (Custom Regex-Rules, Capture-Hooks)
- 📊 **Statistiken** – Nutzungszahlen, Top-Tags, Verteilung nach Kategorien
- 📤 **Export** – als Markdown, JSON oder CSV
- 🐧 **Linux-Kompatibilität** – X11 (`xclip`) mit automatischem Wayland-Fallback (`wl-clipboard`)

## Abhängigkeiten

### Python (pip)
```
pynput flask pystray cryptography pillow
```

### System-Pakete
```
sudo apt install xclip python3-tk xdotool
```

> Die Installation kann auch automatisch per `--install` ausgeführt werden
> (nutzt `sudo` und `pip --break-system-packages`).

## Installation & Start

```bash
# Installation + Autostart + Start
python3 coolclipboard.py --install

# Beispieldaten aus clipboard_tags/ importieren
python3 coolclipboard.py --seed

# RAG-Frage direkt im Terminal stellen
python3 coolclipboard.py --ask "Was ist das Fenbendazol Protokoll?"

# Semantische Vektorsuche im Terminal
python3 coolclipboard.py --rag-search "nohup script"

# Statistiken anzeigen
python3 coolclipboard.py --stats

# Als Markdown / JSON / CSV exportieren
python3 coolclipboard.py --export
python3 coolclipboard.py --export-json
python3 coolclipboard.py --export-csv

# Nur starten
python3 coolclipboard.py

# Selftest ausführen
python3 coolclipboard.py --selftest

# Hilfe
python3 coolclipboard.py --help
```

## Hotkeys

| Hotkey | Funktion |
|--------|----------|
| `Cmd+V` | Clipboard-History-Overlay öffnen |
| `Cmd+H` | Tastatur-/Maus-Anzeige umschalten |

Die Hotkeys können in `~/.local/share/coolclipboard/config.json` angepasst werden.

## Web-GUI

Nach dem Start erreichbar unter: **http://localhost:8234**

- Clips durchsuchen, anpinnen, favorisieren, bearbeiten, löschen
- Snippets verwalten
- Statistiken ansehen
- Daten als Markdown / JSON / CSV exportieren
- MUSCAL-Ansichten (Timeline, Ordner, Favoriten, Wissen, 🧠 RAG / Chat, Snippets, Statistik)

## Daten

Alle Daten liegen unter `~/.local/share/coolclipboard/`:

- `clipboard.db` – SQLite-Datenbank (Clips, Kategorien, Versionen, Snippets, Settings)
- `config.json` – Konfiguration (Hotkeys, Port, Theme, API-Token, MUSCAL-Settings)
- `images/` – gespeicherte Bildcaptures
- `markdown/` – Markdown-Exporte
- `muscal-docs/` – generierte MUSCAL-Dokumente
- `plugins/` – Plugin-Verzeichnis für benutzerdefinierte `.py`-Erweiterungen

## MUSCAL Layer & RAG Engine

`muscal_layer.py` ergänzt CoolClipboard um eine kognitive Analyse- und RAG-Ebene:

- **ContentAnalyzer** – heuristische Erkennung von Sprache, Inhaltstyp,
  Kategorie und Tags ohne externe Abhängigkeiten
- **RagEngine & LocalVectorizer** – Zero-Dependency semantische Vektorsuche (TF-IDF & Sublinear Hashing) mit Cosine-Similarity sowie RAG-Fragebeantwortung über die Zwischenablage-Historie
- **AiHelper** – optionaler OpenAI-kompatibler lokaler Endpoint für Chat & Embeddings
  (konfigurierbar in `config.json`: `muscal_ai_endpoint`, `muscal_ai_key`, `muscal_ai_model`)
- **CaptureStore** – deduplizierte Speicherung mit Metadaten (Hash, Quelle, Sprache, …)
- **Overlays** – Capture-Notification und Floating-Aktionsbutton nach Strg+C
- **Selftest** – 34 automatisierte Komponententests für Analyzer, Datenbank, Store und RAG-Engine

### Selftest ausführen

```bash
python3 muscal_layer.py
```

### MUSCAL in `config.json` aktivieren

```json
{
  "muscal_float": true,
  "muscal_float_timeout": 8,
  "muscal_ai_endpoint": "http://localhost:1234/v1",
  "muscal_ai_key": "",
  "muscal_ai_model": "local"
}
```

## Beispiel-Daten

Der Ordner `clipboard_tags/` enthält Beispiel-Texte (Code, Anleitungen, Kontakte,
URLs usw.) zum Testen der automatischen Tag-Erkennung und Klassifikation.

## Lizenz

Keine Angabe – für persönliche Verwendung freigegeben.