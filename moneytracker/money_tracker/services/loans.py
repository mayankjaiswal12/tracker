# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Loans: amortisation, which is the one thing a Debt Payoff goal cannot do.

**Where this stops.** A `Money Goal` of type Debt Payoff already answers "am I clearing this
card?" — a target, a window, and a balance measured from the ledger. It has no opinion about
*why* the balance falls, and for a card that is right: you pay what you can. A loan is the
other case. The payments are fixed in advance, and every one of them is two different things at
once — principal, which reduces what you owe, and interest, which is the price of the money and
is gone. A goal cannot say that, and it should not try: the simple case keeps the simple tool.

**Three boundaries, and they are the whole design.**

1. **The ledger owns the money.** What is still owed is the balance of a `Money Account` — type
   `Loan` for something borrowed, an asset for something lent — measured on read like every
   other balance in this app. This module stores no outstanding figure.
2. **The loan owns the contract.** Principal, rate, tenure, the EMI and the schedule those
   imply. A schedule *is* recomputable from the terms, so storing it looks like a violation of
   "derive, never store" — and would be, except for the rule in the controller that makes it
   safe: **once a payment has been posted against a loan, its terms are frozen.** A stored
   schedule cannot drift from terms that cannot change, and what is stored is then the thing a
   lender actually gave you, rather than a guess this app recomputes differently next year.
3. **The strategy owns the entry.** `posting/strategies/loan_payment.py` turns one payment into
   three legs. Nothing here posts anything.

Everything below `build_schedule` is arithmetic and touches no database, which is what makes an
amortisation table something you can read and check by hand.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import balances, recurring

# Derived outcomes. Never stored — worked out from the schedule and the ledger on every read.
NOT_STARTED = "Not Started"
NOT_DISBURSED = "Not Disbursed"
ON_SCHEDULE = "On Schedule"
DUE = "Due"
IN_ARREARS = "In Arrears"
CLOSED = "Closed"

# What "nothing to do about it today" means. `Due` is not in it — an instalment inside the
# reminder window is the whole reason somebody looks at a loan — and neither is `In Arrears`.
HEALTHY_OUTCOMES = (ON_SCHEDULE, NOT_STARTED, CLOSED)

# Which way the money went. `Borrowed` is money you owe and its interest is expense; `Lent` is
# money owed to you and its interest is income. Two words, and every sign below follows from
# them, which is why there is one strategy rather than two.
BORROWED = "Borrowed"
LENT = "Lent"
DIRECTIONS = (BORROWED, LENT)

# How the interest is worked out.
#
# `Reducing Balance` charges interest on what is still outstanding, so the interest in each
# instalment falls as the principal does. This is what a bank means by a home or car loan.
#
# `Flat` charges interest on the *original* principal for the whole tenure, so every
# instalment carries the same interest whatever has been repaid. It is what an informal or
# dealer loan usually means, and it is always dearer than the same nominal rate reducing.
REDUCING_BALANCE = "Reducing Balance"
FLAT = "Flat"
INTEREST_TYPES = (REDUCING_BALANCE, FLAT)

# An instalment a month, and that is stated rather than assumed. Amortisation needs a rate per
# period, so a fortnightly loan is not a new field but a new number here plus the matching
# `recurring.FREQUENCIES` row in `nth_date` below. Nothing else in the module would change.
INSTALMENT_FREQUENCY = "Monthly"
PERIODS_PER_YEAR = 12

# Bounds. A tenure of one instalment is legitimate (a single bullet repayment); the upper bound
# is forty years of months, far past any real loan, and stops a mistyped tenure from building a
# ten-thousand-row child table.
MAX_TENURE = 480

# Money is compared and stored at two decimals throughout, the same precision the ledger uses.
PRECISION = 2


@dataclass(frozen=True)
class Instalment:
	"""One row of an amortisation table.

	`payment` is what leaves the account; `principal` and `interest` are what it consists of,
	and they always add up to it. `closing_balance` is what is still owed afterwards, and the
	last row's is exactly zero — see `build_schedule`.
	"""

	instalment: int
	due_date: object
	opening_balance: float
	payment: float
	principal: float
	interest: float
	closing_balance: float

	def as_row(self):
		return {
			"instalment": self.instalment,
			"due_date": self.due_date,
			"opening_balance": self.opening_balance,
			"payment": self.payment,
			"principal": self.principal,
			"interest": self.interest,
			"closing_balance": self.closing_balance,
		}


