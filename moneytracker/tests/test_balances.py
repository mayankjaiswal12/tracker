# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Balances are derived, never counted.

`Money Account.current_balance` is a cache recomputed from `GL Entry`; if one ever
disagrees with the ledger, the ledger is right. The isolation tests at the bottom guard the
cross-tracker leak found in the ID-consistency pass: one ERPNext Account is shared by every
tracker that happens to use the same account name, so a query that filters only by account
sums other people's money.
"""

import frappe
from frappe.utils import add_days, flt

from moneytracker.money_tracker.services import balances
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	ledger_movement,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	unique,
)


class TestBalances(MoneyTrackerTestCase):
	"""The six-transaction run from docs/manual-test-desk.md §5, asserted rather than clicked."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.sbi = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		def post(transaction_type, amount, account, **kwargs):
			return make_transaction(transaction_type, amount, account, tracker=cls.tracker, **kwargs)

		post("Income", 50000, cls.bank, category=cls.salary)
		post("Expense", 2000, cls.bank, category=cls.food)
		post("Expense", 3000, cls.card, category=cls.food)
		post("Transfer", 8000, cls.bank, destination_account=cls.sbi)
		post("Credit Card Payment", 1000, cls.bank, destination_account=cls.card)
		post("Refund", 500, cls.bank, category=cls.food)

	def test_balances_are_what_the_arithmetic_says(self):
		# 50000 - 2000 - 8000 - 1000 + 500
		self.assertMoneyEqual(balances.get_account_balance(self.bank), 39500)
		self.assertMoneyEqual(balances.get_account_balance(self.sbi), 8000)
		# 3000 charged - 1000 paid, positive because it is what you owe.
		self.assertMoneyEqual(balances.get_account_balance(self.card), 2000)

	def test_the_cache_agrees_with_the_ledger(self):
		"""The §76 reconciliation: cached balance == GL movement, for every account."""
		for money_account in (self.bank, self.sbi, self.card):
			cached = frappe.db.get_value("Money Account", money_account, "current_balance")
			self.assertMoneyEqual(cached, balances.get_account_balance(money_account), money_account)

	def test_a_corrupted_cache_is_repaired_from_the_ledger(self):
		"""Recomputed, never incremented — so a wrong number can only ever be transient."""
		frappe.db.set_value("Money Account", self.bank, "current_balance", 1, update_modified=False)
		updated = balances.recompute_balances(money_account=self.bank)

		self.assertEqual(updated, 1)
		self.assertMoneyEqual(frappe.db.get_value("Money Account", self.bank, "current_balance"), 39500)

	def test_recompute_covers_a_whole_tracker(self):
		# Counted from the table rather than hardcoded: sibling tests in this class add
		# accounts of their own, and FrappeTestCase rolls back per class, not per test.
		self.assertEqual(
			balances.recompute_balances(tracker=self.tracker),
			frappe.db.count("Money Account", {"tracker": self.tracker}),
		)

	def test_get_balances_for_tracker_lists_every_account(self):
		rows = {row["money_account"]: row for row in balances.get_balances_for_tracker(self.tracker)}

		self.assertLessEqual({self.bank, self.sbi, self.card}, set(rows))
		self.assertMoneyEqual(rows[self.bank]["balance"], 39500)
		self.assertMoneyEqual(rows[self.sbi]["balance"], 8000)
		self.assertEqual(rows[self.card]["account_type"], "Credit Card")

	def test_an_account_with_no_movement_still_reports_zero(self):
		idle = make_account(self.tracker, account_type="Cash").name
		rows = {row["money_account"]: row for row in balances.get_balances_for_tracker(self.tracker)}

		self.assertIn(idle, rows)
		self.assertMoneyEqual(rows[idle]["balance"], 0)
		self.assertMoneyEqual(balances.get_account_balance(idle), 0)

	def test_net_worth_is_assets_less_liabilities(self):
		net_worth = balances.get_net_worth(tracker=self.tracker)

		self.assertMoneyEqual(net_worth["assets"], 47500)
		self.assertMoneyEqual(net_worth["liabilities"], 2000)
		self.assertMoneyEqual(net_worth["net_worth"], 45500)
		self.assertEqual(net_worth["currency"], frappe.db.get_single_value("Money Settings", "base_currency"))

	def test_an_account_excluded_from_net_worth_is_left_out(self):
		excluded = make_account(self.tracker, account_type="Bank", include_in_net_worth=0).name
		make_transaction("Income", 999, excluded, tracker=self.tracker, category=self.salary)

		self.assertMoneyEqual(balances.get_net_worth(tracker=self.tracker)["assets"], 47500)

	def test_as_of_excludes_later_postings(self):
		yesterday = add_days(self.date, -1)
		self.assertMoneyEqual(balances.get_account_balance(self.bank, as_of=yesterday), 0)
		self.assertMoneyEqual(balances.get_net_worth(tracker=self.tracker, as_of=yesterday)["net_worth"], 0)

	def test_a_tracker_with_no_accounts_reports_nothing(self):
		empty = make_tracker().name
		self.assertEqual(balances.get_balances_for_tracker(empty), [])
		self.assertMoneyEqual(balances.get_net_worth(tracker=empty)["net_worth"], 0)


