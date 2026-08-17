# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The dashboard Dashboard Charts (spec §5) and the series behind them.

Same two concerns as the Number Cards: the arithmetic must not disagree with the ledger,
and the wiring — a Custom chart is a source name and a method path in a JSON file — must
not rot silently. A chart adds one thing a card does not have: *time*. Most of what can go
wrong here is a period boundary, so the empty months are asserted as hard as the full ones.
"""

import json
import os
import re

import frappe
from frappe.utils import add_days, add_months, get_first_day, get_last_day, getdate

from moneytracker.money_tracker.api import dashboard
from moneytracker.money_tracker.dashboard_chart_source.money_period_totals import (
	money_period_totals as source,
)
from moneytracker.money_tracker.services import trends
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	as_user,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	make_user,
	unique,
)

SOURCE_NAME = "Money Period Totals"


def covered_by_a_fiscal_year(date):
	"""ERPNext refuses a posting outside a Fiscal Year, so a back-dated fixture has to check."""
	return bool(
		frappe.db.exists(
			"Fiscal Year",
			{"year_start_date": ["<=", date], "year_end_date": [">=", date], "disabled": 0},
		)
	)


def chart_dir():
	return frappe.get_app_path("moneytracker", "money_tracker", "dashboard_chart")


def source_dir():
	return frappe.get_app_path("moneytracker", "money_tracker", "dashboard_chart_source")


def _fixtures(root):
	"""Every `<folder>/<folder>.json` under `root`, read from disk rather than from the site.

	The file is the source of truth — migrate imports it — so reading the DB instead would
	pass on a site where the import silently never ran.
	"""
	for folder in sorted(os.listdir(root)):
		path = os.path.join(root, folder, f"{folder}.json")
		if os.path.exists(path):
			with open(path) as f:
				yield folder, json.load(f)


def shipped_charts():
	return _fixtures(chart_dir())


def shipped_sources():
	return _fixtures(source_dir())


class TestPeriodSeries(MoneyTrackerTestCase):
	"""One tracker, money in three different months, read back as a monthly series.

	this month  income 50000 · expense 2000 + 3000 - 500 = 4500
	last month  expense 1200
	two back    income 9000
	The transfer and the card payment moved money without earning or spending it.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.this_month = cls.date
		cls.last_month = add_months(cls.date, -1)
		cls.two_back = add_months(cls.date, -2)

		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.sbi = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		def post(transaction_type, amount, account, **kwargs):
			return make_transaction(transaction_type, amount, account, tracker=cls.tracker, **kwargs)

		post("Income", 50000, cls.bank, category=cls.salary)
		post("Expense", 2000, cls.bank, category=cls.food)
		post("Expense", 3000, cls.card, category=cls.food)
		post("Transfer", 8000, cls.bank, destination_account=cls.sbi)
		post("Credit Card Payment", 1000, cls.bank, destination_account=cls.card)
		post("Refund", 500, cls.bank, category=cls.food)

		cls.back_dated = covered_by_a_fiscal_year(cls.two_back)
		if cls.back_dated:
			post("Expense", 1200, cls.bank, category=cls.food, date=cls.last_month)
			post("Income", 9000, cls.bank, category=cls.salary, date=cls.two_back)

	def series(self, from_date=None, to_date=None, interval="Monthly", tracker=None):
		return trends.get_period_series(
			tracker or self.tracker,
			from_date or get_first_day(self.two_back),
			to_date or get_last_day(self.this_month),
			interval,
		)

	def by_label(self, rows):
		return {row["label"]: row for row in rows}

	def test_the_current_month_matches_the_cards(self):
		"""One dashboard, one set of numbers — a chart is not a second implementation.

		The §62 refund rule is stated twice, in `api/dashboard._period_totals` for the cards
		and in `trends.get_period_series` for the charts. This is what catches them drifting.
		"""
		current = self.by_label(self.series())[trends.get_period(self.this_month, "Monthly")]
		summary = dashboard.get_dashboard(tracker=self.tracker, as_of=self.this_month)

		self.assertMoneyEqual(current["income"], summary["monthly_income"])
		self.assertMoneyEqual(current["expense"], summary["monthly_expense"])
		self.assertMoneyEqual(current["income"], 50000)
		self.assertMoneyEqual(current["expense"], 4500)

	def test_expense_is_net_of_refunds(self):
		"""2000 + 3000 - 500: a refund gives spending back, it is not income (§62)."""
		current = self.by_label(self.series())[trends.get_period(self.this_month, "Monthly")]

		self.assertMoneyEqual(current["expense"], 4500)
		self.assertMoneyEqual(current["income"], 50000)

	def test_transfers_and_card_payments_are_neither(self):
		"""The 8000 transfer and the 1000 card payment would show up in both series if the
		query went by account movement instead of by transaction type."""
		total_income = sum(row["income"] for row in self.series())
		total_expense = sum(row["expense"] for row in self.series())

		self.assertMoneyEqual(total_income, 50000 + (9000 if self.back_dated else 0))
		self.assertMoneyEqual(total_expense, 4500 + (1200 if self.back_dated else 0))

	def test_each_month_holds_its_own_money(self):
		if not self.back_dated:
			self.skipTest("no Fiscal Year covers two months ago on this site")

		rows = self.by_label(self.series())

		self.assertMoneyEqual(rows[trends.get_period(self.two_back, "Monthly")]["income"], 9000)
		self.assertMoneyEqual(rows[trends.get_period(self.two_back, "Monthly")]["expense"], 0)
		self.assertMoneyEqual(rows[trends.get_period(self.last_month, "Monthly")]["expense"], 1200)
		self.assertMoneyEqual(rows[trends.get_period(self.last_month, "Monthly")]["income"], 0)

	def test_a_month_with_nothing_in_it_is_still_a_period(self):
		"""Dropping an empty month draws a line straight from March to May, which reads as if
		April never happened rather than as if nothing was spent in it."""
		empty_tracker = make_tracker().name
		rows = self.series(tracker=empty_tracker)

		self.assertEqual(len(rows), 3)
		self.assertEqual([row["income"] for row in rows], [0.0, 0.0, 0.0])
		self.assertEqual([row["expense"] for row in rows], [0.0, 0.0, 0.0])

	def test_the_periods_come_back_oldest_first(self):
		ends = [row["period_end"] for row in self.series()]

		self.assertEqual(ends, sorted(ends))
		self.assertEqual(ends[-1], getdate(get_last_day(self.this_month)))

	def test_a_range_inside_one_month_is_one_period(self):
		rows = self.series(from_date=get_first_day(self.this_month), to_date=self.this_month)

		self.assertEqual(len(rows), 1)
		self.assertMoneyEqual(rows[0]["income"], 50000)

	def test_a_daily_grain_puts_todays_money_on_today(self):
		rows = self.series(from_date=add_days(self.this_month, -2), to_date=self.this_month, interval="Daily")

		self.assertEqual(len(rows), 3)
		self.assertMoneyEqual(rows[-1]["income"], 50000)
		self.assertMoneyEqual(rows[0]["income"], 0)

	def test_a_yearly_grain_rolls_the_months_together(self):
		rows = self.series(interval="Yearly")
		expected_income = 50000 + (9000 if self.back_dated and self.two_back.year == self.date.year else 0)

		self.assertMoneyEqual(sum(row["income"] for row in rows), 50000 + (9000 if self.back_dated else 0))
		self.assertMoneyEqual(rows[-1]["income"], expected_income)

	def test_only_submitted_transactions_count(self):
		draft = make_transaction(
			"Expense", 777, self.bank, tracker=self.tracker, category=self.food, submit=False
		)
		self.addCleanup(draft.delete)

		current = self.by_label(self.series())[trends.get_period(self.this_month, "Monthly")]
		self.assertMoneyEqual(current["expense"], 4500)

	def test_an_unknown_interval_is_refused(self):
		"""Rather than silently falling back to Monthly and drawing the wrong picture."""
		with self.assertRaises(frappe.ValidationError):
			self.series(interval="Fortnightly")

	def test_a_backwards_range_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.series(from_date=get_last_day(self.this_month), to_date=get_first_day(self.two_back))


