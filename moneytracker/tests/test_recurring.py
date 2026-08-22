# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Recurring transactions: the schedule, the generator, the nightly job and the widgets.

The controller's own rules live in
`money_tracker/doctype/money_recurring_transaction/test_money_recurring_transaction.py`.
What is tested here is everything that happens *after* a plan is saved — which is the part
that runs with nobody watching.
"""

import json
from pathlib import Path

import frappe
from frappe.utils import add_to_date, get_first_day, get_last_day, getdate, today

from moneytracker.money_tracker.api import recurring as recurring_api
from moneytracker.money_tracker.dashboard_chart_source.money_recurring_forecast import (
	money_recurring_forecast,
)
from moneytracker.money_tracker.doctype.transaction.transaction import ACCOUNT_TO_ACCOUNT_TYPES
from moneytracker.money_tracker.services import recurring
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	backdate_plan,
	make_account,
	make_category,
	make_recurring,
	make_tracker,
	make_user,
	posting_date,
)


class PlanFixture(MoneyTrackerTestCase):
	"""A tracker, an account and a category per **test**, not per class.

	The same lesson `test_budgets.py` learned: `FrappeTestCase` rolls back once per class, so a
	plan from three tests ago is still on the tracker and still counted by `measure_plans`, by
	`get_fixed_costs` and by the two cards.
	"""

	def setUp(self):
		self.tracker = make_tracker()
		self.account = make_account(self.tracker.name)
		self.destination = make_account(self.tracker.name, account_type="Savings")
		self.category = make_category(self.tracker.name)
		self.income_category = make_category(self.tracker.name, category_type="Income")

	def plan(self, **kwargs):
		kwargs.setdefault("account", self.account.name)
		if kwargs.get("transaction_type") in ACCOUNT_TO_ACCOUNT_TYPES:
			kwargs.setdefault("destination_account", self.destination.name)
		elif kwargs.get("transaction_type") == "Income":
			kwargs.setdefault("category", self.income_category.name)
		else:
			kwargs.setdefault("category", self.category.name)
		return make_recurring(self.tracker.name, **kwargs)


class TestFrequencyTable(MoneyTrackerTestCase):
	"""`FREQUENCIES` is the single table. Everything else reads it rather than branching."""

	def test_the_doctype_select_lists_exactly_the_table(self):
		meta = frappe.get_meta("Money Recurring Transaction")
		options = tuple(meta.get_field("frequency").options.split("\n"))
		self.assertEqual(options, recurring.FREQUENCY_OPTIONS)

	def test_the_doctype_select_lists_exactly_the_create_modes(self):
		meta = frappe.get_meta("Money Recurring Transaction")
		options = tuple(meta.get_field("create_mode").options.split("\n"))
		self.assertEqual(options, recurring.CREATE_MODES)

	def test_the_doctype_offers_only_types_a_schedule_can_repeat(self):
		meta = frappe.get_meta("Money Recurring Transaction")
		options = tuple(meta.get_field("transaction_type").options.split("\n"))
		self.assertEqual(options, recurring.RECURRING_TYPES)

	def test_an_unknown_frequency_throws_and_names_the_supported_ones(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			recurring.get_frequency("Fortnightly-ish")
		self.assertIn("Monthly", str(caught.exception))

	def test_monthly_equivalents_are_consistent_with_the_step(self):
		"""A yearly plan costs a twelfth of itself a month; a weekly one costs 4.35 of itself."""
		self.assertAlmostEqual(recurring.FREQUENCIES["Monthly"].per_month, 1.0)
		self.assertAlmostEqual(recurring.FREQUENCIES["Yearly"].per_month, 1 / 12)
		self.assertAlmostEqual(recurring.FREQUENCIES["Quarterly"].per_month, 1 / 3)
		self.assertAlmostEqual(recurring.FREQUENCIES["Weekly"].per_month, 365.25 / 12 / 7)
		# Two weeklies are one fortnightly, whatever the arithmetic underneath.
		self.assertAlmostEqual(
			recurring.FREQUENCIES["Fortnightly"].per_month * 2,
			recurring.FREQUENCIES["Weekly"].per_month,
		)


class TestOccurrenceMath(MoneyTrackerTestCase):
	"""The calendar, with no database in it at all."""

	def test_the_start_date_is_the_first_occurrence(self):
		self.assertEqual(recurring.nth_date("2026-04-10", "Monthly", 0), getdate("2026-04-10"))

	def test_a_month_end_plan_keeps_its_day_after_a_short_month(self):
		"""The whole reason `nth_date` counts from the anchor instead of stepping.

		Stepping off the previous occurrence would give 31 Jan → 28 Feb → 28 Mar, and the 31st
		would be lost for good the first time the plan passed a short month.
		"""
		dates = [str(recurring.nth_date("2027-01-31", "Monthly", n)) for n in range(5)]
		self.assertEqual(dates, ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31"])

	def test_a_leap_day_plan_clamps_and_returns(self):
		dates = [str(recurring.nth_date("2028-02-29", "Yearly", n)) for n in range(3)]
		self.assertEqual(dates, ["2028-02-29", "2029-02-28", "2030-02-28"])

	def test_weekly_and_fortnightly_step_in_days(self):
		self.assertEqual(recurring.nth_date("2026-04-01", "Weekly", 3), getdate("2026-04-22"))
		self.assertEqual(recurring.nth_date("2026-04-01", "Fortnightly", 2), getdate("2026-04-29"))

	def test_occurrences_are_inclusive_of_the_horizon(self):
		dates = recurring.occurrences("2026-04-01", "Monthly", to_date="2026-07-01")
		self.assertEqual(
			[str(date) for date in dates], ["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"]
		)

	def test_the_end_date_closes_the_schedule(self):
		dates = recurring.occurrences("2026-04-01", "Monthly", to_date="2026-12-01", end_date="2026-06-30")
		self.assertEqual([str(date) for date in dates], ["2026-04-01", "2026-05-01", "2026-06-01"])

	def test_from_date_filters_without_moving_the_anchor(self):
		"""Asking for later occurrences must still answer on the plan's own day of the month."""
		dates = recurring.occurrences("2026-04-10", "Monthly", to_date="2026-08-31", from_date="2026-07-01")
		self.assertEqual([str(date) for date in dates], ["2026-07-10", "2026-08-10"])

	def test_a_daily_schedule_is_bounded_rather_than_endless(self):
		dates = recurring.occurrences("2000-01-01", "Daily", to_date="2100-01-01")
		self.assertEqual(len(dates), recurring.MAX_OCCURRENCES)


