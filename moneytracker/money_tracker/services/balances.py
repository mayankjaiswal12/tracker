# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Balances and net worth, derived from GL Entry.

GL Entry is the single source of truth (spec §68). Money Account.current_balance is a
cache and is always *recomputed* from the ledger, never incremented in place — an
incremental counter silently drifts and there is no way to tell that it has.
"""

import frappe
from frappe.utils import flt

from moneytracker.money_tracker.services import coa, settings as settings_service

# Asset and Expense accounts increase with a debit; Liability, Equity and Income increase
# with a credit. Balances are reported in the direction that makes the account's own
# balance positive when it holds what you would expect it to hold.
DEBIT_POSITIVE_ROOT_TYPES = {"Asset", "Expense"}


def get_account_balance(money_account, as_of=None):
	"""Signed balance of one Money Account, in its natural direction."""
	ledger_account, account_type, tracker = frappe.db.get_value(
		"Money Account", money_account, ["ledger_account", "account_type", "tracker"]
	)
	if not ledger_account:
		return 0.0

	# Scoped by tracker, not just by account: one ERPNext Account is shared by every tracker
	# that happens to use the same account name, so the account alone would sum other
	# people's movements into this balance.
	filters = {"account": ledger_account, "is_cancelled": 0, "tracker": tracker}
	if as_of:
		filters["posting_date"] = ["<=", as_of]

	totals = frappe.db.get_all(
		"GL Entry",
		filters=filters,
		fields=["SUM(debit) as debit", "SUM(credit) as credit"],
	)[0]

	delta = flt(totals.debit) - flt(totals.credit)
	if coa.is_liability(account_type):
		delta = -delta
	return delta


def get_balances_for_tracker(tracker, as_of=None):
	"""Balance of every account on a tracker in ONE aggregate query.

	Deliberately not a loop over get_account_balance — that is the N+1 pattern §74 rules out.
	"""
	accounts = frappe.get_all(
		"Money Account",
		filters={"tracker": tracker},
		fields=["name", "account_name", "account_type", "ledger_account", "currency"],
	)
	by_ledger = {a.ledger_account: a for a in accounts if a.ledger_account}
	if not by_ledger:
		return []

	gl_filters = {"account": ["in", list(by_ledger)], "is_cancelled": 0, "tracker": tracker}
	if as_of:
		gl_filters["posting_date"] = ["<=", as_of]

	rows = frappe.get_all(
		"GL Entry",
		filters=gl_filters,
		fields=["account", "SUM(debit) as debit", "SUM(credit) as credit"],
		group_by="account",
	)
	movement = {r.account: flt(r.debit) - flt(r.credit) for r in rows}

	result = []
	for ledger_account, account in by_ledger.items():
		delta = movement.get(ledger_account, 0.0)
		if coa.is_liability(account.account_type):
			delta = -delta
		result.append(
			{
				"money_account": account.name,
				"account_name": account.account_name,
				"account_type": account.account_type,
				"currency": account.currency,
				"balance": delta,
			}
		)
	return result


def recompute_balances(tracker=None, money_account=None):
	"""Refresh the current_balance cache from the ledger. Returns the number updated."""
	filters = {}
	if tracker:
		filters["tracker"] = tracker
	if money_account:
		filters["name"] = money_account

	trackers = (
		[tracker]
		if tracker
		else [t.name for t in frappe.get_all("Money Account", filters=filters, fields=["distinct tracker as name"])]
	)

	updated = 0
	for tracker_name in trackers:
		for row in get_balances_for_tracker(tracker_name):
			if money_account and row["money_account"] != money_account:
				continue
			frappe.db.set_value(
				"Money Account", row["money_account"], "current_balance", row["balance"], update_modified=False
			)
			updated += 1
	return updated


def get_net_worth(tracker=None, as_of=None):
	"""Net worth = assets - liabilities, over accounts flagged include_in_net_worth (§31)."""
	filters = {"include_in_net_worth": 1}
	if tracker:
		filters["tracker"] = tracker

	accounts = frappe.get_all(
		"Money Account", filters=filters, fields=["name", "account_type", "ledger_account"]
	)
	by_ledger = {a.ledger_account: a for a in accounts if a.ledger_account}
	if not by_ledger:
		return {"assets": 0.0, "liabilities": 0.0, "net_worth": 0.0}

	gl_filters = {"account": ["in", list(by_ledger)], "is_cancelled": 0}
	# Only when a tracker is given — a bare get_net_worth() is a deliberate all-trackers total.
	if tracker:
		gl_filters["tracker"] = tracker
	if as_of:
		gl_filters["posting_date"] = ["<=", as_of]

	rows = frappe.get_all(
		"GL Entry",
		filters=gl_filters,
		fields=["account", "SUM(debit) as debit", "SUM(credit) as credit"],
		group_by="account",
	)

	assets = liabilities = 0.0
	for row in rows:
		account = by_ledger[row.account]
		delta = flt(row.debit) - flt(row.credit)
		if coa.is_liability(account.account_type):
			liabilities += -delta
		else:
			assets += delta

	return {
		"assets": assets,
		"liabilities": liabilities,
		"net_worth": assets - liabilities,
		"currency": settings_service.get_base_currency(),
	}
