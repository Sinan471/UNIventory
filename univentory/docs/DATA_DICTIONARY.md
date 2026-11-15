# Data dictionary: Jesher's entities

Phase 4–5 entities owned by Jesher (plan Section 7). Other members read them
through the contracts and never write their tables directly.

## Identity and reference data (`identity`)

| Entity | Key fields | Rules |
|--------|-----------|-------|
| Department | `code` (unique, A–Z/0–9/_/-), `name`, `name_ar`, `is_active` | deactivated, never deleted (FR-04) |
| Location | `code`, `name`, `site`, `campus`, `building`, `room`, `department` | inactive locations cannot be chosen for new records or moves |
| Category | `code`, `name`, `subcategories[]`, `spec_schema[]` (`key`, `label`, `type` text/integer/decimal/boolean, `unit`), `illustration` | specification values are validated against this schema |
| Role | `code`, `name`, `requires_department`, `is_specialist` | seeded by migration `identity.0002`; cannot be deleted |
| AppUser | `username`, `display_name`, `email`, `identity_issuer`, `identity_subject` (unique pair), `home_department`, `is_active` | no usable password stored; no Authenticator secret (DATA-06) |
| UserRole | `user`, `role`, `department` (null means campus-wide), `effective_from/to`, `granted_by`, `revoked_at/by`, `reason` | one open grant per scope; revoked, never deleted |

## Inventory (`inventory`)

### Asset
Identity: `asset_code` (`KU-YYYY-NNNNNN`), `tracking_type`
(INDIVIDUAL/BATCH), `title`, `description`, `category`, `subcategory`,
`tags[]`, `material`, `weight_kg`, `unit` (EA/SET/BOX are counted in whole
units; KG/L/M are measured), `registered_quantity`.
Responsibility: `legal_owner` (default Khalifa University), `department`,
`custodian`, `location`. These are kept separate (FR-10). For an individual
item they follow an accepted receipt.
Acquisition: `acquisition_date` or `acquisition_date_unknown`;
`estimated_value_aed` or `estimated_value_unknown`.
Restrictions: `ownership_restriction`, `restriction_notes`,
`release_rights_confirmed`, `is_hazardous`, `is_data_bearing`,
`is_regulated`, `handling_notes`.
Other: `specifications{}`, `provenance` (OPERATIONAL/PUBLIC_EXAMPLE/SYNTHETIC),
`record_status` (DRAFT/REGISTERED), `parent_asset` (component recovery),
`version` (optimistic lock).

### AssetPortion (the only quantity store)
`asset`, `parent`, `path` (lineage), `is_active_leaf`, `quantity` (≥ 0),
`department`, `location`, `custodian`, `temporary_custodian`, `condition`,
`lifecycle_state`, `safety_state` with `safety_evidence_ref`, `allocation`,
`claim_ref`, `listing_ref`, `version`.

These are separate state fields; there is no universal status:

| Field | Values |
|-------|--------|
| condition | UNKNOWN, POOR, FAIR, GOOD, EXCELLENT |
| lifecycle_state | DRAFT, IN_USE, AVAILABLE, UNDER_INSPECTION, UNDER_MAINTENANCE, IN_TRANSIT, RETIRED, DONATED, RECOVERED, RECYCLED, DISPOSED, LOST |
| safety_state | UNKNOWN, CLEARED, RESTRICTED |
| allocation | FREE, HELD, COMMITTED, FINAL_COMMITTED, SETTLED |

**Free quantity** is the sum of current portions that are AVAILABLE,
CLEARED and FREE. A held unit stays physically on hand; a safety block
overlays a claim and is not subtracted twice.

### AssetEvent (immutable ledger and history)
`asset`, `portion`, `related_portion`, `event_type`, `quantity`, `details{}`
(before/after, reason, result), `reference`, `evidence_refs[]`, `actor`,
`operation_key`, `operation_name`, `payload_hash`, `correlation_id`,
`occurred_at`. Update and delete raise errors.

### Attachment
`asset`, `context_ref`, `original_name` (sanitised), `stored_name` (random,
outside any public URL), `content_type`, `size_bytes`, `sha256`,
`access_class` (CATALOGUE_PHOTO/RESTRICTED), `status`
(ACCEPTED/QUARANTINED) with `status_reason`, `uploaded_by/at`,
`withdrawn_at/reason`.

## Catalogue (`catalogue`)

### Listing
`asset`, `department` (source), `portion` (provenance), `title`,
`public_description`, `offered_quantity` (> 0), `collection_info`, `state`
(DRAFT, AWAITING_RELEASE, PUBLISHED, PAUSED, WITHDRAWN, CLOSED),
`state_reason`, `release_case_ref`, `released_version`, `version`,
`created_by`, `published_at`. Each (asset, department) pair has at most one
open listing.

Listing free quantity = max(0, min(offered − units claimed through the
listing, reservable units of the asset in the source department that were
not claimed through it)).

## Not in the 38-entity model

`core.FixtureReleaseDecision` backs the labelled release-approval test
adapter only. Remove it when Sinan's ApprovalService is configured.
