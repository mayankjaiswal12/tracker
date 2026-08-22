# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Recurring transactions: a Transaction template plus a schedule, and the job that runs it.

**A recurring transaction is the first thing in this app that writes money on its own.**
Everything before it reads: a budget measures spending, a goal measures progress, a card
totals a window. A plan *posts* — every month at 3am, whether anyone is looking or not — and
almost every decision below follows from that one difference.

**Where it stops, and what a subscription would own.** A plan is the money and the calendar:
this amount, this account, this category, every month. It knows nothing about *who* is being
paid or on what terms. A `Money Subscription` (not built) would own exactly that — vendor,
plan name, trial end, renewal date, the price-change history, the notice period to cancel by
— and would **link to** a plan for the money rather than grow a second schedule of its own.
That is the same boundary `Money Budget` draws against a `Spending Limit` goal: name what
each one owns, then keep the other's fields off it.

**The plan stores nothing about what it has done.** No counter, no `last_run`, no next-date
cache — not even the `last_alert` field `Money Budget` allows itself. It does not need one:
every generated Transaction carries `recurring_transaction` back to its plan, so "has the
2nd of September been posted?" is a question the ledger answers. A stored counter would drift
the first time somebody cancelled a generated transaction, and nothing in the data would say
that it had (§68).

`FREQUENCIES` is the single table describing each kind of schedule — the step to the next
occurrence and how many of them fall in an average month. Adding a fortnightly-on-Fridays
plan is a row in that table; nothing else in the module knows which frequency it is looking
at.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, fmt_money, getdate, today

# Derived outcomes. Never stored — worked out from the schedule and the ledger on every read,
# and worded for a plan rather than for an envelope or a goal: a plan is not something you
# are trying to reach or trying not to empty, it is something that is either running or not.
NOT_STARTED = "Not Started"
SCHEDULED = "Scheduled"
DUE = "Due"
PAUSED = "Paused"
ARCHIVED = "Archived"
ENDED = "Ended"

# What "this plan is running as intended" means. `Due` is not in it: an occurrence whose date
# has passed with nothing posted means the scheduler has not run, which is worth seeing.
HEALTHY_OUTCOMES = (SCHEDULED, NOT_STARTED)

# The transaction types a plan may repeat. The other implemented strategy, `Refund`, is
# deliberately absent: a refund answers one particular expense, and a schedule cannot know
# which one it is answering. The nine `strategies.PLANNED` types are absent because nothing
# can post them yet.
RECURRING_TYPES = ("Expense", "Income", "Transfer", "Credit Card Payment")

# How a generated transaction is left. A plan for a fixed amount posts itself; a plan for a
# bill that varies — a phone bill, an electricity bill — is better off leaving a draft with
# the right shape for somebody to correct the amount on.
POST_AUTOMATICALLY = "Post Automatically"
CREATE_AS_DRAFT = "Create as Draft"
CREATE_MODES = (POST_AUTOMATICALLY, CREATE_AS_DRAFT)

# Average days in a month over a four-year cycle. Used only to normalise a weekly or daily
# plan onto a monthly figure, which is the one comparison people actually make between a
# rent and a gym membership.
DAYS_PER_MONTH = 365.25 / 12

# Bounds on the occurrence walk. `MAX_OCCURRENCES` stops a malformed plan spinning forever
# and is far above any real schedule — a daily plan running for thirteen years. `MAX_PER_RUN`
# bounds one plan's share of one nightly run: if the scheduler has been down for a year, a
# daily plan posts sixty transactions tonight and the rest tomorrow, rather than opening a
# four-hundred-write transaction in a background job. Nothing is lost — an unposted
# occurrence stays due until it is posted.
MAX_OCCURRENCES = 5000
MAX_PER_RUN = 60

# How many posted occurrences `measure()` hands back for the form's history strip.
HISTORY_LIMIT = 12


@dataclass(frozen=True)
class Frequency:
	"""One kind of schedule.

	`step`       `add_to_date` keywords for **one** occurrence's worth of time. Multiplied by
	             `n` to reach the nth occurrence, never applied repeatedly — see `nth_date`.
	`per_month`  occurrences in an average month, for the monthly-equivalent figure.
	`noun`       what one interval is called, so a form can say "every month" without a
	             second table mapping the same six words.
	"""

	step: dict
	per_month: float
	noun: str


