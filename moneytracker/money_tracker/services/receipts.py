# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Receipts: what is attached to a transaction, and what has not been attached to anything.

Deliberately thin. A receipt carries no money and takes part in no total, so there is nothing
here to reconcile against the ledger — which is why this is the shortest service in the app
and why it owns no arithmetic at all.
"""

import os

import frappe

IMAGE = "Image"
PDF = "PDF"
OTHER = "Other"

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".tiff")

# The scan lifecycle. Nothing advances a receipt through it yet; it is stated here so that
# whatever does later has one vocabulary to use rather than inventing a second one.
NOT_SCANNED = "Not Scanned"
QUEUED = "Queued"
SCANNED = "Scanned"
FAILED = "Failed"
CONFIRMED = "Confirmed"
OCR_STATUSES = (NOT_SCANNED, QUEUED, SCANNED, FAILED, CONFIRMED)


def classify(file_url):
	"""Image, PDF or Other, from the file's extension.

	Read from the name rather than the bytes on purpose: this decides how Desk previews the
	thing, and getting it wrong costs a thumbnail rather than anything that matters.
	"""
	if not file_url:
		return OTHER
	extension = os.path.splitext(file_url.split("?")[0])[1].lower()
	if extension in IMAGE_EXTENSIONS:
		return IMAGE
	if extension == ".pdf":
		return PDF
	return OTHER


def get_receipts(transaction):
	"""Every receipt attached to one transaction, oldest first."""
	return frappe.get_all(
		"Money Receipt",
		filters={"transaction": transaction},
		fields=["name", "title", "file", "image", "thumbnail", "file_type", "receipt_date", "ocr_status"],
		order_by="receipt_date asc, creation asc",
	)


def get_unattached(tracker, limit=50):
	"""Receipts nobody has linked to a transaction — the paper inbox.

	The reason `Money Receipt.transaction` is optional: a photograph taken at the till is
	worth keeping before anybody has typed the spending in, and this is how it is found again.
	"""
	return frappe.get_all(
		"Money Receipt",
		filters={"tracker": tracker, "transaction": ["is", "not set"]},
		fields=["name", "title", "file", "image", "thumbnail", "file_type", "receipt_date", "ocr_status"],
		order_by="receipt_date desc, creation desc",
		limit=limit,
	)


def attach(receipt, transaction):
	"""Link a captured receipt to the transaction somebody has now entered for it."""
	doc = frappe.get_doc("Money Receipt", receipt)
	doc.transaction = transaction
	doc.save()
	return doc.name


def count_by_transaction(transactions):
	"""How many receipts each of `transactions` has — one query, for a list view."""
	if not transactions:
		return {}
	rows = frappe.get_all(
		"Money Receipt",
		filters={"transaction": ["in", list(transactions)]},
		fields=["transaction", "COUNT(*) as receipts"],
		group_by="transaction",
	)
	return {row.transaction: row.receipts for row in rows}
