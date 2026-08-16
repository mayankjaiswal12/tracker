# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Income and expense over time — the series behind the dashboard charts (spec §5).

The figures are read from `Transaction` rather than from `GL Entry`, for the same reason
the Number Cards are: a Refund has to *reduce* spending rather than count as income (§62),
and that is a fact about the transaction type, not about the accounts its Journal Entry
happened to touch.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from frappe.utils.dateutils import get_dates_from_timegrain, get_period, get_period_ending

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

	for row in rows:
		period_end = getdate(get_period_ending(row.date, interval))
		if period_end not in buckets:
			# Only reachable if a period boundary and the range disagree; bin it into the
			# last period rather than dropping the money out of the chart entirely.
			period_end = period_ends[-1]
		bucket = buckets[period_end]

		if row.transaction_type == "Income":
			bucket["income"] += flt(row.total)
		elif row.transaction_type == "Refund":
			bucket["expense"] -= flt(row.total)
		else:
			bucket["expense"] += flt(row.total)

	return [
		{
			"period_end": period_end,
			"label": get_period(period_end, interval),
			"income": flt(buckets[period_end]["income"]),
			"expense": flt(buckets[period_end]["expense"]),
		}
		for period_end in period_ends
	]
