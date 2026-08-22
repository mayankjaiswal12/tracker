# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Ticking an account off against a statement.

Nothing here moves money, and that is the property most worth testing: reconciling changes
two flags and must leave every balance exactly where it was. If the difference does not close,
the answer is a missing transaction, not an adjustment — so there is no adjustment to test.
"""

import frappe

from moneytracker.money_tracker.services import balances, reconciliation
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	posting_date,
)


class ReconciliationFixture(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.bank = make_account(self.tracker, account_type="Bank").name
		self.savings = make_account(self.tracker, account_type="Savings").name
		self.card = make_account(self.tracker, account_type="Credit Card").name
		self.category = make_category(self.tracker, category_type="Expense").name
		self.income = make_category(self.tracker, category_type="Income").name

	def spend(self, amount=100, **kwargs):
		return make_transaction(
			"Expense", amount, self.bank, tracker=self.tracker, category=self.category, **kwargs
		)


class TestUnclearedItems(ReconciliationFixture):
	def test_a_fresh_account_has_everything_uncleared(self):
		self.spend(100)
		self.spend(250)
		result = reconciliation.get_reconciliation(self.bank)
		self.assertEqual(result["uncleared_count"], 2)
		self.assertEqual(result["cleared_balance"], 0)

	def test_cleared_plus_uncleared_is_always_the_book_balance(self):
		self.spend(100)
		self.spend(250)
		result = reconciliation.get_reconciliation(self.bank)
		self.assertEqual(result["cleared_balance"] + result["uncleared_total"], result["book_balance"])

	def test_the_book_balance_is_the_one_everything_else_shows(self):
		"""Taken from `balances`, not recomputed, so this screen cannot disagree with the dashboard."""
		self.spend(400)
		self.assertEqual(
			reconciliation.get_reconciliation(self.bank)["book_balance"],
			balances.get_account_balance(self.bank),
		)

	def test_both_ends_of_a_transfer_appear_on_their_own_account(self):
		"""And with opposite signs, read from the ledger rather than from the type."""
		make_transaction("Transfer", 1000, self.bank, tracker=self.tracker, destination_account=self.savings)
		out = reconciliation.get_reconciliation(self.bank)["uncleared"][0]["effect"]
		into = reconciliation.get_reconciliation(self.savings)["uncleared"][0]["effect"]
		self.assertEqual(out, -1000)
		self.assertEqual(into, 1000)

	def test_a_liability_account_is_reported_in_its_own_direction(self):
		make_transaction("Expense", 500, self.card, tracker=self.tracker, category=self.category)
		self.assertEqual(reconciliation.get_reconciliation(self.card)["uncleared"][0]["effect"], 500)

	def test_a_draft_is_not_uncleared_because_it_is_not_anywhere(self):
		self.spend(100, submit=False)
		self.assertEqual(reconciliation.get_reconciliation(self.bank)["uncleared_count"], 0)

	def test_as_of_excludes_later_transactions(self):
		self.spend(100)
		result = reconciliation.get_reconciliation(self.bank, as_of="1999-12-31")
		self.assertEqual(result["uncleared_count"], 0)
		self.assertEqual(result["book_balance"], 0)


class TestMarkingOff(ReconciliationFixture):
	def test_ticking_one_off_moves_it_into_cleared(self):
		first, second = self.spend(100), self.spend(250)
		reconciliation.mark_reconciled([first.name])

		result = reconciliation.get_reconciliation(self.bank)
		self.assertEqual(result["cleared_balance"], -100)
		self.assertEqual(result["uncleared_count"], 1)
		self.assertEqual(result["uncleared"][0]["transaction"], second.name)

	def test_it_changes_no_money(self):
		"""The whole point. Two flags, and every balance where it was."""
		transaction = self.spend(100)
		before = balances.get_account_balance(self.bank)
		reconciliation.mark_reconciled([transaction.name])
		self.assertEqual(balances.get_account_balance(self.bank), before)

	def test_the_cleared_date_defaults_to_the_transaction_date(self):
		transaction = self.spend(100)
		reconciliation.mark_reconciled([transaction.name])
		self.assertEqual(
			frappe.db.get_value("Transaction", transaction.name, "cleared_date"),
			frappe.utils.getdate(transaction.date),
		)

	def test_a_later_cleared_date_is_kept(self):
		"""A cheque that took a fortnight."""
		transaction = self.spend(100)
		later = frappe.utils.add_days(posting_date(), 14)
		reconciliation.mark_reconciled([transaction.name], cleared_date=later)
		self.assertEqual(
			frappe.db.get_value("Transaction", transaction.name, "cleared_date"),
			frappe.utils.getdate(later),
		)

	def test_unticking_puts_it_back(self):
		transaction = self.spend(100)
		reconciliation.mark_reconciled([transaction.name])
		reconciliation.mark_reconciled([transaction.name], reconciled=False)

		result = reconciliation.get_reconciliation(self.bank)
		self.assertEqual(result["cleared_balance"], 0)
		self.assertIsNone(frappe.db.get_value("Transaction", transaction.name, "cleared_date"))

	def test_ticking_twice_changes_nothing_the_second_time(self):
		transaction = self.spend(100)
		self.assertEqual(reconciliation.mark_reconciled([transaction.name]), 1)
		self.assertEqual(reconciliation.mark_reconciled([transaction.name]), 0)

	def test_a_draft_cannot_be_reconciled(self):
		draft = self.spend(100, submit=False)
		with self.assertRaises(frappe.ValidationError):
			reconciliation.mark_reconciled([draft.name])


class TestAgainstAStatement(ReconciliationFixture):
	def test_a_matching_statement_reconciles(self):
		transaction = self.spend(100)
		reconciliation.mark_reconciled([transaction.name])
		result = reconciliation.get_reconciliation(self.bank, statement_balance=-100)
		self.assertEqual(result["difference"], 0)
		self.assertTrue(result["reconciled"])

	def test_a_statement_that_disagrees_reports_the_gap(self):
		transaction = self.spend(100)
		reconciliation.mark_reconciled([transaction.name])
		result = reconciliation.get_reconciliation(self.bank, statement_balance=-600)
		self.assertEqual(result["difference"], -500)
		self.assertFalse(result["reconciled"])

	def test_no_statement_reports_no_difference_rather_than_zero(self):
		"""Zero would read as "reconciled" to anything checking the number."""
		self.spend(100)
		result = reconciliation.get_reconciliation(self.bank)
		self.assertIsNone(result["difference"])
		self.assertFalse(result["reconciled"])


class TestReconciliationFields(ReconciliationFixture):
	def test_a_submitted_transaction_can_still_be_reconciled(self):
		"""Both fields carry `allow_on_submit`: the statement arrives weeks later."""
		transaction = self.spend(100)
		transaction.is_reconciled = 1
		transaction.save(ignore_permissions=True)
		self.assertTrue(frappe.db.get_value("Transaction", transaction.name, "is_reconciled"))

	def test_a_cleared_date_before_the_transaction_is_refused(self):
		transaction = self.spend(100)
		transaction.is_reconciled = 1
		transaction.cleared_date = frappe.utils.add_days(posting_date(), -5)
		with self.assertRaises(frappe.ValidationError):
			transaction.save(ignore_permissions=True)

	def test_unticking_clears_the_date(self):
		transaction = self.spend(100, is_reconciled=1, cleared_date=posting_date(), submit=False)
		transaction.is_reconciled = 0
		transaction.save(ignore_permissions=True)
		self.assertIsNone(transaction.cleared_date)
