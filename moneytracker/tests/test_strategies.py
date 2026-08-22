# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The accounting rules, stated as assertions.

Strategies are pure — they receive a PostingContext and return Legs, touching no database —
so these run without creating a single document. That is the point of the layering: the
rules that decide what is debited and what is credited are checkable in isolation.
"""

import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import frappe

from moneytracker.money_tracker.posting import engine, strategies
from moneytracker.money_tracker.posting.context import PostingContext
from moneytracker.money_tracker.posting.leg import Leg


def fake_account(name="Bank", account_type="Bank"):
	return SimpleNamespace(
		name=f"hash-{name}",
		account_name=name,
		account_type=account_type,
		ledger_account=f"{name} - T",
	)


def fake_category(name="Food", category_type="Expense", ledger_account=None):
	return SimpleNamespace(
		name=f"hash-{name}",
		category_name=name,
		category_type=category_type,
		ledger_account=f"{name} - T" if ledger_account is None else ledger_account,
	)


def build_context(
	amount=1000, account=None, category=None, destination=None, transaction_type="Expense", splits=None
):
	"""A PostingContext with its lookups pre-resolved instead of read from the database.

	`__new__` rather than `__init__` so `require_category` / `require_destination` — the
	guard rails actually under test — stay the real implementations.
	"""
	ctx = PostingContext.__new__(PostingContext)
	ctx.transaction = SimpleNamespace(transaction_type=transaction_type)
	ctx.amount = amount
	ctx.currency = "INR"
	ctx.account = account or fake_account()
	ctx.destination_account = destination
	ctx.category = category
	# A split transaction carries no single category; these hold the breakdown instead.
	ctx.splits = [frappe._dict(category=category, amount=amount) for category, amount in (splits or [])]
	return ctx


class TestLeg(unittest.TestCase):
	def test_leg_cannot_carry_both_sides(self):
		with self.assertRaises(ValueError):
			Leg(ledger_account="Bank - T", debit=100, credit=100)

	def test_leg_cannot_be_empty(self):
		with self.assertRaises(ValueError):
			Leg(ledger_account="Bank - T")

	def test_leg_is_immutable(self):
		leg = Leg(ledger_account="Bank - T", debit=100)
		with self.assertRaises(FrozenInstanceError):
			leg.debit = 200


class TestValidateBalanced(unittest.TestCase):
	"""Spec §76: no journal entry may leave the engine unbalanced."""

	def test_balanced_legs_return_the_debit_total(self):
		legs = [Leg("Food - T", debit=1000), Leg("Bank - T", credit=1000)]
		self.assertEqual(engine.validate_balanced(legs), 1000)

	def test_unbalanced_legs_throw(self):
		legs = [Leg("Food - T", debit=1000), Leg("Bank - T", credit=999)]
		with self.assertRaises(frappe.ValidationError) as caught:
			engine.validate_balanced(legs)
		self.assertIn("unbalanced", str(caught.exception))

	def test_many_legs_may_balance_in_aggregate(self):
		legs = [
			Leg("Food - T", debit=600),
			Leg("Fuel - T", debit=400),
			Leg("Bank - T", credit=1000),
		]
		self.assertEqual(engine.validate_balanced(legs), 1000)

	def test_no_legs_throws(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			engine.validate_balanced([])
		self.assertIn("no amount", str(caught.exception))


class TestStrategyRegistry(unittest.TestCase):
	def test_every_implemented_type_resolves(self):
		for transaction_type in ("Expense", "Income", "Transfer", "Credit Card Payment", "Refund"):
			self.assertTrue(callable(strategies.get_strategy(transaction_type)))

	def test_planned_types_refuse_clearly(self):
		"""A declared-but-unbuilt type must say so, not die on a KeyError."""
		for transaction_type in strategies.PLANNED:
			with self.assertRaises(frappe.ValidationError) as caught:
				strategies.get_strategy(transaction_type)
			self.assertIn("not implemented yet", str(caught.exception))

	def test_unknown_type_refuses(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.get_strategy("Teleportation")
		self.assertIn("Unknown Transaction Type", str(caught.exception))

	def test_planned_and_implemented_do_not_overlap(self):
		self.assertFalse(set(strategies.PLANNED) & set(strategies.STRATEGIES))

	def test_every_implemented_type_has_a_voucher_type(self):
		for transaction_type in strategies.STRATEGIES:
			self.assertIn(transaction_type, engine.VOUCHER_TYPE_MAP)

	def test_declared_transaction_types_are_all_accounted_for(self):
		"""Nothing may be offered in the DocType that neither posts nor refuses cleanly."""
		declared = set(frappe.get_meta("Transaction").get_field("transaction_type").options.split("\n"))
		self.assertFalse(declared - set(strategies.STRATEGIES) - set(strategies.PLANNED))


class TestExpenseStrategy(unittest.TestCase):
	def test_debits_the_category_and_credits_the_account(self):
		ctx = build_context(amount=1000, account=fake_account("Bank"), category=fake_category("Food"))
		legs = strategies.STRATEGIES["Expense"](ctx)

		self.assertEqual(
			[(leg.ledger_account, leg.debit, leg.credit) for leg in legs],
			[("Food - T", 1000, 0.0), ("Bank - T", 0.0, 1000)],
		)
		engine.validate_balanced(legs)

	def test_paying_by_card_credits_the_card(self):
		"""The card's liability grows instead of a bank balance shrinking."""
		ctx = build_context(account=fake_account("Card", "Credit Card"), category=fake_category("Food"))
		legs = strategies.STRATEGIES["Expense"](ctx)
		self.assertEqual(legs[1].ledger_account, "Card - T")
		self.assertEqual(legs[1].credit, 1000)

	def test_an_income_category_is_refused(self):
		ctx = build_context(category=fake_category("Salary", "Income"))
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Expense"](ctx)
		self.assertIn("Income category", str(caught.exception))

	def test_a_missing_category_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			strategies.STRATEGIES["Expense"](build_context(category=None))

	def test_a_category_without_a_ledger_account_is_refused(self):
		"""Group categories never get one, so they can never be posted against."""
		ctx = build_context(category=fake_category("Food", ledger_account=""))
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Expense"](ctx)
		self.assertIn("no ledger account", str(caught.exception))


