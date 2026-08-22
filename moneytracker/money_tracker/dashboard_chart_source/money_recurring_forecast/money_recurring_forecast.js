frappe.provide("frappe.dashboards.chart_sources");

// Read straight off disk by dashboard_chart_source.get_config and eval'd in the browser,
// so it needs no asset build. It declares the filter dialog behind the chart's funnel icon.
frappe.dashboards.chart_sources["Money Recurring Forecast"] = {
	method: "moneytracker.money_tracker.dashboard_chart_source.money_recurring_forecast.money_recurring_forecast.get",
	filters: [
		{
			// Left blank on purpose: the source then falls back to the signed-in user's own
			// tracker, so one standard chart works for everybody on a shared site.
			fieldname: "tracker",
			label: __("Tracker"),
			fieldtype: "Link",
			options: "Tracker",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["Active", "Paused", "Archived"],
			default: "Active",
		},
		{
			// Months ahead. Six is a year's worth of a quarterly plan and half a year of rent —
			// far enough to see a yearly premium coming, near enough to still be a commitment
			// rather than a guess.
			fieldname: "months",
			label: __("Months Ahead"),
			fieldtype: "Int",
			default: 6,
		},
	],
};
