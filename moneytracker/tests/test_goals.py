# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Goals: the six measures, the outcome words, and the widgets over them.

Every figure a goal shows is derived from the ledger on read, so what is guarded here is
that the derivation agrees with the ledger the ERPNext reports are drawn from — and that
the words on top of it ("On Track", "Breached") mean the same thing in the card, the chart
and the progress bar, because all three read them from one place.

The wiring is guarded too, at the bottom: a goal type is a string in three files at once —
a Select in the DocType JSON, a filter in a chart source's `.js`, and a key in
`GOAL_TYPES` — and only one of those three fails loudly on its own.
"""

import json
import re

import frappe
from frappe.utils import add_days, flt, get_first_day, get_last_day

from moneytracker.money_tracker.api import goals as goals_api
from moneytracker.money_tracker.dashboard_chart_source.money_goal_progress import (
	money_goal_progress as goal_chart,
)
from moneytracker.money_tracker.services import coa, goals
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_category,
	make_goal,
	make_tracker,
	make_transaction,
	make_user,
)


def app_path(*parts):
	return frappe.get_app_path("moneytracker", "money_tracker", *parts)


def read(*parts):
	with open(app_path(*parts)) as f:
		return f.read()


class TestSavingsGoals(MoneyTrackerTestCase):
	"""A pot with 20,000 put in ten days ago and 5,000 put in today.

	Which of those two figures counts is the whole point of `measure_basis`: a pot kept for
	one goal holds 25,000 towards it, while a goal started today on a shared account has had
	5,000 put towards it however much the account happens to contain.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.past = add_days(cls.date, -10)

		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.pot = make_account(cls.tracker, account_type="Savings").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		make_transaction("Income", 100000, cls.bank, tracker=cls.tracker, category=cls.salary, date=cls.past)
		make_transaction("Transfer", 20000, cls.bank, tracker=cls.tracker, destination_account=cls.pot, date=cls.past)
		make_transaction("Transfer", 5000, cls.bank, tracker=cls.tracker, destination_account=cls.pot)

	def savings_goal(self, **kwargs):
		kwargs.setdefault("target_account", self.pot)
		kwargs.setdefault("target_amount", 50000)
		return make_goal(self.tracker, goal_type="Savings", **kwargs)

	def test_contributions_count_only_what_went_in_since_the_start(self):
		goal = self.savings_goal(start_date=self.date)

		measured = goals.measure(goal, self.date)
		self.assertMoneyEqual(measured.current, 5000)
		self.assertEqual(measured.progress_percent, 10.0)

	def test_a_contribution_on_the_start_date_itself_counts(self):
		"""The baseline is the day *before* the start, or day one's saving would vanish."""
		goal = self.savings_goal(start_date=self.date)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 5000)

	def test_the_account_balance_basis_counts_everything_in_the_account(self):
		goal = self.savings_goal(start_date=self.date, measure_basis=goals.BASIS_BALANCE)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 25000)

	def test_a_declared_opening_amount_is_added_to_the_contributions(self):
		"""Money put aside before the app knew about it still counts towards the goal."""
		goal = self.savings_goal(start_date=self.date, opening_amount=20000)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 25000)

	def test_the_two_bases_agree_when_the_goal_starts_with_the_account(self):
		contributions = self.savings_goal(start_date=self.past)
		balance = self.savings_goal(start_date=self.past, measure_basis=goals.BASIS_BALANCE)

		self.assertMoneyEqual(
			goals.measure(contributions, self.date).current,
			goals.measure(balance, self.date).current,
		)

	def test_the_window_closes_on_the_deadline(self):
		"""A finished goal keeps its closing figure rather than quietly carrying on.

		Without the clamp, measuring a missed goal later would keep accumulating and turn it
		into an achieved one.
		"""
		goal = self.savings_goal(start_date=self.past, target_date=add_days(self.past, 2))

		measured = goals.measure(goal, self.date)
		self.assertMoneyEqual(measured.current, 20000)
		self.assertEqual(measured.window["to_date"], add_days(self.past, 2))

	def test_a_goal_measured_before_it_starts_has_not_started(self):
		goal = self.savings_goal(start_date=self.date)

		measured = goals.measure(goal, add_days(self.date, -1))
		self.assertEqual(measured.outcome, goals.NOT_STARTED)
		self.assertMoneyEqual(measured.current, 0)
		self.assertMoneyEqual(measured.remaining, 50000)

	def test_reaching_the_target_is_achieved(self):
		goal = self.savings_goal(start_date=self.date, target_amount=5000)

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.ACHIEVED)

	def test_a_cumulative_goal_can_be_achieved_before_its_deadline(self):
		"""The money is there. Nothing between now and the deadline can un-save it."""
		goal = self.savings_goal(
			start_date=self.date, target_amount=5000, target_date=add_days(self.date, 30)
		)

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.ACHIEVED)

	def test_a_deadline_passed_short_of_the_target_is_missed(self):
		goal = self.savings_goal(start_date=self.past, target_date=add_days(self.past, 1))

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.MISSED)

	def test_no_deadline_means_in_progress_rather_than_behind(self):
		"""There is no pace to be behind when no date was ever set."""
		goal = self.savings_goal(start_date=self.date)

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.outcome, goals.IN_PROGRESS)
		self.assertIsNone(measured.expected_percent)
		self.assertIsNone(measured.days_left)

	def test_pace_decides_between_on_track_and_behind(self):
		"""Six days into a ten-day window, 60% of the target should already be there."""
		window = {"start_date": add_days(self.date, -5), "target_date": add_days(self.date, 4)}

		behind = self.savings_goal(target_amount=10000, **window)
		on_track = self.savings_goal(target_amount=8000, **window)

		self.assertEqual(goals.measure(behind, self.date).expected_percent, 60.0)
		self.assertEqual(goals.measure(behind, self.date).outcome, goals.BEHIND)
		self.assertEqual(goals.measure(on_track, self.date).outcome, goals.ON_TRACK)

	def test_what_is_still_needed_per_day(self):
		goal = self.savings_goal(start_date=self.date, target_date=add_days(self.date, 9))

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.days_left, 10)
		self.assertMoneyEqual(measured.remaining, 45000)
		self.assertMoneyEqual(measured.required_per_period, 4500)

	def test_nothing_more_is_needed_once_the_target_is_met(self):
		goal = self.savings_goal(
			start_date=self.date, target_amount=5000, target_date=add_days(self.date, 9)
		)

		self.assertIsNone(goals.measure(goal, self.date).required_per_period)


