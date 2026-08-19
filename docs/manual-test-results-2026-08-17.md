# Manual Desk pass — results, 2026-08-17

The record of walking `docs/manual-test-desk.md`. That document says what to expect; this one
says what actually happened.

**Status: in progress — one finding, found and fixed.** Tick as you go: `[ ]` → `[x]` for a
pass, `[!]` for a finding, then write the finding up in the log below.

> **Scope grew on 2026-08-19.** `Money Budget` landed on branch `feat/phase-2-budgets`, so the
> walkthrough now has **§14 Budgets** and cleanup has moved to §15, and the workspace has a
> seventh card (`Budgets on Track`) and a fourth chart (`Budget vs Actual`). The confirmed
> figures below have been extended to match. Everything else in this file still stands.

---

## 0. Environment, as left for you

| | |
|---|---|
| Containers | all four started 2026-08-17 (they had been OOM-killed, exit 137) |
| Dev server | `bench start` running — Desk answered 200 at 16:41 |
| URL | http://tracker.localhost:8100/app/money-tracker |
| Login | `Administrator` |
| Site data | `TRK-00002 Demo Household` — 67 transactions, 2026-04-01 … 2026-08-15, **7 goals and 5 budgets** |
| Migrate | run twice; the second was a no-op and rewrote no fixture JSON |
| Suite | 339 tests green, ~25s |

If Desk stops answering, restart it:

```bash
docker exec -d -w /workspace/development/frappe-bench frappe_bench2-frappe-1 \
  bash -lc 'nohup bench start > /tmp/bench_start.log 2>&1 &'
```

---

## What is already confirmed without a browser

Every figure below was measured today by calling the card methods, the two chart sources and
the goal measures directly against `TRK-00002`. **The arithmetic is not what you are testing.**
If the browser shows something different from this table, that is a *rendering or wiring* bug —
which is exactly what a manual pass is for.

### The six Number Cards, unfiltered

| Card | Confirmed value |
|---|---|
| Total Balance | `₹ 3,32,550.00` |
| Net Worth | `₹ 2,61,755.00` |
| Income This Month | `₹ 1,20,000.00` |
| Expenses This Month | `₹ 67,899.00` |
| Savings Rate | `43.4%` |
| Goals on Track | `6 of 7` |
| Budgets on Track | `3 of 5` *(added 2026-08-19)* |

Cross-checks that hold: 2,51,300 + 76,850 + 4,400 = **3,32,550**; less the 70,795 owed on the
card = **2,61,755**; and the category roll-up below sums to **67,899**.

### The three charts

| Chart | Labels | Series |
|---|---|---|
| Income vs Expense | 13, `Aug 2025` … `Aug 2026` | `Income`, `Expense` |
| Spending Trend | 13, same | `Expense` only |
| Goal Progress | 7, `Dining Out Budget` … `First 10 Lakh` | `Progress` |
| Budget vs Actual | **4**, `Household Bills` `Groceries` `Fuel & Commute` `Eating Out` | `Budget`, `Spent` |

`Budget vs Actual` shows four and not five on purpose: `Travel Fund` is a **Yearly** budget
and the chart's `period` filter defaults to `Monthly`, because a weekly envelope drawn beside
a yearly one invites a comparison that means nothing.

Monthly values, Apr → Aug 2026 (the first eight months are zero — that is the point):

- Income `1,45,000 · 1,20,000 · 1,21,850 · 1,20,000 · 1,20,000`
- Expense `60,599 · 1,02,599 · 55,399 · 78,599 · 67,899`
- Goal Progress bars `48.0 · 144.72 · 58.41 · 25.0 · 25.62 · 36.65 · 26.18`

### The seven goals

