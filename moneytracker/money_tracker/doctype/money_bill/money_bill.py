# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import bills
from moneytracker.money_tracker.services import settings as settings_service


class MoneyBill(Document):
	"""Money that is owed, tracked until it is settled.

	The boundary against `Money Recurring Transaction` is in `services/bills.py`'s docstring
	and is the reason this doctype exists at all: a plan posts by itself and is never waiting
	on anybody, while a bill is a claim that stays open until a person deals with it. The
	giveaway is *overdue*, a state a plan cannot have.

	Validation is deliberately lighter than a plan's. A plan runs unattended, so whatever is
	wrong with it is wrong every month until somebody notices; a bill is looked at by the
	person paying it, and refusing to save one because its category is not filled in yet would
	get in the way of writing down that money is owed — which is the only thing that matters
	at the moment it arrives.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.currency:
			self.currency = (
				frappe.db.get_value("Tracker", self.tracker, "base_currency")
				or settings_service.get_base_currency()
			)
		if not self.due_date:
			self.due_date = today()

	def validate(self):
		bills.get_frequency(self.frequency)
		self.validate_unique_name_in_tracker()
		self.validate_amount()
		self.validate_window()
		self.validate_links()

	def validate_unique_name_in_tracker(self):
		"""Unique per tracker *among open bills only*.

		Unlike every other master in this app: a repeating bill mints its successor with the
		same name, so "Electricity" in March and "Electricity" in April must both be allowed to
		exist. What must not is two *unpaid* Electricity bills at once, which is somebody
		entering the same claim twice.
		"""
		if self.status != "Unpaid":
			return
		duplicate = frappe.db.exists(
			"Money Bill",
			{
				"bill_name": self.bill_name,
				"tracker": self.tracker,
				"status": "Unpaid",
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("There is already an unpaid bill called {0}. Pay or cancel that one first.").format(
					frappe.bold(self.bill_name)
				)
			)

	def validate_amount(self):
		if self.amount_varies:
			self.amount = 0
			return
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero, or tick Amount Varies."))

	def validate_window(self):
		if self.end_date and getdate(self.end_date) < getdate(self.due_date):
			frappe.throw(_("Until cannot be before the Due Date."))

	def validate_links(self):
		for fieldname, doctype in (
			("category", "Category"),
			("account", "Money Account"),
			("merchant", "Money Merchant"),
		):
			name = self.get(fieldname)
			if not name:
				continue
			owner = frappe.db.get_value(doctype, name, "tracker")
			if owner and owner != self.tracker:
				frappe.throw(_("{0} belongs to another tracker.").format(name))

		if self.category:
			category_type, is_group, category_name = frappe.db.get_value(
				"Category", self.category, ["category_type", "is_group", "category_name"]
			)
			if is_group:
				frappe.throw(
					_("{0} is a group category. Choose one of its sub-categories.").format(category_name)
				)
			if category_type != "Expense":
				frappe.throw(_("{0} is an income category. A bill is money owed.").format(category_name))

	@frappe.whitelist()
	def mark_paid(self, amount=None, account=None, paid_on=None):
		"""Settle the bill: post the transaction, and mint the next one if it repeats.

		The transaction is the record of the money; the bill only records that it was owed and
		now is not. Both, because deleting the bill later must not delete the payment — the
		money really moved.
		"""
		if self.status == "Paid":
			frappe.throw(_("{0} is already paid.").format(self.bill_name))

		amount = flt(amount) if amount else flt(self.amount)
		if amount <= 0:
			frappe.throw(_("How much was paid?"))

		account = account or self.account
		if not account:
			frappe.throw(_("Which account was it paid from?"))
		if not self.category:
			frappe.throw(_("A payment needs a category. Set one on the bill first."))

		paid_on = getdate(paid_on or today())
		transaction = frappe.get_doc(
			{
				"doctype": "Transaction",
				"tracker": self.tracker,
				"date": paid_on,
				"transaction_type": "Expense",
				"amount": amount,
				"currency": self.currency,
				"account": account,
				"category": self.category,
				"payment_method": self.payment_method,
				"merchant": self.merchant,
				"notes": self.notes,
				"bill": self.name,
			}
		)
		transaction.insert()
		transaction.submit()

		self.db_set("status", "Paid")
		self.db_set("linked_transaction", transaction.name)
		self.db_set("paid_on", paid_on)

		return {"transaction": transaction.name, "next_bill": self.mint_next()}

	def mint_next(self):
		"""The next bill in a repeating arrangement, or `None`.

		One open bill per arrangement at a time: the successor appears when this one is settled,
		not all twelve up front. A year of unpaid rows would make "what do I owe" meaningless
		and every reminder fire eleven times over.
		"""
		nxt = bills.next_due_date(self)
		if not nxt:
			return None

		successor = frappe.copy_doc(self)
		successor.due_date = nxt
		successor.status = "Unpaid"
		successor.linked_transaction = None
		successor.paid_on = None
		successor.last_reminder = None
		successor.insert()
		return successor.name

	def on_trash(self):
		"""Deleting a bill keeps the payment it made and clears the link.

		The same choice a recurring plan makes: the money really moved, only the record of what
		was owed is going away.
		"""
		if self.linked_transaction:
			frappe.db.set_value("Transaction", self.linked_transaction, "bill", None, update_modified=False)
