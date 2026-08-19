# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import budgets, settings as settings_service


class MoneyBudget(Document):
	"""An envelope that refills every period. Spending lives in the ledger, not here.

	The controller's only job is to make sure the envelope is measurable: an amount worth
	measuring, a category on the right side of the books, a window that runs forwards, and
	no second envelope quietly counting the same money twice.
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
		budgets.get_budget_period(self.period)
		self.validate_unique_name_in_tracker()
		self.validate_amount()
		self.validate_window()
		self.validate_threshold()
		self.validate_category()
		self.validate_no_duplicate_envelope()

	def validate_unique_name_in_tracker(self):
		"""Names are unique per tracker, not globally — as with Money Account and Money Goal."""
		duplicate = frappe.db.exists(
			"Money Budget",
			{"budget_name": self.budget_name, "tracker": self.tracker, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("A budget named {0} already exists on this tracker.").format(self.budget_name))

	def validate_amount(self):
		if flt(self.budget_amount) <= 0:
			frappe.throw(_("Budget Amount must be greater than zero."))

	def validate_window(self):
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))

	def validate_threshold(self):
		"""Blank means the default, not "warn me at zero"."""
		if not flt(self.alert_threshold):
			self.alert_threshold = budgets.DEFAULT_ALERT_THRESHOLD
			return
		if not (0 < flt(self.alert_threshold) <= 100):
			frappe.throw(_("Alert Threshold must be greater than 0 and no more than 100."))

	def validate_category(self):
		"""An envelope only holds spending, so it can only be set against an expense category.

		A *group* is allowed, and is the usual case: a budget on Food is meant to cover
		Groceries and Restaurants with it, and `get_net_spend_by_date` rolls the subtree up.
		That is the opposite of `Transaction`, which refuses to post to a heading.
		"""
		if not self.category:
			return

		category_tracker, category_type, category_name = frappe.db.get_value(
			"Category", self.category, ["tracker", "category_type", "category_name"]
		)
		if category_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(category_name))

		if category_type != "Expense":
			frappe.throw(
				_(
					"{0} is an income category. A budget caps spending, so it is set against an expense."
				).format(category_name)
			)

	def validate_no_duplicate_envelope(self):
		"""Refuse a second live envelope over the same money on the same clock.

		Two budgets on the same category with different periods are fine and useful — a
		monthly grocery cap inside a yearly food cap. Two *monthly* caps on groceries running
		at the same time are one budget entered twice, and every figure that sums envelopes
		would count the money twice over.
		"""
		if self.status != "Active":
			return

		others = frappe.get_all(
			"Money Budget",
			filters={
				"tracker": self.tracker,
				"period": self.period,
				"status": "Active",
				"name": ["!=", self.name or ""],
			},
			# An empty Link comes back as None, and `{"category": None}` as a filter would be
			# read as "no filter" rather than as "no category" — so they are compared here.
			fields=["name", "budget_name", "category", "start_date", "end_date"],
		)

		for other in others:
			if (other.category or None) != (self.category or None):
				continue
			if not self._overlaps(other):
				continue
			frappe.throw(
				_(
					"{0} is already a {1} budget over the same {2}. Two live envelopes over one pot of money would count it twice."
				).format(
					frappe.bold(other.budget_name),
					self.period,
					_("category") if self.category else _("tracker"),
				)
			)

	def _overlaps(self, other):
		"""Whether two open-ended windows share any day at all."""
		start, end = getdate(self.start_date), getdate(self.end_date) if self.end_date else None
		other_start = getdate(other.start_date)
		other_end = getdate(other.end_date) if other.end_date else None

		if end and other_start > end:
			return False
		if other_end and start > other_end:
			return False
		return True
