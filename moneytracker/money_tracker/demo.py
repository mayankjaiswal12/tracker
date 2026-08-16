# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Demo data: a tracker with a few months of real-looking money in it (spec §87).

An empty site cannot be shown, only described — every dashboard card reads zero, every
chart says "No Data" and the ERPNext reports come back blank. This seeds one household's
finances so the whole app can be demonstrated in the state it is meant to be used in.

	bench --site tracker.localhost execute moneytracker.money_tracker.demo.setup_demo_data
	bench --site tracker.localhost execute moneytracker.money_tracker.demo.clear_demo_data

Two properties are deliberate:

* **Deterministic.** No randomness anywhere, so the figures are reproducible and can be
  written into documentation and checked by eye.
* **Removable.** `clear_demo_data` takes the site back to where it started. A demo you
  cannot delete is worse than no demo.

Everything is scoped to one Tracker, which is what isolates it from real books on this
shared Company — the same mechanism that isolates one user from another.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, fmt_money, get_first_day, get_last_day, getdate, today

from moneytracker.money_tracker.services import balances
from moneytracker.money_tracker.services import settings as settings_service

# Written into the tracker's description. `clear_demo_data` refuses to touch a tracker
# without it, so pointing the teardown at a real tracker called "Demo" cannot wipe it.
DEMO_MARKER = "moneytracker:demo-data"

DEMO_TRACKER_NAME = "Demo Household"
DEFAULT_MONTHS = 6

# (group_name, group_type) — Money Account Group is a site-wide tree, not tracker-scoped,
# so these are only created when the site has none and only removed if nothing else uses them.
ACCOUNT_GROUPS = (
	("Banks", "Asset"),
	("Cards", "Liability"),
	("Cash", "Asset"),
)

# (method_name, applies_to_account_type) — also site-wide.
PAYMENT_METHODS = (
	("UPI", "Bank"),
	("Bank Transfer", "Bank"),
	("Credit Card", "Credit Card"),
	("Cash", "Cash"),
)

# (account_name, account_type, account_group, institution)
DEMO_ACCOUNTS = (
	("HDFC Bank", "Bank", "Banks", "HDFC Bank"),
	("Emergency Fund", "Savings", "Banks", "HDFC Bank"),
	("HDFC Credit Card", "Credit Card", "Cards", "HDFC Bank"),
	("Wallet", "Cash", "Cash", None),
)

# One month of a salaried household, in day order. Accounts and categories are named, not
# linked — they are resolved against this tracker when the row is posted, so the category
# names here must stay in step with `services/categories.DEFAULT_CATEGORIES`.
#
# The order matters: salary lands on the 1st and the cash withdrawal precedes the cash
# spending, so no account is ever driven negative. (`Money Settings.allow_negative_balance`
# defaults to 1, so nothing would stop it — it would just look wrong.)
MONTHLY = (
	{
		"day": 1,
		"transaction_type": "Income",
		"amount": 120000,
		"account": "HDFC Bank",
		"category": "Salary",
		"payee": "Vidarbha Infotech",
		"payment_method": "Bank Transfer",
	},
	{
		"day": 2,
		"transaction_type": "Expense",
		"amount": 35000,
		"account": "HDFC Bank",
		"category": "Rent",
		"merchant": "Landlord",
		"payment_method": "Bank Transfer",
	},
	{
		"day": 3,
		"transaction_type": "Transfer",
		"amount": 15000,
		"account": "HDFC Bank",
		"destination_account": "Emergency Fund",
		"notes": "Monthly savings",
	},
	{
		"day": 5,
		"transaction_type": "Expense",
		"amount": 3200,
		"account": "HDFC Bank",
		"category": "Utilities",
		"merchant": "MSEDCL",
		"payment_method": "UPI",
	},
	{
		"day": 6,
		"transaction_type": "Expense",
		"amount": 1499,
		"account": "HDFC Credit Card",
		"category": "Subscriptions",
		"merchant": "Netflix, Spotify",
		"payment_method": "Credit Card",
	},
	{
		"day": 8,
		"transaction_type": "Expense",
		"amount": 6800,
		"account": "HDFC Credit Card",
		"category": "Groceries",
		"merchant": "DMart",
		"payment_method": "Credit Card",
	},
	{
		"day": 10,
		"transaction_type": "Transfer",
		"amount": 4000,
		"account": "HDFC Bank",
		"destination_account": "Wallet",
		"notes": "ATM withdrawal",
	},
	{
		"day": 12,
		"transaction_type": "Expense",
		"amount": 4500,
		"account": "HDFC Credit Card",
		"category": "Fuel",
		"merchant": "HP Petrol Pump",
		"payment_method": "Credit Card",
	},
	{
		"day": 15,
		"transaction_type": "Expense",
		"amount": 2400,
		"account": "Wallet",
		"category": "Restaurants",
		"merchant": "Local restaurants",
		"payment_method": "Cash",
	},
	{
		"day": 18,
		"transaction_type": "Expense",
		"amount": 5200,
		"account": "HDFC Bank",
		"category": "Groceries",
		"merchant": "Reliance Fresh",
		"payment_method": "UPI",
	},
	{
		"day": 20,
		"transaction_type": "Expense",
		"amount": 900,
		"account": "Wallet",
		"category": "Public Transport",
		"merchant": "Auto, bus",
		"payment_method": "Cash",
	},
	{
		"day": 22,
		"transaction_type": "Expense",
		"amount": 1100,
		"account": "HDFC Bank",
		"category": "Medicines",
		"merchant": "Apollo Pharmacy",
		"payment_method": "UPI",
	},
	{
		"day": 25,
		"transaction_type": "Credit Card Payment",
		"amount": 12000,
		"account": "HDFC Bank",
		"destination_account": "HDFC Credit Card",
		"notes": "Card bill",
	},
)