FREQUENCIES = {
	"Daily": Frequency({"days": 1}, DAYS_PER_MONTH, "day"),
	"Weekly": Frequency({"days": 7}, DAYS_PER_MONTH / 7, "week"),
	"Fortnightly": Frequency({"days": 14}, DAYS_PER_MONTH / 14, "fortnight"),
	"Monthly": Frequency({"months": 1}, 1.0, "month"),
	"Quarterly": Frequency({"months": 3}, 1 / 3, "quarter"),
	"Yearly": Frequency({"years": 1}, 1 / 12, "year"),
}

# The Select on the DocType must list exactly these, in this order.
FREQUENCY_OPTIONS = tuple(FREQUENCIES)


def get_frequency(frequency):
	spec = FREQUENCIES.get(frequency)
	if not spec:
		frappe.throw(
			_("Unknown Frequency {0}. Supported frequencies: {1}.").format(
				frequency, ", ".join(FREQUENCY_OPTIONS)
			)
		)
	return spec


# --- the calendar ----------------------------------------------------------------------


def nth_date(start_date, frequency, n):
	"""The nth occurrence of a schedule, counting the start date as the 0th.

	**Always measured from the start date, never by stepping off the previous occurrence.**
	That is the whole month-end rule in one line: a plan starting on 31 January lands on 28
	February, because `relativedelta` clamps a short month — and then on **31** March, because
	March is `start + 2 months` and not `February + 1 month`. Stepping would have lost the
	31st for good the first time it passed a short month.
	"""
	spec = get_frequency(frequency)
	start_date = getdate(start_date)
	if not n:
		return start_date
	return getdate(add_to_date(start_date, **{unit: value * n for unit, value in spec.step.items()}))


def occurrences(start_date, frequency, to_date, from_date=None, end_date=None, limit=None):
	"""Every occurrence of a schedule up to `to_date`, oldest first.

	`from_date` filters the *result* rather than moving the anchor: the schedule's shape is
	fixed by `start_date`, so asking for September's occurrences of a plan that began in
	April must still answer on the plan's own day of the month.
	"""
	start_date = getdate(start_date)
	horizon = getdate(to_date)
	if end_date:
		horizon = min(horizon, getdate(end_date))
	from_date = getdate(from_date) if from_date else None

	dates = []
	for n in range(MAX_OCCURRENCES):
		date = nth_date(start_date, frequency, n)
		if date > horizon:
			break
		if from_date and date < from_date:
			continue
		dates.append(date)
		if limit and len(dates) >= limit:
			break
	return dates


def next_date(plan, after=None):
	"""The first occurrence strictly after `after` (default today), or None once it is over.

	The plan's window closes on `end_date`: a finished plan has no next date, which is what
	makes `Ended` a fact about the schedule rather than a status somebody has to remember to
	set.
	"""
	after = getdate(after or today())
	end_date = getdate(plan.end_date) if plan.end_date else None
	if end_date and after >= end_date:
		return None

	start_date = getdate(plan.start_date)
	if start_date > after:
		return start_date

	for n in range(MAX_OCCURRENCES):
		date = nth_date(start_date, plan.frequency, n)
		if date > after:
			return date if not end_date or date <= end_date else None
	return None


def effective_from(plan):
	"""The earliest date a plan may **post**, which is never before it was written down.

	A plan reaches forward, not back. Somebody who types a rent that started in April is
	describing history they have already entered by hand, and generating five months of rent
	on top of it would duplicate real money — so generation starts at the later of the start
	date and the day the plan itself was created.

	Note the deliberate asymmetry with `Money Budget`, which measures from its start date
	whatever day it was created on. A budget only ever *reads* the ledger; it can look back
	safely because looking back cannot write anything.
	"""
	created = getdate(plan.creation) if plan.get("creation") else getdate(today())
	return max(getdate(plan.start_date), created)


# --- measurement -----------------------------------------------------------------------


