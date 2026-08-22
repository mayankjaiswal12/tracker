# Progress

Live status, one row per module. Spec is `docs/roadmap.rst`; decisions are `plan.md`; the
narrative and the resume point are `task.md`.

**Update this file at the end of every session.** A row moves to Done only when its tests are
green *and* it has been looked at in Desk.

---

## Where we are — 2026-08-22

| | |
|---|---|
| Branch | `feat/phase-3-merchants` |
| Tests | **592 green**, ~69s |
| Site | `tracker.localhost`, one tracker: `Demo Household` (`TRK-00002`) |
| Shipped | Phase 1 complete · Phase 2: goals, budgets, recurring · **A1.1 tags · A1.3 merchants** |
| **Blocking** | **The manual Desk pass — owed since Phase 1, deferred four times** |

### The one thing owed

The manual Desk pass (`docs/manual-test-desk.md`). 592 automated tests say the arithmetic is
right; nothing yet says the app *looks* right. A headless pre-flight on 2026-08-20 confirmed
every figure and every widget lookup, so what remains is genuinely browser-only.

It gates all of A1. Nothing new should land on a Phase 1 nobody has looked at in a browser.

---

## Shipped

| Module | Date | Branch | Tests |
|---|---|---|---|
| `Money Merchant` — who the money went to | 2026-08-22 | `feat/phase-3-merchants` | ✅ tests, Desk unseen |
| `Money Tag` — labels that cut across categories | 2026-08-22 | `feat/phase-3-tags` | ✅ tests, Desk unseen |
| Ledger migration onto ERPNext JE/GL | 2026-08-14 | — | ✅ |
| Test suite | 2026-08-14 | — | ✅ |
| Number cards (9) | 2026-08-15 | — | ✅ |
| Readable IDs + category tree | 2026-08-15 | — | ✅ |
| Dashboard charts (5) + 4 sources | 2026-08-16 | — | ✅ |
| Demo fixtures | 2026-08-16 | — | ✅ |
| Workspace widget-label fix | 2026-08-17 | — | ✅ |
| `Money Goal` — six measures | 2026-08-17 | `feat/phase-2-goals` | ✅ |
| `Money Budget` — four periods, rollover, alerts | 2026-08-19 | `feat/phase-2-budgets` | ✅ |
| `Money Recurring Transaction` — six frequencies, nightly job | 2026-08-20 | `feat/phase-2-recurring` | ✅ |

---

## Part A · Expense-manager parity

Legend: ⬜ not started · 🟡 in progress · ✅ done · ⏸ deferred

### A1 — core missing functionality *(gated on the Desk pass)*

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| — | **Manual Desk pass** | 🟡 | `feat/phase-2-recurring` | Gate for everything below |
| A1.1 | Tags | 🟡 | `feat/phase-3-tags` | Code + 33 tests green; **Desk unseen**. Tag totals overlap by design; `total`/`tagged` measured without the join |
| A1.2 | Receipts and attachments | ⬜ | | OCR-ready columns filled by nothing until B5 |
| A1.3 | Merchant master | 🟡 | `feat/phase-3-merchants` | Code + 36 tests green; **Desk unseen**. `Data → Link` done; patch linked 49 refs to 12 records |
| A1.4 | Split transactions | ⬜ | | Strategy edit only — the engine does not change |
| A1.5 | Transfer fees | ⬜ | | Third leg in `strategies/transfer.py` |
| A1.6 | Reconciliation | ⬜ | | `reference_no`, `is_reconciled`, `cleared_date` |
| A1.7 | Bills and reminders | ⬜ | | A bill is a claim; a plan is a schedule |

### A2 — productivity

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| A2.1 | `Money Subscription` | ⬜ | | Boundary already drawn in `services/recurring.py` |
| A2.2 | `Money Loan` + `Loan Payment` strategy | ⬜ | | Clears one of nine `PLANNED` types |
| A2.3 | Budget completion | ⬜ | | Account-wise, custom range, templates |
| A2.4 | Recurring completion | ⬜ | | Skip Next, custom interval, pre-reminder |
| A2.5 | Saved views / calendar / global search | ⬜ | | Needs A1.1, A1.3 |
| A2.6 | Notification centre | ⬜ | | Needs A1.7 |

### A3 — analytics and reporting

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| A3.1 | `report/` — nine reports | ⬜ | | The directory does not exist yet |
| A3.2 | Print formats | ⬜ | | Account Statement, Monthly Summary |
| A3.3 | Chart drill-down + missing widgets | ⬜ | | |

