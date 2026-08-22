# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Merchant totals, and the lookup that keeps one shop from becoming three.

This is the counterpart to `services/tags.py`, and the two differ in exactly one way that
matters: **a transaction has at most one merchant**, so these totals *do* partition spending
the way the category tree does, and `untagged`'s awkward sibling here is simply the money
that names nobody. No overlap, no double counting, no join.
"""

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.services.categories import SPEND_TYPES, net_sign

# Same two readings tags offers, and for the same reason: a merchant can be on both sides of
# the books — a shop you buy from and later get a refund from — and one netted figure would
# hide the size of either.
MERCHANT_VIEWS = {
	"Expense": SPEND_TYPES,
	"Income": ("Income",),
}
MERCHANT_VIEW_OPTIONS = tuple(MERCHANT_VIEWS)


def get_merchant_view(view):
	types = MERCHANT_VIEWS.get(view)
	if not types:
		frappe.throw(
			_("{0} is not a merchant view. Supported: {1}.").format(view, ", ".join(MERCHANT_VIEW_OPTIONS))
		)
	return types


def get_spend_by_merchant(tracker, from_date=None, to_date=None, view="Expense", limit=None):
	"""Every merchant on the tracker with what it carries, biggest first.

	Unlike `tags.get_spend_by_tag`, the rows here **do** add up: `sum(rows) + unnamed == total`,
	because a transaction names one merchant or none. `limit` trims the tail for a top-N chart
	and never changes `total`, which stays the whole window.
	"""
	types = get_merchant_view(view)

	filters = {"tracker": tracker, "docstatus": 1, "transaction_type": ["in", types]}
	if from_date and to_date:
		filters["date"] = ["between", [from_date, to_date]]

	rows = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=["merchant", "transaction_type", "SUM(base_amount) as total", "COUNT(*) as transactions"],
		group_by="merchant, transaction_type",
	)

	totals, counts = {}, {}
	for row in rows:
		key = row.merchant or None
		totals[key] = flt(totals.get(key, 0.0)) + net_sign(row.transaction_type) * flt(row.total)
		counts[key] = counts.get(key, 0) + (row.transactions or 0)

	merchants = frappe.get_all(
		"Money Merchant",
		filters={"tracker": tracker},
		fields=["name", "merchant_name", "is_active"],
	)

	measured = [
		{
			"merchant": m.name,
			"merchant_name": m.merchant_name,
			"is_active": m.is_active,
			"total": flt(totals.get(m.name, 0.0)),
			"transactions": counts.get(m.name, 0),
			# What each merchant took as a share of the window. Meaningful here precisely
			# because the rows partition the money, which is why tags offers no equivalent.
			"share": 0.0,
		}
		for m in merchants
	]
	measured.sort(key=lambda row: (-row["total"], row["merchant_name"]))

	unnamed = flt(totals.get(None, 0.0))
	total = flt(sum(totals.values()))
	if total:
		for row in measured:
			row["share"] = flt(row["total"] / total * 100, 2)

	return {
		"view": view,
		"merchants": measured[:limit] if limit else measured,
		"shown": len(measured[:limit] if limit else measured),
		"unnamed": unnamed,
		"unnamed_transactions": counts.get(None, 0),
		"named": flt(total - unnamed),
		"total": total,
	}


def resolve(merchant_name, tracker, create=False):
	"""A `Money Merchant` for `merchant_name` on `tracker`, matched case-insensitively.

	The one place a free-text merchant name becomes a record, so an importer, the demo seeder
	and a client all agree about when two spellings are the same shop. Returns `None` rather
	than throwing when there is no match and `create` is off.
	"""
	name = (merchant_name or "").strip()
	if not name:
		return None

	existing = frappe.db.get_value(
		"Money Merchant", {"tracker": tracker, "merchant_name": ["like", name]}, "name"
	)
	if existing or not create:
		return existing

	doc = frappe.get_doc({"doctype": "Money Merchant", "merchant_name": name, "tracker": tracker})
	doc.insert(ignore_permissions=True)
	return doc.name


def search_names(query, tracker):
	"""Merchant records whose name contains `query` — how a text search reaches a Link field.

	`Transaction.merchant` holds `MER-00007`, so a `LIKE '%dmart%'` against the column matches
	nothing at all. Anything searching by merchant has to come through here first.
	"""
	if not query:
		return []
	return frappe.get_all(
		"Money Merchant",
		filters={"tracker": tracker, "merchant_name": ["like", f"%{query}%"]},
		pluck="name",
	)
