// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Make a Number Card go to the rows it counted.
//
// Every card on this workspace is `type: "Custom"` — it has to be, because Frappe's built-in
// aggregation cannot reach `GL Entry`, cannot net refunds out of expense and would sum every
// tracker the reader can see. The cost of that choice is this file. Frappe routes a Custom card
// by reading a `route` off whatever the card's method returned
// (`number_card_widget.js:set_route_for_custom_card`), and **these methods return a formatted
// string** — deliberately, since a card that hands back a bare number is re-formatted in the
// browser against System Settings' currency instead of the tracker's. So the cards are styled
// `cursor: pointer` by Frappe's own CSS and, until this file existed, did nothing when clicked.
//
// Rather than give up the server-side formatting, the click is handled here: one delegated
// listener, and one table saying where each card's figure comes from. The table is keyed on the
// card's **label**, which is also its name and also the `number_card_name` the workspace block
// writes onto the wrapper — see the widget-label rule in CLAUDE.md.
//
// No tracker filter is applied anywhere below. `permissions.py` already scopes every list to the
// reader's own trackers, and naming one here would be a second, weaker copy of that rule.

frappe.provide("moneytracker.cards");

// Where a card's figure is measured from. `filters` may be a plain object or a function, for the
// ones whose window moves with the date.
//
// **A filter that cannot reproduce the card's own rule is left off** rather than approximated:
// sending somebody to a list that quietly disagrees with the number they clicked is worse than
// sending them to the whole list. `Subscription Spend` is the case — it counts a cancelled
// subscription that is still being paid for and skips one in a trial, and no list filter says
// that.
const CARD_ROUTES = {
	// Both of these span every account; they differ in how a liability is signed, which is
	// arithmetic and not a filter.
	"Total Balance": { doctype: "Money Account" },
	"Net Worth": { doctype: "Money Account" },

	"Income This Month": {
		doctype: "Transaction",
		filters: () => this_month({ transaction_type: "Income" }),
	},
	// Expense *and* Refund: a refund is a separate transaction type and the card nets it out, so
	// these two types together are exactly the rows the figure was measured from.
	"Expenses This Month": {
		doctype: "Transaction",
		filters: () => this_month({ transaction_type: ["in", ["Expense", "Refund"]] }),
	},
	// The month's income and spending side by side, since the rate is one divided by the other.
	"Savings Rate": { doctype: "Transaction", filters: () => this_month() },

	"Goals on Track": { doctype: "Money Goal", filters: { status: "Active" } },
	"Budgets on Track": { doctype: "Money Budget", filters: { status: "Active" } },
	"Plans Running": {
		doctype: "Money Recurring Transaction",
		filters: { status: "Active" },
	},
	"Fixed Costs": {
		doctype: "Money Recurring Transaction",
		filters: { status: "Active", transaction_type: "Expense" },
	},

	// The card's window is thirty days and always includes anything already overdue, however
	// old, which is what the open-ended lower bound says.
	"Bills Due": {
		doctype: "Money Bill",
		filters: () => ({ status: "Unpaid", due_date: ["<=", days_from_now(30)] }),
	},
	"Overdue Bills": {
		doctype: "Money Bill",
		filters: () => ({ status: "Unpaid", due_date: ["<", frappe.datetime.get_today()] }),
	},

	"Subscription Spend": { doctype: "Money Subscription" },
	// Every live trial. The card counts only those inside each subscription's own reminder
	// window, which is per-row and therefore not something a list filter can say.
	"Trials Ending": {
		doctype: "Money Subscription",
		filters: () => ({
			status: "Active",
			trial_end_date: [">=", frappe.datetime.get_today()],
		}),
	},

	// Borrowed only, because that is what the figure counts — money lent out is an asset and
	// adding the two would answer no question.
	"Debt Outstanding": {
		doctype: "Money Loan",
		filters: { status: "Active", direction: "Borrowed" },
	},
	"Loans in Arrears": { doctype: "Money Loan", filters: { status: "Active" } },
};

moneytracker.cards.routes = CARD_ROUTES;

function this_month(filters = {}) {
	return Object.assign(
		{ date: ["between", [frappe.datetime.month_start(), frappe.datetime.month_end()]] },
		filters
	);
}

function days_from_now(days) {
	return frappe.datetime.add_days(frappe.datetime.get_today(), days);
}

function card_label(body) {
	// The workspace block writes the label onto its own wrapper, above the widget. Read from
	// there rather than from the rendered title, which is translated.
	const wrapper = body.closest("[number_card_name]");
	return wrapper ? wrapper.getAttribute("number_card_name") : null;
}

$(document).on("click", ".widget.number-widget-box .widget-body", function (event) {
	// Customising the workspace: a click is a drag handle, not a link.
	if ($(this).closest(".widget").hasClass("edit-mode")) return;

	const label = card_label(this);
	const target = label && CARD_ROUTES[label];
	if (!target) return;

	event.stopPropagation();

	const filters = typeof target.filters === "function" ? target.filters() : target.filters || {};
	frappe.route_options = filters;
	frappe.set_route("List", target.doctype);
});
