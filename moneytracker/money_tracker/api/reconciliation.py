# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Reconciliation API: the books against a statement, and the ticking off."""

import frappe
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.services import reconciliation as reconciliation_service


@frappe.whitelist()
def get_reconciliation(money_account, statement_balance=None, as_of=None):
	"""What the books say, what has not been ticked off, and what the difference is."""
	frappe.has_permission("Money Account", doc=money_account, throw=True)

	result = reconciliation_service.get_reconciliation(money_account, statement_balance, as_of)
	currency = result["currency"]

	# Formatted server-side against the account's own currency (§33).
	result["formatted"] = {
		key: fmt_money(flt(result[key]), currency=currency)
		for key in ("book_balance", "cleared_balance", "uncleared_total")
		if result[key] is not None
	}
	if result["difference"] is not None:
		result["formatted"]["difference"] = fmt_money(flt(result["difference"]), currency=currency)
	for row in result["uncleared"]:
		row["formatted_effect"] = fmt_money(flt(row["effect"]), currency=currency)
	return result


@frappe.whitelist()
def mark_reconciled(transactions, cleared_date=None, reconciled=1):
	"""Tick transactions off against a statement, or untick them."""
	changed = reconciliation_service.mark_reconciled(
		transactions, cleared_date, reconciled=bool(int(reconciled))
	)
	return {"changed": changed}