class TestSeriesIsolation(MoneyTrackerTestCase):
	"""Two trackers on one shared ERPNext Account — the same trap as balances.py.

	`coa.get_or_create_ledger_account` matches on account name and ignores the parent, so two
	people who both call an account "Cash" post into one ledger account.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shared_name = unique("Cash")

		cls.tracker_a = make_tracker().name
		cls.tracker_b = make_tracker().name
		account_a = make_account(cls.tracker_a, account_name=shared_name, account_type="Cash").name
		account_b = make_account(cls.tracker_b, account_name=shared_name, account_type="Cash").name
		category_a = make_category(cls.tracker_a, category_type="Income").name
		category_b = make_category(cls.tracker_b, category_type="Income").name

		make_transaction("Income", 100, account_a, tracker=cls.tracker_a, category=category_a)
		make_transaction("Income", 4242, account_b, tracker=cls.tracker_b, category=category_b)

	def totals(self, tracker):
		rows = trends.get_period_series(
			tracker, get_first_day(self.date), get_last_day(self.date), "Monthly"
		)
		return sum(row["income"] for row in rows)

	def test_each_tracker_reads_only_its_own_money(self):
		self.assertMoneyEqual(self.totals(self.tracker_a), 100)
		self.assertMoneyEqual(self.totals(self.tracker_b), 4242)


class TestChartSource(MoneyTrackerTestCase):
	"""The payload the chart widget actually receives."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name

		make_transaction("Income", 50000, cls.bank, tracker=cls.tracker, category=cls.salary)
		make_transaction("Expense", 2000, cls.bank, tracker=cls.tracker, category=cls.food)

		cls.filters = {"tracker": cls.tracker}
		cls.month = {
			"timespan": "Select Date Range",
			"from_date": get_first_day(cls.date),
			"to_date": get_last_day(cls.date),
		}

	def test_it_returns_both_series_by_default(self):
		result = source.get(filters=self.filters, **self.month)

		self.assertEqual([d["name"] for d in result["datasets"]], ["Income", "Expense"])
		self.assertEqual(len(result["labels"]), 1)
		self.assertMoneyEqual(result["datasets"][0]["values"][0], 50000)
		self.assertMoneyEqual(result["datasets"][1]["values"][0], 2000)

	def test_the_series_filter_picks_one(self):
		result = source.get(filters={**self.filters, "series": "Expense"}, **self.month)

		self.assertEqual([d["name"] for d in result["datasets"]], ["Expense"])
		self.assertMoneyEqual(result["datasets"][0]["values"][0], 2000)

	def test_an_unknown_series_falls_back_to_both(self):
		result = source.get(filters={**self.filters, "series": "Nonsense"}, **self.month)

		self.assertEqual([d["name"] for d in result["datasets"]], ["Income", "Expense"])

	def test_every_dataset_is_as_long_as_the_labels(self):
		"""A dataset shorter than the labels silently shifts every bar left by a period."""
		result = source.get(filters=self.filters)

		for dataset in result["datasets"]:
			self.assertEqual(len(dataset["values"]), len(result["labels"]), dataset["name"])

	def test_the_default_timespan_is_a_year_of_months(self):
		"""Last Year at a Monthly grain: twelve months back plus the one we are in."""
		result = source.get(filters=self.filters)

		self.assertEqual(len(result["labels"]), 13)
		self.assertEqual(result["labels"][-1], trends.get_period(self.date, "Monthly"))

	def test_filters_may_arrive_as_a_json_string(self):
		self.assertEqual(
			source.get(filters=json.dumps(self.filters), **self.month),
			source.get(filters=self.filters, **self.month),
		)

	def test_a_tracker_the_user_may_not_read_is_refused(self):
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			source.get(filters=self.filters)

	def test_an_unfiltered_chart_falls_back_to_the_users_own_tracker(self):
		owner = make_user()
		tracker = make_tracker(owner_user=owner).name
		account = make_account(tracker, account_type="Cash").name
		category = make_category(tracker, category_type="Income").name
		make_transaction("Income", 77, account, tracker=tracker, category=category)

		with as_user(owner):
			result = source.get(**self.month)

		self.assertMoneyEqual(result["datasets"][0]["values"][0], 77)

	def test_a_user_with_no_tracker_gets_an_empty_chart(self):
		"""Empty, not a flat line at zero — the widget then says "No Data" rather than
		claiming this person earned and spent nothing."""
		newcomer = make_user()
		with as_user(newcomer):
			result = source.get()

		self.assertEqual(result, {"labels": [], "datasets": []})

	def test_drawing_a_chart_does_not_create_a_tracker(self):
		"""get_default_tracker() creates one on first use; painting a dashboard is a read."""
		newcomer = make_user()
		before = frappe.db.count("Tracker")

		with as_user(newcomer):
			source.get()

		self.assertEqual(frappe.db.count("Tracker"), before)

	def test_a_saved_chart_supplies_its_own_filters(self):
		"""The widget may send no filters at all and leave filters_json to speak for it."""
		chart = json.dumps(
			{
				"name": "unsaved",
				"filters_json": json.dumps({**self.filters, "series": "Income"}),
				"time_interval": "Monthly",
				"timespan": "Last Month",
			}
		)
		result = source.get(chart=chart)

		self.assertEqual([d["name"] for d in result["datasets"]], ["Income"])
		self.assertMoneyEqual(result["datasets"][0]["values"][-1], 50000)

	def test_a_date_range_chart_with_no_range_still_draws(self):
		"""Select Date Range with nothing saved would otherwise plot a single day."""
		result = source.get(
			chart=json.dumps({"name": "unsaved", "timespan": "Select Date Range"}),
			filters=self.filters,
		)

		self.assertEqual(len(result["labels"]), 13)

	def test_the_api_gives_the_same_numbers(self):
		api = dashboard.get_trend(
			tracker=self.tracker,
			from_date=get_first_day(self.date),
			to_date=get_last_day(self.date),
		)
		chart = source.get(filters=self.filters, **self.month)

		self.assertMoneyEqual(api["rows"][0]["income"], chart["datasets"][0]["values"][0])
		self.assertMoneyEqual(api["rows"][0]["expense"], chart["datasets"][1]["values"][0])


