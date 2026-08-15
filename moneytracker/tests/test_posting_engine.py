# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The engine end to end: a Transaction becomes a submitted, balanced Journal Entry.

`TestSubmitRegressionGuard` is deliberately the narrowest test in the app and exists on its
own — if it fails, nothing else here is worth reading.
"""

import frappe
from frappe.utils import flt

from moneytracker.money_tracker.posting import engine
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	gl_rows,
	je_of,
	ledger_movement,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	money_setting,
)


class LedgerFixture(MoneyTrackerTestCase):
	"""One tracker with the accounts and categories every posting test needs."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.sbi = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

	def expense(self, amount=1000, account=None, **kwargs):
		return make_transaction(
			"Expense", amount, account or self.bank, tracker=self.tracker, category=self.food, **kwargs
		)

	def income(self, amount=50000, **kwargs):
		return make_transaction(
			"Income", amount, self.bank, tracker=self.tracker, category=self.salary, **kwargs
		)

	def transfer(self, amount=8000, **kwargs):
		return make_transaction(
			"Transfer", amount, self.bank, tracker=self.tracker, destination_account=self.sbi, **kwargs
		)

	def card_payment(self, amount=1000, **kwargs):
		return make_transaction(
			"Credit Card Payment",
			amount,
			self.bank,
			tracker=self.tracker,
			destination_account=self.card,
			**kwargs,
		)

	def refund(self, amount=500, **kwargs):
		return make_transaction(
			"Refund", amount, self.bank, tracker=self.tracker, category=self.food, **kwargs
		)

	def assertBalancedJournalEntry(self, transaction):
		journal_entry = je_of(transaction)
		self.assertEqual(journal_entry.docstatus, 1)

		# Spec §76, checked on both sides of the bridge: what the engine wrote, and what
		# ERPNext derived from it.
		self.assertMoneyEqual(
			sum(flt(row.debit) for row in journal_entry.accounts),
			sum(flt(row.credit) for row in journal_entry.accounts),
		)
		rows = gl_rows(journal_entry.name, include_cancelled=False)
		self.assertTrue(rows)
		self.assertMoneyEqual(sum(flt(row.debit) for row in rows), sum(flt(row.credit) for row in rows))
		return journal_entry


class TestSubmitRegressionGuard(LedgerFixture):
	def test_a_transaction_can_be_submitted_at_all(self):
		"""Guards `patches/v1_0/allow_transaction_reference.py`.

		The engine stamps every Journal Entry Account row with reference_type="Transaction",
		but ERPNext ships that field as a fixed Select. Without the Property Setter that
		widens it, Frappe's select validation rejects every row and all five strategies fail
		identically with "Reference Type cannot be Transaction" — i.e. nothing posts at all.
		"""
		transaction = self.expense(amount=1000)

		self.assertEqual(transaction.docstatus, 1)
		self.assertTrue(transaction.journal_entry)


