# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import settings as settings_service
from moneytracker.money_tracker.services import subscriptions


class MoneySubscription(Document):
	"""An arrangement with a vendor: the terms, never the money.

	The boundary against `Money Recurring Transaction` is in `services/subscriptions.py`'s
	docstring and is the reason this doctype exists. A plan is the money and the calendar; a
	subscription is who you are paying, on what tier, until when, and what you have to do to
	get out of it. It **posts nothing** — there is no `generate()` here and no strategy — and
	it names the plan that does.

	Validation sits between a bill's and a plan's. A plan runs unattended, so it is checked
	hard at Save because whatever is wrong with it is wrong every month. A bill is checked
	lightly, because refusing to write down that money is owed until the category is filled in
	gets in the way at the one moment that matters. A subscription is somewhere between: it
	renews unattended, so the dates and the frequency are checked properly, but the category
	and the account are optional, because somebody adding a trial they signed up for five
	minutes ago does not yet know which card it will land on.
	"""

	def before_insert(self):
		if not self.tracker:
			self.tracker = settings_service.get_default_tracker()
		if not self.currency:
			self.currency = (
				frappe.db.get_value("Tracker", self.tracker, "base_currency")
				or settings_service.get_base_currency()
			)
		if not self.start_date:
			self.start_date = today()

	def validate(self):
		subscriptions.get_frequency(self.billing_frequency)
		self.validate_unique_name_in_tracker()
		self.validate_amount()
		self.validate_window()
		self.validate_links()
		self.sync_price_history()

	def validate_unique_name_in_tracker(self):
		"""Unique per tracker, like every other master in this app.

		Unlike `Money Bill`, which only refuses a second *unpaid* one: a bill is a claim that
		arrives again next month, while a subscription is one continuing arrangement. Two rows
		called Netflix mean somebody entered it twice, and every spend figure then counts it
		twice.
		"""
		duplicate = frappe.db.exists(
			"Money Subscription",
			{
				"subscription_name": self.subscription_name,
				"tracker": self.tracker,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("This tracker already has a subscription called {0}.").format(
					frappe.bold(self.subscription_name)
				)
			)

	def validate_amount(self):
		if flt(self.amount) <= 0:
			frappe.throw(
				_(
					"Price must be greater than zero. A free tier has no price to track and no renewal to warn about."
				)
			)
		if int(self.notice_period_days or 0) < 0:
			frappe.throw(_("Notice Period cannot be negative."))

	def validate_window(self):
		"""The three dates have one order: started, trial ended, ends on.

		Checked properly rather than lightly, because everything derived hangs off them — a
		trial ending before the subscription started would anchor the billing calendar before
		the arrangement existed and put every renewal date in the wrong place.
		"""
		start = getdate(self.start_date)

		if self.trial_end_date and getdate(self.trial_end_date) < start:
			frappe.throw(_("The trial cannot end before the subscription started."))
		if self.end_date:
			end = getdate(self.end_date)
			if end < start:
				frappe.throw(_("Ends On cannot be before Started."))
			if self.trial_end_date and end < getdate(self.trial_end_date):
				frappe.throw(_("Ends On cannot be before the trial ends."))

	def validate_links(self):
		for fieldname, doctype in (
			("category", "Category"),
			("account", "Money Account"),
			("vendor", "Money Merchant"),
			("recurring_transaction", "Money Recurring Transaction"),
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
				frappe.throw(
					_("{0} is an income category. A subscription is money going out.").format(category_name)
				)

		self.validate_plan()

	def validate_plan(self):
		"""One plan pays one subscription.

		The plan's amount is what leaves the account, so two subscriptions naming it would
		each claim the same money and `Subscription Spend` would count it twice. A *mismatch*
		between the plan's amount and the price is not refused, though — see
		`subscriptions._plan_agrees`: knowing about a rise before updating the standing order
		is the normal order of events, not a mistake.
		"""
		if not self.recurring_transaction:
			return

		transaction_type = frappe.db.get_value(
			"Money Recurring Transaction", self.recurring_transaction, "transaction_type"
		)
		if transaction_type != "Expense":
			frappe.throw(
				_("{0} is a {1} plan. A subscription is paid, not received.").format(
					self.recurring_transaction, transaction_type
				)
			)

		claimed_by = frappe.db.exists(
			"Money Subscription",
			{"recurring_transaction": self.recurring_transaction, "name": ["!=", self.name or ""]},
		)
		if claimed_by:
			frappe.throw(
				_(
					"That plan already pays {0}. One plan pays one subscription, or its money is counted twice."
				).format(
					frappe.bold(frappe.db.get_value("Money Subscription", claimed_by, "subscription_name"))
				)
			)

	# --- price history ------------------------------------------------------------------

	def sync_price_history(self):
		"""Keep `amount` and the price table saying the same thing, and record the rise.

		`Money Subscription Price` is the source of truth for price — nothing in the ledger
		can be — and `amount` is a cache of the current one, the same relationship
		`Money Account.current_balance` has with `GL Entry`. So there is exactly one rule, and
		it is about which of the two the user just touched:

		* the **field** changed → they are telling us the price today, so the history records
		  it, dated today;
		* only the **table** changed → they are correcting the record, so the field is brought
		  back into line with the newest row.

		Which means the ordinary way to record a price rise is to type the new price over the
		old one. Nobody has to know the history exists for it to be right.
		"""
		before = self.get_doc_before_save()
		field_changed = bool(before) and flt(before.amount) != flt(self.amount)

		if not self.price_history:
			self.append(
				"price_history",
				{
					"effective_from": self.start_date,
					"amount": flt(self.amount),
					"note": _("Opening price"),
				},
			)
			return

		self.validate_price_rows()

		if field_changed:
			self.record_price(flt(self.amount))
		else:
			# The newest row wins. A row added by hand for a rise being recorded after the fact
			# lands at the bottom of the grid, not in date order, which is why this reads the
			# sorted history rather than the last child row.
			self.amount = subscriptions.price_rows(self)[-1].amount

	def validate_price_rows(self):
		seen = set()
		for row in self.price_history:
			if flt(row.amount) <= 0:
				frappe.throw(_("A recorded price must be greater than zero."))
			date = getdate(row.effective_from)
			if date in seen:
				frappe.throw(
					_("There are two prices dated {0}. A subscription cost one thing on a given day.").format(
						date
					)
				)
			seen.add(date)

	def record_price(self, amount, effective_from=None, note=None):
		"""Put `amount` into the history, in place if that day already has a price.

		Dated today rather than at the start date, because a price you are typing now is the
		price now — back-dating it would rewrite what the subscription cost in months that have
		already been reported. The exception is a subscription that has not started yet, where
		today is before any of it applies.
		"""
		when = getdate(effective_from or max(getdate(today()), getdate(self.start_date)))

		for row in self.price_history:
			if getdate(row.effective_from) == when:
				row.amount = flt(amount)
				if note:
					row.note = note
				return row

		return self.append("price_history", {"effective_from": when, "amount": flt(amount), "note": note})

	# --- actions -----------------------------------------------------------------------

	@frappe.whitelist()
	def record_price_change(self, amount, effective_from=None, note=None):
		"""Record a price rise from the form, dated whenever it actually happened.

		The same thing typing over the price does, with one addition: a date. A letter saying
		the price went up on the 1st arrives on the 9th, and dating the change on the 9th would
		make the app disagree with the vendor about what the last eight days cost.
		"""
		amount = flt(amount)
		if amount <= 0:
			frappe.throw(_("A recorded price must be greater than zero."))

		self.record_price(amount, effective_from, note)
		self.amount = subscriptions.price_rows(self)[-1].amount
		self.save()
		return subscriptions.measure(self)

	@frappe.whitelist()
	def cancel_subscription(self, effective_date=None):
		"""Stop it, from a date. Keeps the terms and the price history intact.

		`status` becomes the user's decision and `end_date` becomes the fact, which is what
		makes `Expired` derivable afterwards: a subscription cancelled in March with an end
		date in June is still being paid for until June, and saying otherwise would understate
		three months of spend.
		"""
		effective_date = getdate(effective_date or today())
		if effective_date < getdate(self.start_date):
			frappe.throw(_("It cannot end before it started."))

		self.end_date = effective_date
		self.status = "Cancelled"
		self.save()
		return subscriptions.measure(self)