class TestShippedChartFixtures(MoneyTrackerTestCase):
	"""The JSON files are wiring, and wiring rots quietly.

	A Custom chart names its source, and the source names a Python path in a `.js` file that
	is never compiled or imported. Rename the function and nothing fails except the chart, in
	the browser, with a traceback no test would ever see.
	"""

	def test_every_shipped_chart_uses_a_source_this_app_ships(self):
		charts = list(shipped_charts())
		self.assertTrue(charts, "no Dashboard Chart fixtures found")
		sources = {source_doc["name"] for _folder, source_doc in shipped_sources()}

		for folder, chart in charts:
			with self.subTest(chart=folder):
				self.assertEqual(chart["chart_type"], "Custom")
				self.assertEqual(chart["module"], "Money Tracker")
				self.assertIn(chart["source"], sources)

	def test_every_shipped_chart_declares_a_document_type(self):
		"""Dashboard Chart's permission hook grants a Custom chart on `document_type` when it
		carries no roles. Leave both blank and the chart is invisible to everyone who is not a
		System Manager — which is every Finance User the dashboard exists for."""
		for folder, chart in shipped_charts():
			with self.subTest(chart=folder):
				self.assertTrue(chart.get("document_type"))
				self.assertTrue(frappe.db.exists("DocType", chart["document_type"]))

	def test_every_source_registers_itself_and_a_whitelisted_method(self):
		"""The `.js` is read off disk and eval'd in the browser, so nothing else checks it."""
		for folder, source_doc in shipped_sources():
			with self.subTest(source=folder):
				path = os.path.join(source_dir(), folder, f"{folder}.js")
				self.assertTrue(os.path.exists(path), f"{folder} ships no .js — the chart cannot load")

				with open(path) as f:
					registration = f.read()

				self.assertIn(f'chart_sources["{source_doc["name"]}"]', registration)

				method_path = re.search(r'method:\s*"([^"]+)"', registration)
				self.assertTrue(method_path, "the source declares no method")
				method = frappe.get_attr(method_path.group(1))
				self.assertIn(method, frappe.whitelisted, f"{method_path.group(1)} is not whitelisted")

	def test_the_workspace_shows_the_charts_it_ships(self):
		path = frappe.get_app_path(
			"moneytracker", "money_tracker", "workspace", "money_tracker", "money_tracker.json"
		)
		with open(path) as f:
			workspace = json.load(f)

		shipped = {chart["name"] for _folder, chart in shipped_charts()}
		referenced = {row["chart_name"] for row in workspace["charts"]}
		in_content = {
			block["data"]["chart_name"]
			for block in json.loads(workspace["content"])
			if block["type"] == "chart"
		}

		self.assertEqual(referenced, shipped)
		# A chart listed but not laid out in `content` simply never renders.
		self.assertEqual(in_content, shipped)

	def test_the_charts_reached_the_site(self):
		"""sync_all imports the source and sync_dashboards the charts, both on migrate."""
		for _folder, source_doc in shipped_sources():
			self.assertTrue(
				frappe.db.exists("Dashboard Chart Source", source_doc["name"]),
				f"{source_doc['name']} is missing — run `bench --site <site> migrate`",
			)
		for _folder, chart in shipped_charts():
			self.assertTrue(
				frappe.db.exists("Dashboard Chart", chart["name"]),
				f"{chart['name']} is missing — run `bench --site <site> migrate`",
			)

	def test_a_shipped_charts_own_series_survives_a_tracker_filter(self):
		"""Spending Trend is one series *because of* its filters_json. Passing a tracker and
		nothing else used to replace that wholesale and quietly draw income back onto it.
		"""
		result = source.get(chart_name="Spending Trend", filters={"tracker": make_tracker().name})

		self.assertEqual([d["name"] for d in result["datasets"]], ["Expense"])

	def test_an_explicit_series_still_overrides_the_saved_one(self):
		result = source.get(
			chart_name="Spending Trend",
			filters={"tracker": make_tracker().name, "series": "Income"},
		)

		self.assertEqual([d["name"] for d in result["datasets"]], ["Income"])

	def test_a_shipped_chart_draws_through_its_own_name(self):
		"""The path the widget takes: chart name in, labels and datasets out."""
		self.assertTrue(frappe.db.exists("Dashboard Chart", "Income vs Expense"))

		tracker = make_tracker().name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Income").name
		make_transaction("Income", 1234, account, tracker=tracker, category=category)

		result = source.get(chart_name="Income vs Expense", filters={"tracker": tracker})

		self.assertEqual([d["name"] for d in result["datasets"]], ["Income", "Expense"])
		self.assertMoneyEqual(result["datasets"][0]["values"][-1], 1234)
