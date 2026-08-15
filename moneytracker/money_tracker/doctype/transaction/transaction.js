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
	},

	transaction_type(frm) {
		// The category list depends on the type, so a value chosen under the old one may no
		// longer be valid.
		frm.set_value("category", null);
	},
});