| Goal | Type | Progress | Outcome | Figures | Pace |
|---|---|---|---|---|---|
| Dining Out Budget | Spending Limit | 48.0% | On Track | 2,400 / 5,000 | 54.84% |
| Save 30% of Income | Savings Rate Target | 144.72% | On Track | 43.4% / 30.0% | none |
| Clear the Credit Card | Debt Payoff | 58.41% | On Track | 29,205 / 50,000 | 38.08% |
| Freelance Income | Income Target | 25.0% | **Behind** | 25,000 / 1,00,000 | 38.08% |
| Emergency Fund | Savings | 25.62% | On Track | 76,850 / 3,00,000 | 19.86% |
| Japan Trip | Savings | 36.65% | On Track | 73,300 / 2,00,000 | 2.94% |
| First 10 Lakh | Net Worth Target | 26.18% | On Track | 2,61,755 / 10,00,000 | 19.86% |

### The five budgets

Measured 2026-08-19. All five start with the ledger (2026-04-01) and never end.

| Budget | Period | Amount | Available | Spent | Used | Outcome |
|---|---|---|---|---|---|---|
| Household Bills | Monthly | 45,000 | 45,000 | 38,200 | 84.89% | **Nearing Limit** |
| Groceries | Monthly | 13,000 | 13,000 | 6,800 | 52.31% | Within Budget |
| Fuel & Commute | Monthly | 4,000 | 4,000 | 4,500 | 112.5% | **Over Budget** |
| Eating Out | Monthly | 3,000 | **5,400** | 2,400 | 44.44% | Within Budget |
| Travel Fund | Yearly | 60,000 | 60,000 | 18,000 | 30.0% | Within Budget |

✅ `Eating Out` is the only one with **Rollover** on: 3,000 an envelope, 600 left over in each
of four finished months, so the period it is in has 5,400 to spend. It is the one budget to
open in the browser if you only open one — the carried-in figure and the history strip are
what a budget shows that a goal cannot.

✅ `Household Bills` is set against a **group** category (Housing), so its 38,200 is rent plus
utilities rolled up — the same roll-up the category table below shows.

✅ `Groceries` reads 6,800 and not 12,000: the second grocery run of the month is dated the
18th and the demo was seeded on the 17th, so it was skipped as future. That is the same reason
Expenses This Month is 67,899 rather than a full month.

---

### Balances and the category roll-up

| Account | Type | Balance | | Category | Own | Roll-up |
|---|---|---|---|---|---|---|
| HDFC Bank | Bank | 2,51,300 | | Food & Dining *(group)* | 0 | 9,200 |
| Emergency Fund | Savings | 76,850 | | Housing *(group)* | 0 | 38,200 |
| Wallet | Cash | 4,400 | | Health *(group)* | 0 | 14,500 |
| HDFC Credit Card | Credit Card | 70,795 owed | | Transport *(group)* | 0 | 4,500 |
| | | | | Entertainment *(group)* | 0 | 1,499 |

✅ Every group's own total is **0** and its roll-up is its leaves' — the §5 invariant, holding
on real data.

---

## Findings log

**Severity:** `bug` — wrong data or a broken flow · `cosmetic` — looks wrong, reads wrong,
data fine · `doc` — the walkthrough is wrong, the app is right.

Write each one up under the table in the shape of F1 below: what you did, what you expected,
what happened, whether it repeats.

| # | § | Severity | What | Status |
|---|---|---|---|---|
| F1 | §7 | **bug** | No Number Card and no Dashboard Chart rendered anywhere on the workspace — nine widgets, empty headings | **fixed** |

### F1 — §7 — bug — every card and chart rendered as empty space

**What happened.** The workspace showed `Overview`, `Trends` and `Goals` as headings with
nothing underneath. Shortcuts, headers and paragraphs rendered normally. No console error, no
"No Data" box — just absence.

**Not a goals bug.** Six of the nine widgets predate this branch: the five cards shipped
2026-08-15 and the two trend charts 2026-08-16, and **none of them had ever rendered.** They
were signed off by calling their methods, which is why 334 tests and two "verified" entries in
`task.md` all passed over it. The goals card and chart inherited the same mistake, so all nine
failed together.

**Cause.** `frappe/public/js/frappe/views/workspace/blocks/block.js` resolves a laid-out
widget by **label**, not by name:

