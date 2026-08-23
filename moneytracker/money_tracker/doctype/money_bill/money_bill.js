// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Keyed on the outcome words in services/bills.py, not on the number of days. A bill runs
// the way a budget does rather than the way a goal does: closer is worse.
const OUTCOME_COLOR = {
	Upcoming: "var(--gray-500)",
	"Due Soon": "var(--orange-500)",
	"Due Today": "var(--orange-500)",
	Overdue: "var(--red-500)",
	Paid: "var(--green-500)",
	Skipped: "var(--gray-400)",
	Cancelled: "var(--gray-400)",
};

frappe.ui.form.on("Money Bill", {
	setup(frm) {
		// A bill is money owed, so only an expense category will do — and only a leaf, since
		// Mark Paid copies this onto a Transaction and a transaction cannot post to a heading.
		// Deliberately stricter than Money Budget, which measures a subtree and takes a group.
		frm.set_query("category", () => {
			const filters = { category_type: "Expense", is_group: 0 };
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});
		for (const field of ["account", "merchant"]) {
			frm.set_query(field, () =>
				frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {}
			);
		}
	},

	refresh(frm) {
		render_status(frm);
		add_mark_paid(frm);
	},
});

function add_mark_paid(frm) {
	if (frm.is_new() || frm.doc.status !== "Unpaid") return;

	frm.add_custom_button(__("Mark Paid"), () => mark_paid(frm)).addClass("btn-primary");
}

function mark_paid(frm) {
	// The amount is asked for rather than assumed whenever the bill says it varies — an
	// electricity bill is entered before anybody knows the figure.
	const fields = [
		{
			fieldname: "amount",
			fieldtype: "Currency",
			label: __("Amount Paid"),
			reqd: 1,
			default: frm.doc.amount_varies ? null : frm.doc.amount,
			description: frm.doc.amount_varies
				? __("This bill's amount varies, so there is nothing to pre-fill.")
				: null,
		},
		{
			fieldname: "account",
			fieldtype: "Link",
			label: __("Paid From"),
			options: "Money Account",
			reqd: 1,
			default: frm.doc.account,
			get_query: () => (frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {}),
		},
		{
			fieldname: "paid_on",
			fieldtype: "Date",
			label: __("Paid On"),
			default: frappe.datetime.get_today(),
		},
	];

	frappe.prompt(
		fields,
		(values) => {
			frm.call("mark_paid", values).then(({ message }) => {
				if (!message) return;
				frm.reload_doc();

				// Two things happened, and both are worth saying: the money was recorded, and — if
				// this repeats — the next one already exists, so nobody goes looking for it.
				const links = [link("Transaction", message.transaction, __("the transaction"))];
				if (message.next_bill) {
					links.push(link("Money Bill", message.next_bill, __("the next bill")));
				}
				frappe.show_alert(
					{
						message: __("Paid. See {0}.", [links.join(__(" and "))]),
						indicator: "green",
					},
					7
				);
			});
		},
		__("Mark {0} Paid", [frm.doc.bill_name]),
		__("Record Payment")
	);
}

function link(doctype, name, label) {
	return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(
		name
	)}">${label}</a>`;
}

function render_status(frm) {
	const field = frm.get_field("progress_html");
	if (!field || frm.is_new()) return;

	frappe.call({
		method: "moneytracker.money_tracker.api.bills.get_bill_progress",
		args: { bill: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(status_html(message));
		},
	});
}

function status_html(b) {
	const color = OUTCOME_COLOR[b.outcome] || "var(--gray-400)";
	const outcome = frappe.utils.escape_html(__(b.outcome));
	const amount = frappe.utils.escape_html((b.formatted || {}).amount || "");
	const detail = footnotes(b).map(frappe.utils.escape_html).join(" · ");

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${amount}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm); margin-top:6px;">${detail}</div>
		</div>
	`;
}

function footnotes(b) {
	const notes = [];
	const days = b.days_until_due;

	if (b.outcome === "Paid") {
		notes.push(__("Paid"));
	} else if (days < 0) {
		notes.push(__("{0} days overdue", [Math.abs(days)]));
	} else if (days === 0) {
		notes.push(__("Due today"));
	} else {
		notes.push(__("Due in {0} days", [days]));
	}

	notes.push(__("Due {0}", [frappe.datetime.str_to_user(b.due_date)]));
	if (b.amount_varies) notes.push(__("Amount varies"));
	return notes;
}