class TestDebtPayoffGoals(MoneyTrackerTestCase):
	"""30,000 charged to a card ten days ago, 12,000 of it paid off today."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.past = add_days(cls.date, -10)

		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		make_transaction("Income", 100000, cls.bank, tracker=cls.tracker, category=cls.salary, date=cls.past)
		make_transaction("Expense", 30000, cls.card, tracker=cls.tracker, category=cls.food, date=cls.past)
		make_transaction(
			"Credit Card Payment", 12000, cls.bank, tracker=cls.tracker, destination_account=cls.card
		)

	def payoff_goal(self, **kwargs):
		kwargs.setdefault("target_account", self.card)
		kwargs.setdefault("target_amount", 30000)
		kwargs.setdefault("start_date", self.date)
		return make_goal(self.tracker, goal_type="Debt Payoff", **kwargs)

	def test_progress_is_the_debt_that_has_been_cleared(self):
		"""Opening left empty: the debt as it stood the day before the goal started."""
		goal = self.payoff_goal()

		measured = goals.measure(goal, self.date)
		self.assertMoneyEqual(measured.current, 12000)
		self.assertEqual(measured.progress_percent, 40.0)

	def test_a_declared_opening_amount_wins(self):
		"""For a debt taken on before the app was keeping books."""
		goal = self.payoff_goal(opening_amount=20000, target_amount=20000)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 2000)

	def test_a_debt_that_grew_reads_as_negative_progress(self):
		"""Reported rather than hidden: 10,000 declared against 18,000 still owed."""
		goal = self.payoff_goal(
			opening_amount=10000, target_amount=10000, target_date=add_days(self.date, 10)
		)

		measured = goals.measure(goal, self.date)
		self.assertMoneyEqual(measured.current, -8000)
		self.assertEqual(measured.outcome, goals.BEHIND)

	def test_clearing_the_whole_debt_is_achieved(self):
		goal = self.payoff_goal(target_amount=12000)

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.ACHIEVED)


class TestSpendingLimits(MoneyTrackerTestCase):
	"""One window: groceries 3,000 less a 500 refund, restaurants 2,000, fuel 1,000.

	Plus 9,000 of groceries twenty days back, which is outside the window and must not count.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.pot = make_account(cls.tracker, account_type="Savings").name

		cls.food = make_category(cls.tracker, category_type="Expense", is_group=1).name
		cls.groceries = make_category(cls.tracker, category_type="Expense", parent_category=cls.food).name
		cls.restaurants = make_category(cls.tracker, category_type="Expense", parent_category=cls.food).name
		cls.fuel = make_category(cls.tracker, category_type="Expense").name

		def post(transaction_type, amount, category, date=None):
			make_transaction(
				transaction_type,
				amount,
				cls.bank,
				tracker=cls.tracker,
				category=category,
				date=date or cls.date,
			)

		post("Expense", 3000, cls.groceries)
		post("Refund", 500, cls.groceries)
		post("Expense", 2000, cls.restaurants)
		post("Expense", 1000, cls.fuel)
		post("Expense", 9000, cls.groceries, date=add_days(cls.date, -20))
		make_transaction("Transfer", 4000, cls.bank, tracker=cls.tracker, destination_account=cls.pot)

		cls.window = {"start_date": add_days(cls.date, -5), "target_date": add_days(cls.date, 5)}

	def limit(self, **kwargs):
		kwargs.setdefault("target_amount", 5000)
		return make_goal(self.tracker, goal_type="Spending Limit", **self.window, **kwargs)

	def test_a_limit_counts_net_spend_in_its_category(self):
		"""3,000 spent less 500 refunded — a refund reduces spending, it is not income (§62)."""
		goal = self.limit(category=self.groceries)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 2500)

	def test_a_limit_on_a_group_rolls_up_its_children(self):
		"""2,500 of groceries plus 2,000 of restaurants — the heading total ERPNext will not give."""
		goal = self.limit(category=self.food)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 4500)

	def test_a_limit_with_no_category_covers_the_whole_tracker(self):
		goal = self.limit()

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 5500)

	def test_spending_outside_the_window_does_not_count(self):
		"""The 9,000 twenty days ago would breach every limit here."""
		goal = self.limit(category=self.groceries, target_amount=100000)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 2500)

	def test_a_transfer_is_not_spending(self):
		"""Moving 4,000 into a savings account spends nothing (§76)."""
		goal = self.limit(target_amount=100000)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 5500)

	def test_staying_under_the_cap_is_on_track(self):
		goal = self.limit(category=self.groceries, target_amount=5000)

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.direction, goals.LIMIT)
		self.assertEqual(measured.outcome, goals.ON_TRACK)
		self.assertMoneyEqual(measured.remaining, 2500)

	def test_going_over_the_cap_is_breached(self):
		goal = self.limit(category=self.groceries, target_amount=2000)

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.outcome, goals.BREACHED)
		self.assertMoneyEqual(measured.remaining, -500)

	def test_a_limit_stays_breached_even_before_the_deadline(self):
		"""Unlike a savings goal, which can recover: the money is already spent."""
		goal = self.limit(category=self.groceries, target_amount=2000)

		self.assertEqual(goals.measure(goal, add_days(self.date, 4)).outcome, goals.BREACHED)

	def test_spending_faster_than_the_window_is_at_risk(self):
		"""Six days into ten, 2,500 of a 3,000 cap is 83% spent against 60% elapsed."""
		goal = self.limit(category=self.groceries, target_amount=3000)

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.AT_RISK)

	def test_a_window_that_ended_under_the_cap_is_achieved(self):
		goal = self.limit(category=self.groceries, target_amount=5000)

		self.assertEqual(goals.measure(goal, add_days(self.date, 6)).outcome, goals.ACHIEVED)


