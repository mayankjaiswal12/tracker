# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Subscriptions: the terms of an arrangement, where a plan holds only its money.

Two properties are under test throughout, and they are what separate this from every module
before it.

**A subscription posts nothing.** There is no strategy, no `generate()` and no Journal Entry
anywhere below — the money either comes from a linked standing order or from somebody paying
by hand. So none of these tests needs a Fiscal Year, and literal dates are used freely.

**Its price history is stored, and it has to be.** Every other figure in this app is measured
from `GL Entry` on read, because a stored copy drifts. A price cannot be measured from the
ledger at all: a month somebody forgot to pay looks exactly like a month the thing was free.
"""

from pathlib import Path

import frappe
from frappe.utils import add_days, getdate

from moneytracker.money_tracker.api import subscriptions as subscriptions_api
from moneytracker.money_tracker.services import recurring, subscriptions
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_recurring,
	make_subscription,
	make_tracker,
	posting_date,
)

JAN = getdate("2026-01-01")


class SubscriptionFixture(MoneyTrackerTestCase):
	"""A fresh tracker per test.

	`FrappeTestCase` rolls back per class, so a tracker made once in `setUpClass` would carry
	every earlier test's subscriptions into the spend and renewal figures.
	"""

	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker, account_type="Bank").name
		self.category = make_category(self.tracker, category_type="Expense").name

	def subscription(self, **kwargs):
		kwargs.setdefault("category", self.category)
		kwargs.setdefault("account", self.account)
		return make_subscription(self.tracker, **kwargs)


class TestPriceHistory(SubscriptionFixture):
	"""`Money Subscription Price` is the source of truth; `amount` is a cache of the current
	one — the same relationship `Money Account.current_balance` has with the ledger."""

	def test_the_opening_price_is_recorded_on_insert(self):
		"""Nobody should have to know the history exists for it to be right."""
		sub = self.subscription(amount=499, start_date=JAN)
		self.assertEqual(len(sub.price_history), 1)
		self.assertEqual(getdate(sub.price_history[0].effective_from), JAN)
		self.assertMoneyEqual(sub.price_history[0].amount, 499)

	def test_typing_over_the_price_records_the_rise(self):
		sub = self.subscription(amount=499, start_date=add_days(posting_date(), -60))
		sub.amount = 649
		sub.save()

		self.assertEqual(len(sub.price_history), 2)
		self.assertMoneyEqual(subscriptions.current_price(sub), 649)

	def test_the_old_price_still_applies_to_the_days_it_applied_to(self):
		start = add_days(posting_date(), -60)
		sub = self.subscription(amount=499, start_date=start)
		sub.amount = 649
		sub.save()

		self.assertMoneyEqual(subscriptions.price_at(sub, add_days(start, 1)), 499)
		self.assertMoneyEqual(subscriptions.price_at(sub, posting_date()), 649)

	def test_a_date_before_the_first_price_falls_back_to_the_current_one(self):
		"""Reading zero there would claim the thing was free."""
		sub = self.subscription(amount=499, start_date=JAN)
		self.assertMoneyEqual(subscriptions.price_at(sub, add_days(JAN, -30)), 499)

	def test_the_rise_is_reported_as_an_amount_and_a_percent(self):
		sub = self.subscription(amount=500, start_date=add_days(posting_date(), -60))
		sub.amount = 650
		sub.save()

		change = subscriptions.price_change(sub)
		self.assertMoneyEqual(change.delta, 150)
		self.assertEqual(change.percent, 30.0)
		self.assertEqual(change.changes, 1)

	def test_a_price_that_never_moved_reports_no_change(self):
		"""0% would suggest somebody checked and it held."""
		self.assertIsNone(subscriptions.price_change(self.subscription(amount=499)))

	def test_editing_only_the_table_brings_the_field_into_line(self):
		sub = self.subscription(amount=499, start_date=JAN)
		sub.append("price_history", {"effective_from": add_days(JAN, 40), "amount": 649})
		sub.save()

		self.assertMoneyEqual(sub.amount, 649)

	def test_the_newest_price_is_by_date_not_by_row_order(self):
		"""A rise recorded after the fact lands at the bottom of the grid, not in date order."""
		sub = self.subscription(amount=499, start_date=JAN)
		sub.append("price_history", {"effective_from": add_days(JAN, 60), "amount": 799})
		sub.append("price_history", {"effective_from": add_days(JAN, 30), "amount": 649})
		sub.save()

		self.assertMoneyEqual(sub.amount, 799)
		self.assertMoneyEqual(subscriptions.price_at(sub, add_days(JAN, 45)), 649)

	def test_two_prices_on_one_day_are_refused(self):
		sub = self.subscription(amount=499, start_date=JAN)
		sub.append("price_history", {"effective_from": JAN, "amount": 649})
		self.assertRaises(frappe.ValidationError, sub.save)

	def test_a_recorded_price_of_zero_is_refused(self):
		sub = self.subscription(amount=499, start_date=JAN)
		sub.append("price_history", {"effective_from": add_days(JAN, 30), "amount": 0})
		self.assertRaises(frappe.ValidationError, sub.save)


class TestTheCalendar(SubscriptionFixture):
	def test_the_month_end_rule_is_the_one_a_plan_follows(self):
		"""31 Jan → 28 Feb → **31** Mar, because every occurrence is counted from the anchor
		rather than stepped off the last one."""
		sub = self.subscription(start_date=getdate("2026-01-31"), billing_frequency="Monthly")

		self.assertEqual(subscriptions.next_renewal(sub, getdate("2026-02-01")), getdate("2026-02-28"))
		self.assertEqual(subscriptions.next_renewal(sub, getdate("2026-03-01")), getdate("2026-03-31"))

	def test_a_trial_anchors_the_billing_calendar_the_day_after_it_ends(self):
		"""Not on the start date: the first charge lands when the free period stops."""
		sub = self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 14))

		self.assertEqual(subscriptions.billing_start(sub), add_days(JAN, 15))
		self.assertEqual(subscriptions.next_renewal(sub, JAN), add_days(JAN, 15))

	def test_the_second_charge_after_a_trial_is_a_month_after_the_first(self):
		sub = self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 14))
		first = subscriptions.next_renewal(sub, JAN)
		self.assertEqual(subscriptions.next_renewal(sub, first), getdate("2026-02-16"))

	def test_there_is_no_renewal_after_the_end_date(self):
		sub = self.subscription(start_date=JAN, end_date=add_days(JAN, 40))
		self.assertIsNone(subscriptions.next_renewal(sub, add_days(JAN, 45)))

	def test_cancel_by_is_the_renewal_minus_the_notice(self):
		sub = self.subscription(start_date=JAN, notice_period_days=10)
		self.assertEqual(subscriptions.cancel_by(sub, add_days(JAN, 5)), getdate("2026-01-22"))

	def test_without_a_notice_period_there_is_nothing_to_be_late_for(self):
		self.assertIsNone(subscriptions.cancel_by(self.subscription(start_date=JAN), JAN))

	def test_an_unknown_frequency_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(billing_frequency="Biannually")


class TestOutcomes(SubscriptionFixture):
	"""Derived, never stored — the same rule goals, budgets, plans and bills follow."""

	def outcome(self, as_of, **kwargs):
		kwargs.setdefault("start_date", JAN)
		return subscriptions.measure(self.subscription(**kwargs), as_of).outcome

	def test_a_renewal_far_off_is_simply_active(self):
		self.assertEqual(self.outcome(add_days(JAN, 9)), subscriptions.ACTIVE)

	def test_a_subscription_starting_later_has_not_started(self):
		self.assertEqual(self.outcome(JAN, start_date=add_days(JAN, 90)), subscriptions.NOT_STARTED)

	def test_a_trial_with_time_left_is_trialing(self):
		self.assertEqual(
			self.outcome(add_days(JAN, 4), trial_end_date=add_days(JAN, 31)), subscriptions.TRIALING
		)

	def test_a_trial_running_out_is_the_state_this_doctype_exists_for(self):
		"""The only state in the app where doing nothing costs money."""
		self.assertEqual(
			self.outcome(add_days(JAN, 27), trial_end_date=add_days(JAN, 31)),
			subscriptions.TRIAL_ENDING,
		)

	def test_a_renewal_inside_the_reminder_window_says_so(self):
		self.assertEqual(self.outcome(add_days(JAN, 27)), subscriptions.RENEWING_SOON)

	def test_a_closing_notice_window_outranks_the_renewal(self):
		"""The notice deadline comes first and is the one that can still be acted on."""
		self.assertEqual(self.outcome(add_days(JAN, 19), notice_period_days=10), subscriptions.CANCEL_BY)

	def test_a_notice_window_that_shut_is_reported_as_such(self):
		self.assertEqual(self.outcome(add_days(JAN, 19), notice_period_days=20), subscriptions.NOTICE_PASSED)

	def test_the_users_own_decision_wins_over_the_calendar(self):
		"""A subscription somebody paused is not renewing next week, whatever the dates say."""
		self.assertEqual(self.outcome(add_days(JAN, 27), status="Paused"), subscriptions.PAUSED)
		self.assertEqual(self.outcome(add_days(JAN, 27), status="Cancelled"), subscriptions.CANCELLED)

	def test_a_window_that_has_closed_is_expired(self):
		self.assertEqual(self.outcome(add_days(JAN, 60), end_date=add_days(JAN, 40)), subscriptions.EXPIRED)

	def test_trialing_is_healthy_and_trial_ending_is_not(self):
		"""One is free money, the other is a deadline — the only distinction that matters."""
		self.assertIn(subscriptions.TRIALING, subscriptions.HEALTHY_OUTCOMES)
		self.assertNotIn(subscriptions.TRIAL_ENDING, subscriptions.HEALTHY_OUTCOMES)
		self.assertNotIn(subscriptions.CANCEL_BY, subscriptions.HEALTHY_OUTCOMES)
		self.assertNotIn(subscriptions.RENEWING_SOON, subscriptions.HEALTHY_OUTCOMES)

	def test_a_fact_nobody_can_act_on_is_not_announced(self):
		self.assertNotIn(subscriptions.NOTICE_PASSED, subscriptions.ANNOUNCED_OUTCOMES)


class TestSpend(SubscriptionFixture):
	def test_a_yearly_price_is_reported_per_month(self):
		"""The one figure that lets a domain renewal be compared with a music service."""
		sub = self.subscription(amount=1200, billing_frequency="Yearly", start_date=JAN)
		measured = subscriptions.measure(sub, add_days(JAN, 5))

		self.assertMoneyEqual(measured.monthly_equivalent, 100)
		self.assertMoneyEqual(measured.annual_equivalent, 1200)

	def test_the_spend_totals_the_monthly_equivalents(self):
		self.subscription(amount=499, billing_frequency="Monthly", start_date=JAN)
		self.subscription(amount=1200, billing_frequency="Yearly", start_date=JAN)

		spend = subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 5))
		self.assertMoneyEqual(spend.monthly, 599)
		self.assertEqual(spend.subscriptions, 2)

	def test_a_trial_costs_nothing_yet(self):
		"""Counting what it will cost afterwards reports money nobody has committed to."""
		self.subscription(amount=499, start_date=JAN, trial_end_date=add_days(JAN, 30))

		spend = subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 5))
		self.assertMoneyEqual(spend.monthly, 0)
		self.assertEqual(spend.in_trial, 1)

	def test_a_subscription_starting_next_month_is_a_commitment_now(self):
		"""The same call `get_fixed_costs` makes, and for the same reason."""
		self.subscription(amount=499, start_date=add_days(JAN, 40))
		self.assertMoneyEqual(subscriptions.get_subscription_spend(self.tracker, JAN).monthly, 499)

	def test_a_paused_one_is_left_out(self):
		self.subscription(amount=499, start_date=JAN, status="Paused")
		self.assertMoneyEqual(subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 5)).monthly, 0)

	def test_a_cancelled_one_still_being_paid_for_is_counted(self):
		"""The case the outcome word gets wrong: cancelled in January, paid until June."""
		self.subscription(amount=499, start_date=JAN, status="Cancelled", end_date=add_days(JAN, 150))
		self.assertMoneyEqual(
			subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 60)).monthly, 499
		)

	def test_a_cancelled_one_with_no_end_date_is_over_now(self):
		self.subscription(amount=499, start_date=JAN, status="Cancelled")
		self.assertMoneyEqual(
			subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 60)).monthly, 0
		)

	def test_a_window_that_has_closed_stops_costing(self):
		self.subscription(amount=499, start_date=JAN, end_date=add_days(JAN, 40))
		self.assertMoneyEqual(
			subscriptions.get_subscription_spend(self.tracker, add_days(JAN, 60)).monthly, 0
		)


class TestRenewalsAndTrials(SubscriptionFixture):
	def test_renewals_come_back_soonest_first(self):
		later = self.subscription(start_date=getdate("2026-01-20"))
		sooner = self.subscription(start_date=getdate("2026-01-05"))

		names = [row.subscription for row in subscriptions.get_renewals(self.tracker, days=40, as_of=JAN)]
		self.assertEqual(names, [sooner.name, later.name])

	def test_a_renewal_beyond_the_window_is_left_out(self):
		self.subscription(start_date=JAN, billing_frequency="Yearly")
		self.assertEqual(subscriptions.get_renewals(self.tracker, days=30, as_of=JAN), [])

	def test_a_cancelled_subscription_is_not_a_renewal_to_warn_about(self):
		self.subscription(start_date=JAN, status="Cancelled")
		self.assertEqual(subscriptions.get_renewals(self.tracker, days=40, as_of=JAN), [])

	def test_trials_ending_uses_each_subscriptions_own_window(self):
		self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 3), reminder_days_before=7)
		self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 30), reminder_days_before=7)

		ending = subscriptions.get_trials_ending(self.tracker, as_of=JAN)
		self.assertEqual(len(ending), 1)


class TestValidation(SubscriptionFixture):
	def test_two_subscriptions_with_one_name_are_refused(self):
		"""Every spend figure would count it twice."""
		first = self.subscription()
		with self.assertRaises(frappe.ValidationError):
			self.subscription(subscription_name=first.subscription_name)

	def test_a_price_of_zero_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(amount=0)

	def test_a_negative_notice_period_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(notice_period_days=-5)

	def test_a_trial_ending_before_it_started_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(start_date=JAN, trial_end_date=add_days(JAN, -5))

	def test_an_end_date_before_the_start_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(start_date=JAN, end_date=add_days(JAN, -5))

	def test_an_end_date_before_the_trial_ends_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 30), end_date=add_days(JAN, 10))

	def test_an_income_category_is_refused(self):
		income = make_category(self.tracker, category_type="Income").name
		with self.assertRaises(frappe.ValidationError):
			self.subscription(category=income)

	def test_a_group_category_is_refused(self):
		group = make_category(self.tracker, is_group=1).name
		with self.assertRaises(frappe.ValidationError):
			self.subscription(category=group)

	def test_an_account_from_another_tracker_is_refused(self):
		other = make_tracker().name
		with self.assertRaises(frappe.ValidationError):
			self.subscription(account=make_account(other, account_type="Bank").name)


class TestThePlanItLinksTo(SubscriptionFixture):
	"""A subscription owns the terms; the plan owns the money. It grows no schedule here."""

	def plan(self, **kwargs):
		kwargs.setdefault("account", self.account)
		kwargs.setdefault("category", self.category)
		return make_recurring(self.tracker, **kwargs)

	def test_a_plan_pays_it_and_the_subscription_posts_nothing(self):
		plan = self.plan(amount=499)
		sub = self.subscription(amount=499, recurring_transaction=plan.name)

		self.assertTrue(subscriptions.measure(sub).plan_agrees)
		self.assertEqual(
			frappe.db.count("Transaction", {"tracker": self.tracker}), 0, "a subscription posts nothing"
		)

	def test_a_disagreement_is_reported_rather_than_refused(self):
		"""Knowing about a rise before the standing order is updated is the normal order of
		events, not a mistake."""
		plan = self.plan(amount=499)
		sub = self.subscription(amount=649, recurring_transaction=plan.name)
		self.assertFalse(subscriptions.measure(sub).plan_agrees)

	def test_a_subscription_with_no_plan_has_no_opinion_about_one(self):
		self.assertIsNone(subscriptions.measure(self.subscription()).plan_agrees)

	def test_an_income_plan_is_refused(self):
		income = make_category(self.tracker, category_type="Income").name
		plan = self.plan(transaction_type="Income", category=income)
		with self.assertRaises(frappe.ValidationError):
			self.subscription(recurring_transaction=plan.name)

	def test_one_plan_pays_one_subscription(self):
		"""Two would each claim the same money and the spend would count it twice."""
		plan = self.plan()
		self.subscription(recurring_transaction=plan.name)
		with self.assertRaises(frappe.ValidationError):
			self.subscription(recurring_transaction=plan.name)

	def test_a_plan_from_another_tracker_is_refused(self):
		other = make_tracker().name
		plan = make_recurring(
			other,
			account=make_account(other, account_type="Bank").name,
			category=make_category(other, category_type="Expense").name,
		)
		with self.assertRaises(frappe.ValidationError):
			self.subscription(recurring_transaction=plan.name)


class TestActions(SubscriptionFixture):
	def test_a_price_change_is_dated_when_it_happened(self):
		"""A letter saying the price went up on the 1st arrives on the 9th."""
		sub = self.subscription(amount=499, start_date=JAN)
		sub.record_price_change(649, effective_from=add_days(JAN, 30), note="Annual rise")

		sub.reload()
		self.assertMoneyEqual(sub.amount, 649)
		self.assertMoneyEqual(subscriptions.price_at(sub, add_days(JAN, 20)), 499)
		self.assertMoneyEqual(subscriptions.price_at(sub, add_days(JAN, 31)), 649)

	def test_a_price_change_of_zero_is_refused(self):
		sub = self.subscription(amount=499)
		self.assertRaises(frappe.ValidationError, sub.record_price_change, 0)

	def test_cancelling_records_the_date_it_runs_until(self):
		sub = self.subscription(amount=499, start_date=JAN)
		sub.cancel_subscription(add_days(JAN, 150))

		sub.reload()
		self.assertEqual(sub.status, "Cancelled")
		self.assertEqual(getdate(sub.end_date), add_days(JAN, 150))
		self.assertTrue(subscriptions.measure(sub, add_days(JAN, 60)).is_committed)

	def test_it_cannot_end_before_it_started(self):
		sub = self.subscription(start_date=JAN)
		self.assertRaises(frappe.ValidationError, sub.cancel_subscription, add_days(JAN, -1))


class TestReminders(SubscriptionFixture):
	"""`send_subscription_reminders` is site-wide, like the budget and bill jobs, so these
	assert on the subscription under test rather than on the job's return count."""

	def stamp(self, sub):
		return frappe.db.get_value("Money Subscription", sub.name, "last_reminder")

	def test_a_trial_running_out_is_announced_once_and_not_again(self):
		sub = self.subscription(start_date=posting_date(), trial_end_date=add_days(posting_date(), 3))
		subscriptions.send_subscription_reminders()
		first = self.stamp(sub)
		self.assertTrue(first)
		self.assertIn(subscriptions.TRIAL_ENDING, first)

		subscriptions.send_subscription_reminders()
		self.assertEqual(self.stamp(sub), first, "the same fact is announced once")

	def test_it_speaks_again_when_the_fact_changes(self):
		"""Next month's renewal is a different renewal, so it is said again.

		The stamp is keyed on the date as well as the outcome, which is what separates "the
		same fact" from "the same words about a different date".
		"""
		sub = self.subscription(start_date=JAN)
		subscriptions.send_subscription_reminders(as_of=getdate("2026-01-27"))
		february = self.stamp(sub)
		self.assertIn("2026-02-01", february)

		subscriptions.send_subscription_reminders(as_of=getdate("2026-02-25"))
		self.assertIn("2026-03-01", self.stamp(sub))
		self.assertNotEqual(self.stamp(sub), february)

	def test_a_closing_notice_window_is_announced(self):
		sub = self.subscription(start_date=JAN, notice_period_days=10)
		subscriptions.send_subscription_reminders(as_of=add_days(JAN, 19))
		self.assertIn(subscriptions.CANCEL_BY, self.stamp(sub))

	def test_a_renewal_far_off_is_not_announced(self):
		sub = self.subscription(start_date=JAN)
		subscriptions.send_subscription_reminders(as_of=add_days(JAN, 5))
		self.assertIsNone(self.stamp(sub))

	def test_one_that_opted_out_is_not_announced(self):
		sub = self.subscription(start_date=JAN, notify_on_renewal=0)
		subscriptions.send_subscription_reminders(as_of=add_days(JAN, 27))
		self.assertIsNone(self.stamp(sub))

	def test_a_paused_one_is_not_announced(self):
		sub = self.subscription(start_date=JAN, status="Paused")
		subscriptions.send_subscription_reminders(as_of=add_days(JAN, 27))
		self.assertIsNone(self.stamp(sub))

	def test_the_notification_reaches_the_tracker_owner(self):
		sub = self.subscription(start_date=posting_date(), trial_end_date=add_days(posting_date(), 3))
		subscriptions.send_subscription_reminders()

		owner = frappe.db.get_value("Tracker", self.tracker, "owner_user")
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{
					"document_type": "Money Subscription",
					"document_name": sub.name,
					"for_user": owner,
				},
			)
		)


