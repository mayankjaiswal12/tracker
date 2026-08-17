# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""The category tree: a starter set for a new tracker, and roll-up totals over it.

Roll-ups live here rather than in the chart of accounts. Every leaf category gets its own
flat ERPNext Account, so ERPNext's own reports list the leaves side by side; the "Food
4,500" heading total is derived from the NestedSet `lft`/`rgt` bounds instead.
"""

import frappe
from frappe.utils import flt

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
		# A refund gives spending back rather than earning it, so it nets off the category it
		# was originally spent on (§62).
		sign = -1 if row.transaction_type == "Refund" else 1
		own[row.category] = flt(own.get(row.category, 0.0)) + sign * flt(row.total)

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
