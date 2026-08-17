# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The category tree as a feature: the starter set, and roll-up totals over it.

Roll-ups are the reason sub-categories exist. Every leaf has its own flat ERPNext Account,
so a P&L lists Groceries and Restaurants side by side and never prints a "Food" line — that
total is derived here from the NestedSet bounds.
"""

import frappe
from frappe.utils import add_days

from moneytracker.money_tracker.api import dashboard
from moneytracker.money_tracker.services import categories
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	make_user,
)


class TestDefaultCategories(MoneyTrackerTestCase):
	def test_a_new_tracker_starts_with_a_usable_tree(self):
		"""A tracker with no categories cannot record a single expense."""
		tracker = make_tracker(seed_categories=True).name

		rows = frappe.get_all(
			"Category",
			filters={"tracker": tracker},
			fields=["name", "category_name", "category_type", "is_group", "parent_category"],
		)
		by_name = {r.category_name: r for r in rows}

		self.assertIn("Food & Dining", by_name)
		self.assertIn("Groceries", by_name)
		self.assertTrue(by_name["Food & Dining"].is_group)
		self.assertEqual(by_name["Groceries"].parent_category, by_name["Food & Dining"].name)
		self.assertEqual(by_name["Salary"].category_type, "Income")

	def test_every_seeded_group_is_a_heading_and_every_leaf_can_be_posted_to(self):
		tracker = make_tracker(seed_categories=True).name

		for row in frappe.get_all(
			"Category", filters={"tracker": tracker}, fields=["category_name", "is_group", "ledger_account"]
		):
			with self.subTest(category=row.category_name):
				self.assertEqual(bool(row.is_group), not row.ledger_account)

	def test_seeding_twice_changes_nothing(self):
		"""It is safe to re-run over a tracker somebody has already edited."""
		tracker = make_tracker(seed_categories=True).name
		before = frappe.db.count("Category", {"tracker": tracker})

		self.assertEqual(categories.seed_default_categories(tracker), 0)
		self.assertEqual(frappe.db.count("Category", {"tracker": tracker}), before)

	def test_a_fixture_tracker_is_left_empty(self):
		"""The factories opt out, or every test would start with forty rows in the way."""
		self.assertEqual(frappe.db.count("Category", {"tracker": make_tracker().name}), 0)

	def test_the_income_side_does_not_borrow_the_expense_salary_account(self):
		"""ERPNext's standard chart ships Salary as an expense — the seed must not land there."""
		tracker = make_tracker(seed_categories=True).name
		salary = frappe.db.get_value(
			"Category", {"tracker": tracker, "category_name": "Salary"}, "ledger_account"
		)

		self.assertEqual(frappe.db.get_value("Account", salary, "root_type"), "Income")


class TestCategoryRollup(MoneyTrackerTestCase):
	"""Food 4,500 = Groceries 3,000 + Restaurants 1,500, with the heading holding nothing."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.account = make_account(cls.tracker, account_type="Bank").name

		cls.food = make_category(cls.tracker, category_type="Expense", is_group=1).name
		cls.groceries = make_category(cls.tracker, category_type="Expense", parent_category=cls.food).name
		cls.restaurants = make_category(cls.tracker, category_type="Expense", parent_category=cls.food).name
		cls.transport = make_category(cls.tracker, category_type="Expense").name

		def post(transaction_type, amount, category, **kwargs):
			return make_transaction(
				transaction_type,
				amount,
				cls.account,
				tracker=cls.tracker,
				category=category,
				**kwargs,
			)

		post("Expense", 3000, cls.groceries)
		post("Expense", 1500, cls.restaurants)
		post("Expense", 800, cls.transport)

	def totals(self, **kwargs):
		return {row["category"]: row for row in categories.get_category_totals(self.tracker, **kwargs)}

	def test_a_heading_totals_its_children(self):
		rows = self.totals()

		self.assertMoneyEqual(rows[self.food]["total"], 4500)
		self.assertMoneyEqual(rows[self.groceries]["total"], 3000)
		self.assertMoneyEqual(rows[self.restaurants]["total"], 1500)

	def test_a_heading_holds_nothing_of_its_own(self):
		self.assertMoneyEqual(self.totals()[self.food]["own_total"], 0)

	def test_a_leaf_outside_the_group_is_untouched_by_it(self):
		self.assertMoneyEqual(self.totals()[self.transport]["total"], 800)

	def test_a_refund_nets_off_the_category_it_came_back_to(self):
		make_transaction("Refund", 500, self.account, tracker=self.tracker, category=self.groceries)
		rows = self.totals()

		self.assertMoneyEqual(rows[self.groceries]["total"], 2500)
		self.assertMoneyEqual(rows[self.food]["total"], 4000, "and the heading follows")

	def test_a_period_outside_the_postings_is_empty(self):
		rows = self.totals(from_date=add_days(self.date, -30), to_date=add_days(self.date, -20))

		self.assertMoneyEqual(rows[self.food]["total"], 0)

	def test_the_income_tree_is_a_separate_question(self):
		self.assertNotIn(self.food, self.totals(category_type="Income"))

	def test_a_tracker_with_no_categories_returns_nothing(self):
		self.assertEqual(categories.get_category_totals(make_tracker().name), [])


class TestSpendingByCategoryApi(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		account = make_account(cls.tracker, account_type="Bank").name
		cls.group = make_category(cls.tracker, category_type="Expense", is_group=1).name
		cls.leaf = make_category(cls.tracker, category_type="Expense", parent_category=cls.group).name
		make_transaction("Expense", 250, account, tracker=cls.tracker, category=cls.leaf)

	def test_it_defaults_to_the_current_month(self):
		result = dashboard.get_spending_by_category(tracker=self.tracker)
		rows = {row["category"]: row for row in result["rows"]}

		self.assertMoneyEqual(rows[self.group]["total"], 250)
		self.assertEqual(result["period"]["from_date"].day, 1)

	def test_a_tracker_the_user_may_not_read_is_refused(self):
		with as_user(make_user()), self.assertRaises(frappe.PermissionError):
			dashboard.get_spending_by_category(tracker=self.tracker)
