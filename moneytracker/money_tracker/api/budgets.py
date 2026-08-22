# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Budgets API: a measured envelope for a client, a Desk form, or a dashboard widget.

Nothing here does arithmetic — `services/budgets.py` owns all of it. This module resolves
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
from moneytracker.money_tracker.services import budgets, settings as settings_service


@frappe.whitelist()
def get_budgets(tracker=None, as_of=None, status="Active"):
	"""Every budget on a tracker with its current period measured."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	return {
		"tracker": tracker,
		"as_of": as_of,
		"status": status,
		"currency": settings_service.get_base_currency(),
		"budgets": [_presented(row) for row in budgets.measure_budgets(tracker, as_of, status=status)],
	}


@frappe.whitelist()
def get_budget_progress(budget, as_of=None):
	"""One budget's current period — the single shape the progress bar draws from."""
	frappe.has_permission("Money Budget", doc=budget, throw=True)
	return _presented(budgets.measure(budget, as_of))


def _presented(row):
	"""A measured budget plus the strings to print — one shape for every caller.

	Formatted here rather than in the browser for the same reason the Number Cards are
	(§33): a client formatting a number falls back to *System Settings'* currency, which is
	not necessarily the tracker's.
	"""
	currency = row.currency or settings_service.get_base_currency()
	row.formatted = {
		"budget_amount": fmt_money(flt(row.budget_amount), currency=currency),
		"available": fmt_money(flt(row.available), currency=currency),
		"spent": fmt_money(flt(row.spent), currency=currency),
		"remaining": fmt_money(flt(row.remaining), currency=currency),
		"carried_in": fmt_money(flt(row.carried_in), currency=currency),
		"available_per_day": (
			fmt_money(flt(row.available_per_day), currency=currency) if row.available_per_day else None
		),
	}
	row.history = [
		{**period, "formatted_spent": fmt_money(flt(period["spent"]), currency=currency)}
		for period in row.get("history") or []
	]
	return row


# ---------------------------------------------------------------------------
# Dashboard widgets. Same contract as the cards in api/dashboard.py: a Custom Number Card
# prints a returned string verbatim, so the counting and the wording both happen here.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_budgets_on_track(filters=None):
	"""How many active envelopes are being kept to — "4 of 5".

	Deliberately a count rather than "62% of 45,000 used". A tracker's budgets need not share
	a period, and adding a weekly envelope to a yearly one produces a total that stands for
	no window at all. Counting sidesteps that; the chart shows each envelope against its own.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	measured = budgets.measure_budgets(tracker, filters.get("as_of"))
	if not measured:
		return CARD_NO_DATA

	healthy = sum(1 for row in measured if row.outcome in budgets.HEALTHY_OUTCOMES)
	return _("{0} of {1}").format(healthy, len(measured))
