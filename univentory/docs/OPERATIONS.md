# Operations (owner: Jesher)

## Hosted pilot layout

* nginx terminates TLS (`deploy/nginx.conf.example`) and proxies to gunicorn
  (`deploy/univentory-web.service`). Evidence files are never served by
  nginx.
* PostgreSQL 16 or later. Jessica's module adds the `vector` extension
  (ADR-02).
* The worker runs the same release. Its unit is added with Sinan's jobs
  module.
* Secrets come from `/etc/univentory/univentory.env` (mode 600) and are
  never committed. See `.env.example` for every variable.

Release steps:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py compile_translations
python manage.py collectstatic --noinput
python manage.py check --deploy
systemctl restart univentory-web
```

## Security configuration (NFR-08 to NFR-11, NFR-14)

| Control | Where |
|---------|-------|
| HTTPS redirect, HSTS, secure and HttpOnly cookies, nosniff, frame deny | `config/settings.py` whenever `DJANGO_DEBUG` is false |
| 30-minute sliding inactivity limit | `SESSION_COOKIE_AGE`, `SESSION_SAVE_EVERY_REQUEST` |
| No local passwords | `AppUser` has an unusable password; the only backend is `UniversityIdentityBackend` |
| OIDC PKCE, state and nonce; issuer, audience, signature and expiry validation | `identity/adapters.py` |
| CSRF on every POST; logout is POST-only | Django middleware; `identity/views.py` |
| Scope checks at every endpoint, download and search count | `identity/policy.py`; services raise `NotPermitted`/`HiddenRecord` |
| Upload checks by content signature, Pillow decode, PDF active-content quarantine, sanitised names, random storage names, a hash check on download | `inventory/services.py` (`AttachmentService`) |
| No Django admin (there is no second, unaudited edit path) | `INSTALLED_APPS` |
| Development sign-in refused unless DEBUG | `DevIdentityAdapter.enabled()` |

Responsibilities for security testing (NFR-11): Jesher covers uploads and
the form baseline, Sinan covers workflow injection, and Jessica covers CSV
and prompt injection.

## Performance baseline (NFR-01)

```bash
python manage.py seed_demo --assets 1000     # separate load database
python manage.py perf_catalogue --users 20 --requests 400
```

The command runs at least 200 measured catalogue, search, list and detail
requests after warm-up, using 20 concurrent signed-in clients through the
full Django stack. It excludes network, identity-provider and AI time.

Development baseline, recorded 15 Nov 2026 on a Windows 11 laptop, SQLite,
one process, 1,000 synthetic assets and 459 published listings:
**p50 111 ms, p95 1,122 ms, 0 errors**. One exchange page uses 12 queries
and takes about 22 ms when uncontended. The tail (max 9 s) is SQLite
serialising session writes. PostgreSQL with several gunicorn workers
removes that bottleneck.

**This is not acceptance evidence.** Repeat the measurement on the recorded
reference host with PostgreSQL, and report the host, the date and the error
rate.

## Health and monitoring

`GET /healthz/` returns only service status and database reachability. Use
`integrity_check --max-backup-age-hours 24` for backup freshness and
quantity conservation.
