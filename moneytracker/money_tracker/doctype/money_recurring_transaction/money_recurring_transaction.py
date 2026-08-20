# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.doctype.transaction.transaction import ACCOUNT_TO_ACCOUNT_TYPES
from moneytracker.money_tracker.services import recurring
from moneytracker.money_tracker.services import settings as settings_service


class MoneyRecurringTransaction(Document):
	"""A Transaction template plus a schedule. It stores nothing about what it has posted.

	**The controller validates harder than `Transaction` does, on purpose.** A transaction is
	typed by somebody who is looking at it, so its category type is checked at submit, where
	the posting engine needs it (`context.require_category`). A plan runs unattended at 3am:
	whatever is wrong with it is wrong every month until somebody notices, and the person who
	could have caught it was last here when they pressed Save. So every rule the engine would
	eventually apply is applied now, while there is still somebody to read the message.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.currency:
			self.currency = (
				frappe.db.get_value("Tracker", self.tracker, "base_currency")
				or settings_service.get_base_currency()
			)
		if not self.start_date:
			self.start_date = today()

	def validate(self):
		recurring.get_frequency(self.frequency)
		self.validate_unique_name_in_tracker()
		self.validate_transaction_type()
		self.validate_create_mode()
		self.validate_amount()
		self.validate_window()
		self.validate_accounts()
		self.validate_category()

	def validate_unique_name_in_tracker(self):
		"""Names are unique per tracker, as with Money Account, Money Goal and Money Budget."""
		duplicate = frappe.db.exists(
			"Money Recurring Transaction",
			{"recurring_name": self.recurring_name, "tracker": self.tracker, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(
				_("A recurring transaction named {0} already exists on this tracker.").format(
					self.recurring_name
				)
			)

	def validate_transaction_type(self):
		"""Only the types a schedule can meaningfully repeat — see `RECURRING_TYPES`."""
		if self.transaction_type not in recurring.RECURRING_TYPES:
			frappe.throw(
				_("{0} cannot be scheduled. A recurring transaction may be one of: {1}.").format(
					self.transaction_type, ", ".join(recurring.RECURRING_TYPES)
				)
			)

	def validate_create_mode(self):
		if not self.create_mode:
			self.create_mode = recurring.POST_AUTOMATICALLY
		if self.create_mode not in recurring.CREATE_MODES:
			frappe.throw(
				_("Unknown value for When It Runs: {0}. Supported: {1}.").format(
					self.create_mode, ", ".join(recurring.CREATE_MODES)
				)
			)

	def validate_amount(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero."))

	def validate_window(self):
		"""An end date before the first occurrence would describe a plan that never runs."""
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))

	def validate_accounts(self):
		"""The same rules `Transaction` applies, and one it cannot: the tracker must match.

		A transaction's account is picked from a link field the client already filters by
		tracker. A plan is often written once by API or copied from another plan, and an
		account belonging to somebody else's tracker would post into their books every month.
		"""
		account_tracker, account_name = frappe.db.get_value(
			"Money Account", self.account, ["tracker", "account_name"]
		) or (None, None)
		if account_tracker and account_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(account_name))

		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			if not self.destination_account:
				frappe.throw(_("Destination Account is required for a {0}.").format(self.transaction_type))
			if self.destination_account == self.account:
				frappe.throw(_("Source and destination accounts must be different."))

			destination_tracker, destination_name = frappe.db.get_value(
				"Money Account", self.destination_account, ["tracker", "account_name"]
			) or (None, None)
			if destination_tracker and destination_tracker != self.tracker:
				frappe.throw(_("{0} belongs to another tracker.").format(destination_name))

			# A movement between two accounts has no category by construction. Cleared here so
			# a retyped plan cannot carry a stale one into every future occurrence.
			self.category = None
		elif self.destination_account:
			self.destination_account = None

	def validate_category(self):
		"""Required, on the right side of the books, on this tracker, and not a heading.

		Every one of these would otherwise surface as a posting failure inside a background
		job — the plan saves cleanly, then fails silently every month at 3am.
		"""
		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			return

		if not self.category:
			frappe.throw(_("Category is required for a {0}.").format(self.transaction_type))

		category_tracker, category_type, category_name, is_group = frappe.db.get_value(
			"Category", self.category, ["tracker", "category_type", "category_name", "is_group"]
		)
		if category_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(category_name))

		expected = "Income" if self.transaction_type == "Income" else "Expense"
		if category_type != expected:
			frappe.throw(
				_("{0} is an {1} category, but this plan posts an {2}.").format(
					category_name, category_type, self.transaction_type
				)
			)
		if is_group:
			frappe.throw(
				_("{0} is a group category. Post to one of its sub-categories instead.").format(category_name)
			)

	def on_trash(self):
		"""A plan may be deleted; what it posted stays, with the link cleared.

		The transactions are real money that really moved. Frappe would refuse the delete
		outright over the link, which would leave a finished plan on the list forever — so the
		back-links are dropped and the history is kept. `Archived` is the better answer for a
		plan somebody has finished with, and the form says so.
		"""
		frappe.db.set_value(
			"Transaction",
			{"recurring_transaction": self.name},
			"recurring_transaction",
			None,
			update_modified=False,
		)

	@frappe.whitelist()
	def post_due_now(self, as_of=None):
		"""Post everything outstanding on this plan without waiting for the nightly job.

		The button behind the form's Schedule block. It runs the same `generate()` the
		scheduler does, so it can neither post an occurrence twice nor reach back before the
		plan existed.
		"""
		if self.status != "Active":
			frappe.throw(_("Only an Active plan can post. This one is {0}.").format(self.status))

		created = recurring.generate(self, as_of)
		if not created:
			return {"created": [], "message": _("Nothing is due yet.")}

		return {
			"created": created,
			"message": _("Posted {0} transaction(s).").format(len(created)),
		}
