// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Colours are keyed on the outcome words in services/recurring.py, not on dates. `Due` is
// the only one that wants attention: it means an occurrence's date has passed with nothing
// posted, which is a scheduler that has not run rather than a decision anybody made.
const OUTCOME_COLOR = {
	"Not Started": "var(--gray-400)",
	Scheduled: "var(--green-500)",
	Due: "var(--orange-500)",
	Paused: "var(--gray-400)",
	Archived: "var(--gray-400)",
	Ended: "var(--gray-400)",
};

// Kept in step with services/recurring.py:ACCOUNT_TO_ACCOUNT_TYPES by
// test_recurring.py:TestRecurringFormWiring, which reads this file off disk.
const ACCOUNT_TO_ACCOUNT_TYPES = ["Transfer", "Credit Card Payment"];

frappe.ui.form.on("Money Recurring Transaction", {
	setup(frm) {
		frm.set_query("category", () => {
			// The same three filters transaction.js applies, for the same reasons: the right side
			// of the books, this tracker only, and never a group — a heading holds no ledger
			// account, so an occurrence posted to one would fail every month at 3am.
			const filters = {
				category_type: frm.doc.transaction_type === "Income" ? "Income" : "Expense",
				is_group: 0,
			};
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});

		for (const field of ["account", "destination_account"]) {
			frm.set_query(field, () => {
				const filters = {};
				if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
				return { filters };
			});
		}
	},

	refresh(frm) {
		describe_schedule(frm);
		render_schedule(frm);
		add_post_button(frm);
	},

	transaction_type(frm) {
		// A retyped plan must not keep the other shape's field. The controller clears it
		// server-side too; doing it here as well means the form stops showing a value the
		// document is about to drop.
		if (ACCOUNT_TO_ACCOUNT_TYPES.includes(frm.doc.transaction_type)) {
			frm.set_value("category", null);
		} else {
			frm.set_value("destination_account", null);
		}
		describe_schedule(frm);
	},

	frequency(frm) {
		describe_schedule(frm);
	},

	start_date(frm) {
		describe_schedule(frm);
	},
});

function describe_schedule(frm) {
	// The month-end rule is the one thing about the schedule people do not expect, so the
	// field says it out loud on the days it matters.
	const day = frm.doc.start_date ? frappe.datetime.str_to_obj(frm.doc.start_date).getDate() : null;
	const monthly = ["Monthly", "Quarterly", "Yearly"].includes(frm.doc.frequency);

	let description = __("Every occurrence is counted from the Start Date.");
	if (monthly && day && day > 28) {
		description = __(
			"Counted from the Start Date, so the {0}th is kept in every month that has one and clamped to the last day in the months that do not.",
			[day]
		);
	}
	frm.set_df_property("start_date", "description", description);
}

function add_post_button(frm) {
	if (frm.is_new() || frm.doc.status !== "Active") return;

	frm.add_custom_button(__("Post Due Now"), () => {
		frm.call({
			doc: frm.doc,
			method: "post_due_now",
			freeze: true,
			freeze_message: __("Posting…"),
		}).then(({ message }) => {
			frappe.show_alert({ message: message.message, indicator: message.created.length ? "green" : "blue" });
			frm.reload_doc();
		});
	});
}

function render_schedule(frm) {
	const field = frm.get_field("progress_html");
	if (!field || frm.is_new()) return;

	frappe.call({
		method: "moneytracker.money_tracker.api.recurring.get_recurring_progress",
		args: { recurring_transaction: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(schedule_html(message));
		},
	});
}

function schedule_html(p) {
	const color = OUTCOME_COLOR[p.outcome] || "var(--gray-400)";
	const outcome = frappe.utils.escape_html(__(p.outcome));
	const headline = frappe.utils.escape_html(
		p.next_date ? frappe.datetime.str_to_user(p.next_date) : __("No further occurrences")
	);
	const caption = frappe.utils.escape_html(
		p.next_date ? __("Next {0}", [__(p.frequency_noun)]) : __("Ended")
	);

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${headline}</span>
				<span style="color:var(--text-muted); font-size:var(--text-sm);">${caption}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm); margin-top:6px;">
				${frappe.utils.escape_html(footnotes(p).join(" · "))}
			</div>
			${history_strip(p)}
		</div>
	`;
}

function footnotes(p) {
	const notes = [];
	const f = p.formatted || {};

	// The comparison a plan exists to make: what this one costs on a monthly clock, whatever
	// clock it actually runs on.
	notes.push(__("{0} a month", [f.monthly_equivalent]));

	if (p.posted_count) {
		notes.push(__("{0} posted, {1} in total", [p.posted_count, f.posted_total]));
	} else {
		notes.push(__("nothing posted yet"));
	}
	if (p.due_count) notes.push(__("{0} due now, {1}", [p.due_count, f.due_amount]));
	if (p.draft_count) notes.push(__("{0} left as draft", [p.draft_count]));
	if (p.cancelled_count) notes.push(__("{0} cancelled", [p.cancelled_count]));
	if (p.end_date) notes.push(__("ends {0}", [frappe.datetime.str_to_user(p.end_date)]));

	return notes;
}

function history_strip(p) {
	// What this plan has actually done, most recent last. A cancelled occurrence stays on the
	// strip: it is still a date the plan dealt with, and hiding it would make the plan look
	// like it had skipped a month.
	const history = (p.history || []).slice(-8);
	if (!history.length) return "";

	const pills = history
		.map((h) => {
			const border = h.state === "Cancelled" ? "var(--red-500)" : h.state === "Draft" ? "var(--orange-500)" : "var(--gray-400)";
			const label = frappe.utils.escape_html(frappe.datetime.str_to_user(h.date));
			const title = frappe.utils.escape_html(`${h.formatted_amount} · ${__(h.state)}`);
			const decoration = h.state === "Cancelled" ? "text-decoration:line-through;" : "";
			return `
				<a href="/app/transaction/${encodeURIComponent(h.transaction)}" title="${title}"
					style="border:1px solid ${border}; border-radius:var(--border-radius-full); padding:1px 8px;
					       font-size:var(--text-xs); color:var(--text-muted); ${decoration}">${label}</a>`;
		})
		.join("");

	return `
		<div style="margin-top:12px;">
			<div style="display:flex; gap:4px; flex-wrap:wrap;">${pills}</div>
			<div style="color:var(--text-muted); font-size:var(--text-xs); margin-top:6px;">
				${frappe.utils.escape_html(__("What this plan has posted"))}
			</div>
		</div>
	`;
}
