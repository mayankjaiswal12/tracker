# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""A 300 refund against an earlier 1,000 purchase:

	Dr HDFC Bank        300
	    Cr Food Expense     300

	Crediting the original expense category is what makes net spend on Food read 700. A
	refund is emphatically not income — booking it as income would overstate both income
	and expense for the period (spec §62).
	"""
	category = ctx.require_category("Expense")

	return [
		Leg(ledger_account=ctx.account.ledger_account, debit=ctx.amount, money_account=ctx.account.name),
		Leg(ledger_account=category.ledger_account, credit=ctx.amount),
	]
