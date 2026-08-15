# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MoneySettings(Document):
	def validate(self):
		company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if company_currency and self.base_currency != company_currency:
			frappe.throw(
				_(
					"Base Currency must match the default currency of Company {0}, which is {1}. "
					"ERPNext reports company-currency totals, so a mismatch would misstate every report."
				).format(self.company, company_currency)
			)

		for fieldname in (
			"bank_parent_account",
			"cash_parent_account",
			"current_asset_parent_account",
			"fixed_asset_parent_account",
			"liability_parent_account",
			"income_parent_account",
			"expense_parent_account",
			"receivable_parent_account",
		):
			account = self.get(fieldname)
			if not account:
				continue

			is_group, company = frappe.db.get_value("Account", account, ["is_group", "company"])
			if not is_group:
				frappe.throw(
					_("{0}: {1} is a ledger account. Parent accounts must be group accounts.").format(
						_(self.meta.get_label(fieldname)), account
					)
				)
			if company != self.company:
				frappe.throw(
					_("{0}: {1} belongs to Company {2}, not {3}.").format(
						_(self.meta.get_label(fieldname)), account, company, self.company
					)
				)
