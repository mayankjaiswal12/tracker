===========================================
Roadmap — parity gaps and the analyst layer
===========================================

Two briefs, one document.

**Part A** answers "what does ``moneytracker`` still lack against a mature consumer expense
manager". It is a gap analysis: §0 marks each requested capability Done, Partial or Absent
against the file that proves it, and the phases that follow specify only the Partial and
Absent work.

**Part B** answers a second and much larger brief — a *Financial Analyst System*: risk
profiling, statement ingestion, market and company data, ratio analysis, portfolio analytics,
a rule engine, a controlled ML layer, an explainable advisor, scenario testing and a
compliance layer. Almost none of it has a foundation in the repo today.

The two tracks are **independent**. Part A makes the app a better expense manager; Part B makes
it an analyst. Either can be dropped without stranding the other, and neither blocks the other
except where §4 names a dependency.

Read ``CLAUDE.md`` for conventions, ``docs/architecture.md`` for why the ledger is ERPNext's,
``task.md`` for the current resume point, ``plan.md`` for the per-module build recipe and
``progress.md`` for what is actually built. The decisions behind everything below are §5 of
this document. **This document plans; it does not record** — ``progress.md`` is the live status.

.. note::

   **Phase A1 is built** as of 2026-08-22: tags, receipts, merchant master, splits, transfer
   fees, reconciliation and bills, plus the Desk wiring and demo fixtures for all of them. 716
   tests. None of it has been through the manual Desk pass yet, which is why every row in
   ``progress.md`` still reads amber rather than green.

   Everything from A2 onward is unbuilt.

.. contents::
   :local:
   :depth: 2


§0 · Gap analysis
=================

Thirty capabilities were requested. As first assessed on 2026-08-22: **9 done, 13 partial,
8 absent**. After phase A1 shipped the same day: **16 done, 10 partial, 4 absent**.

The brief describes the app as supporting "basic features … income & expense entries,
categories, accounts, dashboard, basic reports, authentication". That understated it by a good
deal even before A1, and the table says where. Verdicts below are **current**; where A1 changed
one, the row says so.

