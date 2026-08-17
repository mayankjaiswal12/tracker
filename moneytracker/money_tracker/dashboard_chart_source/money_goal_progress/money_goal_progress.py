# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard Chart Source: how far along each goal is, for one tracker.

The one chart in this app that is **not** a time series. `Money Period Totals` plots a
figure per month; this plots a figure per goal, so it needs its own source rather than a
`series` filter on that one — the labels are goal names and there is no interval, timespan
or period boundary anywhere in it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from moneytracker.money_tracker.api.dashboard import parse_widget_filters, resolve_widget_tracker
from moneytracker.money_tracker.services import goals

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

	measured = goals.measure_goals(
		tracker,
		filters.get("as_of"),
		status=filters.get("status") or DEFAULT_STATUS,
		goal_type=filters.get("goal_type"),
	)

	return {
		"labels": [row.goal_name for row in measured],
		"datasets": [
			{
				"name": _("Progress"),
				# Negative progress is real — refunds can outrun a month's spending, a debt can
				# grow — but it has no bar to draw, so the chart floors it at zero while the
				# figure itself stays truthful everywhere else. Over 100 is left alone: a
				# breached spending limit is exactly what the chart should make obvious.
				"values": [max(flt(row.progress_percent), 0.0) for row in measured],
			}
		],
	}


def _get_chart(chart_name, chart):
	"""The chart document as a plain dict, however the widget chose to pass it."""
	if chart_name:
		return frappe.get_doc("Dashboard Chart", chart_name).as_dict()
	return frappe._dict(frappe.parse_json(chart) or {})
