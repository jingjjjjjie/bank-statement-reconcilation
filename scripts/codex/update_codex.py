"""Update this project's Docker Codex CLI to the latest stable OpenAI release."""

import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

# Standard library only: runs on the host as `python scripts/codex/update_codex.py`, outside Docker.
ROOT = Path(__file__).resolve().parents[2]
RELEASES = 'https://api.github.com/repos/openai/codex/releases/latest'
PINS = {
    '.env': r'(?m)^CODEX_VERSION=[^\r\n]+',
    '.env.example': r'(?m)^CODEX_VERSION=[^\r\n]+',
    'docker/Dockerfile': r'(?m)^ARG CODEX_VERSION=[^\r\n]+',
    'docker/compose.yaml': r'\$\{CODEX_VERSION:-[^}]+\}',
}
IDLE_CHECK = '''import json, pathlib, urllib.request, urllib.error
for endpoint in ('content/execution', 'matching-run'):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/' + endpoint, timeout=10) as response:
            state = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 409:
            continue
        raise
    if state.get('running') or state.get('active_processes'):
        raise SystemExit('Workflow is busy. Wait for it to finish before updating.')
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    try:
        args = path.read_bytes().split(b'\\0')[:2]
    except (OSError, PermissionError):
        continue
    if any(arg.rsplit(b'/', 1)[-1] in (b'codex', b'codex.js') for arg in args):
        raise SystemExit('A Codex process is running. Wait for it to finish before updating.')
'''


def compose(*arguments, capture=False, version=None):
    """Run Compose from this repository without invoking a shell."""
    environment = dict(os.environ)
    if version:
        environment['CODEX_VERSION'] = version
    result = subprocess.run(
        ['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT / 'docker/compose.yaml'), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=capture,
        check=True,
    )
    return result.stdout.strip() if capture else None


def latest_version():
    """Resolve the official stable release and reject unexpected release identifiers."""
    request = urllib.request.Request(RELEASES, headers={'User-Agent': 'reconciliation-codex-updater'})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    match = re.fullmatch(r'rust-v(\d+\.\d+\.\d+)', release['tag_name'])
    if not match or release.get('prerelease') or release.get('draft'):
        raise ValueError('Official release metadata did not identify a stable Codex version')
    return match[1]


def installed_version():
    """Read the CLI actually used by the running workflow container."""
    output = compose('exec', '-T', 'dashboard', 'codex', '--version', capture=True)
    match = re.fullmatch(r'codex-cli (\d+\.\d+\.\d+)', output)
    if not match:
        raise ValueError(f'Unexpected installed version: {output}')
    return match[1]


def planned_pins(version):
    """Prepare precise edits while preserving other settings and line endings."""
    changes = {}
    for name, pattern in PINS.items():
        path = ROOT / name
        before = path.read_bytes() if path.exists() else b''
        text = before.decode('utf-8')
        replacement = (
            '${CODEX_VERSION:-' + version + '}'
            if name == 'docker/compose.yaml'
            else ('ARG ' if name == 'docker/Dockerfile' else '') + 'CODEX_VERSION=' + version
        )
        if name == '.env' and not re.search(pattern, text):
            after = text + ('\n' if text and not text.endswith('\n') else '') + replacement + '\n'
        else:
            after, count = re.subn(pattern, lambda _, value=replacement: value, text)
            if count != 1:
                raise ValueError(f'Expected exactly one Codex version pin in {name}')
        if after.encode('utf-8') != before:
            changes[path] = (before, after.encode('utf-8'))
    return changes


def ensure_idle():
    """Refuse to replace a container while application or standalone model work runs."""
    compose('exec', '-T', 'dashboard', 'python', '-c', IDLE_CHECK)


def update(check=False):
    """Build before replacing the service; retain login volume and workflow data."""
    latest, current = latest_version(), installed_version()
    print(f'Workflow Codex: {current}; latest stable: {latest}', flush=True)
    changes = planned_pins(latest)
    if check:
        print(f'Check only: {len(changes)} version-pin file(s) need changes. No changes made.')
        return
    if tuple(map(int, current.split('.'))) > tuple(map(int, latest.split('.'))):
        raise ValueError('Installed Codex is newer than the stable release; refusing to downgrade')
    if current != latest:
        ensure_idle()
        compose('build', '--build-arg', f'CODEX_VERSION={latest}', 'dashboard', version=latest)
        ensure_idle()
    for path, (before, _) in changes.items():
        if (path.read_bytes() if path.exists() else b'') != before:
            raise ValueError(f'{path.name} changed during the update; run again')
    for path, (_, after) in changes.items():
        path.write_bytes(after)
    if current != latest:
        compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '90', 'dashboard', version=latest)
        actual = installed_version()
        if actual != latest:
            raise ValueError(f'Expected Codex {latest}, but the container reports {actual}')
    print(f'Codex {latest} is ready. Version pins are synchronized; login and document volumes retained.')


def main():
    """Offer a one-command update or a read-only version check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Show versions without changing anything')
    args = parser.parse_args()
    try:
        update(args.check)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Update failed: {error}\n')


if __name__ == '__main__':
    main()
