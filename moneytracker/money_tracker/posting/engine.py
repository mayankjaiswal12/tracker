# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The posting kernel.

Turns a Transaction into a balanced, submitted ERPNext Journal Entry. This is the only
code in the app that writes to the ledger. Strategies decide *what* the entry looks like;
this module decides *how* it is written, validated and reversed.
"""

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.posting import strategies
from moneytracker.money_tracker.posting.context import PostingContext
from moneytracker.money_tracker.services import balances, coa, settings as settings_service

# ERPNext voucher types are a fixed Select. Map our richer set onto the closest stock
# value and let Transaction.transaction_type carry the real semantics.
VOUCHER_TYPE_MAP = {
	"Expense": "Journal Entry",
	"Income": "Journal Entry",
	"Transfer": "Contra Entry",
	"Credit Card Payment": "Credit Card Entry",
	"Refund": "Journal Entry",
}


def _rounding_precision():
	return frappe.get_precision("Journal Entry Account", "debit") or 2


def validate_balanced(legs):
	"""Assert sum(debits) == sum(credits) before anything is written (spec §49, §76).

	ERPNext revalidates this on submit; we check first so the error names the transaction
	rather than surfacing as a Journal Entry error the user cannot connect to anything.
	"""
	precision = _rounding_precision()
	total_debit = flt(sum(leg.debit for leg in legs), precision)
	total_credit = flt(sum(leg.credit for leg in legs), precision)

	if flt(total_debit - total_credit, precision) != 0:
		frappe.throw(
			_("Journal entry is unbalanced: debits {0} do not equal credits {1}.").format(
				total_debit, total_credit
			)
		)
	if not total_debit:
		frappe.throw(_("Journal entry has no amount to post."))

	return total_debit


def build_legs(transaction):
	strategy = strategies.get_strategy(transaction.transaction_type)
	legs = strategy(PostingContext(transaction))
	validate_balanced(legs)
	return legs


def post(transaction):
	"""Create and submit the Journal Entry for a Transaction. Idempotent."""
	if transaction.journal_entry:
		return transaction.journal_entry

	legs = build_legs(transaction)
	company = settings_service.get_company()
	cost_center = settings_service.get_default_cost_center()

	journal_entry = frappe.new_doc("Journal Entry")
	journal_entry.update(
		{
			"voucher_type": VOUCHER_TYPE_MAP.get(transaction.transaction_type, "Journal Entry"),
			"company": company,
			"posting_date": transaction.date,
			"user_remark": _build_remark(transaction),
			"multi_currency": 0,
		}
	)

	for leg in legs:
		row = journal_entry.append(
			"accounts",
			{
				"account": leg.ledger_account,
				"debit_in_account_currency": leg.debit,
				"credit_in_account_currency": leg.credit,
				"cost_center": cost_center,
				"reference_type": "Transaction",
				"reference_name": transaction.name,
			},
		)
		if leg.party_type and leg.party:
			row.party_type = leg.party_type
			row.party = leg.party
		# Set by the Tracker accounting dimension; ERPNext copies it through to GL Entry.
		row.set("tracker", transaction.tracker)

	journal_entry.flags.ignore_permissions = True
	journal_entry.insert()
	journal_entry.submit()

	transaction.db_set("journal_entry", journal_entry.name, update_modified=False)

	_refresh_touched_balances(legs)

	return journal_entry.name


def unpost(transaction):
	"""Cancel the Journal Entry behind a Transaction.

	ERPNext writes reversing GL entries and flags the originals `is_cancelled`, so history
	is preserved rather than deleted (spec §80).
	"""
	if not transaction.journal_entry:
		return

	journal_entry = frappe.get_doc("Journal Entry", transaction.journal_entry)
	if journal_entry.docstatus == 1:
		journal_entry.flags.ignore_permissions = True
		journal_entry.cancel()

	touched = frappe.get_all(
		"Money Account",
		filters={"ledger_account": ["in", [row.account for row in journal_entry.accounts]]},
		pluck="name",
	)
	_recompute(touched)


def _refresh_touched_balances(legs):
	_recompute({leg.money_account for leg in legs if leg.money_account})


def _recompute(money_accounts):
	for money_account in money_accounts:
		balances.recompute_balances(money_account=money_account)


def _build_remark(transaction):
	parts = [transaction.transaction_type]
	if transaction.merchant:
		parts.append(transaction.merchant)
	if transaction.notes:
		parts.append(transaction.notes)
	return " | ".join(parts)


def check_sufficient_balance(transaction):
	"""Block an overdraft when Money Settings forbids negative balances (spec §79)."""
	settings = settings_service.get_settings()
	if settings.allow_negative_balance:
		return

	account = frappe.get_cached_doc("Money Account", transaction.account)
	if coa.is_liability(account.account_type):
		return
	if transaction.transaction_type in ("Income", "Refund"):
		return

	available = balances.get_account_balance(account.name)
	if flt(available) < flt(transaction.amount):
		frappe.throw(
			_("Insufficient balance in {0}: available {1}, required {2}.").format(
				account.account_name, flt(available), flt(transaction.amount)
			)
		)
