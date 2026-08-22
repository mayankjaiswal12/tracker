# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from moneytracker.money_tracker.posting.leg import Leg
from moneytracker.money_tracker.services import coa


def build_legs(ctx):
	"""Paying 1,000 off the HDFC credit card from the HDFC bank account:

	Dr HDFC Credit Card   1,000     (liability goes down)
	    Cr HDFC Bank          1,000

	This is a settlement between two balance-sheet accounts, never an expense — the expense
	was already recorded when the card was used (spec §27, §83).

	`account` is the account money leaves; `destination_account` is the card being paid.
	"""
	card = ctx.require_destination()

	if not coa.is_liability(card.account_type):
		frappe.throw(
			_(
				"Destination Account {0} is a {1}, not a liability. A card payment must settle a liability."
			).format(card.account_name, card.account_type)
		)
	if coa.is_liability(ctx.account.account_type):
		frappe.throw(
			_("Paying a {0} from another liability account is not supported.").format(card.account_type)
		)

	fee = ctx.fee_leg()

	legs = [Leg(ledger_account=card.ledger_account, debit=ctx.amount, money_account=card.name)]
	if fee:
		# A convenience charge for paying the card. The card is settled by `amount`; the
		# charge is expense, for the same reason a transfer fee is.
		legs.append(fee)
	legs.append(
		Leg(
			ledger_account=ctx.account.ledger_account,
			credit=ctx.amount + ctx.fee_amount,
			money_account=ctx.account.name,
		)
	)
	return legs
