# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard Chart Source: what the standing plans commit to, month by month, from today on.

The forward-looking twin of `Money Period Totals`, and **the only series in this app that is
not measured from the ledger** — it cannot be, because none of it has happened yet. It says
what the *plans* commit to and claims nothing more: a month with no plan due draws a zero,
not a prediction that nothing will be spent.

Transfers and credit-card payments are in neither series, the same rule the trend chart
follows (§61) — moving your own money between your own accounts is not income and not
expense, however regularly you do it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.api.dashboard import parse_widget_filters, resolve_widget_tracker
from moneytracker.money_tracker.services import recurring

DEFAULT_MONTHS = 6
DEFAULT_STATUS = "Active"


@frappe.whitelist()
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	"""Return `{labels, datasets}` for the chart widget.

	Deliberately **not** wrapped in `frappe.utils.dashboard.cache_source`, for the reason
	spelled out in `money_period_totals`: that decorator's cache key has no user in it, and on
	a single shared Company the tracker is the only thing keeping two people's books apart.
	"""
	chart = _get_chart(chart_name, chart)
	filters = {**parse_widget_filters(chart.get("filters_json")), **parse_widget_filters(filters)}

	tracker = resolve_widget_tracker(filters)
	if not tracker:
		return {"labels": [], "datasets": []}

	forecast = recurring.get_forecast(
		tracker,
		after=filters.get("as_of"),
		months=filters.get("months") or DEFAULT_MONTHS,
		status=filters.get("status") or DEFAULT_STATUS,
	)

	return {
		"labels": forecast["labels"],
		"datasets": [
			{"name": _("Income"), "values": [flt(row["income"]) for row in forecast["rows"]]},
			{"name": _("Expense"), "values": [flt(row["expense"]) for row in forecast["rows"]]},
		],
	}


def _get_chart(chart_name, chart):
	"""The chart document as a plain dict, however the widget chose to pass it."""
	if chart_name:
		return frappe.get_doc("Dashboard Chart", chart_name).as_dict()
	return frappe._dict(frappe.parse_json(chart) or {})
