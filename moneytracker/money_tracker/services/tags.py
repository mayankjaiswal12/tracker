# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Tag totals: the same money read a second way.

A category answers *what kind of spending is this*, and a transaction has exactly one, so the
tree is a partition — every rupee lands in one leaf and `get_category_totals` adds up to the
tracker's spending exactly.

A tag answers *what was this for*, and one purchase is often several things at once: a cafe
bill on a family holiday is Eating Out by category, and Vacation and Kids by tag. So:

**Tag totals overlap and do not sum to total spending.** A transaction carrying three tags is
counted in full under all three. That is the point of tags rather than a defect in them, but it
means a pie chart of tags is a lie — every surface here reports tags as a *ranked bar*, and
`untagged` is returned alongside so a caller can say what share of the money carries no tag at
all rather than implying the bars are a whole.

The refund rule is not restated here: `categories.net_sign` owns it (§62), the same way budgets
and the spending trend take it from there.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.services.categories import SPEND_TYPES, net_sign

# The child table's rows are reached through a join on the parent query. Frappe's `get_all`
# will select and group by a child field, but it cannot wrap one in an aggregate — the join
# parser reads `SUM(`tabX`` as another table to join and emits invalid SQL. So the child field
# is grouped on and the *parent's* amount is what gets summed.
TAG_TABLE = "`tabMoney Transaction Tag`.tag"

UNTAGGED = None


@dataclass(frozen=True)
class TagView:
	"""One side of the books, and the transaction types that move money across it."""

	types: tuple
	verb: str


# Income and Expense are read separately rather than netted. A tag like Vacation legitimately
# carries both an outgoing hotel bill and an incoming refund from a cancelled one, and a single
# net figure would hide the size of both.
TAG_VIEWS = {
	"Expense": TagView(SPEND_TYPES, "spent"),
	"Income": TagView(("Income",), "received"),
}
TAG_VIEW_OPTIONS = tuple(TAG_VIEWS)


def get_tag_view(view):
	spec = TAG_VIEWS.get(view)
	if not spec:
		frappe.throw(_("{0} is not a tag view. Supported: {1}.").format(view, ", ".join(TAG_VIEW_OPTIONS)))
	return spec


def get_spend_by_tag(tracker, from_date=None, to_date=None, view="Expense"):
	"""Every tag on the tracker with what it carries, biggest first.

	Returns `{"view", "verb", "tags": [...], "untagged", "tagged", "total"}`.

	`total` is the tracker's real figure for the window and `tagged` is the part of it carrying
	at least one label. Neither is the sum of the `tags` rows, and that sum is not a number
	worth showing: the join repeats a transaction once per tag, so anything carrying two is in
	there twice.

	Tags with nothing against them in the window are returned at zero, so a chart keeps a
	stable set of bars as the window moves. Deliberately the same choice `trends` makes about
	empty periods.
	"""
	spec = get_tag_view(view)

	filters = {
		"tracker": tracker,
		"docstatus": 1,
		"transaction_type": ["in", spec.types],
	}
	if from_date and to_date:
		filters["date"] = ["between", [from_date, to_date]]

	rows = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=[
			f"{TAG_TABLE} as tag",
			"transaction_type",
			"SUM(base_amount) as total",
			# COUNT(*) rather than COUNT(name): both tables have a `name` column, so an
			# unqualified one is ambiguous across the join — and qualifying it would hit the
			# same aggregate-parsing bug described above.
			"COUNT(*) as transactions",
		],
		group_by=f"{TAG_TABLE}, transaction_type",
	)

	# The join is a LEFT JOIN, so a transaction with no tags comes back once with tag NULL.
	# That row is the untagged bucket rather than something to discard: what share of the money
	# carries no label is the first thing anybody asks of a tagging scheme.
	totals, counts = {}, {}
	for row in rows:
		sign = net_sign(row.transaction_type)
		totals[row.tag] = flt(totals.get(row.tag, 0.0)) + sign * flt(row.total)
		counts[row.tag] = counts.get(row.tag, 0) + (row.transactions or 0)

	tags = frappe.get_all(
		"Money Tag",
		filters={"tracker": tracker},
		fields=["name", "tag_name", "color", "icon", "is_active"],
	)

	measured = [
		{
			"tag": tag.name,
			"tag_name": tag.tag_name,
			"color": tag.color,
			"icon": tag.icon,
			"is_active": tag.is_active,
			"total": flt(totals.get(tag.name, 0.0)),
			"transactions": counts.get(tag.name, 0),
		}
		for tag in tags
	]
	measured.sort(key=lambda row: (-row["total"], row["tag_name"]))

	# The honest denominator, and it needs a query of its own. Summing the rows above is
	# exactly what must not be done: the join repeats a transaction once per tag it carries, so
	# a purchase tagged Vacation and Kids contributes its full amount to both. This query names
	# no child field, so Frappe emits no join and each transaction is counted once.
	untotalled = frappe.get_all(
		"Transaction",
		filters=filters,
		fields=["transaction_type", "SUM(base_amount) as total"],
		group_by="transaction_type",
	)
	total = flt(sum(net_sign(row.transaction_type) * flt(row.total) for row in untotalled))
	untagged = flt(totals.get(UNTAGGED, 0.0))

	return {
		"view": view,
		"verb": spec.verb,
		"tags": measured,
		"untagged": untagged,
		"untagged_transactions": counts.get(UNTAGGED, 0),
		# What carries at least one tag. `total - untagged` rather than a sum of the rows, for
		# the reason above — this is the figure a "72% of spending is labelled" claim needs.
		"tagged": flt(total - untagged),
		"total": total,
	}


def get_tagged_transactions(tags, tracker=None):
	"""The transactions carrying any of `tags`, by name.

	A plain filter on the child table from the parent query — which `get_all` does support, and
	is how `api/transactions.search_transactions` narrows a search by tag.
	"""
	if not tags:
		return []
	if isinstance(tags, str):
		tags = [tags]

	filters = [["Money Transaction Tag", "tag", "in", tags]]
	if tracker:
		filters.append(["Transaction", "tracker", "=", tracker])

	return frappe.get_all("Transaction", filters=filters, pluck="name", distinct=True)


def tags_on(transaction):
	"""The tag names on one transaction, in row order."""
	return frappe.get_all(
		"Money Transaction Tag",
		filters={"parent": transaction, "parenttype": "Transaction"},
		order_by="idx asc",
		pluck="tag",
	)
