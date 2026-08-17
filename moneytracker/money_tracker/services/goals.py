# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Goals: what a Money Goal is worth right now, measured from the ledger.

A goal document stores a target and a window. It stores **no progress**. Every figure here
is derived on read, the same rule GL Entry imposes on `Money Account.current_balance`
(§68) and for the same reason: a stored counter drifts the first time a transaction is
cancelled, and nothing in the data says that it has.

`GOAL_TYPES` is the single table describing every kind of goal — which way it runs, what
unit it is in, what it needs filled in, and the function that measures it. The controller
validates from that table and `measure()` dispatches through it, so adding a goal type
means adding a row and one small function. Neither the controller nor the widgets change.

The measures are functions in this one module rather than a package of one module per type,
as `posting/strategies/` is. A posting strategy carries real accounting rules and earns its
own file; a goal measure asks an existing service a single question, and all six fit in the
space one strategy takes.
"""

from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from moneytracker.money_tracker.services import balances, categories, trends

# Which way a goal runs. An Accumulate goal wants its figure to reach the target; a Limit
# goal wants it to stay underneath, so 100% is failure rather than success and every
# comparison flips.
ACCUMULATE = "Accumulate"
LIMIT = "Limit"

CURRENCY = "Currency"
PERCENT = "Percent"

# How a Savings goal reads the account behind it.
BASIS_CONTRIBUTIONS = "Contributions Since Start"
BASIS_BALANCE = "Account Balance"
MEASURE_BASES = (BASIS_CONTRIBUTIONS, BASIS_BALANCE)

# Derived outcomes. Never stored — recomputed from the ledger on every read.
NOT_STARTED = "Not Started"
IN_PROGRESS = "In Progress"
ON_TRACK = "On Track"
BEHIND = "Behind"
AT_RISK = "At Risk"
ACHIEVED = "Achieved"
MISSED = "Missed"
BREACHED = "Breached"
NO_DATA = "No Data"

# The outcomes that mean "this goal is currently going well". Used by the dashboard card,
# and defined here so the card and the progress bar cannot disagree about the word.
HEALTHY_OUTCOMES = (ACHIEVED, ON_TRACK, IN_PROGRESS)


@dataclass(frozen=True)
class GoalType:
	"""Everything that differs between one kind of goal and another.

	`account`         the root type the target Money Account must have, or None if the goal
	                  is not about one account. Asset for saving into, Liability for paying off.
	`category_type`   the Category type this goal measures over, if any. When set, `category`
	                  *is* the measurement basis and an empty one means the whole tracker.
	                  When None, `category` is only a label saying what the goal is for —
	                  a Transfer into a savings account carries no category by construction
	                  (`Transaction.validate_accounts` clears it), so it cannot be measured by one.
	`needs_deadline`  whether target_date is required. A window measure has no meaning
	                  without one; a savings pot is allowed to have no deadline at all.
	`cumulative`      whether the figure builds up over the window. A cumulative goal can be
	                  achieved early and can be paced against elapsed time. A rate can be
	                  neither: being above target halfway through says nothing final.
	`basis_choice`    whether `measure_basis` applies — only a savings pot can sensibly be
	                  read either as its whole balance or as what has gone in since the start.
	`opening`         whether `opening_amount` applies: money already put aside, or the debt
	                  the goal started from.

	The controller clears every field a type does not use, exactly as
	`Transaction.validate_accounts` clears a category off a transfer, so a retyped goal cannot
	carry a stale value into the measurement.
	"""

	measure: Callable
	direction: str
	unit: str
	account: str | None = None
	category_type: str | None = None
	needs_deadline: bool = False
	cumulative: bool = True
	basis_choice: bool = False
	opening: bool = False

	@property
	def prorated(self):
		"""Whether progress may be compared against the share of the window that has passed."""
		return self.cumulative


# --- measures --------------------------------------------------------------------------
# Each takes the goal, the window as `(from_date, to_date)`, and a per-call cache, and
# returns the figure in the goal's unit. None means "undefined" — a rate with no income —
# and is reported as No Data rather than as zero.


def _savings(goal, window, cache):
	"""Money accumulating in one account."""
	if goal.measure_basis == BASIS_BALANCE:
		return balances.get_account_balance(goal.target_account, window[1])

	# Contributions since the goal started: the account's own movement inside the window,
	# plus whatever the user declares was already put aside. The baseline is the day *before*
	# the start date, so a contribution made on day one counts towards the goal.
	before = balances.get_account_balance(goal.target_account, add_days(window[0], -1))
	return flt(goal.opening_amount) + balances.get_account_balance(goal.target_account, window[1]) - before


def _debt_payoff(goal, window, cache):
	"""How much of the opening debt has been cleared.

	`get_account_balance` reports a liability in its natural direction, so both figures are
	positive amounts owed and the subtraction is progress. It can come out negative — the
	card was used again rather than paid down — and that is reported rather than hidden.
	"""
	opening = flt(goal.opening_amount) or balances.get_account_balance(
		goal.target_account, add_days(window[0], -1)
	)
	return opening - balances.get_account_balance(goal.target_account, window[1])


def _spending_limit(goal, window, cache):
	"""Net spend over a category subtree, or the whole tracker's spend when none is named."""
	return _side_total(goal, "Expense", window, cache)