class TestIncomeAndRateGoals(MoneyTrackerTestCase):
	"""Salary 100,000 and freelance 20,000 earned today, 40,000 spent."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.salary = make_category(cls.tracker, category_type="Income").name
		cls.freelance = make_category(cls.tracker, category_type="Income").name
		cls.rent = make_category(cls.tracker, category_type="Expense").name

		def post(transaction_type, amount, category):
			make_transaction(transaction_type, amount, cls.bank, tracker=cls.tracker, category=category)

		post("Income", 100000, cls.salary)
		post("Income", 20000, cls.freelance)
		post("Expense", 40000, cls.rent)

		cls.window = {"start_date": get_first_day(cls.date), "target_date": get_last_day(cls.date)}

	def test_an_income_target_counts_one_category(self):
		goal = make_goal(
			self.tracker,
			goal_type="Income Target",
			category=self.freelance,
			target_amount=50000,
			**self.window,
		)

		measured = goals.measure(goal, self.date)
		self.assertMoneyEqual(measured.current, 20000)
		self.assertEqual(measured.direction, goals.ACCUMULATE)

	def test_an_income_target_with_no_category_counts_every_source(self):
		goal = make_goal(
			self.tracker, goal_type="Income Target", target_amount=200000, **self.window
		)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 120000)

	def test_a_savings_rate_is_the_share_of_income_kept(self):
		"""(120,000 - 40,000) / 120,000."""
		goal = make_goal(
			self.tracker, goal_type="Savings Rate Target", target_percent=30, **self.window
		)

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.unit, goals.PERCENT)
		self.assertEqual(flt(measured.current, 1), 66.7)

	def test_a_rate_above_target_is_only_on_track_until_the_window_closes(self):
		"""A month can start well and end badly, so a rate is not banked the way money is."""
		goal = make_goal(
			self.tracker, goal_type="Savings Rate Target", target_percent=30, **self.window
		)

		self.assertEqual(goals.measure(goal, self.date).outcome, goals.ON_TRACK)
		self.assertEqual(
			goals.measure(goal, add_days(get_last_day(self.date), 1)).outcome, goals.ACHIEVED
		)

	def test_a_rate_is_never_paced_against_elapsed_time(self):
		"""Half the month gone does not mean half the rate is due."""
		goal = make_goal(
			self.tracker, goal_type="Savings Rate Target", target_percent=30, **self.window
		)

		self.assertIsNone(goals.measure(goal, self.date).expected_percent)

	def test_a_rate_with_no_income_is_no_data_rather_than_zero(self):
		"""0/0 is not 0% — spending with nothing coming in has no savings rate at all."""
		tracker = make_tracker().name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Expense").name
		make_transaction("Expense", 100, account, tracker=tracker, category=category)

		goal = make_goal(tracker, goal_type="Savings Rate Target", target_percent=30, **self.window)

		measured = goals.measure(goal, self.date)
		self.assertEqual(measured.outcome, goals.NO_DATA)
		self.assertIsNone(measured.current)
		self.assertIsNone(measured.progress_percent)


class TestNetWorthGoals(MoneyTrackerTestCase):
	"""120,000 earned and 40,000 spent from a bank, with 2,000 owed on a card.

	Its own class rather than a test alongside the rate goals: `FrappeTestCase` rolls back once
	per class, so posting a transaction inside one test changes every figure the tests after it
	in that class are asserting.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		bank = make_account(cls.tracker, account_type="Bank").name
		card = make_account(cls.tracker, account_type="Credit Card").name
		salary = make_category(cls.tracker, category_type="Income").name
		rent = make_category(cls.tracker, category_type="Expense").name

		make_transaction("Income", 120000, bank, tracker=cls.tracker, category=salary)
		make_transaction("Expense", 40000, bank, tracker=cls.tracker, category=rent)
		make_transaction("Expense", 2000, card, tracker=cls.tracker, category=rent)

	def test_a_net_worth_target_is_assets_minus_liabilities(self):
		goal = make_goal(self.tracker, goal_type="Net Worth Target", target_amount=200000)

		self.assertMoneyEqual(goals.measure(goal, self.date).current, 78000)

	def test_a_net_worth_target_needs_no_account_or_category(self):
		"""It is the one goal that spans every account on the tracker rather than picking one."""
		goal = make_goal(self.tracker, goal_type="Net Worth Target", target_amount=200000)

		measured = goals.measure(goal, self.date)
		self.assertIsNone(measured.target_account)
		self.assertEqual(measured.progress_percent, 39.0)


