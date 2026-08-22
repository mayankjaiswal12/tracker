# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Merchants API: the tracker's payees, and what each of them took.

Nothing here does arithmetic — `services/merchants.py` owns all of it.
"""

import frappe
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.services import (
	merchants as merchants_service,
)
from moneytracker.money_tracker.services import (
	settings as settings_service,
)


@frappe.whitelist()
def get_merchants(tracker=None, is_active=1):
	"""Every merchant on a tracker, for a picker or a filter bar."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	filters = {"tracker": tracker}
	if is_active is not None and str(is_active) != "":
		filters["is_active"] = int(is_active)

	return frappe.get_all(
		"Money Merchant",
		filters=filters,
		fields=["name", "merchant_name", "default_category", "default_payment_method", "is_active"],
		order_by="merchant_name asc",
	)


@frappe.whitelist()
def get_spend_by_merchant(tracker=None, from_date=None, to_date=None, view="Expense", limit=None):
	"""What each merchant took over a window, biggest first — the Top Merchants figure."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	measured = merchants_service.get_spend_by_merchant(
		tracker, from_date, to_date, view=view, limit=int(limit) if limit else None
	)
	currency = (
		frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()
	)

	# Formatted server-side against the tracker's currency, not the browser's (§33).
	for row in measured["merchants"]:
		row["formatted_total"] = fmt_money(flt(row["total"]), currency=currency)

	measured["tracker"] = tracker
	measured["currency"] = currency
	measured["formatted_total"] = fmt_money(flt(measured["total"]), currency=currency)
	measured["formatted_unnamed"] = fmt_money(flt(measured["unnamed"]), currency=currency)
	return measured
