# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Loans API: what is still owed, what the borrowing costs, and the widgets that say so."""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.api.dashboard import (
	CARD_NO_DATA,
	parse_widget_filters,
	resolve_widget_tracker,
)
from moneytracker.money_tracker.services import loans
from moneytracker.money_tracker.services import settings as settings_service


@frappe.whitelist()
def get_loans(tracker=None, as_of=None, status=None, direction=None):
	"""Every loan on a tracker, largest outstanding first."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)

	currency = _currency(tracker)
	debt = loans.get_debt_outstanding(tracker, as_of)
	return {
		"tracker": tracker,
		"currency": currency,
		"outstanding": debt.outstanding,
		"monthly_commitment": debt.monthly_commitment,
		"formatted": {
			"outstanding": fmt_money(debt.outstanding, currency=currency),
			"monthly_commitment": fmt_money(debt.monthly_commitment, currency=currency),
		},
		"loans": [
			_presented(row, currency) for row in loans.measure_loans(tracker, as_of, status, direction)
		],
	}


@frappe.whitelist()
def get_loan_progress(loan, as_of=None):
	"""One loan — the shape the form block draws from."""
	frappe.has_permission("Money Loan", doc=loan, throw=True)
	measured = loans.measure(loan, as_of)
	return _presented(measured, measured.currency or _currency(measured.tracker))


@frappe.whitelist()
def get_schedule(loan):
	"""The amortisation table, with each instalment marked paid or not.

	Paid is decided by **count**, not by matching a payment to a date: somebody who clears
	March and April in one afternoon has paid two instalments, and the schedule should say so
	rather than hunting for an April-dated payment that does not exist.
	"""
	frappe.has_permission("Money Loan", doc=loan, throw=True)
	doc = frappe.get_doc("Money Loan", loan)

	currency = doc.currency or _currency(doc.tracker)
	paid = len(loans.payments(doc.name))
	rows = []
	for row in loans.schedule_rows(doc):
		presented = row.as_row()
		presented["paid"] = row.instalment <= paid
		presented["formatted"] = {
			field: fmt_money(flt(presented[field]), currency=currency)
			for field in ("payment", "principal", "interest", "closing_balance")
		}
		rows.append(presented)

	return {"loan": doc.name, "currency": currency, "paid_count": paid, "schedule": rows}


def _currency(tracker):
	return frappe.db.get_value("Tracker", tracker, "base_currency") or settings_service.get_base_currency()


def _presented(row, currency):
	"""Money formatted server-side against the tracker's currency, not the browser's (§33)."""
	row.formatted = {
		field: fmt_money(flt(row.get(field)), currency=currency)
		for field in (
			"principal",
			"emi",
			"outstanding",
			"total_payable",
			"total_interest",
			"interest_paid",
			"principal_paid",
			"arrears_amount",
		)
	}
	return row


# ---------------------------------------------------------------------------
# Dashboard widgets. A Custom Number Card prints the returned string verbatim.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def card_debt_outstanding(filters=None):
	"""What is still owed across every borrowed loan, measured from the ledger.

	**Borrowed only**, and never netted against money lent out. They are opposite facts, and
	adding them would give a figure that answers no question — the same reason `Total Balance`
	refuses to subtract credit-card debt from cash and reports it in `Net Worth` instead.

	Measured from the loan accounts rather than from the schedules, so paying a lump sum off the
	principal shows up here the day it is posted rather than whenever the schedule said it would.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	debt = loans.get_debt_outstanding(tracker, filters.get("as_of"))
	return fmt_money(debt.outstanding, currency=_currency(tracker))


@frappe.whitelist()
def card_loans_in_arrears(filters=None):
	"""How many loans have an instalment behind — "1 behind", or "All on schedule".

	A count rather than a total, for the reason `Overdue Bills` is: this is about attention, and
	one missed instalment on a small loan needs the same thing done as one on a large loan. It
	also counts *loans* rather than instalments, because a loan three months behind is one
	conversation with one lender.
	"""
	filters = parse_widget_filters(filters)
	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return CARD_NO_DATA

	behind = sum(
		1
		for row in loans.measure_loans(tracker, filters.get("as_of"), status="Active")
		if row.outcome == loans.IN_ARREARS
	)
	return _("{0} behind").format(behind) if behind else _("All on schedule")