class TestCrossTrackerIsolation(MoneyTrackerTestCase):
	"""Two trackers, one shared ERPNext Account — each must see only its own money.

	`coa.get_or_create_ledger_account` matches on `{company, account_name, is_group: 0}`, so
	two people who both call an account "Cash" post into the same ledger account. Only the
	Tracker dimension separates them. Filtering GL Entry by account alone — which is what
	balances.py used to do — makes each of them read the other's total.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shared_name = unique("Cash")

		cls.tracker_a = make_tracker().name
		cls.tracker_b = make_tracker().name
		cls.account_a = make_account(cls.tracker_a, account_name=shared_name, account_type="Cash").name
		cls.account_b = make_account(cls.tracker_b, account_name=shared_name, account_type="Cash").name
		cls.category_a = make_category(cls.tracker_a, category_type="Income").name
		cls.category_b = make_category(cls.tracker_b, category_type="Income").name

		make_transaction("Income", 100, cls.account_a, tracker=cls.tracker_a, category=cls.category_a)
		make_transaction("Income", 4242, cls.account_b, tracker=cls.tracker_b, category=cls.category_b)

	def test_the_two_accounts_really_do_share_one_ledger_account(self):
		"""The precondition. If this ever stops being true, the tests below prove nothing."""
		ledger_a = frappe.db.get_value("Money Account", self.account_a, "ledger_account")
		ledger_b = frappe.db.get_value("Money Account", self.account_b, "ledger_account")

		self.assertEqual(ledger_a, ledger_b)
		self.assertMoneyEqual(ledger_movement(ledger_a), 4342, "both trackers' movements are in there")

	def test_get_account_balance_is_scoped_to_the_tracker(self):
		self.assertMoneyEqual(balances.get_account_balance(self.account_a), 100)
		self.assertMoneyEqual(balances.get_account_balance(self.account_b), 4242)

	def test_get_balances_for_tracker_is_scoped_to_the_tracker(self):
		rows = balances.get_balances_for_tracker(self.tracker_a)
		self.assertEqual(len(rows), 1)
		self.assertMoneyEqual(rows[0]["balance"], 100)

	def test_net_worth_is_scoped_to_the_tracker(self):
		self.assertMoneyEqual(balances.get_net_worth(tracker=self.tracker_a)["net_worth"], 100)
		self.assertMoneyEqual(balances.get_net_worth(tracker=self.tracker_b)["net_worth"], 4242)

	def test_the_cached_balances_are_scoped_too(self):
		self.assertMoneyEqual(frappe.db.get_value("Money Account", self.account_a, "current_balance"), 100)
		self.assertMoneyEqual(frappe.db.get_value("Money Account", self.account_b, "current_balance"), 4242)

	def test_net_worth_without_a_tracker_totals_everything(self):
		"""A bare call is a deliberate all-trackers total, not an oversight."""
		everything = balances.get_net_worth()
		per_tracker = flt(balances.get_net_worth(tracker=self.tracker_a)["net_worth"]) + flt(
			balances.get_net_worth(tracker=self.tracker_b)["net_worth"]
		)
		self.assertGreaterEqual(flt(everything["net_worth"]), per_tracker)