def measure(plan, as_of=None):
	"""Every derived figure for one plan, as a `frappe._dict`.

	`as_of` moves the whole measurement in time, which is what makes it testable and what
	lets the form answer "what was outstanding last Friday?".
	"""
	plan = plan if hasattr(plan, "doctype") else frappe.get_doc("Money Recurring Transaction", plan)
	spec = get_frequency(plan.frequency)

	as_of = getdate(as_of or today())
	amount = flt(plan.amount)
	posted = _posted_rows(plan.name)

	result = frappe._dict(
		{
			"recurring": plan.name,
			"recurring_name": plan.recurring_name,
			"tracker": plan.tracker,
			"status": plan.status,
			"frequency": plan.frequency,
			"frequency_noun": spec.noun,
			"transaction_type": plan.transaction_type,
			"create_mode": plan.create_mode,
			"account": plan.account,
			"destination_account": plan.destination_account,
			"category": plan.category,
			"currency": plan.currency,
			"color": plan.color,
			"amount": amount,
			"start_date": getdate(plan.start_date),
			"end_date": getdate(plan.end_date) if plan.end_date else None,
			"effective_from": effective_from(plan),
			"as_of": as_of,
			# What this plan costs in an average month, whatever clock it runs on. The one
			# figure that lets a yearly insurance premium be compared with a monthly rent.
			"monthly_equivalent": flt(amount * spec.per_month, 2),
			"posted_count": len([row for row in posted if row.docstatus == 1]),
			"posted_total": flt(sum(flt(row.amount) for row in posted if row.docstatus == 1)),
			"draft_count": len([row for row in posted if row.docstatus == 0]),
			"cancelled_count": len([row for row in posted if row.docstatus == 2]),
			"last_posted": _last_posted(posted),
			"history": [_history_row(row) for row in posted[-HISTORY_LIMIT:]],
		}
	)

	# Only an Active plan can be behind: a paused one is not meant to be posting, so calling
	# its unposted occurrences "due" would be reporting the user's own decision as a fault.
	due = due_dates(plan, as_of) if plan.status == "Active" else []
	result.update(
		{
			"due_dates": due,
			"due_count": len(due),
			"due_amount": flt(amount * len(due)),
			"next_date": next_date(plan, as_of),
			"occurrences_to_date": len(
				occurrences(plan.start_date, plan.frequency, as_of, end_date=plan.end_date)
			),
		}
	)
	result.outcome = _outcome(result)
	return result


def _posted_rows(recurring):
	"""Every transaction this plan has made, oldest first — the plan's whole memory.

	Cancelled rows are kept. A cancelled occurrence is still a date the plan has dealt with,
	and re-posting it tomorrow morning because the count no longer mentions it is exactly the
	failure a stored counter would produce.
	"""
	return frappe.get_all(
		"Transaction",
		filters={"recurring_transaction": recurring},
		fields=["name", "date", "amount", "docstatus", "journal_entry"],
		order_by="date asc, creation asc",
	)


def _last_posted(rows):
	for row in reversed(rows):
		if row.docstatus == 1:
			return {"date": getdate(row.date), "transaction": row.name, "amount": flt(row.amount)}
	return None


