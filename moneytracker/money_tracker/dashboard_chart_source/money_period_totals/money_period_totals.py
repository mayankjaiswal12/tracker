# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Dashboard Chart Source: income and expense per period, for one tracker (spec §5).

One source serves both shipped charts — Spending Trend draws the expense series alone,
Income vs Expense draws both — because they are the same query with a different `series`
filter. A built-in "Sum over Transaction" chart cannot do either: it has no way to net
Refunds out of expense (§62), and it would total every tracker the user is allowed to read
instead of the one the dashboard is showing.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate
from frappe.utils.dateutils import get_from_date_from_timespan, get_period_beginning

from moneytracker.money_tracker.api.dashboard import parse_widget_filters, resolve_widget_tracker
from moneytracker.money_tracker.services import trends

# What `filters.series` may ask for, and which series each one draws.
SERIES = {
	"Income and Expense": ("income", "expense"),
	"Income": ("income",),
	"Expense": ("expense",),
}
DEFAULT_SERIES = "Income and Expense"
DEFAULT_TIMESPAN = "Last Year"
DEFAULT_INTERVAL = "Monthly"

SERIES_LABELS = {"income": "Income", "expense": "Expense"}


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

	Deliberately **not** wrapped in `frappe.utils.dashboard.cache_source`. That decorator
	caches under `chart-data:<chart name>`, a key with no user in it, so two people looking
	at the same standard chart would be served each other's figures — and with one shared
	Company the tracker is the only thing keeping their books apart.
	"""
	chart = _get_chart(chart_name, chart)
	# Merged, not replaced. The chart's own filters_json is what makes Spending Trend a
	# one-series chart; a caller that passes only a tracker must not silently turn it back
	# into two. An explicitly passed key still wins.
	filters = {**parse_widget_filters(chart.get("filters_json")), **parse_widget_filters(filters)}

	tracker = resolve_widget_tracker(filters)
	if not tracker:
		# No tracker yet: an empty payload makes the widget say "No Data" rather than draw a
		# flat line at zero, which would read as "you earned and spent nothing".
		return {"labels": [], "datasets": []}

	interval = time_interval or chart.get("time_interval") or DEFAULT_INTERVAL
	from_date, to_date = _resolve_range(
		chart, interval, timespan or chart.get("timespan"), from_date, to_date
	)

	rows = trends.get_period_series(tracker, from_date, to_date, interval)
	series = SERIES.get(filters.get("series") or DEFAULT_SERIES, SERIES[DEFAULT_SERIES])

	return {
		"labels": [row["label"] for row in rows],
		"datasets": [
			{"name": _(SERIES_LABELS[key]), "values": [row[key] for row in rows]} for key in series
		],
	}


def _get_chart(chart_name, chart):
	"""The chart document as a plain dict, however the widget chose to pass it."""
	if chart_name:
		return frappe.get_doc("Dashboard Chart", chart_name).as_dict()
	return frappe._dict(frappe.parse_json(chart) or {})


def _resolve_range(chart, interval, timespan, from_date, to_date):
	"""The date range to plot, honouring the widget's own timespan / date-range controls.

	Mirrors `dashboard_chart.get_chart_config`: an explicit range wins, otherwise the
	timespan is counted back from today, and the start is snapped to a period boundary so
	the first bar covers a whole month rather than part of one.
	"""
	if timespan == "Select Date Range":
		from_date = from_date or chart.get("from_date")
		to_date = to_date or chart.get("to_date")
	else:
		# The widget leaves the range fields lying on the chart after the user switches back
		# to a named timespan, so a non-range chart ignores them, as Frappe's own does.
		from_date = to_date = None

	to_date = getdate(to_date or nowdate())
	if not from_date:
		# Covers a "Select Date Range" chart with no range saved on it: counting a year back
		# beats plotting a single day.
		named = timespan if timespan and timespan != "Select Date Range" else DEFAULT_TIMESPAN
		from_date = get_from_date_from_timespan(to_date, named)

	return get_period_beginning(getdate(from_date), interval), to_date
