# Manual Desk pass — results, 2026-08-17

The record of walking `docs/manual-test-desk.md`. That document says what to expect; this one
says what actually happened.

**Status: in progress — two findings, both found and fixed.** Tick as you go: `[ ]` → `[x]`
for a pass, `[!]` for a finding, then write the finding up in the log below.

> **Scope grew again on 2026-08-20.** `Money Recurring Transaction` landed on branch
> `feat/phase-2-recurring`, so the walkthrough now has **§15 Recurring** and cleanup has moved
> to §16. The workspace has two more cards (`Plans Running`, `Fixed Costs`), a fifth chart
> (`Upcoming Recurring`) and a Recurring section — **14 laid-out widgets**, all confirmed to
> resolve. The demo household gained five standing orders (`RTX-00001`…`00005`).
>
> **Scope grew on 2026-08-19.** `Money Budget` landed on branch `feat/phase-2-budgets`, so the
> walkthrough now has **§14 Budgets** and cleanup has moved to §15, and the workspace has a
> seventh card (`Budgets on Track`) and a fourth chart (`Budget vs Actual`). The confirmed
> figures below have been extended to match. Everything else in this file still stands.

---

## Pre-flight, 2026-08-20 — run again before you start

The containers had been restarted, so everything below was re-established from scratch and
re-measured against **today**. One finding came out of it (F2, the branch), and every figure
in this document still holds.

| Check | Result |
|---|---|
| Containers | all four up; MariaDB reachable, no re-grant needed |
| Branch | **switched `dev` → `feat/phase-2-budgets`** — see F2 |
| `migrate` | clean; rewrote no fixture JSON (working tree still only the docs) |
| `bench build --app moneytracker` | rebuilt after the branch switch |
| Suite | **426 green, 36s** (339 and one failure on `dev` — F2) |
| Dev server | `bench start` running, Desk answered 200 |

### What the browser will be served — reproduced server-side

- **All 14 laid-out widgets resolve.** `block.js`'s label lookup was replayed against what
  `get_desktop_page` actually serves: 9 cards + 5 charts, **0 that would render nothing.**
  This is F1's fix still holding, now over the two budget widgets and the three recurring ones
  as well. (11 when the pre-flight first ran; recurring landed the same day.)
- **Every method named by a widget or a form exists and is whitelisted** — the seven
  `card_*`, the three chart-source `get`s, `get_goal_progress`, `get_budget_progress`,
  `create_transaction`. A chart source's `.js` is eval'd in the browser and nothing imports
  it, so a stale path there fails *only* in a browser; none is stale.
- **Both forms will ship their client script.** `getdoctype` returns `__js` of 5,973 chars for
  `Money Budget` (carrying the carried-in, history and pace code) and 6,736 for `Money Goal`,
  and both doctypes expose the `progress_html` field they draw into.
- `Money Budget` is in **both** permission hook lists (`hooks.py:131` and `:140`).

### Today's figures — the pace numbers have moved, and that is not a finding

Cards, charts, goals and budgets all re-measured on 2026-08-20 and **identical** to the tables
below, with one exception by design: a **pace** figure is the share of the window that has
elapsed, so it moves every day.

| Goal | Pace 08-17 | Pace 08-20 |
|---|---|---|
| Dining Out Budget | 54.84% | **64.52%** (20 of 31 days of August) |
| Clear the Credit Card · Freelance Income | 38.08% | **38.9%** |
| Emergency Fund · First 10 Lakh | 19.86% | **20.29%** |
| Japan Trip | 2.94% | **3.46%** |

`Save 30% of Income` still has no pace — a rate has none. Budget footnotes move the same way:
August's envelope now reads **11 days left** rather than 14.

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

### The nine Number Cards, unfiltered

| Card | Confirmed value |
|---|---|
| Total Balance | `₹ 3,32,550.00` |
| Net Worth | `₹ 2,61,755.00` |
| Income This Month | `₹ 1,20,000.00` |
| Expenses This Month | `₹ 67,899.00` |
| Savings Rate | `43.4%` |
| Goals on Track | `6 of 7` |
| Budgets on Track | `3 of 5` *(added 2026-08-19)* |
| Plans Running | `5 of 5` *(added 2026-08-20)* |
| Fixed Costs | `₹ 39,699.00` *(added 2026-08-20)* |

Cross-checks that hold: 2,51,300 + 76,850 + 4,400 = **3,32,550**; less the 70,795 owed on the
card = **2,61,755**; and the category roll-up below sums to **67,899**.

### The five charts

