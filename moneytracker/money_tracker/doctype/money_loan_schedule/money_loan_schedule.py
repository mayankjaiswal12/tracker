# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MoneyLoanSchedule(Document):
	"""One instalment of an amortisation table.

	Every column is read-only, because every column is arithmetic: the whole table is built by
	`services/loans.build_schedule()` from the loan's terms on save. It is stored rather than
	derived on read only because the terms freeze once a payment has been posted against the
	loan — see the controller — so a stored schedule cannot drift from terms that cannot change.
	"""

	pass
