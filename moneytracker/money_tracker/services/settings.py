# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Accessors for Money Settings.

Nothing else in the app is allowed to hardcode a company, currency or tracker name —
every such value is resolved through here so a site can be reconfigured without a code
change. See spec §33 (no assumed base currency) and §83 (no hardcoded currencies).
"""

import frappe
from frappe import _


def get_settings():
	return frappe.get_cached_doc("Money Settings")


def get_company():
	company = get_settings().company
	if not company:
		frappe.throw(_("Set a Company in Money Settings before recording transactions."))
	return company


def get_base_currency():
	settings = get_settings()
	if settings.base_currency:
		return settings.base_currency
	return frappe.db.get_value("Company", get_company(), "default_currency")


def get_default_cost_center():
	settings = get_settings()
	if settings.default_cost_center:
		return settings.default_cost_center

	company = get_company()
	cost_center = frappe.db.get_value("Company", company, "cost_center")
	if not cost_center:
		cost_center = frappe.db.get_value(
			"Cost Center", {"company": company, "is_group": 0}, "name", order_by="creation asc"
		)
	if not cost_center:
		frappe.throw(_("No Cost Center found for Company {0}. Set one in Money Settings.").format(company))
	return cost_center


def find_tracker(user=None):
	"""The tracker to *display* for `user`, or None if they have none yet.

	Deliberately not `get_default_tracker()`: that creates a Tracker on first use, and
	painting a dashboard — a card, a chart, a read-only widget — must never write one into
	existence. A user with no tracker gets an empty widget, not a new record.
	"""
	user = user or frappe.session.user
	return frappe.db.get_value(
		"Tracker", {"owner_user": user, "is_archived": 0}, "name", order_by="creation asc"
	)


def get_default_tracker(user=None):
	"""Return the tracker a new record belongs to for `user`, creating one on first use.

	Scoped per user: with a single shared Company, the tracker is what separates one
	person's books from another's, so this must never hand back somebody else's tracker.
	"""
	user = user or frappe.session.user

	settings = get_settings()
	if settings.default_tracker:
		owner = frappe.db.get_value("Tracker", settings.default_tracker, "owner_user")
		if owner == user:
			return settings.default_tracker

	existing = frappe.db.get_value(
		"Tracker", {"owner_user": user, "is_archived": 0}, "name", order_by="creation asc"
	)
	if existing:
		return existing

	tracker = frappe.get_doc(
		{
			"doctype": "Tracker",
			"tracker_name": "Personal",
			"tracker_type": "Personal",
			"base_currency": get_base_currency(),
			"owner_user": user,
		}
	)
	tracker.insert(ignore_permissions=True)
	return tracker.name