| Chart | Labels | Series |
|---|---|---|
| Income vs Expense | 13, `Aug 2025` … `Aug 2026` | `Income`, `Expense` |
| Spending Trend | 13, same | `Expense` only |
| Goal Progress | 7, `Dining Out Budget` … `First 10 Lakh` | `Progress` |
| Budget vs Actual | **4**, `Household Bills` `Groceries` `Fuel & Commute` `Eating Out` | `Budget`, `Spent` |
| Upcoming Recurring | 6, this month … five ahead | `Income`, `Expense` |

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

### The five standing orders

Measured 2026-08-20. All five adopted the transactions they stand for, so every one of them
opens with five posted occurrences and **nothing due**.

| Plan | Type | Monthly | Posted | Total | Next | Outcome |
|---|---|---|---|---|---|---|
| Salary | Income | 1,20,000 | 5 | 6,00,000 | 2026-09-01 | Scheduled |
| Rent | Expense | 35,000 | 5 | 1,75,000 | 2026-09-02 | Scheduled |
| Savings Transfer | Transfer | 15,000 | 5 | 75,000 | 2026-09-03 | Scheduled |
| Electricity Bill | Expense | 3,200 | 5 | 16,000 | 2026-09-05 | Scheduled |
| Streaming Subscriptions | Expense | 1,499 | 5 | 7,495 | 2026-09-06 | Scheduled |

✅ **Fixed Costs 39,699** is the three *expense* plans only: 35,000 + 3,200 + 1,499. The salary
is not a cost by any reading, and the transfer is a commitment but not a cost — the money is
still yours.

✅ `Electricity Bill` is the one plan set to **Create as Draft**, because an electricity bill is
a different number every month.

✅ **`Upcoming Recurring` reads zero for the current month on both series.** Every August
occurrence (days 1–6) has already been dealt with, and the forecast window opens *strictly
after today* so one rent cannot appear in both the forecast and the actuals. September onwards:
Income 1,20,000, Expense 39,699.

✅ Running the nightly job on this site posts **nothing** — `{'plans': 5, 'posted': 0,
'failed': 0, 'notified': 0}`. Every occurrence up to today already exists in the ledger.

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
| F2 | §0 | **env** | The checkout was on `dev`, which has no budgets code, while the site is budget-migrated — §14 could not have run and one guard test failed | **fixed** |

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

### F2 — §0 — env — the checkout was on the wrong branch for half the walkthrough

**What happened.** `git status` said `dev`. `dev` is the goals merge (`e8f61dd`) and has **no
budgets code at all** — `moneytracker/money_tracker/doctype/money_budget/` held nothing but a
stale `__pycache__`. Budgets are still on `feat/phase-2-budgets` (`3cfdd70`), unmerged. The
site, meanwhile, is budget-migrated: `Money Budget`, the five demo envelopes, the
`Budgets on Track` card and the `Budget vs Actual` chart are all in the database.

**How it surfaced.** The suite ran **339 tests, one failure** — not the documented 426. The
failure was `test_workspace.TestWorkspaceWidgetsRender.test_the_site_agrees_with_the_shipped_file`,
reporting that the site serves a seventh Number Card the shipped workspace file has never heard
of:

```
First extra element 6:
('Budgets on Track', 'Budgets on Track')
```

That guard was written after F1 to catch a workspace edited without bumping `modified`. It
caught a different thing entirely — code and site out of step — which is the same class of
fault and exactly what it should do.

**Why it mattered to the pass.** §14 is fifteen minutes of the walkthrough and could not have
been started: no `Money Budget` doctype to add. Worse for the pass's *purpose*, the workspace
would still lay out a `Budgets on Track` card pointing at
`moneytracker.money_tracker.api.budgets.card_budgets_on_track`, a module that does not exist on
`dev` — so §7 would have shown a broken card and it would have read as a rendering finding
rather than a checkout one.

**Fix.** Switched to `feat/phase-2-budgets`, re-ran `migrate` (clean, no fixture JSON rewritten),
`clear-cache`, `bench build --app moneytracker`. Suite back to **426 green**. The staged docs
carried over untouched, `docs/how-money-tracker-works.html` included.

