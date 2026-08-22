# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Salary of 100,000 received into HDFC:

	Dr HDFC Bank      100,000
	    Cr Salary Income   100,000

	A split receipt — one payment covering salary and a reimbursement — credits each category
	separately against the single debit to the account the money landed in.
	"""
	legs = [Leg(ledger_account=ctx.account.ledger_account, debit=ctx.amount, money_account=ctx.account.name)]

	if ctx.splits:
		legs.extend(
			Leg(ledger_account=split.category.ledger_account, credit=split.amount)
			for split in ctx.require_splits("Income")
		)
	else:
		legs.append(Leg(ledger_account=ctx.require_category("Income").ledger_account, credit=ctx.amount))

	return legs