class TestMeasuringManyGoals(MoneyTrackerTestCase):
	"""Each test builds its own tracker: the class-level rollback means goals created in one
	test are still there in the next, and every assertion here counts them."""

	def fixture(self):
		tracker = make_tracker().name
		return tracker, make_account(tracker, account_type="Savings").name

	def test_goals_come_back_soonest_deadline_first(self):
		"""A deadline is what makes a goal urgent, and an undated one is never the most urgent."""
		tracker, pot = self.fixture()
		undated = make_goal(tracker, goal_type="Savings", target_account=pot)
		later = make_goal(
			tracker, goal_type="Savings", target_account=pot, target_date=add_days(self.date, 30)
		)
		sooner = make_goal(
			tracker, goal_type="Savings", target_account=pot, target_date=add_days(self.date, 2)
		)

		measured = goals.measure_goals(tracker, self.date)
		self.assertEqual([row.goal for row in measured], [sooner.name, later.name, undated.name])

	def test_only_active_goals_are_measured_by_default(self):
		"""A paused goal is still a goal; it is just not what the dashboard is counting."""
		tracker, pot = self.fixture()
		make_goal(tracker, goal_type="Savings", target_account=pot, status="Paused")
		active = make_goal(tracker, goal_type="Savings", target_account=pot)

		measured = goals.measure_goals(tracker, self.date)
		self.assertEqual([row.goal for row in measured], [active.name])
		self.assertEqual(len(goals.measure_goals(tracker, self.date, status="Paused")), 1)
		self.assertEqual(len(goals.measure_goals(tracker, self.date, status=None)), 2)

	def test_one_trackers_goals_never_include_anothers(self):
		tracker, pot = self.fixture()
		make_goal(tracker, goal_type="Savings", target_account=pot)

		self.assertEqual(goals.measure_goals(make_tracker().name, self.date), [])


