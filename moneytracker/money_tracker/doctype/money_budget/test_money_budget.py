# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Money Budget's own rules: what makes an envelope measurable, and what makes two of them
count the same money twice.

The measurement itself lives in `moneytracker/tests/test_budgets.py`. Everything here is the
controller refusing something.
"""

import frappe
from frappe.utils import add_days, add_months, get_first_day, getdate

from moneytracker.money_tracker.services import budgets
from moneytracker.tests.utils import MoneyTrackerTestCase, make_budget, make_category, make_tracker


class TestMoneyBudget(MoneyTrackerTestCase):
	def setUp(self):
		"""A tracker per test, not per class.

		`FrappeTestCase` rolls back once per class, so budgets left behind by one test are
		still live for the next — and a live budget over the whole tracker is exactly what
		`validate_no_duplicate_envelope` refuses a second of.
		"""
		self.tracker = make_tracker().name
		self.other_tracker = make_tracker().name
		self.expense = make_category(self.tracker).name
		self.income = make_category(self.tracker, category_type="Income").name
		self.month_start = getdate(get_first_day(self.date))

	# --- the basics ---------------------------------------------------------------------

	def test_the_tracker_and_currency_are_filled_in_server_side(self):
		budget = make_budget(self.tracker)

		self.assertEqual(budget.tracker, self.tracker)
		self.assertTrue(budget.currency)

	def test_a_name_is_unique_within_one_tracker(self):
		make_budget(self.tracker, budget_name="Groceries")

		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, budget_name="Groceries")

	def test_the_same_name_on_another_tracker_is_fine(self):
		"""Two people must both be able to have a budget called Groceries."""
		make_budget(self.tracker, budget_name="Fuel")
		self.assertTrue(make_budget(self.other_tracker, budget_name="Fuel").name)

	def test_an_envelope_of_nothing_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, budget_amount=0)

	def test_a_window_that_runs_backwards_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, start_date=self.date, end_date=add_days(self.date, -1))

	def test_an_unknown_period_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, period="Fortnightly")

	# --- the threshold ------------------------------------------------------------------

	def test_a_blank_threshold_means_the_default_not_zero(self):
		"""Warning at 0% would fire on the first rupee of every period."""
		budget = make_budget(self.tracker, alert_threshold=0)

		self.assertEqual(budget.alert_threshold, budgets.DEFAULT_ALERT_THRESHOLD)

	def test_a_threshold_over_a_hundred_percent_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, alert_threshold=120)

	# --- the category -------------------------------------------------------------------

	def test_an_income_category_is_refused(self):
		"""An envelope holds spending; there is nothing to cap on the income side."""
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, category=self.income)

	def test_another_trackers_category_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_budget(self.other_tracker, category=self.expense)

	def test_a_group_category_is_allowed(self):
		"""The opposite of Transaction, which refuses to post to a heading.

		A budget on a group is the usual case: one envelope over everything filed under it.
		"""
		group = make_category(self.tracker, category_name="Food", is_group=1).name
		make_category(self.tracker, category_name="Groceries", parent_category=group)

		self.assertTrue(make_budget(self.tracker, category=group).name)

	def test_no_category_is_allowed_and_means_the_whole_tracker(self):
		self.assertTrue(make_budget(self.tracker, category=None).name)

	# --- one envelope per pot of money --------------------------------------------------

	def test_a_second_live_envelope_over_the_same_money_is_refused(self):
		make_budget(self.tracker, category=self.expense, period="Monthly")

		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, category=self.expense, period="Monthly")

	def test_the_same_category_on_a_different_clock_is_fine(self):
		"""A monthly grocery cap inside a yearly food cap is a real way to budget."""
		category = make_category(self.tracker, category_name="Travel").name
		make_budget(self.tracker, category=category, period="Monthly")

		self.assertTrue(make_budget(self.tracker, category=category, period="Yearly").name)

	def test_two_whole_tracker_budgets_on_one_clock_are_refused(self):
		"""An empty category is a category too — both of them cover every expense there is."""
		make_budget(self.tracker, category=None, period="Quarterly")

		with self.assertRaises(frappe.ValidationError):
			make_budget(self.tracker, category=None, period="Quarterly")

	def test_windows_that_never_meet_are_fine(self):
		"""Last year's envelope and this year's are the same budget told twice, not two."""
		category = make_category(self.tracker, category_name="Fuel").name
		make_budget(
			self.tracker,
			category=category,
			start_date=add_months(self.month_start, -6),
			end_date=add_months(self.month_start, -1),
		)

		self.assertTrue(make_budget(self.tracker, category=category, start_date=self.month_start).name)

	def test_a_paused_budget_does_not_block_a_new_one(self):
		category = make_category(self.tracker, category_name="Books").name
		make_budget(self.tracker, category=category, status="Paused")

		self.assertTrue(make_budget(self.tracker, category=category).name)

	def test_saving_a_budget_again_does_not_collide_with_itself(self):
		budget = make_budget(self.tracker, category=make_category(self.tracker).name)
		budget.budget_amount = 12345
		budget.save()

		self.assertEqual(frappe.db.get_value("Money Budget", budget.name, "budget_amount"), 12345)