# --- the arithmetic --------------------------------------------------------------------


def rate_per_period(annual_rate):
	"""The annual nominal rate as a fraction per instalment. Zero is allowed and means zero.

	An interest-free loan from a relative is a real loan with a real schedule, and it is the
	case that divides by zero in every EMI formula — so it is handled here once rather than
	guarded at each caller.
	"""
	return flt(annual_rate) / 100.0 / PERIODS_PER_YEAR


def emi_for(principal, annual_rate, tenure_months, interest_type=REDUCING_BALANCE):
	"""The level instalment those terms imply.

	Reducing balance is the standard annuity: P·r·(1+r)^n / ((1+r)^n - 1). Flat interest is not
	an annuity at all — the interest is fixed against the original principal for the whole
	tenure — so it is simply everything owed divided by the number of instalments.
	"""
	principal = flt(principal)
	periods = int(tenure_months)
	if principal <= 0 or periods <= 0:
		return 0.0

	if interest_type == FLAT:
		return flt((principal + total_interest_flat(principal, annual_rate, periods)) / periods, PRECISION)

	rate = rate_per_period(annual_rate)
	if not rate:
		return flt(principal / periods, PRECISION)

	growth = (1 + rate) ** periods
	return flt(principal * rate * growth / (growth - 1), PRECISION)


def total_interest_flat(principal, annual_rate, tenure_months):
	"""Interest on the original principal for the whole tenure — the flat-rate definition."""
	years = int(tenure_months) / PERIODS_PER_YEAR
	return flt(flt(principal) * flt(annual_rate) / 100.0 * years, PRECISION)


def nth_due_date(start_date, n):
	"""The nth instalment's date, counted from the disbursal date.

	`recurring.nth_date` does the arithmetic, which buys the month-end rule already argued for
	there: a loan disbursed on 31 January falls due on 28 February and then on **31** March,
	because every instalment is counted from the start rather than stepped off the last one. A
	loan is exactly the case where stepping would be worst — thirty years of it would drift the
	due date to the 28th permanently after one February.
	"""
	return recurring.nth_date(start_date, INSTALMENT_FREQUENCY, n)


def build_schedule(
	principal, annual_rate, tenure_months, start_date, interest_type=REDUCING_BALANCE, emi=None
):
	"""The whole amortisation table, as `Instalment` rows. Pure: no database, no document.

	    **The last instalment absorbs the rounding**, and that is the only interesting line in this
	    function. A level EMI rounded to paise cannot clear the principal exactly, so a schedule
	    built by repeating it either leaves a few paise owing forever or overpays by a few. Real
	    lenders settle the difference in the final instalment, so that is what this does: the last
	    row's principal is whatever is still outstanding, and its `closing_balance` is exactly zero.

	    `emi` may be supplied when the lender's own figure differs from the formula's — their
	    rounding is not ours, and the paper they sent is the truth. An EMI too small to cover the
	    first period's interest is refused rather than amortised, because such a schedule never
	    ends: the balance grows every month and the table would run to `MAX_TENURE` and stop
	mid-loan.
	"""
	principal = flt(principal)
	periods = int(tenure_months)
	if principal <= 0:
		frappe.throw(_("A loan needs a principal greater than zero."))
	if periods <= 0 or periods > MAX_TENURE:
		frappe.throw(_("Tenure must be between 1 and {0} instalments.").format(MAX_TENURE))
	if interest_type not in INTEREST_TYPES:
		frappe.throw(
			_("{0} is not an interest type. Supported: {1}.").format(interest_type, ", ".join(INTEREST_TYPES))
		)

	payment = flt(emi) if flt(emi) else emi_for(principal, annual_rate, periods, interest_type)
	rate = rate_per_period(annual_rate)
	flat_interest = (
		flt(total_interest_flat(principal, annual_rate, periods) / periods, PRECISION)
		if interest_type == FLAT
		else None
	)

	first_interest = flat_interest if flat_interest is not None else flt(principal * rate, PRECISION)
	if payment <= first_interest and periods > 1:
		frappe.throw(
			_(
				"An instalment of {0} does not even cover the first period's interest of {1}, so the loan would never be repaid."
			).format(payment, first_interest)
		)

	rows = []
	outstanding = principal
	for number in range(1, periods + 1):
		interest = flat_interest if flat_interest is not None else flt(outstanding * rate, PRECISION)
		last = number == periods

		if last:
			# Whatever is left, so the table closes at zero rather than at a rounding residue.
			principal_part = flt(outstanding, PRECISION)
			instalment_payment = flt(principal_part + interest, PRECISION)
		else:
			principal_part = flt(payment - interest, PRECISION)
			instalment_payment = flt(payment, PRECISION)

		closing = flt(outstanding - principal_part, PRECISION)
		rows.append(
			Instalment(
				instalment=number,
				due_date=nth_due_date(start_date, number),
				opening_balance=flt(outstanding, PRECISION),
				payment=instalment_payment,
				principal=principal_part,
				interest=flt(interest, PRECISION),
				closing_balance=closing,
			)
		)
		outstanding = closing

	return rows


