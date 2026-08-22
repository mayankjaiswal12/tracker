# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard Chart Source: each budget's envelope against what has been spent out of it.

Two datasets over one set of labels, so a bar chart draws the pair side by side and the
gap between them *is* the headroom. Like `Money Goal Progress` and unlike
`Money Period Totals`, this is not a time series — the labels are budget names and there is
no interval anywhere in it.

The `period` filter is the one that stops the chart lying. A tracker may hold a weekly
grocery envelope and a yearly holiday one, and drawing those two bars next to each other
invites a comparison that means nothing. Narrowing to one kind of period puts every bar on
the same clock.
"""

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.api.dashboard import parse_widget_filters, resolve_widget_tracker
from moneytracker.money_tracker.services import budgets

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

	measured = budgets.measure_budgets(
		tracker,
		filters.get("as_of"),
		status=filters.get("status") or DEFAULT_STATUS,
		period=filters.get("period"),
	)

	return {
		"labels": [row.budget_name for row in measured],
		"datasets": [
			{
				# What the period has to spend, rollover included — the line the bar next to it
				# is being measured against, not the amount typed on the document.
				"name": _("Budget"),
				"values": [flt(row.available) for row in measured],
			},
			{
				"name": _("Spent"),
				"values": [flt(row.spent) for row in measured],
			},
		],
	}


def _get_chart(chart_name, chart):
	"""The chart document as a plain dict, however the widget chose to pass it."""
	if chart_name:
		return frappe.get_doc("Dashboard Chart", chart_name).as_dict()
	return frappe._dict(frappe.parse_json(chart) or {})
