# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.utils.nestedset import NestedSet


class MoneyAccountGroup(NestedSet):
	"""Presentation-only hierarchy for grouping Money Accounts in the UI (spec §12).

	Deliberately separate from the accounting tree: the ERPNext Account tree is the
	accounting truth, this one is how the user wants their accounts arranged on screen.
	Keeping them apart means a user can regroup their dashboard without touching the ledger.
	"""

	nsm_parent_field = "parent_money_account_group"