class TestNextDate(PlanFixture):
	def test_the_next_date_is_strictly_after_the_day_asked_about(self):
		plan = self.plan(start_date="2026-04-10", frequency="Monthly")
		self.assertEqual(recurring.next_date(plan, "2026-04-10"), getdate("2026-05-10"))
		self.assertEqual(recurring.next_date(plan, "2026-04-09"), getdate("2026-04-10"))

	def test_a_plan_that_has_not_started_answers_with_its_start_date(self):
		plan = self.plan(start_date=add_to_date(today(), days=30))
		self.assertEqual(recurring.next_date(plan), getdate(add_to_date(today(), days=30)))

	def test_a_finished_plan_has_no_next_date(self):
		plan = self.plan(start_date="2026-04-01", end_date="2026-06-30")
		self.assertIsNone(recurring.next_date(plan, "2026-07-01"))


class TestEffectiveFrom(PlanFixture):
	"""A plan reaches forward, not back."""

	def test_a_plan_never_posts_for_a_date_before_it_was_created(self):
		plan = self.plan(start_date=get_first_day(posting_date()))
		self.assertEqual(recurring.effective_from(plan), getdate(today()))

	def test_a_future_start_date_wins_over_the_creation_date(self):
		start = add_to_date(today(), days=10)
		plan = self.plan(start_date=start)
		self.assertEqual(recurring.effective_from(plan), getdate(start))

	def test_a_back_dated_plan_may_reach_back_to_its_start(self):
		plan = self.plan(start_date="2026-04-01")
		backdate_plan(plan, "2026-04-01 09:00:00")
		self.assertEqual(recurring.effective_from(plan), getdate("2026-04-01"))

	def test_history_typed_by_hand_is_not_posted_over(self):
		"""The rule in one test: five months of rent already entered stay one copy of rent."""
		plan = self.plan(start_date=get_first_day(add_to_date(today(), months=-5)))
		self.assertEqual(recurring.generate(plan, today()), [])


