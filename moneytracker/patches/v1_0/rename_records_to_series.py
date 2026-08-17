# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.naming import make_autoname

# The real implementation, not `frappe.rename_doc`: the top-level wrapper does not accept
# ignore_permissions, and a patch should not depend on the session user's rights.
from frappe.model.rename_doc import rename_doc

# Same order every run, and deliberately not alphabetical: Tracker first, because it is the
# row every other record hangs off, so if the patch is ever interrupted the half-done state
# is the readable half.
SERIES = (
	("Tracker", "TRK-.#####"),
	("Money Account", "ACC-.#####"),
	("Category", "CAT-.#####"),
	("Money Account Group", "GRP-.#####"),
	("Money Payment Method", "PMT-.#####"),
)


def execute():
	"""Move the hash-named masters onto readable naming series.

	These were named by `hash` because two users must each be able to have an account called
	"Cash" in one shared Company — the name cannot be the primary key. A series keeps that
	property and reads as CAT-00001 rather than lat13t41qs.

	`frappe.rename_doc` rewrites every Link field pointing at a renamed row. For Tracker that
	includes `GL Entry.tracker` and `Journal Entry Account.tracker`: Tracker is registered as
	an ERPNext Accounting Dimension, so its value is stamped on submitted ledger rows. Those
	are updated by direct SQL, so `docstatus` does not stand in the way.

	Re-runnable: a row already on the series is skipped, so a partial run just continues.
	"""
	for doctype, series in SERIES:
		if not frappe.db.exists("DocType", doctype):
			continue

		already_named = re.compile(rf"^{re.escape(series.split('.')[0])}\d+$")

		# creation order, so the numbers read in the order the records were made.
		for name in frappe.get_all(doctype, pluck="name", order_by="creation asc"):
			if already_named.match(name):
				continue

			rename_doc(
				doctype,
				name,
				make_autoname(series, doctype),
				force=True,
				ignore_permissions=True,
				show_alert=False,
				rebuild_search=False,
			)
