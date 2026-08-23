# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Income and expense over time — the series behind the dashboard charts (spec §5).

The figures are read from `Transaction` rather than from `GL Entry`, for the same reason
the Number Cards are: a Refund has to *reduce* spending rather than count as income (§62),
and that is a fact about the transaction type, not about the accounts its Journal Entry
happened to touch.

**And a transaction type is not the only way money becomes spending**, which is the second
thing this module has to know. A transfer fee and a loan's interest are charged to an expense
category on a voucher whose type is neither Expense nor Refund, so a query filtered on the type
alone cannot see either — and they were both already reaching the category roll-up and every
budget through `services/categories.py`. The same money reading as spending on one widget and
not on another is exactly the contradiction §33 is about, so both are folded in here from the
one table that describes them, `categories.SIDE_CHARGES`.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from frappe.utils.dateutils import get_dates_from_timegrain, get_period, get_period_ending

from moneytracker.money_tracker.services import categories

# The grains Frappe's own chart widget offers. Anything else has no period-ending rule.
INTERVALS = ("Yearly", "Quarterly", "Monthly", "Weekly", "Daily")


def get_period_series(tracker, from_date, to_date, interval="Monthly"):
	"""Income and net expense per period over a date range, oldest first.

	Every period in the range is returned, including the empty ones. A chart that silently
	drops a month with no transactions draws a line straight from March to May, which reads
	as if April never happened rather than as if nothing was spent in it.

	Each row is `{period_end, label, income, expense}`; `expense` is already net of refunds.
	"""
	if interval not in INTERVALS:
		frappe.throw(_("Unknown time interval {0}").format(interval))

	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date {0} is after To Date {1}").format(from_date, to_date))

	# The period each bar or point stands for, identified by the date it ends on.
	period_ends = [getdate(d) for d in get_dates_from_timegrain(from_date, to_date, interval)]
	buckets = {period_end: {"income": 0.0, "expense": 0.0} for period_end in period_ends}

	rows = frappe.get_all(
		"Transaction",
		filters={
			"tracker": tracker,
			"docstatus": 1,
			"date": ["between", [from_date, to_date]],
			"transaction_type": ["in", ["Income", "Expense", "Refund"]],
		},
		fields=["date", "transaction_type", "SUM(base_amount) as total"],
		group_by="date, transaction_type",
	)

	def bucket_for(date):
		period_end = getdate(get_period_ending(date, interval))
		if period_end not in buckets:
			# Only reachable if a period boundary and the range disagree; bin it into the
			# last period rather than dropping the money out of the chart entirely.
			period_end = period_ends[-1]
		return buckets[period_end]

	for row in rows:
		bucket = bucket_for(row.date)

		if row.transaction_type == "Income":
			bucket["income"] += flt(row.total)
		elif row.transaction_type == "Refund":
			bucket["expense"] -= flt(row.total)
		else:
			bucket["expense"] += flt(row.total)

	# A transfer fee and a loan's interest: spending charged to a category on a voucher whose
	# own type is not a spending type. Never refundable, so they only ever add.
	for date, total in categories.get_side_charges_by_date(tracker, "Expense", from_date, to_date).items():
		bucket_for(date)["expense"] += flt(total)

	return [
		{
			"period_end": period_end,
			"label": get_period(period_end, interval),
			"income": flt(buckets[period_end]["income"]),
			"expense": flt(buckets[period_end]["expense"]),
		}
		for period_end in period_ends
	]


def get_totals(tracker, from_date, to_date):
	"""Income and net expense over one window as `(income, expense)`.

	The series summed rather than a query of its own. The §62 rule that a Refund *reduces*
	spend was briefly written out once per widget, and a rule stated twice is a rule that
	eventually disagrees with itself — the Number Cards, the goals and anything else asking
	"what did this period come to?" all end up here.
	"""
	rows = get_period_series(tracker, from_date, to_date)
	return (
		flt(sum(row["income"] for row in rows)),
		flt(sum(row["expense"] for row in rows)),
	)
