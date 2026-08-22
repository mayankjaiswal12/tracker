# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""What `Money Recurring Transaction` refuses to save.

Every rule here is one the posting engine would have applied anyway — at 3am, inside a
background job, to a plan the user has long since stopped looking at. The controller applies
them while there is still somebody there to read the message.
"""

import frappe
from frappe.utils import add_to_date, today

from moneytracker.money_tracker.services import recurring
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_recurring,
	make_tracker,
)


class TestMoneyRecurringTransaction(MoneyTrackerTestCase):
	def setUp(self):
		self.tracker = make_tracker()
		self.account = make_account(self.tracker.name)
		self.savings = make_account(self.tracker.name, account_type="Savings")
		self.category = make_category(self.tracker.name)
		self.income_category = make_category(self.tracker.name, category_type="Income")

	def plan(self, **kwargs):
		kwargs.setdefault("account", self.account.name)
		kwargs.setdefault("category", self.category.name)
		return make_recurring(self.tracker.name, **kwargs)

	# --- defaults ---------------------------------------------------------------------

	def test_it_is_named_by_series_with_the_name_as_the_title(self):
		plan = self.plan()
		self.assertTrue(plan.name.startswith("RTX-"))
		self.assertEqual(frappe.get_meta("Money Recurring Transaction").title_field, "recurring_name")

	def test_the_tracker_currency_and_start_date_are_filled_server_side(self):
		plan = frappe.get_doc(
			{
				"doctype": "Money Recurring Transaction",
				"recurring_name": "Fills Itself In",
				"transaction_type": "Expense",
				"amount": 500,
				"frequency": "Monthly",
				"account": self.account.name,
				"category": self.category.name,
				"tracker": self.tracker.name,
			}
		).insert(ignore_permissions=True)

		self.assertTrue(plan.currency)
		self.assertEqual(str(plan.start_date), today())
		self.assertEqual(plan.create_mode, recurring.POST_AUTOMATICALLY)

	def test_it_stores_nothing_about_what_it_has_posted(self):
		"""The invariant, asserted against the schema rather than against a docstring."""
		fieldnames = {field.fieldname for field in frappe.get_meta("Money Recurring Transaction").fields}
		for banned in ("last_run", "last_posted", "next_date", "occurrences_posted", "posted_count"):
			self.assertNotIn(banned, fieldnames)

	# --- the name ---------------------------------------------------------------------

	def test_two_plans_on_one_tracker_may_not_share_a_name(self):
		plan = self.plan()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(recurring_name=plan.recurring_name)
		self.assertIn("already exists on this tracker", str(caught.exception))

	def test_another_tracker_may_use_the_same_name(self):
		plan = self.plan()
		other = make_tracker()
		make_recurring(
			other.name,
			recurring_name=plan.recurring_name,
			account=make_account(other.name).name,
			category=make_category(other.name).name,
		)

	# --- the money --------------------------------------------------------------------

	def test_a_plan_worth_nothing_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(amount=0)
		self.assertIn("greater than zero", str(caught.exception))

	def test_a_negative_plan_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.plan(amount=-100)

	# --- the window -------------------------------------------------------------------

	def test_an_end_date_before_the_start_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(start_date=today(), end_date=add_to_date(today(), days=-1))
		self.assertIn("cannot be before Start Date", str(caught.exception))

	def test_a_single_day_window_is_allowed(self):
		"""One occurrence is a legitimate plan — a deposit due once, on a date."""
		plan = self.plan(start_date=today(), end_date=today())
		self.assertEqual(len(recurring.occurrences(plan.start_date, plan.frequency, today())), 1)

	# --- the type ---------------------------------------------------------------------

	def test_a_type_no_schedule_can_repeat_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(transaction_type="Refund")
		self.assertIn("cannot be scheduled", str(caught.exception))

	def test_an_unimplemented_type_is_refused_here_rather_than_at_3am(self):
		with self.assertRaises(frappe.ValidationError):
			self.plan(transaction_type="Asset Purchase")

	def test_an_unknown_create_mode_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(create_mode="Ask Me Every Time")
		self.assertIn("When It Runs", str(caught.exception))

	# --- the accounts -----------------------------------------------------------------

	def test_a_transfer_needs_a_destination(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(transaction_type="Transfer", category=None)
		self.assertIn("Destination Account is required", str(caught.exception))

	def test_a_transfer_to_itself_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(
				transaction_type="Transfer",
				category=None,
				destination_account=self.account.name,
			)
		self.assertIn("must be different", str(caught.exception))

	def test_a_transfer_drops_the_category_rather_than_carrying_it_forward(self):
		"""A retyped plan must not post a category into every future occurrence."""
		plan = self.plan(transaction_type="Transfer", destination_account=self.savings.name)
		self.assertIsNone(plan.category)

	def test_a_categorised_type_drops_a_stale_destination(self):
		plan = self.plan(destination_account=self.savings.name)
		self.assertIsNone(plan.destination_account)

	def test_an_account_on_another_tracker_is_refused(self):
		other = make_tracker()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(account=make_account(other.name).name)
		self.assertIn("belongs to another tracker", str(caught.exception))

	def test_a_destination_on_another_tracker_is_refused(self):
		other = make_tracker()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(
				transaction_type="Transfer",
				category=None,
				destination_account=make_account(other.name).name,
			)
		self.assertIn("belongs to another tracker", str(caught.exception))

	# --- the category -----------------------------------------------------------------

	def test_a_categorised_plan_without_a_category_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(category=None)
		self.assertIn("Category is required", str(caught.exception))

	def test_an_expense_plan_refuses_an_income_category(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(category=self.income_category.name)
		self.assertIn("Income category", str(caught.exception))

	def test_an_income_plan_refuses_an_expense_category(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(transaction_type="Income", category=self.category.name)
		self.assertIn("Expense category", str(caught.exception))

	def test_a_group_category_is_refused_and_the_message_names_it(self):
		"""The opposite of `Money Budget`, which wants the group so it can roll it up.

		A plan *posts*, and a heading holds no ledger account — so this is the same refusal
		`Transaction` makes, moved from submit to save.
		"""
		group = make_category(self.tracker.name, is_group=1)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(category=group.name)
		self.assertIn(group.category_name, str(caught.exception))
		self.assertIn("group category", str(caught.exception))

	def test_a_category_on_another_tracker_is_refused(self):
		other = make_tracker()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.plan(category=make_category(other.name).name)
		self.assertIn("belongs to another tracker", str(caught.exception))

	# --- the button -------------------------------------------------------------------

	def test_post_due_now_posts_what_is_owed(self):
		plan = self.plan(amount=750)
		result = plan.post_due_now()
		self.assertEqual(len(result["created"]), 1)
		self.assertMoneyEqual(frappe.db.get_value("Transaction", result["created"][0], "amount"), 750)

	def test_post_due_now_says_so_when_nothing_is_owed(self):
		plan = self.plan(start_date=add_to_date(today(), days=5))
		result = plan.post_due_now()
		self.assertEqual(result["created"], [])
		self.assertIn("Nothing is due", result["message"])

	def test_a_paused_plan_refuses_to_post_on_demand(self):
		plan = self.plan()
		plan.status = "Paused"
		plan.save()
		with self.assertRaises(frappe.ValidationError) as caught:
			plan.post_due_now()
		self.assertIn("Only an Active plan", str(caught.exception))

	# --- deletion ---------------------------------------------------------------------

	def test_deleting_a_plan_keeps_its_transactions_and_clears_the_link(self):
		"""The money really moved. Only the arrangement is being deleted."""
		plan = self.plan(amount=400)
		transaction = recurring.generate(plan)[0]

		frappe.delete_doc("Money Recurring Transaction", plan.name, ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Transaction", transaction))
		self.assertIsNone(frappe.db.get_value("Transaction", transaction, "recurring_transaction") or None)
		self.assertEqual(frappe.db.get_value("Transaction", transaction, "docstatus"), 1)
