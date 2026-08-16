# Manual test run — Desk

A click-through pass over everything Phase 1 implements. Every number below is
pre-computed, so you are checking arithmetic, not recomputing it.

Roughly 20 minutes. Nothing here needs the terminal except the two optional cross-checks.

---

## 0. Before you start

The bench dev server is already running (started 2026-08-12). If Desk does not load:

```bash
docker start frappe_bench2-mariadb-1 frappe_bench2-redis-cache-1 \
             frappe_bench2-redis-queue-1 frappe_bench2-frappe-1
docker exec -d -w /workspace/development/frappe-bench frappe_bench2-frappe-1 \
  bash -lc 'nohup bench start > /tmp/bench_start.log 2>&1 &'
```

- **URL:** http://tracker.localhost:8100/app
- **Login:** `Administrator`
- Go to **Money Tracker** in the sidebar (public workspace, all shortcuts live there).

> **If the bench cannot connect to MariaDB** after a Docker restart, the site's DB grant is
> pinned to the frappe container's old IP. See the environment note in `task.md`.

### Two Desk quirks to expect (not bugs in your data)

1. On **Transaction** and **Money Account**, `tracker` and `currency` are mandatory with no
   default. The controllers fill them server-side, but Desk's client-side check fires first,
   so **you must pick them by hand in the form.** The `Add Transaction` page (step 10) does
   not have this problem.
2. `Journal Entry`, `Ledger Account` and `Current Balance` are read-only and are written
   *after* submit. Reload the form (`Ctrl+R`) to see them populate.

### Existing data

Tracker **Demo Household** and its four accounts are the demo data
(`money_tracker/demo.py`), seeded 2026-08-16: 67 transactions over 2026-04-01 … 2026-08-15,
which is what the workspace cards and charts show. Ignore it for the posting steps — this
run creates its own `DT *` set so the numbers stay clean — and use it in §7, where the point
is that the widgets read a populated tracker.

The old `Verify Ledger` / `VL *` data this document used to mention was deleted on
2026-08-16, along with the user `vl.other@example.com`; the demo replaced it.

---

## 1. Money Settings is populated

**Money Tracker → Money Settings**

| Field | Expected |
|---|---|
| Company | `Trackify` |
| Base Currency | `INR` |
| The 8 parent account fields | **all blank** — correct; `services/coa.py` resolves them by name |

✅ If Company is blank, stop: nothing will post. Re-run `bench migrate`.

---

## 2. Create the tracker

**Money Tracker → Tracker → + Add Tracker**

| Field | Value |
|---|---|
| Tracker Name | `Desk Test` |
| Tracker Type | `Personal` |
| Owner User | `Administrator` |
| Base Currency | `INR` |

Save. Note the URL ends in a **hash**, not "Desk Test" — accounts are named by hash so two
users can both have a "Cash" account. The list still shows the readable title.

---

## 3. Create three accounts

**Money Tracker → Money Account → + Add Money Account**, three times:

| Account Name | Account Type | Tracker | Currency |
|---|---|---|---|
| `DT Bank` | `Bank` | `Desk Test` | `INR` |
| `DT SBI` | `Bank` | `Desk Test` | `INR` |
| `DT Card` | `Credit Card` | `Desk Test` | `INR` |

**After saving each, reload the form.** Check `Ledger Account`:

- `DT Bank - T` and `DT SBI - T` sit under **Bank Accounts - T**
- `DT Card - T` sits under **Current Liabilities - T**

✅ The point: you never picked a ledger account. `coa.py` created it.

> **Also worth seeing:** `DT Card`'s ERPNext account_type is blank, not "Credit Card" —
> ERPNext has no such account type. The card-ness lives on `Money Account.account_type`.

**Now try a duplicate:** create another account named `DT Bank` on tracker `Desk Test`.
✅ Expected: *"An account named DT Bank already exists on this tracker."*

---

## 4. Create two categories

**Money Tracker → Category** (opens as a **Tree** — that is the new NestedSet behaviour).

Use **+ Add Category**, or the tree's "Add Child":