class TestIncomeStrategy(unittest.TestCase):
	def test_debits_the_account_and_credits_the_category(self):
		ctx = build_context(
			amount=50000,
			account=fake_account("Bank"),
			category=fake_category("Salary", "Income"),
			transaction_type="Income",
		)
		legs = strategies.STRATEGIES["Income"](ctx)

		self.assertEqual(
			[(leg.ledger_account, leg.debit, leg.credit) for leg in legs],
			[("Bank - T", 50000, 0.0), ("Salary - T", 0.0, 50000)],
		)

	def test_an_expense_category_is_refused(self):
		ctx = build_context(category=fake_category("Food", "Expense"), transaction_type="Income")
		with self.assertRaises(frappe.ValidationError):
			strategies.STRATEGIES["Income"](ctx)


class TestRefundStrategy(unittest.TestCase):
	"""Spec §62: a refund is not income."""

	def test_credits_the_original_expense_category(self):
		ctx = build_context(
			amount=300,
			account=fake_account("Bank"),
			category=fake_category("Food", "Expense"),
			transaction_type="Refund",
		)
		legs = strategies.STRATEGIES["Refund"](ctx)

		self.assertEqual(
			[(leg.ledger_account, leg.debit, leg.credit) for leg in legs],
			[("Bank - T", 300, 0.0), ("Food - T", 0.0, 300)],
		)

	def test_an_income_category_is_refused(self):
		"""Booking a refund as income would overstate both income and expense."""
		ctx = build_context(category=fake_category("Salary", "Income"), transaction_type="Refund")
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Refund"](ctx)
		self.assertIn("Refund", str(caught.exception))


class TestTransferStrategy(unittest.TestCase):
	def test_debits_the_destination_and_credits_the_source(self):
		ctx = build_context(
			amount=8000,
			account=fake_account("Bank"),
			destination=fake_account("SBI"),
			transaction_type="Transfer",
		)
		legs = strategies.STRATEGIES["Transfer"](ctx)

		self.assertEqual(
			[(leg.ledger_account, leg.debit, leg.credit) for leg in legs],
			[("SBI - T", 8000, 0.0), ("Bank - T", 0.0, 8000)],
		)

	def test_both_legs_name_a_money_account(self):
		"""Both sides are real accounts, so both balances must be refreshed after posting."""
		ctx = build_context(
			account=fake_account("Bank"), destination=fake_account("SBI"), transaction_type="Transfer"
		)
		legs = strategies.STRATEGIES["Transfer"](ctx)
		self.assertTrue(all(leg.money_account for leg in legs))

	def test_a_missing_destination_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			strategies.STRATEGIES["Transfer"](build_context(transaction_type="Transfer"))

	def test_transferring_to_itself_is_refused(self):
		account = fake_account("Bank")
		ctx = build_context(account=account, destination=account, transaction_type="Transfer")
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Transfer"](ctx)
		self.assertIn("must be different", str(caught.exception))