# Keyed by month index counting from the *oldest* month seeded, so the default six-month run
# tells a whole story: a laptop bought on the card, part of it returned, the card cleared,
# an insurance premium, some freelance income. A shorter run simply drops the later ones.
ONE_OFFS = {
	0: (
		{
			"day": 20,
			"transaction_type": "Income",
			"amount": 25000,
			"account": "HDFC Bank",
			"category": "Business & Freelance",
			"payee": "Freelance client",
			"payment_method": "Bank Transfer",
		},
	),
	1: (
		{
			"day": 14,
			"transaction_type": "Expense",
			"amount": 42000,
			"account": "HDFC Credit Card",
			"category": "Electronics",
			"merchant": "Croma",
			"notes": "Laptop",
			"payment_method": "Credit Card",
		},
	),
	2: (
		{
			"day": 9,
			"transaction_type": "Refund",
			"amount": 5200,
			"account": "HDFC Credit Card",
			"category": "Electronics",
			"merchant": "Croma",
			"notes": "Returned the docking station",
		},
		{
			"day": 16,
			"transaction_type": "Income",
			"amount": 1850,
			"account": "Emergency Fund",
			"category": "Interest",
			"payee": "HDFC Bank",
		},
	),
	3: (
		{
			"day": 11,
			"transaction_type": "Expense",
			"amount": 18000,
			"account": "HDFC Credit Card",
			"category": "Travel",
			"merchant": "IRCTC, hotel",
			"payment_method": "Credit Card",
		},
	),
	4: (
		{
			"day": 5,
			"transaction_type": "Expense",
			"amount": 14500,
			"account": "HDFC Bank",
			"category": "Health Insurance",
			"merchant": "HDFC Ergo",
			"notes": "Annual premium",
			"payment_method": "UPI",
		},
		{
			"day": 26,
			"transaction_type": "Credit Card Payment",
			"amount": 20000,
			"account": "HDFC Bank",
			"destination_account": "HDFC Credit Card",
			"notes": "Clearing the laptop",
		},
	),
}


# --- setup -------------------------------------------------------------------------------