class TestPostingPerType(LedgerFixture):
	def test_expense_posts_balanced(self):
		self.assertBalancedJournalEntry(self.expense(amount=2000))

	def test_income_posts_balanced(self):
		self.assertBalancedJournalEntry(self.income(amount=50000))

	def test_transfer_posts_balanced(self):
		self.assertBalancedJournalEntry(self.transfer(amount=8000))

	def test_credit_card_payment_posts_balanced(self):
		self.assertBalancedJournalEntry(self.card_payment(amount=1000))

	def test_refund_posts_balanced(self):
		self.assertBalancedJournalEntry(self.refund(amount=500))

	def test_voucher_types_map_as_intended(self):
		"""ERPNext's voucher_type is a fixed Select; the real semantics stay on Transaction."""
		self.assertEqual(je_of(self.expense()).voucher_type, "Journal Entry")
		self.assertEqual(je_of(self.transfer()).voucher_type, "Contra Entry")
		self.assertEqual(je_of(self.card_payment()).voucher_type, "Credit Card Entry")

	def test_every_row_links_back_to_the_transaction(self):
		transaction = self.expense(amount=1234)
		for row in je_of(transaction).accounts:
			self.assertEqual(row.reference_type, "Transaction")
			self.assertEqual(row.reference_name, transaction.name)

	def test_every_gl_row_carries_the_tracker_dimension(self):
		"""Without this the balance and report filters silently match nothing."""
		transaction = self.expense(amount=777)
		rows = gl_rows(transaction.journal_entry)
		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(row.tracker, self.tracker)

	def test_an_unimplemented_type_refuses_on_submit(self):
		transaction = make_transaction(
			"Dividend", 100, self.bank, tracker=self.tracker, category=self.salary, submit=False
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			transaction.submit()
		self.assertIn("not implemented yet", str(caught.exception))

	def test_posting_is_idempotent(self):
		transaction = self.expense(amount=321)
		self.assertEqual(engine.post(transaction), transaction.journal_entry)
		self.assertEqual(frappe.db.count("Journal Entry Account", {"reference_name": transaction.name}), 2)

	def test_the_remark_names_the_transaction(self):
		transaction = self.expense(amount=99, merchant="Cafe", notes="lunch")
		self.assertEqual(je_of(transaction).user_remark, "Expense | Cafe | lunch")


class TestCancellation(LedgerFixture):
	"""Spec §80: cancelling reverses the ledger, it does not erase it."""

	def test_cancelling_reverses_without_deleting(self):
		transaction = self.expense(amount=2000)
		journal_entry = transaction.journal_entry
		bank_ledger = frappe.db.get_value("Money Account", self.bank, "ledger_account")
		before = ledger_movement(bank_ledger, self.tracker)

		transaction.cancel()

		self.assertEqual(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"), 2)
		rows = gl_rows(journal_entry)
		self.assertEqual(len(rows), 4, "2 original rows + 2 reversing rows")
		self.assertTrue(all(row.is_cancelled for row in rows))
		self.assertMoneyEqual(sum(flt(row.debit) for row in rows), sum(flt(row.credit) for row in rows))
		# The live movement returns to where it was: the cancelled rows drop out entirely.
		self.assertMoneyEqual(ledger_movement(bank_ledger, self.tracker), before + 2000)

	def test_the_balance_cache_is_refreshed_on_cancel(self):
		opening = flt(frappe.db.get_value("Money Account", self.bank, "current_balance"))
		transaction = self.expense(amount=1500)
		self.assertMoneyEqual(
			frappe.db.get_value("Money Account", self.bank, "current_balance"), opening - 1500
		)

		transaction.cancel()
		self.assertMoneyEqual(frappe.db.get_value("Money Account", self.bank, "current_balance"), opening)

	def test_a_posted_transaction_cannot_be_deleted(self):
		transaction = self.expense(amount=250)
		transaction.cancel()

		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.delete_doc("Transaction", transaction.name)
		self.assertIn("Cannot delete a posted transaction", str(caught.exception))


class TestOverdraft(LedgerFixture):
	"""`check_sufficient_balance` is a no-op while Money Settings allows negatives.

	The shipped default stays permissive — a personal finance app should record what
	happened. These tests flip it inside the test so the code path itself is covered.
	"""

	def test_permissive_by_default(self):
		self.assertTrue(frappe.db.get_single_value("Money Settings", "allow_negative_balance"))
		self.expense(amount=999999)  # does not throw

	def test_overdraft_is_blocked_when_negatives_are_disallowed(self):
		with money_setting(allow_negative_balance=0):
			empty = make_account(self.tracker, account_type="Bank").name
			transaction = make_transaction(
				"Expense", 100, empty, tracker=self.tracker, category=self.food, submit=False
			)
			with self.assertRaises(frappe.ValidationError) as caught:
				transaction.submit()
			self.assertIn("Insufficient balance", str(caught.exception))
			self.assertEqual(frappe.db.get_value("Transaction", transaction.name, "docstatus"), 0)

	def test_income_and_refund_are_exempt(self):
		with money_setting(allow_negative_balance=0):
			empty = make_account(self.tracker, account_type="Bank").name
			make_transaction("Income", 100, empty, tracker=self.tracker, category=self.salary)
			make_transaction("Refund", 100, empty, tracker=self.tracker, category=self.food)

	def test_a_credit_card_is_exempt(self):
		"""A card has no balance to run out of — spending on it is what creates the debt."""
		with money_setting(allow_negative_balance=0):
			card = make_account(self.tracker, account_type="Credit Card").name
			make_transaction("Expense", 5000, card, tracker=self.tracker, category=self.food)

	def test_the_setting_is_restored_afterwards(self):
		with money_setting(allow_negative_balance=0):
			pass
		self.assertTrue(frappe.db.get_single_value("Money Settings", "allow_negative_balance"))


class TestReverse(LedgerFixture):
	"""`Transaction.reverse()` — implemented but, until now, never exercised.

	Unlike cancelling, a reversal leaves the original on the books and posts a correcting
	entry beside it.
	"""

	def test_reversing_an_expense_books_a_refund(self):
		transaction = self.expense(amount=1200)
		reversal = frappe.get_doc("Transaction", transaction.reverse())

		self.assertEqual(reversal.transaction_type, "Refund")
		self.assertEqual(reversal.reversal_of, transaction.name)
		self.assertEqual(reversal.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Transaction", transaction.name, "docstatus"), 1)

	def test_a_reversal_nets_the_ledger_to_zero(self):
		bank_ledger = frappe.db.get_value("Money Account", self.bank, "ledger_account")
		before = ledger_movement(bank_ledger, self.tracker)

		transaction = self.expense(amount=1200)
		transaction.reverse()

		self.assertMoneyEqual(ledger_movement(bank_ledger, self.tracker), before)
		# Both vouchers survive — that is the difference from cancelling.
		self.assertEqual(frappe.db.count("Transaction", {"reversal_of": transaction.name}), 1)

	def test_reversing_a_refund_books_an_expense(self):
		reversal = frappe.get_doc("Transaction", self.refund(amount=300).reverse())
		self.assertEqual(reversal.transaction_type, "Expense")

	def test_reversing_a_transfer_swaps_the_accounts(self):
		transaction = self.transfer(amount=400)
		reversal = frappe.get_doc("Transaction", transaction.reverse())

		self.assertEqual(reversal.transaction_type, "Transfer")
		self.assertEqual(reversal.account, transaction.destination_account)
		self.assertEqual(reversal.destination_account, transaction.account)

	def test_reversing_a_card_payment_books_a_transfer_back(self):
		"""Undoing a card payment is Dr bank / Cr card, which is not a card payment.

		Swapping the accounts and keeping the type would produce a card payment whose
		destination is a bank — refused, correctly, by the strategy. It is a settlement
		between two balance-sheet accounts, so it reverses as a Transfer.
		"""
		card_ledger = frappe.db.get_value("Money Account", self.card, "ledger_account")
		before = ledger_movement(card_ledger, self.tracker)

		transaction = self.card_payment(amount=200)
		reversal = frappe.get_doc("Transaction", transaction.reverse())

		self.assertEqual(reversal.transaction_type, "Transfer")
		self.assertEqual(reversal.account, transaction.destination_account)
		self.assertEqual(reversal.destination_account, transaction.account)
		self.assertMoneyEqual(ledger_movement(card_ledger, self.tracker), before)

	def test_reversing_an_income_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.income(amount=700).reverse()
		self.assertIn("not supported yet", str(caught.exception))

	def test_a_draft_cannot_be_reversed(self):
		transaction = make_transaction(
			"Expense", 100, self.bank, tracker=self.tracker, category=self.food, submit=False
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			transaction.reverse()
		self.assertIn("Only a submitted transaction", str(caught.exception))

	def test_reversing_twice_is_refused(self):
		transaction = self.expense(amount=650)
		transaction.reverse()
		with self.assertRaises(frappe.ValidationError) as caught:
			transaction.reverse()
		self.assertIn("already been reversed", str(caught.exception))
