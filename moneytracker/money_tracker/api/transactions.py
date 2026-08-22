# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Whitelisted transaction API (spec §70).

Thin wrappers over the service layer. No accounting logic lives here — these methods
validate their inputs, delegate, and return. The frontend is never trusted (§71).
"""

import frappe
from frappe import _
from frappe.utils import today

from moneytracker.money_tracker.services import merchants as merchants_service
from moneytracker.money_tracker.services import tags as tags_service


def _create(transaction_type, **kwargs):
	doc = frappe.get_doc(
		{
			"doctype": "Transaction",
			"transaction_type": transaction_type,
			"date": kwargs.get("date") or today(),
			"amount": kwargs.get("amount"),
			"currency": kwargs.get("currency"),
			"account": kwargs.get("account"),
			"destination_account": kwargs.get("destination_account"),
			"category": kwargs.get("category"),
			"tracker": kwargs.get("tracker"),
			"merchant": kwargs.get("merchant"),
			"payee": kwargs.get("payee"),
			"payment_method": kwargs.get("payment_method"),
			"notes": kwargs.get("notes"),
			"time": kwargs.get("time"),
			"is_reimbursable": kwargs.get("is_reimbursable") or 0,
			"is_tax_deductible": kwargs.get("is_tax_deductible") or 0,
		}
	)
	doc.insert()
	doc.submit()
	return doc.as_dict()


@frappe.whitelist()
def create_expense(amount, account, category, date=None, **kwargs):
	"""Fast path for spec §6: amount, account, category, date and nothing else required."""
	return _create("Expense", amount=amount, account=account, category=category, date=date, **kwargs)


@frappe.whitelist()
def create_income(amount, account, category, date=None, **kwargs):
	return _create("Income", amount=amount, account=account, category=category, date=date, **kwargs)


@frappe.whitelist()
def create_transfer(amount, account, destination_account, date=None, **kwargs):
	return _create(
		"Transfer",
		amount=amount,
		account=account,
		destination_account=destination_account,
		date=date,
		**kwargs,
	)


@frappe.whitelist()
def create_credit_card_payment(amount, account, destination_account, date=None, **kwargs):
	"""`account` pays, `destination_account` is the card being settled."""
	return _create(
		"Credit Card Payment",
		amount=amount,
		account=account,
		destination_account=destination_account,
		date=date,
		**kwargs,
	)


@frappe.whitelist()
def create_refund(amount, account, category, date=None, **kwargs):
	return _create("Refund", amount=amount, account=account, category=category, date=date, **kwargs)


@frappe.whitelist()
def create_transaction(transaction_type, amount, account, **kwargs):
	"""Generic entry point for shortcut / automation callers (spec §41, §42)."""
	return _create(transaction_type, amount=amount, account=account, **kwargs)


@frappe.whitelist()
def reverse_transaction(transaction):
	doc = frappe.get_doc("Transaction", transaction)
	doc.check_permission("submit")
	return doc.reverse()


@frappe.whitelist()
def cancel_transaction(transaction):
	doc = frappe.get_doc("Transaction", transaction)
	doc.check_permission("cancel")
	doc.cancel()
	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def search_transactions(
	query=None,
	tracker=None,
	account=None,
	category=None,
	tags=None,
	transaction_type=None,
	from_date=None,
	to_date=None,
	min_amount=None,
	max_amount=None,
	limit=50,
	start=0,
):
	"""Global search (spec §39). Permission filters are applied by frappe.get_all."""
	filters = {"docstatus": 1}
	if tracker:
		filters["tracker"] = tracker
	if account:
		filters["account"] = account
	if category:
		filters["category"] = category
	if tags:
		# Resolved to names first rather than filtered on the child table inline, because the
		# filters here are a dict and a child-table filter needs list form. Two queries, and
		# the second one leaves every other filter working exactly as it did.
		tagged = tags_service.get_tagged_transactions(tags, tracker)
		if not tagged:
			return []
		filters["name"] = ["in", tagged]
	if transaction_type:
		filters["transaction_type"] = transaction_type
	if from_date and to_date:
		filters["date"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["date"] = [">=", from_date]
	elif to_date:
		filters["date"] = ["<=", to_date]
	if min_amount and max_amount:
		filters["amount"] = ["between", [min_amount, max_amount]]
	elif min_amount:
		filters["amount"] = [">=", min_amount]
	elif max_amount:
		filters["amount"] = ["<=", max_amount]

	or_filters = {}
	if query:
		like = f"%{query}%"
		or_filters = {"payee": ["like", like], "notes": ["like", like], "reference_no": ["like", like]}
		# `merchant` is a Link now, so the column holds MER-00007 and a LIKE against it would
		# match the ID rather than the name — silently returning nothing for every merchant
		# search. The names are resolved to IDs first and matched exactly.
		matches = merchants_service.search_names(query, tracker) if tracker else []
		if matches:
			or_filters["merchant"] = ["in", matches]

	return frappe.get_all(
		"Transaction",
		filters=filters,
		or_filters=or_filters,
		# Link fields are hash-named, so every one is returned with its readable title
		# alongside the ID — callers need the ID to navigate and the title to display.
		fields=[
			"name",
			"date",
			"transaction_type",
			"amount",
			"currency",
			"account",
			"account.account_name as account_name",
			"destination_account",
			"destination_account.account_name as destination_account_name",
			"category",
			"category.category_name as category_name",
			"merchant",
			"notes",
			"tracker",
			"tracker.tracker_name as tracker_name",
		],
		# Table-qualified: the dotted fields above make this a JOIN, and both `date` and
		# `creation` exist on the joined tables too.
		order_by="`tabTransaction`.`date` desc, `tabTransaction`.`creation` desc",
		limit_page_length=int(limit),
		limit_start=int(start),
	)
