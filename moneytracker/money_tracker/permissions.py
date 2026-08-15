# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Row-level security.

All finance data lives in one shared ERPNext Company, so nothing in the ledger itself
separates one user's books from another's — these hooks do. Treat them as security code:
a bug here leaks another person's finances (spec §55).

Tracker membership becomes richer in Phase 4 (owner / admin / editor / viewer). Today a
tracker has exactly one owner, and this module is the single place that decides access,
so extending it later does not mean touching every DocType.
"""

import frappe

# Roles that legitimately see everything. Finance Manager is included because reviewing
# across users is the job; Finance User and Finance Viewer are confined to their own data.
UNRESTRICTED_ROLES = {"Administrator", "System Manager", "Finance Admin", "Finance Manager"}


def _is_unrestricted(user):
	if user == "Administrator":
		return True
	return bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def _accessible_trackers(user):
	return frappe.get_all("Tracker", filters={"owner_user": user}, pluck="name")


def tracker_query_conditions(user=None, doctype=None):
	"""List-view filter for the Tracker DocType itself."""
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return ""
	return f"`tabTracker`.`owner_user` = {frappe.db.escape(user)}"


def tracker_has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return True
	return doc.owner_user == user


def tracker_scoped_query_conditions(user=None, doctype=None):
	"""List-view filter for any DocType carrying a `tracker` link."""
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return ""

	trackers = _accessible_trackers(user)
	if not trackers:
		# No tracker yet means nothing to see. Returning a false condition rather than ""
		# matters: "" would mean "no restriction" and expose every row.
		return "1 = 0"

	table = f"`tab{doctype}`" if doctype else "`tabTransaction`"
	placeholders = ", ".join(frappe.db.escape(t) for t in trackers)
	return f"{table}.`tracker` in ({placeholders})"


def tracker_scoped_has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return True
	if not doc.get("tracker"):
		return True
	return frappe.db.get_value("Tracker", doc.tracker, "owner_user") == user
