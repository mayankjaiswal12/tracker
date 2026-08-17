// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Money Account types that ERPNext books as a Liability. Mirrors the Liability rows of
// services/coa.py:ACCOUNT_TYPE_MAP — test_the_client_script_knows_the_liability_types fails
// if the two ever drift apart.
const LIABILITY_ACCOUNT_TYPES = ["Credit Card", "Loan", "Other Liability"];

// The goal types measured against one Money Account. Mirrors the rows of
// services/goals.py:GOAL_TYPES that carry an `account`.
const ACCOUNT_GOAL_TYPES = ["Savings", "Debt Payoff"];

// The Category type each goal type measures over. A type that is not listed here uses the
// category as a label for what the goal is *for*, so any category will do.
const MEASURED_CATEGORY_TYPE = {
	"Income Target": "Income",
	"Spending Limit": "Expense",
};

// Colours are keyed on the outcome words in services/goals.py, not on percentages: a
// Spending Limit at 90% is nearly in trouble, a Savings goal at 90% is nearly done.
const OUTCOME_COLOR = {
	Achieved: "var(--green-500)",
	"On Track": "var(--green-500)",
	"In Progress": "var(--blue-500)",
	Behind: "var(--orange-500)",
	"At Risk": "var(--orange-500)",
	Missed: "var(--red-500)",
	Breached: "var(--red-500)",
	"Not Started": "var(--gray-400)",
	"No Data": "var(--gray-400)",
};

frappe.ui.form.on("Money Goal", {
	setup(frm) {
		frm.set_query("target_account", () => {
			// A Savings goal cannot be set against a credit card and a Debt Payoff cannot be
			// set against a bank account — the server refuses both, and the link field should
			// not have offered them in the first place.
			const wants_liability = frm.doc.goal_type === "Debt Payoff";
			const filters = {
				is_active: 1,
				account_type: [wants_liability ? "in" : "not in", LIABILITY_ACCOUNT_TYPES],
			};
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});

		frm.set_query("category", () => {
			// Group categories are deliberately *not* excluded: a limit set on Food rolls up
			// everything filed under it. Transaction is the opposite — it refuses a heading.
			const filters = {};
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			const category_type = MEASURED_CATEGORY_TYPE[frm.doc.goal_type];
			if (category_type) filters.category_type = category_type;
			return { filters };
		});
	},

	refresh(frm) {
		describe_fields(frm);
		render_progress(frm);
	},

	goal_type(frm) {
		// The server clears this on save anyway; doing it here stops the form from offering an
		// account the new type cannot measure, and from showing one that is about to vanish.
		if (!ACCOUNT_GOAL_TYPES.includes(frm.doc.goal_type)) frm.set_value("target_account", null);
		describe_fields(frm);
	},

	measure_basis(frm) {
		describe_fields(frm);
	},
});

function describe_fields(frm) {
	// One field, two jobs. Saying which one it is doing right now saves reading the manual.
	const category_type = MEASURED_CATEGORY_TYPE[frm.doc.goal_type];
	frm.set_df_property(
		"category",
		"description",
		category_type
			? __(
					"What is measured: net {0} filed under this category, including its sub-categories. Leave empty to cover the whole tracker.",
					[category_type.toLowerCase()]
			  )
			: __("What this goal is for. It labels the goal; it is not what gets measured.")
	);

	if (frm.doc.goal_type === "Debt Payoff") {
		frm.set_df_property(
			"opening_amount",
			"description",
			__("What was owed when the goal started. Left empty, it is read from the ledger.")
		);
	} else {
		frm.set_df_property(
			"opening_amount",
			"description",
			__(
				"Money already put aside before the start date, including savings held outside this app."
			)
		);
	}
}

function render_progress(frm) {
	const field = frm.get_field("progress_html");
	if (!field || frm.is_new()) return;

	frappe.call({
		method: "moneytracker.money_tracker.api.goals.get_goal_progress",
		args: { goal: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(progress_html(message));
		},
	});
}

function progress_html(p) {
	const color = OUTCOME_COLOR[p.outcome] || "var(--gray-400)";
	// Clamped for the bar only: negative progress has no width to draw and anything over the
	// target has no more bar to fill, while the printed figures stay truthful.
	const width = Math.min(Math.max(p.progress_percent || 0, 0), 100);
	const percent = frappe.utils.escape_html(
		p.progress_percent === null ? "—" : `${p.progress_percent}%`
	);
	const outcome = frappe.utils.escape_html(__(p.outcome));
	const detail = footnotes(p).map(frappe.utils.escape_html).join(" · ");

	const bar = `background:var(--gray-200); border-radius:var(--border-radius-full); height:10px; margin:10px 0 8px; position:relative; overflow:hidden;`;
	const fill = `background:${color}; width:${width}%; height:100%; border-radius:var(--border-radius-full);`;

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${percent}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div style="${bar}">
				<div style="${fill}"></div>
				${pace_marker(p)}
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm);">${detail}</div>
		</div>
	`;
}

function pace_marker(p) {
	// Where the goal *should* be by now, if it is the kind of goal that has a pace at all.
	if (p.expected_percent === null || p.expected_percent === undefined) return "";

	const left = Math.min(Math.max(p.expected_percent, 0), 100);
	const style = `position:absolute; top:-2px; bottom:-2px; left:${left}%; width:2px; background:var(--text-color); opacity:0.45;`;
	const title = __("Expected by now");

	return `<div title="${title}" style="${style}"></div>`;
}

function footnotes(p) {
	const notes = [];
	const f = p.formatted || {};

	if (p.direction === "Limit") {
		notes.push(__("{0} of {1} spent", [f.current, f.target]));
		if (p.remaining < 0) notes.push(__("{0} over", [f.remaining]));
		else notes.push(__("{0} left", [f.remaining]));
	} else {
		notes.push(__("{0} of {1}", [f.current, f.target]));
		if (p.remaining > 0) notes.push(__("{0} to go", [f.remaining]));
	}

	if (p.days_left !== null && p.days_left !== undefined) {
		notes.push(p.days_left ? __("{0} days left", [p.days_left]) : __("deadline passed"));
	}
	if (p.required_per_period) {
		notes.push(__("needs {0} a day", [format_currency(p.required_per_period, p.currency)]));
	}
	return notes;
}
