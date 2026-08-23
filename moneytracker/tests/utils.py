# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Shared harness for the Phase 1 suite.

Two framework facts shape everything here:

1. `FrappeTestCase` rolls back once per **class** (`addClassCleanup(_rollback_db)`), not per
   test. Nothing may assume a clean table between two tests in the same class, so every
   factory mints a unique name and anything global — a Money Settings flag, the session
   user — is restored by a context manager rather than by the rollback.
2. `frappe.get_cached_doc` reads through Redis, which a rollback does not touch. Both
   `PostingContext` and `settings_service.get_settings()` use it, so a document mutated in a
   test has to be evicted explicitly.
"""

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, get_first_day, getdate, nowdate

from moneytracker.money_tracker.services import settings as settings_service


def unique(prefix):
	"""A name no other test will collide with.

	Matters more than it looks: `coa.get_or_create_ledger_account` matches an existing
	ERPNext Account on `{company, account_name, is_group: 0}` and deliberately ignores the
	parent, so two fixtures sharing a name silently share one ledger account.
	"""
	return f"{prefix} {frappe.generate_hash(length=6)}"


def posting_date():
	"""A date inside a Fiscal Year, preferring today.

	Resolved rather than hardcoded: ERPNext throws for a posting outside a Fiscal Year, so a
	literal date would start failing the day the site rolls over.

	Today wins whenever *any* Fiscal Year covers it. Picking the newest year instead looks
	equivalent and is not: ERPNext's own test records seed `_Test Fiscal Year` rows out to
	2050, and a fixture dated 2050-01-01 silently stops matching anything a test compares
	against `today()` — which is what every dashboard figure defaults to.
	"""
	today = getdate(nowdate())
	covering = frappe.db.exists(
		"Fiscal Year",
		{"year_start_date": ["<=", today], "year_end_date": [">=", today], "disabled": 0},
	)
	if covering:
		return today

	years = frappe.get_all(
		"Fiscal Year",
		filters={"disabled": 0},
		fields=["year_start_date"],
		order_by="year_start_date desc",
		limit=1,
	)
	if not years:
		raise RuntimeError("No Fiscal Year on this site — every posting test would fail.")
	return getdate(years[0].year_start_date)


# --- factories -------------------------------------------------------------------------
# `tracker` and `currency` are `reqd` in the JSON but filled server-side in before_insert /
# before_validate, so the API path may omit them. Desk cannot — see CLAUDE.md.


def make_tracker(seed_categories=False, **kwargs):
	"""A tracker with no categories unless asked.

	`Tracker.after_insert` seeds the default tree in real use. Fixtures opt out: ~40 extra
	rows per tracker would dominate the suite's runtime, and they would sit in the way of
	every test that counts the categories it created itself.
	"""
	kwargs.setdefault("tracker_name", unique("Tracker"))
	kwargs.setdefault("tracker_type", "Personal")
	doc = frappe.get_doc({"doctype": "Tracker", **kwargs})
	doc.flags.skip_default_categories = not seed_categories
	doc.insert(ignore_permissions=True)
	return doc


def make_account(tracker=None, **kwargs):
	kwargs.setdefault("account_name", unique("Account"))
	kwargs.setdefault("account_type", "Bank")
	doc = frappe.get_doc({"doctype": "Money Account", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_category(tracker=None, **kwargs):
	kwargs.setdefault("category_name", unique("Category"))
	kwargs.setdefault("category_type", "Expense")
	doc = frappe.get_doc({"doctype": "Category", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_transaction(transaction_type, amount, account, submit=True, **kwargs):
	kwargs.setdefault("date", posting_date())
	doc = frappe.get_doc(
		{
			"doctype": "Transaction",
			"transaction_type": transaction_type,
			"amount": amount,
			"account": account,
			**kwargs,
		}
	)
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_goal(tracker=None, **kwargs):
	"""A goal on `tracker`. Savings by default, so a target account has to be passed with it.

	`target_amount` is filled for every type except the one measured in percent, where it is
	`target_percent` that carries the number and a target amount is refused.
	"""
	kwargs.setdefault("goal_name", unique("Goal"))
	kwargs.setdefault("goal_type", "Savings")
	kwargs.setdefault("start_date", posting_date())
	if kwargs["goal_type"] == "Savings Rate Target":
		kwargs.setdefault("target_percent", 30)
	else:
		kwargs.setdefault("target_amount", 100000)

	doc = frappe.get_doc({"doctype": "Money Goal", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_budget(tracker=None, **kwargs):
	"""An envelope on `tracker`. Monthly and 10,000 unless told otherwise.

	`start_date` defaults to the *first day of the posting month* rather than to today, so a
	budget made by a test already covers the transactions that test posts — a budget starting
	today would measure from today and read zero however much had been spent this month.
	"""
	kwargs.setdefault("budget_name", unique("Budget"))
	kwargs.setdefault("period", "Monthly")
	kwargs.setdefault("budget_amount", 10000)
	kwargs.setdefault("start_date", get_first_day(posting_date()))

	doc = frappe.get_doc({"doctype": "Money Budget", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_payment_method(**kwargs):
	"""A payment method. Site-wide rather than per-tracker, unlike everything around it —
	the ways of paying are a small closed set, not a household's own list."""
	kwargs.setdefault("method_name", unique("Method"))

	doc = frappe.get_doc({"doctype": "Money Payment Method", **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_bill(tracker=None, **kwargs):
	"""A bill on `tracker`. Unpaid, due today, 1,000 unless told otherwise."""
	kwargs.setdefault("bill_name", unique("Bill"))
	kwargs.setdefault("amount", 1000)
	kwargs.setdefault("due_date", posting_date())

	doc = frappe.get_doc({"doctype": "Money Bill", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_receipt(tracker=None, **kwargs):
	"""A receipt on `tracker`. Carries an image unless told otherwise, since a receipt with
	neither a file nor an image is refused."""
	kwargs.setdefault("image", f"/files/{unique('receipt')}.png")
	kwargs.setdefault("title", unique("Receipt"))

	doc = frappe.get_doc({"doctype": "Money Receipt", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_merchant(tracker=None, **kwargs):
	"""A merchant on `tracker`. Names are minted unique because they are unique per tracker."""
	kwargs.setdefault("merchant_name", unique("Merchant"))

	doc = frappe.get_doc({"doctype": "Money Merchant", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_tag(tracker=None, **kwargs):
	"""A tag on `tracker`. Names are minted unique because they are unique per tracker."""
	kwargs.setdefault("tag_name", unique("Tag"))

	doc = frappe.get_doc({"doctype": "Money Tag", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def tag_transaction(transaction, *tags):
	"""Put `tags` on an already-submitted transaction and return it reloaded.

	Goes through `save()` rather than `db_set` on purpose: `tags` is the only field on
	Transaction carrying `allow_on_submit`, and the controller re-validates it in
	`on_update_after_submit`. A test that wrote the rows directly would skip the rule it is
	usually there to exercise.
	"""
	doc = transaction if hasattr(transaction, "doctype") else frappe.get_doc("Transaction", transaction)
	doc.set("tags", [{"tag": tag.name if hasattr(tag, "name") else tag} for tag in tags])
	doc.save(ignore_permissions=True)
	return doc


def make_recurring(tracker=None, **kwargs):
	"""A standing plan on `tracker`. A monthly 1,000 expense unless told otherwise.

	`start_date` defaults to **today** rather than to the first of the month, unlike
	`make_budget`: a plan never posts for a date before it was created
	(`recurring.effective_from`), so a back-dated start would produce a fixture that looks
	overdue and generates nothing. A test that wants catch-up moves `creation` instead — see
	`backdate_plan`.
	"""
	kwargs.setdefault("recurring_name", unique("Plan"))
	kwargs.setdefault("transaction_type", "Expense")
	kwargs.setdefault("frequency", "Monthly")
	kwargs.setdefault("amount", 1000)
	kwargs.setdefault("start_date", posting_date())

	doc = frappe.get_doc({"doctype": "Money Recurring Transaction", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def backdate_plan(plan, creation):
	"""Move a plan's `creation` back, so generation may reach dates before the test began.

	`effective_from` is deliberately the later of the start date and the day the plan was
	written down, which means a freshly inserted fixture can never generate history. Every
	catch-up test therefore has to say, explicitly, that this plan existed earlier.
	"""
	frappe.db.set_value("Money Recurring Transaction", plan.name, "creation", creation, update_modified=False)
	plan.reload()
	return plan


def make_subscription(tracker=None, **kwargs):
	"""A subscription on `tracker`. A monthly 499 billed from today unless told otherwise.

	`start_date` defaults to **today**, like `make_recurring` and unlike `make_budget`: every
	renewal date is counted from the start date, so a fixture back-dated by a month would open
	with its next renewal already behind it.
	"""
	kwargs.setdefault("subscription_name", unique("Subscription"))
	kwargs.setdefault("amount", 499)
	kwargs.setdefault("billing_frequency", "Monthly")
	kwargs.setdefault("start_date", posting_date())

	doc = frappe.get_doc({"doctype": "Money Subscription", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_loan(tracker=None, **kwargs):
	"""A loan on `tracker`. 100,000 borrowed at 12% over 12 monthly instalments.

	`loan_account` and `interest_category` are required and have to be on the side the
	direction implies — a liability and an expense category for something borrowed — so a
	caller passes them rather than having them guessed at.

	`start_date` defaults to **today**, so instalment one falls due next month and a fresh
	fixture is `On Schedule` rather than already behind. A test that wants arrears moves the
	start date back instead.
	"""
	kwargs.setdefault("loan_name", unique("Loan"))
	kwargs.setdefault("direction", "Borrowed")
	kwargs.setdefault("principal", 100000)
	kwargs.setdefault("interest_rate", 12)
	kwargs.setdefault("interest_type", "Reducing Balance")
	kwargs.setdefault("tenure_months", 12)
	kwargs.setdefault("start_date", posting_date())

	doc = frappe.get_doc({"doctype": "Money Loan", "tracker": tracker, **kwargs})
	doc.insert(ignore_permissions=True)
	return doc


def make_user(roles=("Finance User",)):
	"""A user with only the restricted roles, so the permission hooks actually apply."""
	email = f"mt-{frappe.generate_hash(length=8)}@example.com"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "MT Test",
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


# --- ledger inspection -----------------------------------------------------------------


def gl_rows(voucher_no, include_cancelled=True):
	filters = {"voucher_no": voucher_no}
	if not include_cancelled:
		filters["is_cancelled"] = 0
	return frappe.get_all(
		"GL Entry",
		filters=filters,
		fields=["account", "debit", "credit", "is_cancelled", "tracker", "voucher_type"],
		order_by="account, debit desc",
	)


def je_of(transaction):
	return frappe.get_doc("Journal Entry", transaction.journal_entry)


def root_types_touched(voucher_no):
	"""The set of ERPNext root types the voucher's live GL rows land on.

	Cheaper and less brittle than scraping a report, and it is the same question the P&L
	answers: did this movement reach an Income or Expense account?
	"""
	rows = frappe.get_all("GL Entry", filters={"voucher_no": voucher_no, "is_cancelled": 0}, pluck="account")
	if not rows:
		return set()
	return set(frappe.get_all("Account", filters={"name": ["in", rows]}, pluck="root_type"))


def ledger_movement(ledger_account, tracker=None):
	"""Signed debit - credit over live GL rows, the raw figure balances.py derives from."""
	filters = {"account": ledger_account, "is_cancelled": 0}
	if tracker:
		filters["tracker"] = tracker
	totals = frappe.get_all(
		"GL Entry", filters=filters, fields=["SUM(debit) as debit", "SUM(credit) as credit"]
	)[0]
	return flt(totals.debit) - flt(totals.credit)


# --- scoped mutation -------------------------------------------------------------------


@contextmanager
def money_setting(**fields):
	"""Temporarily change Money Settings and evict it from the document cache both ways.

	The class-level rollback would restore the row eventually, but every test after this one
	in the same class would see the changed value until then.
	"""
	settings = frappe.get_doc("Money Settings")
	previous = {field: settings.get(field) for field in fields}

	def apply(values):
		for field, value in values.items():
			frappe.db.set_single_value("Money Settings", field, value)
		frappe.clear_document_cache("Money Settings", "Money Settings")

	apply(fields)
	try:
		yield
	finally:
		apply(previous)


@contextmanager
def as_user(user):
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


class MoneyTrackerTestCase(FrappeTestCase):
	"""Base class: resolves the posting date once and guarantees a cold cache afterwards."""

	@classmethod
	def setUpClass(cls):
		# Added before super() so it runs *after* FrappeTestCase's rollback (cleanups are
		# LIFO). Rolling back leaves the rolled-back documents in the Redis document cache,
		# where the next class would still read them.
		cls.addClassCleanup(frappe.clear_cache)
		super().setUpClass()

		cls.date = posting_date()
		cls.company = settings_service.get_company()
		cls.precision = frappe.get_precision("Journal Entry Account", "debit") or 2

	def assertMoneyEqual(self, first, second, msg=None):
		"""Compare with the app's own idiom: flt() at the ledger's precision (CLAUDE.md)."""
		self.assertEqual(flt(first, self.precision), flt(second, self.precision), msg=msg)