| Category Name | Category Type | Tracker |
|---|---|---|
| `DT Food` | `Expense` | `Desk Test` |
| `DT Salary` | `Income` | `Desk Test` |

Reload each and confirm `Ledger Account`: `DT Food - T` under **Direct Expenses - T**,
`DT Salary - T` under **Direct Income - T**.

### Tree behaviour

1. Add a child under `DT Food`: name `DT Groceries`, type `Expense`, tracker `Desk Test`.
   ✅ It nests under DT Food in the tree and gets its own ledger account.
2. Add a child under `DT Food` with type **`Income`**.
   ✅ Expected refusal: *"A Income category cannot sit under the Expense category … Income
   and expense trees are separate."*

> Known cosmetic defect: that message prints the parent's name **hash** instead of
> "DT Food". Logged in `task.md`.

---

## 5. Post six transactions

**Money Tracker → Transaction → + Add Transaction** (the DocType form, not the page).

Use **date `2026-08-12`** for all six — the only Fiscal Year is 2026-04-01 → 2027-03-31, and
anything outside it throws. Set Tracker `Desk Test` and Currency `INR` every time.
**Save, then Submit** each one.

| # | Type | Amount | Account | Destination | Category |
|---|---|---|---|---|---|
| 1 | Income | 50000 | DT Bank | — | DT Salary |
| 2 | Expense | 2000 | DT Bank | — | DT Food |
| 3 | Expense | 3000 | DT Card | — | DT Food |
| 4 | Transfer | 8000 | DT Bank | DT SBI | *(hides itself)* |
| 5 | Credit Card Payment | 1000 | DT Bank | DT Card | *(hides itself)* |
| 6 | Refund | 500 | DT Bank | — | DT Food |

Notes as you go:

- The **Category** field disappears for Transfer and Credit Card Payment, and **Destination
  Account** appears — that is the `depends_on` doing its job.
- After each Submit, reload: **Journal Entry** is now filled in.
- ✅ **Nothing may fail with "Reference Type cannot be Transaction".** That bug was fixed by
  `patches/v1_0/allow_transaction_reference.py`. If you see it, the patch did not run.

### Try the guardrails

Note *when* each fires: amount and missing-destination are caught on **Save** (controller
`validate`), while the accounting rules are caught on **Submit**, because that is when the
strategy runs. So for most of these you must click Submit to see the error.

- **A refund against an Income category:** new Refund, category `DT Salary`.
  ✅ *"Category DT Salary is an Income category, but this is a Refund."*
- **A card payment into a bank account:** new Credit Card Payment, destination `DT SBI`.
  ✅ *"Destination Account DT SBI is a Bank, not a liability."*
- **A transfer to itself:** Transfer, account and destination both `DT Bank`.
  ✅ *"Source and destination accounts must be different."*
- **An unimplemented type:** Dividend, amount 100, account `DT Bank`.
  ✅ *"Transaction Type Dividend is not implemented yet. Supported types: …"*
- **Zero amount:** ✅ *"Amount must be greater than zero."*

---

## 6. Balances

**Money Tracker → Money Account** list. Add the **Current Balance** column if hidden.

| Account | Expected |
|---|---|
| DT Bank | **39,500** |
| DT SBI | **8,000** |
| DT Card | **2,000** |

Arithmetic: bank = 50000 − 2000 − 8000 − 1000 + 500. Card = 3000 charged − 1000 paid,
shown positive because it is what you *owe*.

> These are a cache, recomputed from `GL Entry` on every post — never incremented. If one
> looks wrong, that is a real bug, not a stale counter.

---

## 7. The dashboard

**Money Tracker** in the sidebar. Everything below reads the same six transactions you just
posted, so the numbers are the ones from step 6 seen a different way.

