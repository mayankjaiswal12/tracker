# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import coa, goals, settings as settings_service


class MoneyGoal(Document):
	"""A target and a window. Progress lives in the ledger, not on this document.

	Every rule below is read out of `goals.GOAL_TYPES` rather than written as a chain of
	`if goal_type == ...`, so a new kind of goal is a row in that table plus a measure
	function — the same bargain `posting/strategies` makes with the posting engine.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.currency:
			self.currency = frappe.db.get_value(
				"Tracker", self.tracker, "base_currency"
			) or settings_service.get_base_currency()
		if not self.start_date:
			self.start_date = today()

	def validate(self):
		spec = goals.get_goal_type(self.goal_type)
		self.validate_unique_name_in_tracker()
		self.clear_unused_fields(spec)
		self.validate_target(spec)
		self.validate_window(spec)
		self.validate_target_account(spec)
		self.validate_category(spec)

	def validate_unique_name_in_tracker(self):
		"""Names are unique per tracker, not globally — as with Money Account and Category."""
		duplicate = frappe.db.exists(
			"Money Goal",
			{"goal_name": self.goal_name, "tracker": self.tracker, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("A goal named {0} already exists on this tracker.").format(self.goal_name))

	def clear_unused_fields(self, spec):
		"""Blank whatever this type of goal does not measure with.

		A goal retyped from Savings to Net Worth Target would otherwise keep pointing at an
		account, and the stale link would show up in every report that joins on it.
		"""
		if not spec.account:
			self.target_account = None
		if not spec.basis_choice:
			self.measure_basis = None
		elif self.measure_basis not in goals.MEASURE_BASES:
			self.measure_basis = goals.BASIS_CONTRIBUTIONS
		if not spec.opening or self.measure_basis == goals.BASIS_BALANCE:
			self.opening_amount = 0

	def validate_target(self, spec):
		"""Exactly one of the two target fields carries the number, decided by the unit."""
		if spec.unit == goals.PERCENT:
			self.target_amount = 0
			if not (0 < flt(self.target_percent) <= 100):
				frappe.throw(_("Target Percent must be greater than 0 and no more than 100."))
			return

		self.target_percent = 0
		if flt(self.target_amount) <= 0:
			frappe.throw(_("Target Amount must be greater than zero."))

	def validate_window(self, spec):
		if spec.needs_deadline and not self.target_date:
			frappe.throw(
				_("A {0} needs a Target Date — it measures a period, and a period has to end.").format(
					self.goal_type
				)
			)
		if self.target_date and getdate(self.target_date) < getdate(self.start_date):
			frappe.throw(_("Target Date cannot be before Start Date."))

	def validate_target_account(self, spec):
		if not spec.account:
			return
		if not self.target_account:
			frappe.throw(_("A {0} needs a Target Account.").format(self.goal_type))

		account_tracker, account_type, account_name = frappe.db.get_value(
			"Money Account", self.target_account, ["tracker", "account_type", "account_name"]
		)
		if account_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(account_name))

		# Saving into a credit card, or paying off a bank account, is the goal typed wrong
		# rather than an unusual plan — and the measurement would report the sign backwards.
		wants_liability = spec.account == "Liability"
		if coa.is_liability(account_type) == wants_liability:
			return

		if wants_liability:
			frappe.throw(
				_("{0} is not a debt. A {1} is set against a credit card or a loan.").format(
					account_name, self.goal_type
				)
			)
		frappe.throw(
			_("{0} is a debt, not somewhere to save. Use a Debt Payoff goal for it instead.").format(
				account_name
			)
		)

	def validate_category(self, spec):
		"""The category is the measurement basis for some types and a label for the rest.

		A *group* category is allowed either way: `get_category_totals` rolls a group up over
		its `lft`/`rgt` bounds, so a limit on Food covers Groceries and Restaurants with it.
		That is the opposite of `Transaction`, which refuses to post to a heading.
		"""
		if not self.category:
			return

		category_tracker, category_type, category_name = frappe.db.get_value(
			"Category", self.category, ["tracker", "category_type", "category_name"]
		)
		if category_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(category_name))

		if spec.category_type and category_type != spec.category_type:
			frappe.throw(
				_("{0} is a {1} category. A {2} is measured over {3} categories.").format(
					category_name, category_type, self.goal_type, spec.category_type
				)
			)
