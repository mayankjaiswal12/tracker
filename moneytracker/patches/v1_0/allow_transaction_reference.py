# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

REFERENCE_DOCTYPE = "Journal Entry Account"
FIELDNAME = "reference_type"
OPTION = "Transaction"


def execute():
	"""Let a Journal Entry Account row point back at the Transaction that created it.

	`posting.engine` stamps every row with reference_type="Transaction" so the ledger can be
	navigated back to the user-facing voucher. ERPNext ships `reference_type` as a fixed
	Select, so without this the Select validation in `_validate_selects` rejects the row and
	*no* transaction can be submitted at all.

	Widening the option list is inert with respect to ERPNext's own behaviour: every branch
	in `journal_entry.py` that acts on a reference is gated either on an explicit equality
	check ("Asset", "Invoice Discounting", ...) or on membership of the invoice/order
	`field_dict`, so an unrecognised value falls through all of them.
	"""
	meta_field = frappe.get_meta(REFERENCE_DOCTYPE).get_field(FIELDNAME)
	if not meta_field:
		frappe.log_error(
			title="Cannot widen reference_type",
			message=f"{REFERENCE_DOCTYPE} has no field {FIELDNAME}; ERPNext may have restructured it.",
		)
		return

	options = (meta_field.options or "").split("\n")
	if OPTION in options:
		return

	options.append(OPTION)
	make_property_setter(
		REFERENCE_DOCTYPE,
		FIELDNAME,
		"options",
		"\n".join(options),
		"Text",
		validate_fields_for_doctype=False,
	)
