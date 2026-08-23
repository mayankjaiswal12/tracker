// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Keyed on the outcome words in services/subscriptions.py. A subscription runs the way a bill
// does rather than the way a goal does — closer is worse — with one word a bill cannot have:
// `Trial Ending`, the only state in this app where doing nothing costs money.
const OUTCOME_COLOR = {
	Active: "var(--green-500)",
	"Not Started": "var(--gray-500)",
	Trialing: "var(--blue-500)",
	"Trial Ending": "var(--orange-500)",
	"Cancel By": "var(--orange-500)",
	"Notice Passed": "var(--red-500)",
	"Renewing Soon": "var(--blue-500)",
	Paused: "var(--gray-400)",
	Cancelled: "var(--gray-400)",
	Expired: "var(--gray-400)",
};

frappe.ui.form.on("Money Subscription", {
	setup(frm) {
		// Money going out, and a leaf: the category is what a payment for this would be filed
		// under, and a transaction cannot post to a heading. The same rule Money Bill follows,
		// and deliberately stricter than Money Budget, which measures a subtree.
		frm.set_query("category", () => {
			const filters = { category_type: "Expense", is_group: 0 };
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});
		for (const field of ["account", "vendor"]) {
			frm.set_query(field, () =>
				frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {}
			);
		}
		// A subscription is paid, never received, so only an expense plan can be the thing
		// paying it. Python refuses the rest — this only keeps it out of the picker.
		frm.set_query("recurring_transaction", () => {
			const filters = { transaction_type: "Expense" };
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});
	},

	refresh(frm) {
		render_status(frm);
		add_buttons(frm);
	},
});

function add_buttons(frm) {
	if (frm.is_new()) return;

	frm.add_custom_button(__("Record Price Change"), () => record_price_change(frm));
	if (frm.doc.status !== "Cancelled") {
		frm.add_custom_button(__("Cancel Subscription"), () => cancel_subscription(frm));
	}
}

function record_price_change(frm) {
	// The date is asked for rather than assumed. A letter saying the price went up on the 1st
	// arrives on the 9th, and dating the change on the 9th would make the app disagree with the
	// vendor about what the last eight days cost.
	frappe.prompt(
		[
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("New Price"),
				reqd: 1,
				default: frm.doc.amount,
			},
			{
				fieldname: "effective_from",
				fieldtype: "Date",
				label: __("From"),
				reqd: 1,
				default: frappe.datetime.get_today(),
				description: __(
					"The day the new price started applying, not the day you found out."
				),
			},
			{ fieldname: "note", fieldtype: "Data", label: __("Note") },
		],
		(values) => {
			frm.call("record_price_change", values).then(({ message }) => {
				if (!message) return;
				frm.reload_doc();
				frappe.show_alert(
					{
						message: __("Price recorded. The history keeps the old one."),
						indicator: "green",
					},
					5
				);
			});
		},
		__("Price Change for {0}", [frm.doc.subscription_name]),
		__("Record")
	);
}

function cancel_subscription(frm) {
	frappe.prompt(
		[
			{
				fieldname: "effective_date",
				fieldtype: "Date",
				label: __("Runs Until"),
				reqd: 1,
				default: frm.doc.end_date || frappe.datetime.get_today(),
				description: __(
					"You keep paying until this date, so it stays in Subscription Spend until then."
				),
			},
		],
		(values) => {
			frm.call("cancel_subscription", values).then(({ message }) => {
				if (!message) return;
				frm.reload_doc();
				frappe.show_alert({ message: __("Cancelled."), indicator: "orange" }, 5);
			});
		},
		__("Cancel {0}", [frm.doc.subscription_name]),
		__("Cancel Subscription")
	);
}

function render_status(frm) {
	const field = frm.get_field("progress_html");
	if (!field || frm.is_new()) return;

	frappe.call({
		method: "moneytracker.money_tracker.api.subscriptions.get_subscription_progress",
		args: { subscription: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(status_html(message));
		},
	});
}

function status_html(s) {
	const color = OUTCOME_COLOR[s.outcome] || "var(--gray-400)";
	const outcome = frappe.utils.escape_html(__(s.outcome));
	const formatted = s.formatted || {};
	const amount = frappe.utils.escape_html(formatted.amount || "");
	const monthly = frappe.utils.escape_html(formatted.monthly_equivalent || "");
	const detail = footnotes(s).map(frappe.utils.escape_html).join(" · ");

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${amount}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm); margin-top:6px;">${detail}</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm);">${__("{0} a month", [
				monthly,
			])}</div>
		</div>
	`;
}

function footnotes(s) {
	const notes = [];

	if (s.in_trial) {
		notes.push(__("Trial ends {0}", [frappe.datetime.str_to_user(s.trial_end_date)]));
	}
	if (s.next_renewal) {
		notes.push(
			__("Renews {0} ({1} days)", [
				frappe.datetime.str_to_user(s.next_renewal),
				s.days_until_renewal,
			])
		);
	} else {
		notes.push(__("No further renewal"));
	}
	// The one date only a subscription knows, so it is worth saying even when it has passed.
	if (s.cancel_by) {
		const passed = s.days_until_cancel_by < 0;
		notes.push(
			passed
				? __("Notice window closed {0}", [frappe.datetime.str_to_user(s.cancel_by)])
				: __("Cancel by {0}", [frappe.datetime.str_to_user(s.cancel_by)])
		);
	}
	if (s.price_change) {
		notes.push(__("Was {0}", [(s.formatted || {}).price_change]));
	}
	if (s.plan_agrees === false) {
		notes.push(__("The plan paying it charges something else"));
	}
	return notes;
}