class TestGoalIsolation(MoneyTrackerTestCase):
	"""Two trackers whose savings accounts share one ERPNext Account.

	The same trap as `balances.py`: `coa.get_or_create_ledger_account` matches on account name
	and ignores the parent, so two people who both call an account "Savings" post into one
	ledger account and only the Tracker dimension tells them apart.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shared = f"Shared Pot {frappe.generate_hash(length=6)}"

		cls.tracker_a = make_tracker().name
		cls.tracker_b = make_tracker().name
		cls.pot_a = make_account(cls.tracker_a, account_name=shared, account_type="Savings").name
		cls.pot_b = make_account(cls.tracker_b, account_name=shared, account_type="Savings").name
		income_a = make_category(cls.tracker_a, category_type="Income").name
		income_b = make_category(cls.tracker_b, category_type="Income").name

		make_transaction("Income", 100, cls.pot_a, tracker=cls.tracker_a, category=income_a)
		make_transaction("Income", 4242, cls.pot_b, tracker=cls.tracker_b, category=income_b)

	def test_each_goal_measures_only_its_own_tracker(self):
		goal_a = make_goal(
			self.tracker_a, goal_type="Savings", target_account=self.pot_a, measure_basis=goals.BASIS_BALANCE
		)
		goal_b = make_goal(
			self.tracker_b, goal_type="Savings", target_account=self.pot_b, measure_basis=goals.BASIS_BALANCE
		)

		self.assertMoneyEqual(goals.measure(goal_a, self.date).current, 100)
		self.assertMoneyEqual(goals.measure(goal_b, self.date).current, 4242)


class TestGoalsApi(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.pot = make_account(cls.tracker, account_type="Savings").name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		make_transaction("Income", 50000, cls.bank, tracker=cls.tracker, category=cls.salary)
		make_transaction("Transfer", 20000, cls.bank, tracker=cls.tracker, destination_account=cls.pot)

		cls.goal = make_goal(
			cls.tracker,
			goal_type="Savings",
			target_account=cls.pot,
			target_amount=100000,
			start_date=cls.date,
		)

	def test_one_goals_progress_carries_formatted_figures(self):
		"""Formatted server-side: a client formats against System Settings' currency, not this
		tracker's (§33)."""
		progress = goals_api.get_goal_progress(self.goal.name, self.date)
		symbol = frappe.db.get_value("Currency", progress["currency"], "symbol") or progress["currency"]

		self.assertMoneyEqual(progress["current"], 20000)
		self.assertIn(symbol, progress["formatted"]["current"])

	def test_a_percentage_goal_is_formatted_as_a_percentage(self):
		rate = make_goal(
			self.tracker,
			goal_type="Savings Rate Target",
			target_percent=30,
			start_date=get_first_day(self.date),
			target_date=get_last_day(self.date),
		)

		progress = goals_api.get_goal_progress(rate.name, self.date)
		self.assertTrue(progress["formatted"]["target"].endswith("%"))

	def test_listing_the_goals_on_a_tracker(self):
		"""Its own tracker: another test in this class adds a goal, and the rollback is per class."""
		tracker = make_tracker().name
		goal = make_goal(
			tracker,
			goal_type="Savings",
			target_account=make_account(tracker, account_type="Savings").name,
		)

		result = goals_api.get_goals(tracker, self.date)
		self.assertEqual([row.goal for row in result["goals"]], [goal.name])
		self.assertIn("formatted", result["goals"][0])

	def test_a_goal_on_another_users_tracker_is_refused(self):
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			goals_api.get_goal_progress(self.goal.name)

	def test_another_users_tracker_is_refused(self):
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			goals_api.get_goals(self.tracker)


