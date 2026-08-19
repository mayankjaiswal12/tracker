# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Budgets: what a Money Budget's current envelope holds, measured from the ledger.

A budget document stores an amount, a period and a window. It stores **no spending** — the
same rule `Money Goal` follows and for the same reason (§68): a stored counter drifts the
first time a transaction is cancelled and nothing in the data says that it has.

**A budget is not a Spending Limit goal.** A goal is one window with a deadline: 5,000 on
restaurants between April and June, and when it is over it is over. A budget is an envelope
that *repeats* — 5,000 on restaurants every month, for as long as the budget is active —
and it carries two things a goal deliberately has not got: a `period` that refills it, and a
`rollover` that decides whether what was left over last month is still there this month.
That boundary is why `Money Goal` has no period field, and it is the whole reason this
module exists rather than another row in `GOAL_TYPES`.

`PERIODS` is the single table describing each kind of period — where it starts, where it
ends, and how to step to the next one. Everything else in the module is period-agnostic, so
adding a fortnightly budget would be a row in that table.
"""

from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import (
	add_to_date,
	flt,
	fmt_money,
	get_first_day,
	get_first_day_of_week,
	get_last_day,
	get_last_day_of_week,
	get_quarter_ending,
	get_quarter_start,
	get_year_ending,
	get_year_start,
	getdate,
	today,
)
from frappe.utils.dateutils import get_period

from moneytracker.money_tracker.services import categories

# Derived outcomes. Never stored — recomputed from the ledger on every read, exactly as a
# goal's are, and worded differently on purpose: a goal is something you are trying to
# reach, an envelope is something you are trying not to empty.
NOT_STARTED = "Not Started"
NO_SPEND = "No Spend"
WITHIN_BUDGET = "Within Budget"
AT_RISK = "At Risk"
NEARING_LIMIT = "Nearing Limit"
OVER_BUDGET = "Over Budget"

# What "this budget is fine" means. Defined here so the card, the chart and the progress bar
# cannot disagree about the word. `At Risk` is spending faster than the period is passing and
# `Nearing Limit` is close to the edge — both are warnings, so neither counts as on track.
HEALTHY_OUTCOMES = (NO_SPEND, WITHIN_BUDGET)

# The outcomes worth telling somebody about. `At Risk` is deliberately not one of them: it
# fires on the pace of an ordinary month and would mail the user most mornings.
ALERT_OUTCOMES = (NEARING_LIMIT, OVER_BUDGET)

# Share of the envelope at which a budget starts warning, when the document does not say.
DEFAULT_ALERT_THRESHOLD = 80.0

# How many finished periods `measure()` hands back. The rollover is still worked out over
# every period since the budget started; this only bounds what is *returned*, so a four-year
# weekly budget does not answer a progress bar with two hundred rows.
HISTORY_LIMIT = 12


@dataclass(frozen=True)
class BudgetPeriod:
	"""One kind of repeating period.

	`first_day` / `last_day`  the calendar period containing a given date. Calendar-aligned
	                          rather than anchored to the budget's start date, so a budget's
	                          month is the same month the dashboard's "Expenses This Month"
	                          card counts and the same month the trend chart plots.
	`step`                    `add_to_date` keywords that move one whole period forward.
	`interval`                the name `frappe.utils.dateutils.get_period` labels it with,
	                          so a budget period reads as "Aug 2026" exactly like a chart's.
	"""

	first_day: Callable
	last_day: Callable
	step: dict
	interval: str


PERIODS = {
	"Weekly": BudgetPeriod(get_first_day_of_week, get_last_day_of_week, {"days": 7}, "Weekly"),
	"Monthly": BudgetPeriod(get_first_day, get_last_day, {"months": 1}, "Monthly"),
	"Quarterly": BudgetPeriod(get_quarter_start, get_quarter_ending, {"months": 3}, "Quarterly"),
	"Yearly": BudgetPeriod(get_year_start, get_year_ending, {"years": 1}, "Yearly"),
}

# The Select on the DocType must list exactly these, in this order.
BUDGET_PERIOD_OPTIONS = tuple(PERIODS)


def get_budget_period(period):
	spec = PERIODS.get(period)
	if not spec:
		frappe.throw(
			_("Unknown Budget Period {0}. Supported periods: {1}.").format(
				period, ", ".join(BUDGET_PERIOD_OPTIONS)
			)
		)
	return spec


# --- the calendar ----------------------------------------------------------------------


def period_bounds(period, date):
	"""The calendar period of that kind containing `date`, as `(first_day, last_day)`."""
	spec = get_budget_period(period)
	date = getdate(date)
	return getdate(spec.first_day(date)), getdate(spec.last_day(date))


def iter_periods(period, start_date, measured_to, end_date=None):
	"""Every period from the one holding `start_date` up to the one holding `measured_to`.

	Each row carries the calendar period *and* the window actually measured inside it. They
	differ at both ends: the first period is clipped at the budget's start date, because
	money spent before a budget existed was not spent against it, and the last is clipped at
	`measured_to`, because a period in progress has only been half lived.

	The envelope itself is **not** prorated for a clipped period. A budget started on the
	20th gets its whole monthly amount for that month, which is what the user typed; scaling
	it down to a third would quietly answer a different question from the one they asked.
	"""
	spec = get_budget_period(period)
	start_date, measured_to = getdate(start_date), getdate(measured_to)
	end_date = getdate(end_date) if end_date else None

	rows = []
	cursor = getdate(spec.first_day(start_date))
	while cursor <= measured_to:
		period_start = cursor
		period_end = getdate(spec.last_day(cursor))

		from_date = max(period_start, start_date)
		to_date = min(period_end, measured_to)
		if end_date:
			to_date = min(to_date, end_date)

		rows.append(
			frappe._dict(
				{
					"index": len(rows),
					"period_start": period_start,
					"period_end": period_end,
					"label": get_period(period_end, spec.interval),
					"from_date": from_date,
					"to_date": to_date,
				}
			)
		)
		cursor = getdate(add_to_date(period_start, **spec.step))

	return rows


# --- measurement -----------------------------------------------------------------------


def measure(budget, as_of=None):
	"""Every derived figure for one budget's current period, as a `frappe._dict`.

	`as_of` moves the whole measurement in time, which is what makes it testable and what
	lets a report show what an envelope looked like three months ago.
	"""
	budget = budget if hasattr(budget, "doctype") else frappe.get_doc("Money Budget", budget)
	get_budget_period(budget.period)

	as_of = getdate(as_of or today())
	start = getdate(budget.start_date)
	end = getdate(budget.end_date) if budget.end_date else None
	amount = flt(budget.budget_amount)
	threshold = flt(budget.alert_threshold) or DEFAULT_ALERT_THRESHOLD

	# A finished budget keeps its closing period. Without the clamp, a budget that ended in
	# June would open a fresh empty envelope every month afterwards and read as spotless.
	measured_to = min(as_of, end) if end else as_of

	result = frappe._dict(
		{
			"budget": budget.name,
			"budget_name": budget.budget_name,
			"tracker": budget.tracker,
			"status": budget.status,
			"period": budget.period,
			"category": budget.category,
			"currency": budget.currency,
			"color": budget.color,
			"rollover": bool(budget.rollover),
			"alert_threshold": threshold,
			"budget_amount": amount,
			"start_date": start,
			"end_date": end,
			"as_of": as_of,
			"ended": bool(end and as_of > end),
		}
	)

	if measured_to < start:
		bounds = period_bounds(budget.period, start)
		return result.update(
			{
				"period_start": bounds[0],
				"period_end": bounds[1],
				"period_label": get_period(bounds[1], get_budget_period(budget.period).interval),
				"carried_in": 0.0,
				"available": amount,
				"spent": 0.0,
				"remaining": amount,
				"used_percent": 0.0,
				"expected_percent": 0.0,
				"days_total": _day_span(bounds[0], bounds[1]),
				"days_elapsed": 0,
				"days_left": _day_span(start, bounds[1]),
				"available_per_day": None,
				"outcome": NOT_STARTED,
				"history": [],
			}
		)

	periods = iter_periods(budget.period, start, measured_to, end)
	spend = categories.get_net_spend_by_date(budget.tracker, budget.category, start, measured_to)
	for row in periods:
		row.spent = flt(sum(amount for day, amount in spend.items() if row.from_date <= day <= row.to_date))
		row.budget_amount = amount

	# Rollover carries the *deficit* as well as the surplus. An envelope that quietly forgets
	# last month's overspend is not an envelope — it is two separate budgets wearing one name.
	current = periods[-1]
	carried_in = (
		flt(sum(amount - row.spent for row in periods[:-1])) if budget.rollover and len(periods) > 1 else 0.0
	)

	available = amount + carried_in
	spent = current.spent
	remaining = available - spent

	# A period whose envelope has already been eaten by carried-over debt has nothing left to
	# take a percentage of, so it reads as fully used rather than as a division by zero.
	used_percent = (spent / available * 100) if available > 0 else (100.0 if remaining < 0 else 0.0)

	days_total = _day_span(current.period_start, current.period_end)
	days_elapsed = _day_span(current.from_date, current.to_date)
	# Inclusive, as a goal's is: on the last day of the period you still have that day to
	# spend in, and `available_per_day` divides by it.
	days_left = _day_span(measured_to, current.period_end)
	expected_percent = min(days_elapsed / days_total * 100, 100.0) if days_total else None

	result.update(
		{
			"period_start": current.period_start,
			"period_end": current.period_end,
			"period_label": current.label,
			"window": {"from_date": current.from_date, "to_date": current.to_date},
			"carried_in": flt(carried_in),
			"available": flt(available),
			"spent": flt(spent),
			"remaining": flt(remaining),
			"used_percent": flt(used_percent, 2),
			"expected_percent": flt(expected_percent, 2) if expected_percent is not None else None,
			"days_total": days_total,
			"days_elapsed": days_elapsed,
			"days_left": days_left,
			"available_per_day": _available_per_day(remaining, days_left),
			"history": [_history_row(row, amount) for row in periods[:-1][-HISTORY_LIMIT:]],
		}
	)
	result.outcome = _outcome(result)
	return result


def _history_row(row, amount):
	return {
		"period_start": row.period_start,
		"period_end": row.period_end,
		"label": row.label,
		"budget_amount": flt(amount),
		"spent": flt(row.spent),
		"remaining": flt(amount - row.spent),
	}


def _day_span(from_date, to_date):
	"""Inclusive day count. Never negative."""
	return max((getdate(to_date) - getdate(from_date)).days + 1, 0)


def _available_per_day(remaining, days_left):
	"""What is left to spend per remaining day, or None once the period is over or blown."""
	if not days_left or remaining <= 0:
		return None
	return flt(remaining / days_left, 2)


def _outcome(row):
	"""The single word for how an envelope is doing.

	Ordered by how much it matters. Over Budget wins outright — the money is already spent,
	and nothing about the pace changes that. Then the threshold the user set, then the pace,
	which is the only one of the three that can un-say itself as the period runs on.
	"""
	if row.remaining < 0:
		return OVER_BUDGET
	if not row.spent:
		return NO_SPEND
	if row.used_percent >= row.alert_threshold:
		return NEARING_LIMIT
	if row.expected_percent is not None and row.used_percent > row.expected_percent:
		return AT_RISK
	return WITHIN_BUDGET


def measure_budgets(tracker, as_of=None, status="Active", period=None):
	"""Measure every budget on a tracker, largest envelope first."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status
	if period:
		filters["period"] = period

	rows = frappe.get_all(
		"Money Budget",
		filters=filters,
		fields=["name"],
		order_by="budget_amount desc, creation asc",
	)
	return [measure(row.name, as_of) for row in rows]


