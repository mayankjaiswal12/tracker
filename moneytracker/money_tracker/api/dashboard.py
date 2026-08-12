# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard and balance API (spec §5, §70)."""

import frappe
from frappe.utils import flt, get_first_day, get_last_day, today

from moneytracker.money_tracker.services import balances, settings as settings_service


@frappe.whitelist()
def get_account_balance(money_account, as_of=None):
	frappe.has_permission("Money Account", doc=money_account, throw=True)
	return balances.get_account_balance(money_account, as_of)


@frappe.whitelist()
def get_balances(tracker=None, as_of=None):
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)
	return balances.get_balances_for_tracker(tracker, as_of)


@frappe.whitelist()
def get_net_worth(tracker=None, as_of=None):
	if tracker:
		frappe.has_permission("Tracker", doc=tracker, throw=True)
	return balances.get_net_worth(tracker, as_of)


@frappe.whitelist()
def recompute_balances(tracker=None):
	"""Reconciliation tool for the cached balances (spec §68)."""
	if tracker:
		frappe.has_permission("Tracker", doc=tracker, ptype="write", throw=True)
	return {"updated": balances.recompute_balances(tracker=tracker)}


def _period_totals(tracker, from_date, to_date):
	"""Income and expense for a period, from the Transaction ledger in one grouped query."""
	rows = frappe.get_all(
		"Transaction",
		filters={
			"tracker": tracker,
			"docstatus": 1,
			"date": ["between", [from_date, to_date]],
			"transaction_type": ["in", ["Income", "Expense", "Refund"]],
		},
		fields=["transaction_type", "SUM(base_amount) as total"],
		group_by="transaction_type",
	)
	totals = {r.transaction_type: flt(r.total) for r in rows}
	# A refund reduces spend rather than adding income (§62).
	expense = totals.get("Expense", 0.0) - totals.get("Refund", 0.0)
	return totals.get("Income", 0.0), expense


@frappe.whitelist()
def get_dashboard(tracker=None, as_of=None):
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	as_of = as_of or today()
	month_start = get_first_day(as_of)
	month_end = get_last_day(as_of)

	income, expense = _period_totals(tracker, month_start, month_end)
	net_worth = balances.get_net_worth(tracker, as_of)
	savings = income - expense

	return {
		"tracker": tracker,
		"tracker_name": frappe.db.get_value("Tracker", tracker, "tracker_name"),
		"currency": settings_service.get_base_currency(),
		"as_of": as_of,
		"period": {"from_date": month_start, "to_date": month_end},
		"total_balance": sum(
			row["balance"] for row in balances.get_balances_for_tracker(tracker, as_of)
		),
		"assets": net_worth["assets"],
		"liabilities": net_worth["liabilities"],
		"net_worth": net_worth["net_worth"],
		"monthly_income": income,
		"monthly_expense": expense,
		"monthly_savings": savings,
		"savings_rate": (savings / income * 100) if income else 0.0,
		"accounts": balances.get_balances_for_tracker(tracker, as_of),
		"recent_transactions": frappe.get_all(
			"Transaction",
			filters={"tracker": tracker, "docstatus": 1},
			fields=[
				"name",
				"date",
				"transaction_type",
				"amount",
				"currency",
				"account",
				"account.account_name as account_name",
				"category",
				"category.category_name as category_name",
				"merchant",
			],
			# Table-qualified: the dotted fields above make this a JOIN, and both `date` and
			# `creation` exist on the joined tables too.
			order_by="`tabTransaction`.`date` desc, `tabTransaction`.`creation` desc",
			limit_page_length=10,
		),
	}