class TestGoalWidgets(MoneyTrackerTestCase):
	"""One goal met, one behind, one paused — the card should say "1 of 2"."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.pot = make_account(cls.tracker, account_type="Savings").name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		make_transaction("Income", 50000, cls.bank, tracker=cls.tracker, category=cls.salary)
		make_transaction("Transfer", 10000, cls.bank, tracker=cls.tracker, destination_account=cls.pot)

		def savings(name, target, **kwargs):
			kwargs.setdefault("start_date", cls.date)
			return make_goal(
				cls.tracker,
				goal_name=name,
				goal_type="Savings",
				target_account=cls.pot,
				target_amount=target,
				**kwargs,
			)

		# The met goal has the sooner deadline, so the two land in this order everywhere.
		# `behind` started eight days ago and has raised 10% with 69% of its window gone.
		cls.met = savings("Widget Met", 10000, target_date=add_days(cls.date, 2))
		cls.behind = savings(
			"Widget Behind",
			100000,
			start_date=add_days(cls.date, -8),
			target_date=add_days(cls.date, 4),
		)
		cls.paused = savings("Widget Paused", 100000, status="Paused")
		cls.filters = {"tracker": cls.tracker, "as_of": str(cls.date)}

	def test_the_fixture_is_one_met_goal_and_one_behind(self):
		"""Named rather than assumed: every count below depends on exactly this."""
		outcomes = {row.goal_name: row.outcome for row in goals.measure_goals(self.tracker, self.date)}

		self.assertEqual(outcomes[self.met.goal_name], goals.ACHIEVED)
		self.assertEqual(outcomes[self.behind.goal_name], goals.BEHIND)

	def test_the_card_counts_the_goals_that_are_going_well(self):
		self.assertEqual(goals_api.card_goals_on_track(self.filters), "1 of 2")

	def test_the_card_ignores_paused_goals(self):
		"""Two active goals, not three: a paused goal is neither on track nor behind."""
		self.assertNotIn("3", goals_api.card_goals_on_track(self.filters))

	def test_the_card_says_no_data_without_goals(self):
		empty = {"tracker": make_tracker().name, "as_of": str(self.date)}

		self.assertEqual(goals_api.card_goals_on_track(empty), goals_api.CARD_NO_DATA)

	def test_the_card_refuses_a_tracker_the_user_may_not_read(self):
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			goals_api.card_goals_on_track(self.filters)

	def test_rendering_the_card_does_not_create_a_tracker(self):
		"""Painting a dashboard is a read. `find_tracker()`, never `get_default_tracker()`."""
		newcomer = make_user()
		before = frappe.db.count("Tracker")

		with as_user(newcomer):
			self.assertEqual(goals_api.card_goals_on_track(), goals_api.CARD_NO_DATA)

		self.assertEqual(frappe.db.count("Tracker"), before)

	def test_the_chart_draws_one_bar_per_active_goal(self):
		result = goal_chart.get(filters=self.filters)

		self.assertEqual(result["labels"], [self.met.goal_name, self.behind.goal_name])
		self.assertEqual(len(result["datasets"]), 1)
		self.assertEqual(result["datasets"][0]["values"], [100.0, 10.0])

	def test_the_chart_can_be_narrowed_to_one_goal_type(self):
		result = goal_chart.get(filters={**self.filters, "goal_type": "Net Worth Target"})

		self.assertEqual(result["labels"], [])

	def test_the_chart_floors_negative_progress_at_zero(self):
		"""A refunded month can spend less than nothing, and a bar cannot be shorter than empty."""
		tracker = make_tracker().name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Expense").name
		make_transaction("Refund", 500, account, tracker=tracker, category=category)
		goal = make_goal(
			tracker,
			goal_type="Spending Limit",
			category=category,
			target_amount=5000,
			start_date=add_days(self.date, -1),
			target_date=add_days(self.date, 1),
		)

		self.assertEqual(flt(goals.measure(goal, self.date).progress_percent), -10.0)
		result = goal_chart.get(filters={"tracker": tracker, "as_of": str(self.date)})
		self.assertEqual(result["datasets"][0]["values"], [0.0])

	def test_a_user_with_no_tracker_gets_an_empty_chart(self):
		newcomer = make_user()
		with as_user(newcomer):
			self.assertEqual(goal_chart.get(), {"labels": [], "datasets": []})

	def test_the_chart_refuses_a_tracker_the_user_may_not_read(self):
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			goal_chart.get(filters=self.filters)

	def test_filters_may_arrive_as_a_json_string(self):
		"""filters_json reaches the method already parsed; a direct API call may not."""
		self.assertEqual(
			goals_api.card_goals_on_track(json.dumps(self.filters)),
			goals_api.card_goals_on_track(self.filters),
		)

	def test_the_shipped_chart_draws_through_its_own_name(self):
		"""The path the widget actually takes: chart name in, labels and datasets out."""
		self.assertTrue(frappe.db.exists("Dashboard Chart", "Goal Progress"))

		result = goal_chart.get(chart_name="Goal Progress", filters={"tracker": self.tracker})
		self.assertEqual(result["labels"], [self.met.goal_name, self.behind.goal_name])


class TestGoalTypeWiring(MoneyTrackerTestCase):
	"""A goal type is a string in three files, and only one of them fails loudly on its own.

	`GOAL_TYPES` is the table; the DocType's Select is what a user picks from; the chart
	source's `.js` is read off disk and eval'd in the browser, so a name that drifts there is
	wrong only in the filter dialog and nowhere a test would otherwise look.
	"""

	def test_every_goal_type_is_fully_described(self):
		for goal_type, spec in goals.GOAL_TYPES.items():
			with self.subTest(goal_type=goal_type):
				self.assertTrue(callable(spec.measure))
				self.assertIn(spec.direction, (goals.ACCUMULATE, goals.LIMIT))
				self.assertIn(spec.unit, (goals.CURRENCY, goals.PERCENT))
				self.assertIn(spec.account, (None, "Asset", "Liability"))
				self.assertIn(spec.category_type, (None, "Income", "Expense"))

	def test_an_unknown_goal_type_is_named_in_the_error(self):
		with self.assertRaises(frappe.ValidationError):
			goals.get_goal_type("Buy A Yacht")

	def test_the_select_lists_exactly_the_implemented_types(self):
		"""A Select option with no measure behind it is a goal that cannot be saved."""
		doctype = json.loads(read("doctype", "money_goal", "money_goal.json"))
		field = next(f for f in doctype["fields"] if f["fieldname"] == "goal_type")

		self.assertEqual(tuple(field["options"].split("\n")), goals.GOAL_TYPE_OPTIONS)

	def test_the_chart_source_filter_lists_every_goal_type(self):
		source_js = read("dashboard_chart_source", "money_goal_progress", "money_goal_progress.js")
		listed = re.search(r"options:\s*\[\s*\"\",(.*?)\]", source_js, re.DOTALL)
		self.assertTrue(listed, "the goal_type filter lists no options")

		options = tuple(re.findall(r'"([^"]+)"', listed.group(1)))
		self.assertEqual(options, goals.GOAL_TYPE_OPTIONS)

	def test_the_client_script_knows_which_types_use_an_account(self):
		listed = self.js_array("ACCOUNT_GOAL_TYPES")
		expected = [name for name, spec in goals.GOAL_TYPES.items() if spec.account]

		self.assertEqual(sorted(listed), sorted(expected))

	def test_the_client_script_knows_the_liability_account_types(self):
		"""The link filter narrows a Debt Payoff to liabilities by listing the types by hand.

		`coa.ACCOUNT_TYPE_MAP` is the real answer, and a type added there with no matching entry
		here would simply never be offered.
		"""
		listed = self.js_array("LIABILITY_ACCOUNT_TYPES")
		expected = [name for name in coa.ACCOUNT_TYPE_MAP if coa.is_liability(name)]

		self.assertEqual(sorted(listed), sorted(expected))

	def test_the_client_script_knows_which_types_measure_a_category(self):
		script = read("doctype", "money_goal", "money_goal.js")
		block = re.search(r"MEASURED_CATEGORY_TYPE = \{(.*?)\};", script, re.DOTALL)
		self.assertTrue(block, "the client script declares no measured category types")

		listed = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', block.group(1)))
		expected = {
			name: spec.category_type for name, spec in goals.GOAL_TYPES.items() if spec.category_type
		}

		self.assertEqual(listed, expected)

	def test_the_client_script_has_a_colour_for_every_outcome(self):
		"""An outcome with no colour renders grey, which reads as "no data" rather than "behind"."""
		script = read("doctype", "money_goal", "money_goal.js")

		for outcome in (
			goals.NOT_STARTED,
			goals.IN_PROGRESS,
			goals.ON_TRACK,
			goals.BEHIND,
			goals.AT_RISK,
			goals.ACHIEVED,
			goals.MISSED,
			goals.BREACHED,
			goals.NO_DATA,
		):
			with self.subTest(outcome=outcome):
				self.assertIn(outcome, script)

	def test_the_doctype_reached_the_site(self):
		self.assertTrue(
			frappe.db.exists("DocType", "Money Goal"),
			"Money Goal is missing — run `bench --site <site> migrate`",
		)

	def js_array(self, name):
		script = read("doctype", "money_goal", "money_goal.js")
		block = re.search(rf"{name} = \[(.*?)\];", script, re.DOTALL)
		self.assertTrue(block, f"the client script declares no {name}")
		return re.findall(r'"([^"]+)"', block.group(1))
