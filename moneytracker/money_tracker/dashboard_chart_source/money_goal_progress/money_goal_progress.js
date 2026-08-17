frappe.provide("frappe.dashboards.chart_sources");

// Read straight off disk by dashboard_chart_source.get_config and eval'd in the browser,
// so it needs no asset build. It declares the filter dialog behind the chart's funnel icon.
frappe.dashboards.chart_sources["Money Goal Progress"] = {
	method: "moneytracker.money_tracker.dashboard_chart_source.money_goal_progress.money_goal_progress.get",
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
			fieldname: "goal_type",
			label: __("Goal Type"),
			fieldtype: "Select",
			// Blank means every type. Kept in step with the DocType's own Select by
			// test_the_chart_source_filter_lists_every_goal_type.
			options: [
				"",
				"Savings",
				"Net Worth Target",
				"Income Target",
				"Savings Rate Target",
				"Spending Limit",
				"Debt Payoff",
			],
		},
	],
};
