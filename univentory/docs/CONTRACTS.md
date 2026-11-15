# Contracts v1.0 (owner: Jesher)

These are the interfaces from plan Section 9 that Jesher's modules provide
or consume. They are frozen for parallel work. To change one, add a
versioned field; do not silently rename a consumed field.

## Common rules

* Every consequential command takes an `ActorContext(user, operation_key,
  correlation_id)` (`core.contracts`). Permissions are always derived on the
  server from `user`. A client-supplied role or department is never
  authority.
* Errors are typed (`core.contracts.errors`) and map to HTTP outcomes:

| Exception | Status | Meaning |
|-----------|--------|---------|
| `ValidationFailed` | 422 | invalid input; `field_errors` names the fields |
| `NotPermitted` | 403 | the actor lacks authority (nothing changed) |
| `HiddenRecord` | 404 | missing or not visible (non-disclosing) |
| `StaleVersion` | 409 | the expected version is out of date; reload |
| `StockConflict` | 409 | the quantity is no longer available or the state forbids it |
| `DuplicateOperationConflict` | 409 | an operation key was reused for different input |

* **Operation keys.** Repeating a ledger command with the same key, actor
  and payload returns the original result. Reusing the key for different
  input raises `DuplicateOperationConflict`.
* **Transactions.** Every `InventoryLedger` method requires the caller's
  `transaction.atomic()` block and raises `RuntimeError` otherwise.
  Workflow, ledger, audit and outbox rows then commit or roll back together.

## Provided by Jesher

### AccessPolicy (`identity.policy`)

`has_role(user, code, department=None)`, `departments_with_role`,
`role_codes`, `has_any_role`, `can_browse_catalogue`, `can_register_asset`,
`can_edit_asset(user, asset)`, `can_view_asset_record(user, asset)`,
`asset_record_scope(user)` (a Q filter, applied before counting), and
`can_manage_listing`. Grants are re-read on every request, so a revocation
applies to the next action.

### AssetQueryService (`inventory.services`)

* `records_for(user)` returns the scoped Asset queryset.
* `get_record(user, asset_id)` returns the asset or raises `HiddenRecord`.
* `current_portions(asset)` and `quantity_summary(asset)` return free, held,
  committed, in-transit, blocked and final quantities.
* `history(user, asset)` returns the immutable `AssetEvent`s.
* `portion_view(user, portion_id)` returns a dict with version, quantity,
  unit, condition, lifecycle, safety, allocation, claim_ref and
  `is_reservable_unit`.

### CatalogueService / CatalogueQueryService (`catalogue.services`)

* `CatalogueService.free_quantity(listing)` is 0 unless the listing is
  Published.
* `CatalogueService.hold(actor, *, listing_id, quantity, claim_ref)` returns
  the held portion IDs. It locks the listing, rechecks release, safety and
  free stock, and claims through the ledger. Reservation approval must call
  this; submitting a request or seeing a match reserves nothing.
* `CatalogueQueryService.visible(user)` and `search(user, params)` return
  only the listings this user may see. Jessica's retrieval must start from
  `visible(user)`.

### InventoryLedger (`inventory.ledger`)

| Method | Use (caller) | Effect |
|--------|--------------|--------|
| `claim(actor, candidate_portion_ids=, quantity=, claim_ref=, allocation=HELD or FINAL_COMMITTED)` | final-action approval (Sinan); holds go through `CatalogueService.hold` | splits off claimed units |
| `commit(actor, claim_ref=)` | transfer approval | HELD to COMMITTED; ends hold expiry |
| `release_claim(actor, claim_ref=, quantity=None, reason=)` | expiry, cancellation | undispatched units return to FREE once |
| `dispatch(actor, claim_ref=, quantity=, consignment_ref=, temporary_custodian=)` | dispatch | committed units to IN_TRANSIT with `claim_ref=consignment_ref` |
| `accept_receipt(actor, consignment_ref=, quantity=, department=, location=, custodian=, lifecycle_state=IN_USE, receipt_ref=)` | assigned receipt | accepted part moves allocation, custody and location; legal owner unchanged |
| `record_return(actor, consignment_ref=, quantity=, location=)` | physical return | units go UNDER_INSPECTION |
| `record_lost(actor, consignment_ref=, quantity=, reference=)` | authorised loss | LOST; never available again |
| `change_lifecycle(actor, portion_id, to_state, quantity=None, reference=, reason=)` | inspection, maintenance, retirement | validated transition table |
| `record_condition(...)`, `record_safety(actor, portion_id, safety_state, evidence_ref=)` | care (Sinan) | a restriction overlays claims immediately (NFR-07) |
| `execute_final(actor, claim_ref=, quantity=, outcome=, reference=, evidence_refs=[...])` | final execution | applies DONATED, RECOVERED, RECYCLED or DISPOSED once for the executed quantity |
| `verify_conservation(asset)` | tests, monitoring | checks current quantity equals registered quantity plus adjustments |

`InventoryService.create_recovered_asset(actor, parent_asset=, data=,
final_action_ref=)` creates a linked component-recovery child record.

### Attachments (`inventory.services.AttachmentService`)

`store(actor, asset, file, access_class=, context_ref="receipt:9")` lets
another module file evidence against an asset (for example receipt photos).
Access follows the asset scope. `open_for(user, attachment_id)` rechecks
access and the file hash.

## Consumed by Jesher (provided by others)

| Port | Setting | Provider | Test adapter in use now |
|------|---------|----------|-------------------------|
| `ReleaseApprovalPort` (`core.contracts.approvals`): `request_release(listing, actor)`, `current_decision(listing)`, `supersede(listing, actor, reason)` | `UNIVENTORY_RELEASE_APPROVALS_ADAPTER` | Sinan, ApprovalService | `FixtureReleaseApprovals`: enforces owning-department rep and no self-approval; adds a fixture queue at `/exchange/release-reviews/` |
| `AuditSink` (`core.contracts.audit`): `record(entry)`, `record_denied(entry)` inside the caller's transaction | `UNIVENTORY_AUDIT_ADAPTER` | Sinan, AuditService | `LoggingAuditSink` (structured log lines) |

While a test adapter is configured, every page shows a banner, and the
release decision shows a "Test adapter" badge. Do not use test adapters in
the final demonstration (plan Section 16).

## UI mount points

* `templates/inventory/asset_form.html` has
  `<div data-mount="classification" data-form="asset-form" data-asset="">`
  for Jessica's classification widget. It must only fill form fields; the
  custodian saves through the normal form.
* `templates/shared/base.html` has `{% block notifications_slot %}` (Sinan)
  and `{% block assistant_slot %}` (Jessica).
* `catalogue/views.py::_request_url` links "Request this item" to
  `demand:new_from_listing` once that route exists (Sinan).
