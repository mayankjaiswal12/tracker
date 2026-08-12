# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import coa, settings as settings_service


class MoneyAccount(Document):
	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.currency:
			self.currency = settings_service.get_base_currency()

	def validate(self):
		self.validate_unique_name_in_tracker()
		if not self.ledger_account:
			self.ledger_account = coa.get_or_create_account_for_money_account(self)

	def validate_unique_name_in_tracker(self):
		"""Names are unique per tracker, not globally.

		Two users each having a "Cash" account is normal; the DocType is named by hash so
		that stays possible, and this is what keeps it unambiguous within one tracker.
		"""
		duplicate = frappe.db.exists(
			"Money Account",
			{"account_name": self.account_name, "tracker": self.tracker, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(
				_("An account named {0} already exists on this tracker.").format(self.account_name)
			)

	def on_trash(self):
		if frappe.db.exists("Transaction", {"account": self.name}) or frappe.db.exists(
			"Transaction", {"destination_account": self.name}
		):
			frappe.throw(_("Cannot delete an account that has transactions against it."))
