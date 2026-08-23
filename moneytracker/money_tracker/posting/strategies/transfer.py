# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.posting.leg import Leg


def build_legs(ctx):
	"""Transfer of 10,000 from HDFC to SBI:

	Dr SBI Bank    10,000
	    Cr HDFC Bank   10,000

	Both legs are balance-sheet accounts, so **the movement** touches neither income nor expense
	and cannot show up in either report (spec §10). Moving your own money between pockets is the
	classic way a naive tracker double-counts spending.

	A fee is the one thing that does cross into expense, and deliberately. Transferring 10,000
	with a 50 charge:

	Dr SBI Bank        10,000
	Dr Bank Charges        50
	    Cr HDFC Bank       10,050

	The destination receives what was sent; the source loses that plus the charge. The fee is
	spending by any honest reading — the bank kept it — and booking it anywhere else would
	understate expenses while leaving both balances right, which is the hardest kind of wrong
	to notice. So the invariant is about the *movement*, not about the voucher.
	"""
	destination = ctx.require_destination()
	fee = ctx.fee_leg()

	legs = [
		Leg(
			ledger_account=destination.ledger_account,
			debit=ctx.amount,
			money_account=destination.name,
		)
	]
	if fee:
		legs.append(fee)
	legs.append(
		Leg(
			ledger_account=ctx.account.ledger_account,
			credit=ctx.amount + ctx.fee_amount,
			money_account=ctx.account.name,
		)
	)
	return legs
