# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from moneytracker.money_tracker.transaction_service import create_leaf_ledger_account, get_default_tracker


class Category(Document):
	def before_insert(self):
		if not self.tracker:
			self.tracker = get_default_tracker()
		if not self.ledger_account:
			self.ledger_account = create_leaf_ledger_account(
				self.tracker, self.category_name, self.category_type
			)
