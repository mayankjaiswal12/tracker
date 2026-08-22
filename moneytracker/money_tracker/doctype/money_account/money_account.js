// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

frappe.ui.form.on("Money Account", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Reconcile"), () => reconcile(frm));
	},
});

function reconcile(frm) {
	// Ask for the two things a statement gives you, then show the difference. Nothing here
	// writes anything: reconciling is a comparison, and if it does not come out the answer is
	// a missing transaction rather than an adjustment (services/reconciliation.py).
	frappe.prompt(
		[
			{
				fieldname: "as_of",
				fieldtype: "Date",
				label: __("Statement Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "statement_balance",
				fieldtype: "Currency",
				label: __("Closing Balance On The Statement"),
				reqd: 1,
			},
		],
		(values) => show_reconciliation(frm, values),
		__("Reconcile {0}", [frm.doc.account_name]),
		__("Compare")
	);
}

function show_reconciliation(frm, values) {
	frappe.call({
		method: "moneytracker.money_tracker.api.reconciliation.get_reconciliation",
		args: { money_account: frm.doc.name, ...values },
		freeze: true,
		callback: ({ message }) => {
			if (message) render_dialog(frm, message);
		},
	});
}

function render_dialog(frm, result) {
	const dialog = new frappe.ui.Dialog({
		title: __("Reconcile {0}", [frm.doc.account_name]),
		size: "large",
		fields: [{ fieldname: "body", fieldtype: "HTML" }],
		primary_action_label: __("Mark Selected Reconciled"),
		primary_action: () => {
			const selected = dialog.$wrapper
				.find(".mt-uncleared:checked")
				.map((_, box) => box.value)
				.get();
			if (!selected.length) {
				frappe.msgprint(__("Nothing selected."));
				return;
			}
			frappe.call({
				method: "moneytracker.money_tracker.api.reconciliation.mark_reconciled",
				args: { transactions: JSON.stringify(selected), cleared_date: result.as_of },
				callback: () => {
					dialog.hide();
					frappe.show_alert(
						{ message: __("{0} ticked off.", [selected.length]), indicator: "green" },
						5
					);
					show_reconciliation(frm, {
						as_of: result.as_of,
						statement_balance: result.statement_balance,
					});
				},
			});
		},
	});

	dialog.fields_dict.body.$wrapper.html(reconciliation_html(result));
	dialog.show();
}

function reconciliation_html(r) {
	const f = r.formatted || {};
	// Zero is the whole point of the exercise, so it gets the colour rather than a tick.
	const settled = r.difference !== null && Math.abs(r.difference) < 0.005;
	const color = settled ? "var(--green-500)" : "var(--red-500)";

	const summary = `
		<div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:12px;">
			${figure(__("Books say"), f.book_balance)}
			${figure(__("Ticked off"), f.cleared_balance)}
			${figure(__("Statement says"), format_or_dash(r.statement_balance, r.currency))}
			${figure(__("Difference"), f.difference || "—", color)}
		</div>
		<p style="color:var(--text-muted);">
			${
				settled
					? __("This account agrees with the statement.")
					: __(
							"Tick off the lines that appear on the statement. If a difference is left over, a transaction is missing or wrong — there is no adjustment to make here."
					  )
			}
		</p>`;

	if (!r.uncleared.length) {
		return `${summary}<p>${__("Nothing left unticked.")}</p>`;
	}

	const rows = r.uncleared
		.map(
			(u) => `
			<tr>
				<td><input type="checkbox" class="mt-uncleared" value="${frappe.utils.escape_html(
					u.transaction
				)}"></td>
				<td>${frappe.datetime.str_to_user(u.date)}</td>
				<td>${frappe.utils.escape_html(__(u.transaction_type))}</td>
				<td>${frappe.utils.escape_html(u.reference_no || "")}</td>
				<td style="text-align:right;">${frappe.utils.escape_html(u.formatted_effect)}</td>
			</tr>`
		)
		.join("");

	return `${summary}
		<div style="max-height:340px; overflow:auto;">
			<table class="table table-sm">
				<thead><tr>
					<th style="width:32px;"></th><th>${__("Date")}</th><th>${__("Type")}</th>
					<th>${__("Reference")}</th><th style="text-align:right;">${__("Effect")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
}

function figure(label, value, color) {
	return `<div>
		<div style="color:var(--text-muted); font-size:var(--text-sm);">${label}</div>
		<div style="font-size:var(--text-lg); font-weight:600; ${
			color ? `color:${color};` : ""
		}">${frappe.utils.escape_html(value || "—")}</div>
	</div>`;
}

function format_or_dash(value, currency) {
	return value === null || value === undefined ? "—" : format_currency(value, currency);
}
