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
from frappe.utils import flt, getdate, nowdate

from moneytracker.money_tracker.services import settings as settings_service


def unique(prefix):
	"""A name no other test will collide with.

	Matters more than it looks: `coa.get_or_create_ledger_account` matches an existing
	ERPNext Account on `{company, account_name, is_group: 0}` and deliberately ignores the
	parent, so two fixtures sharing a name silently share one ledger account.
	"""
	return f"{prefix} {frappe.generate_hash(length=6)}"


def posting_date():
	"""A date inside the site's Fiscal Year.

	Resolved rather than hardcoded: ERPNext throws for a posting outside a Fiscal Year, and
	this site has exactly one (2026-04-01 → 2027-03-31), so a literal date would start
	failing the day the site rolls over.
	"""
	years = frappe.get_all(
		"Fiscal Year",
		fields=["year_start_date", "year_end_date"],
		order_by="year_start_date desc",
		limit=1,
	)
	if not years:
		raise RuntimeError("No Fiscal Year on this site — every posting test would fail.")

	start, end = getdate(years[0].year_start_date), getdate(years[0].year_end_date)
	today = getdate(nowdate())
	return today if start <= today <= end else start


# --- factories -------------------------------------------------------------------------
# `tracker` and `currency` are `reqd` in the JSON but filled server-side in before_insert /
# before_validate, so the API path may omit them. Desk cannot — see CLAUDE.md.


def make_tracker(**kwargs):
	kwargs.setdefault("tracker_name", unique("Tracker"))
	kwargs.setdefault("tracker_type", "Personal")
	doc = frappe.get_doc({"doctype": "Tracker", **kwargs})
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
