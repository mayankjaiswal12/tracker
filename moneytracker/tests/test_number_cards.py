# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The dashboard Number Cards (spec §5).

Two things are being guarded here. The arithmetic — a card must never disagree with the
ledger the reports are drawn from — and the wiring: a Custom card is just a method path in
a JSON file, so a renamed function fails silently in the browser and nowhere else. The
fixture tests at the bottom fail loudly instead.
"""

import json
import os
import re

import frappe
from frappe.utils import add_days, get_first_day

from moneytracker.money_tracker.api import dashboard
from moneytracker.money_tracker.services import balances
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


def amount(card_value):
	"""The number a card printed, with the currency formatting stripped off.

	Asserting on the digits rather than on the whole string keeps these tests independent of
	the site's number format, which is Indian here (99,800.00) and need not stay that way.
	"""
	return float(re.sub(r"[^\d.\-]", "", card_value))


def card_dir():
	return frappe.get_app_path("moneytracker", "money_tracker", "number_card")


def shipped_cards():
	"""Every Number Card JSON this app ships, read from disk rather than from the site.

	sync_dashboards imports these on migrate, so the file is the source of truth; reading
	the DB instead would pass on a site where the import silently never ran.
	"""
	for folder in sorted(os.listdir(card_dir())):
		path = os.path.join(card_dir(), folder, f"{folder}.json")
		if os.path.exists(path):
			with open(path) as f:
				yield folder, json.load(f)


class TestNumberCards(MoneyTrackerTestCase):
	"""The same six-transaction run as test_balances, read back through the cards.

	bank 39500 · sbi 8000 · card 2000 owed → assets 47500, net worth 45500,
	income 50000, expense 2000 + 3000 - 500 = 4500.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
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

		# str(): these filters are also round-tripped through json.dumps below, and a date is
		# not JSON-serialisable — filters_json never holds one either.
		cls.filters = {"tracker": cls.tracker, "as_of": str(cls.date)}

	def test_total_balance_is_what_the_asset_accounts_hold(self):
		self.assertMoneyEqual(amount(dashboard.card_total_balance(self.filters)), 47500)

	def test_total_balance_does_not_add_credit_card_debt_to_your_money(self):
		"""Every account is reported in its natural direction, so 2000 owed reads as +2000.

		Summing that in would print 49500 — more money than exists — and the number would
		*rise* every time the card was used.
		"""
		rows = {r["money_account"]: r for r in balances.get_balances_for_tracker(self.tracker)}

		self.assertMoneyEqual(rows[self.card]["balance"], 2000)
		self.assertMoneyEqual(amount(dashboard.card_total_balance(self.filters)), 47500)

	def test_net_worth_subtracts_the_liability(self):
		self.assertMoneyEqual(amount(dashboard.card_net_worth(self.filters)), 45500)

	def test_monthly_income(self):
		self.assertMoneyEqual(amount(dashboard.card_monthly_income(self.filters)), 50000)

	def test_monthly_expense_is_net_of_refunds(self):
		"""A refund reduces spend rather than adding income (§62): 2000 + 3000 - 500."""
		self.assertMoneyEqual(amount(dashboard.card_monthly_expense(self.filters)), 4500)

	def test_transfers_and_card_payments_are_not_spending(self):
		"""The 8000 transfer and the 1000 card payment moved money without spending it."""
		self.assertMoneyEqual(amount(dashboard.card_monthly_expense(self.filters)), 4500)
		self.assertMoneyEqual(amount(dashboard.card_monthly_income(self.filters)), 50000)

	def test_savings_rate(self):
		# (50000 - 4500) / 50000
		self.assertEqual(dashboard.card_savings_rate(self.filters), "91.0%")

	def test_the_cards_agree_with_get_dashboard(self):
		"""One dashboard, one set of numbers — the cards must not be a second implementation."""
		summary = dashboard.get_dashboard(tracker=self.tracker, as_of=self.date)

		self.assertMoneyEqual(amount(dashboard.card_total_balance(self.filters)), summary["total_balance"])
		self.assertMoneyEqual(amount(dashboard.card_net_worth(self.filters)), summary["net_worth"])
		self.assertMoneyEqual(amount(dashboard.card_monthly_income(self.filters)), summary["monthly_income"])
		self.assertMoneyEqual(
			amount(dashboard.card_monthly_expense(self.filters)), summary["monthly_expense"]
		)

	def test_the_figures_carry_the_tracker_currency(self):
		currency = frappe.db.get_value("Tracker", self.tracker, "base_currency")
		symbol = frappe.db.get_value("Currency", currency, "symbol") or currency

		self.assertIn(symbol, dashboard.card_total_balance(self.filters))

	def test_as_of_excludes_later_postings(self):
		yesterday = {"tracker": self.tracker, "as_of": str(add_days(self.date, -1))}

		self.assertMoneyEqual(amount(dashboard.card_total_balance(yesterday)), 0)
		self.assertMoneyEqual(amount(dashboard.card_net_worth(yesterday)), 0)

	def test_a_month_card_covers_the_month_as_of_falls_in(self):
		"""The month cards are a calendar month, not a running total up to `as_of`.

		So the balance cards move when `as_of` moves by a day and these do not — they only
		change when it crosses into another month.
		"""
		last_month = {"tracker": self.tracker, "as_of": str(add_days(get_first_day(self.date), -1))}

		self.assertMoneyEqual(amount(dashboard.card_monthly_income(last_month)), 0)
		self.assertMoneyEqual(amount(dashboard.card_monthly_expense(last_month)), 0)
		self.assertEqual(dashboard.card_savings_rate(last_month), dashboard.CARD_NO_DATA)

	def test_filters_may_arrive_as_a_json_string(self):
		"""filters_json reaches the method already parsed, but a direct API call may not."""
		self.assertEqual(
			dashboard.card_total_balance(json.dumps(self.filters)),
			dashboard.card_total_balance(self.filters),
		)

	def test_filters_may_arrive_as_desks_list_of_conditions(self):
		"""Editing a card's filters in Desk writes [[doctype, fieldname, operator, value]]."""
		self.assertEqual(
			dashboard.card_total_balance([["Transaction", "tracker", "=", self.tracker]]),
			dashboard.card_total_balance({"tracker": self.tracker}),
		)

	def test_a_tracker_the_user_may_not_read_is_refused(self):
		"""The card takes a tracker straight from its filters, so it has to check it."""
		stranger = make_user()
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			dashboard.card_total_balance(self.filters)


