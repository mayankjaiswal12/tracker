# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Restaurant bill of 1,000 paid from HDFC:

	Dr Food Expense   1,000
	    Cr HDFC Bank      1,000

	Paying by credit card credits the card's liability account instead, which is what makes
	the card balance grow rather than a bank balance shrink.

	A split bill — 800 of groceries and 200 of household goods on one card swipe — is the same
	shape with more debits:

	Dr Groceries        800
	Dr Household        200
	    Cr HDFC Bank        1,000

	One credit either way, because one payment left the account. **The engine does not know
	this happened**: it validates that debits equal credits and writes what it is given, which
	is the whole bargain `posting/strategies/` was built for.
	"""
	if ctx.splits:
		legs = [
			Leg(ledger_account=split.category.ledger_account, debit=split.amount)
			for split in ctx.require_splits("Expense")
		]
	else:
		legs = [Leg(ledger_account=ctx.require_category("Expense").ledger_account, debit=ctx.amount)]

	legs.append(
		Leg(ledger_account=ctx.account.ledger_account, credit=ctx.amount, money_account=ctx.account.name)
	)
	return legs
