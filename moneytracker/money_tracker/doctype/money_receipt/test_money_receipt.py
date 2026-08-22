# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""What a receipt refuses to save, and what it works out for itself."""

import frappe

from moneytracker.money_tracker.services import receipts as receipts_service
from moneytracker.tests.utils import (
	MoneyTrackerTestCase,
	make_account,
	make_category,
	make_receipt,
	make_tracker,
	make_transaction,
)


class TestMoneyReceipt(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.category = make_category(self.tracker, category_type="Expense").name

	def spend(self, **kwargs):
		return make_transaction(
			"Expense", 100, self.account, tracker=self.tracker, category=self.category, **kwargs
		)

	def test_it_is_named_by_series(self):
		self.assertTrue(make_receipt(self.tracker).name.startswith("RCP-"))

	def test_a_receipt_needs_a_file_or_an_image(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Money Receipt", "tracker": self.tracker, "title": "Nothing"}).insert(
				ignore_permissions=True
			)

	def test_it_can_exist_with_no_transaction_at_all(self):
		"""The reason this is not a child table: paper is captured before it is entered."""
		self.assertIsNone(make_receipt(self.tracker).transaction)

	def test_it_takes_its_tracker_from_the_transaction(self):
		transaction = self.spend()
		receipt = make_receipt(tracker=None, transaction=transaction.name)
		self.assertEqual(receipt.tracker, self.tracker)

	def test_a_transaction_from_another_tracker_is_refused(self):
		outsider = make_tracker().name
		other_account = make_account(outsider).name
		other_category = make_category(outsider, category_type="Expense").name
		theirs = make_transaction("Expense", 50, other_account, tracker=outsider, category=other_category)
		with self.assertRaises(frappe.ValidationError):
			make_receipt(self.tracker, transaction=theirs.name)

	def test_the_title_defaults_to_the_file_name(self):
		receipt = make_receipt(self.tracker, image="/files/dmart-bill.jpg", title=None)
		self.assertEqual(receipt.title, "dmart-bill.jpg")

	def test_an_image_gets_a_thumbnail_and_a_pdf_does_not(self):
		image = make_receipt(self.tracker, image="/files/bill.png")
		self.assertEqual(image.file_type, "Image")
		self.assertEqual(image.thumbnail, "/files/bill.png")

		pdf = make_receipt(self.tracker, image=None, file="/files/invoice.pdf")
		self.assertEqual(pdf.file_type, "PDF")
		self.assertIsNone(pdf.thumbnail)

	def test_the_scan_columns_start_empty(self):
		"""Nothing fills them yet — they exist so scanning needs no migration later."""
		receipt = make_receipt(self.tracker)
		self.assertEqual(receipt.ocr_status, "Not Scanned")
		self.assertFalse(receipt.extracted_amount)
		self.assertFalse(receipt.ocr_text)


class TestReceiptService(MoneyTrackerTestCase):
	def setUp(self):
		super().setUp()
		self.tracker = make_tracker().name
		self.account = make_account(self.tracker).name
		self.category = make_category(self.tracker, category_type="Expense").name
		self.transaction = make_transaction(
			"Expense", 100, self.account, tracker=self.tracker, category=self.category
		)

	def test_classify_reads_the_extension(self):
		self.assertEqual(receipts_service.classify("/files/a.JPG"), "Image")
		self.assertEqual(receipts_service.classify("/files/a.pdf"), "PDF")
		self.assertEqual(receipts_service.classify("/files/a.docx"), "Other")
		self.assertEqual(receipts_service.classify(None), "Other")

	def test_classify_ignores_a_query_string(self):
		self.assertEqual(receipts_service.classify("/files/a.png?v=2"), "Image")

	def test_get_receipts_returns_what_is_attached(self):
		make_receipt(self.tracker, transaction=self.transaction.name)
		make_receipt(self.tracker, transaction=self.transaction.name)
		self.assertEqual(len(receipts_service.get_receipts(self.transaction.name)), 2)

	def test_the_inbox_holds_only_unattached_ones(self):
		make_receipt(self.tracker, transaction=self.transaction.name)
		loose = make_receipt(self.tracker)
		inbox = [row["name"] for row in receipts_service.get_unattached(self.tracker)]
		self.assertEqual(inbox, [loose.name])

	def test_attaching_takes_it_out_of_the_inbox(self):
		loose = make_receipt(self.tracker)
		receipts_service.attach(loose.name, self.transaction.name)
		self.assertEqual(receipts_service.get_unattached(self.tracker), [])
		self.assertEqual(len(receipts_service.get_receipts(self.transaction.name)), 1)

	def test_counting_is_one_query_for_many_transactions(self):
		other = make_transaction("Expense", 50, self.account, tracker=self.tracker, category=self.category)
		make_receipt(self.tracker, transaction=self.transaction.name)
		make_receipt(self.tracker, transaction=self.transaction.name)
		make_receipt(self.tracker, transaction=other.name)

		counts = receipts_service.count_by_transaction([self.transaction.name, other.name])
		self.assertEqual(counts, {self.transaction.name: 2, other.name: 1})

	def test_counting_nothing_asks_nothing(self):
		self.assertEqual(receipts_service.count_by_transaction([]), {})
