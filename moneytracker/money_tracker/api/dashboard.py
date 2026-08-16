# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard and balance API (spec §5, §70)."""

import frappe
from frappe.utils import add_to_date, flt, fmt_money, get_first_day, get_last_day, getdate, today

from moneytracker.money_tracker.services import (
	balances,
	categories,
	coa,
	settings as settings_service,
	trends,
)


@frappe.whitelist()
def get_account_balance(money_account, as_of=None):
	frappe.has_permission("Money Account", doc=money_account, throw=True)
	return balances.get_account_balance(money_account, as_of)


@frappe.whitelist()
def get_balances(tracker=None, as_of=None):
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)
	return balances.get_balances_for_tracker(tracker, as_of)


@frappe.whitelist()
def get_net_worth(tracker=None, as_of=None):
	if tracker:
		frappe.has_permission("Tracker", doc=tracker, throw=True)
	return balances.get_net_worth(tracker, as_of)


@frappe.whitelist()
def recompute_balances(tracker=None):
	"""Reconciliation tool for the cached balances (spec §68)."""
	if tracker:
		frappe.has_permission("Tracker", doc=tracker, ptype="write", throw=True)
	return {"updated": balances.recompute_balances(tracker=tracker)}


@frappe.whitelist()
def get_spending_by_category(tracker=None, category_type="Expense", from_date=None, to_date=None):
	"""The category tree with roll-up totals — the heading total ERPNext's reports don't give.

	Every leaf category has its own flat ledger account, so a P&L lists Groceries and
	Restaurants side by side with no "Food" line. This adds it up over the tree instead.
	"""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	if not (from_date and to_date):
		reference = to_date or from_date or today()
		from_date, to_date = get_first_day(reference), get_last_day(reference)

	return {
		"tracker": tracker,
		"category_type": category_type,
		"period": {"from_date": from_date, "to_date": to_date},
		"currency": settings_service.get_base_currency(),
		"rows": categories.get_category_totals(tracker, category_type, from_date, to_date),
	}


@frappe.whitelist()
def get_trend(tracker=None, from_date=None, to_date=None, interval="Monthly"):
	"""Income and net expense per period — the same series the dashboard charts draw.

	Whitelisted separately from the Dashboard Chart Source so a client that is not Desk can
	ask for the numbers without going through the chart widget's argument shape.
	"""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	to_date = to_date or today()
	from_date = from_date or add_to_date(to_date, years=-1)

	return {
		"tracker": tracker,
		"interval": interval,
		"period": {"from_date": getdate(from_date), "to_date": getdate(to_date)},
		"currency": settings_service.get_base_currency(),
		"rows": trends.get_period_series(tracker, from_date, to_date, interval),
	}


def _total_balance(account_rows):
	"""What the tracker's asset accounts hold, from rows of get_balances_for_tracker.

	Liabilities are excluded rather than added in: every account is reported in its own
	natural direction, so a credit card with 1,500 owed on it comes back as +1,500, and
	summing that would add a debt to the money you have. Debt belongs to net worth, which
	subtracts it.
	"""
	return sum(row["balance"] for row in account_rows if not coa.is_liability(row["account_type"]))


def _period_totals(tracker, from_date, to_date):
	"""Income and net expense for a period — the cards' figures, totalled over the series.

	Deliberately not its own query. The §62 rule that a Refund *reduces* spend rather than
	adding income was written out here as well as in `trends.get_period_series`, and a rule
	stated in two places is a rule that eventually disagrees with itself. The chart series is
	the one implementation; a card is that series summed.
	"""
	rows = trends.get_period_series(tracker, from_date, to_date)
	return (
		flt(sum(row["income"] for row in rows)),
		flt(sum(row["expense"] for row in rows)),
	)


@frappe.whitelist()
def get_dashboard(tracker=None, as_of=None):
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	as_of = as_of or today()
	month_start = get_first_day(as_of)
	month_end = get_last_day(as_of)

	income, expense = _period_totals(tracker, month_start, month_end)
	net_worth = balances.get_net_worth(tracker, as_of)
	savings = income - expense
	account_rows = balances.get_balances_for_tracker(tracker, as_of)

	return {
		"tracker": tracker,
		"tracker_name": frappe.db.get_value("Tracker", tracker, "tracker_name"),
		"currency": settings_service.get_base_currency(),
		"as_of": as_of,
		"period": {"from_date": month_start, "to_date": month_end},
		"total_balance": _total_balance(account_rows),
		"assets": net_worth["assets"],
		"liabilities": net_worth["liabilities"],
		"net_worth": net_worth["net_worth"],
		"monthly_income": income,
		"monthly_expense": expense,
		"monthly_savings": savings,
		"savings_rate": (savings / income * 100) if income else 0.0,
		"accounts": account_rows,
		"recent_transactions": frappe.get_all(
			"Transaction",
			filters={"tracker": tracker, "docstatus": 1},
			fields=[
				"name",
				"date",
				"transaction_type",
				"amount",
				"currency",
				"account",
				"account.account_name as account_name",
				"category",
				"category.category_name as category_name",
				"merchant",
			],
			# Table-qualified: the dotted fields above make this a JOIN, and both `date` and
			# `creation` exist on the joined tables too.
			order_by="`tabTransaction`.`date` desc, `tabTransaction`.`creation` desc",
			limit_page_length=10,
		),
	}


