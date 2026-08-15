# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import settings as settings_service


class Tracker(Document):
	def before_insert(self):
		if not self.owner_user:
			self.owner_user = frappe.session.user
		if not self.base_currency:
			self.base_currency = settings_service.get_base_currency()

	def on_trash(self):
		if frappe.db.exists("Transaction", {"tracker": self.name}):
			frappe.throw(_("Cannot delete a tracker that has transactions on it. Archive it instead."))
