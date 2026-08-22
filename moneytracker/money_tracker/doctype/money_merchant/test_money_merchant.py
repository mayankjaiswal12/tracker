# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""What a merchant refuses to save, what its defaults do, and what deleting one leaves behind."""

import frappe

from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_merchant,
	make_payment_method,
	make_tracker,
	make_transaction,
)


class TestMoneyMerchant(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name

	def test_it_is_named_by_series(self):
		self.assertTrue(make_merchant(self.tracker).name.startswith("MER-"))

	def test_a_name_is_unique_within_a_tracker(self):
		make_merchant(self.tracker, merchant_name="DMart")
		with self.assertRaises(frappe.ValidationError):
			make_merchant(self.tracker, merchant_name="DMart")

	def test_a_name_differing_only_in_case_is_a_duplicate(self):
		"""Splitting one shop's spending in two is the exact problem this doctype exists for."""
		make_merchant(self.tracker, merchant_name="Croma")
		with self.assertRaises(frappe.ValidationError):
			make_merchant(self.tracker, merchant_name="croma")

	def test_the_same_name_is_free_on_another_tracker(self):
		make_merchant(self.tracker, merchant_name="Reliance Fresh")
		self.assertTrue(make_merchant(make_tracker().name, merchant_name="Reliance Fresh").name)

	def test_surrounding_whitespace_is_trimmed(self):
		self.assertEqual(make_merchant(self.tracker, merchant_name="  Blinkit ").merchant_name, "Blinkit")

	def test_a_group_category_is_refused_as_a_default(self):
		"""Stricter than Money Budget, which measures a subtree. This value gets copied onto a
		transaction, and a transaction cannot post to a heading."""
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		with self.assertRaises(frappe.ValidationError):
			make_merchant(self.tracker, default_category=group.name)

	def test_a_default_category_from_another_tracker_is_refused(self):
		outsider = make_category(make_tracker().name, category_type="Expense")
		with self.assertRaises(frappe.ValidationError):
			make_merchant(self.tracker, default_category=outsider.name)

	def test_a_leaf_category_is_accepted_as_a_default(self):
		leaf = make_category(self.tracker, category_type="Expense")
		self.assertEqual(make_merchant(self.tracker, default_category=leaf.name).default_category, leaf.name)


class TestMerchantDefaults(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.groceries = make_category(self.tracker, category_type="Expense").name
		self.other = make_category(self.tracker, category_type="Expense").name
		self.method = make_payment_method().name
		self.dmart = make_merchant(
			self.tracker, default_category=self.groceries, default_payment_method=self.method
		)

	def test_a_blank_category_is_filled_from_the_merchant(self):
		txn = make_transaction(
			"Expense", 100, self.account, submit=False, tracker=self.tracker, merchant=self.dmart.name
		)
		self.assertEqual(txn.category, self.groceries)
		self.assertEqual(txn.payment_method, self.method)

	def test_a_category_typed_by_hand_always_wins(self):
		"""A default is a convenience on entry, not a rule."""
		txn = make_transaction(
			"Expense",
			100,
			self.account,
			submit=False,
			tracker=self.tracker,
			merchant=self.dmart.name,
			category=self.other,
		)
		self.assertEqual(txn.category, self.other)

	def test_editing_the_merchant_does_not_rewrite_what_is_saved(self):
		txn = make_transaction(
			"Expense", 100, self.account, submit=False, tracker=self.tracker, merchant=self.dmart.name
		)
		self.dmart.default_category = self.other
		self.dmart.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Transaction", txn.name, "category"), self.groceries)

	def test_a_transfer_takes_no_category_from_a_merchant(self):
		"""An account-to-account movement has no category by construction."""
		destination = make_account(self.tracker).name
		txn = make_transaction(
			"Transfer",
			100,
			self.account,
			submit=False,
			tracker=self.tracker,
			destination_account=destination,
			merchant=self.dmart.name,
		)
		self.assertIsNone(txn.category)

	def test_a_merchant_from_another_tracker_is_refused(self):
		outsider = make_merchant(make_tracker().name)
		with self.assertRaises(frappe.ValidationError):
			make_transaction(
				"Expense",
				100,
				self.account,
				submit=False,
				tracker=self.tracker,
				category=self.groceries,
				merchant=outsider.name,
			)

	def test_deleting_a_merchant_keeps_the_money_and_clears_the_link(self):
		"""The choice a recurring plan makes, not the one a tag makes: the spending really
		happened and is still worth reading, it just no longer says who it was with."""
		txn = make_transaction(
			"Expense",
			100,
			self.account,
			tracker=self.tracker,
			category=self.groceries,
			merchant=self.dmart.name,
		)
		frappe.delete_doc("Money Merchant", self.dmart.name, ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Transaction", txn.name))
		self.assertIsNone(frappe.db.get_value("Transaction", txn.name, "merchant"))
