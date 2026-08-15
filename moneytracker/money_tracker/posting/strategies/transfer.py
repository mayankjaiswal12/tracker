# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Transfer of 10,000 from HDFC to SBI:

	Dr SBI Bank    10,000
	    Cr HDFC Bank   10,000

	Both legs are balance-sheet accounts, so a transfer touches neither income nor expense
	and cannot show up in either report (spec §10).
	"""
	destination = ctx.require_destination()

	return [
		Leg(
			ledger_account=destination.ledger_account,
			debit=ctx.amount,
			money_account=destination.name,
		),
		Leg(ledger_account=ctx.account.ledger_account, credit=ctx.amount, money_account=ctx.account.name),
	]
