import frappe
from frappe import _
from frappe.utils import flt, today

ASSET_ROOT_TYPES = {
	"Cash": "Asset",
	"Wallet": "Asset",
	"Bank": "Asset",
	"Investment": "Asset",
	"Goal": "Asset",
	"Credit Card": "Liability",
	"Loan": "Liability",
}

# Asset/Expense accounts increase with a debit; Liability/Equity/Income accounts increase with a credit.
DEBIT_INCREASES = {"Asset", "Expense"}


def get_default_tracker():
	existing = frappe.db.get_value("Tracker", {"is_archived": 0}, "name", order_by="creation asc")
	if existing:
		return existing

	tracker = frappe.get_doc(
		{
			"doctype": "Tracker",
			"tracker_name": "Personal",
			"tracker_type": "Personal",
			"base_currency": "INR",
			"owner_user": frappe.session.user,
		}
	)
	tracker.insert(ignore_permissions=True)
	return tracker.name


def get_or_create_root_ledger_account(tracker, root_type):
	"""Each Tracker gets one group Ledger Account per root_type (Asset/Liability/Equity/Income/Expense),
	the parent every Account/Category-linked leaf Ledger Account hangs off."""
	name = frappe.db.get_value(
		"Ledger Account", {"tracker": tracker, "root_type": root_type, "is_group": 1}, "name"
	)
	if name:
		return name

	doc = frappe.get_doc(
		{
			"doctype": "Ledger Account",
			"account_name": root_type,
			"root_type": root_type,
			"is_group": 1,
			"tracker": tracker,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def create_leaf_ledger_account(tracker, account_name, root_type, account_subtype=None):
	parent = get_or_create_root_ledger_account(tracker, root_type)
	doc = frappe.get_doc(
		{
			"doctype": "Ledger Account",
			"account_name": account_name,
			"root_type": root_type,
			"account_subtype": account_subtype,
			"parent_ledger_account": parent,
			"is_group": 0,
			"tracker": tracker,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def adjust_account_balance(account_name, root_type, debit, credit):
	delta = flt(debit) - flt(credit)
	if root_type not in DEBIT_INCREASES:
		delta = -delta
	frappe.db.set_value(
		"Money Account",
		account_name,
		"current_balance",
		flt(frappe.db.get_value("Money Account", account_name, "current_balance")) + delta,
	)


def post_journal_entry(transaction):
	"""The kernel: atomically posts a balanced Money Journal Entry + two Money GL Entry rows
	for a Transaction. This is the ONLY code path that is allowed to create these two doctypes —
	both are permission-locked against direct Desk create for every other role."""

	if transaction.journal_entry:
		return  # already posted, never re-post

	account = frappe.get_doc("Money Account", transaction.account)
	amount = flt(transaction.amount)

	if transaction.transaction_type == "Expense":
		category = frappe.get_doc("Category", transaction.category)
		dr_ledger, dr_root = category.ledger_account, "Expense"
		cr_ledger, cr_root = account.ledger_account, ASSET_ROOT_TYPES[account.account_type]
		dr_account, cr_account = None, account.name
		against = account.name

	elif transaction.transaction_type == "Income":
		category = frappe.get_doc("Category", transaction.category)
		dr_ledger, dr_root = account.ledger_account, ASSET_ROOT_TYPES[account.account_type]
		cr_ledger, cr_root = category.ledger_account, "Income"
		dr_account, cr_account = account.name, None
		against = account.name

	elif transaction.transaction_type == "Transfer":
		destination = frappe.get_doc("Money Account", transaction.destination_account)
		dr_ledger, dr_root = destination.ledger_account, ASSET_ROOT_TYPES[destination.account_type]
		cr_ledger, cr_root = account.ledger_account, ASSET_ROOT_TYPES[account.account_type]
		dr_account, cr_account = destination.name, account.name
		against = f"{account.name} -> {destination.name}"

	else:
		frappe.throw(_("Unsupported transaction type: {0}").format(transaction.transaction_type))

	je = frappe.get_doc(
		{
			"doctype": "Money Journal Entry",
			"tracker": transaction.tracker,
			"transaction": transaction.name,
			"posting_date": transaction.date,
			"reference_type": transaction.transaction_type,
			"total_debit": amount,
			"total_credit": amount,
			"remarks": transaction.notes,
		}
	)
	je.insert(ignore_permissions=True)

	for ledger, acc, debit, credit, root in (
		(dr_ledger, dr_account, amount, 0, dr_root),
		(cr_ledger, cr_account, 0, amount, cr_root),
	):
		frappe.get_doc(
			{
				"doctype": "Money GL Entry",
				"journal_entry": je.name,
				"ledger_account": ledger,
				"account": acc,
				"tracker": transaction.tracker,
				"posting_date": transaction.date,
				"debit": debit,
				"credit": credit,
				"currency": transaction.currency,
				"against_account": against,
			}
		).insert(ignore_permissions=True)
		if acc:
			adjust_account_balance(acc, root, debit, credit)

	frappe.db.set_value("Transaction", transaction.name, "journal_entry", je.name)
	transaction.journal_entry = je.name


@frappe.whitelist()
def create_transaction(
	transaction_type, date, amount, account, category=None, destination_account=None, notes=None
):
	tracker = get_default_tracker()
	doc = frappe.get_doc(
		{
			"doctype": "Transaction",
			"tracker": tracker,
			"transaction_type": transaction_type,
			"date": date or today(),
			"amount": amount,
			"currency": "INR",
			"account": account,
			"category": category,
			"destination_account": destination_account,
			"notes": notes,
		}
	)
	doc.insert()
	return doc.as_dict()
