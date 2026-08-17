# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Row-level security — treat a failure here as a leak, not a bug.

Every user's books live in one shared ERPNext Company, so nothing in the ledger separates
them. `money_tracker/permissions.py` is the only thing that does. These tests exercise it
through `frappe.get_list` as a real logged-in user, not just by calling the hook functions,
because it is the wiring in hooks.py that has to hold as much as the logic.
"""

import frappe

from moneytracker.money_tracker import permissions
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	make_user,
)

SCOPED_DOCTYPES = ("Transaction", "Money Account", "Category")


class PermissionFixture(MoneyTrackerTestCase):
	"""Two users with only `Finance User` — the roles in UNRESTRICTED_ROLES see everything
	by design, so testing with those would prove nothing."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user_a = make_user()
		cls.user_b = make_user()
		cls.stranger = make_user()  # owns no tracker at all

		cls.tracker_a, cls.account_a, cls.category_a, cls.transaction_a = cls.books(cls.user_a)
		cls.tracker_b, cls.account_b, cls.category_b, cls.transaction_b = cls.books(cls.user_b)

	@classmethod
	def books(cls, user):
		tracker = make_tracker(owner_user=user).name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Income").name
		transaction = make_transaction("Income", 1000, account, tracker=tracker, category=category).name
		return tracker, account, category, transaction


class TestListIsolation(PermissionFixture):
	def test_a_user_sees_only_their_own_rows(self):
		with as_user(self.user_a):
			self.assertEqual(frappe.get_list("Tracker", pluck="name"), [self.tracker_a])
			self.assertEqual(frappe.get_list("Transaction", pluck="name"), [self.transaction_a])
			self.assertEqual(frappe.get_list("Money Account", pluck="name"), [self.account_a])
			self.assertEqual(frappe.get_list("Category", pluck="name"), [self.category_a])

	def test_a_user_never_sees_another_user_s_rows(self):
		with as_user(self.user_b):
			self.assertNotIn(self.transaction_a, frappe.get_list("Transaction", pluck="name"))
			self.assertNotIn(self.account_a, frappe.get_list("Money Account", pluck="name"))
			self.assertNotIn(self.category_a, frappe.get_list("Category", pluck="name"))
			self.assertNotIn(self.tracker_a, frappe.get_list("Tracker", pluck="name"))

	def test_a_user_with_no_tracker_sees_nothing(self):
		"""Empty, not everything. `tracker_scoped_query_conditions` returns "1 = 0" here;
		returning "" would mean *no restriction* and expose every row on the site."""
		with as_user(self.stranger):
			for doctype in (*SCOPED_DOCTYPES, "Tracker"):
				self.assertEqual(frappe.get_list(doctype, pluck="name"), [], doctype)

	def test_naming_a_document_directly_is_still_denied(self):
		"""Pasting someone else's URL must not work either — the list filter is not the
		only gate."""
		with as_user(self.user_b):
			self.assertFalse(frappe.has_permission("Transaction", doc=self.transaction_a, user=self.user_b))
			self.assertFalse(frappe.has_permission("Tracker", doc=self.tracker_a, user=self.user_b))
			self.assertFalse(frappe.has_permission("Money Account", doc=self.account_a, user=self.user_b))

	def test_a_user_can_still_read_their_own_document(self):
		with as_user(self.user_a):
			self.assertTrue(frappe.has_permission("Transaction", doc=self.transaction_a, user=self.user_a))

	def test_an_unrestricted_role_sees_everything(self):
		with as_user("Administrator"):
			names = frappe.get_list("Transaction", pluck="name", limit_page_length=0)
			self.assertIn(self.transaction_a, names)
			self.assertIn(self.transaction_b, names)


class TestQueryConditions(PermissionFixture):
	"""The generated SQL, checked directly — a wrong string here fails open."""

	def test_no_tracker_produces_a_false_condition(self):
		for doctype in SCOPED_DOCTYPES:
			self.assertEqual(
				permissions.tracker_scoped_query_conditions(self.stranger, doctype=doctype), "1 = 0"
			)

	def test_the_condition_names_the_right_table(self):
		"""Every scoped DocType shares one hook, so the table has to come from the argument."""
		condition = permissions.tracker_scoped_query_conditions(self.user_a, doctype="Money Account")

		self.assertIn("`tabMoney Account`.`tracker`", condition)
		self.assertIn(self.tracker_a, condition)
		self.assertNotIn(self.tracker_b, condition)

	def test_the_condition_defaults_to_transaction(self):
		self.assertIn("`tabTransaction`.`tracker`", permissions.tracker_scoped_query_conditions(self.user_a))

	def test_an_unrestricted_user_is_unfiltered(self):
		self.assertEqual(permissions.tracker_scoped_query_conditions("Administrator"), "")
		self.assertEqual(permissions.tracker_query_conditions("Administrator"), "")

	def test_the_tracker_condition_matches_on_owner(self):
		condition = permissions.tracker_query_conditions(self.user_a)

		self.assertIn("`tabTracker`.`owner_user`", condition)
		self.assertIn(self.user_a, condition)


class TestHasPermissionHooks(PermissionFixture):
	def test_tracker_access_follows_ownership(self):
		tracker = frappe.get_doc("Tracker", self.tracker_a)

		self.assertTrue(permissions.tracker_has_permission(tracker, user=self.user_a))
		self.assertFalse(permissions.tracker_has_permission(tracker, user=self.user_b))
		self.assertTrue(permissions.tracker_has_permission(tracker, user="Administrator"))

	def test_scoped_access_follows_the_tracker_owner(self):
		transaction = frappe.get_doc("Transaction", self.transaction_a)

		self.assertTrue(permissions.tracker_scoped_has_permission(transaction, user=self.user_a))
		self.assertFalse(permissions.tracker_scoped_has_permission(transaction, user=self.user_b))

	def test_a_document_with_no_tracker_falls_through(self):
		"""Currently permissive. Asserted so that changing it is a deliberate decision."""
		orphan = frappe.get_doc({"doctype": "Category", "category_name": "x", "category_type": "Expense"})

		self.assertTrue(permissions.tracker_scoped_has_permission(orphan, user=self.user_b))

	def test_a_controller_hook_can_only_deny(self):
		"""Frappe never grants on the strength of these hooks, so a user without the role
		stays out even though they own the tracker."""
		roleless = make_user(roles=())
		tracker = make_tracker(owner_user=roleless).name

		self.assertFalse(frappe.has_permission("Transaction", user=roleless))
		self.assertTrue(permissions.tracker_scoped_query_conditions(roleless).find(tracker) > 0)
