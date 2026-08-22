# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""What a tag refuses to save, and what happens to the labels when one is deleted."""

import frappe

from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_tag,
	make_tracker,
	make_transaction,
	tag_transaction,
)


class TestMoneyTag(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name

	def test_it_is_named_by_series(self):
		self.assertTrue(make_tag(self.tracker).name.startswith("TAG-"))

	def test_a_name_is_unique_within_a_tracker(self):
		make_tag(self.tracker, tag_name="Vacation")
		with self.assertRaises(frappe.ValidationError):
			make_tag(self.tracker, tag_name="Vacation")

	def test_the_same_name_is_free_on_another_tracker(self):
		"""Two households must both be able to have a Vacation tag."""
		make_tag(self.tracker, tag_name="Holiday")
		other = make_tracker().name
		self.assertTrue(make_tag(other, tag_name="Holiday").name)

	def test_a_name_differing_only_in_case_is_a_duplicate(self):
		"""Tags are typed inline on a form, where "vacation" beside "Vacation" would
		quietly split one total in two. Accounts do not need this; a list of six is read."""
		make_tag(self.tracker, tag_name="Medical")
		with self.assertRaises(frappe.ValidationError):
			make_tag(self.tracker, tag_name="medical")

	def test_surrounding_whitespace_is_trimmed(self):
		self.assertEqual(make_tag(self.tracker, tag_name="  Office  ").tag_name, "Office")

	def test_it_takes_the_default_tracker_when_none_is_given(self):
		tag = frappe.get_doc({"doctype": "Money Tag", "tag_name": "Unattached"}).insert(
			ignore_permissions=True
		)
		self.assertTrue(tag.tracker)

	def test_deleting_a_tag_takes_it_off_the_transactions(self):
		"""A tag is nothing but the label, so deleting it removes the whole of what it was —
		unlike a recurring plan, which keeps its transactions and only clears the back-link."""
		account = make_account(self.tracker).name
		category = make_category(self.tracker, category_type="Expense").name
		tag = make_tag(self.tracker)
		txn = make_transaction("Expense", 500, account, tracker=self.tracker, category=category)
		tag_transaction(txn, tag)
		self.assertEqual(frappe.db.count("Money Transaction Tag", {"tag": tag.name}), 1)

		frappe.delete_doc("Money Tag", tag.name, ignore_permissions=True)

		self.assertEqual(frappe.db.count("Money Transaction Tag", {"tag": tag.name}), 0)
		self.assertTrue(frappe.db.exists("Transaction", txn.name), "the money must survive")


class TestTagsOnTransaction(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.account = make_account(cls.tracker).name
		cls.category = make_category(cls.tracker, category_type="Expense").name

	def new_draft(self, tags):
		return make_transaction(
			"Expense",
			100,
			self.account,
			submit=False,
			tracker=self.tracker,
			category=self.category,
			tags=[{"tag": tag} for tag in tags],
		)

	def test_a_tag_from_another_tracker_is_refused(self):
		outsider = make_tag(make_tracker().name)
		with self.assertRaises(frappe.ValidationError):
			self.new_draft([outsider.name])

	def test_a_repeated_tag_is_dropped_rather_than_refused(self):
		"""A double-click on a multiselect is not a decision worth interrupting somebody over
		— but left alone it would count the transaction twice in that tag's total."""
		tag = make_tag(self.tracker)
		txn = self.new_draft([tag.name, tag.name])
		self.assertEqual([row.tag for row in txn.tags], [tag.name])

	def test_several_different_tags_are_kept(self):
		a, b = make_tag(self.tracker), make_tag(self.tracker)
		txn = self.new_draft([a.name, b.name])
		self.assertEqual({row.tag for row in txn.tags}, {a.name, b.name})

	def test_no_tags_is_fine(self):
		self.assertEqual(self.new_draft([]).tags, [])
