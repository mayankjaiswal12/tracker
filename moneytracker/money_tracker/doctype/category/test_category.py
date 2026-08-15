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

	def group(self, category_type="Expense", **kwargs):
		return make_category(self.tracker, category_type=category_type, is_group=1, **kwargs)

	def test_a_child_nests_under_its_parent(self):
		parent = self.group()
		child = make_category(self.tracker, category_type="Expense", parent_category=parent.name)

		parent.reload()
		self.assertLess(parent.lft, child.lft)
		self.assertGreater(parent.rgt, child.rgt)

	def test_the_tree_can_go_deeper_than_one_level(self):
		"""Sub-categories are ordinary categories, so nothing caps the depth."""
		top = self.group()
		middle = self.group(parent_category=top.name)
		leaf = make_category(self.tracker, category_type="Expense", parent_category=middle.name)

		top.reload()
		middle.reload()
		self.assertLess(top.lft, middle.lft)
		self.assertLess(middle.lft, leaf.lft)
		self.assertLess(leaf.rgt, middle.rgt)
		self.assertLess(middle.rgt, top.rgt)

	def test_a_child_needs_a_group_for_a_parent(self):
		"""A leaf holds a ledger account, so its total would mix its own postings with its
		children's and stop being the sum of its leaves."""
		leaf = make_category(self.tracker, category_type="Expense")

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Expense", parent_category=leaf.name)
		self.assertIn("is not a group", str(caught.exception))

	def test_income_cannot_sit_under_expense(self):
		"""The two trees are separate; mixing them would put income inside expense totals."""
		parent = self.group()

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Income", parent_category=parent.name)
		self.assertIn("Income and expense trees are separate", str(caught.exception))

	def test_a_parent_on_another_tracker_is_refused(self):
		stranger = make_category(make_tracker().name, category_type="Expense", is_group=1)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Expense", parent_category=stranger.name)
		self.assertIn("another tracker", str(caught.exception))

	def test_the_refusal_names_the_parent_rather_than_its_id(self):
		"""Categories are named CAT-#####, so the message has to reach for the title field."""
		parent = self.group()

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Income", parent_category=parent.name)

		message = str(caught.exception)
		self.assertIn(parent.category_name, message)
		self.assertNotIn(parent.name, message)

	def test_a_duplicate_name_on_one_tracker_is_refused(self):
		"""One ERPNext Account is keyed by name, so two "Groceries" would share a ledger."""
		first = make_category(self.tracker, category_type="Expense")

		with self.assertRaises(frappe.ValidationError) as caught:
			make_category(self.tracker, category_type="Expense", category_name=first.category_name)
		self.assertIn(first.category_name, str(caught.exception))

	def test_the_same_name_on_another_tracker_is_fine(self):
		"""Two people may both have a Groceries category; the Tracker dimension separates them."""
		mine = make_category(self.tracker, category_type="Expense")
		theirs = make_category(make_tracker().name, category_type="Expense", category_name=mine.category_name)

		self.assertEqual(theirs.category_name, mine.category_name)
		self.assertEqual(theirs.ledger_account, mine.ledger_account, "and they share one account")

	def test_the_same_name_as_an_expense_does_not_reuse_its_ledger_account(self):
		"""ERPNext ships "Salary" as an *expense*; matching on the name alone put income there."""
		spent = make_category(self.tracker, category_type="Expense")
		earned = make_category(self.tracker, category_type="Income", category_name=spent.category_name)

		self.assertNotEqual(earned.ledger_account, spent.ledger_account)
		self.assertEqual(frappe.db.get_value("Account", earned.ledger_account, "root_type"), "Income")
		self.assertEqual(frappe.db.get_value("Account", spent.ledger_account, "root_type"), "Expense")

	def test_a_category_with_transactions_cannot_become_a_group(self):
		"""Its own spending would sit beside its children's, so the heading would double-count."""
		category = make_category(self.tracker, category_type="Expense")
		account = make_account(self.tracker, account_type="Bank").name
		make_transaction("Expense", 100, account, tracker=self.tracker, category=category.name)

		category.is_group = 1
		with self.assertRaises(frappe.ValidationError) as caught:
			category.save()
		self.assertIn("cannot become a group", str(caught.exception))

	def test_promoting_an_unused_category_drops_its_ledger_account(self):
		category = make_category(self.tracker, category_type="Expense")
		self.assertTrue(category.ledger_account)

		category.is_group = 1
		category.save()

		self.assertFalse(category.ledger_account)

	def test_a_group_with_children_has_to_stay_a_group(self):
		parent = self.group()
		make_category(self.tracker, category_type="Expense", parent_category=parent.name)

		parent.reload()
		parent.is_group = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			parent.save()
		self.assertIn("has to stay a group", str(caught.exception))

	def test_a_leaf_gets_a_ledger_account_of_the_right_root_type(self):
		expense = make_category(self.tracker, category_type="Expense")
		income = make_category(self.tracker, category_type="Income")

		self.assertEqual(frappe.db.get_value("Account", expense.ledger_account, "root_type"), "Expense")
		self.assertEqual(frappe.db.get_value("Account", income.ledger_account, "root_type"), "Income")

	def test_a_group_gets_no_ledger_account(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		self.assertFalse(group.ledger_account)

	def test_a_group_cannot_be_posted_against(self):
		"""Refused while the user is still choosing, not at submit on a missing ledger account."""
		group = self.group()
		account = make_account(self.tracker, account_type="Bank").name

		with self.assertRaises(frappe.ValidationError) as caught:
			make_transaction("Expense", 100, account, tracker=self.tracker, category=group.name, submit=False)

		message = str(caught.exception)
		self.assertIn("group category", message)
		self.assertIn(group.category_name, message)

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