def _income_target(goal, window, cache):
	return _side_total(goal, "Income", window, cache)


def _savings_rate(goal, window, cache):
	"""The share of the window's income that was not spent. Undefined without income."""
	income, expense = _totals(goal.tracker, window, cache)
	if not income:
		return None
	return (income - expense) / income * 100


def _net_worth(goal, window, cache):
	"""Assets minus liabilities as at the end of the window (§31)."""
	return balances.get_net_worth(goal.tracker, window[1])["net_worth"]


# Ordered as the Select reads to a user: the four things you build up, then the two you
# keep down. `test_the_select_lists_exactly_the_implemented_types` pins the two together.
GOAL_TYPES = {
	"Savings": GoalType(
		_savings, ACCUMULATE, CURRENCY, account="Asset", basis_choice=True, opening=True
	),
	"Net Worth Target": GoalType(_net_worth, ACCUMULATE, CURRENCY),
	"Income Target": GoalType(
		_income_target, ACCUMULATE, CURRENCY, category_type="Income", needs_deadline=True
	),
	"Savings Rate Target": GoalType(
		_savings_rate, ACCUMULATE, PERCENT, needs_deadline=True, cumulative=False
	),
	"Spending Limit": GoalType(
		_spending_limit, LIMIT, CURRENCY, category_type="Expense", needs_deadline=True
	),
	"Debt Payoff": GoalType(
		_debt_payoff, ACCUMULATE, CURRENCY, account="Liability", opening=True
	),
}

# The Select on the DocType must list exactly these, in this order.
GOAL_TYPE_OPTIONS = tuple(GOAL_TYPES)


def get_goal_type(goal_type):
	spec = GOAL_TYPES.get(goal_type)
	if not spec:
		frappe.throw(
			_("Unknown Goal Type {0}. Supported types: {1}.").format(
				goal_type, ", ".join(GOAL_TYPE_OPTIONS)
			)
		)
	return spec


# --- shared queries --------------------------------------------------------------------
# Measuring a list of goals runs the same two aggregates over and over — a tracker's
# spending limit, its income target and its savings rate all want the same window. The
# cache is a plain dict handed down from measure_goals(); one goal on its own gets a fresh
# empty one and pays for a single query, which is what §74 asks for.


def _totals(tracker, window, cache):
	key = ("totals", tracker, *window)
	if key not in cache:
		cache[key] = trends.get_totals(tracker, *window)
	return cache[key]


def _category_totals(tracker, category_type, window, cache):
	key = ("categories", tracker, category_type, *window)
	if key not in cache:
		cache[key] = categories.get_category_totals(tracker, category_type, *window)
	return cache[key]


def _side_total(goal, category_type, window, cache):
	"""One side of the tracker's books over the window, narrowed to a category if given.

	The category figure is the roll-up including descendants, so a limit set on a group
	covers everything filed under it, and refunds are already netted off (§62).
	"""
	if not goal.category:
		income, expense = _totals(goal.tracker, window, cache)
		return income if category_type == "Income" else expense

	rows = _category_totals(goal.tracker, category_type, window, cache)
	row = next((r for r in rows if r["category"] == goal.category), None)
	return flt(row["total"]) if row else 0.0


# --- measurement -----------------------------------------------------------------------