> The widgets are scoped to **one tracker** — `filters.tracker` if the widget names one,
> otherwise *your own* tracker, and with more than one that is the **earliest** you created.
> On `tracker.localhost` that is `Demo Household`, not `Desk Test`. To see the table below,
> open each card and chart's filter and set Tracker to `Desk Test`.
>
> Unfiltered, against the demo household, the cards read **Total Balance 3,32,550 · Net
> Worth 2,61,755 · Income This Month 1,20,000 · Expenses This Month 67,899 · Savings Rate
> 43.4%** (verified 2026-08-16). The current month is deliberately part-finished — the
> seeder skips future-dated rows — so those two month figures grow as the month does.

### The five Number Cards

| Card | Expected | Why |
|---|---|---|
| Total Balance | **47,500** | assets only: 39,500 + 8,000. The 2,000 card debt is *not* added |
| Net Worth | **45,500** | 47,500 − 2,000 owed |
| Income This Month | **50,000** | |
| Expenses This Month | **4,500** | 2,000 + 3,000 − 500 refund |
| Savings Rate | **91.0%** | (50,000 − 4,500) / 50,000 |

✅ **The key check:** Total Balance is 47,500, not 49,500. Every account is reported in its
natural direction, so the credit card's 2,000 comes back positive; adding it in would show
you *more* money the more you charged to the card.

✅ Each figure carries the **tracker's** currency symbol, because the card renders the
string server-side rather than handing the browser a bare number.

### The two charts

Both are `Custom` charts fed by the `Money Period Totals` source, monthly, last year.

- **Income vs Expense** (bar) — two series. This month: Income 50,000, Expense 4,500.
- **Spending Trend** (line) — the expense series alone.

✅ Thirteen labels, ending on the current month, even though only one month has any money
in it. An empty month is a period at zero, not a missing point.

✅ The transfer and the credit card payment appear in **neither** series — they moved money
without earning or spending it.

✅ Click the funnel on a chart → **Tracker** and **Series** filters, no doctype filter
fields. Set Series to `Income` and the bar chart drops to one series.

✅ Change **Monthly → Daily** in the chart's own toolbar: the money lands on today's date.

---

## 8. The ledger underneath

**Money Tracker → Journal Entry** — six entries, all **Submitted**.

Open the Transfer one:

- **Voucher Type** is `Contra Entry` (the Credit Card Payment is `Credit Card Entry`)
- Two rows, debit total == credit total
- Each row's **Reference Type** = `Transaction`, **Reference Name** = your TXN number —
  that is the back-link the Property Setter enables
- Each row carries **Tracker** = `Desk Test` — the accounting dimension

✅ **The key check:** open the Transfer and the Credit Card Payment and confirm **neither
touches an income or expense account.** A settlement between balance-sheet accounts can
never show up as spending.

✅ Open the Refund: it **credits `DT Food - T`**. It does not touch any income account —
that is what makes net Food spend read correctly instead of inflating both sides.

---

## 9. Reports (the payoff)

Every report below is **ERPNext's**, with a **Tracker** filter that exists only because
`Tracker` is registered as an Accounting Dimension. There is no reporting code in this app.

Common filters: Company `Trackify`, Tracker **`Desk Test`**, Fiscal Year `2026-2027`.
Balance Sheet, P&L and Cash Flow also want **From Fiscal Year** and **To Fiscal Year** =
`2026-2027`.

### Trial Balance

| Account | Debit | Credit |
|---|---|---|
| DT Bank - T | 50,500 | 11,000 |
| DT SBI - T | 8,000 | 0 |
| DT Card - T | 1,000 | 3,000 |
| DT Food - T | 5,000 | 500 |
| DT Salary - T | 0 | 50,000 |
| **Total** | **64,500** | **64,500** |

✅ Debits == credits. This is the §76 invariant, visible.

### Profit and Loss Statement

| Line | Expected |
|---|---|
| DT Salary (income) | **50,000** |
| DT Food (expense) | **4,500** (2000 + 3000 − 500 refund) |
| DT Bank / DT SBI / DT Card | **must not appear at all** |

✅ The transfer and the card payment are invisible here. That is the whole design.

### Balance Sheet

DT Bank **39,500**, DT SBI **8,000**, DT Card **2,000** — matching step 6 exactly.

### General Ledger

Filter by Tracker `Desk Test`: six vouchers. Clear the Tracker filter and the demo
household's rows appear too — proving the filter is doing real work.