def _history_row(row):
	return {
		"date": getdate(row.date),
		"transaction": row.name,
		"amount": flt(row.amount),
		"docstatus": row.docstatus,
		"state": {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(row.docstatus, "Draft"),
	}


def _outcome(row):
	"""The single word for what a plan is doing.

	The user's own intent wins first — a paused plan is paused, and describing it as behind
	would be reporting their decision back to them as a fault. Then the end of the schedule,
	which is a fact and not an opinion. Only then the two live states.
	"""
	if row.status == "Archived":
		return ARCHIVED
	if row.status == "Paused":
		return PAUSED
	if row.next_date is None and not row.due_count:
		return ENDED
	if row.due_count:
		return DUE
	if row.start_date > row.as_of:
		return NOT_STARTED
	return SCHEDULED


def measure_plans(tracker, as_of=None, status="Active", transaction_type=None):
	"""Measure every plan on a tracker, dearest per month first."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status
	if transaction_type:
		filters["transaction_type"] = transaction_type

	rows = frappe.get_all(
		"Money Recurring Transaction",
		filters=filters,
		fields=["name"],
		order_by="amount desc, creation asc",
	)
	return [measure(row.name, as_of) for row in rows]


def get_fixed_costs(tracker, as_of=None):
	"""What the tracker's active expense plans cost in an average month.

	**Expense plans only.** A transfer to a savings account is a commitment but it is not a
	cost — the money is still yours — and an income plan is not a cost by any reading. Adding
	either would produce a figure that answers no question.

	A plan that has not started yet is counted: a rent beginning next month is a commitment
	now, which is the whole reason somebody writes it down in advance. A plan whose schedule
	has run out is not.
	"""
	as_of = getdate(as_of or today())
	rows = frappe.get_all(
		"Money Recurring Transaction",
		filters={"tracker": tracker, "status": "Active", "transaction_type": "Expense"},
		fields=["name", "amount", "frequency", "start_date", "end_date"],
	)

	total = 0.0
	counted = 0
	for row in rows:
		if row.end_date and getdate(row.end_date) < as_of:
			continue
		total += flt(row.amount) * get_frequency(row.frequency).per_month
		counted += 1
	return frappe._dict({"tracker": tracker, "as_of": as_of, "monthly": flt(total, 2), "plans": counted})


def get_forecast(tracker, after=None, months=6, status="Active"):
	"""Scheduled income and expense, month by month, for the months still to come.

	The forward-looking twin of `trends.get_period_series`, and the only series in the app
	that is not measured from the ledger — it cannot be, because none of it has happened. It
	says what the *plans* commit to, which is exactly as much as it should claim.

	**The window opens strictly after `after`, the same rule `next_date` follows.** An
	occurrence dated today has either posted already or is about to, and either way it belongs
	to the actuals the trend chart draws rather than to a forecast; counting it in both would
	show the same rent twice on one dashboard. So the current month's bar is what is *left* of
	the month, and the first bar and `next_date` can never disagree.

	Every month in the range is returned including empty ones, for the same reason the trend
	chart returns them: a month with no rent due should draw a gap, not close it up.
	"""
	after = getdate(after or today())
	first = getdate(add_to_date(after, days=1))
	months = max(int(months or 1), 1)

	# Month buckets, first day to last day, starting with the month `after` falls in — which
	# may be empty, if `after` is the last day of it.
	buckets = []
	for index in range(months):
		start = getdate(add_to_date(after.replace(day=1), months=index))
		buckets.append(
			frappe._dict(
				{
					"label": start.strftime("%b %Y"),
					"from_date": max(start, first),
					"to_date": getdate(add_to_date(add_to_date(start, months=1), days=-1)),
					"income": 0.0,
					"expense": 0.0,
				}
			)
		)

	horizon = buckets[-1].to_date
	plans = frappe.get_all(
		"Money Recurring Transaction",
		filters={"tracker": tracker, "status": status} if status else {"tracker": tracker},
		fields=["name", "amount", "frequency", "transaction_type", "start_date", "end_date"],
	)

	for plan in plans:
		# Transfers and card payments move money between the household's own accounts, so
		# they belong in neither series — the same rule the trend chart follows (§61).
		bucket_key = {"Income": "income", "Expense": "expense"}.get(plan.transaction_type)
		if not bucket_key:
			continue

		for date in occurrences(
			plan.start_date, plan.frequency, horizon, from_date=first, end_date=plan.end_date
		):
			for bucket in buckets:
				if bucket.from_date <= date <= bucket.to_date:
					bucket[bucket_key] += flt(plan.amount)
					break

	return {
		"tracker": tracker,
		"after": after,
		"from_date": first,
		"labels": [bucket.label for bucket in buckets],
		"rows": [
			{
				"label": bucket.label,
				"from_date": bucket.from_date,
				"to_date": bucket.to_date,
				"income": flt(bucket.income),
				"expense": flt(bucket.expense),
			}
			for bucket in buckets
		],
	}


# --- generation ------------------------------------------------------------------------


def due_dates(plan, as_of=None):
	"""Occurrence dates that should have been posted by `as_of` and have not been.

	This is the whole idempotency story, and it is a query rather than a counter: an
	occurrence is handled when a Transaction linked to this plan carries that date,
	**whatever state it is in**. A draft counts, because somebody is meant to be looking at
	it. A cancelled one counts too — cancelling a generated transaction is a decision, and
	posting it again the next morning would overrule it nightly.
	"""
	plan = plan if hasattr(plan, "doctype") else frappe.get_doc("Money Recurring Transaction", plan)
	as_of = getdate(as_of or today())

	dates = occurrences(
		plan.start_date,
		plan.frequency,
		to_date=as_of,
		from_date=effective_from(plan),
		end_date=plan.end_date,
	)
	if not dates:
		return []

	handled = {
		getdate(date)
		for date in frappe.get_all(
			"Transaction",
			filters={"recurring_transaction": plan.name, "date": ["in", dates]},
			pluck="date",
		)
	}
	return [date for date in dates if date not in handled]


def generate(plan, as_of=None):
	"""Post everything this plan owes up to `as_of`. Returns the transaction names created.

	Only an Active plan generates. A paused one keeps its schedule and its history and simply
	does not act on either, which is what makes pausing safe — nothing is lost, and nothing
	is silently caught up on when it resumes, because `effective_from` has not moved.
	"""
	plan = plan if hasattr(plan, "doctype") else frappe.get_doc("Money Recurring Transaction", plan)
	if plan.status != "Active":
		return []

	created = []
	for date in due_dates(plan, as_of)[:MAX_PER_RUN]:
		created.append(_post_occurrence(plan, date))
	return created


def _post_occurrence(plan, date):
	"""One occurrence as a Transaction, submitted unless the plan asks for a draft."""
	transaction = frappe.get_doc(
		{
			"doctype": "Transaction",
			"tracker": plan.tracker,
			"date": date,
			"transaction_type": plan.transaction_type,
			"amount": flt(plan.amount),
			"currency": plan.currency,
			"account": plan.account,
			"destination_account": plan.destination_account,
			"category": plan.category,
			"payment_method": plan.payment_method,
			"merchant": plan.merchant,
			"payee": plan.payee,
			"notes": plan.notes,
			"is_reimbursable": plan.is_reimbursable,
			"is_tax_deductible": plan.is_tax_deductible,
			# Tags come from the plan, so a standing order's occurrences are all labelled the
			# same way without anybody retagging them twelve times a year. Copied as values
			# rather than shared: retagging the plan changes what it posts next month, not what
			# it already posted, which is the same rule the amount follows.
			"tags": [{"tag": row.tag} for row in (plan.tags or [])],
			# The back-link that makes every count above derivable, and that lets the ledger
			# explain itself: this rent is not a one-off somebody typed, it came from a plan.
			"recurring_transaction": plan.name,
		}
	)
	transaction.insert(ignore_permissions=True)
	if plan.create_mode != CREATE_AS_DRAFT:
		transaction.submit()
	return transaction.name


def run_recurring_transactions(as_of=None):
	"""Daily: post every active plan's outstanding occurrences. Returns a summary dict.

	**One plan's failure must not stop the others.** A posting can throw for reasons that
	have nothing to do with the plan being run — no Fiscal Year covering the date, a ledger
	account somebody renamed — and a job that gives up on the first exception would leave the
	rest of the household's standing orders unposted without saying so. Each plan therefore
	runs inside its own savepoint: a failure rolls back that plan alone, is logged, and the
	run carries on.

	Idempotent, and in the strongest sense available: it holds no state at all, so a second
	run on the same day posts nothing because the transactions from the first run are already
	there. Order against `send_budget_alerts` does not matter either — an envelope alerted
	before this morning's rent posted simply alerts again tomorrow with the fuller figure.
	"""
	plans = frappe.get_all("Money Recurring Transaction", filters={"status": "Active"}, pluck="name")

	summary = frappe._dict({"plans": len(plans), "posted": 0, "failed": 0, "notified": 0})
	for name in plans:
		savepoint = f"recurring_{name.replace('-', '_')}"
		frappe.db.savepoint(savepoint)
		try:
			created = generate(name, as_of)
			summary.posted += len(created)
			if created and _notify(name, created):
				summary.notified += 1
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			summary.failed += 1
			frappe.log_error(title=f"Recurring transaction {name} could not post")

	return summary


def _notify(recurring, created):
	"""One Notification Log for the tracker's owner. False when there is nobody to tell.

	No stamp is needed to keep this from repeating, unlike a budget's alert: the notification
	is about transactions that have just been created, and they will never be created again.
	"""
	plan = frappe.get_doc("Money Recurring Transaction", recurring)
	if not plan.notify_on_post:
		return False

	owner = frappe.db.get_value("Tracker", plan.tracker, "owner_user")
	if not owner:
		return False

	currency = plan.currency or frappe.db.get_value("Tracker", plan.tracker, "base_currency")
	money = fmt_money(flt(plan.amount) * len(created), currency=currency)
	if len(created) == 1:
		subject = _("{0} posted {1}").format(plan.recurring_name, money)
	else:
		subject = _("{0} posted {1} transactions totalling {2}").format(
			plan.recurring_name, len(created), money
		)

	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": owner,
			"type": "Alert",
			"document_type": "Money Recurring Transaction",
			"document_name": plan.name,
			"subject": subject,
		}
	).insert(ignore_permissions=True)
	return True
