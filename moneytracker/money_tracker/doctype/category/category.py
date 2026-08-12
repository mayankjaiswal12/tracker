# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

from moneytracker.money_tracker.services import coa, settings as settings_service


class Category(NestedSet):
	nsm_parent_field = "parent_category"

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()

	def validate(self):
		self.validate_parent_type()
		if not self.ledger_account and not self.is_group:
			self.ledger_account = coa.get_or_create_account_for_category(self)

	def validate_parent_type(self):
		if not self.parent_category:
			return

		parent_type, parent_name = frappe.db.get_value(
			"Category", self.parent_category, ["category_type", "category_name"]
		)
		if parent_type != self.category_type:
			frappe.throw(
				_("A {0} category cannot sit under the {1} category {2}. Income and expense trees are separate.").format(
					self.category_type, parent_type, parent_name
				)
			)

	def on_trash(self):
		if frappe.db.exists("Transaction", {"category": self.name}):
			frappe.throw(_("Cannot delete a category that has transactions against it."))
		super().on_trash()
