# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Category: a tree of spending headings, one level or many.

A group category is a *heading*: it holds no ledger account and nothing can be posted to it,
so a total like "Food 4,500" is always the sum of its leaves and never a mix of its own
postings and its children's. The tree is a Money Tracker concept — every leaf still gets its
own flat ERPNext Account — so roll-up totals are computed from `lft`/`rgt` here rather than
by nesting the chart of accounts.
"""

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
		self.validate_parent()
		self.validate_unique_name()
		self.validate_group_flag()
		self.set_ledger_account()

	def validate_parent(self):
		if not self.parent_category:
			return

		parent = frappe.db.get_value(
			"Category",
			self.parent_category,
			["category_type", "category_name", "is_group", "tracker"],
			as_dict=True,
		)

		if parent.category_type != self.category_type:
			frappe.throw(
				_(
					"A {0} category cannot sit under the {1} category {2}. Income and expense trees are separate."
				).format(self.category_type, parent.category_type, parent.category_name)
			)

		if parent.tracker != self.tracker:
			frappe.throw(_("Category {0} belongs to another tracker.").format(parent.category_name))

		if not parent.is_group:
			frappe.throw(
				_(
					"Category {0} is not a group. Tick Is Group on it before nesting anything under it."
				).format(parent.category_name)
			)

	def validate_unique_name(self):
		"""One name per tracker and type.

		Not cosmetic: `coa.get_or_create_ledger_account` keys an ERPNext Account on its name,
		so two categories called "Groceries" would quietly share one ledger account and each
		would report the other's spending as its own.
		"""
		duplicate = frappe.db.get_value(
			"Category",
			{
				"category_name": self.category_name,
				"category_type": self.category_type,
				"tracker": self.tracker,
				"name": ["!=", self.name],
			},
			"name",
		)
		if duplicate:
			frappe.throw(
				_("You already have a {0} category called {1}.").format(
					self.category_type.lower(), self.category_name
				)
			)

	def validate_group_flag(self):
		if self.is_new() or not self.has_value_changed("is_group"):
			return

		if self.is_group:
			# Its own postings would sit alongside its children's, so a heading's total would
			# no longer be the sum of its leaves.
			if frappe.db.exists("Transaction", {"category": self.name}):
				frappe.throw(
					_(
						"{0} already has transactions against it, so it cannot become a group. Move them to a sub-category first."
					).format(self.category_name)
				)
		elif frappe.db.exists("Category", {"parent_category": self.name}):
			frappe.throw(_("{0} has sub-categories, so it has to stay a group.").format(self.category_name))

	def set_ledger_account(self):
		if self.is_group:
			# A heading holds no money. Clearing rather than leaving a stale link matters when a
			# leaf is promoted: the old account may be shared with another tracker's category
			# of the same name, so it is dropped here, never deleted.
			self.ledger_account = None
			return

		if not self.ledger_account:
			self.ledger_account = coa.get_or_create_account_for_category(self)

	def on_trash(self):
		if frappe.db.exists("Transaction", {"category": self.name}):
			frappe.throw(_("Cannot delete a category that has transactions against it."))
		super().on_trash()
