"""Encrypted backup and verified restore (NFR-17, plan Section 7.4).

A backup is one encrypted archive holding a consistent database snapshot,
the protected evidence files referenced by that snapshot and a manifest of
their SHA-256 hashes. Seven daily versions are retained. Restore always goes
to an isolated directory first and is verified before anything is exposed.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import connection

PREFIX = "univentory-backup-"
SUFFIX = ".tar.gz.enc"


class BackupError(Exception):
    pass


def _fernet() -> Fernet:
    key = settings.UNIVENTORY_BACKUP["ENCRYPTION_KEY"]
    if not key:
        raise BackupError("UNIVENTORY_BACKUP_KEY is not set. Generate one with: manage.py backup_create --generate-key")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise BackupError("UNIVENTORY_BACKUP_KEY is not a valid Fernet key.") from exc


def _dump_database(workdir: Path) -> str:
    db = settings.DATABASES["default"]
    if db["ENGINE"].endswith("sqlite3"):
        target = workdir / "database.sqlite3"
        source = sqlite3.connect(db["NAME"])
        dest = sqlite3.connect(target)
        with dest:
            source.backup(dest)  # consistent online snapshot
        source.close()
        dest.close()
        return target.name
    if db["ENGINE"].endswith("postgresql"):
        target = workdir / "database.pgdump"
        env = dict(os.environ, PGPASSWORD=db.get("PASSWORD", ""))
        cmd = ["pg_dump", "--format=custom", "--no-owner", f"--file={target}",
               f"--host={db.get('HOST') or 'localhost'}", f"--port={db.get('PORT') or '5432'}",
               f"--username={db.get('USER')}", db["NAME"]]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise BackupError("pg_dump failed: " + result.stderr.strip()[:500])
        return target.name
    raise BackupError(f"Unsupported database engine {db['ENGINE']}")


def _manifest() -> list[dict]:
    from inventory.models import Attachment

    rows = []
    for a in Attachment.objects.order_by("pk").values("pk", "stored_name", "sha256", "size_bytes"):
        rows.append({"id": a["pk"], "stored_name": a["stored_name"], "sha256": a["sha256"], "size": a["size_bytes"]})
    return rows


def create_backup() -> Path:
    fernet = _fernet()
    out_dir = Path(settings.UNIVENTORY_BACKUP["DIRECTORY"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    media_root = Path(settings.PROTECTED_MEDIA_ROOT)
    with tempfile.TemporaryDirectory(prefix="univentory-bk-") as tmp:
        work = Path(tmp)
        # Manifest is read in the same moment as the snapshot so files and
        # metadata match (immutable attachment manifest, plan 7.4 step 1).
        manifest = _manifest()
        db_name = _dump_database(work)
        missing = []
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(work / db_name, arcname=db_name)
            for row in manifest:
                path = media_root / row["stored_name"]
                if not path.exists():
                    missing.append(row["stored_name"])
                    continue
                tar.add(path, arcname=f"files/{row['stored_name']}")
            meta = {
                "created_utc": stamp,
                "database_file": db_name,
                "database_engine": settings.DATABASES["default"]["ENGINE"],
                "attachments": manifest,
                "missing_files": missing,
            }
            data = json.dumps(meta, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        encrypted = fernet.encrypt(buf.getvalue())
    target = out_dir / f"{PREFIX}{stamp}{SUFFIX}"
    target.write_bytes(encrypted)
    prune(out_dir)
    if missing:
        raise BackupError(f"Backup written to {target}, but {len(missing)} referenced files were missing.")
    return target


def prune(out_dir: Path) -> list[Path]:
    keep = settings.UNIVENTORY_BACKUP["RETAIN_DAILY_VERSIONS"]
    backups = sorted(out_dir.glob(f"{PREFIX}*{SUFFIX}"))
    removed = backups[:-keep] if len(backups) > keep else []
    for path in removed:
        path.unlink()
    return removed


def latest_backup_age_hours() -> float | None:
    out_dir = Path(settings.UNIVENTORY_BACKUP["DIRECTORY"])
    backups = sorted(out_dir.glob(f"{PREFIX}*{SUFFIX}"))
    if not backups:
        return None
    stamp = backups[-1].name[len(PREFIX):-len(SUFFIX)]
    created = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def restore_backup(archive: Path, target: Path) -> dict:
    """Decrypt into an isolated directory and verify every file hash."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise BackupError("The restore target must be an empty directory.")
    target.mkdir(parents=True, exist_ok=True)
    try:
        payload = _fernet().decrypt(Path(archive).read_bytes())
    except InvalidToken as exc:
        raise BackupError("The backup could not be decrypted with the configured key.") from exc
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        tar.extractall(target, filter="data")  # rejects absolute paths and traversal
    meta = json.loads((target / "manifest.json").read_text())
    bad = []
    for row in meta["attachments"]:
        path = target / "files" / row["stored_name"]
        if row["stored_name"] in meta.get("missing_files", []):
            continue
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            bad.append(row["stored_name"])
    meta["hash_failures"] = bad
    if bad:
        raise BackupError(f"{len(bad)} restored files failed their hash check.")
    return meta


def copy_restored_files(restored_dir: Path, media_root: Path) -> int:
    count = 0
    for path in (Path(restored_dir) / "files").rglob("*"):
        if path.is_file():
            dest = Path(media_root) / path.relative_to(Path(restored_dir) / "files")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            count += 1
    return count


def db_vendor() -> str:
    return connection.vendor
