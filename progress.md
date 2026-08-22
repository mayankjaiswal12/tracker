# Progress

Live status, one row per module. Spec is `docs/roadmap.rst`; decisions are `plan.md`; the
narrative and the resume point are `task.md`.

**Update this file at the end of every session.** A row moves to Done only when its tests are
green *and* it has been looked at in Desk.

---

## Where we are — 2026-08-22

| | |
|---|---|
| Branch | `feat/phase-3-a1-rest` |
| Tests | **716 green**, ~89s |
| Site | `tracker.localhost`, one tracker: `Demo Household` (`TRK-00002`) |
| Shipped | Phase 1 complete · Phase 2: goals, budgets, recurring · **A1.1 tags · A1.3 merchants · A1.4 splits · A1.5 transfer fees · **A1 complete** |
| **Blocking** | **The manual Desk pass — owed since Phase 1, deferred four times** |

### The one thing owed — now actually clickable

The manual Desk pass (`docs/manual-test-desk.md`). 716 automated tests say the arithmetic is
right; nothing yet says the app *looks* right. A headless pre-flight on 2026-08-20 confirmed
every figure and every widget lookup, so what remains is genuinely browser-only.

It gates all of A1. Nothing new should land on a Phase 1 nobody has looked at in a browser.

---

## Shipped

| Module | Date | Branch | Tests |
|---|---|---|---|
| `Money Bill` — money owed, tracked until settled | 2026-08-22 | `feat/phase-3-a1-rest` | ✅ tests, Desk unseen |
| `Money Receipt` — the paper behind a transaction | 2026-08-22 | `feat/phase-3-a1-rest` | ✅ tests, Desk unseen |
| Reconciliation — ticking off against a statement | 2026-08-22 | `feat/phase-3-a1-rest` | ✅ tests, Desk unseen |
| Transfer & card-payment fees | 2026-08-22 | `feat/phase-3-transfer-fees` | ✅ tests, Desk unseen |
| `Money Transaction Split` — one payment, several categories | 2026-08-22 | `feat/phase-3-splits` | ✅ tests, Desk unseen |
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

### A1 — core missing functionality — **all seven built, none seen in Desk**

| | Module | Status | Branch | Notes |
|---|---|---|---|---|
| — | **Manual Desk pass** | 🟡 | `feat/phase-2-recurring` | Gate for everything below |
| A1.1 | Tags | 🟡 | `feat/phase-3-tags` | Code + 33 tests green; **Desk unseen**. Tag totals overlap by design; `total`/`tagged` measured without the join |
| A1.2 | Receipts and attachments | 🟡 | `feat/phase-3-a1-rest` | 15 tests. Standalone doctype, not a child table — paper is captured before it is entered |
| A1.3 | Merchant master | 🟡 | `feat/phase-3-merchants` | Code + 36 tests green; **Desk unseen**. `Data → Link` done; patch linked 49 refs to 12 records |
| A1.4 | Split transactions | 🟡 | `feat/phase-3-splits` | Code + 25 tests green; **Desk unseen**. Engine untouched, as designed |
| A1.5 | Transfer fees | 🟡 | `feat/phase-3-transfer-fees` | Code + 22 tests green; **Desk unseen**. Restated the balance-sheet-only invariant |
| A1.6 | Reconciliation | 🟡 | `feat/phase-3-a1-rest` | 20 tests. Changes no money; no adjustment entry, on purpose |
| A1.7 | Bills and reminders | 🟡 | `feat/phase-3-a1-rest` | 41 tests. Mark Paid posts and mints the next; daily reminder job |

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

## Notes from closing the Desk gaps

- **Three A1 modules had no UI at all.** The bill cards existed as API methods with no Number
  Card fixtures, `mark_paid` was whitelisted but had no button, and the reconciliation service
  had nothing calling it. Built as backend, never wired.
- **`clear_demo_data` was leaving orphaned child rows.** Transactions are removed by raw table
  delete — deliberately, since there can be hundreds and the GL rows go separately — which
  bypasses `delete_doc` and never touched child tables. Correct until A1 gave `Transaction`
  two of them. `demo.TRANSACTION_CHILD_TABLES` now names them and a test derives the same list
  from the doctype meta, so adding a third and forgetting the teardown fails rather than
  orphaning rows.