.. list-table::
   :header-rows: 1
   :widths: 4 20 10 66

   * - #
     - Capability
     - Verdict
     - Evidence / what is missing
   * - 1
     - Budget management
     - **Partial**
     - ``Money Budget`` ships four periods, rollover **both ways**, alert threshold, a daily
       alert job, a progress bar and two widgets. Missing: **account-wise**, **custom date
       range**, **templates**, **comparison report**.
   * - 2
     - Multiple accounts
     - **Done**
     - ``Money Account``: 17 types, opening balance + date, currency, icon, colour,
       ``is_active``, notes, credit limit, masked number, institution,
       ``include_in_net_worth``. Grouped by a ``Money Account Group`` tree. Reconciliation
       added in A1.
   * - 3
     - Transfers
     - **Done** *(A1)*
     - ``strategies/transfer.py`` posts a Contra Entry whose *movement* touches only
       balance-sheet accounts. A1 added the **fee leg**, which is the one part that is expense —
       the source pays amount plus fee, the destination receives the amount.
   * - 4
     - Recurring transactions
     - **Partial**
     - ``Money Recurring Transaction``: six frequencies, nightly job with a savepoint per plan,
       month-end-safe ``nth_date``, Pause/Resume via ``status``, end date, ``post_due_now``.
       Missing: **Skip Next**, **custom interval**, **reminder before execution**.
   * - 5
     - Bill & payment reminders
     - **Done** *(A1)*
     - ``Money Bill``: due date, six repeat frequencies, Mark Paid posting a Transaction and
       minting the successor, a daily reminder job, and two Number Cards.
   * - 6
     - Receipt management
     - **Done** *(A1)*
     - ``Money Receipt``: file, image, thumbnail, and the OCR columns nothing fills yet.
       Standalone rather than a child table, so an unattached receipt is an inbox.
   * - 7
     - Tags
     - **Done** *(A1)*
     - ``Money Tag`` + ``Money Transaction Tag``, a real child table so tag spend is a GROUP BY.
       Totals overlap by design and are never summed.
   * - 8
     - Calendar view
     - **Absent**
     - No calendar JS, no ``doctype_calendar_js`` hook.
   * - 9
     - Advanced search
     - **Partial**
     - A1 added **tags**, **merchant** (resolved through ``merchants.search_names``, since the
       column now holds IDs) and **reference number**. Still missing: **saved filters** and
       global search registration — both A2.
   * - 10
     - Analytics
     - **Partial**
     - 5 charts over 4 sources; category pie, monthly trend, cash flow, income-vs-expense,
       budget-vs-actual all present. Missing: **weekly/daily grain surfaced**, **top
       merchants**, **account distribution**, **drill-down**.
   * - 11
     - Reports
     - **Partial**
     - ERPNext's GL / Trial Balance / Balance Sheet / P&L / Cash Flow are per-tracker via the
       Accounting Dimension. But **``report/`` does not exist** — the app owns zero reports.
   * - 12
     - Backup & restore
     - **Partial**
     - ``bench backup`` plus core ``Google Drive``, ``Dropbox Settings``, ``S3 Backup
       Settings``. **Wiring and documentation only.**
   * - 13
     - Cloud sync
     - **Absent**
     - No sync surface, no idempotency keys, no versioned API namespace.
   * - 14
     - Notification centre
     - **Partial**
     - Both daily jobs write ``Notification Log``, and ``Money Budget.last_alert`` dedupes.
       Missing: **preferences**, **more event types**, **digest**.
   * - 15
     - Goals
     - **Done**
     - ``Money Goal``: six measures, derived outcomes, window clamping, progress bar, card and
       chart.
   * - 16
     - Savings tracker
     - **Done**
     - Savings rate card, Savings and Savings Rate goal types, ``trends.get_totals`` as the
       single §62 refund rule.
   * - 17
     - Debt & loan management
     - **Absent**
     - Three strings only — a ``Loan`` account type, a ``Loan Payment`` transaction type in
       ``strategies.PLANNED``, a Debt Payoff goal. No principal, rate, tenure, EMI or schedule.
   * - 18
     - Subscription tracker
     - **Absent**
     - Boundary drawn in ``services/recurring.py``'s docstring; nothing built.
   * - 19
     - Merchant management
     - **Done** *(A1)*
     - ``Money Merchant`` master, ``Transaction.merchant`` migrated Data → Link by
       ``patches/v1_1/link_merchants``, defaults that fill a blank field on entry, and
       per-merchant totals that — unlike tags — partition the money.
   * - 20
     - Payment methods
     - **Partial**
     - ``Money Payment Method`` exists with Links from Transaction and Recurring Transaction.
       Missing: **analytics by method**; ``applies_to_account_type`` is unvalidated free text.
   * - 21
     - Attachments
     - **Done** *(A1)*
     - Same as #6. Voice notes remain unbuilt.
   * - 22
     - Currency support
     - **Partial**
     - ``currency`` on seven DocTypes, ``exchange_rate`` (precision 9) + read-only
       ``base_amount``, ``services/fx.py`` over ERPNext rates. But ``enable_multi_currency``
       defaults **0** and there is **no converted reporting**.
   * - 23
     - Security
     - **Partial**
     - ``permissions.py`` isolates by tracker across **11** DocTypes; 4 Finance roles. Core supplies
       ``Version``, ``Activity Log``, ``Access Log``. Missing: **``track_changes`` not
       enabled**, **PIN lock** (client-side), **``Money Account Group`` / ``Money Payment
       Method`` unscoped** (defensible — they are shared masters — but undocumented).
   * - 24
     - Import & export
     - **Partial**
     - Core ``Data Import`` covers CSV/Excel in; Report Builder and ``Prepared Report`` cover
       CSV/Excel out. Missing: **bank statement import**, **PDF export** (no print format),
       **JSON export**.
   * - 25
     - Settings
     - **Partial**
     - ``Money Settings`` holds company, base currency, cost centre, default tracker, 8 CoA
       parents, 3 behaviour flags. Missing: **date format, theme, language, timezone,
       notification preferences** — most of which are core User/System Settings and should not
       be duplicated.
   * - 26
     - Dashboard widgets
     - **Partial**
     - 9 cards + 5 charts on a Workspace that Frappe already lets a user re-arrange in edit
       mode. Missing: **per-user dashboards**, upcoming-bills and recent-transactions widgets.
   * - 27
     - Audit trail
     - **Partial**
     - Core ``Version`` records old/new/user/timestamp — but **``track_changes`` is not set on
       any app DocType**, so nothing is being recorded. A one-line-per-DocType fix.
   * - 28
     - Offline support
     - **Absent**
     - Same as #13.
   * - 29
     - AI-ready architecture
     - **Absent**
     - No OCR columns, no categorisation rules, no duplicate detection, no insight storage.
   * - 30
     - Frappe deliverables per feature
     - —
     - Specified per module below, with the shared conventions stated once in §3.


Two corrections worth stating plainly
-------------------------------------

**Budget carry-forward already exists and is better than asked for.** ``Money Budget.rollover``
carries the **deficit as well as the surplus** — the reasoning in ``CLAUDE.md`` is that an
envelope which forgets last month's overspend is two budgets wearing one name.

**A transfer cannot appear as income or expense by construction, not by policy.** Both legs are
balance-sheet accounts. That is a structural guarantee most expense managers only assert.


Part A · Expense-manager parity
===============================

Phase A1 — core missing functionality — **built**
--------------------------------------------------

.. note::

   All seven shipped on 2026-08-22, on branches ``feat/phase-3-tags``,
   ``feat/phase-3-merchants``, ``feat/phase-3-splits``, ``feat/phase-3-transfer-fees`` and
   ``feat/phase-3-a1-rest``. The specifications below are kept as written rather than rewritten
   in the past tense — where the built thing differs from the plan, ``progress.md`` and
   ``docs/architecture.md`` are the record.

   The manual Desk pass this phase was gated on is **still owed**, and now covers §17–§22 of
   ``docs/manual-test-desk.md``.

A1.1 · Tags
~~~~~~~~~~~