class TestWidgets(SubscriptionFixture):
	def test_the_spend_card_totals_the_monthly_equivalents(self):
		self.subscription(amount=499, start_date=JAN)
		self.subscription(amount=1200, billing_frequency="Yearly", start_date=JAN)

		card = subscriptions_api.card_subscription_spend(
			{"tracker": self.tracker, "as_of": str(add_days(JAN, 5))}
		)
		self.assertIn("599", card)

	def test_the_trials_card_counts_rather_than_totals(self):
		"""The amount does not change what has to be done about it."""
		self.subscription(start_date=JAN, trial_end_date=add_days(JAN, 3))
		card = subscriptions_api.card_trials_ending({"tracker": self.tracker, "as_of": str(JAN)})
		self.assertEqual(card, "1 ending")

	def test_the_trials_card_says_so_when_there_are_none(self):
		self.subscription(start_date=JAN)
		card = subscriptions_api.card_trials_ending({"tracker": self.tracker, "as_of": str(JAN)})
		self.assertEqual(card, "No trials")

	def test_the_api_formats_money_against_the_trackers_currency(self):
		"""A client formats against System Settings' instead (§33)."""
		self.subscription(amount=499, start_date=JAN)
		payload = subscriptions_api.get_subscriptions(self.tracker, as_of=str(add_days(JAN, 5)))
		self.assertIn("499", payload["subscriptions"][0].formatted["amount"])


