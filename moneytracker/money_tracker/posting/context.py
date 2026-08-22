# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _


class PostingContext:
	"""Everything a strategy needs, resolved once.

	Strategies receive this instead of hitting the database themselves, so each strategy
	stays a pure statement of its accounting rule.
	"""

	def __init__(self, transaction):
		self.transaction = transaction
		self.amount = transaction.amount
		self.currency = transaction.currency

		self.account = frappe.get_cached_doc("Money Account", transaction.account)
		self.destination_account = (
			frappe.get_cached_doc("Money Account", transaction.destination_account)
			if transaction.destination_account
			else None
		)
		self.category = (
			frappe.get_cached_doc("Category", transaction.category) if transaction.category else None
		)
		# Resolved here for the same reason `category` is: a strategy states an accounting rule
		# and touches no database. A split transaction has no single category, so `self.category`
		# is None and these carry the breakdown instead.
		self.splits = [
			frappe._dict(
				category=frappe.get_cached_doc("Category", row.category),
				amount=row.amount,
			)
			for row in (transaction.get("splits") or [])
		]

	def require_category(self, expected_type):
		if not self.category:
			frappe.throw(_("Category is required for a {0}.").format(self.transaction.transaction_type))
		if self.category.category_type != expected_type:
			frappe.throw(
				_("Category {0} is an {1} category, but this is a {2}.").format(
					self.category.category_name,
					self.category.category_type,
					self.transaction.transaction_type,
				)
			)
		if not self.category.ledger_account:
			frappe.throw(_("Category {0} has no ledger account.").format(self.category.category_name))
		return self.category

	def require_splits(self, expected_type):
		"""The split rows, each checked the way `require_category` checks the single one.

		The controller has already refused anything that does not add up, so this is the
		posting-time half of the same rule: every category still has to be on the right side of
		the books and still has to have a ledger account to post to.
		"""
		for split in self.splits:
			category = split.category
			if category.category_type != expected_type:
				frappe.throw(
					_("Category {0} is an {1} category, but this is a {2}.").format(
						category.category_name, category.category_type, self.transaction.transaction_type
					)
				)
			if not category.ledger_account:
				frappe.throw(_("Category {0} has no ledger account.").format(category.category_name))
		return self.splits

	def require_destination(self):
		if not self.destination_account:
			frappe.throw(
				_("Destination Account is required for a {0}.").format(self.transaction.transaction_type)
			)
		if self.destination_account.name == self.account.name:
			frappe.throw(_("Source and destination accounts must be different."))
		return self.destination_account
