# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import settings as settings_service


class MoneyMerchant(Document):
	"""Who the money went to — promoted from a string to a record.

	`Transaction.merchant` was free text, which is fine for reading one voucher back and
	useless for everything else: "DMart", "Dmart" and "D-Mart" are three merchants to a GROUP
	BY and one to a person. A master fixes that, and gives the merchant somewhere to keep the
	things a string cannot — a default category, and the patterns a statement importer will
	match on.

	**Per tracker, like Category and unlike Money Payment Method.** A household's list of shops
	is its own; the ways of paying are a small closed set everybody shares. It does mean two
	trackers each get their own DMart, which is the same trade Category already makes.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()

	def validate(self):
		self.merchant_name = (self.merchant_name or "").strip()
		self.validate_unique_name_in_tracker()
		self.validate_default_category()

	def validate_unique_name_in_tracker(self):
		"""Case-insensitively unique per tracker, the same rule Money Tag follows.

		For the same reason: a merchant is typed inline on a transaction form, where "dmart"
		beside "DMart" would quietly split one merchant's spending in two — which is precisely
		the problem this doctype exists to solve.
		"""
		duplicate = frappe.db.exists(
			"Money Merchant",
			{
				"merchant_name": ["like", self.merchant_name],
				"tracker": self.tracker,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(_("A merchant named {0} already exists on this tracker.").format(self.merchant_name))

	def validate_default_category(self):
		"""A default has to be postable, or it would fill in a category that cannot be used.

		Stricter than `Money Budget`, which happily takes a group: a budget *measures* a
		subtree, while this is a value copied onto a transaction, and `Transaction` refuses to
		post to a heading.
		"""
		if not self.default_category:
			return

		category_tracker, category_type, is_group, category_name = frappe.db.get_value(
			"Category", self.default_category, ["tracker", "category_type", "is_group", "category_name"]
		)
		if category_tracker and category_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(category_name))
		if is_group:
			frappe.throw(
				_("{0} is a group category. A default has to be one a transaction can post to.").format(
					category_name
				)
			)

	def on_trash(self):
		"""Deleting a merchant clears the back-link and keeps the money.

		The same choice `Money Recurring Transaction` makes and the opposite of `Money Tag`:
		the spending really happened and is still worth reading, it just no longer says who it
		was with. A merchant somebody has finished with is better marked inactive.
		"""
		for doctype in ("Transaction", "Money Recurring Transaction"):
			for name in frappe.get_all(doctype, filters={"merchant": self.name}, pluck="name"):
				frappe.db.set_value(doctype, name, "merchant", None, update_modified=False)