def measure(goal, as_of=None, cache=None):
	"""Every derived figure for one goal, as a `frappe._dict`.

	`as_of` moves the whole measurement in time, which is what makes this testable and what
	lets a report show where a goal stood last quarter.
	"""
	goal = goal if hasattr(goal, "doctype") else frappe.get_doc("Money Goal", goal)
	spec = get_goal_type(goal.goal_type)
	cache = cache if cache is not None else {}

	as_of = getdate(as_of or today())
	start = getdate(goal.start_date)
	deadline = getdate(goal.target_date) if goal.target_date else None

	# A finished goal keeps its closing figure. Without the clamp, measuring a goal a year
	# after its deadline would keep accumulating and turn a missed goal into an achieved one.
	window_end = min(as_of, deadline) if deadline else as_of

	target = flt(goal.target_percent) if spec.unit == PERCENT else flt(goal.target_amount)
	result = frappe._dict(
		{
			"goal": goal.name,
			"goal_name": goal.goal_name,
			"goal_type": goal.goal_type,
			"tracker": goal.tracker,
			"status": goal.status,
			"direction": spec.direction,
			"unit": spec.unit,
			"currency": goal.currency,
			"category": goal.category,
			"target_account": goal.target_account,
			"color": goal.color,
			"start_date": start,
			"target_date": deadline,
			"as_of": as_of,
			"target": target,
			"window": {"from_date": start, "to_date": window_end},
		}
	)

	if window_end < start:
		return result.update(
			{
				"current": 0.0,
				"remaining": target,
				"progress_percent": 0.0,
				"outcome": NOT_STARTED,
				"days_total": _day_span(start, deadline),
				"days_elapsed": 0,
				"days_left": _day_span(as_of, deadline),
				"expected_percent": 0.0 if spec.prorated and deadline else None,
				"required_per_period": None,
			}
		)

	current = spec.measure(goal, (start, window_end), cache)
	if current is None:
		return result.update(
			{
				"current": None,
				"remaining": None,
				"progress_percent": None,
				"outcome": NO_DATA,
				"days_total": _day_span(start, deadline),
				"days_elapsed": _day_span(start, window_end),
				"days_left": _day_span(as_of, deadline),
				"expected_percent": None,
				"required_per_period": None,
			}
		)

	current = flt(current)
	days_total = _day_span(start, deadline)
	days_elapsed = _day_span(start, window_end)
	days_left = _day_span(as_of, deadline)

	# Reported truthfully, negatives included: refunds can outweigh a month's spending, and a
	# debt can grow instead of shrink. The progress bar clamps its own width; the figure does
	# not lie about which way things went.
	progress_percent = (current / target * 100) if target else 0.0
	expected_percent = (
		min(days_elapsed / days_total * 100, 100.0) if spec.prorated and days_total else None
	)

	return result.update(
		{
			"current": current,
			"remaining": target - current,
			"progress_percent": flt(progress_percent, 2),
			"outcome": _outcome(spec, current, target, progress_percent, expected_percent, as_of, deadline),
			"days_total": days_total,
			"days_elapsed": days_elapsed,
			"days_left": days_left,
			"expected_percent": flt(expected_percent, 2) if expected_percent is not None else None,
			"required_per_period": _required_per_period(spec, target - current, days_left),
		}
	)


def _day_span(from_date, to_date):
	"""Inclusive day count, or None without an end date. Never negative."""
	if not to_date:
		return None
	return max((getdate(to_date) - getdate(from_date)).days + 1, 0)


def _required_per_period(spec, remaining, days_left):
	"""What must still be set aside each remaining day to land the goal on time.

	Only meaningful for a cumulative Accumulate goal with a deadline: a limit is not
	something you have to achieve daily, and a rate does not accumulate.
	"""
	if spec.direction != ACCUMULATE or not spec.cumulative:
		return None
	if not days_left or remaining <= 0:
		return None
	return flt(remaining / days_left, 2)


def _outcome(spec, current, target, progress_percent, expected_percent, as_of, deadline):
	"""The single word for how a goal is doing."""
	overdue = bool(deadline and as_of > deadline)

	if spec.direction == LIMIT:
		if current > target:
			# Once breached, always breached for this window: the money is spent.
			return BREACHED
		if overdue:
			return ACHIEVED
		if expected_percent is None or progress_percent <= expected_percent:
			return ON_TRACK
		return AT_RISK

	if current >= target:
		# A rate can be above target halfway through and below it by the end, so it is only
		# achieved once the window has actually closed.
		if spec.cumulative or overdue:
			return ACHIEVED
		return ON_TRACK
	if overdue:
		return MISSED
	if expected_percent is None:
		# No deadline: there is no pace to be behind, only progress.
		return IN_PROGRESS
	return ON_TRACK if progress_percent >= expected_percent else BEHIND


def measure_goals(tracker, as_of=None, status="Active", goal_type=None):
	"""Measure every goal on a tracker, oldest deadline first, sharing one query cache."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status
	if goal_type:
		filters["goal_type"] = goal_type

	rows = frappe.get_all(
		"Money Goal", filters=filters, fields=["name", "target_date", "creation"], order_by="creation asc"
	)
	# Soonest deadline first, undated goals last — a deadline is what makes a goal urgent.
	# Ordered in Python rather than in SQL because an empty Date is NULL, which MariaDB sorts
	# *first* ascending; the fix is a NULLS LAST clause the query builder does not accept.
	rows.sort(key=lambda row: (row.target_date is None, row.target_date or row.creation))

	cache = {}
	return [measure(row.name, as_of, cache) for row in rows]
