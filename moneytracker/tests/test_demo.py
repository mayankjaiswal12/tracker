# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The demo data (spec §87).

Most of this costs nothing to check: the plan is a table of names, and every way it can rot
— a category renamed in `DEFAULT_CATEGORIES`, an account referenced but never created, a
transaction type that is still only planned — is a lookup, not a posting. Those tests run
without touching the database.

Two do post, because the only way to know a seeder works is to run it: one month in, and
then out again leaving nothing behind.
"""

from contextlib import contextmanager

import frappe
from frappe.utils import get_first_day, getdate, today

from moneytracker.money_tracker import demo
from moneytracker.money_tracker.posting import strategies
from moneytracker.money_tracker.services import coa, goals, subscriptions
from moneytracker.money_tracker.services.categories import DEFAULT_CATEGORIES
from moneytracker.tests.utils import MoneyTrackerTestCase, unique

ACCOUNT_TYPES = {name: account_type for name, account_type, _group, _bank in demo.DEMO_ACCOUNTS}


def every_row():
	"""Every row of the plan, monthly and one-off alike, with where it came from."""
	for row in demo.MONTHLY:
		yield "MONTHLY", row
	for index, rows in sorted(demo.ONE_OFFS.items()):
		for row in rows:
			yield f"ONE_OFFS[{index}]", row


def seeded_categories():
	"""The leaf categories `Tracker.after_insert` actually creates, by type.

	A group is excluded: `Transaction.validate` refuses to post to one, so naming a group in
	the plan would fail at submit time on a real run and nowhere earlier.
	"""
	leaves = {"Income": set(), "Expense": set()}
	for category_type, groups in DEFAULT_CATEGORIES.items():
		for label, children in groups:
			if children:
				leaves[category_type].update(children)
			else:
				leaves[category_type].add(label)
	return leaves


@contextmanager
def demo_allowed():
	"""`demo.py` refuses to run under test unless a caller opts in, which is the point."""
	previous = frappe.flags.allow_demo_data
	frappe.flags.allow_demo_data = True
	try:
		yield
	finally:
		frappe.flags.allow_demo_data = previous


class TestDemoPlan(MoneyTrackerTestCase):
	"""The plan as data — no posting, so this stays fast and still catches the real rot."""

	def test_every_row_names_an_account_the_demo_creates(self):
		for origin, row in every_row():
			with self.subTest(origin=origin, day=row["day"]):
				self.assertIn(row["account"], ACCOUNT_TYPES)
				if row.get("destination_account"):
					self.assertIn(row["destination_account"], ACCOUNT_TYPES)

	def test_every_row_names_a_category_the_default_tree_seeds(self):
		"""The plan resolves categories by name against the seeded tree and throws if one is
		missing, so a rename in DEFAULT_CATEGORIES breaks the demo. This is cheaper than
		finding out at transaction 40 of 80."""
		leaves = seeded_categories()

		for origin, row in every_row():
			if not row.get("category"):
				continue
			category_type = "Income" if row["transaction_type"] == "Income" else "Expense"
			with self.subTest(origin=origin, category=row["category"]):
				self.assertIn(row["category"], leaves[category_type])

	def test_every_row_uses_an_implemented_strategy(self):
		"""Nine of the transaction types are declared but only planned; one in the demo would
		fail at submit with "not implemented yet"."""
		for origin, row in every_row():
			with self.subTest(origin=origin, type=row["transaction_type"]):
				self.assertIn(row["transaction_type"], strategies.STRATEGIES)
				self.assertNotIn(row["transaction_type"], strategies.PLANNED)

	def test_a_credit_card_payment_settles_a_credit_card(self):
		"""Dr card / Cr bank. Point it at a bank and the strategy refuses outright."""
		payments = [row for _origin, row in every_row() if row["transaction_type"] == "Credit Card Payment"]
		self.assertTrue(payments, "the demo should show a card being paid off")

		for row in payments:
			self.assertEqual(ACCOUNT_TYPES[row["destination_account"]], "Credit Card")
			self.assertNotEqual(ACCOUNT_TYPES[row["account"]], "Credit Card")

	def test_a_refund_credits_an_expense_category(self):
		"""A refund is not income (§62) — the strategy demands an Expense category."""
		refunds = [row for _origin, row in every_row() if row["transaction_type"] == "Refund"]
		self.assertTrue(refunds, "the demo should show a refund, it is the subtlest rule here")

		for row in refunds:
			self.assertIn(row["category"], seeded_categories()["Expense"])

	def test_transfers_and_card_payments_carry_no_category(self):
		"""They touch only balance-sheet accounts, so a category on one is meaningless."""
		for origin, row in every_row():
			if row["transaction_type"] in ("Transfer", "Credit Card Payment"):
				with self.subTest(origin=origin):
					self.assertIsNone(row.get("category"))
					self.assertTrue(row.get("destination_account"))

	def test_every_day_exists_in_every_month(self):
		"""The dates are built by replacing the day on the 1st, so a 29th would blow up in
		February and nowhere else."""
		for origin, row in every_row():
			with self.subTest(origin=origin):
				self.assertGreaterEqual(row["day"], 1)
				self.assertLessEqual(row["day"], 28)

	def test_the_monthly_plan_is_in_date_order(self):
		"""Not cosmetic: income lands before the spending it pays for, and the cash
		withdrawal before the cash is spent, so no account is driven negative."""
		days = [row["day"] for row in demo.MONTHLY]
		self.assertEqual(days, sorted(days))

	def test_every_payment_method_named_is_one_the_demo_seeds(self):
		seeded = {method_name for method_name, _applies in demo.PAYMENT_METHODS}

		for origin, row in every_row():
			if row.get("payment_method"):
				with self.subTest(origin=origin):
					self.assertIn(row["payment_method"], seeded)

	def test_the_month_ends_solvent(self):
		"""Sum the monthly plan per account: the bank must not be drained and the wallet must
		be funded before it is spent from."""
		net = dict.fromkeys(ACCOUNT_TYPES, 0.0)
		for row in demo.MONTHLY:
			if row["transaction_type"] == "Income":
				net[row["account"]] += row["amount"]
			elif row["transaction_type"] in ("Transfer", "Credit Card Payment"):
				net[row["account"]] -= row["amount"]
				net[row["destination_account"]] += row["amount"]
			else:
				net[row["account"]] -= row["amount"]

		self.assertGreater(net["HDFC Bank"], 0, "the bank should be ahead at the end of a month")
		self.assertGreater(net["Wallet"], 0, "the wallet is topped up by more than it spends")


class TestDemoGoals(MoneyTrackerTestCase):
	"""The goal plan, checked the same way as the transaction plan: as data.

	A demo goal names an account, a category and a goal type, and every one of those can rot
	without anything failing until somebody looks at the workspace and sees an empty chart.
	"""

	def test_every_goal_uses_an_implemented_type(self):
		for row in demo.DEMO_GOALS:
			with self.subTest(goal=row["goal_name"]):
				self.assertIn(row["goal_type"], goals.GOAL_TYPES)

	def test_the_plan_shows_every_measure_at_least_once(self):
		"""The point of the demo set: each measure in GOAL_TYPES visible on the workspace."""
		self.assertEqual({row["goal_type"] for row in demo.DEMO_GOALS}, set(goals.GOAL_TYPE_OPTIONS))

	def test_every_goal_names_an_account_the_demo_creates(self):
		created = {name for name, _type, _group, _bank in demo.DEMO_ACCOUNTS}

		for row in demo.DEMO_GOALS:
			if row.get("target_account"):
				with self.subTest(goal=row["goal_name"]):
					self.assertIn(row["target_account"], created)

	def test_a_goal_names_an_account_of_the_side_its_type_needs(self):
		"""A Savings goal on a credit card, or a Debt Payoff on a bank, is refused on save."""
		for row in demo.DEMO_GOALS:
			spec = goals.GOAL_TYPES[row["goal_type"]]
			if not spec.account:
				with self.subTest(goal=row["goal_name"]):
					self.assertIsNone(row.get("target_account"))
				continue

			with self.subTest(goal=row["goal_name"]):
				account_type = ACCOUNT_TYPES[row["target_account"]]
				self.assertEqual(coa.is_liability(account_type), spec.account == "Liability")

	def test_every_goal_names_a_category_the_default_tree_seeds(self):
		"""Same rule as the transactions — except a goal may name a *group*, since a limit on
		one rolls up its children."""
		leaves = seeded_categories()
		groups = {
			label
			for category_type, entries in DEFAULT_CATEGORIES.items()
			for label, children in entries
			if children
		}

		for row in demo.DEMO_GOALS:
			if not row.get("category"):
				continue
			category_type = "Income" if row["goal_type"] == "Income Target" else "Expense"
			with self.subTest(goal=row["goal_name"]):
				self.assertIn(row["category"], leaves[category_type] | groups)

	def test_a_goal_carries_the_target_field_its_unit_needs(self):
		"""A percentage goal is refused a target amount and vice versa."""
		for row in demo.DEMO_GOALS:
			spec = goals.GOAL_TYPES[row["goal_type"]]
			with self.subTest(goal=row["goal_name"]):
				if spec.unit == goals.PERCENT:
					self.assertTrue(0 < row.get("target_percent", 0) <= 100)
				else:
					self.assertGreater(row.get("target_amount", 0), 0)

	def test_every_window_is_one_the_planner_knows(self):
		self.assertEqual(
			{row["window"] for row in demo.DEMO_GOALS} - {"month", "year", "horizon", "recent"}, set()
		)

	def test_a_period_goal_gets_a_window_that_ends(self):
		"""`needs_deadline` types are refused without a target date, and every named window
		here supplies one — but a window keyed wrong would only fail when the demo is run."""
		period = [getdate(get_first_day(today()))]

		for row in demo.DEMO_GOALS:
			with self.subTest(goal=row["goal_name"]):
				start_date, target_date = demo._goal_window(row["window"], period)
				self.assertTrue(target_date)
				self.assertGreaterEqual(target_date, start_date)


class TestDemoSubscriptions(MoneyTrackerTestCase):
	"""The subscription plan as data. A subscription is nothing but its state, so what can rot
	here is a state the demo claims to show and no longer does."""

	def test_every_subscription_names_an_account_the_demo_creates(self):
		created = {name for name, _type, _group, _bank in demo.DEMO_ACCOUNTS}
		for row in demo.DEMO_SUBSCRIPTIONS:
			with self.subTest(subscription=row["subscription_name"]):
				self.assertIn(row["account"], created)

	def test_every_subscription_names_a_leaf_category_the_default_tree_seeds(self):
		"""A leaf, not a group: the category is what a payment for it would be filed under,
		and a transaction cannot post to a heading."""
		leaves = seeded_categories()["Expense"]
		for row in demo.DEMO_SUBSCRIPTIONS:
			with self.subTest(subscription=row["subscription_name"]):
				self.assertIn(row["category"], leaves)

	def test_every_payment_method_named_is_one_the_demo_seeds(self):
		seeded = {name for name, _applies_to in demo.PAYMENT_METHODS}
		for row in demo.DEMO_SUBSCRIPTIONS:
			with self.subTest(subscription=row["subscription_name"]):
				self.assertIn(row["payment_method"], seeded)

	def test_every_billing_frequency_is_one_the_table_knows(self):
		for row in demo.DEMO_SUBSCRIPTIONS:
			with self.subTest(subscription=row["subscription_name"]):
				self.assertIn(row["billing_frequency"], subscriptions.FREQUENCY_OPTIONS)

	def test_the_plan_shows_a_trial_a_notice_period_and_a_price_rise(self):
		"""The three things only a subscription has. A demo without them shows nothing this
		doctype could not have been a standing order."""
		self.assertTrue(any("trial_in_days" in row for row in demo.DEMO_SUBSCRIPTIONS))
		self.assertTrue(any(row.get("notice_period_days") for row in demo.DEMO_SUBSCRIPTIONS))
		self.assertTrue(any(row.get("prices") for row in demo.DEMO_SUBSCRIPTIONS))

	def test_the_plan_shows_every_status_the_doctype_allows(self):
		selectable = frappe.get_meta("Money Subscription").get_field("status").options.split("\n")
		self.assertEqual({row.get("status", "Active") for row in demo.DEMO_SUBSCRIPTIONS}, set(selectable))

	def test_no_subscription_claims_a_plan(self):
		"""The household's one streaming standing order pays for two services, and a
		subscription claims a whole plan. Linking one would misstate what the plan pays for."""
		for row in demo.DEMO_SUBSCRIPTIONS:
			with self.subTest(subscription=row["subscription_name"]):
				self.assertNotIn("recurring_transaction", row)

	def test_a_price_rise_is_dated_before_today(self):
		"""`record_price` would collide with the opening row if a rise were dated today, and a
		rise in the future is not a rise that happened."""
		for row in demo.DEMO_SUBSCRIPTIONS:
			for offset, _amount, _note in row.get("prices", ()):
				with self.subTest(subscription=row["subscription_name"], offset=offset):
					self.assertLess(offset, 0)
					self.assertGreater(offset, row["start_in_days"])


class TestDemoRefusals(MoneyTrackerTestCase):
	def test_it_refuses_to_run_during_a_test(self):
		"""Without the opt-in. Demo data in a suite run would skew every total in it."""
		with self.assertRaises(frappe.ValidationError):
			demo.setup_demo_data(months=1)

	def test_the_teardown_refuses_a_tracker_that_is_not_demo_data(self):
		"""The marker, not the name, is what makes deleting a tracker's ledger safe."""
		from moneytracker.tests.utils import make_tracker

		innocent = make_tracker(tracker_name="Demo Household").name

		with demo_allowed(), self.assertRaises(frappe.ValidationError):
			demo.clear_demo_data(tracker=innocent)

		self.assertTrue(frappe.db.exists("Tracker", innocent))

	def test_the_teardown_is_not_reachable_over_http(self):
		"""It deletes GL Entry rows outright, and it is only ever run from `bench execute`.

		Its `only_for("System Manager")` cannot be tested — Frappe makes `only_for` a no-op
		under test — so the absence of the whitelist is what gets asserted instead. Whitelist
		it and this fails, which is the point.
		"""
		self.assertNotIn(demo.clear_demo_data, frappe.whitelisted)
		self.assertNotIn(demo.setup_demo_data, frappe.whitelisted)