Core Frappe tagging is ``_user_tags``, a comma-joined text column — it filters, but it cannot
be grouped or summed, so "spend by tag" would be a ``LIKE`` scan. ``Tag Link``, which would fix
that, **is not present in this Frappe version** (checked). Tag analytics therefore needs a real
child table.

- ``Money Tag`` (``TAG-.#####``, tracker-scoped, name unique per tracker, colour + icon).
- ``Money Transaction Tag`` child table on ``Transaction`` and ``Money Recurring Transaction``.
- ``services/tags.py`` — ``get_spend_by_tag(tracker, from_date, to_date)``, one aggregate join,
  the refund rule taken from ``categories.net_sign()`` rather than restated.
- ``api/tags.py`` — ``get_tags``, ``get_spend_by_tag``; ``search_transactions`` gains a ``tags``
  filter.
- Chart source ``Money Tag Totals`` + chart ``Spending by Tag``.

A1.2 · Receipts and attachments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``Money Receipt`` (``RCP-.#####``): ``Attach`` + ``Attach Image``, ``thumbnail``,
  ``file_type``, and the OCR-ready columns nothing fills yet — ``ocr_status``, ``ocr_text``,
  ``extracted_amount``, ``extracted_date``, ``extracted_merchant``, ``ocr_confidence``,
  ``ocr_source``. Many per transaction.
- Those columns are the whole point of building it now: B5's OCR pipeline writes into them
  without a schema change, which is what "AI-ready" means concretely (#29).
- Thumbnails generated with **pillow, already installed**.

A1.3 · Merchant master
~~~~~~~~~~~~~~~~~~~~~~

- ``Money Merchant`` (``MER-.#####``, tracker-scoped): name, ``default_category``,
  ``default_payment_method``, contact, address, notes, ``is_active``, plus ``match_patterns``
  for B5's auto-detection.
- ``Transaction.merchant`` **Data → Link**, with ``patches/v1_1/link_merchants.py`` creating a
  master per distinct existing string per tracker and repointing the rows. Re-runnable.
- ``default_category`` fills a blank category on ``before_validate`` — never overwrites a typed
  one.

A1.4 · Split transactions
~~~~~~~~~~~~~~~~~~~~~~~~~

One purchase, several categories — a supermarket run that is 80% Groceries and 20% Household.

- ``Money Transaction Split`` child table: ``category``, ``amount``, ``notes``.
- **The posting engine does not change.** ``strategies/expense.py`` emits N category debits
  against one account credit when splits are present, one otherwise;
  ``engine.validate_balanced`` already enforces the invariant. This is precisely the bargain
  ``posting/strategies/`` was built for — adding behaviour is a strategy edit, never an engine
  edit.
- Controller: splits must sum to ``amount``, every split category must match the transaction
  type and be a leaf.

A1.5 · Transfer fees
~~~~~~~~~~~~~~~~~~~~

``fee_amount`` + ``fee_category`` on ``Transaction``; ``strategies/transfer.py`` emits a third
leg debiting the fee category. Source is debited ``amount + fee``, destination credited
``amount``.

A1.6 · Reconciliation
~~~~~~~~~~~~~~~~~~~~~

- On ``Transaction``: ``reference_no``, ``is_reconciled``, ``cleared_date``.
- On ``Money Account``: a *Reconcile* action taking a statement closing balance and date,
  reporting the difference against ``balances.get_account_balance`` and listing uncleared rows.
- ``services/reconciliation.py``. Deliberately **not** ERPNext's Bank Reconciliation Tool, which
  is built around Payment Entries and invoices this app does not create.

A1.7 · Bills and reminders
~~~~~~~~~~~~~~~~~~~~~~~~~~

The boundary, stated the way this repo states boundaries: **a recurring plan posts money on a
schedule; a bill is a claim that must be settled, and is tracked until it is.** A plan that
posts rent automatically is not waiting for anything. A credit-card bill is.

- ``Money Bill`` (``BIL-.#####``): payee/merchant, amount (or "varies"), ``due_date``,
  ``repeat`` (reusing ``FREQUENCIES``), ``reminder_days_before``, ``status``
  (Upcoming / Due / Overdue / Paid / Skipped), ``linked_transaction``,
  ``recurring_transaction`` (optional — a bill *may* be settled by a plan).
- *Mark Paid* creates the Transaction and back-links it, the same relationship recurring uses.
- Daily job ``services/bills.py:send_bill_reminders``, idempotent on a ``last_reminder`` stamp,
  the pattern ``send_budget_alerts`` already established.
- Widgets: card ``Bills Due``, chart ``Upcoming Bills``.


Phase A2 — productivity
-----------------------

**A2.1 · Money Subscription** — boundary already drawn in ``services/recurring.py``: vendor,
plan name, trial end, renewal date, price-change history (``Money Subscription Price`` child
table), notice period, ``status``. **Links to** a ``Money Recurring Transaction`` for the money;
grows no second schedule. Card ``Subscription Spend``, report *Subscriptions by Renewal*.

**A2.2 · Money Loan** — the case a Debt Payoff goal does *not* cover: amortisation. Principal,
rate, tenure, EMI, start date, ``interest_type``, lender, ``direction`` (Borrowed / Lent),
party. ``Money Loan Schedule`` child table generated by ``services/loans.py:build_schedule()``
— pure, no DB, tested without a site, the same shape as a posting strategy. Implements the
**Loan Payment strategy** currently in ``strategies.PLANNED``, splitting each payment into
principal (liability) and interest (expense). A Debt Payoff goal keeps the simple case; a loan
owns the schedule.

**A2.3 · Budget completion** — ``budget_basis`` (Category / Account / Tracker) so account-wise
budgets work; ``Custom`` period in ``PERIODS`` honouring ``start_date``/``end_date`` literally;
``Money Budget Template`` + ``Money Budget Template Line`` with an *Apply* action minting a
period's worth of budgets; ``Money Budget.parent_template`` for comparison.

**A2.4 · Recurring completion** — ``Money Recurring Skip`` child table (dates to skip, so
``due_dates()`` subtracts them and stays ledger-derived), ``Custom`` frequency with an interval
in days, ``reminder_days_before`` + a pre-execution notification.

**A2.5 · Saved views, calendar, global search** — ``Money Saved View`` (doctype, filters JSON,
``is_shared``); ``transaction_calendar.js`` with income green / expense red and a day click
showing totals; ``global_search_doctypes`` in ``hooks.py``.

**A2.6 · Notification centre** — ``Money Notification Preference`` (per user × event type ×
channel); an ``EVENTS`` registry so budget/bill/recurring/goal/backup all announce through one
path; a weekly digest job.


Phase A3 — analytics and reporting
----------------------------------

The app owns **zero reports today**; ``report/`` does not exist. Create it.

.. list-table::
   :header-rows: 1
   :widths: 30 12 58

   * - Report
     - Type
     - Notes
   * - Monthly Summary
     - Script
     - Income, expense, savings, per-category, MoM delta
   * - Category Analysis
     - Script
     - ``lft``/``rgt`` roll-up, drill to leaves
   * - Tag Analysis
     - Query
     - Needs A1.1
   * - Merchant Analysis
     - Script
     - Needs A1.3; top merchants, frequency, average ticket
   * - Account Statement
     - Script
     - Print-format-backed, PDF
   * - Payment Method Analysis
     - Query
     - Share of spend by method; needs no new schema
   * - Budget vs Actual (multi-period)
     - Script
     - The report ``Money Budget`` never had
   * - Recurring Schedule
     - Script
     - Plan-by-plan, next 12 months
   * - Cash Flow Forecast
     - Script
     - Recurring + bills forward; the honest complement to ERPNext's backward Cash Flow

Plus print formats (Account Statement, Monthly Summary), drill-down on the five existing charts,
and the missing widgets — Recent Transactions, Upcoming Bills, Account Distribution, Top
Categories, Top Merchants.


Phase A4 — premium
------------------

**A4.1 · Statement import** — ``Money Statement Import`` + ``Money Statement Line``. **Zero new
dependencies**: ``pypdf``, ``openpyxl`` and ``xlrd`` are already in the bench venv. An
``INGEST_PARSERS`` registry keyed by bank format, each parser pure and separately testable.
Staged lines are matched against existing transactions (date ± tolerance, amount, reference),
duplicates flagged, unmatched offered for creation. Nothing posts without confirmation.

**A4.2 · Investments and assets** — ``Money Asset``, ``Money Holding``, and the four remaining
``PLANNED`` strategies (Investment Purchase, Investment Sale, Asset Purchase, Asset Sale), plus
Dividend and Interest. This is the seam Part B's portfolio module builds on.

**A4.3 · Multi-currency reporting** — turn ``enable_multi_currency`` into something that means
anything: a presentation-currency filter on every widget and report, converting through
``services/fx.py`` at the row's own date.

**A4.4 · API and sync (mobile)** — a versioned ``moneytracker/api/v1/`` namespace, distinct from
today's unversioned ``api/``, which stays as the Desk-facing surface. ``client_uuid``
idempotency key on every write; ``GET /sync?since=<modified>`` cursor; ``Money Sync Log``
recording conflicts resolved last-writer-wins with the loser retained. PIN lock is a client
concern and needs nothing server-side.

**A4.5 · Backup and audit** — document ``bench backup`` plus the core Google Drive / Dropbox /
S3 integrations rather than rebuilding them; set ``track_changes: 1`` on ``Transaction``,
``Money Account``, ``Money Budget``, ``Money Goal``, ``Money Recurring Transaction`` so core
``Version`` actually records the audit trail #27 asks for.


Part B · The Financial Analyst System
=====================================

Part B is a different kind of software from Part A. Part A records what happened; Part B
*advises*. That difference drives every decision below, and three of them are worth stating
before the modules.


B0 · Three rules that make the advice worth having
--------------------------------------------------

**Point-in-time correctness.** A recommendation must be computed from data as it was known at
the decision date. A transaction dated 3 July but entered on 20 August must not appear in an
"as of 31 July" recommendation — otherwise every backtest of the rule engine is contaminated by
look-ahead bias and no threshold can ever be validated. ``GL Entry`` carries both
``posting_date`` and ``creation``, so this is a filter, not a schema change: one helper in
``services/analyst/asof.py`` returning ``posting_date <= as_of AND creation <= known_at``, used
by every analyst read. Market data gets the same shape through ``as_of`` / ``ingested_on``.
The app discovered this asymmetry once already, in ``recurring.effective_from`` — "a plan
reaches forward, not back". B0 generalises it.

**Confidence is data sufficiency, not model output.** §1's high/medium/low is defined once, in
``services/analyst/confidence.py``, from five observable quantities: months of history, share of
days with any transaction, share of spend uncategorised, account coverage, and days since last
import. Every recommendation is gated on it and weakens as it falls. A recommendation issued on
three weeks of data with 40% of spend uncategorised is noise wearing a confidence interval.

**Advice is scored against what happened.** Not in the brief; added here because without it
there is no label set for any model, no evidence a threshold is right, and no way to tell a good
recommendation from a merely confident one. ``Money Recommendation`` stores what was said and on
what inputs; a scheduled job writes ``Money Recommendation Outcome`` N periods later. This is
also what turns §13's audit trail from a disclaimer into a measurement.

**Two deliberate exceptions to "derive, never store."** The app's central rule is that figures
are measured from the ledger on read. Part B breaks it twice, on purpose: **external
observations** (a stock price, a reported EPS, a cohort benchmark) have no ledger to be derived
from and are stored with source and as-of date; **advice snapshots** are immutable, because the
point of an audit trail is what was said, not what would be said now. Everything personal —
ratios, savings rate, cash flow, runway, allocation — stays derived.


Phase B1 — profile and foundation
---------------------------------

- ``Money Financial Profile`` (one per tracker): age, dependents, income and its stability,
  employment type, ``risk_tolerance``, ``financial_maturity``, ``time_horizon``,
  ``tax_bracket``.
- ``RISK_BANDS`` registry mapping tolerance × horizon → an allowed equity/debt/cash band. Every
  suitability check in B3 reads this table and nothing else.
- ``services/analyst/confidence.py`` and ``services/analyst/asof.py`` — both from B0, both
  before anything consumes them.
- ``Money Analyst Settings`` (single): ``predictor_backend``, benchmark defaults, inflation
  assumption, disclaimer text, retention.


Phase B2 — ratios and the rule engine
-------------------------------------

**RATIOS registry.** Each row names ``formula``, ``window``, ``denominator``, ``benchmark``,
``direction``, ``severity_bands``, ``unit``. The registry exists because ratio definitions are
where finance apps quietly disagree with each other: debt-to-income on gross or net income,
trailing twelve months or annualised last three. **Decided once, versioned, and printed
alongside the number** — a ratio whose denominator is unstated is not a measurement.

Personal set: savings ratio, debt-to-income, expense-to-income, emergency-fund months, burn
rate, fixed-vs-discretionary share, liquidity. Each reuses an existing service —
``trends.get_totals``, ``balances.get_net_worth``, ``recurring.get_fixed_costs`` — rather than
recomputing from ``GL Entry``, so the §62 refund rule keeps its single implementation.

**RULES registry** (§8): predicate, severity (Informational / Warning / Critical), message
template, remediation, and the ratios it reads. Findings are ``Money Finding`` rows.

**Arbitration, made testable.** §9 says ML must not override rules. That is implemented as an
explicit merge order in ``services/analyst/arbitrate.py``: a model finding that contradicts a
rule finding is downgraded, and a model finding never rises above Warning on its own. A test
asserts it for every rule.


Phase B3 — market data and portfolio
------------------------------------

**Shared masters, not tracker-scoped** — a stock price is the same fact for every user:
``Money Security``, ``Money Price``, ``Money Fundamental``, ``Money Sector``,
``Money Benchmark``, ``Money Market Data Source``. Only holdings are private.

``INGEST_PARSERS`` keeps the provider swappable; a daily RQ job fetches prices, a weekly one
fundamentals. Every row stores ``source``, ``as_of``, ``ingested_on``.

**Portfolio analytics — Money Portfolio, Money Holding (tracker-scoped).** The measures below
are chosen because they are the ones retail tools usually get wrong:

- **XIRR *and* TWR, both, labelled.** Money-weighted return answers "how am I doing", since the
  user's own contribution timing is part of their result. Time-weighted answers "is this fund
  any good", stripping timing out. They are different questions with different answers and
  conflating them is the standard error. XIRR by bisection — pure Python, no scipy.
- **HHI for concentration; effective holdings = 1/HHI for diversification.** Named, standard
  measures rather than a hand-rolled 0–100 score nobody can interpret or dispute.
- **Benchmark comparison as a counterfactual** — the user's own cash flows applied to the index.
  Comparing a portfolio's return against an index return over differently-timed cash flows is
  not a comparison; it is two unrelated numbers side by side.
- Sector exposure, max drawdown, realised volatility, and suitability checked against B1's risk
  band.


Phase B4 — trends, forecasting, scenarios
-----------------------------------------

**Robust statistics throughout.** Household spend is heavy-tailed and seasonal; one laptop
purchase poisons a three-month mean and turns a normal month into an alert. Baselines use
**median and MAD**, trimmed means and winsorised inputs. Fixed and discretionary are separated
*before* any trend is computed — and the app already knows its fixed costs from
``recurring.get_fixed_costs()``, which is a genuine head start over a flat transaction table.

**Forecasts are quantiles, never points.** P10/P50/P90 from bootstrapped residuals off a
seasonal-naive-plus-drift baseline. On twelve months of data that is the honest model; anything
heavier overfits and reports its overfitting as precision. Runway then reads *"3.1–5.4 months at
P10–P90"*, not *"4.2 months"* — which is both more truthful and more useful, because the
decision changes at 3.1 and not at 4.2.

**Anomaly detection** is a robust z-score per (category, merchant) with a minimum sample size,
plus a seasonal-naive comparison against the same month last year. A global z-score over all
spend flags every large legitimate purchase and is worse than nothing.

**SCENARIOS registry** (§12) — income reduction, expense inflation, market drawdown, job loss,
rate rise. Each scenario re-runs **the same measurement functions** against a perturbed view
rather than reimplementing them. That only works because every figure in this app already goes
through a named service, and it is the single largest payoff from the existing architecture:
stress testing costs a perturbation layer, not a parallel implementation to keep in sync.


Phase B5 — advisor, compliance, feedback
----------------------------------------

- ``Money Recommendation`` — immutable. Stores the advice, the inputs, the rule version, stated
  assumptions, the confidence band, and **alternatives rather than commands** (§10).
- ``Money Explainability Log`` — the derivation behind each recommendation, so "why" is
  answerable from data instead of regenerated prose.
- Compliance: educational-only disclaimer, source attribution, assumption disclosure on every
  surface that carries advice.
- **``Money Recommendation Outcome`` + the scoring job** — B0's feedback loop.
- **Tier-1 ML** behind the ``predictor`` interface, trained on the labels the feedback loop
  produced: NLP categorisation, learned anomaly detection, duplicate detection, merchant
  auto-detection. Tier-2 (OCR into A1.2's columns, embeddings) over HTTP if it is ever needed.


ML: three tiers, one interface
------------------------------

The bench venv has **no numpy, pandas, scipy or scikit-learn**. It has ``pypdf``, ``openpyxl``,
``xlrd``, ``rq``, ``redis``, Python 3.12. That decides the hosting question:

.. list-table::
   :header-rows: 1
   :widths: 10 24 26 40

   * - Tier
     - Where
     - Dependencies
     - Covers
   * - **0**
     - in-bench, RQ
     - **none** — stdlib ``statistics``, ``math``
     - every ratio, robust baselines, quantile bootstrap, HHI, XIRR/TWR, seasonal-naive
       forecasting, z-score anomalies, keyword categorisation
   * - **1**
     - in-bench, RQ
     - ``numpy`` + ``scikit-learn``, **imported lazily inside the job**
     - NLP categorisation, learned anomaly detection
   * - **2**
     - separate FastAPI service
     - its own
     - OCR, embeddings — anything genuinely heavy

All three sit behind ``services/analyst/ml/predictor.py``, selected by
``Money Analyst Settings.predictor_backend``. A missing Tier-1 dependency **degrades to the
Tier-0 baseline**; it does not break ``migrate``.

This reads §14's "separate ML services" as a *module* boundary rather than a *process* one. For
one household — thousands of rows, not millions — a separate service buys horizontal scale that
will never be needed, and costs a deployment, an auth contract and a second failure mode.
Tier 2 is the escape hatch if that stops being true.

**Tier 0 is not a placeholder.** Every number in §5, §6, §7, §8 and §12, and honest baselines
for §9, are computable with zero new dependencies. Nothing in the analyst brief is blocked on
installing a scientific stack.


§3 · Frappe deliverables — stated once
======================================

Repeating nineteen rows per module would bury the deltas. Everything below applies to **every**
new DocType in this document; module sections state only what differs.

**Naming.** ``Money`` prefix without exception — DocType names are globally unique per site and
ERPNext already owns ``Account``, ``Budget``, ``Asset``, ``Subscription``, ``Journal Entry``,
``GL Entry``, ``Payment Entry``, ``Cost Center``. A three-letter uppercase ``autoname`` series,
``XXX-.#####``, no ``naming_rule`` key. Module ``"Money Tracker"``. *(All 28 proposed names were
checked against the* ``frappe`` *and* ``erpnext`` *trees — no collisions.)*

**Permissions.** A tracker-scoped DocType must be added to **both** dicts in ``hooks.py``:
``permission_query_conditions`` and ``has_permission``, both pointing at
``permissions.tracker_scoped_*``. ``tests/test_permissions.py`` derives ``SCOPED_DOCTYPES`` from
the hook dict, so registering in one only **fails outright**. This is the app's only tenant
isolation — treat it as security code. Part B's shared masters (``Money Security``,
``Money Price``, ``Money Fundamental``, ``Money Sector``, ``Money Benchmark``) are deliberately
**not** scoped, and that decision belongs in their docstring so the next reader does not "fix"
it.

**Registry table.** Every module gets one: a frozen dataclass, a module-level dict,
``OPTIONS = tuple(REGISTRY)`` pinned by a test against the DocType Select, and a ``get_x()``
that throws listing valid names. ``GOAL_TYPES``, ``PERIODS``, ``FREQUENCIES``,
``ACCOUNT_TYPE_MAP`` and ``STRATEGIES`` are the same pattern five times over; ``RATIOS``,
``RULES``, ``SCENARIOS``, ``RISK_BANDS`` and ``INGEST_PARSERS`` make it ten. Adding a variant is
a dict row and one small function.

**Widgets.** Fixtures live at
``money_tracker/{number_card,dashboard_chart,dashboard_chart_source}/<snake>/``. A card returns a
**formatted string**, never a number. A card's ``document_type`` must be one the reader can
actually read. A chart's ``roles`` must be ``[]``. **name must equal label must equal the string
in the workspace content block** — ``block.js`` resolves widgets by label and renders *nothing,
with no console error*, on a miss; all nine widgets were blank for two days because of this.
**Bump ``modified``** in any widget JSON you edit, or the import silently no-ops.
``Dashboard Chart Source`` rides ``sync_all``; ``Number Card`` and ``Dashboard Chart`` ride
``sync_dashboards`` at the end of ``migrate``.

**Jobs.** Idempotent, savepoint per item, ``frappe.log_error`` and continue — the shape
``run_recurring_transactions`` established. Note that **``frappe.enqueue`` appears nowhere in
the app today**; Part B's ingestion and scoring jobs are its first users.

**Workflows.** None proposed. Frappe ``Workflow`` earns its keep on multi-party approval; every
state machine here (bill status, recommendation lifecycle, import status) is single-actor and
belongs in a controller, where it can be tested without a Workflow document.

**Tests.** Cross-cutting in ``moneytracker/tests/``, controller rules beside the controller.
Fixtures via ``tests/utils.py`` factories only — they mint unique names because
``coa.get_or_create_ledger_account`` matches on name and ignores the parent. ``FrappeTestCase``
rolls back per **class**, not per test.


§4 · Sequencing
===============

.. list-table::
   :header-rows: 1
   :widths: 38 10 12 30 10

   * - Module
     - Track
     - Phase
     - Depends on
     - Size
   * - Manual Desk pass
     - —
     - **gate**
     - —
     - S
   * - Tags ✅
     - A
     - A1
     - Desk pass
     - M
   * - Receipts ✅
     - A
     - A1
     - Desk pass
     - M
   * - Merchant master ✅
     - A
     - A1
     - Desk pass
     - M
   * - Splits ✅
     - A
     - A1
     - Desk pass
     - M
   * - Transfer fees ✅
     - A
     - A1
     - —
     - S
   * - Reconciliation ✅
     - A
     - A1
     - —
     - M
   * - Bills ✅
     - A
     - A1
     - —
     - L
   * - Subscriptions
     - A
     - A2
     - Bills
     - M
   * - Loans + Loan Payment
     - A
     - A2
     - —
     - L
   * - Budget completion
     - A
     - A2
     - —
     - M
   * - Recurring completion
     - A
     - A2
     - —
     - S
   * - Saved views / calendar / search
     - A
     - A2
     - Tags, Merchant
     - M
   * - Notification centre
     - A
     - A2
     - Bills
     - M
   * - Reports
     - A
     - A3
     - Tags, Merchant
     - L
   * - Statement import
     - A
     - A4
     - Merchant, Reconciliation
     - L
   * - Investments and assets
     - A
     - A4
     - —
     - L
   * - Multi-currency reporting
     - A
     - A4
     - —
     - M
   * - API v1 + sync
     - A
     - A4
     - —
     - L
   * - Backup + track_changes
     - A
     - A4
     - —
     - S
   * - Profile + confidence + as-of
     - B
     - B1
     - —
     - M
   * - Ratios + rule engine
     - B
     - B2
     - **B1**
     - L
   * - Market data + portfolio
     - B
     - B3
     - A4.2
     - XL
   * - Trends + forecast + scenarios
     - B
     - B4
     - B2
     - L
   * - Advisor + compliance + feedback
     - B
     - B5
     - B2, B4
     - L
   * - Tier-1 ML
     - B
     - B5
     - Feedback loop
     - M

**Two hard gates.** The Desk pass before A1. And B1's confidence and as-of services before any
B2 rule fires — a rule engine without point-in-time reads and a confidence floor produces advice
that cannot be evaluated, which is worse than no advice, because it looks like advice.

Per the standing instruction, each module goes on **its own branch** and committing is the
user's.


§5 · Decisions register
=======================

Each entry is settled. Re-open one only with a reason that is new, and amend the entry rather
than arguing beside it. Sections above state *what* is to be built; this states *why the
boundaries sit where they do*.

D1 — One app, two independent tracks
------------------------------------

Part A (expense-manager parity) and Part B (financial analyst) live in ``moneytracker`` as new
``Money *`` DocTypes, with **separate phase ladders**. Either can be dropped without stranding
the other.

*Rejected:* a second Frappe app. Every analyst ratio reads the same ``GL Entry`` rows the
dashboard already reads, and a cross-app boundary would mean forking ``permissions.py`` — the
app's only tenant isolation, and therefore security code.

D2 — ML runs in-bench, in three tiers, behind one interface
-----------------------------------------------------------

The bench venv has **no numpy, pandas, scipy or scikit-learn**; it has ``pypdf``, ``openpyxl``,
``xlrd``, ``rq``, ``redis``, Python 3.12. That fact decided this. The tier table is in
*ML: three tiers, one interface* above; the reasoning is here.

The brief's "separate ML services" is honoured as a **module** boundary, not a **process** one.
For one household — thousands of rows — a separate service buys horizontal scale that will
never be needed and costs a deployment, an auth contract and a second failure mode. Tier 0 is
not a placeholder: nothing in the analyst brief is blocked on installing a scientific stack.
Tier 2 exists so that stops being an assumption and becomes a switch.

D3 — "Derive, never store" keeps two documented exceptions
-----------------------------------------------------------

The app measures figures from ``GL Entry`` on read. Part B breaks that twice, deliberately:

- **External observations are stored** — a stock price, a reported EPS, a cohort benchmark.
  There is no ledger to re-derive them from. Every row carries ``source``, ``as_of``,
  ``ingested_on``.
- **Advice snapshots are immutable** — an audit trail records what was said, not what would be
  said now.

Everything personal — ratios, savings rate, cash flow, runway, allocation — **stays derived**.

D4 — Point-in-time correctness is mandatory
--------------------------------------------

A recommendation is computed from data as it was known at the decision date. A transaction
dated 3 July but entered on 20 August must not appear in an "as of 31 July" figure, or every
backtest of the rule engine carries look-ahead bias and no threshold can ever be validated.

``GL Entry`` has both ``posting_date`` and ``creation``, so this is a filter, not a schema
change: one helper in ``services/analyst/asof.py``. The app already found this asymmetry once,
in ``recurring.effective_from`` — *a plan reaches forward, not back*. D4 generalises it.

D5 — Recommendations are scored against what happened
-------------------------------------------------------

``Money Recommendation`` stores the advice and its inputs; a scheduled job writes
``Money Recommendation Outcome`` N periods later.

*Not in either brief.* Without it there is no label set for Tier-1 ML, no evidence any
threshold is right, and no way to tell a good recommendation from a confident one.

D6 — Confidence is data sufficiency, not model output
-------------------------------------------------------

Defined once in ``services/analyst/confidence.py`` from five observables: months of history,
share of days with any transaction, share of spend uncategorised, account coverage, days since
last import. Every recommendation is gated on it and weakens as it falls.

D7 — Shared masters are not tracker-scoped; holdings are
----------------------------------------------------------

A stock price is the same fact for every user. ``Money Security``, ``Money Price``,
``Money Fundamental``, ``Money Sector``, ``Money Benchmark`` carry ordinary role permissions and
are **deliberately** outside ``permissions.py``. Say so in their docstrings so nobody "fixes"
it. Holdings, portfolios, recommendations and every ingestion artefact are scoped.

D8 — Desk and mobile, off one versioned API
---------------------------------------------

Desk stays the operator surface. Mobile targets ``moneytracker/api/v1/``, kept separate from
today's unversioned ``api/``: ``client_uuid`` idempotency keys on write, a ``modified``-cursor
sync endpoint, ``Money Sync Log`` for conflicts. PIN lock is a client concern; the server
exposes nothing for it.

D9 — Reuse the platform
------------------------

Confirmed present in this bench and **not to be rebuilt**: ``Version`` (audit trail),
``Activity Log``, ``Access Log``, ``Notification Log``, ``Tag``, ``Data Import``,
``Prepared Report``, ``Google Drive`` / ``Dropbox Settings`` / ``S3 Backup Settings``,
``Auto Repeat``. ERPNext supplies General Ledger, Trial Balance, Balance Sheet, P&L and Cash
Flow, already per-tracker.

**One exception:** core ``Tag Link`` does **not** exist in this Frappe version. Tags live in
``_user_tags``, a comma-joined text column that cannot be aggregated — so tag *analytics* needs
a real child table.

D10 — Every module gets a registry table
------------------------------------------

A frozen dataclass, a module-level dict, ``OPTIONS = tuple(REGISTRY)`` pinned by a test against
the DocType Select, and a ``get_x()`` that throws listing valid names. ``GOAL_TYPES``,
``PERIODS``, ``FREQUENCIES``, ``ACCOUNT_TYPE_MAP`` and ``STRATEGIES`` are this pattern five
times; ``RATIOS``, ``RULES``, ``SCENARIOS``, ``RISK_BANDS``, ``INGEST_PARSERS`` make it ten.
Adding a variant is a dict row and one small function.

D11 — Documentation formats
-----------------------------

This file is reStructuredText at the user's request. The rest of ``docs/`` remains Markdown
(``architecture.md``, ``manual-test-desk.md``). If more docs go RST, convert the set rather than
letting the split widen.

``plan.md`` and ``task.md`` are both in ``.gitignore``, under the *Claude / AI context* block
alongside ``CLAUDE.md`` — deliberate, and the reason this register lives here rather than
there: a decisions register that is not in the repository is not a decisions register.
