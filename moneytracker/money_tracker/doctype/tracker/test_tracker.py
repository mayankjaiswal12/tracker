# Copyright (c) 2026, Mayank Jaiswal and Contributors
# See license.txt

"""Tracker: the unit of ownership, and therefore the unit of isolation."""

import frappe

from moneytracker.money_tracker.services import settings as settings_service
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	make_user,
	money_setting,
)


class TestTracker(MoneyTrackerTestCase):
	def test_the_owner_and_currency_default_server_side(self):
		tracker = make_tracker()

		self.assertEqual(tracker.owner_user, frappe.session.user)
		self.assertEqual(tracker.base_currency, settings_service.get_base_currency())

	def test_a_tracker_is_named_by_hash_with_a_readable_title(self):
		"""Two users must both be able to call a tracker "Personal"."""
		name = "Personal"
		first = make_tracker(tracker_name=name)
		second = make_tracker(tracker_name=name)

		self.assertNotEqual(first.name, second.name)
		self.assertNotIn(name, first.name)
		self.assertEqual(frappe.get_meta("Tracker").title_field, "tracker_name")

	def test_a_tracker_with_transactions_cannot_be_deleted(self):
		tracker = make_tracker().name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Income").name
		make_transaction("Income", 100, account, tracker=tracker, category=category)

		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.delete_doc("Tracker", tracker)
		self.assertIn("Archive it instead", str(caught.exception))

	def test_an_empty_tracker_can_be_deleted(self):
		tracker = make_tracker().name
		frappe.delete_doc("Tracker", tracker)

		self.assertFalse(frappe.db.exists("Tracker", tracker))


class TestDefaultTracker(MoneyTrackerTestCase):
	"""`get_default_tracker` is scoped per user — with one shared Company, handing back
	somebody else's tracker would hand back their books."""

	def test_one_is_created_on_first_use(self):
		user = make_user()
		with as_user(user):
			tracker = settings_service.get_default_tracker()

		self.assertEqual(frappe.db.get_value("Tracker", tracker, "owner_user"), user)

	def test_the_same_one_comes_back_next_time(self):
		user = make_user()
		with as_user(user):
			self.assertEqual(settings_service.get_default_tracker(), settings_service.get_default_tracker())

	def test_it_never_returns_another_user_s_tracker(self):
		owner = make_user()
		other = make_user()
		theirs = make_tracker(owner_user=owner).name

		with as_user(other):
			self.assertNotEqual(settings_service.get_default_tracker(), theirs)

	def test_a_configured_default_belonging_to_someone_else_is_ignored(self):
		"""Money Settings holds one default_tracker for the whole site; it may only be handed
		to the person who owns it."""
		owner = make_user()
		other = make_user()
		theirs = make_tracker(owner_user=owner).name

		with money_setting(default_tracker=theirs):
			self.assertEqual(settings_service.get_default_tracker(user=owner), theirs)
			self.assertNotEqual(settings_service.get_default_tracker(user=other), theirs)
