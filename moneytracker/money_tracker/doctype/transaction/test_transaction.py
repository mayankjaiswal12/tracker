# Copyright (c) 2026, Mayank Jaiswal and Contributors
# See license.txt

"""Controller rules, before anything reaches the ledger.

Posting, cancellation and reversal live in `moneytracker/tests/test_posting_engine.py`;
this file is about what `validate` accepts and what it quietly fixes.
"""

import frappe
from frappe.utils import flt

from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
)


class TestTransaction(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.sbi = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name

	def draft(self, transaction_type="Expense", amount=100, account=None, **kwargs):
		kwargs.setdefault("category", self.food if transaction_type not in ("Transfer",) else None)
		return make_transaction(
			transaction_type,
			amount,
			account or self.bank,
			tracker=self.tracker,
			submit=False,
			**kwargs,
		)

	def test_zero_amount_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.draft(amount=0)
		self.assertIn("greater than zero", str(caught.exception))

	def test_a_negative_amount_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(amount=-500)

	def test_a_transfer_needs_a_destination(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.draft("Transfer", category=None)
		self.assertIn("Destination Account is required", str(caught.exception))

	def test_a_credit_card_payment_needs_a_destination(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft("Credit Card Payment", category=None)

	def test_a_transfer_drops_a_stale_category(self):
		"""Retyping a saved Expense into a Transfer must not leave the category behind, or a
		movement between two accounts would still reach the P&L."""
		transaction = self.draft("Transfer", destination_account=self.sbi, category=self.food)
		self.assertIsNone(transaction.category)

	def test_a_credit_card_payment_drops_a_stale_category(self):
		transaction = self.draft("Credit Card Payment", destination_account=self.card, category=self.food)
		self.assertIsNone(transaction.category)

	def test_an_expense_drops_a_stale_destination(self):
		transaction = self.draft("Expense", destination_account=self.sbi)
		self.assertIsNone(transaction.destination_account)

	def test_the_tracker_company_and_currency_are_filled_server_side(self):
		"""They are `reqd` with no default, so Desk asks for them — the API path does not."""
		transaction = make_transaction("Expense", 100, self.bank, category=self.food, submit=False)

		self.assertTrue(transaction.tracker)
		self.assertEqual(transaction.company, self.company)
		self.assertEqual(transaction.currency, frappe.db.get_value("Money Account", self.bank, "currency"))

	def test_the_base_amount_matches_in_the_base_currency(self):
		transaction = self.draft(amount=750)

		self.assertEqual(flt(transaction.exchange_rate), 1.0)
		self.assertMoneyEqual(transaction.base_amount, 750)

	def test_a_draft_can_be_deleted(self):
		"""Only *posted* transactions are protected; an unsubmitted one is not history yet."""
		transaction = self.draft(amount=42)
		frappe.delete_doc("Transaction", transaction.name)

		self.assertFalse(frappe.db.exists("Transaction", transaction.name))

	def test_a_draft_writes_nothing_to_the_ledger(self):
		transaction = self.draft(amount=60)

		self.assertFalse(transaction.journal_entry)
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": transaction.name}), 0)
