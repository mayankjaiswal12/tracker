# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Budgets: the period calendar, the rollover, the outcome words and the widgets over them.

A budget is measured from the ledger on read, so what is guarded here is that the
measurement agrees with the ledger the ERPNext reports are drawn from — and that the words
on top of it ("Nearing Limit", "Over Budget") mean the same thing in the card, the chart and
the progress bar, because all three read them from one place.

The rollover gets a class of its own. It is the one figure in the app that depends on
periods the user is no longer looking at, and the one most easily got wrong by an off-by-one
at either end of the window.

The wiring is guarded at the bottom: a period is a string in three files at once — a Select
in the DocType JSON, a filter in a chart source's `.js`, and a key in `PERIODS` — and only
one of those three fails loudly on its own.
"""

import json
import re

import frappe
from frappe.utils import add_days, add_months, add_to_date, get_first_day, get_last_day, getdate

from moneytracker.money_tracker.api import budgets as budgets_api
from moneytracker.money_tracker.dashboard_chart_source.money_budget_actuals import (
	money_budget_actuals as budget_chart,
)
from moneytracker.money_tracker.services import budgets
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_budget,
	make_category,
	make_tracker,
	make_transaction,
	make_user,
)


def app_path(*parts):
	return frappe.get_app_path("moneytracker", "money_tracker", *parts)


def read(*parts):
	with open(app_path(*parts)) as f:
		return f.read()


class BudgetFixture(MoneyTrackerTestCase):
	"""A fresh tracker, account and category for **every** test, not for every class.

	`FrappeTestCase` rolls back once per class, so one test's spending and one test's budgets
	are still there for the next one. Budgets feel that harder than most fixtures do: an
	envelope is measured over a whole period, so a stray transaction from three tests ago
	lands inside the window, and `Money Budget` refuses a second live envelope over the same
	category on the same clock — which is precisely what a shared fixture keeps trying to
	build.
	"""

	def setUp(self):
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.category = make_category(self.tracker).name
		self.month_start = getdate(get_first_day(self.date))
		self.month_end = getdate(get_last_day(self.date))

	def spend(self, amount, category=None, date=None, transaction_type="Expense"):
		return make_transaction(
			transaction_type,
			amount,
			self.account,
			tracker=self.tracker,
			category=category or self.category,
			date=date or self.date,
		)


class TestBudgetPeriods(MoneyTrackerTestCase):
	"""The calendar, on its own. No money, no documents — just where a period begins and ends.

	Periods are calendar-aligned rather than anchored to the budget's start date, so that a
	budget's month is the same month the dashboard's "Expenses This Month" card counts and the
	trend chart plots. Anchoring to the start date would give a budget created on the 20th a
	private calendar nothing else in the app shares.
	"""

	def test_a_monthly_period_is_a_calendar_month(self):
		self.assertEqual(
			budgets.period_bounds("Monthly", "2026-08-19"),
			(getdate("2026-08-01"), getdate("2026-08-31")),
		)

	def test_a_quarterly_period_is_a_calendar_quarter(self):
		self.assertEqual(
			budgets.period_bounds("Quarterly", "2026-08-19"),
			(getdate("2026-07-01"), getdate("2026-09-30")),
		)

	def test_a_yearly_period_is_a_calendar_year(self):
		self.assertEqual(
			budgets.period_bounds("Yearly", "2026-08-19"),
			(getdate("2026-01-01"), getdate("2026-12-31")),
		)

	def test_a_weekly_period_is_seven_days_long(self):
		first, last = budgets.period_bounds("Weekly", "2026-08-19")
		self.assertEqual((last - first).days, 6)
		self.assertLessEqual(first, getdate("2026-08-19"))
		self.assertGreaterEqual(last, getdate("2026-08-19"))

	def test_an_unknown_period_is_named_in_the_error(self):
		with self.assertRaises(frappe.ValidationError):
			budgets.period_bounds("Fortnightly", "2026-08-19")

	def test_one_row_per_period_up_to_the_measuring_date(self):
		rows = budgets.iter_periods("Monthly", "2026-05-10", "2026-08-19")

		self.assertEqual([row.label for row in rows], ["May 2026", "Jun 2026", "Jul 2026", "Aug 2026"])

	def test_the_first_period_is_clipped_at_the_start_date(self):
		"""Money spent before the budget existed was not spent against it."""
		first = budgets.iter_periods("Monthly", "2026-05-10", "2026-08-19")[0]

		self.assertEqual(first.period_start, getdate("2026-05-01"))
		self.assertEqual(first.from_date, getdate("2026-05-10"))
		self.assertEqual(first.to_date, getdate("2026-05-31"))

	def test_the_last_period_is_clipped_at_the_measuring_date(self):
		last = budgets.iter_periods("Monthly", "2026-05-10", "2026-08-19")[-1]

		self.assertEqual(last.period_end, getdate("2026-08-31"))
		self.assertEqual(last.to_date, getdate("2026-08-19"))

	def test_an_end_date_closes_the_last_period_early(self):
		rows = budgets.iter_periods("Monthly", "2026-05-10", "2026-08-19", end_date="2026-08-10")

		self.assertEqual(rows[-1].to_date, getdate("2026-08-10"))


class TestBudgetMeasurement(BudgetFixture):
	"""One month, one envelope, and what does and does not come out of it.

	The tree is Food (group) → Groceries, so the roll-up has something to roll up, and there
	is a second unrelated category to prove the envelope does not reach it.
	"""

	def setUp(self):
		super().setUp()
		self.food = make_category(self.tracker, category_name="Food", is_group=1).name
		self.groceries = make_category(
			self.tracker, category_name="Groceries", parent_category=self.food
		).name
		self.fuel = make_category(self.tracker, category_name="Fuel").name
		self.category = self.groceries

	def budget(self, **kwargs):
		kwargs.setdefault("category", self.groceries)
		return make_budget(self.tracker, **kwargs)

	def test_spending_in_the_category_comes_out_of_the_envelope(self):
		self.spend(2500)
		measured = budgets.measure(self.budget(budget_amount=10000), self.date)

		self.assertMoneyEqual(measured.spent, 2500)
		self.assertMoneyEqual(measured.remaining, 7500)
		self.assertMoneyEqual(measured.used_percent, 25)

	def test_spending_in_another_category_does_not(self):
		self.spend(4000, category=self.fuel)
		measured = budgets.measure(self.budget(budget_amount=10000), self.date)

		self.assertMoneyEqual(measured.spent, 0)

	def test_a_budget_on_a_group_rolls_up_its_children(self):
		"""The usual case: an envelope for Food is meant to cover Groceries with it."""
		self.spend(1800)
		measured = budgets.measure(self.budget(category=self.food, budget_amount=10000), self.date)

		self.assertMoneyEqual(measured.spent, 1800)

	def test_a_budget_with_no_category_covers_the_whole_tracker(self):
		"""Including a category the envelope was never pointed at."""
		budget = self.budget(category=None, budget_amount=100000)
		before = budgets.measure(budget, self.date).spent
		self.spend(700, category=self.fuel)

		self.assertMoneyEqual(budgets.measure(budget, self.date).spent - before, 700)

	def test_a_refund_gives_the_envelope_its_money_back(self):
		"""§62 — a refund reduces spending rather than counting as income."""
		self.spend(3000)
		budget = self.budget(budget_amount=10000)
		before = budgets.measure(budget, self.date).spent
		self.spend(1200, transaction_type="Refund")

		self.assertMoneyEqual(before - budgets.measure(budget, self.date).spent, 1200)

	def test_a_transfer_is_not_spending(self):
		"""Moving money between two of your own accounts empties no envelope."""
		destination = make_account(self.tracker, account_type="Savings").name
		budget = self.budget(category=None, budget_amount=100000)
		before = budgets.measure(budget, self.date).spent
		make_transaction(
			"Transfer",
			9000,
			self.account,
			tracker=self.tracker,
			destination_account=destination,
			date=self.date,
		)

		self.assertMoneyEqual(budgets.measure(budget, self.date).spent, before)

	def test_spending_before_the_budget_started_does_not_count(self):
		last_month = getdate(add_months(self.month_start, -1))
		self.spend(6000, date=last_month)
		measured = budgets.measure(self.budget(budget_amount=10000), self.date)

		self.assertMoneyEqual(measured.spent, 0)

	def test_a_budget_measured_before_it_starts_has_not_started(self):
		budget = self.budget(start_date=add_months(self.month_start, 1), budget_amount=10000)
		measured = budgets.measure(budget, self.date)

		self.assertEqual(measured.outcome, budgets.NOT_STARTED)
		self.assertMoneyEqual(measured.spent, 0)
		self.assertMoneyEqual(measured.available, 10000)

	def test_the_period_that_is_measured_is_the_one_holding_the_date(self):
		measured = budgets.measure(self.budget(budget_amount=10000), self.date)

		self.assertEqual(measured.period_start, self.month_start)
		self.assertEqual(measured.period_end, getdate(get_last_day(self.date)))

	def test_a_finished_budget_keeps_its_closing_period(self):
		"""Without the clamp, an ended budget opens a fresh empty envelope every month."""
		ended = self.budget(budget_amount=10000, end_date=self.date)
		self.spend(4000)

		later = budgets.measure(ended, add_months(self.date, 3))

		self.assertEqual(later.period_end, getdate(get_last_day(self.date)))
		self.assertMoneyEqual(later.spent, 4000)
		self.assertTrue(later.ended)


class TestBudgetRollover(BudgetFixture):
	"""Three months, 10,000 an envelope, and 6,000 spent in each of the first two.

	Every figure below turns on which periods are counted and where each of them stops, so
	the fixture is deliberately arithmetic anybody can do in their head: 4,000 left over
	twice.
	"""

	def setUp(self):
		super().setUp()
		self.months = [getdate(add_months(self.month_start, -offset)) for offset in (2, 1, 0)]
		for month_start in self.months[:2]:
			self.spend(6000, date=add_days(month_start, 4))

	def budget(self, **kwargs):
		kwargs.setdefault("category", self.category)
		kwargs.setdefault("budget_amount", 10000)
		kwargs.setdefault("start_date", self.months[0])
		return make_budget(self.tracker, **kwargs)

	def test_without_rollover_every_period_starts_at_the_full_amount(self):
		measured = budgets.measure(self.budget(rollover=0), self.date)

		self.assertMoneyEqual(measured.carried_in, 0)
		self.assertMoneyEqual(measured.available, 10000)

	def test_rollover_carries_what_was_left_of_the_earlier_periods(self):
		measured = budgets.measure(self.budget(rollover=1), self.date)

		self.assertMoneyEqual(measured.carried_in, 8000)
		self.assertMoneyEqual(measured.available, 18000)
		self.assertMoneyEqual(measured.spent, 0)

	def test_rollover_carries_an_overspend_too(self):
		"""An envelope that quietly forgets last month is two budgets wearing one name."""
		self.spend(30000, date=add_days(self.months[1], 8))
		measured = budgets.measure(self.budget(rollover=1), self.date)

		# 4,000 left in the first month, 26,000 overspent in the second.
		self.assertMoneyEqual(measured.carried_in, -22000)
		self.assertMoneyEqual(measured.available, -12000)
		self.assertEqual(measured.outcome, budgets.OVER_BUDGET)

	def test_an_envelope_already_eaten_reads_as_fully_used(self):
		"""No division by zero, and no flattering 0% on a period with nothing left in it."""
		self.spend(30000, date=add_days(self.months[1], 9))
		measured = budgets.measure(self.budget(rollover=1), self.date)

		self.assertMoneyEqual(measured.used_percent, 100)

	def test_the_current_period_is_never_carried_into_itself(self):
		measured = budgets.measure(self.budget(rollover=1), add_days(self.months[0], 20))

		self.assertMoneyEqual(measured.carried_in, 0)
		self.assertMoneyEqual(measured.spent, 6000)

	def test_history_holds_the_finished_periods_oldest_first(self):
		measured = budgets.measure(self.budget(rollover=1), self.date)

		self.assertEqual([row["spent"] for row in measured.history], [6000, 6000])
		self.assertLess(measured.history[0]["period_end"], measured.history[1]["period_end"])

	def test_history_is_capped_without_capping_the_rollover(self):
		"""The rollover still walks every period; only what comes *back* is bounded."""
		long_running = self.budget(rollover=1, start_date=add_months(self.month_start, -20))
		measured = budgets.measure(long_running, self.date)

		self.assertEqual(len(measured.history), budgets.HISTORY_LIMIT)
		# 21 finished periods at 10,000 each, less the 12,000 actually spent.
		self.assertMoneyEqual(measured.carried_in, 20 * 10000 - 12000)


class TestBudgetOutcomes(BudgetFixture):
	"""The six words, on one 30,000 envelope with a threshold of 80%.

	Every one of them is measured on the **last day of the month**, so the pace is 100% and
	only the money decides — except the two tests that are explicitly about pace.
	"""

	def outcome(self, as_of=None, **kwargs):
		kwargs.setdefault("category", self.category)
		kwargs.setdefault("budget_amount", 30000)
		kwargs.setdefault("alert_threshold", 80)
		budget = make_budget(self.tracker, **kwargs)
		return budgets.measure(budget, as_of or self.month_end).outcome

	def test_nothing_spent_is_no_spend(self):
		self.assertEqual(self.outcome(), budgets.NO_SPEND)

	def test_comfortably_under_is_within_budget(self):
		self.spend(9000)
		self.assertEqual(self.outcome(), budgets.WITHIN_BUDGET)

	def test_past_the_threshold_is_nearing_the_limit(self):
		self.spend(24000)  # 80% of 30,000, exactly on the line
		self.assertEqual(self.outcome(), budgets.NEARING_LIMIT)

	def test_past_the_envelope_is_over_budget(self):
		self.spend(33000)
		self.assertEqual(self.outcome(), budgets.OVER_BUDGET)

	def test_spending_exactly_the_envelope_is_not_yet_over(self):
		"""Nothing has been overspent at 100%, and the word has to stay honest about that."""
		self.spend(30000)
		measured = budgets.measure(
			make_budget(self.tracker, category=self.category, budget_amount=30000), self.month_end
		)

		self.assertMoneyEqual(measured.remaining, 0)
		self.assertEqual(measured.outcome, budgets.NEARING_LIMIT)

	def test_spending_faster_than_the_month_is_at_risk(self):
		"""Half the envelope gone on day two is a warning nothing else in the set would give."""
		self.spend(30000, date=self.month_start)
		outcome = self.outcome(as_of=add_days(self.month_start, 1), budget_amount=80000)

		self.assertEqual(outcome, budgets.AT_RISK)

	def test_the_same_spending_later_in_the_month_is_fine(self):
		"""The one outcome that can un-say itself: a month catches up with its own spending."""
		self.spend(30000, date=self.month_start)
		outcome = self.outcome(as_of=self.month_end, budget_amount=80000)

		self.assertEqual(outcome, budgets.WITHIN_BUDGET)

	def test_the_pace_marker_is_the_share_of_the_period_that_has_passed(self):
		budget = make_budget(self.tracker, category=self.category, budget_amount=30000)
		measured = budgets.measure(budget, self.month_end)

		self.assertEqual(measured.expected_percent, 100.0)
		self.assertEqual(measured.days_left, 1)

	def test_what_is_left_to_spend_per_remaining_day(self):
		budget = make_budget(self.tracker, category=self.category, budget_amount=30000)
		measured = budgets.measure(budget, self.month_end)

		# One day left, and everything unspent still available in it.
		self.assertMoneyEqual(measured.available_per_day, measured.remaining)

	def test_nothing_is_available_per_day_once_the_envelope_is_empty(self):
		self.spend(500)
		budget = make_budget(self.tracker, category=self.category, budget_amount=100)
		measured = budgets.measure(budget, self.month_end)

		self.assertIsNone(measured.available_per_day)


class TestMeasuringManyBudgets(MoneyTrackerTestCase):
	"""A tracker per test — two budgets over the same money is exactly what is refused."""

	def setUp(self):
		self.tracker = make_tracker().name

	def test_budgets_come_back_largest_envelope_first(self):
		small = make_budget(self.tracker, budget_amount=1000, category=make_category(self.tracker).name)
		large = make_budget(self.tracker, budget_amount=90000)

		measured = budgets.measure_budgets(self.tracker, self.date)
		names = [row.budget for row in measured]

		self.assertLess(names.index(large.name), names.index(small.name))

	def test_only_active_budgets_are_measured_by_default(self):
		paused = make_budget(self.tracker, status="Paused")

		measured = budgets.measure_budgets(self.tracker, self.date)

		self.assertNotIn(paused.name, [row.budget for row in measured])

	def test_one_trackers_budgets_never_include_anothers(self):
		mine = make_budget(self.tracker)
		theirs = make_budget(make_tracker().name)

		measured = [row.budget for row in budgets.measure_budgets(self.tracker, self.date)]

		self.assertIn(mine.name, measured)
		self.assertNotIn(theirs.name, measured)

	def test_measuring_can_be_narrowed_to_one_period(self):
		monthly = make_budget(self.tracker, period="Monthly")
		yearly = make_budget(self.tracker, period="Yearly")

		measured = [row.budget for row in budgets.measure_budgets(self.tracker, self.date, period="Yearly")]

		self.assertIn(yearly.name, measured)
		self.assertNotIn(monthly.name, measured)


class TestBudgetAlerts(BudgetFixture):
	"""The one thing on a budget that is stateful, and the reason it has to be.

	`last_alert` is bookkeeping about a message that was sent, not about the money — so the
	tests are all about *repetition*: the same fact must not be announced twice, and a fact
	that has genuinely changed must be.
	"""

	def setUp(self):
		super().setUp()
		self.user = make_user()
		frappe.db.set_value("Tracker", self.tracker, "owner_user", self.user)
		self.budget = make_budget(
			self.tracker, category=self.category, budget_amount=10000, alert_threshold=80
		)

	def alerts(self):
		return frappe.get_all(
			"Notification Log",
			filters={"document_type": "Money Budget", "document_name": self.budget.name},
			pluck="subject",
		)

	def test_a_healthy_budget_says_nothing(self):
		budgets.send_budget_alerts(self.date)

		self.assertEqual(self.alerts(), [])

	def test_crossing_the_threshold_notifies_the_tracker_owner(self):
		self.spend(8500)
		budgets.send_budget_alerts(self.date)

		self.assertEqual(len(self.alerts()), 1)
		self.assertIn(self.budget.budget_name, self.alerts()[0])
		self.assertEqual(
			frappe.db.get_value(
				"Notification Log",
				{"document_type": "Money Budget", "document_name": self.budget.name},
				"for_user",
			),
			self.user,
		)

	def test_the_same_warning_is_not_repeated_the_next_day(self):
		self.spend(8500)
		budgets.send_budget_alerts(self.date)
		budgets.send_budget_alerts(add_days(self.date, 1))

		self.assertEqual(len(self.alerts()), 1)

	def test_going_over_after_a_warning_is_worth_saying_again(self):
		self.spend(8500)
		budgets.send_budget_alerts(self.date)
		self.spend(3000)
		budgets.send_budget_alerts(self.date)

		self.assertEqual(len(self.alerts()), 2)

	def test_a_budget_that_asked_not_to_be_told_is_not_told(self):
		self.budget.db_set("notify_on_alert", 0)
		self.spend(9500)
		budgets.send_budget_alerts(self.date)

		self.assertEqual(self.alerts(), [])

	def test_a_paused_budget_is_not_alerted_on(self):
		self.budget.db_set("status", "Paused")
		self.spend(9500)
		budgets.send_budget_alerts(self.date)

		self.assertEqual(self.alerts(), [])


class TestBudgetsApi(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user = make_user()
		cls.tracker = make_tracker(owner_user=cls.user).name
		cls.account = make_account(cls.tracker).name
		cls.category = make_category(cls.tracker).name
		cls.budget = make_budget(cls.tracker, category=cls.category, budget_amount=20000)
		make_transaction(
			"Expense", 5000, cls.account, tracker=cls.tracker, category=cls.category, date=cls.date
		)

	def test_one_budgets_progress_carries_formatted_figures(self):
		"""Money is formatted server-side against the budget's own currency (§33)."""
		progress = budgets_api.get_budget_progress(self.budget.name)

		self.assertMoneyEqual(progress["spent"], 5000)
		self.assertIn("5,000", progress["formatted"]["spent"])
		self.assertIn("20,000", progress["formatted"]["available"])

	def test_listing_the_budgets_on_a_tracker(self):
		listed = budgets_api.get_budgets(tracker=self.tracker)

		self.assertEqual([row.budget for row in listed["budgets"]], [self.budget.name])
		self.assertEqual(listed["tracker"], self.tracker)

	def test_a_budget_on_another_users_tracker_is_refused(self):
		with as_user(make_user()), self.assertRaises(frappe.PermissionError):
			budgets_api.get_budget_progress(self.budget.name)

	def test_another_users_tracker_is_refused(self):
		with as_user(make_user()), self.assertRaises(frappe.PermissionError):
			budgets_api.get_budgets(tracker=self.tracker)


