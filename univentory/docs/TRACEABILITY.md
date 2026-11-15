# Requirement traceability: Jesher's part

"Code" names the main implementation. "Evidence" names the automated tests
(`<module>/tests.py`) or the manual check still outstanding.

| Requirement | Code | Evidence |
|-------------|------|----------|
| FR-01 SSO, failure, cancel, logout | `identity/adapters.py`, `identity/views.py` | `SignInTests` (cancel, state mismatch, PKCE, nonce, logout). Live KU IdP integration still to be configured with KU IT |
| FR-02 role, department and assignment scope | `identity/policy.py`, `core/web.py` | `AccessPolicyTests`, `test_cross_department_record_is_not_disclosed`, `test_download_permissions` |
| FR-03 grant and revoke; revocation applies next | `identity/services.py` | `test_revocation_applies_to_next_request_in_same_session` |
| FR-04 reference data: deactivate, no duplicates | `identity/models.py`, `ReferenceDataService` | `ReferenceDataTests` |
| FR-05 asset fields; Unknown not invented | `inventory/models.py`, `InventoryService.register` | `test_register_retains_every_field_and_assigns_id`, `test_missing_history_must_be_explicitly_unknown` |
| FR-06 individual vs batch; linked splits | `InventoryLedger.split` | `test_split_conserves_quantity_and_links_records`, `test_individual_items_cannot_be_split` |
| FR-07 assigned edits; stale and invalid rejected | `InventoryService.update`, `InventoryLedger.adjust` | `test_edit_only_assigned_and_stale_edit_conflicts`, `test_invalid_values_rejected_with_field`, `test_adjustment_cannot_reduce_claimed_stock` |
| FR-08 evidence types, limits, permissions | `AttachmentService` | `AttachmentTests` |
| FR-09 dated history, actor and evidence | `AssetEvent`, asset History tab | `test_events_are_immutable_and_assets_not_deletable` |
| FR-10 owner, allocation, location and custody separated | ledger receipt and dispatch | `test_documented_ten_chair_example`, `test_individual_item_receipt_moves_responsibility` |
| FR-11 listing at most the releasable quantity | `CatalogueService.create` | `test_cannot_offer_more_than_releasable` |
| FR-12 release approval and blockers | `CatalogueService.publication_blockers` | `test_publication_requires_current_release_approval`, `test_each_blocking_condition_reported` |
| FR-13 pause, resume, withdraw, close | `CatalogueService.transition` | `test_publish_pause_resume_withdraw`, `test_resume_rechecks_eligibility` |
| FR-14 public fields only | `templates/catalogue/listing_detail.html` | `test_listing_page_hides_restricted_evidence` |
| FR-19 search, filters, sort | `CatalogueQueryService.search` | `test_keyword_and_filters`, `test_availability_filter_hides_fully_held` |
| FR-20 restricted records excluded, including counts | `CatalogueQueryService.visible` | `test_restricted_records_excluded_from_results_and_counts` |
| FR-57 Arabic framework and core labels | `LocaleMiddleware`, `locale/ar`, logical CSS | `test_arabic_layout_is_rtl`. **Fluent review outstanding** |
| FR-59 CSV import (optional) | not started | none |
| NFR-01 catalogue p95 ≤ 2 s | indexed subqueries, single photo query | `perf_catalogue` baseline (docs/OPERATIONS.md). **Reference-host run outstanding** |
| NFR-04 (inventory part) one hold for the last unit | listing row lock, `select_for_update`, version-guarded update | `test_twenty_competing_claims_one_success`, `test_last_unit_cannot_be_held_twice` |
| NFR-05 and NFR-07 safety blocks | ledger claim, commit and dispatch checks; `record_safety` | `test_unsafe_units_cannot_be_held_or_dispatched`, `test_new_safety_problem_blocks_held_units_without_releasing` |
| NFR-08 no passwords or Authenticator codes stored | `AppUser`, backend | `test_no_password_is_stored` |
| NFR-09 server-side permissions everywhere | policy at every view and service | access tests in identity, inventory and catalogue |
| NFR-10 HTTPS, encryption, secrets | settings, `core/backup.py` | `DeploymentSettingsTests`, `test_round_trip_is_encrypted_and_verified`, `check --deploy` |
| NFR-11 (uploads and forms) | `AttachmentService`, CSRF | `test_wrong_type_rejected_by_content_not_name`, `test_malicious_filename_is_sanitised`, quarantine test |
| NFR-14 30-minute inactivity | settings | `test_session_inactivity_limit_is_thirty_minutes` |
| NFR-15 (ledger) atomic rollback | caller-transaction requirement | `test_failed_transaction_leaves_no_partial_change`, `test_ledger_requires_caller_transaction` |
| NFR-17 backup and restore | `core/backup.py`, commands | `BackupTests`. **Timed restore exercise outstanding** |
| NFR-18 to NFR-20 usability, accessibility, browsers | design system, `/design/` | **Manual: 5-user test, keyboard review, Chrome/Edge/Firefox at 390 px still to do** |
| NFR-24 reproducible setup and regression tests | README, requirements, tests | **Another member must install from README** |
| BR-01, 03, 05, 13, 17 | policy, ledger, blockers, immutable models | tests listed above |
| DATA-01, 08, 09 | Asset model, validation, provenance, no deletes | inventory tests |