class TestCardsWithoutData(MoneyTrackerTestCase):
	def test_a_user_with_no_tracker_gets_no_data(self):
		newcomer = make_user()
		with as_user(newcomer):
			for card in (
				dashboard.card_total_balance,
				dashboard.card_net_worth,
				dashboard.card_monthly_income,
				dashboard.card_monthly_expense,
				dashboard.card_savings_rate,
			):
				self.assertEqual(card(), dashboard.CARD_NO_DATA, card.__name__)

	def test_rendering_a_card_does_not_create_a_tracker(self):
		"""get_default_tracker() creates one on first use; a dashboard render must not.

		Painting a card is a read. If it wrote, every visit by a user who has no books yet
		would leave a Tracker behind.
		"""
		newcomer = make_user()
		before = frappe.db.count("Tracker")

		with as_user(newcomer):
			dashboard.card_total_balance()

		self.assertEqual(frappe.db.count("Tracker"), before)

	def test_savings_rate_has_no_denominator_without_income(self):
		"""0/0 is not 0% — spending with no income at all is not a savings rate."""
		tracker = make_tracker().name
		account = make_account(tracker, account_type="Bank").name
		category = make_category(tracker, category_type="Expense").name
		make_transaction("Expense", 100, account, tracker=tracker, category=category)

		filters = {"tracker": tracker, "as_of": self.date}
		self.assertEqual(dashboard.card_savings_rate(filters), dashboard.CARD_NO_DATA)
		self.assertMoneyEqual(amount(dashboard.card_monthly_expense(filters)), 100)

	def test_an_empty_tracker_reports_zero_rather_than_nothing(self):
		empty = {"tracker": make_tracker().name, "as_of": self.date}

		self.assertMoneyEqual(amount(dashboard.card_total_balance(empty)), 0)
		self.assertMoneyEqual(amount(dashboard.card_net_worth(empty)), 0)


