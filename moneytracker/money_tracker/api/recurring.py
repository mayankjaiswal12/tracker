# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Recurring API: a measured plan for a client, a Desk form, or a dashboard widget.

Nothing here does arithmetic — `services/recurring.py` owns all of it. This module resolves
who is asking, which tracker they may see, and how the answer is formatted.
"""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.api.dashboard import (
	CARD_NO_DATA,
	parse_widget_filters,
	resolve_widget_tracker,
)
from moneytracker.money_tracker.services import recurring
from moneytracker.money_tracker.services import settings as settings_service


@frappe.whitelist()
def get_recurring_transactions(tracker=None, as_of=None, status="Active"):
	"""Every plan on a tracker, measured."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	return {
		"tracker": tracker,
		"as_of": as_of,
		"status": status,
		"currency": settings_service.get_base_currency(),
		"plans": [_presented(row) for row in recurring.measure_plans(tracker, as_of, status=status)],
	}


@frappe.whitelist()
def get_recurring_progress(recurring_transaction, as_of=None):
	"""One plan's schedule and history — the single shape the form's block draws from."""
	frappe.has_permission("Money Recurring Transaction", doc=recurring_transaction, throw=True)
	return _presented(recurring.measure(recurring_transaction, as_of))


@frappe.whitelist()
def get_forecast(tracker=None, months=6, status="Active", after=None):
	"""Scheduled income and expense by month, for the months still to come."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)
	return recurring.get_forecast(tracker, after=after, months=months, status=status)


def _presented(row):
	"""A measured plan plus the strings to print — one shape for every caller.

	Formatted here rather than in the browser for the same reason the Number Cards are
	(§33): a client formatting a number falls back to *System Settings'* currency, which is
	not necessarily the tracker's.
	"""
	currency = row.currency or settings_service.get_base_currency()
	row.formatted = {
		"amount": fmt_money(flt(row.amount), currency=currency),
		"monthly_equivalent": fmt_money(flt(row.monthly_equivalent), currency=currency),
		"posted_total": fmt_money(flt(row.posted_total), currency=currency),
		"due_amount": fmt_money(flt(row.due_amount), currency=currency),
	}
	row.history = [
		{**occurrence, "formatted_amount": fmt_money(flt(occurrence["amount"]), currency=currency)}
		for occurrence in row.get("history") or []
	]
	return row


# ---------------------------------------------------------------------------
# Dashboard widgets. Same contract as the cards in api/dashboard.py: a Custom Number Card
# prints a returned string verbatim, so the wording happens here.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_fixed_costs(filters=None):
	"""What the active expense plans cost in an average month — "₹ 36,499.00".

	A money total rather than a count, which is the opposite choice from `Budgets on Track`
	and for the opposite reason. Envelopes on different clocks cannot be added up at all; a
	plan's monthly equivalent is a real figure whatever clock it runs on, and "what do I owe
	every month before I have decided anything?" is the question fixed costs exist to answer.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	costs = recurring.get_fixed_costs(tracker, filters.get("as_of"))
	if not costs.plans:
		return CARD_NO_DATA

	currency = (
		frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()
	)
	return fmt_money(costs.monthly, currency=currency)


@frappe.whitelist()
def card_plans_running(filters=None):
	"""How many plans are running as intended — "4 of 5".

	The count `Fixed Costs` cannot give: a plan whose occurrence date has passed with nothing
	posted is `Due`, which means the scheduler has not run, and no money figure would show it.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	measured = recurring.measure_plans(tracker, filters.get("as_of"))
	if not measured:
		return CARD_NO_DATA

	healthy = sum(1 for row in measured if row.outcome in recurring.HEALTHY_OUTCOMES)
	return _("{0} of {1}").format(healthy, len(measured))