- **Two demo day references pointed at the wrong rows.** `DEMO_TAGGED` named day 10, which is a
  **Transfer** — tagging one is legal and completely invisible, since a movement has no category
  and never appears in the Expense view. It read as a working demo with an empty chart bar. Both
  the missing-day and the not-an-expense cases now throw.
- **`transactions_posted` now counts the tracker rather than the plan loop.** The loop knows
  about MONTHLY and ONE_OFFS; it did not know about the split that is cancelled and re-posted
  or the transfer carrying a fee.

---

## Notes from A1.2 / A1.6 / A1.7

- **A receipt is a standalone doctype, not a child table**, and `transaction` is optional.
  Paper is photographed at the till and typed up on Sunday; a child row cannot exist without a
  parent. That also makes the unattached ones a real thing to show — an inbox.
- **Reconciliation changes no money and offers no adjustment entry.** If the difference does
  not close, the answer is a missing or wrong transaction. An app that plugs the gap has
  stopped being a ledger.
- **A bill is a claim; a plan is a schedule.** The giveaway is *overdue* — a state a standing
  order cannot have. If a plan has not posted the scheduler is broken; if a bill has not been
  paid, a person has not paid it. They compose: a bill may name the plan that settles it.
- **A repeating bill mints its successor when it is paid**, one open bill at a time. Twelve
  unpaid rows up front would make "what do I owe" meaningless and fire every reminder eleven
  times.
- **Bill names are unique per tracker only among *unpaid* bills** — unlike every other master
  here — because a repeating bill reuses its own name every month.

---

## Notes from A1.5 (transfer fees)

- **A documented invariant had to be restated, not worked around.** "Transfers and card
  payments touch only balance-sheet accounts" was true and is now too strong: a fee is
  spending, because the bank kept it. `docs/architecture.md` now says the *movement* is
  balance-sheet only, and names the fee as the deliberate exception.
- **The source pays `amount + fee`; the destination receives `amount`.** Netting the fee out
  of what arrives would leave both balances right and understate expenses.
- **Third aggregation site in three modules.** Splits and fees both attach money to a category
  from a voucher whose own `category` is empty, and both had to be added to
  `get_category_totals` *and* `get_net_spend_by_date`. Any future way of attaching money to a
  category needs the same two edits — that is now a pattern worth watching, not a coincidence.

---

## Notes from A1.4 (splits)

- **The engine was not touched.** Split posting is entirely a strategy edit — N debits against
  one credit — and `engine.validate_balanced` was already the only invariant it needed. The
  pure tests in `test_strategies.py` never mention the engine, which is the point.
- **A split transaction has no `category` of its own; the controller clears it.** Keeping a
  "primary" category alongside the rows would be double-counted by everything that sums
  categories.
- **Two aggregation traps, one caught only by a test.** `get_category_totals` was safe because
  it filters `category in (...)` and a split parent's is empty. `get_net_spend_by_date` was
  not: a whole-tracker budget applies no category filter, so the parent's full amount was
  counted *and* its shares added on top — 2,000 for a 1,000 bill. Split parents are now
  excluded from the unsplit query explicitly.
- **Budgets measure through `get_net_spend_by_date`**, so making that split-aware is what stops
  a split grocery bill from vanishing out of the Groceries envelope.

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
| 2026-08-22 | **A1 complete.** Receipts, reconciliation and bills shipped; 715 tests. |
| 2026-08-22 | A1.5 transfer fees shipped; 639 tests. Restated the balance-sheet-only invariant in architecture.md. |
| 2026-08-22 | A1.4 splits shipped; 617 tests. Category roll-ups and budgets made split-aware; fixed a whole-tracker budget double-count. |
| 2026-08-22 | A1.3 merchants shipped; 592 tests. `Transaction.merchant` Data → Link, backfilled by `patches/v1_1/link_merchants`. Fixed a remark regression and a silently-broken merchant search. |
| 2026-08-22 | A1.1 tags shipped; 556 tests. Also fixed a Desk write-back that had left the workspace DB row at `col: 12` with a newer `modified` than the file, so migrate skipped it. |
| 2026-08-22 | Gap analysis against the expense-manager brief; `docs/roadmap.rst`, `plan.md`, `progress.md` added. No code. |
| 2026-08-20 | Recurring transactions shipped; 523 tests. |
| 2026-08-19 | Budgets shipped; 426 tests. |
| 2026-08-17 | Goals shipped; 339 tests. Workspace widget-label bug found and fixed. |
