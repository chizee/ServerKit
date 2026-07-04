"""Persist a detected manifest and seed what it declares (plan 17, Phase 1).

Stops the import flow from discarding what `RepositoryManifestService` already
parses: the health-check path, the manifest env, and (for v1 manifests) the
whole normalized spec are recorded so later pushes can re-read them.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from app import db
from app.models.application import Application
from app.models.application_manifest import ApplicationManifest, STATUS_PENDING
from app.services.env_service import EnvService


class ManifestPersistenceService:
    """Store the manifest row + seed non-secret env at import. Best-effort."""

    @classmethod
    def apply_import(cls, app: Application, analysis: Dict[str, Any],
                     user_id: Optional[int] = None,
                     source_repo: Optional[str] = None,
                     source_ref: Optional[str] = None,
                     source_commit: Optional[str] = None) -> Dict[str, Any]:
        """Consume a RepositoryManifestService result for a freshly imported app.

        - populate ``app.healthcheck_path`` from the detected recommendation
        - seed non-secret env values as EnvironmentVariable rows
        - store the ApplicationManifest row (v1 only, when the app has a project)

        Never raises — import must not fail because a manifest hint could not be
        persisted. Returns a small summary for the response/logs.
        """
        summary = {'healthcheck_path': None, 'env_seeded': 0, 'manifest_stored': False}

        recommended = analysis.get('recommended') or {}
        hc = recommended.get('healthcheck_path')
        if hc and not app.healthcheck_path:
            app.healthcheck_path = hc
            summary['healthcheck_path'] = hc

        summary['env_seeded'] = cls._seed_env(app, analysis, user_id)

        if analysis.get('manifest_v1_normalized') and app.project_id:
            try:
                cls.store_manifest(
                    project_id=app.project_id,
                    normalized=analysis['manifest_v1_normalized'],
                    raw_text=analysis.get('manifest_v1_raw'),
                    source_repo=source_repo,
                    source_ref=source_ref,
                    source_commit=source_commit,
                    source_path=analysis.get('manifest_v1_file') or 'serverkit.yaml',
                )
                summary['manifest_stored'] = True
            except Exception:
                db.session.rollback()

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return summary

    @classmethod
    def _seed_env(cls, app: Application, analysis: Dict[str, Any],
                  user_id: Optional[int]) -> int:
        """Seed non-secret literal env values. Secrets/placeholders stay empty."""
        entries = analysis.get('env') or []
        to_set: Dict[str, Any] = {}
        for entry in entries:
            key = entry.get('key')
            if not key or entry.get('kind') == 'env_file':
                continue
            if entry.get('secret'):
                continue  # placeholder — UI hints the operator to fill it
            value = entry.get('value')
            if value in (None, ''):
                continue
            to_set[key] = value
        if not to_set:
            return 0
        try:
            count, _errors = EnvService.bulk_set_env_vars(app.id, to_set, user_id)
            return count
        except Exception:
            return 0

    @classmethod
    def store_manifest(cls, project_id: int, normalized: Dict[str, Any],
                       raw_text: Optional[str] = None,
                       source_repo: Optional[str] = None,
                       source_ref: Optional[str] = None,
                       source_commit: Optional[str] = None,
                       source_path: str = 'serverkit.yaml',
                       status: str = STATUS_PENDING) -> ApplicationManifest:
        """Upsert the single ApplicationManifest row for a project."""
        row = ApplicationManifest.query.filter_by(project_id=project_id).first()
        if row is None:
            row = ApplicationManifest(project_id=project_id)
            db.session.add(row)

        row.raw_text = raw_text
        row.set_normalized(normalized)
        row.manifest_hash = cls.hash_normalized(normalized)
        row.source_repo = source_repo
        row.source_ref = source_ref
        row.source_commit = source_commit
        row.source_path = source_path
        row.status = status
        db.session.flush()
        return row

    @staticmethod
    def hash_normalized(normalized: Dict[str, Any]) -> str:
        payload = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()
