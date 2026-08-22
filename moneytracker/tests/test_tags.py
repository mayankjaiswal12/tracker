# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Tags: the same money read a second way, and the arithmetic that makes that honest.

The rule under test throughout is that **tag totals overlap**. A transaction carrying two
tags is counted in full under both, so the rows do not partition the tracker's spending the
way the category tree does — and every figure that could be mistaken for a partition
(`total`, `tagged`) is measured without the join instead of summed from it.
"""

import frappe

from moneytracker.money_tracker.services import tags as tags_service
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tag,
	make_tracker,
	make_transaction,
	posting_date,
	tag_transaction,
)


class TestTagTotals(MoneyTrackerTestCase):
	"""`services/tags.py` over a small tracker whose figures are checkable by hand."""

	def setUp(self):
		"""Built per test, not per class.

		`FrappeTestCase` rolls back once per *class*, so a test here that posts an extra
		transaction — the refund and the income cases below both do — would still be visible to
		every test that ran after it, and the totals would drift by whatever it added.
		"""
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.food = make_category(self.tracker, category_type="Expense").name
		self.salary = make_category(self.tracker, category_type="Income").name

		self.vacation = make_tag(self.tracker)
		self.kids = make_tag(self.tracker)
		self.unused = make_tag(self.tracker)

		# 1,000 tagged with both; 400 tagged Vacation only; 250 untagged.
		both = make_transaction("Expense", 1000, self.account, tracker=self.tracker, category=self.food)
		one = make_transaction("Expense", 400, self.account, tracker=self.tracker, category=self.food)
		make_transaction("Expense", 250, self.account, tracker=self.tracker, category=self.food)
		tag_transaction(both, self.vacation, self.kids)
		tag_transaction(one, self.vacation)

	def measured(self, **kwargs):
		out = tags_service.get_spend_by_tag(self.tracker, **kwargs)
		return out, {row["tag"]: row["total"] for row in out["tags"]}

	def test_a_tag_carries_every_transaction_it_is_on(self):
		_, by_tag = self.measured()
		self.assertEqual(by_tag[self.vacation.name], 1400)
		self.assertEqual(by_tag[self.kids.name], 1000)

	def test_a_transaction_with_two_tags_counts_in_full_under_both(self):
		"""The defining property. 1,000 appears under Vacation *and* under Kids."""
		_, by_tag = self.measured()
		self.assertEqual(by_tag[self.vacation.name] + by_tag[self.kids.name], 2400)

	def test_total_is_not_the_sum_of_the_rows(self):
		"""The bug this module exists to avoid: 1,650 spent, not 2,650."""
		out, by_tag = self.measured()
		self.assertEqual(out["total"], 1650)
		self.assertEqual(sum(by_tag.values()), 2400)
		self.assertGreater(sum(by_tag.values()), out["total"])

	def test_tagged_plus_untagged_is_the_whole(self):
		out, _ = self.measured()
		self.assertEqual(out["tagged"], 1400)
		self.assertEqual(out["untagged"], 250)
		self.assertEqual(out["tagged"] + out["untagged"], out["total"])

	def test_untagged_counts_transactions_carrying_no_label(self):
		out, _ = self.measured()
		self.assertEqual(out["untagged_transactions"], 1)

	def test_transactions_are_counted_per_tag(self):
		out, _ = self.measured()
		counts = {row["tag"]: row["transactions"] for row in out["tags"]}
		self.assertEqual(counts[self.vacation.name], 2)
		self.assertEqual(counts[self.kids.name], 1)

	def test_a_tag_with_nothing_against_it_is_returned_at_zero(self):
		"""So a chart keeps a stable set of bars as the window moves."""
		out, by_tag = self.measured()
		self.assertIn(self.unused.name, by_tag)
		self.assertEqual(by_tag[self.unused.name], 0)

	def test_rows_come_back_biggest_first(self):
		out, _ = self.measured()
		totals = [row["total"] for row in out["tags"]]
		self.assertEqual(totals, sorted(totals, reverse=True))

	def test_a_refund_nets_off_the_tag_it_was_spent_under(self):
		"""§62, taken from `categories.net_sign` rather than restated here."""
		refund = make_transaction("Refund", 150, self.account, tracker=self.tracker, category=self.food)
		tag_transaction(refund, self.kids)
		_, by_tag = self.measured()
		self.assertEqual(by_tag[self.kids.name], 850)

	def test_income_is_a_separate_view_rather_than_netted_into_spending(self):
		earned = make_transaction("Income", 5000, self.account, tracker=self.tracker, category=self.salary)
		tag_transaction(earned, self.vacation)

		_, spent = self.measured()
		_, received = self.measured(view="Income")
		self.assertEqual(spent[self.vacation.name], 1400)
		self.assertEqual(received[self.vacation.name], 5000)

	def test_an_unknown_view_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError):
			tags_service.get_spend_by_tag(self.tracker, view="Sideways")

	def test_the_window_is_honoured(self):
		out = tags_service.get_spend_by_tag(self.tracker, from_date="1999-01-01", to_date="1999-12-31")
		self.assertEqual(out["total"], 0)
		self.assertEqual(out["tagged"], 0)
		self.assertTrue(all(row["total"] == 0 for row in out["tags"]))

	def test_a_draft_transaction_is_not_counted(self):
		draft = make_transaction(
			"Expense", 9999, self.account, submit=False, tracker=self.tracker, category=self.food
		)
		draft.set("tags", [{"tag": self.kids.name}])
		draft.save(ignore_permissions=True)
		_, by_tag = self.measured()
		self.assertEqual(by_tag[self.kids.name], 1000)


class TestTaggedTransactions(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.account = make_account(cls.tracker).name
		cls.category = make_category(cls.tracker, category_type="Expense").name
		cls.tag = make_tag(cls.tracker)
		cls.other = make_tag(cls.tracker)
		cls.txn = make_transaction("Expense", 100, cls.account, tracker=cls.tracker, category=cls.category)
		tag_transaction(cls.txn, cls.tag)

	def test_it_finds_the_transactions_carrying_a_tag(self):
		found = tags_service.get_tagged_transactions([self.tag.name], self.tracker)
		self.assertEqual(found, [self.txn.name])

	def test_a_tag_nobody_used_finds_nothing(self):
		self.assertEqual(tags_service.get_tagged_transactions([self.other.name], self.tracker), [])

	def test_no_tags_finds_nothing_rather_than_everything(self):
		"""An empty filter must not silently widen to the whole tracker."""
		self.assertEqual(tags_service.get_tagged_transactions([], self.tracker), [])
		self.assertEqual(tags_service.get_tagged_transactions(None, self.tracker), [])

	def test_a_bare_string_is_accepted_as_one_tag(self):
		self.assertEqual(tags_service.get_tagged_transactions(self.tag.name, self.tracker), [self.txn.name])

	def test_tags_on_reads_them_back_in_row_order(self):
		self.assertEqual(tags_service.tags_on(self.txn.name), [self.tag.name])


class TestTagsAfterSubmit(MoneyTrackerTestCase):
	"""`tags` is the only field on Transaction that may change after submission."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.account = make_account(cls.tracker).name
		cls.category = make_category(cls.tracker, category_type="Expense").name
		cls.tag = make_tag(cls.tracker)

	def test_a_submitted_transaction_can_still_be_tagged(self):
		"""Coming home and labelling the fortnight you already entered."""
		txn = make_transaction("Expense", 300, self.account, tracker=self.tracker, category=self.category)
		self.assertEqual(txn.docstatus, 1)
		tag_transaction(txn, self.tag)
		self.assertEqual(tags_service.tags_on(txn.name), [self.tag.name])

	def test_the_money_on_a_submitted_transaction_still_cannot_change(self):
		"""Tags being editable must not have loosened anything else."""
		txn = make_transaction("Expense", 300, self.account, tracker=self.tracker, category=self.category)
		txn.amount = 999
		with self.assertRaises(frappe.exceptions.UpdateAfterSubmitError):
			txn.save(ignore_permissions=True)

	def test_a_stray_tracker_is_still_refused_after_submit(self):
		"""`validate` does not run on update-after-submit, so the rule is re-run explicitly."""
		outsider = make_tag(make_tracker().name)
		txn = make_transaction("Expense", 300, self.account, tracker=self.tracker, category=self.category)
		txn.set("tags", [{"tag": outsider.name}])
		with self.assertRaises(frappe.ValidationError):
			txn.save(ignore_permissions=True)


class TestRecurringInheritsTags(MoneyTrackerTestCase):
	def test_a_plan_puts_its_tags_on_what_it_posts(self):
		from moneytracker.money_tracker.services import recurring
		from moneytracker.tests.utils import backdate_plan, make_recurring

		tracker = make_tracker().name
		account = make_account(tracker).name
		category = make_category(tracker, category_type="Expense").name
		tag = make_tag(tracker)

		plan = make_recurring(
			tracker,
			account=account,
			category=category,
			frequency="Monthly",
			start_date=posting_date(),
			tags=[{"tag": tag.name}],
		)
		backdate_plan(plan, frappe.utils.add_days(posting_date(), -1))

		created = recurring.generate(frappe.get_doc("Money Recurring Transaction", plan.name))
		self.assertTrue(created, "the plan should have posted its first occurrence")
		self.assertEqual(tags_service.tags_on(created[0]), [tag.name])