### Cash Flow

Renders without error for `2026-2027`.

---

## 10. The Add Transaction page

**Money Tracker → Add Transaction** (custom page, not a DocType form).

Post an Expense: amount `250`, account `DT Bank`, category `DT Food`.

✅ Expected: green toast *"Transaction TXN-000xx posted"*, form resets, and **DT Bank drops
to 39,250** with **DT Food** rising to 4,750.

Switch Type to **Transfer**: the Category field hides and Destination Account appears.

> This page only offers Expense / Income / Transfer — it is a Phase 1 stub. It calls
> `api.transactions.create_transaction`, which inserts *and* submits in one step, so there
> is no draft.

**Undo it before continuing** (so the numbers below still hold): open TXN for the 250,
**Cancel** it.

---

## 11. Cancel and reversal

Open the **2,000 Expense** (#2). Menu → **Cancel**.

✅ Check all of:

| What | Expected |
|---|---|
| Transaction | **Cancelled** |
| Its Journal Entry | **Cancelled** — not deleted |
| DT Bank balance | **41,500** (39,500 + 2,000 back) |
| P&L → DT Food | **2,500** (4,500 − 2,000) |
| Journal Entry → **GL Entry** for that voucher | **4 rows**, all `is_cancelled = 1` — the 2 originals plus 2 reversing rows, netting to zero |

✅ History is preserved. Nothing was erased.

**Now try to delete it:** with the cancelled transaction open, Menu → **Delete**.
✅ Expected: *"Cannot delete a posted transaction. Cancel it instead, which reverses the
ledger entries."*

**And try deleting an account in use:** open `DT Bank`, Menu → Delete.
✅ *"Cannot delete an account that has transactions against it."*

---

## 12. Row-level security (the important one)

All books share one ERPNext Company, so `permissions.py` is the **only** thing separating
users. Test it for real, not by reading code.

1. **User list → + Add User:** email `dt.other@example.com`, first name `DT Other`.
2. Roles: tick **Finance User** only. **Do not** give System Manager or Finance Manager —
   both are deliberately unrestricted.
3. On that user: **Menu → Set New Password** (or Reset Password), and set one you know.
4. Open an **incognito window** → http://tracker.localhost:8100/app → log in as
   `dt.other@example.com`.

✅ Expected as that user:

| Where | Expected |
|---|---|
| Transaction list | **empty** |
| Money Account list | **empty** |
| Category tree | **empty** |
| Tracker list | **empty** |
| Paste a TXN URL from your Administrator session | **Not permitted** |

❌ **If even one row of `Desk Test` or `Demo Household` data is visible, that is a security
bug — stop and report it.**

> Why empty rather than an error: `tracker_scoped_query_conditions` returns `1 = 0` for a
> user who owns no tracker. Returning `""` would mean "no restriction" and leak everything.

Optionally, still as that user, create a tracker and an account of their own and confirm
they see *only* those.

---

## 13. Cleanup (optional)

Desk will not let you delete a submitted transaction, so:

1. Cancel each `Desk Test` transaction, then delete it.
2. Delete `DT Groceries`, `DT Food`, `DT Salary`.
3. Delete `DT Bank`, `DT SBI`, `DT Card`.
4. Delete tracker `Desk Test`, and user `dt.other@example.com`.

Two things deliberately survive and are safe to leave:

- The **ERPNext Accounts** (`DT Bank - T` etc.) — deleting a Money Account does not remove
  its ledger account.
- The **cancelled Journal Entries and their GL rows** — cancelled, never deleted, by design.

---

## What this run does *not* cover

- `Transaction.reverse()` — implemented, no UI button, never exercised
- Multi-currency (`fx.py`) — everything here is INR
- The nine `strategies.PLANNED` types — step 5 only proves they refuse cleanly
- Overdraft blocking — `Money Settings.allow_negative_balance` defaults to `1`, so
  `check_sufficient_balance()` is currently a no-op. To test it, untick that box, then try
  spending more than `DT Bank` holds.