def setup_demo_data(months=DEFAULT_MONTHS, user=None, tracker_name=DEMO_TRACKER_NAME):
	"""Create the demo tracker and post its transactions. Returns a summary dict.

	Refuses rather than adding a second copy of the *same* tracker; a different
	`tracker_name` seeds a second, independent one, which is how two sets of books on one
	shared Company can be demonstrated side by side.
	"""
	_refuse_in_tests()
	months = int(months)

	if _find_demo_tracker(tracker_name):
		frappe.throw(
			_("Demo tracker {0} is already on this site. Run clear_demo_data first.").format(
				frappe.bold(tracker_name)
			),
			title=_("Demo Already Set Up"),
		)

	settings_service.get_company()  # fails loudly here rather than on the first posting

	period = _demo_months(months)
	if not period:
		frappe.throw(
			_("No Fiscal Year covers any recent month, so nothing can be posted. Create one first."),
			title=_("No Fiscal Year"),
		)

	groups = _seed_account_groups()
	methods = _seed_payment_methods()
	tracker = _create_tracker(user, tracker_name)
	accounts = _create_accounts(tracker, groups)

	posted = 0
	skipped = 0
	for index, month_start in enumerate(period):
		for row in MONTHLY + ONE_OFFS.get(index, ()):
			if _post(tracker, accounts, methods, month_start, row):
				posted += 1
			else:
				skipped += 1

	return _summary(tracker, tracker_name, period, posted, skipped)


def _create_tracker(user, tracker_name):
	tracker = frappe.get_doc(
		{
			"doctype": "Tracker",
			"tracker_name": tracker_name,
			"tracker_type": "Family",
			"owner_user": user or frappe.session.user,
			# The marker is what makes the teardown safe — see clear_demo_data.
			"description": f"Sample data for demonstrating Money Tracker. {DEMO_MARKER}",
		}
	)
	# Not skipped: the seeded tree is part of what the demo shows off, and every category
	# named in MONTHLY / ONE_OFFS is one of its leaves.
	tracker.insert(ignore_permissions=True)
	return tracker.name


def _create_accounts(tracker, groups):
	accounts = {}
	for account_name, account_type, group, institution in DEMO_ACCOUNTS:
		doc = frappe.get_doc(
			{
				"doctype": "Money Account",
				"tracker": tracker,
				"account_name": account_name,
				"account_type": account_type,
				"account_group": groups.get(group),
				"institution": institution,
			}
		)
		doc.insert(ignore_permissions=True)
		accounts[account_name] = doc.name
	return accounts


def _seed_account_groups():
	"""Money Account Group is site-wide, so only fill it when it is empty."""
	if frappe.db.count("Money Account Group"):
		return {
			row.group_name: row.name
			for row in frappe.get_all("Money Account Group", fields=["name", "group_name"])
		}

	groups = {}
	for group_name, group_type in ACCOUNT_GROUPS:
		doc = frappe.get_doc(
			{"doctype": "Money Account Group", "group_name": group_name, "group_type": group_type}
		)
		doc.insert(ignore_permissions=True)
		groups[group_name] = doc.name
	return groups


def _seed_payment_methods():
	"""Money Payment Method is site-wide too. Idempotent by name."""
	methods = {}
	for method_name, applies_to in PAYMENT_METHODS:
		existing = frappe.db.get_value("Money Payment Method", {"method_name": method_name}, "name")
		if existing:
			methods[method_name] = existing
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Money Payment Method",
				"method_name": method_name,
				"applies_to_account_type": applies_to,
			}
		)
		doc.insert(ignore_permissions=True)
		methods[method_name] = doc.name
	return methods


def _post(tracker, accounts, methods, month_start, row):
	"""Post one row of the plan. Returns False if its date has not arrived yet."""
	date = getdate(month_start).replace(day=row["day"])
	if date > getdate(today()):
		# The current month is deliberately left part-finished: a month in progress is what
		# the dashboard normally shows, and a full one would misrepresent it.
		return False

	transaction = frappe.get_doc(
		{
			"doctype": "Transaction",
			"tracker": tracker,
			"date": date,
			"transaction_type": row["transaction_type"],
			"amount": row["amount"],
			"account": accounts[row["account"]],
			"destination_account": accounts.get(row.get("destination_account")),
			"category": _category(tracker, row) if row.get("category") else None,
			"payment_method": methods.get(row.get("payment_method")),
			"merchant": row.get("merchant"),
			"payee": row.get("payee"),
			"notes": row.get("notes"),
		}
	)
	transaction.insert(ignore_permissions=True)
	transaction.submit()
	return True