class TestGeneration(PlanFixture):
	def test_an_occurrence_becomes_a_submitted_transaction_linked_back(self):
		plan = self.plan(amount=2500)
		created = recurring.generate(plan)
		self.assertEqual(len(created), 1)

		transaction = frappe.get_doc("Transaction", created[0])
		self.assertEqual(transaction.docstatus, 1)
		self.assertEqual(transaction.recurring_transaction, plan.name)
		self.assertMoneyEqual(transaction.amount, 2500)
		self.assertEqual(transaction.category, self.category.name)
		self.assertTrue(transaction.journal_entry, "an automatic plan posts to the ledger")

	def test_the_template_fields_are_copied_onto_every_occurrence(self):
		plan = self.plan(merchant="Landlord", payee="Mrs Rao", notes="First of the month")
		transaction = frappe.get_doc("Transaction", recurring.generate(plan)[0])
		self.assertEqual(transaction.merchant, "Landlord")
		self.assertEqual(transaction.payee, "Mrs Rao")
		self.assertEqual(transaction.notes, "First of the month")

	def test_running_twice_posts_once(self):
		plan = self.plan()
		self.assertEqual(len(recurring.generate(plan)), 1)
		self.assertEqual(recurring.generate(plan), [])

	def test_a_draft_plan_leaves_a_draft_and_still_counts_as_handled(self):
		"""A bill that varies wants checking, and a checked bill must not be posted twice."""
		plan = self.plan(create_mode=recurring.CREATE_AS_DRAFT)
		created = recurring.generate(plan)
		transaction = frappe.get_doc("Transaction", created[0])
		self.assertEqual(transaction.docstatus, 0)
		self.assertFalse(transaction.journal_entry)
		self.assertEqual(recurring.generate(plan), [], "a draft occurrence is already handled")

	def test_a_cancelled_occurrence_is_not_posted_again(self):
		"""Cancelling is a decision. Re-posting it the next morning would overrule it nightly."""
		plan = self.plan()
		transaction = frappe.get_doc("Transaction", recurring.generate(plan)[0])
		transaction.cancel()
		self.assertEqual(recurring.generate(plan), [])

	def test_a_paused_plan_generates_nothing_and_loses_nothing(self):
		plan = self.plan()
		plan.status = "Paused"
		plan.save()
		self.assertEqual(recurring.generate(plan), [])

		plan.status = "Active"
		plan.save()
		self.assertEqual(len(recurring.generate(plan)), 1, "resuming picks up where it left off")

	def test_catch_up_posts_every_missed_occurrence(self):
		plan = self.plan(start_date=get_first_day(add_to_date(today(), months=-3)), amount=1000)
		backdate_plan(plan, f"{get_first_day(add_to_date(today(), months=-3))} 09:00:00")

		created = recurring.generate(plan)
		self.assertEqual(len(created), 4, "three missed months plus this one")
		dates = frappe.get_all("Transaction", filters={"recurring_transaction": plan.name}, pluck="date")
		self.assertEqual(len(set(dates)), 4, "one occurrence per date, never two")

	def test_one_run_is_bounded_and_the_rest_stays_due(self):
		# Drafts rather than postings: what is being counted is occurrences, and sixty journal
		# entries through the ledger would cost the suite ten seconds to prove nothing extra.
		plan = self.plan(
			frequency="Daily",
			create_mode=recurring.CREATE_AS_DRAFT,
			start_date=add_to_date(today(), days=-90),
		)
		backdate_plan(plan, f"{add_to_date(today(), days=-90)} 09:00:00")

		created = recurring.generate(plan)
		self.assertEqual(len(created), recurring.MAX_PER_RUN)
		self.assertTrue(recurring.due_dates(plan), "what did not fit is still owed")

	def test_a_transfer_plan_posts_between_two_accounts_and_carries_no_category(self):
		plan = self.plan(transaction_type="Transfer", amount=5000)
		transaction = frappe.get_doc("Transaction", recurring.generate(plan)[0])
		self.assertEqual(transaction.destination_account, self.destination.name)
		self.assertFalse(transaction.category)

	def test_an_income_plan_posts_income(self):
		plan = self.plan(transaction_type="Income", amount=120000)
		transaction = frappe.get_doc("Transaction", recurring.generate(plan)[0])
		self.assertEqual(transaction.transaction_type, "Income")
		self.assertEqual(transaction.category, self.income_category.name)

	def test_an_occurrence_after_the_end_date_is_never_posted(self):
		plan = self.plan(start_date=today(), end_date=today())
		self.assertEqual(len(recurring.generate(plan)), 1)

		plan.reload()
		self.assertEqual(recurring.due_dates(plan, add_to_date(today(), months=6)), [])


