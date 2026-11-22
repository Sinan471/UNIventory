# Earlier Phase 6 request and transfer demonstration

> This is an earlier transfer scenario. For the integrated demo and current staged personas, start with [DEMO_GUIDE.md](DEMO_GUIDE.md).

This guide uses local synthetic data and development sign-in. It does not demonstrate real university authentication. The AI features are separate team work.

## Prepare a local demo

Follow the existing README to install the dependencies and create the database. In PowerShell, from the `univentory` folder, set the development options and use the implemented approval and audit services:

```powershell
$env:DJANGO_DEBUG = 'true'
$env:DJANGO_SECURE_SSL_REDIRECT = 'false'
$env:UNIVENTORY_RELEASE_APPROVALS_ADAPTER = 'workflow.adapters.ReleaseApprovals'
$env:UNIVENTORY_AUDIT_ADAPTER = 'audit.services.AuditService'
python manage.py migrate
python manage.py seed_demo
python manage.py seed_transfer_demo
python manage.py runserver
```

Use the project virtual environment's Python if `python` is unavailable. Run `seed_demo` once on a fresh local database: it adds new sample assets each time. `seed_transfer_demo` enables the Chemistry custodian as a synthetic receiver and is available only in development mode.

## Demonstration sequence

1. Open `http://127.0.0.1:8000/identity/sign-in/`. Select `sara.requester`. In Exchange, select a published item offered by Mechanical Engineering and choose **Request this item**. Choose Chemistry, enter a purpose and quantity, and submit.
2. Sign out. Select `aisha.rep`, open **Approvals**, and approve the need. A requester cannot approve their own need.
3. Sign in as `sara.requester`, open **My Requests**, select the approved request, and request a reservation.
4. Sign in as `khalid.rep`, open **Transfers**, select the reservation and approve the hold. This sets aside stock for 48 hours.
5. Sign in as `aisha.rep`, open **Transfers** and approve the transfer.
6. Sign in as `mariam.custodian`, open **Transfers**, choose the case, and dispatch to Chemistry. Choose `omar.custodian` as receiver and destination custodian and select a Chemistry location.
7. Sign in as `omar.custodian`, open **Transfers** and confirm the quantity physically received. The requester's **My Requests** page shows accepted and outstanding quantities and the action history.

Use an item with enough free units for the quantity selected. For a partial-receipt demonstration, choose a batch listing with at least two free units, request and dispatch two, then receive one. Outstanding demand should remain one until another receipt is accepted.

Hold expiry is queued, but requires an external scheduler to run `python manage.py run_work` regularly. The demo does not establish that the full project, AI features, production sign-in, PostgreSQL concurrency, or all exception paths are finished.

