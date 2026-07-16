# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from moneytracker.money_tracker.transaction_service import get_default_tracker, post_journal_entry


class Transaction(Document):
	def before_insert(self):
		if not self.tracker:
			self.tracker = get_default_tracker()

	def validate(self):
		# GL Entries are immutable; once a Transaction is posted, it can never be edited —
		# corrections are a new reversing Transaction in a later version, never an edit to history.
		if not self.is_new() and frappe.db.get_value("Transaction", self.name, "journal_entry"):
			frappe.throw("This Transaction has already been posted to the ledger and cannot be edited.")

	def after_insert(self):
		post_journal_entry(self)

	def on_trash(self):
		if self.journal_entry:
			frappe.throw("This Transaction has already been posted to the ledger and cannot be deleted.")
