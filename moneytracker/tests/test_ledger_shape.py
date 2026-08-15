# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""What may never appear as spending, and the reports that come for free.

These are the invariants that justify the whole ERPNext migration. They are asserted
against GL Entry joined to Account.root_type rather than by scraping report output — same
question the P&L answers, without the brittleness — plus one real run of ERPNext's Trial
Balance to prove the Tracker dimension reaches the reports.
"""

import frappe
from frappe.utils import flt

from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	gl_rows,
	ledger_movement,
	make_account,
	make_category,
	make_tracker,
	make_transaction,
	root_types_touched,
)


class TestLedgerShape(MoneyTrackerTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.sbi = make_account(cls.tracker, account_type="Bank").name
		cls.card = make_account(cls.tracker, account_type="Credit Card").name
		cls.food = make_category(cls.tracker, category_type="Expense").name
		cls.salary = make_category(cls.tracker, category_type="Income").name
		cls.food_ledger = frappe.db.get_value("Category", cls.food, "ledger_account")

		def post(transaction_type, amount, account, **kwargs):
			return make_transaction(transaction_type, amount, account, tracker=cls.tracker, **kwargs)

		cls.income = post("Income", 50000, cls.bank, category=cls.salary)
		cls.bank_expense = post("Expense", 2000, cls.bank, category=cls.food)
		cls.card_expense = post("Expense", 3000, cls.card, category=cls.food)
		cls.transfer = post("Transfer", 8000, cls.bank, destination_account=cls.sbi)
		cls.card_payment = post("Credit Card Payment", 1000, cls.bank, destination_account=cls.card)
		cls.refund = post("Refund", 500, cls.bank, category=cls.food)

	def test_a_transfer_touches_only_asset_accounts(self):
		"""Moving your own money between your own accounts is not spending."""
		self.assertEqual(root_types_touched(self.transfer.journal_entry), {"Asset"})

	def test_a_credit_card_payment_touches_only_balance_sheet_accounts(self):
		"""The expense was recorded when the card was used; settling it is not a second one."""
		self.assertEqual(root_types_touched(self.card_payment.journal_entry), {"Asset", "Liability"})

	def test_neither_settlement_can_appear_in_income_or_expense(self):
		for transaction in (self.transfer, self.card_payment):
			touched = root_types_touched(transaction.journal_entry)
			self.assertNotIn("Income", touched)
			self.assertNotIn("Expense", touched)

	def test_a_refund_credits_the_expense_category(self):
		"""Spec §62: booking it as income would overstate both sides of the P&L."""
		rows = gl_rows(self.refund.journal_entry, include_cancelled=False)
		credited = [row for row in rows if flt(row.credit)]

		self.assertEqual(len(credited), 1)
		self.assertEqual(credited[0].account, self.food_ledger)
		self.assertNotIn("Income", root_types_touched(self.refund.journal_entry))

	def test_the_refund_lowers_net_spend_rather_than_raising_income(self):
		# 2000 on the bank + 3000 on the card - 500 refunded
		self.assertMoneyEqual(ledger_movement(self.food_ledger, self.tracker), 4500)

	def test_an_expense_paid_by_card_grows_the_liability(self):
		card_ledger = frappe.db.get_value("Money Account", self.card, "ledger_account")
		# 3000 charged (credit) less 1000 paid off (debit); a liability is credit-positive.
		self.assertMoneyEqual(ledger_movement(card_ledger, self.tracker), -2000)

	def test_only_income_and_expense_reach_the_profit_and_loss(self):
		"""Six transactions, but only three of them are income or expense."""
		vouchers = frappe.get_all(
			"GL Entry",
			filters={"tracker": self.tracker, "is_cancelled": 0},
			fields=["voucher_no", "account"],
		)
		root_by_account = {
			account.name: account.root_type
			for account in frappe.get_all(
				"Account",
				filters={"name": ["in", list({row.account for row in vouchers})]},
				fields=["name", "root_type"],
			)
		}
		on_the_pl = {
			row.voucher_no for row in vouchers if root_by_account[row.account] in ("Income", "Expense")
		}

		self.assertEqual(
			on_the_pl,
			{
				self.income.journal_entry,
				self.bank_expense.journal_entry,
				self.card_expense.journal_entry,
				self.refund.journal_entry,
			},
		)


class TestTrackerDimension(MoneyTrackerTestCase):
	"""Tracker is registered as an ERPNext Accounting Dimension — that is the whole reporting
	story. If the registration patch stops running, the field vanishes from GL Entry and
	every balance and report filter silently matches nothing."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tracker = make_tracker().name
		cls.other_tracker = make_tracker().name
		cls.bank = make_account(cls.tracker, account_type="Bank").name
		cls.salary = make_category(cls.tracker, category_type="Income").name
		cls.food = make_category(cls.tracker, category_type="Expense").name

		make_transaction("Income", 9000, cls.bank, tracker=cls.tracker, category=cls.salary)
		make_transaction("Expense", 1500, cls.bank, tracker=cls.tracker, category=cls.food)

	def test_tracker_is_registered_as_an_accounting_dimension(self):
		self.assertTrue(frappe.db.exists("Accounting Dimension", {"document_type": "Tracker"}))

	def test_the_dimension_field_exists_where_posting_needs_it(self):
		for doctype in ("GL Entry", "Journal Entry Account"):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "tracker"}),
				f"{doctype} has no tracker field",
			)

	def test_the_trial_balance_balances_for_one_tracker(self):
		"""ERPNext's own report, filtered by a dimension this app contributed.

		The dimension filter is applied with `.isin(...)`, so a programmatic call has to pass
		a **list** — a bare string silently matches nothing.
		"""
		rows = self.trial_balance([self.tracker])
		total = rows[-1]

		self.assertMoneyEqual(total["debit"], total["credit"])
		self.assertMoneyEqual(total["debit"], 10500)  # 9000 income + 1500 expense

	def test_the_trial_balance_excludes_another_tracker(self):
		"""A tracker with no postings reports nothing but its (zero) total row."""
		rows = self.trial_balance([self.other_tracker])

		self.assertEqual([row for row in rows if row["account"] != "'Total'"], [])
		self.assertMoneyEqual(rows[-1]["debit"], 0)
		self.assertMoneyEqual(rows[-1]["credit"], 0)

	def trial_balance(self, trackers):
		from erpnext.accounts.report.trial_balance.trial_balance import execute

		year = frappe.get_all(
			"Fiscal Year",
			filters={"year_start_date": ["<=", self.date], "year_end_date": [">=", self.date]},
			fields=["name", "year_start_date", "year_end_date"],
			limit=1,
		)[0]

		return execute(
			frappe._dict(
				{
					"company": self.company,
					"fiscal_year": year.name,
					"from_date": year.year_start_date,
					"to_date": year.year_end_date,
					"with_period_closing_entry_for_opening": 0,
					"show_zero_values": 0,
					"include_default_book_entries": 1,
					"tracker": trackers,
				}
			)
		)[1]
