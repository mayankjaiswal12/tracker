// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Keyed on the outcome words in services/loans.py. A loan reads like a bill rather than like a
// goal — behind is bad, on schedule is the good case and not an achievement.
const OUTCOME_COLOR = {
	"On Schedule": "var(--green-500)",
	"Not Started": "var(--gray-500)",
	"Not Disbursed": "var(--blue-500)",
	Due: "var(--orange-500)",
	"In Arrears": "var(--red-500)",
	Closed: "var(--gray-400)",
};

// Restated from services/loans.py, and tests/test_loans.py:TestFormWiring reads this file off
// disk and fails if either drifts. Borrowed money sits on a liability and its interest is
// expense; lent money sits on an asset and its interest is income. Getting either the wrong way
// round still balances, which is why the pickers are filtered as well as validated.
const BORROWED = "Borrowed";
const LIABILITY_ACCOUNT_TYPES = ["Loan", "Credit Card", "Other Liability"];

frappe.ui.form.on("Money Loan", {
	setup(frm) {
		frm.set_query("loan_account", () => {
			const filters = {};
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			// A loan you have taken is a liability; one you have given out is an asset, and
			// "not a liability" is the honest way to say that without listing every asset type.
			if (frm.doc.direction === BORROWED) {
				filters.account_type = ["in", LIABILITY_ACCOUNT_TYPES];
			} else {
				filters.account_type = ["not in", LIABILITY_ACCOUNT_TYPES];
			}
			return { filters };
		});

		frm.set_query("interest_category", () => {
			const filters = {
				is_group: 0,
				category_type: frm.doc.direction === BORROWED ? "Expense" : "Income",
			};
			if (frm.doc.tracker) filters.tracker = frm.doc.tracker;
			return { filters };
		});

		frm.set_query("counterparty", () =>
			frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {}
		);
	},

	direction(frm) {
		// Both pickers change sides with the direction, so anything already chosen is now on the
		// wrong one. Cleared rather than left to fail validation, which would otherwise refuse
		// the save and blame a field the user has not touched.
		frm.set_value("loan_account", null);
		frm.set_value("interest_category", null);
	},

	refresh(frm) {
		render_status(frm);
		add_buttons(frm);
	},
});

function add_buttons(frm) {
	if (frm.is_new()) return;

	if (frm.doc.status === "Closed") return;

	// Nothing can be repaid before the principal is on the books, so only one of these two is
	// ever the next thing to do.
	if (!frm.doc.disbursal_transaction) {
		frm.add_custom_button(__("Disburse"), () => disburse(frm)).addClass("btn-primary");
	} else {
		frm.add_custom_button(__("Post Instalment"), () => post_instalment(frm)).addClass(
			"btn-primary"
		);
	}
	frm.add_custom_button(__("Close Loan"), () => close_loan(frm));
}

function disburse(frm) {
	const borrowed = frm.doc.direction === BORROWED;
	frappe.prompt(
		[
			{
				fieldname: "account",
				fieldtype: "Link",
				label: borrowed ? __("Money Arrived In") : __("Money Went Out Of"),
				options: "Money Account",
				reqd: 1,
				get_query: () =>
					frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {},
			},
			{
				fieldname: "on_date",
				fieldtype: "Date",
				label: __("On"),
				default: frm.doc.start_date,
			},
		],
		(values) => {
			frm.call("disburse", values).then(({ message }) => {
				if (!message) return;
				frm.reload_doc();
				frappe.show_alert(
					{
						message: __("Principal of {0} is on the books. See {1}.", [
							format_currency(message.amount, frm.doc.currency),
							link("Transaction", message.transaction, __("the transfer")),
						]),
						indicator: "green",
					},
					7
				);
			});
		},
		__("Disburse {0}", [frm.doc.loan_name]),
		__("Disburse")
	);
}

