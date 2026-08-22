# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import settings as settings_service


class MoneyTag(Document):
	"""A label that cuts across the category tree.

	A category answers *what kind of spending is this* and a transaction has exactly one, so
	the tree has to be a partition — every rupee lands in one leaf and the roll-ups add up.
	A tag answers *what was this for*, and one purchase can honestly be several things at
	once: a café bill on a family holiday is Eating Out, and Vacation, and Kids.

	That is the whole reason this is not another Category. Tag totals **overlap by design**
	and do not sum to the tracker's spending — `services/tags.py` says so where it matters.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()

	def validate(self):
		self.tag_name = (self.tag_name or "").strip()
		self.validate_unique_name_in_tracker()

	def validate_unique_name_in_tracker(self):
		"""Names are unique per tracker, not globally — as with Money Account and Money Budget.

		Compared case-insensitively, which the other doctypes do not need to do: two accounts
		called "HDFC" and "hdfc" are a typo somebody will notice on a list of six, while tags
		are typed inline on a transaction form and "vacation" beside "Vacation" would quietly
		split one total in two.
		"""
		duplicate = frappe.db.exists(
			"Money Tag",
			{
				"tag_name": ["like", self.tag_name],
				"tracker": self.tracker,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(_("A tag named {0} already exists on this tracker.").format(self.tag_name))

	def on_trash(self):
		"""Deleting a tag takes it off the transactions that carry it.

		The opposite of `Money Recurring Transaction.on_trash`, which keeps its transactions and
		only clears the back-link — because there the money really moved and only the
		arrangement is going away. A tag is nothing but the label, so removing it removes the
		whole of what it was.
		"""
		frappe.db.delete("Money Transaction Tag", {"tag": self.name})
