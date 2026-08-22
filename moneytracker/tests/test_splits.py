# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Splitting one payment across several categories.

The leg shapes are asserted without a database in `test_strategies.py`. What is tested here
is everything downstream of them, and one thing in particular: **a split bill must not go
missing.** A split transaction carries no category of its own, so every figure that groups by
category — the roll-up, the dashboard chart, every budget envelope — has to read the split
rows instead, or the money silently disappears from all of them while the bank balance stays
right.
"""

import frappe

from moneytracker.money_tracker.services import budgets as budgets_service
from moneytracker.money_tracker.services import categories as categories_service
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	gl_rows,
	make_account,
	make_budget,
	make_category,
	make_tracker,
	make_transaction,
	posting_date,
)


class SplitFixture(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker, account_type="Bank").name
		self.groceries = make_category(self.tracker, category_type="Expense").name
		self.household = make_category(self.tracker, category_type="Expense").name
		self.salary = make_category(self.tracker, category_type="Income").name

	def split_expense(self, amount=1000, shares=None, **kwargs):
		shares = shares or ((self.groceries, 800), (self.household, 200))
		return make_transaction(
			"Expense",
			amount,
			self.account,
			tracker=self.tracker,
			splits=[{"category": c, "amount": a} for c, a in shares],
			**kwargs,
		)


class TestSplitPosting(SplitFixture):
	def test_it_posts_one_credit_and_a_debit_per_category(self):
		transaction = self.split_expense()
		rows = gl_rows(transaction.journal_entry, include_cancelled=False)
		self.assertEqual(len(rows), 3)
		self.assertEqual(sum(r.debit for r in rows), sum(r.credit for r in rows))
		self.assertEqual(sum(r.debit for r in rows), 1000)

	def test_the_parent_keeps_no_category_of_its_own(self):
		"""Keeping a "primary" one would be counted twice by everything that sums categories."""
		self.assertIsNone(self.split_expense().category)

	def test_each_row_is_stamped_with_its_base_amount(self):
		transaction = self.split_expense()
		self.assertEqual([r.base_amount for r in transaction.splits], [800, 200])

	def test_income_splits_the_other_way_round(self):
		other = make_category(self.tracker, category_type="Income").name
		transaction = make_transaction(
			"Income",
			5000,
			self.account,
			tracker=self.tracker,
			splits=[{"category": self.salary, "amount": 4000}, {"category": other, "amount": 1000}],
		)
		rows = gl_rows(transaction.journal_entry, include_cancelled=False)
		self.assertEqual(len(rows), 3)
		self.assertEqual(len([r for r in rows if r.debit]), 1)

	def test_cancelling_reverses_every_leg(self):
		transaction = self.split_expense()
		transaction.cancel()
		rows = gl_rows(transaction.journal_entry, include_cancelled=True)
		self.assertEqual(sum(r.debit for r in rows), sum(r.credit for r in rows))


class TestSplitsReachTheRollUp(SplitFixture):
	"""The bug this module exists to prevent."""

	def totals(self):
		return {row["category"]: row["total"] for row in categories_service.get_category_totals(self.tracker)}

	def test_each_category_gets_its_share(self):
		self.split_expense()
		totals = self.totals()
		self.assertEqual(totals[self.groceries], 800)
		self.assertEqual(totals[self.household], 200)

	def test_split_and_unsplit_spending_add_up_together(self):
		self.split_expense()
		make_transaction("Expense", 500, self.account, tracker=self.tracker, category=self.groceries)
		self.assertEqual(self.totals()[self.groceries], 1300)

	def test_a_split_rolls_up_into_a_parent_category(self):
		parent = make_category(self.tracker, category_type="Expense", is_group=1)
		child = make_category(self.tracker, category_type="Expense", parent_category=parent.name)
		self.split_expense(shares=((child.name, 600), (self.household, 400)))

		rolled = {
			row["category"]: row["total"] for row in categories_service.get_category_totals(self.tracker)
		}
		self.assertEqual(rolled[parent.name], 600, "a group totals its leaves, splits included")

	def test_a_refund_split_nets_off_each_category(self):
		self.split_expense()
		make_transaction("Refund", 100, self.account, tracker=self.tracker, category=self.groceries)
		self.assertEqual(self.totals()[self.groceries], 700)


class TestSplitsReachBudgets(SplitFixture):
	def test_a_budget_counts_a_split_bill(self):
		"""Budgets measure through `get_net_spend_by_date`, so this is the same rule again."""
		budget = make_budget(self.tracker, category=self.groceries, budget_amount=1000)
		self.split_expense()
		measured = budgets_service.measure(budget.name)
		self.assertEqual(measured.spent, 800)

	def test_a_whole_tracker_budget_counts_every_share(self):
		budget = make_budget(self.tracker, budget_amount=5000)
		self.split_expense()
		self.assertEqual(budgets_service.measure(budget.name).spent, 1000)


class TestSplitValidation(SplitFixture):
	def draft(self, shares, amount=1000, **kwargs):
		return make_transaction(
			"Expense",
			amount,
			self.account,
			submit=False,
			tracker=self.tracker,
			splits=[{"category": c, "amount": a} for c, a in shares],
			**kwargs,
		)

	def test_splits_must_add_up_to_the_amount(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(((self.groceries, 800), (self.household, 100)))

	def test_a_split_of_zero_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(((self.groceries, 1000), (self.household, 0)))

	def test_a_group_category_cannot_be_split_to(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		with self.assertRaises(frappe.ValidationError):
			self.draft(((group.name, 1000),))

	def test_a_split_on_the_wrong_side_of_the_books_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(((self.salary, 1000),))

	def test_a_category_from_another_tracker_is_refused(self):
		outsider = make_category(make_tracker().name, category_type="Expense")
		with self.assertRaises(frappe.ValidationError):
			self.draft(((outsider.name, 1000),))

	def test_a_transfer_cannot_be_split(self):
		"""An account-to-account movement touches no category, so there is nothing to split."""
		destination = make_account(self.tracker).name
		with self.assertRaises(frappe.ValidationError):
			make_transaction(
				"Transfer",
				1000,
				self.account,
				submit=False,
				tracker=self.tracker,
				destination_account=destination,
				splits=[{"category": self.groceries, "amount": 1000}],
			)

	def test_one_split_is_allowed_and_behaves_like_no_split(self):
		transaction = self.split_expense(shares=((self.groceries, 1000),))
		self.assertEqual(len(gl_rows(transaction.journal_entry, include_cancelled=False)), 2)

	def test_an_unsplit_transaction_still_requires_its_category(self):
		with self.assertRaises(frappe.ValidationError):
			make_transaction("Expense", 100, self.account, submit=False, tracker=self.tracker).submit()
