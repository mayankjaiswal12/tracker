# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Goals API: measured progress for a client, a Desk form, or a dashboard widget.

Nothing here does arithmetic — `services/goals.py` owns all of it. This module resolves who
is asking, which tracker they may see, and how the answer is formatted.
"""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.api.dashboard import (
	CARD_NO_DATA,
	parse_widget_filters,
	resolve_widget_tracker,
)
from moneytracker.money_tracker.services import goals, settings as settings_service


@frappe.whitelist()
def get_goals(tracker=None, as_of=None, status="Active"):
	"""Every goal on a tracker with its measured progress."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	return {
		"tracker": tracker,
		"as_of": as_of,
		"status": status,
		"currency": settings_service.get_base_currency(),
		"goals": [_presented(row) for row in goals.measure_goals(tracker, as_of, status=status)],
	}


@frappe.whitelist()
def get_goal_progress(goal, as_of=None):
	"""Measured progress for one goal — the single shape the progress bar draws from."""
	frappe.has_permission("Money Goal", doc=goal, throw=True)
	return _presented(goals.measure(goal, as_of))


def _presented(row):
	"""A measured goal plus the strings to print — one shape for every caller.

	The figures are formatted here rather than in the browser for the same reason the Number
	Cards are (§33): a client formatting a number falls back to *System Settings'* currency,
	which is not necessarily the tracker's.
	"""
	return row.update({"formatted": format_measured(row)})


# ---------------------------------------------------------------------------
# Dashboard widgets. Same contract as the five cards in api/dashboard.py: a Custom Number
# Card prints a returned string verbatim, so the counting and the wording both happen here.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_goals_on_track(filters=None):
	"""How many active goals are being met — "3 of 5"."""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	measured = goals.measure_goals(tracker, filters.get("as_of"))
	if not measured:
		return CARD_NO_DATA

	healthy = sum(1 for row in measured if row.outcome in goals.HEALTHY_OUTCOMES)
	return _("{0} of {1}").format(healthy, len(measured))


def format_measured(row):
	"""One measured goal as the strings a widget or a progress bar shows.

	A percentage target reads as "43.4% of 30%"; everything else is money, formatted here
	against the goal's own currency rather than in the browser against System Settings'.
	"""
	if row.current is None:
		return {"current": CARD_NO_DATA, "target": CARD_NO_DATA, "remaining": CARD_NO_DATA}

	if row.unit == goals.PERCENT:
		return {
			"current": f"{flt(row.current, 1)}%",
			"target": f"{flt(row.target, 1)}%",
			"remaining": f"{flt(row.remaining, 1)}%",
		}

	currency = row.currency or settings_service.get_base_currency()
	return {
		"current": fmt_money(flt(row.current), currency=currency),
		"target": fmt_money(flt(row.target), currency=currency),
		"remaining": fmt_money(flt(row.remaining), currency=currency),
	}
