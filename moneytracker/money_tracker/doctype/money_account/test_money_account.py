# Copyright (c) 2026, Mayank Jaiswal and Contributors
# See license.txt

"""Money Account: named per tracker, backed by a ledger account the user never picks."""

import frappe

from moneytracker.money_tracker.services import coa
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	unique,
)


class TestMoneyAccount(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.other_tracker = make_tracker().name

	def test_a_duplicate_name_on_one_tracker_is_refused(self):
		name = unique("Cash")
		make_account(self.tracker, account_name=name)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_account(self.tracker, account_name=name)
		self.assertIn("already exists on this tracker", str(caught.exception))

	def test_the_same_name_on_another_tracker_is_fine(self):
		"""Two people both having a "Cash" account is normal — which is why the DocType is
		named by hash and uniqueness is enforced per tracker, not by the primary key."""
		name = unique("Cash")
		first = make_account(self.tracker, account_name=name)
		second = make_account(self.other_tracker, account_name=name)

		self.assertNotEqual(first.name, second.name)
		# And they share one ERPNext account, which is exactly why balances filter by tracker.
		self.assertEqual(first.ledger_account, second.ledger_account)

	def test_a_ledger_account_is_created_without_being_asked_for(self):
		account = make_account(self.tracker, account_type="Bank")

		self.assertTrue(account.ledger_account)
		self.assertEqual(frappe.db.get_value("Account", account.ledger_account, "root_type"), "Asset")
		self.assertEqual(frappe.db.get_value("Account", account.ledger_account, "is_group"), 0)

	def test_a_credit_card_is_a_liability(self):
		card = make_account(self.tracker, account_type="Credit Card")

		self.assertEqual(frappe.db.get_value("Account", card.ledger_account, "root_type"), "Liability")
		# ERPNext has no "Credit Card" account_type — the card-ness lives on Money Account.
		self.assertNotEqual(
			frappe.db.get_value("Account", card.ledger_account, "account_type"), "Credit Card"
		)
		self.assertTrue(coa.is_liability("Credit Card"))

	def test_a_bank_and_a_card_land_under_different_parents(self):
		bank = make_account(self.tracker, account_type="Bank")
		card = make_account(self.tracker, account_type="Credit Card")

		self.assertNotEqual(
			frappe.db.get_value("Account", bank.ledger_account, "parent_account"),
			frappe.db.get_value("Account", card.ledger_account, "parent_account"),
		)

	def test_every_offered_account_type_can_be_posted_to(self):
		"""Nothing may be selectable in Desk that has no ledger mapping."""
		offered = frappe.get_meta("Money Account").get_field("account_type").options.split("\n")

		self.assertFalse([option for option in offered if option and option not in coa.ACCOUNT_TYPE_MAP])

	def test_the_tracker_and_currency_default_server_side(self):
		account = make_account(account_name=unique("Wallet"), account_type="Wallet")

		self.assertTrue(account.tracker)
		self.assertEqual(account.currency, frappe.db.get_single_value("Money Settings", "base_currency"))

	def test_an_account_in_use_cannot_be_deleted(self):
		account = make_account(self.tracker, account_type="Bank")
		category = make_category(self.tracker, category_type="Income")
		make_transaction("Income", 100, account.name, tracker=self.tracker, category=category.name)

		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.delete_doc("Money Account", account.name)
		self.assertIn("has transactions against it", str(caught.exception))

	def test_a_destination_account_in_use_cannot_be_deleted_either(self):
		source = make_account(self.tracker, account_type="Bank")
		destination = make_account(self.tracker, account_type="Bank")
		make_transaction(
			"Transfer", 100, source.name, tracker=self.tracker, destination_account=destination.name
		)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Money Account", destination.name)

	def test_an_unused_account_can_be_deleted(self):
		account = make_account(self.tracker, account_type="Cash")
		frappe.delete_doc("Money Account", account.name)

		self.assertFalse(frappe.db.exists("Money Account", account.name))
		# The ledger account deliberately survives — it may hold history from another tracker.
		self.assertTrue(frappe.db.exists("Account", account.ledger_account))
