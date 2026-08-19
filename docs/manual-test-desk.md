# Manual test run — Desk

A click-through pass over everything Phase 1 implements, plus the goals that opened Phase 2
(§13). Every number below is pre-computed and was verified against the ledger — 2026-08-16
for §1–§12, 2026-08-17 for §13 — so you are checking arithmetic, not recomputing it.

Roughly 30 minutes. Nothing here needs the terminal except the two optional cross-checks.

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
seven goals added 2026-08-17 and **five budgets added 2026-08-19**, which is what the
workspace cards and charts show. Ignore it for the posting steps — this
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

Save. Note the URL ends in **`TRK-0000x`**, not "Desk Test" — trackers, accounts, categories
and goals are named by series so two users can both have a "Cash" account. The list still
shows the readable title. (They were named by *hash* until 2026-08-15; this document said so
until 2026-08-17.)

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
   ✅ Expected refusal first: *"Category DT Food is not a group. Tick Is Group on it before
   nesting anything under it."* Tick **Is Group** on `DT Food`, save, and add the child again.
   ✅ It nests under DT Food in the tree and gets its own ledger account, `DT Groceries - T`.
   ✅ Reload `DT Food`: its **Ledger Account is now empty**. A heading holds no money — and
   the old account is *dropped*, never deleted, because another tracker's Food category may
   be sharing it.
   ✅ From here on, **`DT Food` cannot be posted to**: it is a heading, and §5 files spending
   under `DT Groceries` instead. Try an Expense against `DT Food` if you want to see it
   refused — *"DT Food is a group category. Post to one of its sub-categories instead."*
2. Add a child under `DT Food` with type **`Income`**.
   ✅ Expected refusal: *"A Income category cannot sit under the Expense category … Income
   and expense trees are separate."*

> That message used to print the parent's name **hash**; it was fixed on 2026-08-12 in the
> ID-consistency pass, so it should now read "DT Food". If you see a hash, that is a
> regression.

---

## 5. Post six transactions

**Money Tracker → Transaction → + Add Transaction** (the DocType form, not the page).

Use **date `2026-08-12`** for all six — the only Fiscal Year is 2026-04-01 → 2027-03-31, and
anything outside it throws. Set Tracker `Desk Test` and Currency `INR` every time.
**Save, then Submit** each one.

| # | Type | Amount | Account | Destination | Category |
|---|---|---|---|---|---|
| 1 | Income | 50000 | DT Bank | — | DT Salary |
| 2 | Expense | 2000 | DT Bank | — | DT Groceries |
| 3 | Expense | 3000 | DT Card | — | DT Groceries |
| 4 | Transfer | 8000 | DT Bank | DT SBI | *(hides itself)* |
| 5 | Credit Card Payment | 1000 | DT Bank | DT Card | *(hides itself)* |
| 6 | Refund | 500 | DT Bank | — | DT Groceries |

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
> 43.4% · Goals on Track 6 of 7 · Budgets on Track 3 of 5** (verified 2026-08-16, goals
> 2026-08-17, budgets 2026-08-19). The current month is deliberately part-finished — the
> seeder skips future-dated rows — so those two month figures grow as the month does.

### The Number Cards

| Card | Expected | Why |
|---|---|---|
| Total Balance | **47,500** | assets only: 39,500 + 8,000. The 2,000 card debt is *not* added |
| Net Worth | **45,500** | 47,500 − 2,000 owed |
| Income This Month | **50,000** | |
| Expenses This Month | **4,500** | 2,000 + 3,000 − 500 refund |
| Savings Rate | **91.0%** | (50,000 − 4,500) / 50,000 |
| Goals on Track | **—** | no goals yet; §13 builds them and this becomes **5 of 6** |
| Budgets on Track | **—** | no budgets yet; §14 builds them and this becomes **1 of 3** |

✅ **The key check:** Total Balance is 47,500, not 49,500. Every account is reported in its
natural direction, so the credit card's 2,000 comes back positive; adding it in would show
you *more* money the more you charged to the card.

✅ Each figure carries the **tracker's** currency symbol, because the card renders the
string server-side rather than handing the browser a bare number.

### The charts

Income vs Expense and Spending Trend are `Custom` charts fed by the `Money Period Totals`
source, monthly, last year. The other two each have a source of their own and are covered
where they belong — **Goal Progress** in §13, **Budget vs Actual** in §14.

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

