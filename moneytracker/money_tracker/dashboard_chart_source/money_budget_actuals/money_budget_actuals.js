frappe.provide("frappe.dashboards.chart_sources");

// Read straight off disk by dashboard_chart_source.get_config and eval'd in the browser,
// so it needs no asset build. It declares the filter dialog behind the chart's funnel icon.
frappe.dashboards.chart_sources["Money Budget Actuals"] = {
	method: "moneytracker.money_tracker.dashboard_chart_source.money_budget_actuals.money_budget_actuals.get",
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
			fieldname: "period",
			label: __("Period"),
			fieldtype: "Select",
			// Blank means every period, which puts envelopes on different clocks side by side.
			// Kept in step with the DocType's own Select by
			// test_the_chart_source_filter_lists_every_period.
			options: ["", "Weekly", "Monthly", "Quarterly", "Yearly"],
			default: "Monthly",
		},
	],
};