```js
let block_data = this.config.page_data[block + "s"].items.find(
    (obj) => unescape_html(obj.label) == unescape_html(__(block_name))
);
if (!block_data) return false;      // ← renders nothing at all
```

`block_name` is the content block's `number_card_name` / `chart_name` — the widget's record
name — but it is compared against the label of the workspace's own child row
(`desktop.py:get_number_cards`). This app named its cards `Money Total Balance` and labelled
them `Total Balance`, so every lookup missed and every block returned early. Reproduced
server-side before touching anything: all nine printed `RENDERS NOTHING`.

The same label is also what the widget **prints as its title**
(`base_widget.js:set_title` → `this.title || this.label || this.name`), so it cannot just be
set to the prefixed record name either — that would render "Money Total Balance" on the card.

**Fix.** Both constraints resolve the same way, and it is what every workspace frappe and
erpnext ship already does: **a widget's name is its label.** The nine records were renamed —
`Money Total Balance` → `Total Balance`, `Money Income vs Expense` → `Income vs Expense`, and
so on — their fixture folders renamed to match, the workspace's rows and content blocks
updated, and the nine orphaned records deleted from the site. The `Money ` prefix stays on the
two **Dashboard Chart Sources**, which no label lookup touches.

**Guard.** `moneytracker/tests/test_workspace.py`, 5 tests, which reproduce `block.js`'s lookup
against the shipped JSON *and* against what `get_desktop_page` actually serves. Re-introducing
the old label on one card fails 3 of them; restoring it passes. They also catch the adjacent
trap — a workspace edited without bumping `modified`, which `import_file_by_path` skips
silently, leaving the site laid out the old way while the repo looks right.

**Still to confirm in the browser** — the part I cannot do: that the nine widgets now actually
paint, showing the figures confirmed above. `bench start` is running and the cache was cleared,
so a hard reload of the workspace is all it needs.

---

## The pass

### §1 Money Settings
- [ ] Company `Trackify`, Base Currency `INR`
- [ ] All 8 parent account fields **blank** (correct — `coa.py` resolves them by name)

### §2 Create the tracker `Desk Test`
- [ ] Saves; URL ends in `TRK-0000x`, list shows the readable title
- [ ] You had to pick Tracker and Currency by hand (the known Desk quirk, not a bug)

### §3 Three accounts
- [ ] `DT Bank` / `DT SBI` ledger accounts under **Bank Accounts - T** after reload
- [ ] `DT Card` under **Current Liabilities - T**, ERPNext `account_type` **blank**
- [ ] Duplicate `DT Bank` refused: *"An account named DT Bank already exists on this tracker."*

### §4 Categories and the tree
- [ ] Category opens as a **Tree**
- [ ] Child under a non-group refused: *"…Tick Is Group on it before nesting anything under it."*
- [ ] After ticking Is Group, `DT Groceries` nests and gets `DT Groceries - T`
- [ ] `DT Food`'s Ledger Account is now **empty** — a heading holds no money
- [ ] Posting to `DT Food` refused: *"…Post to one of its sub-categories instead."*
- [ ] Cross-type child refused, and the message names **DT Food, not a hash**
      *(this was a documented defect; it was fixed 2026-08-12, so a hash here is a regression)*

### §5 Six transactions
- [ ] Category hides / Destination Account appears for Transfer and Credit Card Payment
- [ ] `Journal Entry` populates after reload
- [ ] **No "Reference Type cannot be Transaction"** anywhere
- [ ] All five guardrail messages fire, and at the stage the document says (Save vs Submit)

### §6 Balances
- [ ] DT Bank **39,500** · DT SBI **8,000** · DT Card **2,000**

### §7 The dashboard
- [ ] Six cards render, unfiltered, matching the confirmed table above
- [ ] Each money card shows the **tracker's** currency symbol
- [ ] Filtered to `Desk Test`: 47,500 · 45,500 · 50,000 · 4,500 · 91.0% · **—** (no goals yet)
- [ ] Income vs Expense: 13 labels, the eight empty months drawn as **zero, not skipped**
- [ ] Spending Trend: one series
- [ ] Transfer and card payment appear in **neither** series
- [ ] Chart funnel offers **Tracker** and **Series** only — no doctype filter fields
- [ ] Monthly → Daily puts the money on today
- [ ] Layout holds at a narrow window; tooltips readable in both themes