class TestDemoRoundTrip(MoneyTrackerTestCase):
	"""One month in and out again. The only way to know a seeder works is to run it.

	Each test seeds its *own* uniquely named tracker rather than the shipped
	`Demo Household`. A seeder must work on a site that already has demo data on it, and a
	test that assumes the opposite fails on exactly the site the feature is written for.
	"""

	def test_one_month_posts_and_then_clears_completely(self):
		before = {
			doctype: frappe.db.count(doctype)
			for doctype in (
				"Tracker",
				"Money Account",
				"Category",
				"Transaction",
				"Journal Entry",
				"Money Subscription",
				# The child table too: `Money Subscription` goes by `delete_doc`, which clears
				# its rows — unlike `Transaction`, which goes by raw table delete and needs
				# `TRANSACTION_CHILD_TABLES` for exactly that reason.
				"Money Subscription Price",
			)
		}

		with demo_allowed():
			summary = demo.setup_demo_data(months=1, tracker_name=unique("Demo"))

		tracker = summary["tracker"]
		self.assertGreater(summary["transactions_posted"], 0)
		self.assertEqual(frappe.db.count("Transaction", {"tracker": tracker}), summary["transactions_posted"])

		# Every posting reached the ledger, and every GL row carries the dimension the
		# teardown deletes by.
		gl_rows = frappe.get_all("GL Entry", filters={"tracker": tracker}, fields=["debit", "credit"])
		self.assertTrue(gl_rows)
		self.assertMoneyEqual(sum(r.debit for r in gl_rows), sum(r.credit for r in gl_rows))

		with demo_allowed():
			demo.clear_demo_data(tracker=tracker)

		self.assertFalse(frappe.db.exists("Tracker", tracker))
		self.assertEqual(frappe.db.count("GL Entry", {"tracker": tracker}), 0)
		for doctype, count in before.items():
			self.assertEqual(frappe.db.count(doctype), count, f"{doctype} was left behind")

	def test_it_refuses_to_seed_the_same_tracker_twice(self):
		"""By name, not globally: a second demo under a different name is a legitimate way to
		show two sets of books side by side on this shared Company."""
		name = unique("Demo")

		with demo_allowed():
			summary = demo.setup_demo_data(months=1, tracker_name=name)
			try:
				with self.assertRaises(frappe.ValidationError):
					demo.setup_demo_data(months=1, tracker_name=name)
			finally:
				demo.clear_demo_data(tracker=summary["tracker"])


class TestTeardownLeavesNothingBehind(MoneyTrackerTestCase):
	"""Transactions are cleared by raw table delete, so their child rows must go by hand."""

	def test_the_child_table_list_matches_the_doctype(self):
		"""Derived from the meta, so adding a child table and forgetting the teardown fails here
		rather than leaving orphan rows nobody sees until something counts them."""
		declared = set(demo.TRANSACTION_CHILD_TABLES)
		actual = {
			field.options
			for field in frappe.get_meta("Transaction").fields
			if field.fieldtype in ("Table", "Table MultiSelect")
		}
		self.assertEqual(
			declared,
			actual,
			"demo.TRANSACTION_CHILD_TABLES is out of step with Transaction's child tables",
		)