class TestBudgetWidgets(MoneyTrackerTestCase):
	"""One kept envelope and one blown one, then the card and the chart over them."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user = make_user()
		cls.tracker = make_tracker(owner_user=cls.user).name
		cls.account = make_account(cls.tracker).name
		cls.kept_category = make_category(cls.tracker, category_name="Kept").name
		cls.blown_category = make_category(cls.tracker, category_name="Blown").name

		cls.kept = make_budget(
			cls.tracker, budget_name="Kept", category=cls.kept_category, budget_amount=50000
		)
		cls.blown = make_budget(
			cls.tracker, budget_name="Blown", category=cls.blown_category, budget_amount=1000
		)
		for category, amount in ((cls.kept_category, 1000), (cls.blown_category, 4000)):
			make_transaction(
				"Expense", amount, cls.account, tracker=cls.tracker, category=category, date=cls.date
			)

		cls.filters = {"tracker": cls.tracker}

	def test_the_fixture_is_one_kept_envelope_and_one_blown_one(self):
		measured = {row.budget_name: row.outcome for row in budgets.measure_budgets(self.tracker)}

		self.assertEqual(measured["Kept"], budgets.WITHIN_BUDGET)
		self.assertEqual(measured["Blown"], budgets.OVER_BUDGET)

	def test_the_card_counts_the_budgets_being_kept_to(self):
		self.assertEqual(budgets_api.card_budgets_on_track(self.filters), "1 of 2")

	def test_the_card_says_no_data_without_budgets(self):
		with as_user(make_user()):
			self.assertEqual(budgets_api.card_budgets_on_track({}), "—")

	def test_the_card_refuses_a_tracker_the_user_may_not_read(self):
		with as_user(make_user()), self.assertRaises(frappe.PermissionError):
			budgets_api.card_budgets_on_track(self.filters)

	def test_rendering_the_card_does_not_create_a_tracker(self):
		"""Painting a dashboard must not write — `find_tracker`, never `get_default_tracker`."""
		stranger = make_user()
		with as_user(stranger):
			budgets_api.card_budgets_on_track({})

		self.assertEqual(frappe.get_all("Tracker", filters={"owner_user": stranger}), [])

	def test_filters_may_arrive_as_a_json_string(self):
		self.assertEqual(
			budgets_api.card_budgets_on_track(json.dumps(self.filters)),
			budgets_api.card_budgets_on_track(self.filters),
		)

	def test_the_chart_draws_the_envelope_and_the_spending_side_by_side(self):
		result = budget_chart.get(chart={}, filters=self.filters)

		self.assertEqual(sorted(result["labels"]), ["Blown", "Kept"])
		self.assertEqual([dataset["name"] for dataset in result["datasets"]], ["Budget", "Spent"])

	def test_the_chart_plots_what_the_period_has_to_spend_not_what_was_typed(self):
		"""With rollover on, the bar to beat is the envelope plus whatever came into it."""
		result = budget_chart.get(chart={}, filters=self.filters)
		by_label = dict(zip(result["labels"], result["datasets"][1]["values"], strict=True))

		self.assertMoneyEqual(by_label["Blown"], 4000)
		self.assertMoneyEqual(by_label["Kept"], 1000)

	def test_the_chart_can_be_narrowed_to_one_period(self):
		"""On a tracker of its own: a stray budget here would show up in every other test."""
		tracker = make_tracker().name
		make_budget(tracker, budget_name="Monthly one", period="Monthly")
		yearly = make_budget(tracker, budget_name="Yearly one", period="Yearly")

		result = budget_chart.get(chart={}, filters={"tracker": tracker, "period": "Yearly"})

		self.assertEqual(result["labels"], [yearly.budget_name])

	def test_a_user_with_no_tracker_gets_an_empty_chart(self):
		with as_user(make_user()):
			self.assertEqual(budget_chart.get(chart={}, filters={}), {"labels": [], "datasets": []})

	def test_the_chart_refuses_a_tracker_the_user_may_not_read(self):
		with as_user(make_user()), self.assertRaises(frappe.PermissionError):
			budget_chart.get(chart={}, filters=self.filters)

	def test_the_shipped_chart_draws_through_its_own_name(self):
		"""The path the widget actually takes: chart name in, labels and datasets out."""
		self.assertTrue(frappe.db.exists("Dashboard Chart", "Budget vs Actual"))

		result = budget_chart.get(chart_name="Budget vs Actual", filters=self.filters)

		self.assertEqual(sorted(result["labels"]), ["Blown", "Kept"])


class TestBudgetWiring(MoneyTrackerTestCase):
	"""A period is a string in three files, and only one of them fails loudly on its own."""

	def test_every_period_is_fully_described(self):
		for period, spec in budgets.PERIODS.items():
			with self.subTest(period=period):
				self.assertTrue(callable(spec.first_day))
				self.assertTrue(callable(spec.last_day))
				self.assertTrue(spec.step)
				# One step forward from a period's first day must land in the next period.
				first = getdate(spec.first_day("2026-05-15"))
				self.assertGreater(getdate(add_to_date(first, **spec.step)), getdate(spec.last_day(first)))

	def test_the_select_lists_exactly_the_implemented_periods(self):
		"""A Select option with no calendar behind it is a budget that cannot be saved."""
		doctype = json.loads(read("doctype", "money_budget", "money_budget.json"))
		field = next(f for f in doctype["fields"] if f["fieldname"] == "period")

		self.assertEqual(tuple(field["options"].split("\n")), budgets.BUDGET_PERIOD_OPTIONS)

	def test_the_chart_source_filter_lists_every_period(self):
		source_js = read("dashboard_chart_source", "money_budget_actuals", "money_budget_actuals.js")
		listed = re.search(r"options:\s*\[\s*\"\",(.*?)\]", source_js, re.DOTALL)
		self.assertTrue(listed, "the period filter lists no options")

		options = tuple(re.findall(r'"([^"]+)"', listed.group(1)))
		self.assertEqual(options, budgets.BUDGET_PERIOD_OPTIONS)

	def test_the_client_script_has_a_colour_for_every_outcome(self):
		"""An outcome with no colour renders grey, which reads as "nothing spent"."""
		script = read("doctype", "money_budget", "money_budget.js")

		for outcome in (
			budgets.NOT_STARTED,
			budgets.NO_SPEND,
			budgets.WITHIN_BUDGET,
			budgets.AT_RISK,
			budgets.NEARING_LIMIT,
			budgets.OVER_BUDGET,
		):
			with self.subTest(outcome=outcome):
				self.assertIn(outcome, script)

	def test_the_alert_outcomes_are_the_unhealthy_ones(self):
		"""Nothing may be both fine and worth waking somebody up about."""
		self.assertEqual(set(budgets.ALERT_OUTCOMES) & set(budgets.HEALTHY_OUTCOMES), set())

	def test_the_doctype_reached_the_site(self):
		self.assertTrue(
			frappe.db.exists("DocType", "Money Budget"),
			"Money Budget is missing — run `bench --site <site> migrate`",
		)

	def test_the_daily_job_is_scheduled(self):
		"""An alert nothing calls is an alert that never arrives."""
		from moneytracker import hooks

		self.assertIn(
			"moneytracker.money_tracker.services.budgets.send_budget_alerts",
			hooks.scheduler_events["daily"],
		)
