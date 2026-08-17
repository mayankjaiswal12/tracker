# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Money Goal's controller rules.

The arithmetic lives in `moneytracker/tests/test_goals.py`. What is guarded here is the
shape of the document: that every rule is read out of `goals.GOAL_TYPES` rather than
hand-written per type, and that a goal cannot be saved describing something the measurement
would then have to guess at.
"""

import frappe
from frappe.utils import add_days, today

from moneytracker.money_tracker.services import goals
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_goal,
	make_tracker,
	unique,
)


class TestMoneyGoal(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.savings = make_account(cls.tracker, account_type="Savings").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

	# --- defaults ----------------------------------------------------------------------

	def test_the_tracker_currency_and_start_date_are_filled_in(self):
		"""The API path may omit all three; only `goal_name` is genuinely the user's to give."""
		goal = frappe.get_doc(
			{
				"doctype": "Money Goal",
				"goal_name": unique("Goal"),
				"goal_type": "Net Worth Target",
				"target_amount": 500,
			}
		).insert(ignore_permissions=True)

		self.assertTrue(goal.tracker)
		self.assertEqual(goal.currency, frappe.db.get_value("Tracker", goal.tracker, "base_currency"))
		self.assertEqual(str(goal.start_date), str(today()))

	def test_an_unknown_goal_type_is_refused(self):
		"""A Select can be bypassed by the API, and the measurement has nothing to dispatch on."""
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Retire Early", target_amount=100)

	def test_two_goals_on_one_tracker_cannot_share_a_name(self):
		name = unique("Goal")
		make_goal(self.tracker, goal_name=name, goal_type="Net Worth Target")

		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_name=name, goal_type="Net Worth Target")

	def test_another_tracker_may_reuse_the_name(self):
		"""Names are unique per tracker, as with Money Account and Category."""
		name = unique("Goal")
		make_goal(self.tracker, goal_name=name, goal_type="Net Worth Target")
		other = make_goal(make_tracker().name, goal_name=name, goal_type="Net Worth Target")

		self.assertEqual(other.goal_name, name)

	# --- the target --------------------------------------------------------------------

	def test_a_target_amount_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Net Worth Target", target_amount=0)

	def test_a_negative_target_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Net Worth Target", target_amount=-100)

	def test_a_percentage_goal_carries_its_target_in_the_percent_field(self):
		goal = make_goal(
			self.tracker,
			goal_type="Savings Rate Target",
			target_percent=30,
			target_amount=99999,
			target_date=add_days(self.date, 30),
		)

		# The amount is cleared rather than refused: a goal retyped from Savings would carry one.
		self.assertEqual(goal.target_percent, 30)
		self.assertEqual(goal.target_amount, 0)

	def test_a_rate_over_a_hundred_percent_is_refused(self):
		"""You cannot save more than everything you earned."""
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				self.tracker,
				goal_type="Savings Rate Target",
				target_percent=120,
				target_date=add_days(self.date, 30),
			)

	def test_a_money_goal_clears_a_stray_percentage(self):
		goal = make_goal(self.tracker, goal_type="Net Worth Target", target_amount=500, target_percent=42)

		self.assertEqual(goal.target_percent, 0)

	# --- the window --------------------------------------------------------------------

	def test_a_period_goal_needs_a_deadline(self):
		"""A Spending Limit measures a window, and a window has to end somewhere."""
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Spending Limit", category=self.food)

	def test_a_balance_goal_needs_no_deadline(self):
		"""Saving up with no date in mind is a real plan, unlike a limit with no period."""
		goal = make_goal(self.tracker, goal_type="Savings", target_account=self.savings)

		self.assertFalse(goal.target_date)

	def test_a_deadline_before_the_start_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				self.tracker,
				goal_type="Savings",
				target_account=self.savings,
				target_date=add_days(self.date, -1),
			)

	# --- the target account ------------------------------------------------------------

	def test_a_savings_goal_needs_an_account(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Savings")

	def test_a_savings_goal_refuses_a_credit_card(self):
		"""Saving into a card is a Debt Payoff typed wrong, and the sign would come out backwards."""
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Savings", target_account=self.card)

	def test_a_debt_payoff_refuses_a_bank_account(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Debt Payoff", target_account=self.bank)

	def test_an_account_on_another_tracker_is_refused(self):
		"""Otherwise a goal would quietly measure somebody else's money."""
		stranger = make_tracker().name
		foreign = make_account(stranger, account_type="Savings").name

		with self.assertRaises(frappe.ValidationError):
			make_goal(self.tracker, goal_type="Savings", target_account=foreign)

	def test_a_type_that_needs_no_account_drops_one_it_is_given(self):
		goal = make_goal(
			self.tracker, goal_type="Net Worth Target", target_amount=500, target_account=self.savings
		)

		self.assertIsNone(goal.target_account)

	def test_retyping_a_goal_clears_what_the_new_type_does_not_use(self):
		"""A goal that was a Savings pot keeps nothing of the account it used to point at."""
		goal = make_goal(
			self.tracker,
			goal_type="Savings",
			target_account=self.savings,
			measure_basis=goals.BASIS_CONTRIBUTIONS,
			opening_amount=5000,
		)

		goal.goal_type = "Net Worth Target"
		goal.save(ignore_permissions=True)

		self.assertIsNone(goal.target_account)
		self.assertIsNone(goal.measure_basis)
		self.assertEqual(goal.opening_amount, 0)

	def test_the_account_balance_basis_has_no_opening_amount(self):
		"""It counts everything in the account already, so an opening would double-count it."""
		goal = make_goal(
			self.tracker,
			goal_type="Savings",
			target_account=self.savings,
			measure_basis=goals.BASIS_BALANCE,
			opening_amount=5000,
		)

		self.assertEqual(goal.opening_amount, 0)

	def test_a_savings_goal_defaults_to_the_contributions_basis(self):
		goal = make_goal(self.tracker, goal_type="Savings", target_account=self.savings)

		self.assertEqual(goal.measure_basis, goals.BASIS_CONTRIBUTIONS)

	# --- the category ------------------------------------------------------------------

	def test_a_spending_limit_refuses_an_income_category(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				self.tracker,
				goal_type="Spending Limit",
				category=self.salary,
				target_date=add_days(self.date, 30),
			)

	def test_an_income_target_refuses_an_expense_category(self):
		with self.assertRaises(frappe.ValidationError):
			make_goal(
				self.tracker,
				goal_type="Income Target",
				category=self.food,
				target_date=add_days(self.date, 30),
			)

	def test_a_category_on_another_tracker_is_refused(self):
		foreign = make_category(make_tracker().name, category_type="Expense").name

		with self.assertRaises(frappe.ValidationError):
			make_goal(
				self.tracker,
				goal_type="Spending Limit",
				category=foreign,
				target_date=add_days(self.date, 30),
			)

	def test_a_group_category_is_allowed_on_a_limit(self):
		"""The opposite of Transaction, which refuses to post to a heading.

		A limit on a group is the useful case: `get_category_totals` rolls it up over its
		`lft`/`rgt` bounds, so one cap covers everything filed under it.
		"""
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		goal = make_goal(
			self.tracker,
			goal_type="Spending Limit",
			category=group.name,
			target_date=add_days(self.date, 30),
		)

		self.assertEqual(goal.category, group.name)

	def test_a_category_of_any_type_may_label_a_savings_goal(self):
		"""For a type that does not measure over a category, the field says what the goal is for.

		A Transfer into a savings account carries no category by construction, so it cannot be
		the basis — but "this pot is for Travel" is still worth recording.
		"""
		goal = make_goal(
			self.tracker, goal_type="Savings", target_account=self.savings, category=self.food
		)

		self.assertEqual(goal.category, self.food)
