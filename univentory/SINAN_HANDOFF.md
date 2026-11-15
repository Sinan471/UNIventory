# Requests, transfer and care work in progress

This document describes an incomplete implementation. The branch is not a finished Phase 6 submission.

The demand module records requests and independent need reviews. The exchange module provides an initial reservation, transfer, receipt and discrepancy flow using the shared inventory ledger. Care includes defect reporting and an initial maintenance workflow. Final actions currently cover a limited donation, recycling and disposal path. Audit, in-app notifications and a scheduled hold-expiry work item are also present.

## Local configuration

Follow the existing README for a local installation and migrations. To use the new release-review and audit implementations instead of the labelled fixtures, set these environment variables before starting the application:

```
UNIVENTORY_RELEASE_APPROVALS_ADAPTER=workflow.adapters.ReleaseApprovals
UNIVENTORY_AUDIT_ADAPTER=audit.services.AuditService
```

For development only, set `DJANGO_DEBUG=true` and `DJANGO_SECURE_SSL_REDIRECT=false` when running locally over HTTP. Development sign-in and synthetic demo data are not KU SSO or real records. The `seed_demo` command works with these adapters.

Run `python manage.py run_work` regularly through a supervised scheduler. It processes due work once and exits. Hold expiry will not run automatically unless that scheduler is configured. Failed work items remain recorded after five attempts. The existing test command uses SQLite and fixture adapters by default; the release integration test switches to the new adapters.

## Still needed

- A complete review of request expiry, request revisions, quantity balances, repeat submissions, permission changes and all required approval stages.
- Complete concurrency testing on PostgreSQL, and end-to-end testing of reservation rejection, cancellation, multiple partial deliveries and discrepancy resolution. Cancellation of a committed reservation is currently blocked after any dispatch.
- Full inspection, maintenance and expenditure decisions, with a documented cost-service handoff and broader exception testing.
- Component recovery with linked child assets, retirement, specialist safety and data-clearing reviews, final-action cancellation, corrections and full evidence handling. Data-bearing, hazardous and regulated assets are currently blocked from the limited final-action flow.
- Full audit immutability at the database level, denied-attempt handling outside rolled-back transactions, audit scope for departmental auditors and delivery of all required notifications.
- A continuously supervised worker, operational monitoring and all required retry and timing tests.
- Responsive, accessibility and visual checks; screenshot evidence; presentation material; and integration with Jessica's AI and reporting modules.

The current tests are useful checks of implemented paths, not proof that all requirements or security and concurrency acceptance criteria have been met.
