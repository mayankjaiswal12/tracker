# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from moneytracker.money_tracker.posting import engine
from moneytracker.money_tracker.services import fx, settings as settings_service

# Types where `destination_account` is the other side of the movement rather than a category.
ACCOUNT_TO_ACCOUNT_TYPES = ("Transfer", "Credit Card Payment")


class Transaction(Document):
	def before_validate(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.company:
			self.company = settings_service.get_company()
		if not self.currency:
			self.currency = frappe.db.get_value("Money Account", self.account, "currency")

	def validate(self):
		self.validate_amount()
		self.validate_accounts()
		self.validate_category()
		self.set_base_amount()

	def validate_amount(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero."))

	def validate_accounts(self):
		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			if not self.destination_account:
				frappe.throw(_("Destination Account is required for a {0}.").format(self.transaction_type))
			# A movement between two accounts has no category by construction; clearing it
			# here stops a stale value from a retyped transaction reaching the ledger.
			self.category = None
		elif self.destination_account:
			self.destination_account = None

	def validate_category(self):
		"""A group category is a heading, not a place to post.

		Caught here rather than at submit: the posting engine would fail too, on the missing
		ledger account, but by then the user has already filled in a whole voucher and the
		message talks about accounting rather than about the choice they made.
		"""
		if not self.category:
			return

		category_name, is_group = frappe.db.get_value(
			"Category", self.category, ["category_name", "is_group"]
		)
		if is_group:
			frappe.throw(
				_("{0} is a group category. Post to one of its sub-categories instead.").format(category_name)
			)

	def set_base_amount(self):
		base_amount, rate = fx.to_base_currency(self.amount, self.currency, self.date, self.exchange_rate)
		self.exchange_rate = rate
		self.base_amount = base_amount

	def before_submit(self):
		engine.check_sufficient_balance(self)

	def on_submit(self):
		if settings_service.get_settings().auto_post_transactions:
			engine.post(self)

	def on_cancel(self):
		# Frappe would otherwise complain that journal_entry changed after cancellation.
		self.ignore_linked_doctypes = ("Journal Entry", "GL Entry")
		engine.unpost(self)

	def on_trash(self):
		if self.journal_entry:
			frappe.throw(
				_("Cannot delete a posted transaction. Cancel it instead, which reverses the ledger entries.")
			)

	@frappe.whitelist()
	def reverse(self):
		"""Create a mirror-image transaction that cancels this one out (spec §80).

		Used when the original must stay on the books — cancelling would hide it, whereas a
		reversal leaves both the original and its correction visible.
		"""
		if self.docstatus != 1:
			frappe.throw(_("Only a submitted transaction can be reversed."))
		if frappe.db.exists("Transaction", {"reversal_of": self.name, "docstatus": 1}):
			frappe.throw(_("This transaction has already been reversed."))

		reversal = frappe.copy_doc(self)
		reversal.reversal_of = self.name
		reversal.journal_entry = None
		reversal.amended_from = None

		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			reversal.account, reversal.destination_account = (
				self.destination_account,
				self.account,
			)
			if self.transaction_type == "Credit Card Payment":
				# Undoing a card payment means Dr bank / Cr card — money going back the other
				# way. That is not itself a card payment, which always debits the card, so the
				# swapped pair would be refused as "destination is a Bank, not a liability".
				# It is a settlement between two balance-sheet accounts: a Transfer.
				reversal.transaction_type = "Transfer"
		elif self.transaction_type == "Expense":
			reversal.transaction_type = "Refund"
		elif self.transaction_type == "Refund":
			reversal.transaction_type = "Expense"
		elif self.transaction_type == "Income":
			frappe.throw(_("Reversing an Income is not supported yet. Cancel the transaction instead."))

		reversal.insert()
		reversal.submit()
		return reversal.name
