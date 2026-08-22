# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Ticking an account's transactions off against a bank statement.

The question this answers is narrow and worth stating exactly: *the statement says the closing
balance on this date was X; the books say it was Y; what has not been ticked off that would
account for the difference?*

**Nothing here changes any money.** `is_reconciled` and `cleared_date` record that a human has
seen a line on a statement. If the difference does not close, the answer is a missing or wrong
transaction, and the fix is to enter or correct one — not to adjust a balance until it agrees.
That is the whole reason there is no "create adjustment entry" button: an app that silently
plugs a gap has stopped being a ledger.

Deliberately **not** ERPNext's Bank Reconciliation Tool, which is built around Payment Entries
and invoices this app never creates.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from moneytracker.money_tracker.services import balances, coa


def get_reconciliation(money_account, statement_balance=None, as_of=None):
	"""Where the books and a statement agree, and what stands between them.

	`book_balance` is the account's real balance from `GL Entry` — the same figure every other
	surface shows, taken from `balances.get_account_balance` rather than recomputed, so a
	reconciliation screen can never disagree with the dashboard.

	`cleared_balance` is that balance with the unreconciled transactions taken back out: what
	the bank should think the balance is, if everything ticked off is everything they have
	processed. `difference` is what is left once the statement is compared against it, and a
	reconciliation is finished when it reaches zero.
	"""
	account = frappe.db.get_value(
		"Money Account",
		money_account,
		["name", "account_name", "ledger_account", "account_type", "tracker", "currency"],
		as_dict=True,
	)
	if not account:
		frappe.throw(_("{0} is not a Money Account.").format(money_account))

	book_balance = balances.get_account_balance(money_account, as_of)
	uncleared = get_uncleared(money_account, as_of)

	# Each uncleared transaction's own effect on this account, in the same direction the
	# balance is reported in. Removing them leaves what the bank has actually processed.
	uncleared_effect = flt(sum(row["effect"] for row in uncleared))
	cleared_balance = flt(book_balance - uncleared_effect)

	result = {
		"money_account": account.name,
		"account_name": account.account_name,
		"currency": account.currency,
		"as_of": as_of,
		"book_balance": flt(book_balance),
		"cleared_balance": cleared_balance,
		"uncleared_total": uncleared_effect,
		"uncleared_count": len(uncleared),
		"uncleared": uncleared,
		"statement_balance": None,
		"difference": None,
		"reconciled": False,
	}

	if statement_balance is not None and statement_balance != "":
		statement = flt(statement_balance)
		result["statement_balance"] = statement
		result["difference"] = flt(statement - cleared_balance)
		result["reconciled"] = not flt(result["difference"], 2)

	return result


def get_uncleared(money_account, as_of=None):
	"""Submitted transactions touching this account that nobody has ticked off yet.

	A transaction reaches an account either as its `account` or as its `destination_account`,
	and the sign differs between the two, so the effect is read from the ledger rather than
	guessed from the transaction type — the same rule `balances` follows, and the reason a
	transfer's two ends come out opposite without this module knowing what a transfer is.
	"""
	ledger_account, account_type, tracker = frappe.db.get_value(
		"Money Account", money_account, ["ledger_account", "account_type", "tracker"]
	)
	if not ledger_account:
		return []

	filters = {
		"tracker": tracker,
		"docstatus": 1,
		"is_reconciled": 0,
		"journal_entry": ["is", "set"],
	}
	if as_of:
		filters["date"] = ["<=", as_of]

	transactions = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=["name", "date", "transaction_type", "amount", "currency", "journal_entry", "reference_no"],
		order_by="date asc, name asc",
	)
	if not transactions:
		return []

	by_voucher = {row.journal_entry: row for row in transactions}
	rows = frappe.get_all(
		"GL Entry",
		filters={
			"voucher_no": ["in", list(by_voucher)],
			"account": ledger_account,
			"tracker": tracker,
			"is_cancelled": 0,
		},
		fields=["voucher_no", "SUM(debit) as debit", "SUM(credit) as credit"],
		group_by="voucher_no",
	)

	liability = coa.is_liability(account_type)
	uncleared = []
	for row in rows:
		effect = flt(row.debit) - flt(row.credit)
		if liability:
			effect = -effect
		if not effect:
			continue
		transaction = by_voucher[row.voucher_no]
		uncleared.append(
			{
				"transaction": transaction.name,
				"date": transaction.date,
				"transaction_type": transaction.transaction_type,
				"amount": flt(transaction.amount),
				"reference_no": transaction.reference_no,
				"effect": effect,
			}
		)

	uncleared.sort(key=lambda row: (getdate(row["date"]), row["transaction"]))
	return uncleared


def mark_reconciled(transactions, cleared_date=None, reconciled=True):
	"""Tick a batch of transactions off, or untick them. Returns how many changed.

	Written straight to the column rather than through the document: these are submitted, and
	`db_set` on a field carrying `allow_on_submit` is the sanctioned path. `update_modified`
	stays on, because unlike a migration this *is* somebody editing the record.
	"""
	if isinstance(transactions, str):
		transactions = frappe.parse_json(transactions) if transactions.startswith("[") else [transactions]

	changed = 0
	for name in transactions or []:
		doc = frappe.get_doc("Transaction", name)
		if doc.docstatus != 1:
			frappe.throw(_("{0} is not submitted, so there is nothing to reconcile.").format(name))
		frappe.has_permission("Transaction", "write", doc=doc, throw=True)

		if bool(doc.is_reconciled) == bool(reconciled):
			continue
		doc.db_set("is_reconciled", 1 if reconciled else 0)
		doc.db_set("cleared_date", (cleared_date or doc.date) if reconciled else None)
		changed += 1

	return changed