✅ Open the Refund: it **credits `DT Groceries - T`**. It does not touch any income account —
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
| DT Groceries - T | 5,000 | 500 |
| DT Salary - T | 0 | 50,000 |
| **Total** | **64,500** | **64,500** |

✅ Debits == credits. This is the §76 invariant, visible.

### Profit and Loss Statement

| Line | Expected |
|---|---|
| DT Salary (income) | **50,000** |
| DT Groceries (expense) | **4,500** (2000 + 3000 − 500 refund) |
| DT Food | **absent** — a group holds no ledger account, so ERPNext lists only the leaf |
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

Post an Expense: amount `250`, account `DT Bank`, category `DT Groceries`.

✅ Expected: green toast *"Transaction TXN-000xx posted"*, form resets, and **DT Bank drops
to 39,250** with **DT Groceries** rising to 4,750.

✅ `DT Food` is not offered in the category list — the page filters group categories out.

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
| P&L → DT Groceries | **2,500** (4,500 − 2,000) |
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

## 13. Goals

**Money Tracker → Money Goal → + Add Money Goal.** Six goals over the same six
transactions, one of every type. A goal stores **no progress** — every figure below is
measured from the ledger each time you open the form, so none of it can go stale.

Set **Tracker `Desk Test`** on each one. Use **Start Date `2026-08-12`** throughout — the
same date the transactions carry — and where a Target Date is given, `2026-08-12` as well.

> Why a Target Date in the past: it makes every outcome below **date-independent**. A window
> that has closed is judged on its final figure, so these words read the same whenever you
> run this pass. Live goals in the demo household are the other case — §7.

Create them in this order:

| # | Goal Name | Type | Target | Dates | Other fields |
|---|---|---|---|---|---|
| 1 | `DT Food Cap` | Spending Limit | 5000 | 08-12 → 08-12 | Category `DT Food` |
| 2 | `DT Keep 30` | Savings Rate Target | 30% | 08-12 → 08-12 | — |
| 3 | `DT Earn 60k` | Income Target | 60000 | 08-12 → 08-12 | Category `DT Salary` |
| 4 | `DT SBI Pot` | Savings | 20000 | 08-12, no deadline | Account `DT SBI`, basis `Account Balance` |
| 5 | `DT Card Payoff` | Debt Payoff | 3000 | 08-12, no deadline | Account `DT Card`, Opening `3000` |
| 6 | `DT First Lakh` | Net Worth Target | 100000 | 08-12, no deadline | — |

Watch the form as you pick each type: **the fields change**. Target Amount becomes Target
Percent for the rate goal, Target Account appears only for Savings and Debt Payoff, Measure
Basis only for Savings, and the **Category description rewrites itself** — "what is measured"
for #1 and #3, "what this goal is for" for the rest.

### The progress bar

Reload each saved goal. The **Progress** block at the top of the form:

| Goal | Progress | Outcome | Footnote reads |
|---|---|---|---|
| DT Food Cap | **90%** | Achieved | 4,500 of 5,000 spent · 500 left · deadline passed |
| DT Keep 30 | **303.33%** | Achieved | 91.0% of 30.0% · deadline passed |
| DT Earn 60k | **83.33%** | **Missed** | 50,000 of 60,000 · 10,000 to go · deadline passed |
| DT SBI Pot | **40%** | In Progress | 8,000 of 20,000 · 12,000 to go |
| DT Card Payoff | **33.33%** | In Progress | 1,000 of 3,000 · 2,000 to go |
| DT First Lakh | **45.5%** | In Progress | 45,500 of 1,00,000 · 54,500 to go |

✅ **DT Food Cap is 4,500, not 5,000.** Two things had to work: the 500 refund **reduced**
the spend (§62), and `DT Food` is a **group**, so the 2,000 and 3,000 filed under it and its
child rolled up. A group is deliberately allowed here — the opposite of a Transaction, which
refuses to post to a heading.

✅ **The transfer and the card payment appear in no goal's spend.** They moved money.

✅ **DT Card Payoff reads 1,000 cleared** — 3,000 declared as the opening, 2,000 still owed.
Now blank the Opening Amount and save: it drops to **−2,000, an empty bar**. That is correct
and worth understanding — with no opening declared it is read from the ledger as at 11 Aug,
when nothing was owed yet, so the card was *charged* inside the window rather than paid down.
Put the 3,000 back.

