# UNIventory demo guide

All people and records are synthetic. Development sign-in is a test adapter,
not KU SSO.

## 1. Set up (about 1 minute)

From the `univentory` folder:

```bash
.venv/Scripts/python -m pip install -r requirements.txt   # first time only
cp .env.example .env                                       # first time only
.venv/Scripts/python manage.py demo_reset --yes           # wipes the LOCAL SQLite database and rebuilds the demo
.venv/Scripts/python manage.py runserver
```

Open <http://127.0.0.1:8000/> and click a profile card to sign in. Sign out
from the account menu (top right). The theme starts dark; the moon/sun button
in the top bar switches to light and remembers the choice.

Run `demo_reset --yes` before each rehearsal. It only runs with
`DJANGO_DEBUG=true` and SQLite.

## 2. The cast: one person per job

| Person | Job | What they do in the demo |
|---|---|---|
| **Sara Ibrahim** | Requester, Chemistry | Asks for items, reserves them, confirms deliveries |
| **Mariam Al Hammadi** | Asset custodian | Lists surplus, publishes it, dispatches transfers, reports faults |
| **Khalid Al Suwaidi** | Department representative | Approves needs, releases listings, approves holds, transfers, repair spend and final actions |
| **Rashid Al Nuaimi** | Maintenance | Inspects defects, repairs, verifies a colleague's repair |
| **Reem Al Ketbi** | Impact and reports | Sustainability dashboard, reports, publishes a summary |
| **Salma Yousuf** | Auditor | Reads and exports the audit trail |
| **Hessa Al Mansoori** | Administrator | People, roles and reference data; no approval power |
| **Tariq Aziz** | No role yet | Signed in but sees nothing (access check) |

Colleagues such as Ali Mahmoud, Dana Yousef and Lina Haddad appear in the
records (six months of history, a second maintenance signature) but cannot
sign in, so the demo stays simple.

## 3. How the people connect

```
Mariam lists ──► Khalid releases ──► Mariam publishes ──► Sara requests
                                                              │
Sara confirms receipt ◄── Mariam dispatches ◄── Khalid approves need, hold, transfer
        │
        ▼
Reem sees it on Impact and Reports        Salma sees every step in Audit
```

Repairs: Mariam reports a defect ──► Rashid inspects ──► Khalid approves the
spend ──► Rashid repairs ──► a different technician verifies.

## 4. What is staged after a reset

| Who | Waiting on their Workbench |
|---|---|
| Sara | Confirm the last 2 monitors of a partial delivery |
| Mariam | Publish the sit-stand desks (released); dispatch 2 whiteboards (approved) |
| Khalid | 2 needs, drill listing to release, centrifuge hold, microscope transfer, balance repair spend, recycling proposal |
| Rashid | Hotplate defect to inspect; a document-camera repair to verify |
| Reem | Six months of reuse, savings, diversion and repair data |

## 5. Suggested 10-minute script

1. **Sign-in page.** One profile per job. Point out the KU SSO button (OIDC with PKCE) and that the demo profiles exist only on a development server.
2. **Khalid's Workbench.** Stat tiles, *Waiting on you* item cards, exchange activity chart and stock by category. Approve the **drill release** and the **centrifuge hold**.
3. **Mariam.** Workbench card *Ready to publish* ▸ **Publish** the desks. Open **Exchange**: category tiles, item cards and filters. Open an asset ▸ **Next steps** tab (sustainable-action advice).
4. **Sara.** Find the desks ▸ **Request this item** ▸ submit. On the request page show the progress track, quantity breakdown and **Suggested items** (AI matching with a factor breakdown). Then confirm the **last 2 monitors** on her Workbench: the partial delivery completes.
5. **Khalid.** Approve Sara's desk need, the hold and the transfer. Approve the **microscope transfer** too.
6. **Mariam.** Dispatch the desk to Sara (receiver Sara, a Chemistry location).
7. **Sara.** Confirm receipt. The request is now **Fulfilled**; the bell shows each step.
8. **Rashid.** Inspect the hotplate. Verify the document-camera repair (he did not do that repair, so he can verify it).
9. **Reem.** **Impact**: reused units, avoided purchases, net savings, carbon estimate, monthly trend, diversion donut, repair outcomes; open *How every figure is calculated*. **Reports**: volume chart, CSV export, **Draft a summary** ▸ add a wrong number ▸ **Publish** is blocked ▸ fix ▸ publish.
10. **Salma** ▸ Audit history. **Tariq** ▸ no access anywhere.