class TestCardIsolation(MoneyTrackerTestCase):
	"""Two trackers on one shared ERPNext Account — a card must show only its own money.

	Same trap as balances.py: `coa.get_or_create_ledger_account` matches on account name and
	ignores the parent, so two people who both call an account "Cash" post into one ledger
	account, and only the Tracker dimension tells them apart.
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

	def test_each_tracker_reads_only_its_own_total(self):
		self.assertMoneyEqual(amount(dashboard.card_total_balance({"tracker": self.tracker_a})), 100)
		self.assertMoneyEqual(amount(dashboard.card_total_balance({"tracker": self.tracker_b})), 4242)

	def test_income_is_scoped_too(self):
		filters_a = {"tracker": self.tracker_a, "as_of": self.date}
		self.assertMoneyEqual(amount(dashboard.card_monthly_income(filters_a)), 100)

	def test_an_unfiltered_card_falls_back_to_the_users_own_tracker(self):
		"""No filters means "my money", never everybody's."""
		owner = make_user()
		tracker = make_tracker(owner_user=owner).name
		account = make_account(tracker, account_type="Cash").name
		category = make_category(tracker, category_type="Income").name
		make_transaction("Income", 77, account, tracker=tracker, category=category)

		with as_user(owner):
			self.assertMoneyEqual(amount(dashboard.card_total_balance()), 77)


class TestShippedCardFixtures(MoneyTrackerTestCase):
	"""The JSON files are wiring, and wiring rots quietly.

	A Custom card names its method as a string. Rename the function and nothing fails except
	the card, in the browser, with a traceback no test would ever see.
	"""

	def test_every_shipped_card_points_at_a_whitelisted_method(self):
		cards = list(shipped_cards())
		self.assertTrue(cards, "no Number Card fixtures found")

		for folder, card in cards:
			with self.subTest(card=folder):
				self.assertEqual(card["type"], "Custom")
				self.assertEqual(card["module"], "Money Tracker")

				method = frappe.get_attr(card["method"])
				self.assertIn(method, frappe.whitelisted, f"{card['method']} is not whitelisted")

	def test_every_shipped_card_declares_a_document_type(self):
		"""Number Card's own permission hooks gate a Custom card on `document_type`.

		Leave it blank and the card is invisible to everyone who is not a System Manager —
		which is every Finance User the dashboard exists for.
		"""
		for folder, card in shipped_cards():
			with self.subTest(card=folder):
				self.assertTrue(card.get("document_type"))
				self.assertTrue(frappe.db.exists("DocType", card["document_type"]))

	def test_the_workspace_shows_the_cards_it_ships(self):
		path = frappe.get_app_path(
			"moneytracker", "money_tracker", "workspace", "money_tracker", "money_tracker.json"
		)
		with open(path) as f:
			workspace = json.load(f)

		shipped = {card["name"] for _folder, card in shipped_cards()}
		referenced = {row["number_card_name"] for row in workspace["number_cards"]}
		in_content = {
			block["data"]["number_card_name"]
			for block in json.loads(workspace["content"])
			if block["type"] == "number_card"
		}

		self.assertEqual(referenced, shipped)
		# A card listed but not laid out in `content` simply never renders.
		self.assertEqual(in_content, shipped)

	def test_the_cards_reached_the_site(self):
		"""sync_dashboards imports these on migrate; this is the check that it happened."""
		for _folder, card in shipped_cards():
			with self.subTest(card=card["name"]):
				self.assertTrue(
					frappe.db.exists("Number Card", card["name"]),
					f"{card['name']} is missing — run `bench --site <site> migrate`",
				)
