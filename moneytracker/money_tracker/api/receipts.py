# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Receipts API: the paper behind a transaction, and the paper behind nothing yet."""

import frappe

from moneytracker.money_tracker.services import receipts as receipts_service
from moneytracker.money_tracker.services import settings as settings_service


@frappe.whitelist()
def get_receipts(transaction):
	"""Every receipt attached to one transaction."""
	frappe.has_permission("Transaction", doc=transaction, throw=True)
	return receipts_service.get_receipts(transaction)


@frappe.whitelist()
def get_unattached(tracker=None, limit=50):
	"""The inbox: receipts captured but not yet linked to any transaction."""
	tracker = tracker or settings_service.get_default_tracker()
	frappe.has_permission("Tracker", doc=tracker, throw=True)
	return receipts_service.get_unattached(tracker, limit=int(limit))


@frappe.whitelist()
def attach(receipt, transaction):
	"""Link a captured receipt to a transaction."""
	frappe.has_permission("Money Receipt", "write", doc=receipt, throw=True)
	frappe.has_permission("Transaction", "write", doc=transaction, throw=True)
	return receipts_service.attach(receipt, transaction)