✅ **DT First Lakh's 45,500 is the Net Worth card's figure**, arrived at independently.

✅ Each money figure carries the **tracker's** currency symbol — formatted server-side, like
the cards.

✅ **The tick mark on the bar** is where the goal should have been by now. `DT Food Cap` and
`DT Earn 60k` have one, at the far right — their window is over, so 100% of it should have
been done. The three undated goals have **no tick and no "days left"**: there is no pace to
be behind when no date was ever set, which is why they read *In Progress* rather than
*Behind*. **`DT Keep 30` has no tick either**, despite having a deadline — a rate does not
accumulate, so being at 91% halfway through a window says nothing about where it "should"
be. That is the `cumulative` flag in `GOAL_TYPES` doing its job.

### Breaching a limit

Open `DT Food Cap`, change Target Amount to **4000**, save, reload.

✅ **Breached**, bar red, footnote *"4,500 of 4,000 spent · −500 over"*. A limit that goes
over stays breached for that window — the money is already spent. Compare `DT Earn 60k`,
which is only *Missed* because its window closed short.

Set it back to **5000**.

### The link fields are filtered

- New Savings goal → open **Target Account**: `DT Bank` and `DT SBI` only. **`DT Card` is
  not offered.** Switch the type to Debt Payoff → now `DT Card` **only**.
- `DT SBI` from another tracker is not offered either — the list is scoped to `Desk Test`.
- Spending Limit → **Category** offers `DT Food` and `DT Groceries`, not `DT Salary`.
  Income Target → the reverse.

### The refusals

Each is caught on **Save**, not Submit — a goal is not submittable.

- **Saving into a credit card:** Savings goal, account `DT Card`.
  ✅ *"DT Card is a debt, not somewhere to save. Use a Debt Payoff goal for it instead."*
- **Paying off a bank account:** Debt Payoff, account `DT Bank`.
  ✅ *"DT Bank is not a debt. A Debt Payoff is set against a credit card or a loan."*
- **A limit on an income category:** Spending Limit, category `DT Salary`.
  ✅ *"DT Salary is a Income category. A Spending Limit is measured over Expense categories."*
- **A limit with no deadline:** leave Target Date empty.
  ✅ *"A Spending Limit needs a Target Date — it measures a period, and a period has to end."*
- **A deadline before the start:** Target Date `2026-08-01`.
  ✅ *"Target Date cannot be before Start Date."*
- **A duplicate name:** a second goal called `DT Food Cap` on `Desk Test`.
  ✅ *"A goal named DT Food Cap already exists on this tracker."* The same name on another
  tracker is fine — names are unique per tracker, as with accounts and categories.
- **Zero target:** ✅ *"Target Amount must be greater than zero."*
- **A rate over 100:** Savings Rate Target, 120.
  ✅ *"Target Percent must be greater than 0 and no more than 100."*

### Retyping clears what the new type cannot use

Open `DT SBI Pot`, change **Goal Type** to `Net Worth Target`, save, reload.

✅ Target Account, Measure Basis and Opening Amount are **empty** — a stale link to an
account the new type never reads would show up in every report that joins on it. Change it
back to Savings and set `DT SBI` / `Account Balance` again.

### The dashboard, again

Back to **Money Tracker**, with every widget's Tracker filter still on `Desk Test`:

✅ **Goals on Track** reads **5 of 6** — every goal except `DT Earn 60k`. Achieved, On Track
and In Progress all count as going well; Missed, Behind, At Risk and Breached do not.

✅ **Goal Progress** draws **six bars**, one per goal, in the order *DT Food Cap · DT Keep 30
· DT Earn 60k · DT SBI Pot · DT Card Payoff · DT First Lakh* — soonest deadline first, and
undated goals last, because a deadline is what makes a goal urgent.

✅ Bar heights are the percentages from the table above; `DT Keep 30` runs off the top at
303%, which is honest — it is three times the target rate.

✅ Click the funnel: **Tracker**, **Status** and **Goal Type** filters. Set Goal Type to
`Savings` → **one bar**, `DT SBI Pot`. The payoff is a different type, and blank means every type.