class TestCreditCardPaymentStrategy(unittest.TestCase):
	def test_debits_the_card_and_credits_the_funding_account(self):
		ctx = build_context(
			amount=1000,
			account=fake_account("Bank"),
			destination=fake_account("Card", "Credit Card"),
			transaction_type="Credit Card Payment",
		)
		legs = strategies.STRATEGIES["Credit Card Payment"](ctx)

		self.assertEqual(
			[(leg.ledger_account, leg.debit, leg.credit) for leg in legs],
			[("Card - T", 1000, 0.0), ("Bank - T", 0.0, 1000)],
		)

	def test_paying_into_a_bank_account_is_refused(self):
		ctx = build_context(
			account=fake_account("Bank"),
			destination=fake_account("SBI", "Bank"),
			transaction_type="Credit Card Payment",
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Credit Card Payment"](ctx)
		self.assertIn("not a liability", str(caught.exception))

	def test_paying_a_card_from_another_card_is_refused(self):
		ctx = build_context(
			account=fake_account("Card A", "Credit Card"),
			destination=fake_account("Card B", "Credit Card"),
			transaction_type="Credit Card Payment",
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			strategies.STRATEGIES["Credit Card Payment"](ctx)
		self.assertIn("another liability", str(caught.exception))


class TestSplitLegs(unittest.TestCase):
	"""One payment, several categories — and the engine none the wiser.

	The point of these is that `posting/engine.py` is not mentioned anywhere in them. Adding
	split posting was a strategy edit, which is the bargain the engine/strategy split was made
	for in the first place.
	"""

	def test_an_expense_debits_each_category_and_credits_the_account_once(self):
		legs = strategies.get_strategy("Expense")(
			build_context(
				amount=1000,
				splits=[(fake_category("Groceries"), 800), (fake_category("Household"), 200)],
			)
		)
		self.assertEqual(len(legs), 3)
		self.assertEqual(
			[(leg.ledger_account, leg.debit) for leg in legs if leg.debit],
			[("Groceries - T", 800), ("Household - T", 200)],
		)
		credits = [leg for leg in legs if leg.credit]
		self.assertEqual(len(credits), 1, "one payment left the account, so one credit")
		self.assertEqual(credits[0].credit, 1000)

	def test_an_income_credits_each_category_and_debits_the_account_once(self):
		legs = strategies.get_strategy("Income")(
			build_context(
				amount=5000,
				transaction_type="Income",
				splits=[
					(fake_category("Salary", "Income"), 4000),
					(fake_category("Bonus", "Income"), 1000),
				],
			)
		)
		self.assertEqual(len(legs), 3)
		self.assertEqual(len([leg for leg in legs if leg.debit]), 1)
		self.assertEqual(
			[(leg.ledger_account, leg.credit) for leg in legs if leg.credit],
			[("Salary - T", 4000), ("Bonus - T", 1000)],
		)

	def test_split_legs_balance(self):
		legs = strategies.get_strategy("Expense")(
			build_context(
				amount=999,
				splits=[
					(fake_category("A"), 333),
					(fake_category("B"), 333),
					(fake_category("C"), 333),
				],
			)
		)
		engine.validate_balanced(legs)

	def test_a_split_onto_the_wrong_side_of_the_books_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			strategies.get_strategy("Expense")(
				build_context(amount=100, splits=[(fake_category("Salary", "Income"), 100)])
			)

	def test_a_split_category_with_no_ledger_account_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			strategies.get_strategy("Expense")(
				build_context(amount=100, splits=[(fake_category("Food", ledger_account=""), 100)])
			)

	def test_no_splits_still_takes_the_single_category_path(self):
		legs = strategies.get_strategy("Expense")(build_context(amount=100, category=fake_category("Food")))
		self.assertEqual(len(legs), 2)