def _category(tracker, row):
	"""Resolve a category by name against the tracker's seeded tree.

	Throws rather than creating one: a name that no longer matches DEFAULT_CATEGORIES means
	the plan has drifted from the seed, and quietly minting a stray category would hide it.
	"""
	category_type = "Income" if row["transaction_type"] == "Income" else "Expense"
	name = frappe.db.get_value(
		"Category",
		{"tracker": tracker, "category_name": row["category"], "category_type": category_type},
		"name",
	)
	if not name:
		frappe.throw(
			_("Demo plan names a {0} category {1} that the default tree does not have.").format(
				category_type, frappe.bold(row["category"])
			)
		)
	return name


def _demo_months(months):
	"""The first day of each month to seed, oldest first, skipping any without a Fiscal Year.

	ERPNext refuses a posting outside a Fiscal Year, and a site whose only year is the
	current one cannot hold six months of history. Rather than failing halfway through, the
	months that will not fit are dropped and reported.
	"""
	period = []
	for offset in range(months - 1, -1, -1):
		month_start = getdate(get_first_day(add_months(today(), -offset)))
		if _covered_by_a_fiscal_year(month_start) and _covered_by_a_fiscal_year(get_last_day(month_start)):
			period.append(month_start)
	return period


def _covered_by_a_fiscal_year(date):
	return bool(
		frappe.db.exists(
			"Fiscal Year",
			{"year_start_date": ["<=", date], "year_end_date": [">=", date], "disabled": 0},
		)
	)


def _summary(tracker, tracker_name, period, posted, skipped):
	currency = frappe.db.get_value("Tracker", tracker, "base_currency")
	rows = balances.get_balances_for_tracker(tracker)
	net_worth = balances.get_net_worth(tracker)

	summary = {
		"tracker": tracker,
		"tracker_name": tracker_name,
		"months": [str(month) for month in period],
		"transactions_posted": posted,
		"transactions_skipped_as_future": skipped,
		"currency": currency,
		"balances": {row["account_name"]: flt(row["balance"]) for row in rows},
		"net_worth": flt(net_worth["net_worth"]),
	}

	print(f"\nDemo tracker {tracker} ({tracker_name}) — {posted} transactions")
	print(f"  months   {summary['months'][0]} … {summary['months'][-1]}")
	for account_name, balance in summary["balances"].items():
		print(f"  {account_name:<20} {fmt_money(balance, currency=currency)}")
	print(f"  {'net worth':<20} {fmt_money(summary['net_worth'], currency=currency)}")

	# The dashboard cards fall back to the user's *earliest* tracker, not the newest one.
	owner = frappe.db.get_value("Tracker", tracker, "owner_user")
	first = frappe.db.get_value(
		"Tracker", {"owner_user": owner, "is_archived": 0}, "name", order_by="creation asc"
	)
	if first != tracker:
		print(
			f"\n  Note: {owner} already owns {first}, which is what the unfiltered dashboard\n"
			f"  cards and charts will show. Set Tracker on each widget's filter, or archive\n"
			f"  the older tracker, to see the demo data on the workspace."
		)
	return summary


# --- teardown ----------------------------------------------------------------------------


