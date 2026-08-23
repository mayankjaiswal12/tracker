# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Loans: amortisation, and the one entry in this app that is two facts at once.

The property under test throughout is the one that separates a loan from a Debt Payoff goal:
**every payment is part principal and part interest**, and only one of those halves is
spending. Book the whole instalment as expense and the household looks poorer by the principal
every month; book none of it and the entire cost of borrowing disappears.

`TestAmortisation` touches no document at all — `services/loans.build_schedule` is arithmetic,
which is what makes an amortisation table something you can check by hand.
"""

import json
from pathlib import Path

import frappe
from frappe.utils import add_days, add_months, flt, getdate

from moneytracker.money_tracker.api import loans as loans_api
from moneytracker.money_tracker.posting import strategies
from moneytracker.money_tracker.services import categories, loans, trends
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_loan,
	make_tracker,
	make_transaction,
	posting_date,
)


class TestAmortisation(MoneyTrackerTestCase):
	"""Pure arithmetic: no loan document, no ledger, no site state."""

	def test_the_reducing_balance_instalment(self):
		"""100,000 at 12% over twelve months — the standard annuity."""
		self.assertMoneyEqual(loans.emi_for(100000, 12, 12), 8884.88)

	def test_the_flat_instalment_is_dearer_at_the_same_rate(self):
		"""Flat interest is charged on the original principal for the whole tenure, so half the
		loan is being charged for after it has been repaid. Always dearer, never the same."""
		reducing = loans.emi_for(100000, 12, 12, loans.REDUCING_BALANCE)
		flat = loans.emi_for(100000, 12, 12, loans.FLAT)
		self.assertMoneyEqual(flat, 9333.33)
		self.assertGreater(flat, reducing)

	def test_an_interest_free_loan_is_the_principal_divided_up(self):
		"""The case that divides by zero in every EMI formula, and a real kind of loan."""
		self.assertMoneyEqual(loans.emi_for(120000, 0, 12), 10000)

	def test_the_schedule_closes_at_exactly_zero(self):
		"""The last instalment absorbs the rounding. A schedule built by repeating a rounded EMI
		leaves a few paise owing forever, which is the one thing an amortisation table may not do.
		"""
		for interest_type in loans.INTEREST_TYPES:
			with self.subTest(interest_type=interest_type):
				rows = loans.build_schedule(100000, 12, 12, "2026-01-01", interest_type)
				self.assertEqual(len(rows), 12)
				self.assertMoneyEqual(rows[-1].closing_balance, 0)

	def test_the_principal_repaid_is_exactly_the_principal(self):
		rows = loans.build_schedule(100000, 12, 12, "2026-01-01")
		self.assertMoneyEqual(loans.schedule_totals(rows).principal, 100000)

	def test_the_interest_falls_as_the_balance_does(self):
		"""What "reducing balance" means, and the only thing that distinguishes it from flat."""
		rows = loans.build_schedule(100000, 12, 12, "2026-01-01", loans.REDUCING_BALANCE)
		self.assertGreater(rows[0].interest, rows[-1].interest)
		self.assertMoneyEqual(loans.schedule_totals(rows).interest, 6618.53)

	def test_flat_interest_is_the_same_every_month(self):
		rows = loans.build_schedule(100000, 12, 12, "2026-01-01", loans.FLAT)
		self.assertMoneyEqual(rows[0].interest, rows[-1].interest)
		self.assertMoneyEqual(loans.schedule_totals(rows).interest, 12000)

	def test_every_instalment_adds_up(self):
		for row in loans.build_schedule(100000, 12, 12, "2026-01-01"):
			with self.subTest(instalment=row.instalment):
				self.assertMoneyEqual(row.principal + row.interest, row.payment)
				self.assertMoneyEqual(row.opening_balance - row.principal, row.closing_balance)

	def test_the_month_end_rule_is_the_one_a_plan_follows(self):
		"""31 Jan → 28 Feb → **31** Mar. Thirty years of stepping off the previous date would
		lose the 31st permanently the first time it crossed a February."""
		rows = loans.build_schedule(100000, 12, 3, "2026-01-31")
		self.assertEqual(
			[row.due_date for row in rows],
			[getdate("2026-02-28"), getdate("2026-03-31"), getdate("2026-04-30")],
		)

	def test_a_single_bullet_repayment_is_a_valid_schedule(self):
		rows = loans.build_schedule(50000, 10, 1, "2026-01-01")
		self.assertEqual(len(rows), 1)
		self.assertMoneyEqual(rows[0].principal, 50000)

	def test_the_lenders_own_instalment_wins_when_given(self):
		"""Their rounding is not ours, and the paper they sent is the truth."""
		rows = loans.build_schedule(100000, 12, 12, "2026-01-01", emi=8900)
		self.assertMoneyEqual(rows[0].payment, 8900)
		self.assertMoneyEqual(rows[-1].closing_balance, 0)

	def test_an_instalment_too_small_to_cover_the_interest_is_refused(self):
		"""Such a schedule never ends: the balance grows every month."""
		with self.assertRaises(frappe.ValidationError):
			loans.build_schedule(100000, 12, 12, "2026-01-01", emi=500)

	def test_an_impossible_tenure_is_refused(self):
		for tenure in (0, loans.MAX_TENURE + 1):
			with self.subTest(tenure=tenure), self.assertRaises(frappe.ValidationError):
				loans.build_schedule(100000, 12, tenure, "2026-01-01")

	def test_a_principal_of_zero_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			loans.build_schedule(0, 12, 12, "2026-01-01")

	def test_an_unknown_interest_type_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError):
			loans.build_schedule(100000, 12, 12, "2026-01-01", "Compound Daily")


class LoanFixture(MoneyTrackerTestCase):
	"""A fresh tracker per test: measurements and card figures span the whole tracker."""

	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.bank = make_account(self.tracker, account_type="Bank").name
		self.loan_account = make_account(self.tracker, account_type="Loan").name
		self.interest = make_category(self.tracker, category_type="Expense").name

	def loan(self, **kwargs):
		kwargs.setdefault("loan_account", self.loan_account)
		kwargs.setdefault("interest_category", self.interest)
		return make_loan(self.tracker, **kwargs)

	def lent_loan(self, **kwargs):
		"""A loan the other way round: an asset account and an income category."""
		kwargs.setdefault("direction", "Lent")
		kwargs.setdefault("loan_account", make_account(self.tracker, account_type="Other Asset").name)
		kwargs.setdefault("interest_category", make_category(self.tracker, category_type="Income").name)
		return make_loan(self.tracker, **kwargs)

	def fund(self, amount=500000):
		"""Money in the bank, so a payment is not fighting the overdraft rule."""
		income = make_category(self.tracker, category_type="Income").name
		return make_transaction(
			"Income", amount, self.bank, tracker=self.tracker, category=income, date=posting_date()
		)

	def disbursed(self, **kwargs):
		"""A loan with its principal actually on the books, which is most of them.

		Until it is disbursed a loan has no debt to measure at all — its account sits at zero,
		which looks exactly like a loan that has been paid off. That is a state worth its own
		tests (below) and a bad default for every other one.
		"""
		loan = self.loan(**kwargs)
		loan.disburse(account=self.bank)
		loan.reload()
		return loan


class TestTheStoredSchedule(LoanFixture):
	def test_saving_a_loan_builds_its_schedule_and_stamps_the_instalment(self):
		loan = self.loan(principal=100000, interest_rate=12, tenure_months=12)
		self.assertEqual(len(loan.schedule), 12)
		self.assertMoneyEqual(loan.emi, 8884.88)

	def test_the_lenders_figure_overrides_the_arithmetic(self):
		loan = self.loan(emi_override=8900)
		self.assertMoneyEqual(loan.emi, 8900)

	def test_changing_a_term_rebuilds_the_table(self):
		loan = self.loan(tenure_months=12)
		loan.tenure_months = 24
		loan.save()
		self.assertEqual(len(loan.schedule), 24)


class TestTermsFreeze(LoanFixture):
	"""The rule that makes a *stored* schedule safe in an app that derives everything else."""

	def paid(self, loan):
		self.fund()
		return loan.post_instalment(from_account=self.bank)

	def test_a_term_cannot_change_once_a_payment_has_been_posted(self):
		loan = self.disbursed()
		self.paid(loan)

		loan.reload()
		loan.interest_rate = 18
		self.assertRaises(frappe.ValidationError, loan.save)

	def test_everything_else_can_still_be_edited(self):
		"""Freezing the terms must not freeze the document."""
		loan = self.disbursed()
		self.paid(loan)

		loan.reload()
		loan.notes = "Rescheduled by phone"
		loan.save()
		self.assertEqual(loan.notes, "Rescheduled by phone")

	def test_re_saving_with_the_same_terms_is_fine(self):
		loan = self.disbursed()
		self.paid(loan)
		loan.reload()
		loan.save()

	def test_terms_are_free_until_the_first_payment(self):
		loan = self.loan()
		loan.principal = 200000
		loan.save()
		self.assertMoneyEqual(loan.principal, 200000)


class TestValidation(LoanFixture):
	def test_borrowed_money_must_sit_on_a_liability(self):
		"""Both readings balance, so nothing downstream would catch it: the Balance Sheet would
		simply say the household owns what it owes."""
		with self.assertRaises(frappe.ValidationError):
			self.loan(loan_account=self.bank)

	def test_lent_money_must_not_sit_on_a_liability(self):
		with self.assertRaises(frappe.ValidationError):
			self.loan(direction="Lent", loan_account=self.loan_account)

	def test_interest_on_borrowed_money_needs_an_expense_category(self):
		income = make_category(self.tracker, category_type="Income").name
		with self.assertRaises(frappe.ValidationError):
			self.loan(interest_category=income)

	def test_interest_on_lent_money_needs_an_income_category(self):
		with self.assertRaises(frappe.ValidationError):
			self.loan(
				direction="Lent",
				loan_account=make_account(self.tracker, account_type="Other Asset").name,
				interest_category=self.interest,
			)

	def test_a_group_interest_category_is_refused(self):
		group = make_category(self.tracker, category_type="Expense", is_group=1).name
		with self.assertRaises(frappe.ValidationError):
			self.loan(interest_category=group)

	def test_an_account_from_another_tracker_is_refused(self):
		other = make_tracker().name
		with self.assertRaises(frappe.ValidationError):
			self.loan(loan_account=make_account(other, account_type="Loan").name)

	def test_two_loans_with_one_name_are_refused(self):
		first = self.loan()
		with self.assertRaises(frappe.ValidationError):
			self.loan(loan_name=first.loan_name)

	def test_a_negative_rate_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.loan(interest_rate=-2)


class TestPosting(LoanFixture):
	"""One payment, three legs, and only one of them is spending."""

	def test_loan_payment_is_no_longer_a_planned_type(self):
		self.assertIn("Loan Payment", strategies.STRATEGIES)
		self.assertNotIn("Loan Payment", strategies.PLANNED)

	def payment(self, loan, amount, interest, **kwargs):
		self.fund()
		return make_transaction(
			"Loan Payment",
			amount,
			self.bank,
			tracker=self.tracker,
			loan=loan.name,
			interest_amount=interest,
			date=posting_date(),
			**kwargs,
		)

	def test_the_principal_reduces_the_loan_and_the_interest_is_expense(self):
		loan = self.loan()
		transaction = self.payment(loan, 10000, 2000)

		entry = frappe.get_doc("Journal Entry", transaction.journal_entry)
		self.assertEqual(len(entry.accounts), 3)

		by_account = {row.account: row for row in entry.accounts}
		loan_ledger = frappe.db.get_value("Money Account", self.loan_account, "ledger_account")
		interest_ledger = frappe.db.get_value("Category", self.interest, "ledger_account")
		bank_ledger = frappe.db.get_value("Money Account", self.bank, "ledger_account")

		self.assertMoneyEqual(by_account[loan_ledger].debit, 8000)
		self.assertMoneyEqual(by_account[interest_ledger].debit, 2000)
		self.assertMoneyEqual(by_account[bank_ledger].credit, 10000)

	def test_a_lent_loan_posts_the_mirror_image(self):
		loan = self.lent_loan()
		transaction = self.payment(loan, 10000, 2000)

		entry = frappe.get_doc("Journal Entry", transaction.journal_entry)
		by_account = {row.account: row for row in entry.accounts}
		bank_ledger = frappe.db.get_value("Money Account", self.bank, "ledger_account")
		loan_ledger = frappe.db.get_value("Money Account", loan.loan_account, "ledger_account")

		self.assertMoneyEqual(by_account[bank_ledger].debit, 10000)
		self.assertMoneyEqual(by_account[loan_ledger].credit, 8000)

	def test_a_payment_that_is_all_interest_has_no_principal_leg(self):
		"""A moratorium instalment. A leg carrying nothing is not a leg."""
		loan = self.loan()
		transaction = self.payment(loan, 2000, 2000)
		self.assertEqual(len(frappe.get_doc("Journal Entry", transaction.journal_entry).accounts), 2)

	def test_a_payment_with_no_interest_is_pure_principal(self):
		loan = self.loan(interest_rate=0)
		transaction = self.payment(loan, 5000, 0)
		self.assertEqual(len(frappe.get_doc("Journal Entry", transaction.journal_entry).accounts), 2)

	def test_interest_larger_than_the_payment_is_refused(self):
		loan = self.loan()
		with self.assertRaises(frappe.ValidationError):
			self.payment(loan, 1000, 2000)

	def test_a_loan_payment_carries_no_category_of_its_own(self):
		"""It has two halves with different answers, so a category on the voucher would be a
		third."""
		loan = self.loan()
		transaction = self.payment(loan, 10000, 2000, category=self.interest)
		self.assertIsNone(transaction.category)

	def test_a_loan_payment_cannot_be_split(self):
		loan = self.loan()
		with self.assertRaises(frappe.ValidationError):
			self.payment(loan, 10000, 2000, splits=[{"category": self.interest, "amount": 10000}])

	def test_a_loan_payment_has_to_name_a_loan(self):
		self.fund()
		with self.assertRaises(frappe.ValidationError):
			make_transaction("Loan Payment", 5000, self.bank, tracker=self.tracker, date=posting_date())

	def test_a_loan_cannot_be_repaid_from_itself(self):
		loan = self.loan()
		self.assertRaises(
			frappe.ValidationError,
			make_transaction,
			"Loan Payment",
			5000,
			self.loan_account,
			tracker=self.tracker,
			loan=loan.name,
			interest_amount=0,
			date=posting_date(),
		)

	def test_a_closed_loan_takes_no_more_payments(self):
		loan = self.loan()
		frappe.db.set_value("Money Loan", loan.name, "status", "Closed")
		with self.assertRaises(frappe.ValidationError):
			self.payment(loan, 10000, 2000)

	def test_cancelling_puts_the_principal_back(self):
		loan = self.loan()
		transaction = self.payment(loan, 10000, 2000)
		self.assertMoneyEqual(loans.measure(loan).outstanding, -8000)

		transaction.cancel()
		self.assertMoneyEqual(loans.measure(loan).outstanding, 0)


class TestInterestReachesSpending(LoanFixture):
	"""The A1 lesson, applied before it could bite again.

	Interest is charged to a category on a voucher whose type is not a spending type, so every
	query that groups by `Transaction.category` or filters on `SPEND_TYPES` is blind to it. It
	posts to `GL Entry` correctly and leaves the bank balance right, so nothing looks broken —
	the money simply vanishes from the roll-up, the chart and every budget.
	"""

	def setUp(self):
		super().setUp()
		income = make_category(self.tracker, category_type="Income").name
		make_transaction(
			"Income", 500000, self.bank, tracker=self.tracker, category=income, date=posting_date()
		)
		self.paid = make_transaction(
			"Loan Payment",
			10000,
			self.bank,
			tracker=self.tracker,
			loan=self.loan().name,
			interest_amount=2000,
			date=posting_date(),
		)

	def totals(self):
		return {
			row["category"]: row["total"] for row in categories.get_category_totals(self.tracker, "Expense")
		}

	def test_the_interest_reaches_the_category_roll_up(self):
		self.assertMoneyEqual(self.totals()[self.interest], 2000)

	def test_the_principal_does_not(self):
		"""It is a balance coming down, not money spent."""
		self.assertMoneyEqual(sum(self.totals().values()), 2000)

	def test_the_interest_reaches_a_budget(self):
		by_date = categories.get_net_spend_by_date(
			self.tracker, self.interest, add_days(posting_date(), -1), add_days(posting_date(), 1)
		)
		self.assertMoneyEqual(sum(by_date.values()), 2000)

	def test_the_interest_reaches_the_spending_trend(self):
		"""And therefore "Expenses This Month". The same money reading as spending on the
		category roll-up and not on the dashboard is the contradiction §33 is about."""
		_income, expense = trends.get_totals(
			self.tracker, add_days(posting_date(), -1), add_days(posting_date(), 1)
		)
		self.assertMoneyEqual(expense, 2000)

	def test_interest_on_money_lent_is_not_spending(self):
		"""It is income. The side is a property of the charge, not of the mechanism."""
		sides = {charge.side for charge in categories.SIDE_CHARGES}
		self.assertEqual(sides, {"Expense"})


class TestMeasurement(LoanFixture):
	def test_a_loan_starting_later_has_not_started(self):
		loan = self.loan(start_date=add_months(posting_date(), 2))
		self.assertEqual(loans.measure(loan).outcome, loans.NOT_STARTED)

	def test_a_loan_whose_principal_is_not_on_the_books_says_so(self):
		"""And it is the first thing to do about it. A loan account at zero is indistinguishable
		from one that has been paid off, so neither reading would be honest."""
		self.assertEqual(loans.measure(self.loan()).outcome, loans.NOT_DISBURSED)

	def test_disbursing_puts_the_principal_on_the_books_as_a_transfer(self):
		"""Nobody is richer or poorer for having borrowed, so it touches neither income nor
		expense — which is what a Transfer already guarantees."""
		loan = self.loan(principal=100000)
		result = loan.disburse(account=self.bank)

		transaction = frappe.get_doc("Transaction", result["transaction"])
		self.assertEqual(transaction.transaction_type, "Transfer")
		self.assertMoneyEqual(loans.measure(loan).outstanding, 100000)

	def test_a_lent_loan_disburses_the_other_way(self):
		loan = self.lent_loan(principal=50000)
		self.fund()
		loan.disburse(account=self.bank)
		self.assertMoneyEqual(loans.measure(loan).outstanding, 50000)

	def test_it_cannot_be_disbursed_twice(self):
		loan = self.loan()
		loan.disburse(account=self.bank)
		self.assertRaises(frappe.ValidationError, loan.disburse, account=self.bank)

	def test_nothing_can_be_repaid_before_it_is_disbursed(self):
		loan = self.loan()
		self.fund()
		self.assertRaises(frappe.ValidationError, loan.post_instalment, from_account=self.bank)

	def test_a_fresh_disbursed_loan_is_on_schedule(self):
		self.assertEqual(loans.measure(self.disbursed()).outcome, loans.ON_SCHEDULE)

	def test_an_instalment_gone_by_unpaid_is_arrears(self):
		loan = self.disbursed(start_date=add_months(posting_date(), -3))
		measured = loans.measure(loan)
		self.assertEqual(measured.outcome, loans.IN_ARREARS)
		self.assertEqual(measured.arrears_count, 3)

	def test_an_instalment_coming_up_is_due(self):
		loan = self.disbursed(start_date=add_days(posting_date(), -28), reminder_days_before=5)
		self.assertEqual(loans.measure(loan).outcome, loans.DUE)

	def test_the_users_own_decision_wins_over_the_schedule(self):
		loan = self.disbursed(start_date=add_months(posting_date(), -3))
		frappe.db.set_value("Money Loan", loan.name, "status", "Closed")
		loan.reload()
		self.assertEqual(loans.measure(loan).outcome, loans.CLOSED)

	def test_two_payments_in_one_afternoon_clear_two_months_of_arrears(self):
		"""A schedule is not a set of individual claims the way bills are, so arrears are
		counted rather than matched date for date."""
		loan = self.disbursed(start_date=add_months(posting_date(), -2))
		self.fund()
		loan.post_instalment(from_account=self.bank)
		loan.post_instalment(from_account=self.bank)

		self.assertEqual(loans.measure(loan).outcome, loans.ON_SCHEDULE)

	def test_the_outstanding_figure_comes_from_the_ledger(self):
		"""Not from the schedule. They differ the moment somebody pays early or pays a lump sum,
		and the ledger is right every time."""
		loan = self.disbursed(principal=100000)
		self.fund()
		# A lump sum straight off the principal, which no schedule predicted.
		make_transaction(
			"Transfer",
			30000,
			self.bank,
			tracker=self.tracker,
			destination_account=self.loan_account,
			date=posting_date(),
		)
		self.assertMoneyEqual(loans.measure(loan).outstanding, 70000)

	def test_percent_repaid_counts_principal_and_not_payments(self):
		loan = self.disbursed()
		self.fund()
		loan.post_instalment(from_account=self.bank)

		measured = loans.measure(loan)
		self.assertMoneyEqual(measured.interest_paid, 1000)
		self.assertMoneyEqual(measured.principal_paid, 7884.88)


class TestActions(LoanFixture):
	def test_post_instalment_takes_the_interest_off_the_schedule(self):
		"""The agreement says what this month's interest is; paying a round number does not
		change it."""
		loan = self.disbursed(principal=100000, interest_rate=12, tenure_months=12)
		self.fund()
		result = loan.post_instalment(from_account=self.bank)

		self.assertEqual(result["instalment"], 1)
		self.assertMoneyEqual(result["interest"], 1000)
		self.assertMoneyEqual(result["principal"], 7884.88)

	def test_paying_more_than_the_instalment_goes_to_principal(self):
		"""Which is exactly what a part-prepayment is."""
		loan = self.disbursed()
		self.fund()
		result = loan.post_instalment(from_account=self.bank, amount=20000)

		self.assertMoneyEqual(result["interest"], 1000)
		self.assertMoneyEqual(result["principal"], 19000)

	def test_each_call_settles_the_next_instalment(self):
		loan = self.disbursed()
		self.fund()
		self.assertEqual(loan.post_instalment(from_account=self.bank)["instalment"], 1)
		self.assertEqual(loan.post_instalment(from_account=self.bank)["instalment"], 2)

	def test_it_refuses_once_the_schedule_is_exhausted(self):
		loan = self.disbursed(tenure_months=1)
		self.fund()
		loan.post_instalment(from_account=self.bank)
		self.assertRaises(frappe.ValidationError, loan.post_instalment, from_account=self.bank)

	def test_closing_is_refused_while_the_ledger_says_money_is_owed(self):
		"""A loan reading closed over a live balance would understate every debt figure in the
		app, and nothing would say why."""
		loan = self.disbursed()
		self.assertRaises(frappe.ValidationError, loan.close)

	def test_a_settled_loan_closes(self):
		loan = self.loan()
		loan.close()
		self.assertEqual(loan.status, "Closed")

	def test_deleting_a_loan_keeps_its_payments(self):
		loan = self.disbursed()
		self.fund()
		transaction = loan.post_instalment(from_account=self.bank)["transaction"]

		frappe.delete_doc("Money Loan", loan.name, force=True)
		self.assertTrue(frappe.db.exists("Transaction", transaction))
		self.assertIsNone(frappe.db.get_value("Transaction", transaction, "loan"))


class TestWidgets(LoanFixture):
	def test_the_debt_card_totals_what_is_owed(self):
		loan = self.disbursed(principal=100000)
		self.assertIn("1,00,000", loans_api.card_debt_outstanding({"tracker": self.tracker}))
		self.assertMoneyEqual(loans.measure(loan).outstanding, 100000)

	def test_money_lent_is_not_added_to_money_owed(self):
		"""Opposite facts. Adding them gives a figure that answers no question."""
		self.lent_loan()
		debt = loans.get_debt_outstanding(self.tracker)
		self.assertEqual(debt.loans, 0)

	def test_the_arrears_card_counts_loans_rather_than_instalments(self):
		"""A loan three months behind is one conversation with one lender."""
		self.disbursed(start_date=add_months(posting_date(), -3))
		self.assertEqual(loans_api.card_loans_in_arrears({"tracker": self.tracker}), "1 behind")

	def test_the_arrears_card_says_so_when_there_are_none(self):
		self.disbursed()
		self.assertEqual(loans_api.card_loans_in_arrears({"tracker": self.tracker}), "All on schedule")

	def test_the_schedule_api_marks_paid_instalments(self):
		loan = self.disbursed()
		self.fund()
		loan.post_instalment(from_account=self.bank)

		payload = loans_api.get_schedule(loan.name)
		self.assertEqual(payload["paid_count"], 1)
		self.assertTrue(payload["schedule"][0]["paid"])
		self.assertFalse(payload["schedule"][1]["paid"])


class TestFormWiring(MoneyTrackerTestCase):
	"""The form script and the DocType JSON restate things Python knows."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		folder = Path(frappe.get_app_path("moneytracker")) / "money_tracker/doctype/money_loan"
		cls.form_js = (folder / "money_loan.js").read_text()
		cls.doctype_json = json.loads((folder / "money_loan.json").read_text())

	def field(self, fieldname):
		return next(row for row in self.doctype_json["fields"] if row["fieldname"] == fieldname)

	def test_the_form_colours_every_outcome(self):
		block = self.form_js.split("const OUTCOME_COLOR = {")[1].split("};")[0]
		for outcome in (
			loans.ON_SCHEDULE,
			loans.NOT_STARTED,
			loans.NOT_DISBURSED,
			loans.DUE,
			loans.IN_ARREARS,
			loans.CLOSED,
		):
			self.assertIn(outcome.replace(" ", ""), block.replace('"', "").replace(" ", ""))

	def test_the_direction_select_matches_the_service(self):
		self.assertEqual(tuple(self.field("direction")["options"].split("\n")), loans.DIRECTIONS)

	def test_the_interest_type_select_matches_the_service(self):
		self.assertEqual(tuple(self.field("interest_type")["options"].split("\n")), loans.INTEREST_TYPES)

	def test_the_status_select_holds_only_the_users_own_decisions(self):
		self.assertEqual(self.field("status")["options"].split("\n"), ["Active", "Closed"])

	def test_the_form_knows_which_account_types_are_liabilities(self):
		from moneytracker.money_tracker.services.coa import ACCOUNT_TYPE_MAP

		listed = self.form_js.split("const LIABILITY_ACCOUNT_TYPES = [")[1].split("]")[0]
		liabilities = {name for name, spec in ACCOUNT_TYPE_MAP.items() if spec[0] == "Liability"}
		for account_type in liabilities:
			self.assertIn(f'"{account_type}"', listed)

	def test_the_form_calls_methods_that_exist(self):
		self.assertIn("moneytracker.money_tracker.api.loans.get_loan_progress", self.form_js)
		self.assertTrue(callable(loans_api.get_loan_progress))

	def test_the_schedule_table_is_read_only(self):
		"""It is arithmetic, rebuilt on every save. An editable copy would be a second opinion."""
		self.assertTrue(self.field("schedule")["read_only"])

	def test_it_rounds_to_the_ledgers_own_precision(self):
		self.assertEqual(loans.PRECISION, 2)
