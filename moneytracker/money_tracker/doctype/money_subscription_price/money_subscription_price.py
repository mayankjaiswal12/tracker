# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MoneySubscriptionPrice(Document):
	"""One price, and the day it started applying.

	The only stored series in this app that is not derived from the ledger, and it has to be:
	a price rise is a fact about the vendor, not about money that has moved. Nothing in
	`GL Entry` can say that Netflix went from 499 to 649 in June — the ledger only knows what
	was paid, and a month somebody forgot to pay looks exactly like a month the price was zero.
	"""

	pass