class TestMeasure(PlanFixture):
	def test_a_plan_with_nothing_due_is_scheduled(self):
		plan = self.plan()
		recurring.generate(plan)
		measured = recurring.measure(plan)

		self.assertEqual(measured.outcome, recurring.SCHEDULED)
		self.assertEqual(measured.posted_count, 1)
		self.assertEqual(measured.due_count, 0)
		self.assertEqual(measured.next_date, recurring.next_date(plan))

	def test_an_unposted_occurrence_reads_due(self):
		"""`Due` says the nightly job has not run. No money figure would show that."""
		plan = self.plan()
		measured = recurring.measure(plan)
		self.assertEqual(measured.outcome, recurring.DUE)
		self.assertEqual(measured.due_count, 1)
		self.assertMoneyEqual(measured.due_amount, plan.amount)

	def test_a_future_plan_has_not_started(self):
		plan = self.plan(start_date=add_to_date(today(), days=7))
		self.assertEqual(recurring.measure(plan).outcome, recurring.NOT_STARTED)

	def test_a_finished_plan_has_ended(self):
		plan = self.plan(start_date="2026-04-01", end_date="2026-04-30")
		backdate_plan(plan, "2026-04-01 09:00:00")
		recurring.generate(plan, "2026-05-01")
		self.assertEqual(recurring.measure(plan, "2026-05-01").outcome, recurring.ENDED)

	def test_the_users_own_intent_wins_over_the_schedule(self):
		"""A paused plan is paused, not behind — reporting their decision back as a fault."""
		plan = self.plan()
		plan.status = "Paused"
		plan.save()

		measured = recurring.measure(plan)
		self.assertEqual(measured.outcome, recurring.PAUSED)
		self.assertEqual(measured.due_count, 0)

	def test_a_cancelled_occurrence_leaves_the_total_alone_but_stays_in_the_history(self):
		plan = self.plan(amount=800)
		transaction = frappe.get_doc("Transaction", recurring.generate(plan)[0])
		transaction.cancel()

		measured = recurring.measure(plan)
		self.assertEqual(measured.posted_count, 0)
		self.assertMoneyEqual(measured.posted_total, 0)
		self.assertEqual(measured.cancelled_count, 1)
		self.assertEqual(len(measured.history), 1)
		self.assertEqual(measured.history[0]["state"], "Cancelled")

	def test_the_monthly_equivalent_puts_every_clock_on_one(self):
		yearly = self.plan(frequency="Yearly", amount=12000)
		self.assertMoneyEqual(recurring.measure(yearly).monthly_equivalent, 1000)

	def test_the_history_is_bounded(self):
		plan = self.plan(
			frequency="Daily",
			create_mode=recurring.CREATE_AS_DRAFT,
			start_date=add_to_date(today(), days=-40),
		)
		backdate_plan(plan, f"{add_to_date(today(), days=-40)} 09:00:00")
		recurring.generate(plan)
		self.assertEqual(len(recurring.measure(plan).history), recurring.HISTORY_LIMIT)