def schedule_totals(rows):
	"""What the table adds up to: paid, principal, interest.

	Principal must come back exactly as the loan's own, which is the property the last-row rule
	above exists to guarantee, and the cheapest possible check that it worked.
	"""
	return frappe._dict(
		{
			"instalments": len(rows),
			"payment": flt(sum(row.payment for row in rows), PRECISION),
			"principal": flt(sum(row.principal for row in rows), PRECISION),
			"interest": flt(sum(row.interest for row in rows), PRECISION),
		}
	)


# --- measurement -----------------------------------------------------------------------


def schedule_rows(loan):
	"""The loan's stored schedule as `Instalment` rows, oldest first."""
	rows = [
		Instalment(
			instalment=int(row.instalment),
			due_date=getdate(row.due_date),
			opening_balance=flt(row.opening_balance),
			payment=flt(row.payment),
			principal=flt(row.principal),
			interest=flt(row.interest),
			closing_balance=flt(row.closing_balance),
		)
		for row in (loan.get("schedule") or [])
		if row.due_date
	]
	rows.sort(key=lambda row: row.instalment)
	return rows


def payments(loan_name):
	"""Every submitted payment posted against this loan, oldest first.

	The loan's whole memory of what has happened, and it is a query rather than a counter — the
	same choice `recurring` made and for the same reason. Cancel a payment and the count is
	right again with nothing to correct.
	"""
	return frappe.get_all(
		"Transaction",
		filters={"loan": loan_name, "docstatus": 1},
		fields=["name", "date", "amount", "interest_amount"],
		order_by="date asc, creation asc",
	)


def outstanding(loan):
	"""What is still owed, from the ledger — never from the schedule.

	A schedule says what *should* have happened. The account says what did. They differ the
	moment somebody pays early, pays late, or pays a lump sum off the principal, and the ledger
	is right every time.
	"""
	if not loan.loan_account:
		return 0.0
	return flt(balances.get_account_balance(loan.loan_account), PRECISION)