class TestFormWiring(MoneyTrackerTestCase):
	"""The form script and the DocType JSON restate things Python knows. These fail if they
	drift — the same guard `test_goals.py` and `test_recurring.py` apply."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		app = Path(frappe.get_app_path("moneytracker"))
		cls.folder = app / "money_tracker/doctype/money_subscription"
		cls.form_js = (cls.folder / "money_subscription.js").read_text()
		cls.doctype_json = frappe.parse_json((cls.folder / "money_subscription.json").read_text())

	def test_the_form_colours_every_outcome(self):
		block = self.form_js.split("const OUTCOME_COLOR = {")[1].split("};")[0]
		for outcome in (
			subscriptions.ACTIVE,
			subscriptions.NOT_STARTED,
			subscriptions.TRIALING,
			subscriptions.TRIAL_ENDING,
			subscriptions.CANCEL_BY,
			subscriptions.NOTICE_PASSED,
			subscriptions.RENEWING_SOON,
			subscriptions.PAUSED,
			subscriptions.CANCELLED,
			subscriptions.EXPIRED,
		):
			self.assertIn(outcome.replace(" ", ""), block.replace('"', "").replace(" ", ""))

	def test_the_billing_select_matches_the_frequency_table(self):
		"""One table of frequencies, shared with plans. Two would disagree."""
		field = next(row for row in self.doctype_json["fields"] if row["fieldname"] == "billing_frequency")
		self.assertEqual(tuple(field["options"].split("\n")), recurring.FREQUENCY_OPTIONS)

	def test_the_status_select_holds_only_the_users_own_decisions(self):
		"""Everything derived — renewing, trialing, expired — must not be selectable, or the
		document would carry two answers to the same question."""
		field = next(row for row in self.doctype_json["fields"] if row["fieldname"] == "status")
		self.assertEqual(field["options"].split("\n"), ["Active", "Paused", "Cancelled"])

	def test_the_form_calls_a_method_that_exists(self):
		self.assertIn("moneytracker.money_tracker.api.subscriptions.get_subscription_progress", self.form_js)
		self.assertTrue(callable(subscriptions_api.get_subscription_progress))