**Note for whoever merges.** The doc files were already identical on both branches —
`docs/architecture.md` and `docs/manual-test-desk.md` on `dev` matched
`feat/phase-2-budgets` byte for byte, so the budgets *documentation* had been copied onto `dev`
while the budgets *code* stayed behind. That is what made the mismatch invisible: CLAUDE.md
and every doc described budgets, and only the suite disagreed. **Run the pass on the branch that
ships the feature, and check the test count before starting — 426, not 339.**

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
- [ ] Seven cards render, unfiltered, matching the confirmed table above
- [ ] Each money card shows the **tracker's** currency symbol
- [ ] Filtered to `Desk Test`: 47,500 · 45,500 · 50,000 · 4,500 · 91.0% · **—** (no goals yet)
- [ ] Income vs Expense: 13 labels, the eight empty months drawn as **zero, not skipped**
- [ ] Spending Trend: one series
- [ ] Transfer and card payment appear in **neither** series
- [ ] Chart funnel offers **Tracker** and **Series** only — no doctype filter fields
- [ ] Monthly → Daily puts the money on today
- [ ] Layout holds at a narrow window; tooltips readable in both themes
- [ ] Budget vs Actual renders under Budgets (unfiltered: four pairs, not five)
- [ ] Upcoming Recurring renders under Recurring, beside the Fixed Costs card
- [ ] Nine cards in two tidy rows of four and a bit — none blank

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

### §13 Goals *(new 2026-08-17)*
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

### §14 Budgets *(new 2026-08-19)*
- [ ] Three envelopes save; Category link offers **only expense** categories and **does** offer
      the group `DT Food`
- [ ] `DT Food Budget` and `DT Tight Cap` coexist — parent cap plus a tighter child cap
- [ ] The **This Period** block reads 75.0% Within Budget · 90.0% Nearing Limit ·
      112.5% Over Budget, all three over the same **4,500**
- [ ] `DT Food Budget` reads **4,500 not zero** — the group rolls its subtree up
- [ ] `DT Everything` reads **4,500** with no category, and the transfer and card payment are
      **not** in it
- [ ] #3's bar is clamped full while the text still says 112.5% and **−500 over**
- [ ] Pace marker sits at the far right — the window is closed
- [ ] `send_budget_alerts` raises **two** bell notifications, to the tracker's owner
- [ ] Running it **again** raises none; dropping #1 to 4,000 raises one (a new fact)
- [ ] Demo `Eating Out`: **2,400 of 5,400**, **2,400 carried in**, Within Budget 44.44%
- [ ] Its history strip draws the earlier periods against the dashed envelope line
- [ ] Rollover off → *2,400 of 3,000*, carried-in line gone; back on again
- [ ] All six refusals fire with the documented wording
- [ ] Same category on a **Yearly** clock saves; a **Paused** duplicate saves
- [ ] Filtered to `Desk Test`: **Budgets on Track 1 of 3**, Budget vs Actual **three pairs**
- [ ] Chart funnel has Tracker / Status / Period, Period defaulting to Monthly; `Yearly` → no bars

### §15 Recurring transactions *(new 2026-08-20)*
- [ ] Four plans save; the Type dropdown offers **four** options and no `Refund`
- [ ] Transfer hides Category / shows Destination Account, and retyping clears the other one
- [ ] Two plans on one category both save (the opposite of a budget's duplicate refusal)
- [ ] All four read **Due** on the day they are made, with today as the headline
- [ ] **Post Due Now** posts one each; the block turns **Scheduled**, headline next month
- [ ] The date-pill strip links to the transaction, which names the plan and is read-only
- [ ] `DT Power Bill`'s occurrence is a **Draft** with no Journal Entry (orange pill)
- [ ] Post Due Now again → *Nothing is due yet.*
- [ ] `DT Bank` **80,500** · `DT SBI` **9,000** (the draft moved nothing)
- [ ] The nightly job posts **nothing** and raises no notification
- [ ] Cancelling an occurrence: struck-through red pill, *1 cancelled*, still **not** `Due`,
      and Post Due Now still refuses — cancelling is a decision
- [ ] Pausing hides the button and reads **Paused**, with nothing due
- [ ] Start Date on the 31st rewrites the field's own description with the clamp rule
- [ ] All eight refusals fire with the documented wording, group category included
- [ ] Category link filtered by tracker, by side of the books, and never the group
- [ ] Deleting a plan keeps its transaction, submitted, with the link cleared
- [ ] Filtered to `Desk Test`: **Fixed Costs 9,200** · **Plans Running 2 of 3**
- [ ] Upcoming Recurring: current month **zero on both series**, six bars, funnel has
      Tracker / Status / Months Ahead
- [ ] Unfiltered: **Fixed Costs 39,699** · **Plans Running 5 of 5**

### §16 Cleanup *(optional)*
- [ ] Goals, budgets and plans deleted before accounts and categories
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
