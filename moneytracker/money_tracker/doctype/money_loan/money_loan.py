# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from moneytracker.money_tracker.services import coa, loans
from moneytracker.money_tracker.services import settings as settings_service

# The terms an amortisation table is a function of. Change any one of them and the schedule is
# a different schedule — which is why they freeze together, and why `emi` is not among them: it
# is derived from the rest.
TERM_FIELDS = (
	"principal",
	"interest_rate",
	"interest_type",
	"tenure_months",
	"start_date",
	"emi_override",
)


class MoneyLoan(Document):
	"""A loan: its terms, its schedule, and nothing about the money.

	The boundary is in `services/loans.py`'s docstring. The short version: the ledger says what
	is still owed, this document says what was agreed, and `posting/strategies/loan_payment.py`
	turns one payment into three legs. A `Money Goal` of type Debt Payoff keeps the simple case
	— a card you pay down as you can — because a loan's payments are fixed in advance and each
	one is two things at once.

	Validation is the strictest in the app, and deliberately so. A bill is checked lightly
	because refusing to write down that money is owed gets in the way at the one moment that
	matters. A loan is the opposite: it is entered once, from a piece of paper, and then relied
	on for years. Every field it amortises from is required, and every one of them is frozen the
	moment real money has moved against it.
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
		self.validate_unique_name_in_tracker()
		self.validate_terms()
		self.validate_accounts()
		self.validate_terms_are_frozen()
		self.refresh_schedule()

	def validate_unique_name_in_tracker(self):
		duplicate = frappe.db.exists(
			"Money Loan",
			{"loan_name": self.loan_name, "tracker": self.tracker, "name": ["!=", self.name or ""]},
		)
		if duplicate:
			frappe.throw(_("This tracker already has a loan called {0}.").format(frappe.bold(self.loan_name)))

	def validate_terms(self):
		if self.direction not in loans.DIRECTIONS:
			frappe.throw(_("Direction must be one of: {0}.").format(", ".join(loans.DIRECTIONS)))
		if self.interest_type not in loans.INTEREST_TYPES:
			frappe.throw(_("Interest Type must be one of: {0}.").format(", ".join(loans.INTEREST_TYPES)))
		if flt(self.principal) <= 0:
			frappe.throw(_("Principal must be greater than zero."))
		if flt(self.interest_rate) < 0:
			frappe.throw(_("Interest Rate cannot be negative."))
		if int(self.tenure_months or 0) < 1 or int(self.tenure_months) > loans.MAX_TENURE:
			frappe.throw(_("Tenure must be between 1 and {0} instalments.").format(loans.MAX_TENURE))
		if flt(self.emi_override) < 0:
			frappe.throw(_("The lender's instalment cannot be negative."))

	def validate_accounts(self):
		"""The loan account and the interest category, each on the side the direction implies.

		This is where `direction` earns its place as a field rather than a note. Money borrowed
		sits on a liability and its interest is expense; money lent sits on an asset and its
		interest is income. Get either the wrong way round and the posting still balances — it
		is three legs whichever way you sign it — and the Balance Sheet quietly says the
		household owns what it owes. So it is checked here, at save, and not left to the engine.
		"""
		account = frappe.db.get_value(
			"Money Account",
			self.loan_account,
			["tracker", "account_type", "account_name"],
			as_dict=True,
		)
		if not account:
			frappe.throw(_("Loan Account does not exist."))
		if account.tracker and account.tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(account.account_name))

		is_liability = coa.is_liability(account.account_type)
		if self.direction == loans.BORROWED and not is_liability:
			frappe.throw(
				_(
					"{0} is a {1}. Money you have borrowed is a liability — use an account of type Loan."
				).format(account.account_name, account.account_type)
			)
		if self.direction == loans.LENT and is_liability:
			frappe.throw(
				_(
					"{0} is a liability. Money you have lent is owed *to* you, so it belongs on an asset account."
				).format(account.account_name)
			)

		category = frappe.db.get_value(
			"Category",
			self.interest_category,
			["tracker", "category_type", "is_group", "category_name"],
			as_dict=True,
		)
		if not category:
			frappe.throw(_("Interest Category does not exist."))
		if category.tracker and category.tracker != self.tracker:
			frappe.throw(_("{0} belongs to another tracker.").format(category.category_name))
		if category.is_group:
			frappe.throw(
				_("{0} is a group category. Charge the interest to one of its sub-categories.").format(
					category.category_name
				)
			)

		expected = "Expense" if self.direction == loans.BORROWED else "Income"
		if category.category_type != expected:
			frappe.throw(
				_("Interest on money {0} is {1}, so {2} must be an {1} category.").format(
					self.direction.lower(), expected.lower(), category.category_name
				)
			)

		if self.counterparty:
			owner = frappe.db.get_value("Money Merchant", self.counterparty, "tracker")
			if owner and owner != self.tracker:
				frappe.throw(_("{0} belongs to another tracker.").format(self.counterparty))

	def validate_terms_are_frozen(self):
		"""Once a payment has been posted, the terms cannot move.

		This is the rule that makes a *stored* schedule safe in an app that otherwise derives
		everything. A schedule is a pure function of the terms, so keeping a copy would normally
		be the drift this codebase refuses to allow — but a copy of something that cannot change
		cannot drift. It is also right in its own terms: a loan is not renegotiated by editing a
		field. Close it and open the new one, and the history of what was actually paid against
		the old terms survives.
		"""
		before = self.get_doc_before_save()
		if not before:
			return

		changed = [field for field in TERM_FIELDS if self._differs(before, field)]
		if not changed:
			return

		posted = loans.payments(self.name)
		if posted:
			frappe.throw(
				_(
					"{0} payments have already been posted against this loan, so its terms are fixed. Close this loan and open a new one on the new terms."
				).format(len(posted)),
				title=_("Terms Are Frozen"),
			)

	def _differs(self, before, field):
		old, new = before.get(field), self.get(field)
		if field == "start_date":
			return getdate(old) != getdate(new)
		if field == "interest_type":
			return old != new
		return flt(old) != flt(new)

	def refresh_schedule(self):
		"""Rebuild the amortisation table, and stamp the instalment it implies.

		Unconditional, because it is cheap and because the alternative is a stored table that is
		correct only if every path that could have touched a term remembered to say so.
		`validate_terms_are_frozen` above is what makes it safe to do on every save: after the
		first payment the terms cannot have changed, so the rebuilt table is the same table.
		"""
		rows = loans.build_schedule(
			principal=self.principal,
			annual_rate=self.interest_rate,
			tenure_months=self.tenure_months,
			start_date=self.start_date,
			interest_type=self.interest_type,
			emi=self.emi_override,
		)

		self.emi = rows[0].payment
		self.set("schedule", [])
		for row in rows:
			self.append("schedule", row.as_row())

	# --- actions -----------------------------------------------------------------------

	@frappe.whitelist()
	def disburse(self, account, on_date=None):
		"""Put the principal on the books. Returns the transaction that did it.

		**A plain Transfer, and no new strategy**, because that is honestly what a disbursal is:
		a movement between two balance-sheet accounts. Borrowing credits the loan liability — you
		now owe it — and debits the account the money landed in; lending does the opposite.
		Neither is income and neither is expense, since nobody is richer or poorer for having
		borrowed, and that is exactly the invariant `strategies/transfer.py` already states.

		Until this has happened the loan has no debt to measure, and the outcome word says so.
		A loan account sitting at zero looks identical to one that has been paid off, and
		guessing which by reading the schedule instead would be the drift this app refuses.
		"""
		if self.disbursal_transaction:
			frappe.throw(
				_("{0} has already been disbursed by {1}.").format(self.loan_name, self.disbursal_transaction)
			)
		if account == self.loan_account:
			frappe.throw(_("The principal has to move between two different accounts."))

		# Borrowed: out of the liability, into the account it landed in. Lent: the other way.
		source, destination = (
			(self.loan_account, account) if self.direction == loans.BORROWED else (account, self.loan_account)
		)

		transaction = frappe.get_doc(
			{
				"doctype": "Transaction",
				"tracker": self.tracker,
				"date": getdate(on_date or self.start_date),
				"transaction_type": "Transfer",
				"amount": flt(self.principal),
				"currency": self.currency,
				"account": source,
				"destination_account": destination,
				"merchant": self.counterparty,
				"notes": _("Principal of {0}").format(self.loan_name),
			}
		)
		transaction.insert()
		transaction.submit()

		self.db_set("disbursal_transaction", transaction.name)
		return {"transaction": transaction.name, "amount": flt(self.principal)}

	@frappe.whitelist()
	def post_instalment(self, from_account=None, amount=None, paid_on=None):
		"""Post the next instalment as a `Loan Payment`, split into principal and interest.

		The interest comes off the **schedule**, not off a proportion of whatever was paid: the
		agreement says what this month's interest is, and paying a round number does not change
		it. Anything paid above the scheduled instalment therefore goes to principal, which is
		exactly what a part-prepayment is.
		"""
		if self.status == "Closed":
			frappe.throw(_("{0} is closed.").format(self.loan_name))
		if not self.disbursal_transaction:
			frappe.throw(
				_("Disburse {0} first, so the principal is on the books before anything is repaid.").format(
					self.loan_name
				)
			)

		instalment = loans.next_instalment(self)
		if not instalment:
			frappe.throw(_("Every instalment on this loan has been paid."))

		amount = flt(amount) if amount else instalment.payment
		if amount <= 0:
			frappe.throw(_("How much was paid?"))
		if not from_account:
			frappe.throw(
				_("Which account was it paid from?")
				if self.direction == loans.BORROWED
				else _("Which account did the repayment arrive in?")
			)

		interest = min(flt(instalment.interest), amount)
		transaction = frappe.get_doc(
			{
				"doctype": "Transaction",
				"tracker": self.tracker,
				"date": getdate(paid_on or today()),
				"transaction_type": "Loan Payment",
				"amount": amount,
				"currency": self.currency,
				"account": from_account,
				"loan": self.name,
				"interest_amount": interest,
				"merchant": self.counterparty,
				"notes": _("Instalment {0} of {1}").format(instalment.instalment, len(self.schedule)),
			}
		)
		transaction.insert()
		transaction.submit()

		return {
			"transaction": transaction.name,
			"instalment": instalment.instalment,
			"interest": interest,
			"principal": flt(amount - interest),
		}

	@frappe.whitelist()
	def close(self):
		"""Mark it settled. Refuses while the ledger still says something is owed.

		A loan that reads closed while its account carries a balance is worse than one that
		reads open: every debt figure in the app would understate what the household owes, and
		nothing would say why. Write off the remainder as an Adjustment first, or pay it.
		"""
		measured = loans.measure(self)
		if flt(measured.outstanding) > 0:
			frappe.throw(
				_("{0} still has {1} outstanding on {2}. Settle or write off the balance first.").format(
					self.loan_name, measured.outstanding, measured.loan_account
				)
			)

		self.status = "Closed"
		self.save()
		return loans.measure(self)

	def on_trash(self):
		"""Deleting a loan keeps the payments and clears their back-link.

		The same choice a plan and a bill make: the money really moved, and only the record of
		what was agreed is going away.
		"""
		for row in frappe.get_all("Transaction", filters={"loan": self.name}, pluck="name"):
			frappe.db.set_value("Transaction", row, "loan", None, update_modified=False)