# --- alerts ----------------------------------------------------------------------------


def send_budget_alerts(as_of=None):
	"""Daily: notify each budget's owner when its envelope crosses a line. Returns the count.

	The alert is stamped with the period *and* the outcome that caused it, so a budget that
	warns at 80% in August and then goes over in the same August raises two notifications and
	not two hundred. That stamp is the only mutable state on the document, and it is
	bookkeeping about a message that was sent rather than anything about the money.
	"""
	rows = frappe.get_all(
		"Money Budget",
		filters={"status": "Active", "notify_on_alert": 1},
		fields=["name", "tracker", "last_alert"],
	)

	sent = 0
	for row in rows:
		measured = measure(row.name, as_of)
		if measured.outcome not in ALERT_OUTCOMES:
			continue

		stamp = f"{measured.period_end}|{measured.outcome}"
		if row.last_alert == stamp:
			continue

		if _notify(measured, row.tracker):
			sent += 1
		frappe.db.set_value("Money Budget", row.name, "last_alert", stamp, update_modified=False)

	return sent


def _notify(measured, tracker):
	"""One Notification Log for the tracker's owner. False when there is nobody to tell."""
	owner = frappe.db.get_value("Tracker", tracker, "owner_user")
	if not owner:
		return False

	currency = measured.currency or frappe.db.get_value("Tracker", tracker, "base_currency")
	if measured.outcome == OVER_BUDGET:
		subject = _("{0} is over budget: {1} of {2} spent in {3}").format(
			measured.budget_name,
			fmt_money(measured.spent, currency=currency),
			fmt_money(measured.available, currency=currency),
			measured.period_label,
		)
	else:
		subject = _("{0} is at {1}% of its budget for {2}").format(
			measured.budget_name, flt(measured.used_percent, 1), measured.period_label
		)

	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": owner,
			"type": "Alert",
			"document_type": "Money Budget",
			"document_name": measured.budget,
			"subject": subject,
		}
	).insert(ignore_permissions=True)
	return True
