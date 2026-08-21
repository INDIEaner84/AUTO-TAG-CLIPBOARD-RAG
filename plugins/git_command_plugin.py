"""
Plugin: Git Command & Hash Analyzer
Erkennt Git-Befehle, Commit-Hashes und Diff-Auszüge und vergibt 'git' und 'vcs'-Tags.
"""
import re

def register_rules():
    return [
        (r'\bgit\s+(?:status|commit|push|pull|checkout|switch|branch|merge|rebase|clone|diff|log|stash)\b', 'git'),
        (r'\b[0-9a-f]{40}\b', 'git-sha'),
        (r'^(?:diff --git|--- a/|\+\+\+ b/)', 'git-diff'),
    ]

def on_capture(item):
    text = (item.get('content') or '') if isinstance(item, dict) else ''
    if text.startswith('git '):
        cmd = text.split()[1] if len(text.split()) > 1 else ''
        pass