def measure(loan, as_of=None):
	"""Every derived figure for one loan, as a `frappe._dict`."""
	loan = loan if hasattr(loan, "doctype") else frappe.get_doc("Money Loan", loan)
	as_of = getdate(as_of or today())

	rows = schedule_rows(loan)
	totals = schedule_totals(rows)
	posted = payments(loan.name)
	paid = flt(sum(flt(row.amount) for row in posted), PRECISION)
	interest_paid = flt(sum(flt(row.interest_amount) for row in posted), PRECISION)

	# Instalments whose date has passed. Compared against how many payments have been posted
	# rather than matched date for date: a household that paid March and April in one go on the
	# 20th is not in arrears, and a schedule is not a set of individual claims the way bills are.
	elapsed = [row for row in rows if row.due_date <= as_of]
	upcoming = [row for row in rows if row.due_date > as_of]
	arrears_count = max(len(elapsed) - len(posted), 0)

	result = frappe._dict(
		{
			"loan": loan.name,
			"loan_name": loan.loan_name,
			"tracker": loan.tracker,
			"status": loan.status,
			"direction": loan.direction,
			"counterparty": loan.counterparty,
			"currency": loan.currency,
			"loan_account": loan.loan_account,
			"interest_category": loan.interest_category,
			"interest_type": loan.interest_type,
			"interest_rate": flt(loan.interest_rate),
			"principal": flt(loan.principal),
			"emi": flt(loan.emi),
			"tenure_months": int(loan.tenure_months or 0),
			"start_date": getdate(loan.start_date),
			"as_of": as_of,
			"instalments": totals.instalments,
			"total_payable": totals.payment,
			"total_interest": totals.interest,
			"outstanding": outstanding(loan),
			"paid_count": len(posted),
			"paid_total": paid,
			"interest_paid": interest_paid,
			"principal_paid": flt(paid - interest_paid, PRECISION),
			"elapsed_count": len(elapsed),
			"arrears_count": arrears_count,
			"arrears_amount": flt(sum(row.payment for row in elapsed[len(posted) :]), PRECISION),
			"disbursed": bool(loan.disbursal_transaction),
			"disbursal_transaction": loan.disbursal_transaction,
			"next_due": upcoming[0].as_row() if upcoming else None,
			"last_payment": posted[-1] if posted else None,
			"final_due_date": rows[-1].due_date if rows else None,
		}
	)

	result.percent_repaid = (
		flt(result.principal_paid / flt(loan.principal) * 100, 1) if flt(loan.principal) else 0.0
	)
	result.outcome = _outcome(result, loan)
	return result


def _outcome(row, loan):
	"""The single word for where a loan stands.

	The user's own decision wins first, the rule every module in this app follows: a loan they
	marked Closed is closed, and telling them it is in arrears would report their own decision
	back to them as a fault. A loan the *ledger* says is clear is closed too — paying one off
	early is a good thing and should not need a second click to be believed.
	"""
	if loan.status == "Closed":
		return CLOSED
	if row.start_date > row.as_of:
		return NOT_STARTED
	# Until the principal is on the books there is no debt to be on schedule with, and the
	# ledger figure is not a debt figure at all: a loan account at zero looks exactly like one
	# that has been paid off. Saying so is better than reading it as either — and it is the one
	# thing the user has to do next, which is what an outcome word is for.
	if not row.disbursed:
		return NOT_DISBURSED
	if row.instalments and row.outstanding <= 0 and row.paid_count:
		return CLOSED
	if row.arrears_count:
		return IN_ARREARS
	if row.next_due and (row.next_due["due_date"] - row.as_of).days <= int(loan.reminder_days_before or 0):
		return DUE
	return ON_SCHEDULE


def measure_loans(tracker, as_of=None, status=None, direction=None):
	"""Every loan on a tracker, largest outstanding first."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status
	if direction:
		filters["direction"] = direction

	names = frappe.get_all("Money Loan", filters=filters, order_by="loan_name asc", pluck="name")
	measured = [measure(name, as_of) for name in names]
	measured.sort(key=lambda row: row.outstanding, reverse=True)
	return measured


def get_debt_outstanding(tracker, as_of=None):
	"""What the household still owes across every borrowed loan.

	**Borrowed only.** Money lent out is an asset, and adding it to money owed would net two
	opposite facts into a figure that answers no question — the same reason `Total Balance`
	refuses to add credit-card debt to cash.
	"""
	measured = [row for row in measure_loans(tracker, as_of, direction=BORROWED) if row.outcome != CLOSED]
	return frappe._dict(
		{
			"tracker": tracker,
			"as_of": getdate(as_of or today()),
			"outstanding": flt(sum(row.outstanding for row in measured), PRECISION),
			"loans": len(measured),
			"monthly_commitment": flt(sum(row.emi for row in measured), PRECISION),
			"in_arrears": sum(1 for row in measured if row.outcome == IN_ARREARS),
		}
	)


def next_instalment(loan, as_of=None):
	"""The instalment a payment would settle next: the earliest one not yet paid for.

	Read off the count rather than off the dates, which is what lets somebody catch up two
	months in one afternoon and have the second payment carry the second month's interest.
	"""
	loan = loan if hasattr(loan, "doctype") else frappe.get_doc("Money Loan", loan)
	rows = schedule_rows(loan)
	paid = len(payments(loan.name))
	if paid >= len(rows):
		return None
	return rows[paid]
