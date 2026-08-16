frappe.provide("frappe.dashboards.chart_sources");

// Read straight off disk by dashboard_chart_source.get_config and eval'd in the browser,
// so it needs no asset build. It declares the filter dialog behind the chart's funnel icon.
frappe.dashboards.chart_sources["Money Period Totals"] = {
	method: "moneytracker.money_tracker.dashboard_chart_source.money_period_totals.money_period_totals.get",
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
			fieldname: "series",
			label: __("Series"),
			fieldtype: "Select",
			options: ["Income and Expense", "Income", "Expense"],
			default: "Income and Expense",
		},
	],
};
