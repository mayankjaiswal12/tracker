# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""A charge taken on top of a movement between accounts.

The leg shapes are asserted without a database in `test_strategies.py`. What matters here is
the consequence: a fee is the **one** part of a transfer that reaches expense, and it has to
reach it everywhere — the ledger, the category roll-up and every budget — or it is money that
left the account and appears in none of the places spending is counted.
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
)


class FeeFixture(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.source = make_account(self.tracker, account_type="Bank").name
		self.destination = make_account(self.tracker, account_type="Savings").name
		self.card = make_account(self.tracker, account_type="Credit Card").name
		self.charges = make_category(self.tracker, category_type="Expense").name

	def transfer(self, amount=10000, fee=50, fee_category=None, submit=True, **kwargs):
		return make_transaction(
			"Transfer",
			amount,
			self.source,
			submit=submit,
			tracker=self.tracker,
			destination_account=kwargs.pop("destination_account", self.destination),
			fee_amount=fee,
			fee_category=(self.charges if fee_category is None else fee_category) if fee else None,
			**kwargs,
		)


class TestFeePosting(FeeFixture):
	def test_the_source_pays_the_amount_plus_the_fee(self):
		rows = gl_rows(self.transfer().journal_entry, include_cancelled=False)
		self.assertEqual(len(rows), 3)
		self.assertEqual(sum(r.credit for r in rows), 10050)
		self.assertEqual(sum(r.debit for r in rows), 10050)

	def test_the_destination_receives_the_amount_untouched(self):
		transaction = self.transfer()
		ledger = frappe.db.get_value("Money Account", self.destination, "ledger_account")
		row = next(
			r for r in gl_rows(transaction.journal_entry, include_cancelled=False) if r.account == ledger
		)
		self.assertEqual(row.debit, 10000)

	def test_a_card_payment_can_carry_one_too(self):
		transaction = make_transaction(
			"Credit Card Payment",
			1000,
			self.source,
			tracker=self.tracker,
			destination_account=self.card,
			fee_amount=20,
			fee_category=self.charges,
		)
		self.assertEqual(len(gl_rows(transaction.journal_entry, include_cancelled=False)), 3)

	def test_the_fee_is_stamped_in_base_currency(self):
		self.assertEqual(self.transfer().fee_base_amount, 50)

	def test_no_fee_posts_the_plain_two_legged_movement(self):
		transaction = self.transfer(fee=0)
		self.assertEqual(len(gl_rows(transaction.journal_entry, include_cancelled=False)), 2)

	def test_cancelling_reverses_the_fee_with_everything_else(self):
		transaction = self.transfer()
		transaction.cancel()
		rows = gl_rows(transaction.journal_entry, include_cancelled=True)
		self.assertEqual(sum(r.debit for r in rows), sum(r.credit for r in rows))


class TestFeeReachesSpending(FeeFixture):
	"""The invariant, restated: the *movement* is balance-sheet only. The fee is not."""

	def test_the_fee_lands_in_the_category_roll_up(self):
		self.transfer()
		totals = {
			row["category"]: row["total"] for row in categories_service.get_category_totals(self.tracker)
		}
		self.assertEqual(totals[self.charges], 50)

	def test_the_movement_itself_still_reaches_no_category(self):
		"""10,000 moved; only the 50 is spending."""
		self.transfer()
		totals = {
			row["category"]: row["total"] for row in categories_service.get_category_totals(self.tracker)
		}
		self.assertEqual(sum(totals.values()), 50)

	def test_a_budget_on_the_fee_category_counts_it(self):
		budget = make_budget(self.tracker, category=self.charges, budget_amount=500)
		self.transfer()
		self.assertEqual(budgets_service.measure(budget.name).spent, 50)

	def test_a_whole_tracker_budget_counts_the_fee_and_not_the_movement(self):
		budget = make_budget(self.tracker, budget_amount=5000)
		self.transfer()
		self.assertEqual(budgets_service.measure(budget.name).spent, 50)


class TestFeeValidation(FeeFixture):
	def test_a_fee_needs_a_category(self):
		with self.assertRaises(frappe.ValidationError):
			make_transaction(
				"Transfer",
				100,
				self.source,
				submit=False,
				tracker=self.tracker,
				destination_account=self.destination,
				fee_amount=5,
			)

	def test_an_income_category_is_refused(self):
		income = make_category(self.tracker, category_type="Income")
		with self.assertRaises(frappe.ValidationError):
			self.transfer(submit=False, fee_category=income.name)

	def test_a_group_category_is_refused(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		with self.assertRaises(frappe.ValidationError):
			self.transfer(submit=False, fee_category=group.name)

	def test_a_category_from_another_tracker_is_refused(self):
		outsider = make_category(make_tracker().name, category_type="Expense")
		with self.assertRaises(frappe.ValidationError):
			self.transfer(submit=False, fee_category=outsider.name)

	def test_an_expense_cannot_carry_a_fee(self):
		"""Every other type has a category of its own; a charge on an expense is part of it."""
		category = make_category(self.tracker, category_type="Expense")
		with self.assertRaises(frappe.ValidationError):
			make_transaction(
				"Expense",
				100,
				self.source,
				submit=False,
				tracker=self.tracker,
				category=category.name,
				fee_amount=5,
				fee_category=self.charges,
			)

	def test_a_zero_fee_clears_the_category_rather_than_keeping_a_stray_one(self):
		transaction = self.transfer(submit=False, fee=0, fee_category=self.charges)
		self.assertIsNone(transaction.fee_category)

	def test_a_negative_fee_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.transfer(submit=False, fee=-10)