def clear_demo_data(tracker=None, tracker_name=None):
	"""Remove the demo tracker and everything posted on it. Returns a count of what went.

	This deletes ledger rows outright rather than cancelling them, which nothing else in
	this app is allowed to do — a cancellation is the right answer for a real mistake, but
	the point here is to leave no trace. Two things make it safe:

	* the tracker must carry `DEMO_MARKER`, so the teardown cannot be pointed at real books;
	* `GL Entry` rows are deleted by **tracker**, the accounting dimension, which by
	  definition cannot reach another tracker's rows.

	Deliberately **not** `@frappe.whitelist()`. It is only ever run from `bench execute`, and
	whitelisting would expose a ledger-deleting call over HTTP for no gain. The
	`only_for("System Manager")` below is the second line of defence for a console or server
	script caller — note that Frappe makes `only_for` a no-op under test, so the suite checks
	the absence of the whitelist instead.

	The ERPNext `Account` records the demo created are left behind on purpose: accounts are
	shared by name across trackers, so deleting "HDFC Bank" could take a real tracker's
	ledger account with it. They are empty once the GL rows are gone.
	"""
	_refuse_in_tests()
	frappe.only_for("System Manager")

	tracker = tracker or _find_demo_tracker(tracker_name)
	if not tracker:
		frappe.throw(_("No demo data found on this site."), title=_("Nothing to Clear"))
	_assert_is_demo(tracker)

	journal_entries = frappe.get_all(
		"Transaction", filters={"tracker": tracker, "journal_entry": ["is", "set"]}, pluck="journal_entry"
	)
	removed = {
		"gl_entries": frappe.db.count("GL Entry", {"tracker": tracker}),
		"journal_entries": len(journal_entries),
		"transactions": frappe.db.count("Transaction", {"tracker": tracker}),
	}

	frappe.db.delete("GL Entry", {"tracker": tracker})
	if journal_entries:
		frappe.db.delete("Journal Entry Account", {"parent": ["in", journal_entries]})
		frappe.db.delete("Journal Entry", {"name": ["in", journal_entries]})
	frappe.db.delete("Transaction", {"tracker": tracker})

	removed["money_accounts"] = _delete_all("Money Account", {"tracker": tracker})
	removed["categories"] = _delete_categories(tracker)
	frappe.delete_doc("Tracker", tracker, ignore_permissions=True, force=True)
	removed["payment_methods"] = _delete_unreferenced_payment_methods()
	removed["account_groups"] = _delete_unreferenced_account_groups()

	# No commit here on purpose: `bench execute` commits for us, and committing inside would
	# break the per-class rollback the test suite relies on.
	print(f"Cleared demo tracker {tracker}: {removed}")
	return removed


def _delete_all(doctype, filters):
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	for name in names:
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
	return len(names)


def _delete_categories(tracker):
	"""Deepest first: a NestedSet refuses to delete a node that still has children."""
	names = frappe.get_all("Category", filters={"tracker": tracker}, order_by="lft desc", pluck="name")
	for name in names:
		frappe.delete_doc("Category", name, ignore_permissions=True, force=True)
	return len(names)


def _delete_unreferenced_payment_methods():
	"""Only the ones the demo introduced, and only while nothing else points at them."""
	removed = 0
	for method_name, _applies_to in PAYMENT_METHODS:
		name = frappe.db.get_value("Money Payment Method", {"method_name": method_name}, "name")
		if name and not frappe.db.exists("Transaction", {"payment_method": name}):
			frappe.delete_doc("Money Payment Method", name, ignore_permissions=True, force=True)
			removed += 1
	return removed


def _delete_unreferenced_account_groups():
	removed = 0
	for group_name, _group_type in ACCOUNT_GROUPS:
		name = frappe.db.get_value("Money Account Group", {"group_name": group_name}, "name")
		if name and not frappe.db.exists("Money Account", {"account_group": name}):
			frappe.delete_doc("Money Account Group", name, ignore_permissions=True, force=True)
			removed += 1
	return removed


# --- helpers -----------------------------------------------------------------------------


def _find_demo_tracker(tracker_name=None):
	"""A demo tracker by name, or any of them when no name is given."""
	filters = {"description": ["like", f"%{DEMO_MARKER}%"]}
	if tracker_name:
		filters["tracker_name"] = tracker_name
	return frappe.db.get_value("Tracker", filters, "name")


def _assert_is_demo(tracker):
	description = frappe.db.get_value("Tracker", tracker, "description") or ""
	if DEMO_MARKER not in description:
		frappe.throw(
			_("Tracker {0} is not demo data — it carries no demo marker. Refusing to delete it.").format(
				tracker
			),
			title=_("Not Demo Data"),
		)


def _refuse_in_tests():
	"""The suite builds its own fixtures; demo data in a test run would skew every total.

	`flags.allow_demo_data` is the opt-in for the two tests that exercise this module, the
	same idiom as `Tracker.flags.skip_default_categories`.
	"""
	if frappe.flags.in_test and not frappe.flags.allow_demo_data:
		frappe.throw(_("Demo data must not be created during a test run."))