### §8 The ledger underneath
- [ ] Six Journal Entries, all Submitted, debits == credits
- [ ] Rows carry Reference Type `Transaction`, Reference Name `TXN-…`, Tracker `Desk Test`
- [ ] Transfer and card payment touch **no** income or expense account
- [ ] The Refund credits `DT Groceries - T` and no income account

### §9 Reports
- [ ] Trial Balance totals **64,500 / 64,500**
- [ ] P&L: DT Salary 50,000, DT Groceries 4,500, `DT Food` **absent** (a group has no account)
- [ ] Balance Sheet matches §6; no balance-sheet leakage into P&L
- [ ] The **Tracker** filter exists on every report — the whole payoff of the dimension

### §10 The Add Transaction page
- [ ] Toast, form resets, DT Bank → 39,250, DT Groceries → 4,750
- [ ] `DT Food` **not offered** in the category list
- [ ] Cancelled the 250 afterwards, so later numbers still hold

### §11 Cancel and reversal
- [ ] Transaction and its JE both **Cancelled**, not deleted
- [ ] DT Bank back to **41,500**, P&L DT Groceries **2,500**
- [ ] **4 GL rows**, all `is_cancelled = 1`, netting to zero
- [ ] Delete refused: *"Cannot delete a posted transaction…"*

### §12 Row-level security — the important one
- [ ] The second user sees **zero** rows across Transaction / Money Account / Category / Tracker
- [ ] A pasted TXN URL is **Not permitted**
- [ ] ❌ Any `Desk Test` or `Demo Household` row visible to them is a **security bug** — stop and record it

### §13 Goals *(new)*
- [ ] Six goals save; the form's fields change per type (Target Percent, Target Account,
      Measure Basis, and the Category description rewriting itself)
- [ ] The progress table matches: 90% Achieved · 303.33% Achieved · 83.33% **Missed** ·
      40% In Progress · 33.33% In Progress · 45.5% In Progress
- [ ] `DT Food Cap` reads **4,500** — the refund reduced it *and* the group rolled up
- [ ] Blanking the payoff's Opening Amount drops it to **−2,000, empty bar**; putting 3,000 back restores it
- [ ] `DT First Lakh` = **45,500**, the same figure as the Net Worth card
- [ ] Pace tick present on `DT Food Cap` and `DT Earn 60k`, **absent** on `DT Keep 30` (a rate has no pace) and on the three undated goals
- [ ] Cap at 4,000 → **Breached**, red, *"−500 over"*; back to 5,000 → Achieved
- [ ] Link fields filtered: no `DT Card` for Savings, only `DT Card` for Debt Payoff, no `DT Salary` for a Spending Limit
- [ ] All eight refusals fire with the wording in the document
- [ ] Retyping to Net Worth Target **clears** Target Account, Measure Basis, Opening Amount
- [ ] Card reads **5 of 6**; chart draws **six bars** in the documented order
- [ ] Goal Type filter `Savings` → one bar
- [ ] Pausing `DT First Lakh` → card **4 of 5**, chart five bars; unpaused again
- [ ] Colours read sensibly in **both light and dark** — the bar uses `var(--green-500)` etc.

### §14 Cleanup *(optional)*
- [ ] Goals deleted before accounts and categories
- [ ] ERPNext accounts and cancelled JEs deliberately left behind

---

## Verdict

*(fill in when done)*

| | |
|---|---|
| Sections passed | |
| Findings | |
| Blocking anything? | |

Once this is signed off, `task.md`'s NEXT ACTION moves on to the rest of Phase 2 — budgets
first, and note the boundary already drawn there: a budget is a recurring envelope, which is
deliberately *not* what a Spending Limit goal is.
