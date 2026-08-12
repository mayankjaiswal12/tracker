# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Currency conversion (spec §33, §34).

The original amount and currency on a Transaction are never altered. This module only
supplies the rate used to derive the base-currency figure that reports read.
"""

import frappe
from frappe.utils import flt

from moneytracker.money_tracker.services import settings as settings_service


def get_exchange_rate(from_currency, to_currency=None, transaction_date=None):
	"""Rate from `from_currency` to the base currency, as of a date.

	Reuses ERPNext's Currency Exchange store and its provider fallback rather than
	introducing a second rate table.
	"""
	to_currency = to_currency or settings_service.get_base_currency()
	if from_currency == to_currency:
		return 1.0

	from erpnext.setup.utils import get_exchange_rate as erpnext_get_exchange_rate

	rate = erpnext_get_exchange_rate(from_currency, to_currency, transaction_date)
	return flt(rate) or 1.0


def to_base_currency(amount, from_currency, transaction_date=None, exchange_rate=None):
	"""Return (base_amount, rate_used). An explicit rate always wins (§34 manual override)."""
	rate = flt(exchange_rate) or get_exchange_rate(from_currency, transaction_date=transaction_date)
	return flt(amount) * rate, rate