### A4 — premium

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| A4.1 | Statement import | ⬜ | | `pypdf`/`openpyxl`/`xlrd` already installed |
| A4.2 | Investments and assets | ⬜ | | Clears the last four `PLANNED` strategies |
| A4.3 | Multi-currency reporting | ⬜ | | `enable_multi_currency` currently means nothing |
| A4.4 | API v1 + sync | ⬜ | | Mobile track |
| A4.5 | Backup + `track_changes` | ⬜ | | Mostly wiring core features |

---

## Part B · Financial Analyst System

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| B1 | Profile, confidence, as-of | ⬜ | | **Gate for B2** — see D4, D6 |
| B2 | `RATIOS` + `RULES` + arbitration | ⬜ | | Needs B1 |
| B3 | Market data + portfolio | ⬜ | | Needs A4.2. XIRR *and* TWR, HHI, counterfactual benchmark |
| B4 | Trends, quantile forecasts, scenarios | ⬜ | | Needs B2. Median/MAD, P10/P50/P90 |
| B5 | Advisor, compliance, feedback loop | ⬜ | | Needs B2 + B4 |
| B5b | Tier-1 ML | ⬜ | | Needs the feedback loop's labels |

---

## Notes from A1.3 (merchants)

- **Merchant rows partition the money; tag rows do not.** A transaction names one merchant or
  none, so `sum(rows) + unnamed == total` and a `share` percentage is meaningful. That is the
  one structural difference between `services/merchants.py` and `services/tags.py`, and it is
  why merchants get a pie-able figure and tags get a ranked bar.
- **The backfill does not guess.** The demo data carried "Netflix, Spotify", "Auto, bus" and
  "IRCTC, hotel" — the free-text field had been used as a note. Splitting on the comma would
  invent merchants ("hotel", "bus"), so each distinct string became one record verbatim.
  Merging two merchants is a decision somebody makes on purpose.
- **Two things the Link change broke silently, both caught by tests.** `_build_remark` was
  putting `MER-00007` into the Journal Entry remark that ERPNext's General Ledger prints; and
  `search_transactions` was running `LIKE '%dmart%'` against a column that now holds IDs, so
  every merchant search returned nothing. Anything searching by merchant must go through
  `merchants.search_names()` first.
- **Deleting a merchant clears the link and keeps the money** — the recurring-plan choice, not
  the tag choice: the spending really happened, it just no longer says who it was with.

---

## Notes from A1.1 (tags)

- **`Transaction.tags` is the only field on the doctype carrying `allow_on_submit`.** A tag
  reaches no `GL Entry`, so freezing it at submit protects nothing and costs the main use case
  — labelling a fortnight you have already entered. `validate` does not run on
  update-after-submit, so `on_update_after_submit` re-runs the tracker check.
- **`frappe.get_all` will group by a child-table field but cannot aggregate one.** Wrapping a
  backticked child field in `SUM()` makes the join parser read it as another table to join and
  emits invalid SQL. Group by the child field, sum the *parent's* amount, and use `COUNT(*)` —
  `COUNT(name)` is ambiguous across the join. This is why the app still has no raw SQL.
- **Tag totals overlap and must never be summed.** A transaction with two tags is counted in
  full under both. `total` and `tagged` are therefore measured by a second, un-joined query.

---

## Known open defects

Carried from `task.md`; none are blocking.

- `balances.get_net_worth` omits `"currency"` from its empty short-circuit → `KeyError` for a
  tracker with no accounts. Tests assert today's shape rather than papering over it.
- `Money Settings.allow_negative_balance` and `auto_post_transactions` both default to `1`, so
  `engine.check_sufficient_balance()` is a no-op on every site. Confirm that is intended before
  writing overdraft tests.
- `Money Payment Method.applies_to_account_type` is free-text `Data`, not validated.
- `Category.tracker` and `tracker` on Budget / Goal / Recurring are not `reqd`, unlike
  `Money Account.tracker` and `Transaction.tracker` — a scoping asymmetry worth a decision.
- Untracked cruft: `docs/How Money Tracker Works.html` + `_files/` — a saved snapshot of a
  deleted artifact, safe to remove.

---

## Log

| Date | What |
|---|---|
| 2026-08-22 | A1.3 merchants shipped; 592 tests. `Transaction.merchant` Data → Link, backfilled by `patches/v1_1/link_merchants`. Fixed a remark regression and a silently-broken merchant search. |
| 2026-08-22 | A1.1 tags shipped; 556 tests. Also fixed a Desk write-back that had left the workspace DB row at `col: 12` with a newer `modified` than the file, so migrate skipped it. |
| 2026-08-22 | Gap analysis against the expense-manager brief; `docs/roadmap.rst`, `plan.md`, `progress.md` added. No code. |
| 2026-08-20 | Recurring transactions shipped; 523 tests. |
| 2026-08-19 | Budgets shipped; 426 tests. |
| 2026-08-17 | Goals shipped; 339 tests. Workspace widget-label bug found and fixed. |
