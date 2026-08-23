# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.posting.leg import Leg
from moneytracker.money_tracker.services import loans


def build_legs(ctx):
	"""An instalment of 10,000 on a borrowed loan, of which 2,000 is interest:

	Dr Car Loan            8,000     (what you owe comes down)
	Dr Interest Paid       2,000     (the price of the money, and it is gone)
	    Cr HDFC Bank          10,000

	**One payment, two different facts**, and that is the whole reason this strategy exists and
	the reason a Debt Payoff goal cannot stand in for a loan. The principal is a balance-sheet
	movement — the household is no poorer for having paid it, it simply owes less. The interest
	is expense, and it is the only part of the instalment that makes anybody worse off. Booking
	the whole 10,000 as spending would overstate expense by the principal every month; booking
	none of it would hide the entire cost of borrowing.

	A loan **lent** rather than borrowed is the same entry mirrored, with the interest on the
	income side:

	Dr HDFC Bank          10,000
	    Cr Loan to Ravi       8,000
	    Cr Interest Earned    2,000

	Which is why `direction` is a field and not a note: two sets of signs, one rule, and the
	loan's own controller has already checked that the account and the category sit on the sides
	the direction implies. Both readings balance, so nothing downstream would catch it here.
	"""
	loan = ctx.require_loan()
	interest = flt(ctx.interest_amount)
	principal = flt(ctx.amount - interest)

	if principal < 0:
		frappe.throw(_("Interest of {0} is more than the payment of {1}.").format(interest, ctx.amount))

	loan_account = ctx.loan_account
	if not loan_account.ledger_account:
		frappe.throw(_("Account {0} has no ledger account.").format(loan_account.account_name))

	interest_category = ctx.interest_category if interest else None
	if interest and not interest_category:
		frappe.throw(_("Interest needs a category. Set one on the loan."))
	if interest_category and not interest_category.ledger_account:
		frappe.throw(_("Category {0} has no ledger account.").format(interest_category.category_name))

	# A payment that is all interest is legitimate — a moratorium instalment, or the first
	# payment on a loan whose principal repayment has not started. It simply has no principal
	# leg, since a leg carrying nothing is not a leg.
	if loan.direction == loans.LENT:
		legs = [
			Leg(
				ledger_account=ctx.account.ledger_account,
				debit=ctx.amount,
				money_account=ctx.account.name,
			)
		]
		if principal:
			legs.append(
				Leg(
					ledger_account=loan_account.ledger_account,
					credit=principal,
					money_account=loan_account.name,
				)
			)
		if interest:
			legs.append(Leg(ledger_account=interest_category.ledger_account, credit=interest))
		return legs

	legs = []
	if principal:
		legs.append(
			Leg(
				ledger_account=loan_account.ledger_account,
				debit=principal,
				money_account=loan_account.name,
			)
		)
	if interest:
		legs.append(Leg(ledger_account=interest_category.ledger_account, debit=interest))
	legs.append(
		Leg(
			ledger_account=ctx.account.ledger_account,
			credit=ctx.amount,
			money_account=ctx.account.name,
		)
	)
	return legs
