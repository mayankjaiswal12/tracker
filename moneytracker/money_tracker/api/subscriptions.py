# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Subscriptions API: what you are signed up to, what renews next, and what a trial will cost."""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.api.dashboard import (
	CARD_NO_DATA,
	parse_widget_filters,
	resolve_widget_tracker,
)
from moneytracker.money_tracker.services import settings as settings_service
from moneytracker.money_tracker.services import subscriptions


@frappe.whitelist()
def get_subscriptions(tracker=None, as_of=None, status=None):
	"""Every subscription on a tracker, dearest per month first."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	currency = _currency(tracker)
	measured = subscriptions.measure_subscriptions(tracker, as_of, status)
	spend = subscriptions.get_subscription_spend(tracker, as_of)
	return {
		"tracker": tracker,
		"currency": currency,
		"monthly": spend.monthly,
		"annual": spend.annual,
		"formatted": {
			"monthly": fmt_money(spend.monthly, currency=currency),
			"annual": fmt_money(spend.annual, currency=currency),
		},
		"subscriptions": [_presented(row, currency) for row in measured],
	}


@frappe.whitelist()
def get_renewals(tracker=None, days=30, as_of=None):
	"""Live subscriptions charging again inside the window, soonest first.

	The shape *Subscriptions by Renewal* will read once `report/` exists (A3). Exposed now
	because the form and the card already need it and a report must not be the only way to
	reach a figure.
	"""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	currency = _currency(tracker)
	upcoming = subscriptions.get_renewals(tracker, int(days), as_of)
	return {
		"tracker": tracker,
		"currency": currency,
		"total": flt(sum(row.amount for row in upcoming)),
		"renewals": [_presented(row, currency) for row in upcoming],
	}


@frappe.whitelist()
def get_subscription_progress(subscription, as_of=None):
	"""One subscription — the shape the form block draws from."""
	frappe.has_permission("Money Subscription", doc=subscription, throw=True)
	measured = subscriptions.measure(subscription, as_of)
	return _presented(measured, measured.currency or _currency(measured.tracker))


def _currency(tracker):
	return frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()


def _presented(row, currency):
	"""Money formatted server-side against the tracker's currency, not the browser's (§33)."""
	row.formatted = {
		"amount": fmt_money(flt(row.amount), currency=currency),
		"monthly_equivalent": fmt_money(flt(row.monthly_equivalent), currency=currency),
		"annual_equivalent": fmt_money(flt(row.annual_equivalent), currency=currency),
	}
	if row.price_change:
		was = fmt_money(flt(row.price_change.from_amount), currency=currency)
		now = fmt_money(flt(row.price_change.to_amount), currency=currency)
		row.formatted["price_change"] = f"{was} → {now}"
	return row


# ---------------------------------------------------------------------------
# Dashboard widgets. A Custom Number Card prints the returned string verbatim.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_subscription_spend(filters=None):
	"""What the live subscriptions cost in an average month.

	A money total, like `Fixed Costs` and for the same reason: a monthly equivalent is a real
	figure whatever clock the thing is billed on, so a yearly domain renewal and a monthly
	music service can honestly be added.

	**It overlaps `Fixed Costs` on purpose.** A subscription paid by a standing order is in
	both. They answer different questions — what leaves the account every month, and what am I
	signed up to — and nothing sums the two, exactly as nothing sums a tag total with a
	category total.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	spend = subscriptions.get_subscription_spend(tracker, filters.get("as_of"))
	return fmt_money(spend.monthly, currency=_currency(tracker))


@frappe.whitelist()
def card_trials_ending(filters=None):
	"""How many free trials are about to turn into charges — "1 ending", or "No trials".

	A count rather than a total, because this is about attention and about the only state in
	the app where **doing nothing costs money**. The amount does not change what has to be
	done, and a trial's price is not being paid yet, so putting it in a money figure would
	claim money that has not moved and may never.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	ending = subscriptions.get_trials_ending(tracker, filters.get("days"), filters.get("as_of"))
	return _("{0} ending").format(len(ending)) if ending else _("No trials")
