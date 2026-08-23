# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Bills API: what is owed, what is overdue, and the widgets that say so."""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.api.dashboard import (
	CARD_NO_DATA,
	parse_widget_filters,
	resolve_widget_tracker,
)
from moneytracker.money_tracker.services import bills
from moneytracker.money_tracker.services import settings as settings_service


@frappe.whitelist()
def get_bills(tracker=None, as_of=None, status=None):
	"""Every bill on a tracker with its outcome worked out."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	currency = _currency(tracker)
	return {
		"tracker": tracker,
		"currency": currency,
		"bills": [_presented(row, currency) for row in bills.measure_bills(tracker, as_of, status)],
	}


@frappe.whitelist()
def get_upcoming(tracker=None, days=30, as_of=None):
	"""Open bills due within the window, plus anything already overdue."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	currency = _currency(tracker)
	upcoming = bills.get_upcoming(tracker, int(days), as_of)
	return {
		"tracker": tracker,
		"currency": currency,
		"total_due": flt(bills.get_total_due(tracker, int(days), as_of)),
		"bills": [_presented(row, currency) for row in upcoming],
	}


@frappe.whitelist()
def get_bill_progress(bill, as_of=None):
	"""One bill — the shape the form block draws from."""
	frappe.has_permission("Money Bill", doc=bill, throw=True)
	measured = bills.measure(bill, as_of)
	return _presented(measured, measured.currency or _currency(measured.tracker))


def _currency(tracker):
	return frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()


def _presented(row, currency):
	"""Money formatted server-side against the tracker's currency, not the browser's (§33)."""
	row.formatted = {
		"amount": _("Varies") if row.amount_varies else fmt_money(flt(row.amount), currency=currency)
	}
	return row


# ---------------------------------------------------------------------------
# Dashboard widgets. A Custom Number Card prints the returned string verbatim.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_bills_due(filters=None):
	"""What is owed in the next 30 days — a money total, not a count.

	The opposite choice from `Budgets on Track` and for the opposite reason: envelopes on
	different clocks cannot be added, while bills all name the same thing, an amount owed by
	a date. A bill whose amount varies is left out of the figure rather than guessed at, so
	this reads low rather than wrong.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	total = bills.get_total_due(tracker, int(filters.get("days") or 30), filters.get("as_of"))
	return fmt_money(flt(total), currency=_currency(tracker))


@frappe.whitelist()
def card_overdue_bills(filters=None):
	"""How many bills have gone past their date — "2 overdue", or "None overdue".

	A count rather than a total because this is about attention, not money: one forgotten
	500-rupee bill and one forgotten 50,000-rupee bill both need the same thing done.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	measured = bills.measure_bills(tracker, filters.get("as_of"), status="Unpaid")
	overdue = sum(1 for row in measured if row.outcome == bills.OVERDUE)
	return _("{0} overdue").format(overdue) if overdue else _("None overdue")
