# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The category tree: a starter set for a new tracker, and roll-up totals over it.

Roll-ups live here rather than in the chart of accounts. Every leaf category gets its own
flat ERPNext Account, so ERPNext's own reports list the leaves side by side; the "Food
4,500" heading total is derived from the NestedSet `lft`/`rgt` bounds instead.
"""

from dataclasses import dataclass

import frappe
from frappe.utils import flt, getdate

# The transaction types that move money across an expense category. A Refund is one of them
# and is the reason this list is not just "Expense": it gives spending back rather than
# earning it, so it nets off the category it was originally spent on (§62).
SPEND_TYPES = ("Expense", "Refund")


@dataclass(frozen=True)
class SideCharge:
	"""Money attached to a category on a voucher that carries no category of its own.

	Every one of these is invisible to a query that groups by `Transaction.category`, and every
	one of them posts to `GL Entry` correctly and leaves the account balance right — so when one
	goes missing, nothing looks broken. It simply disappears from the roll-up, from the spending
	chart and from every budget.

	That has now happened twice: transfer fees, and loan interest. It is a *table* rather than a
	third hand-written query so that the third one is a row here and not a fourth bug — and so
	that the rule in CLAUDE.md ("any new way of attaching money to a category needs both
	aggregation call sites updated") is enforced by structure rather than remembered.

	`side` is the category type the charge lands on. Loan interest on money *lent* is income, so
	it must not be added to spending.
	"""

	amount_field: str
	category_field: str
	base_field: str
	side: str
	what: str


SIDE_CHARGES = (
	SideCharge("fee_amount", "fee_category", "fee_base_amount", "Expense", "a transfer fee"),
	# The price of borrowing, on a voucher whose other half is a balance-sheet movement. A
	# budget on "Interest Paid" is precisely there to catch this.
	SideCharge(
		"interest_amount",
		"interest_category",
		"interest_base_amount",
		"Expense",
		"interest on a loan",
	),
)


def net_sign(transaction_type):
	"""+1 for money going out, -1 for money coming back (§62).

	Stated once, here, because it is the rule that decides what "spent" means everywhere —
	the category roll-up, the spending trend, a Spending Limit goal and a budget envelope all
	have to agree about it or the same month reads differently on two widgets.
	"""
	return -1 if transaction_type == "Refund" else 1


# (group label, children). A group with no children is a leaf the user can post to.
DEFAULT_CATEGORIES = {
	"Expense": (
		("Food & Dining", ("Groceries", "Restaurants", "Cafes")),
		("Transport", ("Fuel", "Public Transport", "Taxi")),
		("Housing", ("Rent", "Utilities", "Maintenance")),
		("Shopping", ("Clothing", "Electronics", "Household")),
		("Health", ("Doctor", "Medicines", "Health Insurance")),
		("Entertainment", ("Subscriptions", "Movies & Events")),
		("Personal Care", ()),
		("Education", ()),
		("Travel", ()),
		("Gifts & Donations", ()),
		("Bank Charges & Fees", ()),
		# The price of borrowing. A default rather than something each household invents,
		# because `Money Loan` requires one and the alternative is filing interest under
		# "Bank Charges", where it stops being separable from a 50-rupee transfer fee.
		("Interest Paid", ()),
		("Taxes", ()),
		("Miscellaneous", ()),
	),
	"Income": (
		("Salary", ()),
		("Business & Freelance", ()),
		("Investments", ("Interest", "Dividends", "Capital Gains")),
		("Rent Received", ()),
		("Other Income", ()),
	),
}


def _get_or_create(tracker, category_type, category_name, is_group=0, parent=None):
	existing = frappe.db.get_value(
		"Category",
		{"tracker": tracker, "category_type": category_type, "category_name": category_name},
		"name",
	)
	if existing:
		return existing

	category = frappe.get_doc(
		{
			"doctype": "Category",
			"tracker": tracker,
			"category_type": category_type,
			"category_name": category_name,
			"is_group": is_group,
			"parent_category": parent,
		}
	)
	category.insert(ignore_permissions=True)
	return category.name


def seed_default_categories(tracker):
	"""Give a new tracker a usable category tree. Returns the number created.

	Idempotent by name, so it is safe to re-run over a tracker somebody has already edited —
	a category they renamed or deleted is simply recreated, never duplicated.
	"""
	before = frappe.db.count("Category", {"tracker": tracker})

	for category_type, groups in DEFAULT_CATEGORIES.items():
		for label, children in groups:
			parent = _get_or_create(tracker, category_type, label, is_group=1 if children else 0)
			for child in children:
				_get_or_create(tracker, category_type, child, parent=parent)

	return frappe.db.count("Category", {"tracker": tracker}) - before


def _split_rows(tracker, types, from_date=None, to_date=None, categories=None):
	"""Every split row in the window as `(category, transaction_type, date, base_amount)`.

	A split transaction has **no** `category` of its own — the controller clears it — so it is
	invisible to the plain grouped queries below, and its money would simply disappear from
	every category total and every budget. This is where it comes back.

	Child fields are selected, never aggregated: `get_all` will put a backticked child column
	in the SELECT and join correctly, but wrapping one in `SUM()` makes its join parser read
	the aggregate as another table and emit invalid SQL. They are aliased because both tables
	carry `base_amount`. Summing happens in Python, over the split rows only, which are few.
	"""
	filters = [
		["Transaction", "tracker", "=", tracker],
		["Transaction", "docstatus", "=", 1],
		["Transaction", "transaction_type", "in", list(types)],
		["Money Transaction Split", "category", "is", "set"],
	]
	if from_date and to_date:
		filters.append(["Transaction", "date", "between", [from_date, to_date]])
	if categories is not None:
		if not categories:
			return []
		filters.append(["Money Transaction Split", "category", "in", list(categories)])

	return frappe.get_all(
		"Transaction",
		filters=filters,
		fields=[
			"name as transaction",
			"transaction_type",
			"date",
			"`tabMoney Transaction Split`.category as split_category",
			"`tabMoney Transaction Split`.base_amount as split_base_amount",
		],
	)


def _side_charge_rows(tracker, side="Expense", from_date=None, to_date=None, categories=None):
	"""Every `SIDE_CHARGES` amount on that side, as `(category, date, total)`.

	One query per row of the table rather than one hand-written function per feature — see
	`SideCharge`. Always the money going *that* way, never a refund, so no `net_sign` is
	involved: a fee is not refundable and neither is interest already paid.
	"""
	rows = []
	for charge in SIDE_CHARGES:
		if charge.side != side:
			continue

		filters = {
			"tracker": tracker,
			"docstatus": 1,
			charge.amount_field: [">", 0],
			charge.category_field: ["is", "set"],
		}
		if from_date and to_date:
			filters["date"] = ["between", [from_date, to_date]]
		if categories is not None:
			if not categories:
				continue
			filters[charge.category_field] = ["in", list(categories)]

		rows.extend(
			frappe._dict({"category": row[0], "date": row[1], "total": flt(row[2])})
			for row in frappe.get_all(
				"Transaction",
				filters=filters,
				fields=[
					charge.category_field,
					"date",
					f"SUM(`{charge.base_field}`) as total",
				],
				group_by=f"{charge.category_field}, date",
				as_list=True,
			)
		)
	return rows


def get_category_totals(tracker, category_type="Expense", from_date=None, to_date=None):
	"""Every category on the tracker with its own total and its total including descendants.

	One query for the tree and one for the money, then the roll-up is done in Python over
	`lft`/`rgt` — a category tree is a handful of rows, and a self-join per node would be the
	N+1 pattern §74 rules out.
	"""
	categories = frappe.get_all(
		"Category",
		filters={"tracker": tracker, "category_type": category_type},
		fields=["name", "category_name", "parent_category", "is_group", "lft", "rgt"],
		order_by="lft asc",
	)
	if not categories:
		return []

	filters = {
		"tracker": tracker,
		"docstatus": 1,
		"category": ["in", [c.name for c in categories]],
	}
	if from_date and to_date:
		filters["date"] = ["between", [from_date, to_date]]

	rows = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=["category", "transaction_type", "SUM(base_amount) as total"],
		group_by="category, transaction_type",
	)

	own = {}
	for row in rows:
		own[row.category] = flt(own.get(row.category, 0.0)) + net_sign(row.transaction_type) * flt(row.total)

	# A split bill contributes to each category it was split across. Its parent carries no
	# category at all, so without this the money is missing from the roll-up entirely.
	names = [c.name for c in categories]
	types = SPEND_TYPES if category_type == "Expense" else ("Income",)
	for row in _split_rows(tracker, types, from_date, to_date, categories=names):
		own[row.split_category] = flt(own.get(row.split_category, 0.0)) + net_sign(
			row.transaction_type
		) * flt(row.split_base_amount)

	# A transfer fee and a loan's interest are both money charged to a category on a voucher
	# that carries none. See `SIDE_CHARGES`.
	for row in _side_charge_rows(tracker, category_type, from_date, to_date, categories=names):
		own[row.category] = flt(own.get(row.category, 0.0)) + flt(row.total)

	result = []
	for category in categories:
		descendants = [c for c in categories if category.lft <= c.lft and c.rgt <= category.rgt]
		result.append(
			{
				"category": category.name,
				"category_name": category.category_name,
				"parent_category": category.parent_category,
				"is_group": category.is_group,
				"own_total": flt(own.get(category.name, 0.0)),
				"total": flt(sum(own.get(c.name, 0.0) for c in descendants)),
			}
		)
	return result


def get_net_spend_by_date(tracker, category=None, from_date=None, to_date=None):
	"""Net spend per day over one category subtree, as `{date: amount}`.

	The daily form of `get_category_totals`, for callers that have to slice the same money
	into periods of their own — a budget envelope repeats, so it needs a month at a time out
	of one query rather than one query per month.

	`category` is rolled up over its `lft`/`rgt` bounds, so a budget set on Food covers
	Groceries and Restaurants with it. **No category means the whole tracker's spending**,
	including transactions filed under nothing at all — the same reading a Spending Limit
	goal with no category takes.

	Days with no spending are absent rather than zero; the caller is bucketing anyway and a
	dict of every date in a three-year range would be mostly padding.
	"""
	filters = {
		"tracker": tracker,
		"docstatus": 1,
		"transaction_type": ["in", SPEND_TYPES],
	}
	if from_date and to_date:
		filters["date"] = ["between", [from_date, to_date]]

	subtree = None
	if category:
		subtree = get_subtree(category)
		if not subtree:
			return {}
		filters["category"] = ["in", subtree]

	# Fetched before the main query so the transactions they belong to can be left out of it.
	# `get_category_totals` needs no such guard: it filters on `category in (...)`, and a split
	# transaction's own category is empty, so it is excluded already. Here there may be no
	# category filter at all — a whole-tracker budget — and without this the parent's full
	# amount would be counted *and* its shares added on top of it.
	splits = _split_rows(tracker, SPEND_TYPES, from_date, to_date, categories=subtree if category else None)
	if splits:
		filters["name"] = ["not in", list({row.transaction for row in splits})]

	rows = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=["date", "transaction_type", "SUM(base_amount) as total"],
		group_by="date, transaction_type",
	)

	by_date = {}
	for row in rows:
		day = getdate(row.date)
		by_date[day] = flt(by_date.get(day, 0.0)) + net_sign(row.transaction_type) * flt(row.total)

	# Budgets measure through here, so a split grocery bill has to reach the Groceries envelope
	# as surely as an unsplit one does. `subtree` is already resolved above when a category was
	# given; `None` means the whole tracker and therefore every split row in it.
	for row in splits:
		day = getdate(row.date)
		by_date[day] = flt(by_date.get(day, 0.0)) + net_sign(row.transaction_type) * flt(
			row.split_base_amount
		)

	# And the side charges — a transfer fee, a loan's interest — which a budget on Bank Charges
	# or on Interest Paid is precisely there to catch. The main query above cannot see either:
	# it filters on SPEND_TYPES, and neither a Transfer nor a Loan Payment is one.
	for row in _side_charge_rows(
		tracker, "Expense", from_date, to_date, categories=subtree if category else None
	):
		day = getdate(row.date)
		by_date[day] = flt(by_date.get(day, 0.0)) + flt(row.total)
	return by_date


def get_side_charges_by_date(tracker, side="Expense", from_date=None, to_date=None):
	"""`SIDE_CHARGES` totals per day over the whole tracker, as `{date: amount}`.

	The window form of the same table, for callers that measure a *period* rather than a
	category — the spending trend and the month cards. Without it a transfer fee and a loan's
	interest are spending on the category roll-up and on every budget, and not spending on the
	dashboard: the same money reading two ways on one screen, which is the contradiction §33
	exists to prevent.
	"""
	by_date = {}
	for row in _side_charge_rows(tracker, side, from_date, to_date):
		day = getdate(row.date)
		by_date[day] = flt(by_date.get(day, 0.0)) + flt(row.total)
	return by_date


def get_subtree(category):
	"""A category and every category filed under it, by name.

	One query on the NestedSet bounds rather than a recursive walk — and scoped to the
	category's own tracker, since `lft`/`rgt` are only unique within one tree.
	"""
	row = frappe.db.get_value("Category", category, ["tracker", "category_type", "lft", "rgt"], as_dict=True)
	if not row:
		return []

	return frappe.get_all(
		"Category",
		filters={
			"tracker": row.tracker,
			"category_type": row.category_type,
			"lft": [">=", row.lft],
			"rgt": ["<=", row.rgt],
		},
		pluck="name",
	)
