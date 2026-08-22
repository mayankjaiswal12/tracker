# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Bills: money owed, tracked until settled.

The property under test throughout is the one that separates a bill from a standing order:
**a bill can be overdue.** A plan that has not posted means the scheduler is broken; a bill
that has not been paid means a person has not paid it, and the app has to say so without
turning that into an accusation about anything it did itself.
"""

import frappe
from frappe.utils import add_days, getdate

from moneytracker.money_tracker.api import bills as bills_api
from moneytracker.money_tracker.services import bills
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_bill,
	make_category,
	make_tracker,
	posting_date,
)


class BillFixture(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker, account_type="Bank").name
		self.category = make_category(self.tracker, category_type="Expense").name

	def bill(self, **kwargs):
		kwargs.setdefault("category", self.category)
		kwargs.setdefault("account", self.account)
		return make_bill(self.tracker, **kwargs)


class TestOutcomes(BillFixture):
	def test_a_bill_in_the_future_is_upcoming(self):
		bill = self.bill(due_date=add_days(posting_date(), 30))
		self.assertEqual(bills.measure(bill.name).outcome, bills.UPCOMING)

	def test_a_bill_inside_the_reminder_window_is_due_soon(self):
		bill = self.bill(due_date=add_days(posting_date(), 2), reminder_days_before=3)
		self.assertEqual(bills.measure(bill.name).outcome, bills.DUE_SOON)

	def test_a_bill_due_today_says_so(self):
		self.assertEqual(bills.measure(self.bill().name).outcome, bills.DUE_TODAY)

	def test_a_bill_past_its_date_is_overdue(self):
		"""The state a standing order cannot have, and the reason this doctype exists."""
		bill = self.bill(due_date=add_days(posting_date(), -1))
		measured = bills.measure(bill.name)
		self.assertEqual(measured.outcome, bills.OVERDUE)
		self.assertEqual(measured.days_until_due, -1)

	def test_the_users_own_decision_wins_over_the_calendar(self):
		"""A bill somebody cancelled is not overdue — reporting their decision back to them
		as a fault is the mistake `recurring.measure` was careful to avoid."""
		bill = self.bill(due_date=add_days(posting_date(), -30), status="Cancelled")
		self.assertEqual(bills.measure(bill.name).outcome, bills.CANCELLED)

	def test_a_skipped_bill_is_not_overdue_either(self):
		bill = self.bill(due_date=add_days(posting_date(), -30), status="Skipped")
		self.assertEqual(bills.measure(bill.name).outcome, bills.SKIPPED)

	def test_due_soon_is_not_a_healthy_outcome(self):
		"""It is the whole point of a reminder."""
		self.assertNotIn(bills.DUE_SOON, bills.HEALTHY_OUTCOMES)
		self.assertNotIn(bills.OVERDUE, bills.HEALTHY_OUTCOMES)


class TestUpcoming(BillFixture):
	def test_it_lists_bills_inside_the_window_soonest_first(self):
		later = self.bill(due_date=add_days(posting_date(), 20))
		sooner = self.bill(due_date=add_days(posting_date(), 5))
		names = [row.bill for row in bills.get_upcoming(self.tracker, days=30)]
		self.assertEqual(names, [sooner.name, later.name])

	def test_a_bill_beyond_the_window_is_left_out(self):
		self.bill(due_date=add_days(posting_date(), 90))
		self.assertEqual(bills.get_upcoming(self.tracker, days=30), [])

	def test_an_overdue_bill_is_always_included_however_old(self):
		"""Dropping it would hide it at exactly the point it started to matter."""
		old = self.bill(due_date=add_days(posting_date(), -200))
		self.assertEqual([row.bill for row in bills.get_upcoming(self.tracker, days=7)], [old.name])

	def test_a_paid_bill_is_not_upcoming(self):
		self.bill(status="Paid", amount=500)
		self.assertEqual(bills.get_upcoming(self.tracker), [])

	def test_the_total_skips_a_bill_whose_amount_is_unknown(self):
		"""Reads low rather than wrong: guessing last month's figure invents money."""
		self.bill(amount=1200)
		self.bill(amount_varies=1)
		self.assertEqual(bills.get_total_due(self.tracker), 1200)


