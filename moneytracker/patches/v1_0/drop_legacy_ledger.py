# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe

# The app's own parallel ledger is replaced by ERPNext's Account / Journal Entry / GL Entry.
# These three DocTypes never held data, so there is nothing to migrate — see docs/architecture.md.
LEGACY_DOCTYPES = ("Money GL Entry", "Money Journal Entry", "Ledger Account")


def execute():
	for doctype in LEGACY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue

		count = frappe.db.count(doctype)
		if count:
			frappe.throw(
				f"Refusing to drop {doctype}: it holds {count} rows. "
				"This patch only supports the greenfield case; migrate the data first."
			)

		frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)

	frappe.db.commit()
