# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Tags API: the tracker's labels, and what each of them carries.

Nothing here does arithmetic — `services/tags.py` owns all of it. This module resolves who is
asking, which tracker they may see, and how the answer is formatted.
"""

import frappe
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.services import settings as settings_service
from moneytracker.money_tracker.services import tags as tags_service


@frappe.whitelist()
def get_tags(tracker=None, is_active=1):
	"""Every tag on a tracker, for a picker or a filter bar."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	filters = {"tracker": tracker}
	if is_active is not None and str(is_active) != "":
		filters["is_active"] = int(is_active)

	return frappe.get_all(
		"Money Tag",
		filters=filters,
		fields=["name", "tag_name", "color", "icon", "is_active"],
		order_by="tag_name asc",
	)


@frappe.whitelist()
def get_spend_by_tag(tracker=None, from_date=None, to_date=None, view="Expense"):
	"""What each tag carries over a window, biggest first.

	`total` is the tracker's real figure, not the sum of the rows: a transaction with three
	tags is counted in full under all three, so the rows overlap on purpose (§tags).
	"""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	measured = tags_service.get_spend_by_tag(tracker, from_date, to_date, view=view)
	currency = (
		frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()
	)

	# Formatted server-side against the tracker's currency, not the browser's: a client
	# formats against System Settings' instead (§33).
	for row in measured["tags"]:
		row["formatted_total"] = fmt_money(flt(row["total"]), currency=currency)

	measured["tracker"] = tracker
	measured["currency"] = currency
	measured["formatted_total"] = fmt_money(flt(measured["total"]), currency=currency)
	measured["formatted_untagged"] = fmt_money(flt(measured["untagged"]), currency=currency)
	return measured
