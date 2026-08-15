# Copyright (c) 2026, Mayank Jaiswal and Contributors
# See license.txt

"""Category: a NestedSet tree with income and expense kept strictly apart."""

import frappe

from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
)


class TestCategory(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name

	def test_a_child_nests_under_its_parent(self):
		parent = make_category(self.tracker, category_type="Expense")
		child = make_category(self.tracker, category_type="Expense", parent_category=parent.name)

		parent.reload()
		self.assertLess(parent.lft, child.lft)
		self.assertGreater(parent.rgt, child.rgt)

	def test_income_cannot_sit_under_expense(self):
		"""The two trees are separate; mixing them would put income inside expense totals."""
		parent = make_category(self.tracker, category_type="Expense")

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Income", parent_category=parent.name)
		self.assertIn("Income and expense trees are separate", str(caught.exception))

	def test_the_refusal_names_the_parent_rather_than_its_hash(self):
		"""Categories are named by hash, so the message has to reach for the title field."""
		parent = make_category(self.tracker, category_type="Expense")

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Income", parent_category=parent.name)

		message = str(caught.exception)
		self.assertIn(parent.category_name, message)
		self.assertNotIn(parent.name, message)

	def test_a_leaf_gets_a_ledger_account_of_the_right_root_type(self):
		expense = make_category(self.tracker, category_type="Expense")
		income = make_category(self.tracker, category_type="Income")

		self.assertEqual(frappe.db.get_value("Account", expense.ledger_account, "root_type"), "Expense")
		self.assertEqual(frappe.db.get_value("Account", income.ledger_account, "root_type"), "Income")

	def test_a_group_gets_no_ledger_account(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		self.assertFalse(group.ledger_account)

	def test_a_group_cannot_be_posted_against(self):
		"""Which is the point of withholding the ledger account: totals belong on the leaves."""
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		account = make_account(self.tracker, account_type="Bank").name
		transaction = make_transaction(
			"Expense", 100, account, tracker=self.tracker, category=group.name, submit=False
		)

		with self.assertRaises(frappe.ValidationError) as caught:
			transaction.submit()
		self.assertIn("no ledger account", str(caught.exception))

	def test_a_category_in_use_cannot_be_deleted(self):
		category = make_category(self.tracker, category_type="Expense")
		account = make_account(self.tracker, account_type="Bank").name
		make_transaction("Expense", 100, account, tracker=self.tracker, category=category.name)

		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.delete_doc("Category", category.name)
		self.assertIn("has transactions against it", str(caught.exception))

	def test_an_unused_category_can_be_deleted(self):
		category = make_category(self.tracker, category_type="Expense")
		frappe.delete_doc("Category", category.name)

		self.assertFalse(frappe.db.exists("Category", category.name))

	def test_the_tracker_defaults_server_side(self):
		self.assertTrue(make_category(category_type="Expense").tracker)