function post_instalment(frm) {
	frappe.prompt(
		[
			{
				fieldname: "from_account",
				fieldtype: "Link",
				label: frm.doc.direction === BORROWED ? __("Paid From") : __("Received Into"),
				options: "Money Account",
				reqd: 1,
				get_query: () =>
					frm.doc.tracker ? { filters: { tracker: frm.doc.tracker } } : {},
			},
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				default: frm.doc.emi,
				description: __(
					"Anything above the scheduled instalment goes to principal — which is what a part-prepayment is."
				),
			},
			{
				fieldname: "paid_on",
				fieldtype: "Date",
				label: __("Date"),
				default: frappe.datetime.get_today(),
			},
		],
		(values) => {
			frm.call("post_instalment", values).then(({ message }) => {
				if (!message) return;
				frm.reload_doc();
				frappe.show_alert(
					{
						message: __(
							"Instalment {0} posted: {1} principal, {2} interest. See {3}.",
							[
								message.instalment,
								format_currency(message.principal, frm.doc.currency),
								format_currency(message.interest, frm.doc.currency),
								link("Transaction", message.transaction, __("the transaction")),
							]
						),
						indicator: "green",
					},
					7
				);
			});
		},
		__("Instalment on {0}", [frm.doc.loan_name]),
		__("Post")
	);
}

function close_loan(frm) {
	frappe.confirm(
		__("Mark {0} settled? This refuses if the ledger still says something is owed.", [
			frm.doc.loan_name,
		]),
		() =>
			frm.call("close").then(({ message }) => {
				if (!message) return;
				frm.reload_doc();
				frappe.show_alert({ message: __("Closed."), indicator: "green" }, 5);
			})
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
		method: "moneytracker.money_tracker.api.loans.get_loan_progress",
		args: { loan: frm.doc.name },
		callback: ({ message }) => {
			if (message) field.$wrapper.html(status_html(message));
		},
	});
}

function status_html(l) {
	const color = OUTCOME_COLOR[l.outcome] || "var(--gray-400)";
	const outcome = frappe.utils.escape_html(__(l.outcome));
	const formatted = l.formatted || {};
	const outstanding = frappe.utils.escape_html(formatted.outstanding || "");
	const percent = Math.max(0, Math.min(100, l.percent_repaid || 0));
	const detail = footnotes(l).map(frappe.utils.escape_html).join(" · ");

	return `
		<div style="padding: var(--padding-sm) 0;">
			<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">
				<span style="font-size:var(--text-2xl); font-weight:600;">${outstanding}</span>
				<span class="indicator-pill" style="background:${color}1a; color:${color};">${outcome}</span>
			</div>
			<div class="progress" style="height:6px; margin:10px 0 6px 0;">
				<div class="progress-bar" role="progressbar" style="width:${percent}%; background:${color};"></div>
			</div>
			<div style="color:var(--text-muted); font-size:var(--text-sm);">${detail}</div>
		</div>
	`;
}

function footnotes(l) {
	const formatted = l.formatted || {};
	if (!l.disbursed) {
		return [
			__("The principal is not on the books yet, so there is nothing to measure."),
			__("{0} over {1} instalments", [formatted.principal, l.instalments]),
		];
	}

	const notes = [__("{0}% of the principal repaid", [l.percent_repaid])];

	notes.push(__("{0} of {1} instalments paid", [l.paid_count, l.instalments]));
	if (l.arrears_count) {
		notes.push(__("{0} behind, {1} owing", [l.arrears_count, formatted.arrears_amount]));
	} else if (l.next_due) {
		notes.push(__("Next {0}", [frappe.datetime.str_to_user(l.next_due.due_date)]));
	}
	// The figure a schedule exists to show: what the borrowing costs in total.
	notes.push(__("{0} interest over the tenure", [formatted.total_interest]));
	if (l.interest_paid) {
		notes.push(__("{0} of it paid", [formatted.interest_paid]));
	}
	return notes;
}
