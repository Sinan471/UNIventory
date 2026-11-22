# Implementation plan review (22 November 2026)

A check of `UNIventory_Three_Member_Implementation_Plan.docx` against the
Phase 1 to 5 documents and against the code on branch
`feature/demo-ready-navy-ui`. "Done in this pass" marks work added on this
branch; "Open" items are not implemented and are listed so the team can plan
Phase 7.

## 1. Is the plan consistent with the documents?

Mostly yes. The plan follows Phase 3 (requirements) and Phase 4-5 (design):
modular Django monolith, server-rendered forms, append-only audit,
transactional outbox, RP-1 ranking weights, 48-hour holds, accepted receipt as
the only fulfilment, separate states per record type, and the same FR/AI/NFR
numbering. Points to correct or confirm:

| Topic | Documents say | Plan says | Recommendation |
|---|---|---|---|
| Who approves transfers | Phase 3 BR-02 and 5.5.1: an **Authorised Approver** approves transfers, service spend and final actions | Same, but the code uses the receiving **Department Representative** for transfers and the source representative for service and final actions | Either record this as a prototype decision (TBD-01) or route these stages to the `APPROVER` role. The role exists and is seeded but no workflow uses it |
| Release review owner | Phase 3: owning department representative | Plan: Jesher's catalogue calls Sinan's approval interface | Implemented as specified (`workflow.adapters.ReleaseApprovals`) |
| Matching top-N | Phase 3 AC-05 evaluates top three | Plan shows five and keeps top-three evaluation separate | Consistent; the UI shows up to five |
| AI model | Phase 2/4-5 name gpt-6-astra and text-embedding-3-large | Plan says verify the callable identifier before integration | No provider is configured; all AI features run the labelled fallback (see section 3) |
| Visual direction | Plan section 13: warm canvas `#F6F4EE`, green primary | The team now wants a navy theme | Changed in this pass to "harbour navy" (section 4); the plan's section 13 should be updated to match |

## 2. Coverage of the core feature screenshot (plan section 2)

| ID | Feature | Status |
|---|---|---|
| C1 | Login and roles | Done: OIDC/PKCE adapter, roles with department scope, revocation on next request, 30-minute expiry. Live KU IdP registration outstanding |
| C2 | Departments and assets | Done: full asset record, batches and splits, evidence, ledger |
| C3 | Publish and search | Done: release before publish, nine filters, scoped counts |
| C4 | Request and track | Done; **this pass** added the missing FR-15 fields (category, minimum condition, destination), past-date rejection, a progress track and the full quantity breakdown |
| C5 | Approve and transfer | Done: independent approval, 20-way race test, partial receipt, replay protection |
| C6 | States and history | Done: separate state fields and immutable history |
| C7 | Sustainability dashboard | **Done in this pass**: `/sustainability/` with all seven indicators, formula, inputs, unit, status and version per measure; Unknown and Not applicable kept distinct |
| C8 | Notifications | Done; **this pass** added the unread filter, mark-all-read and a bell with an unread count |
| C9 | Basic report | **Done in this pass**: `/reporting/` request and transfer tables, period, department and status filters, UTF-8 CSV with formula neutralisation and an audit entry per export |

## 3. Coverage of the AI feature screenshot (plan section 3)

No live model is configured, so every AI feature runs the deterministic
fallback that AI-18 requires and says so on screen. The controls around the
model (scope, review, provenance, refusal to act) are real.

| Feature | Status |
|---|---|
| AI 1 Classification | **Done in this pass (fallback)**: "Suggest a category" widget in the asset editor; evidence words, Needs review or Sufficient evidence, custodian applies it; AIRun recorded |
| AI 2 Matching and ranking | **Done in this pass**: up to five eligible items on the request page, RP-1 factor bars, unknown factors excluded rather than zeroed, partial supply labelled, category and minimum condition enforced before ranking, accept/reject stored as MatchRecommendation and RecommendationReview, recheck before reserving (AI-17). Fixed a bug that sorted the worst match first |
| AI 3 Sustainable-action advice | **Done in this pass (fallback)**: "Next steps" tab on each asset comparing all nine options with blocked and evidence-needed states |
| AI 4 Assistant | **Done in this pass (fallback)**: grounded catalogue search, own-request status, approved guidance with sources, "I could not find" when there is no evidence, request preview that needs an explicit confirmation and creates a draft through the normal service |
| AI 5 Generated report | **Done in this pass**: snapshot, narrative draft, human edit, publish; publication is blocked when a number in the text is not in the snapshot; published versions are immutable |