✅ Set `DT First Lakh`'s **Status** to `Paused` and reload the workspace: the card reads
**4 of 5** and the chart drops to five bars. A paused goal is still a goal — it is just not
what the dashboard is counting. Set it back to `Active`.

---

## 14. Budgets

**Money Tracker → Money Budget → + Add Money Budget.** Three envelopes over the same six
transactions. A budget stores **no spending** — like a goal, every figure below is measured
from the ledger each time you open the form.

A budget is deliberately **not** a Spending Limit goal. A goal is one window with a
deadline; an envelope *repeats*, and carries two things a goal has not got — a Period that
refills it, and a Rollover that decides whether last month's leftovers are still there.

Set **Tracker `Desk Test`** on each one, and give every one of them
**Start Date `2026-08-01`, End Date `2026-08-31`**.

> Why an End Date: a budget is otherwise **live** — it always measures the period containing
> today, so running this pass in September would read an empty September rather than the
> August you posted into. The end date clamps the measurement to August's envelope forever,
> which is the same rule that stops a finished budget opening a fresh clean envelope every
> month. Everything below is therefore date-independent, like §13.

| # | Budget Name | Period | Amount | Category | Threshold |
|---|---|---|---|---|---|
| 1 | `DT Food Budget` | Monthly | 6000 | `DT Food` *(the group)* | 80 |
| 2 | `DT Tight Cap` | Monthly | 5000 | `DT Groceries` | 80 |
| 3 | `DT Everything` | Monthly | 4000 | *(leave empty)* | 80 |

✅ The Category link offers **only expense categories**, and it *does* offer `DT Food` even
though it is a group. That is the point of #1: one envelope over everything filed under it —
the exact opposite of `Transaction`, which refuses to post to a heading.

✅ #1 and #2 are allowed to coexist: a cap on the parent and a tighter cap on one child is a
real way to budget. What is refused is two envelopes over the *same* category on the *same*
clock — see the refusals below.

### The period block

Reload each saved budget. The **This Period** block at the top of the form:

| Budget | Used | Period | Outcome | Footnote reads |
|---|---|---|---|---|
| DT Food Budget | **75.0%** | Aug 2026 | Within Budget | 4,500 of 6,000 spent · 1,500 left · 1 days left · 1,500.00 a day left |
| DT Tight Cap | **90.0%** | Aug 2026 | Nearing Limit | 4,500 of 5,000 spent · 500 left · … |
| DT Everything | **112.5%** | Aug 2026 | Over Budget | 4,500 of 4,000 spent · -500 over |

The 4,500 is the same figure the Expenses This Month card gives in §7: 2,000 + 3,000 less
the 500 refund. Three things are worth stopping on:

✅ **#1 reads 4,500, not zero.** Nothing was ever posted to `DT Food` itself — it is a
heading. The envelope rolls its subtree up.

✅ **#3 reads 4,500 too**, with no category at all. An empty category means the whole
tracker's spending — and the **transfer and the credit card payment are not in it**. Moving
your own money about empties no envelope.

✅ **The bar is clamped, the figures are not.** #3's bar is full, and its text still says
112.5% and *-500 over*. The bar has no more width to give; the number has no reason to lie.

✅ The thin vertical line on the bar is the **pace marker** — how much of the period has
passed. It sits at the far right here, because the window is closed.

### Alerts

`Notify Me` is on by default, and #2 and #3 have both crossed a line. From a shell:

```bash
docker exec -w /workspace/development/frappe-bench frappe_bench2-frappe-1 \
  bash -lc 'bench --site tracker.localhost execute moneytracker.money_tracker.services.budgets.send_budget_alerts'
```

✅ The **bell icon** in Desk's navbar gains two notifications: *"DT Tight Cap is at 90.0% of
its budget for Aug 2026"* and *"DT Everything is over budget: ₹ 4,500.00 of ₹ 4,000.00 spent
in Aug 2026"*. They go to the **tracker's owner**, not to whoever ran the job.

✅ It will also alert on the demo household's `Fuel & Commute` and `Household Bills`, which
are genuinely over and near. That is the job working, not a leak.

✅ **Run it again.** No new notifications. Each budget is stamped with the period and outcome
it last announced, so the same fact is never told twice. Now open `DT Food Budget`, drop its
amount to `4000`, save, and run the job once more: it appears, because that is a new fact.

### Rollover — go and look at the demo household

