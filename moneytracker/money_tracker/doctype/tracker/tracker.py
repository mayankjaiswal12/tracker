# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import categories, settings as settings_service


class Tracker(Document):
	def before_insert(self):
		if not self.owner_user:
			self.owner_user = frappe.session.user
		if not self.base_currency:
			self.base_currency = settings_service.get_base_currency()

	def after_insert(self):
		"""Start the tracker off with a usable category tree.

		A tracker with no categories cannot record a single expense, and the first one is
		often created implicitly by `settings.get_default_tracker()` — so leaving this to the
		user means their first transaction fails on an empty link field.

		`flags.skip_default_categories` exists for the test factories: seeding ~40 categories
		per fixture tracker would dominate the suite's runtime and put rows in the way of
		tests that count what they created.
		"""
		if self.flags.skip_default_categories:
			return
		categories.seed_default_categories(self.name)

	def on_trash(self):
		if frappe.db.exists("Transaction", {"tracker": self.name}):
			frappe.throw(_("Cannot delete a tracker that has transactions on it. Archive it instead."))
