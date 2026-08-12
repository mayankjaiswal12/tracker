# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe

from moneytracker.money_tracker.setup import create_finance_roles


def execute():
	create_finance_roles()
	frappe.db.commit()
