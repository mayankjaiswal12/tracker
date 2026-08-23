# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import os

import frappe
from frappe import _
from frappe.model.document import Document

from moneytracker.money_tracker.services import receipts as receipts_service
from moneytracker.money_tracker.services import settings as settings_service


class MoneyReceipt(Document):
	"""The piece of paper behind a transaction.

	**A standalone document rather than a child table of `Transaction`, and `transaction` is
	optional.** A receipt is often captured before the spending is entered — you photograph the
	bill at the till and type it up on Sunday — and a child row cannot exist without a parent.
	That also makes an unattached receipt a real thing the app can show you: an inbox of paper
	nobody has entered yet.

	The `ocr_*` columns are filled by nothing today. They are here so that receipt scanning can
	be added later without a schema change and without a migration over everybody's history,
	which is what "AI-ready" has to mean if it means anything. `ocr_status` starts at
	*Not Scanned* and the reading, when it arrives, is kept separate from what the user typed —
	an extracted amount is evidence, not a fact.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = (
				frappe.db.get_value("Transaction", self.transaction, "tracker")
				if self.transaction
				else settings_service.get_default_tracker()
			)
		if not self.title:
			self.title = self.derive_title()

	def validate(self):
		self.validate_transaction()
		self.validate_file()
		self.set_file_type()
		self.set_thumbnail()

	def validate_transaction(self):
		"""A receipt and the transaction it belongs to must be the same household's."""
		if not self.transaction:
			return
		transaction_tracker = frappe.db.get_value("Transaction", self.transaction, "tracker")
		if transaction_tracker and self.tracker and transaction_tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(self.transaction))
		self.tracker = self.tracker or transaction_tracker

	def validate_file(self):
		if not (self.file or self.image):
			frappe.throw(_("A receipt needs a file or an image."))

	def derive_title(self):
		source = self.image or self.file or ""
		return os.path.basename(source.split("?")[0]) or _("Receipt")

	def set_file_type(self):
		"""Derived from the file itself, so it cannot disagree with what was uploaded."""
		self.file_type = receipts_service.classify(self.image or self.file)

	def set_thumbnail(self):
		"""Only an image has one. A PDF gets none rather than a broken preview.

		Frappe already generates a thumbnail for an `Attach Image` field when the file is
		uploaded through Desk, so this points at the image rather than making a second copy —
		a receipts folder is the one place in this app where storage genuinely adds up.
		"""
		self.thumbnail = self.image if self.file_type == receipts_service.IMAGE else None