# ---------------------------------------------------------------------------
# Number Card sources (spec §5)
#
# The cards are `type: "Custom"` rather than Frappe's built-in "Document Type"
# aggregation, for three reasons that are not stylistic:
#   * balances come from GL Entry, and no Sum over Transaction reproduces them;
#   * net expense has to subtract Refunds (§62), which one filter set cannot express;
#   * every figure is scoped to a single Tracker, where a built-in card would sum every
#     tracker the user is allowed to read.
#
# A Custom card calls its method with `{"filters": <parsed filters_json>}` and, when the
# return value is a string, prints it verbatim. So the figures are formatted here rather
# than in the browser: the card widget's own currency formatting falls back to System
# Settings' currency, which is not necessarily the tracker's.
# ---------------------------------------------------------------------------

# Shown when the user has no tracker yet, or when a rate has no denominator. An empty
# string would render as a blank card that looks broken rather than empty.
CARD_NO_DATA = "—"


def parse_widget_filters(filters=None):
	"""Normalise a dashboard widget's filters to a dict.

	They arrive as whatever `filters_json` parsed to. The shipped cards and charts carry an
	object, but Desk's filter editor writes `[[doctype, fieldname, operator, value], ...]`
	if someone edits one in the UI, so accept that too.
	"""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	if isinstance(filters, dict):
		return filters
	if isinstance(filters, list):
		return {f[1]: f[3] for f in filters if len(f) == 4 and f[2] == "="}
	return {}


def resolve_widget_tracker(filters):
	"""The tracker a card or chart should paint, or None if the user has none.

	A widget is scoped to exactly one tracker: `filters.tracker` when the widget names one —
	permission-checked, since a shared Company means the Tracker *is* the isolation — and
	otherwise the session user's own.
	"""
	tracker = filters.get("tracker")
	if tracker:
		frappe.has_permission("Tracker", doc=tracker, throw=True)
		return tracker
	return settings_service.find_tracker()


def _card_context(filters=None):
	"""Return `(tracker, as_of)` for a card, with tracker None if the user has none."""
	filters = parse_widget_filters(filters)
	return resolve_widget_tracker(filters), filters.get("as_of") or today()


def _card_currency(tracker):
	return frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()


def _card_money(value, tracker):
	return fmt_money(flt(value), currency=_card_currency(tracker))


@frappe.whitelist()
def card_total_balance(filters=None):
	"""What the tracker's asset accounts hold right now."""
	tracker, as_of = _card_context(filters)
	if not tracker:
		return CARD_NO_DATA
	return _card_money(_total_balance(balances.get_balances_for_tracker(tracker, as_of)), tracker)


@frappe.whitelist()
def card_net_worth(filters=None):
	"""Assets minus liabilities, over the accounts flagged include_in_net_worth (§31)."""
	tracker, as_of = _card_context(filters)
	if not tracker:
		return CARD_NO_DATA
	return _card_money(balances.get_net_worth(tracker, as_of)["net_worth"], tracker)


@frappe.whitelist()
def card_monthly_income(filters=None):
	tracker, as_of = _card_context(filters)
	if not tracker:
		return CARD_NO_DATA
	income, _expense = _period_totals(tracker, get_first_day(as_of), get_last_day(as_of))
	return _card_money(income, tracker)


@frappe.whitelist()
def card_monthly_expense(filters=None):
	"""Spending this month, net of refunds — a refund reduces spend, it is not income."""
	tracker, as_of = _card_context(filters)
	if not tracker:
		return CARD_NO_DATA
	_income, expense = _period_totals(tracker, get_first_day(as_of), get_last_day(as_of))
	return _card_money(expense, tracker)


@frappe.whitelist()
def card_savings_rate(filters=None):
	"""Share of this month's income that was not spent. Undefined without income."""
	tracker, as_of = _card_context(filters)
	if not tracker:
		return CARD_NO_DATA
	income, expense = _period_totals(tracker, get_first_day(as_of), get_last_day(as_of))
	if not income:
		return CARD_NO_DATA
	return f"{flt((income - expense) / income * 100, 1)}%"
