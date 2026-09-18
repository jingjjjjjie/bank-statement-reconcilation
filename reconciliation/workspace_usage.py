"""Durable workspace totals, deduplicated across review and benchmark logs."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from reconciliation.paths import WORKSPACE

SKIP = {'.git', 'node_modules', '.venv', '__pycache__', 'model-cache', 'model-requests',
        'assets', 'test-deps', 'playwright', 'uploads', 'documents', 'statement', 'runtime'}


def connect(root):
    """Open the independent accounting ledger, including when development is off."""
    folder = Path(root) / 'duplicated/accounting'
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'usage.sqlite3', timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS events (key TEXT PRIMARY KEY, event TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS imports (path TEXT PRIMARY KEY, size INTEGER, stamp INTEGER)')
    return db


def merge(db, event, mirrored=False):
    """Keep each attempt once, preferring reported usage over incomplete copies."""
    if event.get('status') == 'cached':
        if mirrored and not event.get('event_id'):
            return
        key = 'cache:' + (event.get('event_id') or hashlib.sha256(
            json.dumps(event, sort_keys=True).encode()).hexdigest())
    elif event.get('id'):
        key = 'attempt:' + event['id']
    else:
        return
    previous = db.execute('SELECT event FROM events WHERE key=?', (key,)).fetchone()
    if previous:
        old = json.loads(previous[0])
        if isinstance(old.get('usage'), dict) and not isinstance(event.get('usage'), dict):
            return
        if old.get('status') != 'started' and event.get('status') == 'started':
            return
    db.execute('INSERT OR REPLACE INTO events VALUES (?, ?)', (key, json.dumps(event)))


def persist(path, event):
    """Mirror new workspace attempts into a ledger that survives review cleanup."""
    if not Path(path).resolve().is_relative_to(WORKSPACE.resolve()):
        return
    db = connect(WORKSPACE)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            merge(db, event)
    finally:
        db.close()


def workspace_summary(root=None):
    """Import historical logs and return all retained workspace usage once."""
    from reconciliation.token_usage import summarize
    root = Path(root or WORKSPACE)
    db = connect(root)
    unreadable = []
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            for folder, directories, files in os.walk(root):
                directories[:] = [d for d in directories if d not in SKIP and not (Path(folder) / d).is_symlink()]
                if 'token-usage.jsonl' not in files:
                    continue
                path = Path(folder) / 'token-usage.jsonl'
                try:
                    stat = path.stat()
                    relative = str(path.relative_to(root)).replace('\\', '/')
                    prior = db.execute('SELECT size, stamp FROM imports WHERE path=?', (relative,)).fetchone()
                    if prior == (stat.st_size, stat.st_mtime_ns):
                        continue
                    for line in path.read_text(encoding='utf-8').splitlines():
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            unreadable.append(relative)
                            continue
                        if not isinstance(event, dict):
                            unreadable.append(relative)
                            continue
                        merge(db, event, mirrored='development-cache/runs/' in relative)
                    if relative not in unreadable:
                        db.execute('INSERT OR REPLACE INTO imports VALUES (?, ?, ?)',
                                   (relative, stat.st_size, stat.st_mtime_ns))
                except (OSError, UnicodeError):
                    unreadable.append(str(path))
            events = [json.loads(row[0]) for row in db.execute('SELECT event FROM events')]
        result = summarize(events)
        return {**result, 'scope': 'workspace', 'unreadable_logs': sorted(set(unreadable)),
                'complete': result['unknown_attempts'] == 0 and not unreadable}
    finally:
        db.close()
