"""Reset or remove managed workspaces while preserving originals and durable history."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from dashboard.services.review import Review
from reconciliation.core.development_cache import write_json
from reconciliation.intake.exact_report import prepare


def unlinked(path):
    """Reject links and junctions before moving any application-owned directory."""
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('Workspace storage contains a linked path; no files were changed')
    return path


def locate(sources, identity):
    """Resolve an opaque project ID only within the managed project directory."""
    root = unlinked(sources.workspace / 'duplicated/projects')
    for manifest in root.glob('*/duplicate-manifest.json'):
        if hashlib.sha256(str(manifest.resolve()).encode()).hexdigest()[:24] != identity:
            continue
        unlinked(manifest)
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
        source = Path(data['SupportingRoot'])
        if not source.is_absolute() or source.resolve().is_relative_to(manifest.parent):
            raise ValueError('Workspace has an invalid original-document location')
        return manifest, source, data
    raise ValueError('Workspace is no longer available. Refresh the project list.')


def change(sources, manifest, source, saved, action):
    """Archive generated state; rebuild a fresh review on reset, rolling back failures."""
    if action not in {'reset', 'delete'}:
        raise ValueError('Unknown workspace action')
    if action == 'reset':
        if saved.get('Mode') != 'exact_report':
            raise ValueError('Open this legacy workspace first to restore its original documents before resetting')
        sources.inspect_workspace(source.parent)
    project = unlinked(manifest.parent)
    history = unlinked(sources.workspace / 'duplicated/project-history') / uuid4().hex
    duplicates = None
    duplicate_archive = None
    if saved.get('Mode') == 'exact_report':
        duplicates = unlinked(source.parent / 'output/duplicates')
        if source.name != 'documents' or Path(saved['DuplicateRoot']).absolute() != duplicates:
            raise ValueError('Duplicate output does not belong to this workspace')
        duplicate_archive = unlinked(source.parent / 'output/.reconciliation-history') / history.name / 'duplicates'
        if duplicates.exists():
            report = json.loads((duplicates / 'report.json').read_text(encoding='utf-8'))
            if Path(report['SupportingRoot']).resolve() != source.resolve():
                raise ValueError('Duplicate report belongs to another workspace')
    history.mkdir(parents=True)
    write_json(
        history / 'action.json',
        {
            'action': action,
            'project': str(project),
            'source': str(source),
            'duplicate_archive': str(duplicate_archive) if duplicate_archive else None,
        },
    )
    moved_project = moved_duplicates = preparing = False
    try:
        project.rename(history / 'project')
        moved_project = True
        if duplicate_archive and duplicates.exists():
            # Stay on the input filesystem, including separately mounted Docker volumes.
            duplicate_archive.parent.mkdir(parents=True)
            duplicates.rename(duplicate_archive)
            moved_duplicates = True
        if action == 'reset':
            project.mkdir()
            preparing = True
            prepare(source, manifest)
            review = Review(manifest, project / 'dashboard-data')
        else:
            review = None
        write_json(history / 'completed.json', {'action': action})
        return review
    except Exception:
        # Retain any incomplete new output as well as the previous review for recovery.
        if moved_project:
            if project.exists():
                project.rename(history / 'incomplete-reset')
            (history / 'project').rename(project)
        if duplicate_archive and (moved_duplicates or preparing) and duplicates.exists():
            duplicate_archive.parent.mkdir(parents=True, exist_ok=True)
            duplicates.rename(duplicate_archive.parent / 'incomplete-reset')
        if moved_duplicates:
            duplicate_archive.rename(duplicates)
        raise
