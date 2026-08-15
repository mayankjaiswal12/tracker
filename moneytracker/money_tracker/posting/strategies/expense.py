# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Restaurant bill of 1,000 paid from HDFC:

	Dr Food Expense   1,000
	    Cr HDFC Bank      1,000

	Paying by credit card credits the card's liability account instead, which is what makes
	the card balance grow rather than a bank balance shrink.
	"""
	category = ctx.require_category("Expense")

	return [
		Leg(ledger_account=category.ledger_account, debit=ctx.amount),
		Leg(ledger_account=ctx.account.ledger_account, credit=ctx.amount, money_account=ctx.account.name),
	]