class TestFixedCosts(PlanFixture):
	def test_only_expense_plans_are_a_cost(self):
		"""A transfer to savings is a commitment but not a cost — the money is still yours."""
		self.plan(amount=35000)
		self.plan(transaction_type="Income", amount=120000)
		self.plan(transaction_type="Transfer", amount=15000)

		costs = recurring.get_fixed_costs(self.tracker.name)
		self.assertMoneyEqual(costs.monthly, 35000)
		self.assertEqual(costs.plans, 1)

	def test_clocks_are_normalised_before_they_are_added(self):
		self.plan(amount=1200, frequency="Yearly")
		self.plan(amount=500, frequency="Monthly")
		self.assertMoneyEqual(recurring.get_fixed_costs(self.tracker.name).monthly, 600)

	def test_a_plan_that_has_not_started_is_still_a_commitment(self):
		self.plan(amount=9000, start_date=add_to_date(today(), months=1))
		self.assertMoneyEqual(recurring.get_fixed_costs(self.tracker.name).monthly, 9000)

	def test_a_finished_plan_is_not(self):
		plan = self.plan(amount=9000, start_date="2026-04-01", end_date="2026-04-30")
		backdate_plan(plan, "2026-04-01 09:00:00")
		self.assertMoneyEqual(recurring.get_fixed_costs(self.tracker.name).monthly, 0)

	def test_a_paused_plan_is_not(self):
		plan = self.plan(amount=9000)
		plan.status = "Paused"
		plan.save()
		self.assertEqual(recurring.get_fixed_costs(self.tracker.name).plans, 0)


class TestForecast(PlanFixture):
	def test_the_window_opens_strictly_after_today(self):
		"""Today's occurrence belongs to the actuals, or the dashboard shows one rent twice."""
		self.plan(amount=1000, start_date=today(), frequency="Monthly")
		forecast = recurring.get_forecast(self.tracker.name, after=today(), months=2)
		self.assertMoneyEqual(forecast["rows"][0]["expense"], 0)
		self.assertMoneyEqual(forecast["rows"][1]["expense"], 1000)

	def test_every_month_in_the_range_is_returned_including_empty_ones(self):
		self.plan(amount=1000, frequency="Yearly", start_date=add_to_date(today(), days=1))
		forecast = recurring.get_forecast(self.tracker.name, after=today(), months=4)
		self.assertEqual(len(forecast["labels"]), 4)
		self.assertEqual([row["expense"] for row in forecast["rows"]].count(0.0), 3)

	def test_income_and_expense_are_separate_series(self):
		self.plan(amount=1000, start_date=add_to_date(today(), days=1))
		self.plan(transaction_type="Income", amount=5000, start_date=add_to_date(today(), days=1))

		row = recurring.get_forecast(self.tracker.name, after=today(), months=1)["rows"][0]
		self.assertMoneyEqual(row["expense"], 1000)
		self.assertMoneyEqual(row["income"], 5000)

	def test_transfers_and_card_payments_are_in_neither_series(self):
		self.plan(transaction_type="Transfer", amount=15000, start_date=add_to_date(today(), days=1))
		row = recurring.get_forecast(self.tracker.name, after=today(), months=1)["rows"][0]
		self.assertMoneyEqual(row["income"], 0)
		self.assertMoneyEqual(row["expense"], 0)

	def test_a_weekly_plan_puts_several_occurrences_in_one_month(self):
		start = get_first_day(add_to_date(today(), months=1))
		self.plan(amount=100, frequency="Weekly", start_date=start)
		row = recurring.get_forecast(self.tracker.name, after=get_last_day(today()), months=2)["rows"][1]
		self.assertGreaterEqual(row["expense"], 400)

	def test_the_chart_source_returns_two_datasets_over_the_same_labels(self):
		self.plan(amount=1000, start_date=add_to_date(today(), days=1))
		result = money_recurring_forecast.get(
			chart=json.dumps({"filters_json": json.dumps({"tracker": self.tracker.name})})
		)
		self.assertEqual([dataset["name"] for dataset in result["datasets"]], ["Income", "Expense"])
		for dataset in result["datasets"]:
			self.assertEqual(len(dataset["values"]), len(result["labels"]))

	def test_the_chart_source_answers_empty_for_a_user_with_no_tracker(self):
		with as_user(make_user()):
			self.assertEqual(money_recurring_forecast.get(chart="{}"), {"labels": [], "datasets": []})


