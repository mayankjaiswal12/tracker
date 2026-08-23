// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// An Income transaction needs an income category, everything else an expense one — a Refund
// included, because a refund credits back the category the money was spent on.
const CATEGORY_TYPE_FOR = {
	Income: "Income",
};

frappe.ui.form.on("Transaction", {
	setup(frm) {
		// Groups are headings and hold no ledger account, so posting to one is refused
		// server-side. Filtering them out here means the choice never comes up.
		frm.set_query("category", () => ({
			filters: {
				is_group: 0,
				is_active: 1,
				tracker: frm.doc.tracker,
				category_type: CATEGORY_TYPE_FOR[frm.doc.transaction_type] || "Expense",
			},
		}));

		for (const field of ["account", "destination_account"]) {
			frm.set_query(field, () => ({ filters: { tracker: frm.doc.tracker } }));
		}

		// A fee is spending wherever it lands, so it takes an expense leaf whatever the
		// transaction type is — unlike `category` above, which follows the type.
		frm.set_query("fee_category", () => ({
			filters: {
				is_group: 0,
				is_active: 1,
				tracker: frm.doc.tracker,
				category_type: "Expense",
			},
		}));

		for (const field of ["merchant", "tags"]) {
			frm.set_query(field, () => ({ filters: { tracker: frm.doc.tracker } }));
		}

		// Split rows follow the transaction's own side of the books, the same rule `category`
		// follows — the server refuses anything else, and the picker should not offer it.
		frm.set_query("category", "splits", () => ({
			filters: {
				is_group: 0,
				is_active: 1,
				tracker: frm.doc.tracker,
				category_type: CATEGORY_TYPE_FOR[frm.doc.transaction_type] || "Expense",
			},
		}));
	},

	transaction_type(frm) {
		// The category list depends on the type, so a value chosen under the old one may no
		// longer be valid. Split rows are cleared for the same reason, and the fee with them:
		// only a movement between accounts can carry one.
		frm.set_value("category", null);
		frm.clear_table("splits");
		frm.refresh_field("splits");

		if (!["Transfer", "Credit Card Payment"].includes(frm.doc.transaction_type)) {
			frm.set_value("fee_amount", 0);
			frm.set_value("fee_category", null);
		}
	},
});
