# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Merchants: the same money grouped by who it went to.

The contrast with `test_tags.py` is the point of both modules. A transaction has **one**
merchant, so these rows partition the tracker's spending and `sum(rows) + unnamed == total`.
Tags overlap and never add up. Every assertion here about totals is the one tags cannot make.
"""

import frappe

from moneytracker.money_tracker.api import transactions as transactions_api
from moneytracker.money_tracker.services import merchants as merchants_service
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_merchant,
	make_tracker,
	make_transaction,
)


class TestMerchantTotals(MoneyTrackerTestCase):
	def setUp(self):
		"""Per test — `FrappeTestCase` rolls back per class, and several tests here post."""
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.food = make_category(self.tracker, category_type="Expense").name
		self.salary = make_category(self.tracker, category_type="Income").name

		self.dmart = make_merchant(self.tracker, merchant_name="DMart")
		self.croma = make_merchant(self.tracker, merchant_name="Croma")
		self.unused = make_merchant(self.tracker, merchant_name="Nobody")

		self.spend(600, self.dmart)
		self.spend(400, self.dmart)
		self.spend(1000, self.croma)
		self.spend(250, None)  # names nobody

	def spend(self, amount, merchant, **kwargs):
		return make_transaction(
			"Expense",
			amount,
			self.account,
			tracker=self.tracker,
			category=self.food,
			merchant=merchant.name if merchant else None,
			**kwargs,
		)

	def measured(self, **kwargs):
		out = merchants_service.get_spend_by_merchant(self.tracker, **kwargs)
		return out, {row["merchant"]: row["total"] for row in out["merchants"]}

	def test_a_merchant_carries_every_transaction_naming_it(self):
		_, by_merchant = self.measured()
		self.assertEqual(by_merchant[self.dmart.name], 1000)
		self.assertEqual(by_merchant[self.croma.name], 1000)

	def test_the_rows_partition_the_money(self):
		"""The property tags do not have. 1,000 + 1,000 + 250 unnamed == 2,250."""
		out, by_merchant = self.measured()
		self.assertEqual(sum(by_merchant.values()) + out["unnamed"], out["total"])
		self.assertEqual(out["total"], 2250)
		self.assertEqual(out["named"], 2000)
		self.assertEqual(out["unnamed"], 250)

	def test_money_naming_nobody_is_reported_rather_than_dropped(self):
		out, _ = self.measured()
		self.assertEqual(out["unnamed"], 250)
		self.assertEqual(out["unnamed_transactions"], 1)

	def test_share_is_of_the_whole_window_including_the_unnamed(self):
		out, _ = self.measured()
		shares = {row["merchant"]: row["share"] for row in out["merchants"]}
		self.assertAlmostEqual(shares[self.dmart.name], 1000 / 2250 * 100, places=2)

	def test_a_merchant_with_nothing_against_it_is_returned_at_zero(self):
		_, by_merchant = self.measured()
		self.assertEqual(by_merchant[self.unused.name], 0)

	def test_transactions_are_counted_per_merchant(self):
		out, _ = self.measured()
		counts = {row["merchant"]: row["transactions"] for row in out["merchants"]}
		self.assertEqual(counts[self.dmart.name], 2)
		self.assertEqual(counts[self.croma.name], 1)

	def test_rows_come_back_biggest_first(self):
		out, _ = self.measured()
		totals = [row["total"] for row in out["merchants"]]
		self.assertEqual(totals, sorted(totals, reverse=True))

	def test_a_limit_trims_the_tail_without_changing_the_total(self):
		out, _ = self.measured(limit=1)
		self.assertEqual(len(out["merchants"]), 1)
		self.assertEqual(out["shown"], 1)
		self.assertEqual(out["total"], 2250)

	def test_a_refund_nets_off_the_merchant_it_was_spent_with(self):
		make_transaction(
			"Refund",
			150,
			self.account,
			tracker=self.tracker,
			category=self.food,
			merchant=self.dmart.name,
		)
		_, by_merchant = self.measured()
		self.assertEqual(by_merchant[self.dmart.name], 850)

	def test_income_is_a_separate_view(self):
		make_transaction(
			"Income",
			5000,
			self.account,
			tracker=self.tracker,
			category=self.salary,
			merchant=self.croma.name,
		)
		_, spent = self.measured()
		_, received = self.measured(view="Income")
		self.assertEqual(spent[self.croma.name], 1000)
		self.assertEqual(received[self.croma.name], 5000)

	def test_an_unknown_view_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError):
			merchants_service.get_spend_by_merchant(self.tracker, view="Sideways")

	def test_a_draft_is_not_counted(self):
		self.spend(9999, self.dmart, submit=False)
		_, by_merchant = self.measured()
		self.assertEqual(by_merchant[self.dmart.name], 1000)


class TestResolve(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.dmart = make_merchant(cls.tracker, merchant_name="DMart")

	def test_it_matches_case_insensitively(self):
		"""The whole point of a master: DMart, dmart and D MART must not be three shops."""
		for spelling in ("DMart", "dmart", "DMART"):
			self.assertEqual(merchants_service.resolve(spelling, self.tracker), self.dmart.name)

	def test_it_trims_surrounding_whitespace(self):
		self.assertEqual(merchants_service.resolve("  DMart  ", self.tracker), self.dmart.name)

	def test_an_unknown_name_resolves_to_nothing_without_create(self):
		self.assertIsNone(merchants_service.resolve("Nowhere", self.tracker))

	def test_create_mints_one_and_only_one(self):
		first = merchants_service.resolve("Blinkit", self.tracker, create=True)
		second = merchants_service.resolve("blinkit", self.tracker, create=True)
		self.assertEqual(first, second)

	def test_an_empty_name_is_nothing_rather_than_a_blank_merchant(self):
		for empty in (None, "", "   "):
			self.assertIsNone(merchants_service.resolve(empty, self.tracker, create=True))

	def test_it_does_not_reach_another_tracker(self):
		self.assertIsNone(merchants_service.resolve("DMart", make_tracker().name))


class TestMerchantSearch(MoneyTrackerTestCase):
	"""`merchant` is a Link, so a LIKE on the column matches MER-00007 and not the name."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.account = make_account(cls.tracker).name
		cls.category = make_category(cls.tracker, category_type="Expense").name
		cls.dmart = make_merchant(cls.tracker, merchant_name="DMart Whitefield")
		cls.txn = make_transaction(
			"Expense",
			500,
			cls.account,
			tracker=cls.tracker,
			category=cls.category,
			merchant=cls.dmart.name,
		)

	def test_searching_by_merchant_name_finds_the_transaction(self):
		hits = transactions_api.search_transactions(query="Whitefield", tracker=self.tracker)
		self.assertIn(self.txn.name, [row["name"] for row in hits])

	def test_search_names_resolves_a_fragment_to_ids(self):
		self.assertEqual(merchants_service.search_names("whitefield", self.tracker), [self.dmart.name])

	def test_a_fragment_matching_nothing_finds_nothing(self):
		self.assertEqual(merchants_service.search_names("nowhere", self.tracker), [])
		self.assertEqual(merchants_service.search_names("", self.tracker), [])


class TestMerchantBackfillPatch(MoneyTrackerTestCase):
	"""The migration turns free text into records without inventing any."""

	def test_it_leaves_an_already_linked_value_alone(self):
		from moneytracker.patches.v1_1 import link_merchants

		tracker = make_tracker().name
		account = make_account(tracker).name
		category = make_category(tracker, category_type="Expense").name
		merchant = make_merchant(tracker)
		txn = make_transaction(
			"Expense", 100, account, tracker=tracker, category=category, merchant=merchant.name
		)

		before = frappe.db.count("Money Merchant")
		link_merchants.execute()

		self.assertEqual(frappe.db.count("Money Merchant"), before)
		self.assertEqual(frappe.db.get_value("Transaction", txn.name, "merchant"), merchant.name)