class TestMarkPaid(BillFixture):
	def test_it_posts_a_transaction_and_settles_the_bill(self):
		bill = self.bill(amount=1500)
		result = bill.mark_paid()

		transaction = frappe.get_doc("Transaction", result["transaction"])
		self.assertEqual(transaction.amount, 1500)
		self.assertEqual(transaction.docstatus, 1)
		self.assertEqual(transaction.category, self.category)

		bill.reload()
		self.assertEqual(bill.status, "Paid")
		self.assertEqual(bill.linked_transaction, transaction.name)

	def test_the_transaction_links_back_to_the_bill(self):
		bill = self.bill()
		transaction = frappe.get_doc("Transaction", bill.mark_paid()["transaction"])
		self.assertEqual(transaction.bill, bill.name)

	def test_a_varying_bill_takes_the_amount_at_payment_time(self):
		bill = self.bill(amount_varies=1)
		transaction = frappe.get_doc("Transaction", bill.mark_paid(amount=2345)["transaction"])
		self.assertEqual(transaction.amount, 2345)

	def test_a_varying_bill_with_no_amount_is_refused(self):
		bill = self.bill(amount_varies=1)
		with self.assertRaises(frappe.ValidationError):
			bill.mark_paid()

	def test_paying_twice_is_refused(self):
		bill = self.bill()
		bill.mark_paid()
		bill.reload()
		with self.assertRaises(frappe.ValidationError):
			bill.mark_paid()

	def test_a_bill_with_no_category_cannot_be_paid(self):
		bill = make_bill(self.tracker, account=self.account)
		with self.assertRaises(frappe.ValidationError):
			bill.mark_paid()

	def test_deleting_a_bill_keeps_the_payment(self):
		bill = self.bill()
		transaction = bill.mark_paid()["transaction"]
		bill.reload()
		frappe.delete_doc("Money Bill", bill.name, ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Transaction", transaction))
		self.assertIsNone(frappe.db.get_value("Transaction", transaction, "bill"))


class TestRepeating(BillFixture):
	def test_paying_a_monthly_bill_mints_the_next_one(self):
		bill = self.bill(frequency="Monthly", due_date=posting_date())
		successor = bill.mark_paid()["next_bill"]

		self.assertTrue(successor)
		nxt = frappe.get_doc("Money Bill", successor)
		self.assertEqual(nxt.status, "Unpaid")
		self.assertEqual(nxt.due_date, getdate(frappe.utils.add_months(posting_date(), 1)))

	def test_only_one_open_bill_exists_at_a_time(self):
		"""A year of unpaid rows would make "what do I owe" meaningless."""
		bill = self.bill(frequency="Monthly")
		bill.mark_paid()
		self.assertEqual(frappe.db.count("Money Bill", {"tracker": self.tracker, "status": "Unpaid"}), 1)

	def test_a_one_off_bill_mints_nothing(self):
		self.assertIsNone(self.bill(frequency="Does Not Repeat").mark_paid()["next_bill"])

	def test_repeating_stops_at_the_end_date(self):
		bill = self.bill(frequency="Monthly", due_date=posting_date(), end_date=posting_date())
		self.assertIsNone(bill.mark_paid()["next_bill"])

	def test_the_next_date_steps_from_the_due_date_not_the_payment_date(self):
		"""Paying the electricity late does not move the next bill."""
		bill = self.bill(frequency="Monthly", due_date=add_days(posting_date(), -10))
		nxt = frappe.get_doc("Money Bill", bill.mark_paid()["next_bill"])
		self.assertEqual(nxt.due_date, getdate(frappe.utils.add_months(add_days(posting_date(), -10), 1)))

	def test_an_unknown_frequency_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError):
			self.bill(frequency="Hourly")


