// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Colours are keyed on the outcome words in services/budgets.py, not on percentages. An
// envelope runs the other way from a savings goal: 90% full is nearly in trouble.
const OUTCOME_COLOR = {
	"No Spend": "var(--gray-400)",
	"Within Budget": "var(--green-500)",
	"At Risk": "var(--orange-500)",
	"Nearing Limit": "var(--orange-500)",
	"Over Budget": "var(--red-500)",
	"Not Started": "var(--gray-400)",
};

frappe.ui.form.on("Money Budget", {
	setup(frm) {
		frm.set_query("category", () => {
			// Expense only — an envelope holds spending. Group categories are deliberately *not*
			// excluded: a budget on Food is meant to roll up Groceries and Restaurants.
			const filters = { category_type: "Expense" };
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});
	},

	refresh(frm) {
		describe_fields(frm);
		render_progress(frm);
	},

	rollover(frm) {
		describe_fields(frm);
	},
});

function describe_fields(frm) {
	// Rollover carries a deficit as well as a surplus, which is the half people do not expect.
	frm.set_df_property(
		"rollover",
		"description",
		frm.doc.rollover
			? __(
					"On: what is left of a period is added to the next one — and an overspend is subtracted from it."
			  )
			: __("Off: every period starts again at the full amount, whatever happened last time.")
	);
}

function render_progress(frm) {
	const field = frm.get_field("progress_html");
	if (!field || frm.is_new()) return;

	frappe.call({
		method: "moneytracker.money_tracker.api.budgets.get_budget_progress",
		args: { budget: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(progress_html(message));
		},
	});
}

function progress_html(p) {
	const color = OUTCOME_COLOR[p.outcome] || "var(--gray-400)";
	// Clamped for the bar only: there is no more bar to fill past the end of the envelope,
	// while the printed figures stay truthful about how far past it the spending went.
	const width = Math.min(Math.max(p.used_percent || 0, 0), 100);
	const percent = frappe.utils.escape_html(`${p.used_percent}%`);
	const outcome = frappe.utils.escape_html(__(p.outcome));
	const period = frappe.utils.escape_html(p.period_label || "");
	const detail = footnotes(p).map(frappe.utils.escape_html).join(" · ");

	const bar = `background:var(--gray-200); border-radius:var(--border-radius-full); height:10px; margin:10px 0 8px; position:relative; overflow:hidden;`;
	const fill = `background:${color}; width:${width}%; height:100%; border-radius:var(--border-radius-full);`;

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${percent}</span>
				<span style="color:var(--text-muted); font-size:var(--text-sm);">${period}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div style="${bar}">
				<div style="${fill}"></div>
				${pace_marker(p)}
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm);">${detail}</div>
			${history_strip(p)}
		</div>
	`;
}

function pace_marker(p) {
	// How much of the period has passed. Spending past this line is spending faster than the
	// month is going, which is what "At Risk" means before anything has actually been breached.
	if (p.expected_percent === null || p.expected_percent === undefined) return "";

	const left = Math.min(Math.max(p.expected_percent, 0), 100);
	const style = `position:absolute; top:-2px; bottom:-2px; left:${left}%; width:2px; background:var(--text-color); opacity:0.45;`;
	return `<div title="${__("Where the period has got to")}" style="${style}"></div>`;
}

function footnotes(p) {
	const notes = [];
	const f = p.formatted || {};

	notes.push(__("{0} of {1} spent", [f.spent, f.available]));
	notes.push(p.remaining < 0 ? __("{0} over", [f.remaining]) : __("{0} left", [f.remaining]));

	if (p.rollover && p.carried_in) {
		notes.push(
			p.carried_in > 0
				? __("{0} carried in", [f.carried_in])
				: __("{0} carried in from an overspend", [f.carried_in])
		);
	}
	if (p.days_left) notes.push(__("{0} days left", [p.days_left]));
	if (f.available_per_day) notes.push(__("{0} a day left", [f.available_per_day]));

	return notes;
}

function history_strip(p) {
	// The one thing a budget shows that a goal cannot: the same envelope, over and over. Six
	// finished periods is enough to see a habit without turning the form into a report.
	const history = (p.history || []).slice(-6);
	if (!history.length) return "";

	const tallest = Math.max(...history.map((h) => Math.max(h.spent, h.budget_amount)), 1);
	const columns = history
		.map((h) => {
			const height = Math.round((Math.max(h.spent, 0) / tallest) * 100);
			const color = h.remaining < 0 ? "var(--red-500)" : "var(--gray-400)";
			const cap = Math.round((h.budget_amount / tallest) * 100);
			const title = frappe.utils.escape_html(`${h.label}: ${h.formatted_spent}`);
			return `
				<div title="${title}" style="flex:1; display:flex; flex-direction:column; justify-content:flex-end; height:40px; position:relative;">
					<div style="position:absolute; left:0; right:0; bottom:${cap}%; border-top:1px dashed var(--gray-400); opacity:0.7;"></div>
					<div style="background:${color}; height:${height}%; border-radius:2px 2px 0 0;"></div>
				</div>`;
		})
		.join("");

	return `
		<div style="margin-top:12px;">
			<div style="display:flex; gap:4px; align-items:flex-end;">${columns}</div>
			<div style="color:var(--text-muted); font-size:var(--text-xs); margin-top:4px;">
				${frappe.utils.escape_html(__("Earlier periods, against the dashed envelope"))}
			</div>
		</div>
	`;
}