The `DT *` set is one month old, so it has nothing to roll over. Open **Eating Out** on
`Demo Household` instead, the one demo budget with Rollover ticked (measured 2026-08-19):

✅ Amount **3,000**, but the footnote says **2,400 of 5,400 spent** and **2,400 carried in**.
Four finished months at 600 left over each. `Within Budget` at 44.44%.

✅ Below the bar, a strip of small columns — **the earlier periods**, against a dashed line
for the envelope. That strip is the one thing a budget shows that a goal cannot: the same
envelope, over and over.

✅ Tick Rollover **off** on it and save. The footnote becomes *2,400 of 3,000 spent* and the
carried-in line vanishes. Tick it back on.

> Rollover carries a **deficit** as well as a surplus — an envelope that quietly forgets last
> month's overspend is two budgets wearing one name. `Fuel & Commute` would show it if it had
> rollover on; the automated suite covers it.

### The refusals

Try each; each should be refused on save:

| What you do | Expected |
|---|---|
| A budget with Category `DT Salary` | *"DT Salary is an income category. A budget caps spending, so it is set against an expense."* |
| A **second** Monthly budget on `DT Groceries` | *"DT Tight Cap is already a Monthly budget over the same category…"* |
| Budget Amount `0` | *"Budget Amount must be greater than zero."* |
| End Date before Start Date | *"End Date cannot be before Start Date."* |
| Alert Threshold `150` | *"Alert Threshold must be greater than 0 and no more than 100."* |
| A second budget named `DT Tight Cap` | *"A budget named DT Tight Cap already exists on this tracker."* |

✅ Now change the second `DT Groceries` budget's **Period to `Yearly`** and save: it goes
through. A monthly grocery cap inside a yearly one is two different questions about the same
money, not the same question twice. Delete it again before moving on.

✅ Set `DT Tight Cap`'s **Status to `Paused`**, then try the duplicate Monthly budget again:
it now saves. A paused envelope is not counting anything, so nothing is double-counted. Undo
both.

### The dashboard, a third time

Back to **Money Tracker**, with every widget's Tracker filter on `Desk Test`:

✅ **Budgets on Track** reads **1 of 3** — only `DT Food Budget`. `Nearing Limit` and
`Over Budget` are both warnings, and neither counts as on track.

✅ **Budget vs Actual** draws **three pairs of bars**, largest envelope first — *DT Food
Budget · DT Tight Cap · DT Everything* — with Budget at 6,000 / 5,000 / 4,000 and Spent at
4,500 on all three.

✅ Click the funnel: **Tracker**, **Status** and **Period** filters, with Period defaulting
to `Monthly`. Set it to `Yearly` → **no bars**, because all three are monthly. Blank means
every period, which puts a weekly envelope next to a yearly one — the reason the filter
defaults to a single clock rather than to everything.

✅ Unfiltered, against the demo household, the chart shows **four** bars and not five: the
`Travel Fund` is Yearly, and the default filter is doing its job.

---

## 15. Cleanup (optional)

Desk will not let you delete a submitted transaction, so:

1. Cancel each `Desk Test` transaction, then delete it.
2. Delete the six `DT *` goals from §13 and the three `DT *` budgets from §14 — neither is
   submittable, so they just delete.
3. Delete `DT Groceries`, `DT Food`, `DT Salary`.
4. Delete `DT Bank`, `DT SBI`, `DT Card`.
5. Delete tracker `Desk Test`, and user `dt.other@example.com`.

Goals and budgets before accounts and categories: both link to both.

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
- A goal measured **while its window is still open** — §13 uses closed windows on purpose, so
  its outcomes read the same whenever you run it. The demo household's goals are the live
  case: open any of them from §7 and the pace marker sits mid-bar.
- `Money Goal`'s `Archived` status, and a Savings goal on the `Contributions Since Start`
  basis — §13's pot uses `Account Balance`. Both are covered by the automated suite.
- A budget on a **Weekly or Quarterly** period, and a rollover carrying a **deficit** — §14
  is monthly throughout and the one rollover it looks at is in surplus. Both are covered by
  the automated suite.
- A budget measured **while its period is still running**. §14 clamps every envelope to a
  closed August on purpose, so its figures read the same whenever you run it; the demo
  household's five budgets are the live case, and their pace markers sit mid-bar.