class TestValidation(BillFixture):
	def test_two_unpaid_bills_with_one_name_are_refused(self):
		self.bill(bill_name="Electricity")
		with self.assertRaises(frappe.ValidationError):
			self.bill(bill_name="Electricity")

	def test_a_paid_one_frees_the_name_again(self):
		"""A repeating bill mints its successor with the same name, so this has to work."""
		self.bill(bill_name="Electricity", status="Paid")
		self.assertTrue(self.bill(bill_name="Electricity").name)

	def test_an_amount_of_zero_is_refused_unless_it_varies(self):
		with self.assertRaises(frappe.ValidationError):
			self.bill(amount=0)
		self.assertTrue(self.bill(amount=0, amount_varies=1).name)

	def test_an_income_category_is_refused(self):
		income = make_category(self.tracker, category_type="Income")
		with self.assertRaises(frappe.ValidationError):
			self.bill(category=income.name)

	def test_a_group_category_is_refused(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1)
		with self.assertRaises(frappe.ValidationError):
			self.bill(category=group.name)

	def test_an_account_from_another_tracker_is_refused(self):
		outsider = make_account(make_tracker().name)
		with self.assertRaises(frappe.ValidationError):
			self.bill(account=outsider.name)

	def test_an_end_date_before_the_due_date_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.bill(frequency="Monthly", end_date=add_days(posting_date(), -5))


class TestReminders(BillFixture):
	"""`send_bill_reminders` is site-wide, like `send_budget_alerts`.

	So these assert on the bill under test rather than on the job's return count —
	`FrappeTestCase` rolls back per class, and an earlier test's bill is still there and
	entitled to announce itself too.
	"""

	def stamp(self, bill):
		return frappe.db.get_value("Money Bill", bill.name, "last_reminder")

	def test_it_notifies_once_and_not_again(self):
		bill = self.bill(due_date=posting_date(), notify_on_due=1)
		bills.send_bill_reminders()
		first = self.stamp(bill)
		self.assertTrue(first, "a bill due today is announced")

		bills.send_bill_reminders()
		self.assertEqual(self.stamp(bill), first, "the same fact is announced once")

	def test_it_speaks_again_when_the_fact_changes(self):
		"""Due today becomes overdue tomorrow, which is a different thing to say."""
		bill = self.bill(due_date=posting_date(), notify_on_due=1)
		bills.send_bill_reminders()
		due_today = self.stamp(bill)

		bills.send_bill_reminders(as_of=add_days(posting_date(), 1))
		overdue = self.stamp(bill)
		self.assertNotEqual(overdue, due_today)
		self.assertIn(bills.OVERDUE, overdue)

	def test_a_bill_far_off_is_not_announced(self):
		bill = self.bill(due_date=add_days(posting_date(), 60), notify_on_due=1)
		bills.send_bill_reminders()
		self.assertIsNone(self.stamp(bill))

	def test_a_bill_that_opted_out_is_not_announced(self):
		bill = self.bill(due_date=posting_date(), notify_on_due=0)
		bills.send_bill_reminders()
		self.assertIsNone(self.stamp(bill))

	def test_a_paid_bill_is_not_announced(self):
		bill = self.bill(due_date=add_days(posting_date(), -5), status="Paid", notify_on_due=1)
		bills.send_bill_reminders()
		self.assertIsNone(self.stamp(bill))

	def test_the_notification_reaches_the_tracker_owner(self):
		bill = self.bill(due_date=posting_date(), notify_on_due=1)
		bills.send_bill_reminders()
		owner = frappe.db.get_value("Tracker", self.tracker, "owner_user")
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"document_type": "Money Bill", "document_name": bill.name, "for_user": owner},
			)
		)


class TestWidgets(BillFixture):
	def test_the_due_card_totals_the_window(self):
		self.bill(amount=1200)
		self.bill(amount=800, due_date=add_days(posting_date(), 10))
		self.assertIn("2,000", bills_api.card_bills_due({"tracker": self.tracker}))

	def test_the_overdue_card_counts_rather_than_totals(self):
		self.bill(due_date=add_days(posting_date(), -3))
		self.bill(due_date=add_days(posting_date(), -1))
		self.assertEqual(bills_api.card_overdue_bills({"tracker": self.tracker}), "2 overdue")

	def test_the_overdue_card_says_so_when_there_are_none(self):
		self.bill(due_date=add_days(posting_date(), 10))
		self.assertEqual(bills_api.card_overdue_bills({"tracker": self.tracker}), "None overdue")
