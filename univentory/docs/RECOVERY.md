# Backup and recovery (NFR-17, Phase 4–5 Section 7.4)

Targets: RPO ≤ 24 hours, RTO ≤ 4 hours, seven daily versions. These are
targets; record each timed exercise with its measured results.

## Daily backup

1. `UNIVENTORY_BACKUP_KEY` is set (`manage.py backup_create --generate-key`).
   Keep a copy of the key and these instructions in protected storage that
   is separate from the application disk.
2. `deploy/univentory-backup.timer` runs `manage.py backup_create` daily at
   02:30 Asia/Dubai. Each run:
   * takes a consistent database snapshot (`pg_dump --format=custom`, or the
     SQLite online backup API);
   * reads the attachment manifest (ID, stored name, SHA-256, size) at the
     same moment;
   * packs the snapshot, the referenced evidence files and the manifest,
     encrypts them (Fernet: AES-128-CBC + HMAC-SHA256) and writes
     `univentory-backup-<UTC>.tar.gz.enc`;
   * deletes all but the seven newest versions.
3. The service then runs `integrity_check --max-backup-age-hours 24`. Alert
   the administrator if either step fails or a referenced file is missing.
4. Copy the backup directory to independently restricted storage.

Retaining backups is separate from business-record retention. Pilot purge
stays disabled.

## Restore exercise

1. Start the timer and choose a backup.
2. Restore into an empty, isolated directory:
   `manage.py backup_restore <archive> --target /srv/restore-test`
   This decrypts the archive, extracts it (blocking path traversal) and
   checks every file hash. It never touches the live database.
3. Load the database into an isolated instance:
   * PostgreSQL: `createdb univentory_restore && pg_restore --no-owner -d univentory_restore /srv/restore-test/database.pgdump`
     (create the `vector` extension first if Jessica's module is installed)
   * SQLite: use `/srv/restore-test/database.sqlite3`.
4. Point an isolated app copy at the restore: set `DATABASE_URL` and set
   `UNIVENTORY_PROTECTED_MEDIA_ROOT=/srv/restore-test/files`.
5. Run `manage.py migrate --check` and `manage.py integrity_check`. This
   checks quantity conservation, claim references, duplicate codes and
   attachment hashes. Once Sinan's modules are present, also check audit
   continuity and outstanding holds and consignments, and reset expired
   worker leases.
6. Test sign-in, one permitted read, one denied read and one normal
   transaction.
7. Record the elapsed time and the snapshot timestamp. Reopen only after
   every check passes.
