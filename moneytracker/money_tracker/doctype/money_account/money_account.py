# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from moneytracker.money_tracker.transaction_service import (
	ASSET_ROOT_TYPES,
	create_leaf_ledger_account,
	get_default_tracker,
)


class MoneyAccount(Document):
	def before_insert(self):
		if not self.tracker:
			self.tracker = get_default_tracker()
		if not self.ledger_account:
			self.ledger_account = create_leaf_ledger_account(
				self.tracker, self.account_name, ASSET_ROOT_TYPES[self.account_type], self.account_type
			)
		if not self.current_balance:
			self.current_balance = self.opening_balance

	def on_trash(self):
		if frappe.db.exists("Transaction", {"account": self.name}) or frappe.db.exists(
			"Transaction", {"destination_account": self.name}
		):
			frappe.throw("Cannot delete an Account that has posted Transactions against it.")