class TestTheNightlyJob(PlanFixture):
	def test_it_posts_every_active_plan_and_reports_what_it_did(self):
		self.plan(amount=1000)
		self.plan(amount=2000, transaction_type="Income")

		summary = recurring.run_recurring_transactions()
		self.assertGreaterEqual(summary.posted, 2)
		self.assertEqual(summary.failed, 0)

	def test_it_is_idempotent(self):
		self.plan()
		recurring.run_recurring_transactions()
		self.assertEqual(recurring.run_recurring_transactions().posted, 0)

	def test_one_broken_plan_does_not_stop_the_others(self):
		"""The savepoint. A posting can fail for reasons that have nothing to do with the plan.

		The category's ledger account is emptied under one plan, which is what a rename or a
		half-finished chart of accounts looks like from here. The engine throws on it; the
		other plan must still post.
		"""
		broken_category = make_category(self.tracker.name)
		broken = self.plan(category=broken_category.name, amount=700)
		healthy = self.plan(amount=900)

		frappe.db.set_value("Category", broken_category.name, "ledger_account", None)
		frappe.clear_document_cache("Category", broken_category.name)

		summary = recurring.run_recurring_transactions()
		self.assertEqual(summary.failed, 1)
		self.assertTrue(
			frappe.db.exists("Transaction", {"recurring_transaction": healthy.name}),
			"the healthy plan posted anyway",
		)
		self.assertFalse(frappe.db.exists("Transaction", {"recurring_transaction": broken.name}))

	def test_it_notifies_the_trackers_owner_once_per_run(self):
		user = make_user()
		tracker = make_tracker(owner_user=user)
		account = make_account(tracker.name)
		category = make_category(tracker.name)
		plan = make_recurring(tracker.name, account=account.name, category=category.name, amount=1200)

		recurring.run_recurring_transactions()
		logs = frappe.get_all(
			"Notification Log",
			filters={"document_type": "Money Recurring Transaction", "document_name": plan.name},
			pluck="subject",
		)
		self.assertEqual(len(logs), 1)
		self.assertIn(plan.recurring_name, logs[0])

	def test_a_plan_that_asks_not_to_be_told_is_not(self):
		user = make_user()
		tracker = make_tracker(owner_user=user)
		plan = make_recurring(
			tracker.name,
			account=make_account(tracker.name).name,
			category=make_category(tracker.name).name,
			notify_on_post=0,
		)
		recurring.run_recurring_transactions()
		self.assertFalse(
			frappe.db.exists("Notification Log", {"document_name": plan.name}),
		)

	def test_it_is_registered_as_a_daily_job(self):
		from moneytracker import hooks

		self.assertIn(
			"moneytracker.money_tracker.services.recurring.run_recurring_transactions",
			hooks.scheduler_events["daily"],
		)


