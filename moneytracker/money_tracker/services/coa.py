# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Chart-of-accounts provisioning.

Every user-facing Money Account and Category is backed 1:1 by an ERPNext Account. Users
never see or pick a ledger account — this module creates it for them (spec §78: do not
expose the accounting model to ordinary users).
"""

import frappe
from frappe import _

from moneytracker.money_tracker.services import settings as settings_service

# Money Account type -> (root_type, ERPNext account_type, Money Settings parent field).
# ERPNext has no "Credit Card" account_type, so cards are Current Liability; the fact that
# a liability is a credit card is carried by Money Account.account_type, not by the ledger.
ACCOUNT_TYPE_MAP = {
	"Bank": ("Asset", "Bank", "bank_parent_account"),
	"Savings": ("Asset", "Bank", "bank_parent_account"),
	"Current Account": ("Asset", "Bank", "bank_parent_account"),
	"Cash": ("Asset", "Cash", "cash_parent_account"),
	"Wallet": ("Asset", "Cash", "cash_parent_account"),
	"Virtual": ("Asset", "Cash", "cash_parent_account"),
	"Investment": ("Asset", "", "current_asset_parent_account"),
	"Brokerage": ("Asset", "", "current_asset_parent_account"),
	"Fixed Deposit": ("Asset", "", "current_asset_parent_account"),
	"Recurring Deposit": ("Asset", "", "current_asset_parent_account"),
	"Insurance": ("Asset", "", "current_asset_parent_account"),
	"Property": ("Asset", "Fixed Asset", "fixed_asset_parent_account"),
	"Vehicle": ("Asset", "Fixed Asset", "fixed_asset_parent_account"),
	"Other Asset": ("Asset", "", "current_asset_parent_account"),
	"Credit Card": ("Liability", "", "liability_parent_account"),
	"Loan": ("Liability", "", "liability_parent_account"),
	"Other Liability": ("Liability", "", "liability_parent_account"),
}

# Fallback group accounts to look for when Money Settings has no explicit parent set.
# Matched against Account.account_name so the company abbreviation does not matter.
PARENT_FALLBACKS = {
	"bank_parent_account": ("Bank Accounts", "Current Assets", "Application of Funds (Assets)"),
	"cash_parent_account": ("Cash In Hand", "Current Assets", "Application of Funds (Assets)"),
	"current_asset_parent_account": ("Current Assets", "Application of Funds (Assets)",),
	"fixed_asset_parent_account": ("Fixed Assets", "Application of Funds (Assets)"),
	"liability_parent_account": ("Current Liabilities", "Source of Funds (Liabilities)"),
	"income_parent_account": ("Direct Income", "Income"),
	"expense_parent_account": ("Direct Expenses", "Expenses"),
	"receivable_parent_account": ("Accounts Receivable", "Current Assets"),
}

ROOT_TYPE_BY_PARENT_FIELD = {
	"bank_parent_account": "Asset",
	"cash_parent_account": "Asset",
	"current_asset_parent_account": "Asset",
	"fixed_asset_parent_account": "Asset",
	"receivable_parent_account": "Asset",
	"liability_parent_account": "Liability",
	"income_parent_account": "Income",
	"expense_parent_account": "Expense",
}


def resolve_parent_account(parent_field):
	"""Find the group Account new leaves hang off, preferring the configured value."""
	settings = settings_service.get_settings()
	configured = settings.get(parent_field)
	if configured:
		return configured

	company = settings_service.get_company()
	for account_name in PARENT_FALLBACKS.get(parent_field, ()):
		match = frappe.db.get_value(
			"Account", {"company": company, "account_name": account_name, "is_group": 1}, "name"
		)
		if match:
			return match

	# Last resort: the root group for this root_type.
	root_type = ROOT_TYPE_BY_PARENT_FIELD[parent_field]
	root = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": root_type, "is_group": 1, "parent_account": ""},
		"name",
	)
	if not root:
		frappe.throw(
			_("No {0} parent account found for Company {1}. Set {2} in Money Settings.").format(
				root_type, company, frappe.unscrub(parent_field)
			)
		)
	return root


def get_or_create_ledger_account(account_name, parent_field, account_type=None, currency=None):
	"""Return the name of a leaf ERPNext Account, creating it if absent.

	Idempotent: called from before_insert on Money Account and Category, and safe to
	re-run against an existing chart.
	"""
	company = settings_service.get_company()
	parent = resolve_parent_account(parent_field)
	root_type = ROOT_TYPE_BY_PARENT_FIELD[parent_field]

	# Matched without parent_account on purpose. ERPNext names an Account
	# "<account_name> - <abbr>" and ignores the parent, so the same name under a different
	# parent is not a second account — it is a primary-key collision. Including the parent
	# here would miss the existing row and then die on a duplicate insert.
	existing = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": account_name, "is_group": 0},
		"name",
	)
	if existing:
		return existing

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": company,
			"root_type": root_type,
			"is_group": 0,
			"account_type": account_type or None,
			"account_currency": currency or settings_service.get_base_currency(),
		}
	)
	account.insert(ignore_permissions=True)
	return account.name


def get_or_create_account_for_money_account(money_account):
	mapping = ACCOUNT_TYPE_MAP.get(money_account.account_type)
	if not mapping:
		frappe.throw(
			_("Account Type {0} has no ledger mapping. Add it to ACCOUNT_TYPE_MAP.").format(
				money_account.account_type
			)
		)

	_root_type, erpnext_account_type, parent_field = mapping
	return get_or_create_ledger_account(
		account_name=money_account.account_name,
		parent_field=parent_field,
		account_type=erpnext_account_type,
		currency=money_account.currency,
	)


def get_or_create_account_for_category(category):
	parent_field = "income_parent_account" if category.category_type == "Income" else "expense_parent_account"
	account_type = "Income Account" if category.category_type == "Income" else "Expense Account"
	return get_or_create_ledger_account(
		account_name=category.category_name,
		parent_field=parent_field,
		account_type=account_type,
	)


def is_liability(money_account_type):
	mapping = ACCOUNT_TYPE_MAP.get(money_account_type)
	return bool(mapping) and mapping[0] == "Liability"
