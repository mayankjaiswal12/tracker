# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, fmt_money

from moneytracker.money_tracker.posting import engine
from moneytracker.money_tracker.services import fx
from moneytracker.money_tracker.services import settings as settings_service

# Types where `destination_account` is the other side of the movement rather than a category.
ACCOUNT_TO_ACCOUNT_TYPES = ("Transfer", "Credit Card Payment")


class Transaction(Document):
	def before_validate(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.company:
			self.company = settings_service.get_company()
		if not self.currency:
			self.currency = frappe.db.get_value("Money Account", self.account, "currency")
		self.apply_merchant_defaults()

	def validate(self):
		self.validate_amount()
		self.validate_accounts()
		self.validate_category()
		self.validate_tags()
		self.validate_merchant()
		self.set_base_amount()
		# After `set_base_amount`, which is where `exchange_rate` is resolved — each split row
		# is stamped with its own base amount at that rate.
		self.validate_splits()
		self.validate_fee()

	def apply_merchant_defaults(self):
		"""Let the merchant fill in what has been left blank, and nothing else.

		A default is a convenience on entry, not a rule: it only ever fills an empty field, so
		editing a merchant never rewrites what is already saved, and a category typed by hand
		always wins. Runs in `before_validate` so `validate_category` still gets the last word
		on whatever ends up there.
		"""
		if not self.merchant or self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			return

		defaults = frappe.db.get_value(
			"Money Merchant", self.merchant, ["default_category", "default_payment_method"], as_dict=True
		)
		if not defaults:
			return
		if not self.category:
			self.category = defaults.default_category
		if not self.payment_method:
			self.payment_method = defaults.default_payment_method

	def validate_merchant(self):
		"""A merchant from another tracker would quietly mix two households' spending."""
		if not self.merchant:
			return

		merchant_tracker, merchant_name = frappe.db.get_value(
			"Money Merchant", self.merchant, ["tracker", "merchant_name"]
		)
		if merchant_tracker and merchant_tracker != self.tracker:
			frappe.throw(_("Merchant {0} belongs to another tracker.").format(frappe.bold(merchant_name)))

	def validate_amount(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero."))

	def validate_accounts(self):
		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			if not self.destination_account:
				frappe.throw(_("Destination Account is required for a {0}.").format(self.transaction_type))
			# A movement between two accounts has no category by construction; clearing it
			# here stops a stale value from a retyped transaction reaching the ledger.
			self.category = None
		elif self.destination_account:
			self.destination_account = None

	def validate_category(self):
		"""A group category is a heading, not a place to post.

		Caught here rather than at submit: the posting engine would fail too, on the missing
		ledger account, but by then the user has already filled in a whole voucher and the
		message talks about accounting rather than about the choice they made.
		"""
		if not self.category:
			return

		category_name, is_group = frappe.db.get_value(
			"Category", self.category, ["category_name", "is_group"]
		)
		if is_group:
			frappe.throw(
				_("{0} is a group category. Post to one of its sub-categories instead.").format(category_name)
			)

	def validate_splits(self):
		"""Splits must add up to the amount, and each must be somewhere money can be posted.

		**When a transaction is split it has no single category, so `category` is cleared.**
		Keeping a "primary" one alongside the rows would be counted twice by everything that
		sums categories — the roll-up, the chart, every budget. `services/categories.py` reads
		the split rows instead, which is why splitting a bill does not make its money vanish
		from a budget.

		`base_amount` is stamped on each row here, at the transaction's own exchange rate, for
		the same reason `Transaction.base_amount` is stored: the rate is a fact about the day
		it happened, and recomputing later would restate last year's totals. This runs *after*
		`set_base_amount` for that reason — that is where the rate is resolved.
		"""
		if not self.splits:
			return

		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			frappe.throw(
				_(
					"A {0} moves money between accounts, so there is nothing to split across categories."
				).format(self.transaction_type)
			)

		total = sum(flt(row.amount) for row in self.splits)
		if flt(total, self.precision("amount")) != flt(self.amount, self.precision("amount")):
			frappe.throw(
				_("The splits add up to {0}, but the transaction is {1}.").format(
					frappe.bold(fmt_money(total, currency=self.currency)),
					frappe.bold(fmt_money(flt(self.amount), currency=self.currency)),
				)
			)

		expected = "Income" if self.transaction_type == "Income" else "Expense"
		rate = flt(self.exchange_rate) or 1.0

		for row in self.splits:
			if flt(row.amount) <= 0:
				frappe.throw(_("Every split must be greater than zero."))

			category = frappe.db.get_value(
				"Category",
				row.category,
				["tracker", "category_type", "is_group", "category_name"],
				as_dict=True,
			)
			if category.tracker and category.tracker != self.tracker:
				frappe.throw(_("Category {0} belongs to another tracker.").format(category.category_name))
			if category.is_group:
				frappe.throw(
					_("{0} is a group category. Split to one of its sub-categories instead.").format(
						category.category_name
					)
				)
			if category.category_type != expected:
				frappe.throw(
					_("{0} is an {1} category, but this is a {2}.").format(
						category.category_name, category.category_type, self.transaction_type
					)
				)
			row.base_amount = flt(row.amount) * rate

		# Last, so the checks above still had the single category available to compare against.
		self.category = None

	def validate_fee(self):
		"""A fee belongs to a movement between accounts, and is expense wherever it lands.

		Only Transfer and Credit Card Payment can carry one: every other type already has a
		category of its own, and a "fee" on an expense is simply part of the expense.

		Like the split rows, `fee_base_amount` is stamped at the transaction's own rate, so
		this runs after `set_base_amount` too.
		"""
		if not flt(self.fee_amount):
			self.fee_amount = 0
			self.fee_category = None
			self.fee_base_amount = 0
			return

		if self.transaction_type not in ACCOUNT_TO_ACCOUNT_TYPES:
			frappe.throw(
				_(
					"Only a Transfer or a Credit Card Payment carries a fee. A charge on a {0} is part of it."
				).format(self.transaction_type)
			)
		if flt(self.fee_amount) < 0:
			frappe.throw(_("Fee Amount cannot be negative."))
		if not self.fee_category:
			frappe.throw(_("A fee is spending, so it needs an expense category to be charged to."))

		category = frappe.db.get_value(
			"Category",
			self.fee_category,
			["tracker", "category_type", "is_group", "category_name"],
			as_dict=True,
		)
		if category.tracker and category.tracker != self.tracker:
			frappe.throw(_("Category {0} belongs to another tracker.").format(category.category_name))
		if category.is_group:
			frappe.throw(
				_("{0} is a group category. Charge the fee to one of its sub-categories.").format(
					category.category_name
				)
			)
		if category.category_type != "Expense":
			frappe.throw(_("{0} is an income category. A fee is spending.").format(category.category_name))

		self.fee_base_amount = flt(self.fee_amount) * (flt(self.exchange_rate) or 1.0)

	def validate_tags(self):
		"""Tags must belong to this tracker, and each may appear once.

		Checked at Save rather than at submit, unlike the category: a tag never reaches the
		ledger, so the posting engine would not catch a stray one — nothing downstream would,
		and it would surface much later as a tag total quietly mixing two households.

		A duplicated row is dropped rather than refused. It is a double-click on a multiselect,
		not a decision worth interrupting somebody over, and left alone it would count the same
		transaction twice in that tag's total.
		"""
		if not self.tags:
			return

		seen = {}
		for row in self.tags:
			seen.setdefault(row.tag, row)
		if len(seen) != len(self.tags):
			self.tags = list(seen.values())
			for idx, row in enumerate(self.tags, start=1):
				row.idx = idx

		owners = frappe.get_all(
			"Money Tag",
			filters={"name": ["in", list(seen)]},
			fields=["name", "tag_name", "tracker"],
		)
		for tag in owners:
			if tag.tracker and tag.tracker != self.tracker:
				frappe.throw(_("Tag {0} belongs to another tracker.").format(frappe.bold(tag.tag_name)))

	def set_base_amount(self):
		base_amount, rate = fx.to_base_currency(self.amount, self.currency, self.date, self.exchange_rate)
		self.exchange_rate = rate
		self.base_amount = base_amount

	def on_update_after_submit(self):
		"""Tags are the one thing on a submitted transaction that may still change.

		`tags` carries `allow_on_submit`, and it is the only field on this doctype that does.
		A submitted transaction is immutable because its money is already in the ledger — but a
		tag reaches no `GL Entry`, no `Journal Entry` and no account, so freezing it protects
		nothing and costs the main thing tags are for: you come back from a holiday and label
		the fortnight you have already entered. The category cannot work that way, because each
		leaf owns a ledger account and changing it would move real money.

		Frappe does not run `validate` on an update-after-submit, so the check is re-run here
		rather than trusted to have happened at insert.
		"""
		self.validate_tags()

	def before_submit(self):
		engine.check_sufficient_balance(self)

	def on_submit(self):
		if settings_service.get_settings().auto_post_transactions:
			engine.post(self)

	def on_cancel(self):
		# Frappe would otherwise complain that journal_entry changed after cancellation.
		self.ignore_linked_doctypes = ("Journal Entry", "GL Entry")
		engine.unpost(self)

	def on_trash(self):
		if self.journal_entry:
			frappe.throw(
				_("Cannot delete a posted transaction. Cancel it instead, which reverses the ledger entries.")
			)

	@frappe.whitelist()
	def reverse(self):
		"""Create a mirror-image transaction that cancels this one out (spec §80).

		Used when the original must stay on the books — cancelling would hide it, whereas a
		reversal leaves both the original and its correction visible.
		"""
		if self.docstatus != 1:
			frappe.throw(_("Only a submitted transaction can be reversed."))
		if frappe.db.exists("Transaction", {"reversal_of": self.name, "docstatus": 1}):
			frappe.throw(_("This transaction has already been reversed."))

		reversal = frappe.copy_doc(self)
		reversal.reversal_of = self.name
		reversal.journal_entry = None
		reversal.amended_from = None

		if self.transaction_type in ACCOUNT_TO_ACCOUNT_TYPES:
			reversal.account, reversal.destination_account = (
				self.destination_account,
				self.account,
			)
			if self.transaction_type == "Credit Card Payment":
				# Undoing a card payment means Dr bank / Cr card — money going back the other
				# way. That is not itself a card payment, which always debits the card, so the
				# swapped pair would be refused as "destination is a Bank, not a liability".
				# It is a settlement between two balance-sheet accounts: a Transfer.
				reversal.transaction_type = "Transfer"
		elif self.transaction_type == "Expense":
			reversal.transaction_type = "Refund"
		elif self.transaction_type == "Refund":
			reversal.transaction_type = "Expense"
		elif self.transaction_type == "Income":
			frappe.throw(_("Reversing an Income is not supported yet. Cancel the transaction instead."))

		reversal.insert()
		reversal.submit()
		return reversal.name
