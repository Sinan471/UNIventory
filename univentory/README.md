# UNIventory application

Khalifa University's internal resource-reuse system: one modular Django
application with PostgreSQL, protected evidence storage and a worker running
the same release (Phase 4–5 design, ADR-01).

This folder holds the application source. The phase documents at the
repository root remain the requirements baseline.

## Current status: Increment 1–2, Jesher's part

| Part | Owner | State in this branch |
|------|-------|----------------------|
| Access, Inventory and Visual Foundation (S1–S6) | Jesher | **Implemented** (see below) |
| Requests, Approvals and Asset Operations (J1–J6) | Sinan | Not started. Contracts and test adapters are ready |
| AI, Sustainability and Reporting (A1–A6) | Jessica | Not started. Mount points and read contracts are ready |

Jesher's implemented scope:

* **S1 Platform and access:** project configuration, root routing and module
  composition, `AccessPolicy` (role, department and assignment scope),
  `IdentityAdapter` for KU SSO (OIDC code flow with PKCE, state and nonce;
  ID-token issuer, audience, signature, expiry and nonce checks), a 30-minute
  inactivity limit, failed and cancelled sign-in, logout, revocation that
  applies on the next request, and administration of departments, locations,
  categories and role grants.
* **S2 Asset records:** asset editor, detail and history; individual items
  and batches; KU asset IDs; AED values with an explicit Unknown option;
  restrictions and handling; typed per-category specifications; protected
  evidence upload and download (JPG/PNG/PDF checked by content, 10 MB and
  ten-file limits, quarantine).
* **S3 Inventory integrity:** `InventoryLedger` is the only place physical
  quantities change. It covers splits, adjustments, hold/commit/release,
  dispatch, receipt, return, loss, lifecycle, condition, safety and final
  execution. Every change locks rows, checks the version, conserves
  quantity, writes an immutable `AssetEvent` and replays operation keys.
  Legal ownership, departmental allocation, location and custody are kept
  separate.
* **S4 Catalogue:** listing preparation; submit, publish, pause, resume,
  withdraw and close with every publication blocker explained; keyword
  search, nine filters, sorting, pagination and grid/list views; restricted
  records are excluded before counting; only approved public fields are
  shown.
* **S5 Visual foundation:** design tokens, self-hosted fonts (OFL), base
  template, navigation rail with a mobile bottom bar, forms, buttons, tabs,
  dialogs with focus return, state badges, tables, a timeline, quantity bars,
  six category illustrations and a component reference page at `/design/`.
* **S6 Operations:** HTTPS and security settings, protected storage,
  encrypted backups with seven daily versions, verified isolated restore,
  `integrity_check`, the `perf_catalogue` baseline, deployment units, the
  English/Arabic framework (RTL, a translation compiler that needs no
  gettext) and core Arabic labels (draft, needs fluent review).
  Optional CSV import (FR-59) is **not started**.

## Quick start (local development)

```bash
cd univentory
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
# .venv/bin/python -m pip install -r requirements.txt       # macOS/Linux
cp .env.example .env              # DEBUG on, SQLite, dev sign-in enabled
python manage.py migrate
python manage.py compile_translations
python manage.py seed_demo        # 3 departments, 6 categories, 120 synthetic assets
python manage.py runserver
```

Open http://127.0.0.1:8000/identity/sign-in/ and choose a seeded account
under **Development sign-in (test adapter, not KU SSO)**. That panel exists
only when `DJANGO_DEBUG=true`. Useful accounts:

| Account | Shows |
|---------|-------|
| `mariam.custodian` | My Assets, register/edit/split, prepare and publish listings (MECH) |
| `khalid.rep` | Release reviews for MECH (fixture Approvals queue) |
| `sara.requester` | Exchange discovery only |
| `admin` | Administration (no business approval power) |
| `tariq.norole` | Signed in with no role: sees no protected records |

## Tests

```bash
python manage.py test --settings=config.test_settings
```

84 tests cover access and denial paths, SSO state/nonce/PKCE, reference-data
rules, asset validation, stale edits, ledger conservation (including the
documented ten-chair example), receipt replay, the 20-way race for the last
unit, unsafe-stock blocking, evidence validation and permissions, publication
blockers, search scoping, backup encryption and restore, and RTL layout.
Run the suite against PostgreSQL by setting `DATABASE_URL=postgres://...`.

## Layout and ownership (plan Section 8)

```
config/                    Jesher   settings, root routing, module composition
core/                      Jesher   contracts, shared web helpers, navigation, ops commands
  contracts/               Jesher   frozen v1.0 interfaces + labelled test adapters
identity/                  Jesher   AppUser, Role, UserRole, Department, Location, Category; AccessPolicy; SSO
inventory/                 Jesher   Asset, AssetPortion, AssetEvent, Attachment; InventoryLedger and services
catalogue/                 Jesher   Listing; CatalogueService; search
templates/shared/          Jesher   base layout and components
static/design/, fonts/, graphics/catalogue/   Jesher
demand/ workflow/ exchange/ care/ final_actions/ audit/ notifications/ jobs/   Sinan (to be added)
ai/ sustainability/ reporting/                                                 Jessica (to be added)
```

A member's module is installed and routed automatically once
`<module>/apps.py` exists (`config/settings.py` `OPTIONAL_MODULES`,
`config/urls.py`). Navigation entries register through `core.navigation`.
Nobody edits another member's module or the global styles. Ask the file
owner instead.

## Integration points for Sinan and Jessica

Full details: [docs/CONTRACTS.md](docs/CONTRACTS.md).

* Holds: `CatalogueService.hold(actor, listing_id=, quantity=, claim_ref=)`
  inside your reservation-approval transaction.
* Commit, dispatch, receipt, return, loss, release, lifecycle, safety and
  final execution: `InventoryLedger.*` inside your transaction.
* Scoped reads: `AssetQueryService`, `CatalogueQueryService.visible/search`,
  `AccessPolicy`.
* To replace the release-approval and audit test adapters, set
  `UNIVENTORY_RELEASE_APPROVALS_ADAPTER` and `UNIVENTORY_AUDIT_ADAPTER`.
* Classification widget: the `data-mount="classification"` element in
  `templates/inventory/asset_form.html`.
* Header slots: `notifications_slot` and `assistant_slot` blocks in
  `templates/shared/base.html`.

## More documentation

* [docs/CONTRACTS.md](docs/CONTRACTS.md): interfaces, error outcomes, operation keys
* [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md): Jesher's entities and state fields
* [docs/TRACEABILITY.md](docs/TRACEABILITY.md): requirement to code to test
* [docs/OPERATIONS.md](docs/OPERATIONS.md): deployment, security configuration, performance
* [docs/RECOVERY.md](docs/RECOVERY.md): backup and restore procedure