## 6. Practice runs: the full workflow, three more times

Three extra items are registered and safety-cleared after every reset but
**not yet listed**, so each can go through the whole exchange from the very
first step. They follow exactly the same workflow; only the details change.

| Run | Item (My Assets) | From | Stock | Sara asks for | Request title | Purpose |
|---|---|---|---|---|---|---|
| 1 | Herman Miller Sayl office chairs | Facilities | 6 | 2 | `Task chairs for the C-210 write-up desks` | `Replace two broken chairs at the write-up desks` |
| 2 | Jabra Speak 750 conference speakerphones | Facilities | 4 | 1 | `Speakerphone for the group meeting room` | `Hybrid group meetings with external collaborators` |
| 3 | Ohaus Pioneer precision balances | Mechanical Engineering | 4 | 2 | `Top-loading balances for the teaching lab` | `Two more weighing stations for first-year practicals` |

**The workflow (same for every run):**

1. **Mariam** ▸ My Assets ▸ open the item ▸ **Prepare listing** ▸ **Save draft** ▸ **Submit for release review**.
2. **Khalid** ▸ Workbench card *Listings to release* ▸ choose **Approve release** ▸ **Record decision**.
3. **Mariam** ▸ Workbench card *Ready to publish* ▸ **Publish to the exchange**.
4. **Sara** ▸ Exchange ▸ category tile ▸ the item ▸ **Request this item** ▸ title, quantity and purpose from the table, *Needed by* two weeks ahead, *Deliver to* a Chemistry location ▸ **Submit for approval**.
5. **Khalid** ▸ Workbench card *Needs to approve* ▸ **Approve need**.
6. **Sara** ▸ My Requests ▸ the request ▸ **Request a reservation** ▸ same quantity ▸ **Send for hold approval**.
7. **Khalid** ▸ Transfers ▸ the case ▸ **Approve hold**, then **Approve transfer**.
8. **Mariam** ▸ Workbench card *Ready to dispatch* ▸ **Dispatch**: same quantity, receiver Sara, a Chemistry location, custodian Mariam ▸ **Confirm dispatch**.
9. **Sara** ▸ Workbench card *Deliveries to confirm* ▸ **Confirm receipt** (same quantity). The request shows **Fulfilled**.

Tips: do one run end to end first, then do runs 2 and 3 side by side (one
step for each item before moving on) to show several requests moving at once.
For an AI variation on run 3, open the request after step 5 and use
**Suggested items** ▸ **Use this item** instead of *Request a reservation*.
Every run lands on Impact, Reports and Audit history. Run `demo_reset --yes`
to get all three back.

## 7. Talking points

* **Independence.** Nobody approves their own request; administrators have no approval power. The server enforces it, not hidden buttons.
* **Stock integrity.** A hold is only granted after a fresh stock check; twenty competing approvals for the last unit produce one hold. A repeated receipt has no second effect.
* **Only accepted units count.** Holds and dispatches never mark a need as fulfilled.
* **Evidence-based impact.** Every figure opens its formula and inputs; missing evidence is Unknown, never zero.
* **AI as assistance.** Matching, advice, the assistant and report drafting suggest; people decide. Suggestions marked *Assisted* run on the documented rule-based fallback because no live model is configured.

## 8. Honest limits

* KU SSO is built but needs KU's client registration.
* No live AI model is configured (see above).
* Hold expiry needs `python manage.py run_work` on a schedule.
* All figures come from synthetic records and demonstrate the formulas only.
