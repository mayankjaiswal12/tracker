# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Posting strategies: one per transaction type.

A strategy answers a single question — "which accounts are debited and credited, and by
how much?" — and returns a list of Leg objects. It never touches the database, which is
what makes the accounting rules readable and directly unit-testable.

Adding a transaction type means adding a strategy and registering it here. The engine
never changes.
"""

import frappe
from frappe import _

from moneytracker.money_tracker.posting.strategies import (
	credit_card_payment,
	expense,
	income,
	loan_payment,
	refund,
	transfer,
)

STRATEGIES = {
	"Expense": expense.build_legs,
	"Income": income.build_legs,
	"Transfer": transfer.build_legs,
	"Credit Card Payment": credit_card_payment.build_legs,
	"Refund": refund.build_legs,
	"Loan Payment": loan_payment.build_legs,
}

# Declared in the Transaction DocType and designed for, but not yet implemented.
# Listed explicitly so an attempt fails with a clear message instead of a KeyError.
PLANNED = (
	"Reimbursement",
	"Adjustment",
	"Investment Purchase",
	"Investment Sale",
	"Dividend",
	"Interest",
	"Asset Purchase",
	"Asset Sale",
)


def get_strategy(transaction_type):
	strategy = STRATEGIES.get(transaction_type)
	if strategy:
		return strategy

	if transaction_type in PLANNED:
		frappe.throw(
			_("Transaction Type {0} is not implemented yet. Supported types: {1}.").format(
				transaction_type, ", ".join(sorted(STRATEGIES))
			)
		)

	frappe.throw(_("Unknown Transaction Type: {0}").format(transaction_type))
