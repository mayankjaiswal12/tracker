# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Salary of 100,000 received into HDFC:

	Dr HDFC Bank      100,000
	    Cr Salary Income   100,000
	"""
	category = ctx.require_category("Income")

	return [
		Leg(ledger_account=ctx.account.ledger_account, debit=ctx.amount, money_account=ctx.account.name),
		Leg(ledger_account=category.ledger_account, credit=ctx.amount),
	]
