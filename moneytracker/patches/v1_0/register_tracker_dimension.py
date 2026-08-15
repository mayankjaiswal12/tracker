# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Register Tracker as an ERPNext Accounting Dimension.

	This makes ERPNext add a `tracker` field to GL Entry, Journal Entry Account and every
	other accounting DocType, which in turn gives every stock financial report (General
	Ledger, Trial Balance, Balance Sheet, Profit and Loss, Cash Flow) a Tracker filter for
	free. It is the reason we do not need per-tracker reporting code.
	"""
	if frappe.db.exists("Accounting Dimension", {"document_type": "Tracker"}):
		return

	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	dimension = frappe.get_doc(
		{
			"doctype": "Accounting Dimension",
			"document_type": "Tracker",
			"label": "Tracker",
			"fieldname": "tracker",
		}
	)
	dimension.insert(ignore_permissions=True)

	# on_update enqueues this in a background job; run it inline so `migrate` leaves the
	# site in a finished state rather than one that depends on a worker being up.
	make_dimension_in_accounting_doctypes(doc=dimension)

	frappe.db.commit()