## 4. Visual direction (plan section 13): redesigned in this pass

* Palette: deep navy rail `#0D1B34` with a faint blueprint grid, porcelain
  canvas `#EEF1F6`, paper surfaces `#F8FAFC` (no pure white), navy primary
  `#1F4E9C`, brass `#B8892B` only for asset-tag plates and "waiting on you"
  counts. Contrast pairs are listed in `static/design/tokens.css`.
* Type: IBM Plex Sans, Plex Sans Condensed for headings and figures, Plex Mono
  only for KU asset IDs, Plex Sans Arabic for Arabic. All self-hosted (OFL).
* Every page by every member now uses the shared components. Sinan's and
  Jessica's templates previously used class names that did not exist, so they
  rendered as unstyled browser defaults; they have been rewritten.
* New: role-aware Workbench home page, progress tracks for requests,
  reservations, repairs and final actions, decision panels for approvals and
  persona sign-in for the demo.

## 5. Security review

Fixed in this pass:

| Issue | Risk | Fix |
|---|---|---|
| `/ai/monitoring/` used `login_required` only | Any signed-in account, including one with no role, could read every AI run and user | Restricted to administrator, sustainability, management and auditor roles |
| `/reporting/export/<id>/` exported any snapshot to any signed-in user, without formula neutralisation | Cross-department disclosure; CSV formula injection (FR-49, NFR-11) | Scope check per department, draft visibility rule, shared `core/csvsafe.py` |
| Audit CSV neutralised `= + - @` only | Tab and carriage-return prefixes still executable in some spreadsheets | Uses the shared helper |
| No Content Security Policy | Any injected markup could load scripts | Django 6 CSP: scripts, fonts, images and connections only from this origin; no framing; forms post only here |
| Hardening headers only when DEBUG is off | Weaker local and staging environments | nosniff, same-origin referrer, COOP and frame denial in every environment |
| Development sign-in crashed on a non-numeric id | Error page instead of a refusal | Validated; returns 404 |
| `.env` values leaked into the test run | Tests used the real adapters and one test failed | `config/test_settings.py` pins the fixture adapters |

Checked and sound: server-side permission checks in every view and service,
no self-approval, CSRF on every POST, safe `next` redirects, DEBUG-only test
sign-in limited to `dev-test` identities, uploads checked by content, no raw
SQL, no `|safe` or `mark_safe` on user content, secrets only from the
environment and `.env` git-ignored.

Still to do before any hosted pilot: run `manage.py check --deploy` with
`DJANGO_DEBUG=false`, add login rate limiting at the proxy, enforce audit
immutability at database level (trigger or permissions), and register the KU
OIDC client.

## 6. Open items (not done)

| Item | Requirement | Owner per plan |
|---|---|---|
| Hold-expiry and notice worker running continuously | FR-23, NFR-03 | Sinan (needs a scheduler for `run_work`) |
| Request revision after approval (new version, supersede approvals) | FR-17, FR-29, BR-08 | Sinan |
| Request expiry at the required date | Phase 3 6.2.2 | Sinan |
| Component recovery with child assets; retirement; specialist clearance flow | FR-44 to FR-47 | Sinan |
| Authorised Approver role in routing (see section 1) | BR-02, 5.5.1 | Sinan |
| Reuse rate on a defined cohort | SUS-02 | Jessica |
| Live model integration, spend ceiling notices at 70%/85% | AI-14 to AI-19 | Jessica |
| Held-out AI evaluation (60 classification, 20 matching cases) | AC-04, AC-05 | Jessica |
| CSV asset import | FR-59 (optional) | Jesher |
| PostgreSQL concurrency run, p95 timing on the reference host, restore drill | NFR-01, NFR-04, NFR-17 | Jesher, Sinan |
| Fluent Arabic review of labels; new strings from this pass are English only | FR-57 | Jesher and each owner |
| Five-user usability test | NFR-18 | All |
| CODEOWNERS once GitHub handles are confirmed | Plan section 8 | Jesher |

## 7. Ownership note

The plan gives each file one owner. This pass changed files owned by Sinan
(`demand`, `workflow`, `exchange`, `care`, `final_actions`, `notifications`,
`audit` templates and small view changes) and Jessica (`ai`, `sustainability`,
`reporting`). Please review those diffs with them and record the handoff
before merging, as section 8 of the plan requires.