class TestTheApiAndCards(PlanFixture):
	def test_the_progress_api_formats_money_against_the_tracker(self):
		plan = self.plan(amount=1500)
		payload = recurring_api.get_recurring_progress(plan.name)
		self.assertIn("formatted", payload)
		self.assertIn("1,500", payload["formatted"]["amount"])
		self.assertIn("monthly_equivalent", payload["formatted"])

	def test_the_fixed_costs_card_prints_money(self):
		self.plan(amount=35000)
		card = recurring_api.card_fixed_costs(json.dumps({"tracker": self.tracker.name}))
		self.assertIn("35,000", card)

	def test_the_fixed_costs_card_says_nothing_rather_than_zero(self):
		card = recurring_api.card_fixed_costs(json.dumps({"tracker": self.tracker.name}))
		self.assertEqual(card, "—")

	def test_the_plans_running_card_counts_the_healthy_ones(self):
		posted = self.plan(amount=100)
		recurring.generate(posted)
		self.plan(amount=200)  # never generated, so overdue

		card = recurring_api.card_plans_running(json.dumps({"tracker": self.tracker.name}))
		self.assertEqual(card, "1 of 2")

	def test_a_card_never_creates_a_tracker_for_a_user_who_has_none(self):
		"""§35: painting a dashboard must not write. `find_tracker`, never `get_default_tracker`."""
		user = make_user()
		before = frappe.db.count("Tracker")
		with as_user(user):
			self.assertEqual(recurring_api.card_fixed_costs(), "—")
			self.assertEqual(recurring_api.card_plans_running(), "—")
		self.assertEqual(frappe.db.count("Tracker"), before)

	def test_the_widgets_name_a_doctype_their_reader_can_read(self):
		"""§34: a Custom card is gated on `document_type`, so an unreadable one is invisible."""
		for name in ("Fixed Costs", "Plans Running"):
			self.assertEqual(
				frappe.db.get_value("Number Card", name, "document_type"),
				"Money Recurring Transaction",
			)
		self.assertEqual(
			frappe.db.get_value("Dashboard Chart", "Upcoming Recurring", "document_type"),
			"Money Recurring Transaction",
		)


class TestPermissions(MoneyTrackerTestCase):
	"""A plan is tracker-scoped, so it must be in both hook lists (`hooks.py`)."""

	def test_both_hooks_cover_the_new_doctype(self):
		from moneytracker import hooks

		self.assertIn("Money Recurring Transaction", hooks.permission_query_conditions)
		self.assertIn("Money Recurring Transaction", hooks.has_permission)

	def test_another_users_plan_is_neither_listed_nor_readable(self):
		tracker = make_tracker()
		plan = make_recurring(
			tracker.name,
			account=make_account(tracker.name).name,
			category=make_category(tracker.name).name,
		)

		with as_user(make_user()):
			# get_list, not get_all: `get_all` ignores permissions by design, so it would pass
			# whatever the hooks did.
			self.assertEqual(frappe.get_list("Money Recurring Transaction", filters={"name": plan.name}), [])
			self.assertFalse(
				frappe.has_permission("Money Recurring Transaction", doc=plan.name, user=frappe.session.user)
			)


class TestFormWiring(MoneyTrackerTestCase):
	"""The form script restates things Python knows. These fail if they drift.

	The same guard `test_goals.py:TestGoalTypeWiring` applies, and for the same reason: a
	`.js` file is read off disk and eval'd, so nothing else would notice.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		app = Path(frappe.get_app_path("moneytracker"))
		cls.form_js = (
			app / "money_tracker/doctype/money_recurring_transaction/money_recurring_transaction.js"
		).read_text()
		cls.source_js = (
			app / "money_tracker/dashboard_chart_source/money_recurring_forecast/money_recurring_forecast.js"
		).read_text()

	def test_the_form_lists_the_same_account_to_account_types(self):
		listed = self.form_js.split("const ACCOUNT_TO_ACCOUNT_TYPES = [")[1].split("]")[0]
		for transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			self.assertIn(f'"{transaction_type}"', listed)

	def test_the_form_colours_every_outcome(self):
		block = self.form_js.split("const OUTCOME_COLOR = {")[1].split("};")[0]
		for outcome in (
			recurring.NOT_STARTED,
			recurring.SCHEDULED,
			recurring.DUE,
			recurring.PAUSED,
			recurring.ARCHIVED,
			recurring.ENDED,
		):
			self.assertIn(outcome.replace(" ", ""), block.replace('"', "").replace(" ", ""))

	def test_the_form_calls_a_method_that_exists(self):
		self.assertIn("moneytracker.money_tracker.api.recurring.get_recurring_progress", self.form_js)
		self.assertTrue(callable(recurring_api.get_recurring_progress))

	def test_the_chart_source_js_points_at_the_real_method(self):
		method = (
			"moneytracker.money_tracker.dashboard_chart_source."
			"money_recurring_forecast.money_recurring_forecast.get"
		)
		self.assertIn(method, self.source_js)
		self.assertTrue(callable(frappe.get_attr(method)))
