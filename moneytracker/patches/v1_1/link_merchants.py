# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

import frappe

# Every doctype whose `merchant` column has just become a Link. Both are migrated in one pass
# so a tracker's two sources of merchant names resolve to the same masters — a plan named
# "MSEDCL" and the transactions it posted must not end up pointing at two different records.
DOCTYPES = ("Transaction", "Money Recurring Transaction")


def execute():
	"""Turn the free-text `merchant` strings into `Money Merchant` records.

	`merchant` was a `Data` field, so the column holds whatever anybody typed. It is now a Link,
	and the column has to hold a `Money Merchant` name instead.

	**Backfilled verbatim, one master per distinct string per tracker. Nothing is guessed.**
	The demo household alone carries "Netflix, Spotify", "Auto, bus" and "IRCTC, hotel" — the
	field has been used as a note as much as a name. Splitting those on the comma is tempting
	and wrong: it would invent two merchants from one string, and "hotel" and "bus" are not
	merchants under any reading. A master called "Netflix, Spotify" is at least *true* — it
	records what was written — and merging two merchants later is a decision somebody makes on
	purpose, not one a migration makes silently at three in the morning.

	Scoped per tracker because `Money Merchant` is, so two households that both shopped at DMart
	get one record each rather than sharing one. Same trade `Category` already makes.

	Re-runnable. A value that is already a `Money Merchant` name is left alone, so a partial run
	simply continues, and a second full run does nothing.
	"""
	if not frappe.db.exists("DocType", "Money Merchant"):
		return

	created = migrated = 0
	# (tracker, lowercased name) -> Money Merchant. Lowercased because the controller treats
	# names case-insensitively, so "DMart" and "dmart" must resolve to the same record here
	# too — otherwise the second insert throws and the patch dies half way.
	cache = {}

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue

		rows = frappe.get_all(
			doctype,
			filters={"merchant": ["is", "set"]},
			fields=["name", "tracker", "merchant"],
		)
		for row in rows:
			raw = (row.merchant or "").strip()
			if not raw or frappe.db.exists("Money Merchant", raw):
				# Already a link, or an empty string masquerading as a value.
				continue

			key = (row.tracker, raw.lower())
			merchant = cache.get(key)
			if not merchant:
				merchant = frappe.db.get_value(
					"Money Merchant", {"tracker": row.tracker, "merchant_name": raw}, "name"
				)
			if not merchant:
				doc = frappe.get_doc(
					{
						"doctype": "Money Merchant",
						"merchant_name": raw,
						"tracker": row.tracker,
					}
				)
				doc.insert(ignore_permissions=True)
				merchant = doc.name
				created += 1
			cache[key] = merchant

			# Direct, and deliberately so: these rows are submitted, and this is a
			# representation change rather than a change to the money. `update_modified` stays
			# off so a migration does not look like somebody editing every transaction.
			frappe.db.set_value(doctype, row.name, "merchant", merchant, update_modified=False)
			migrated += 1

	if created or migrated:
		print(f"Linked {migrated} merchant references to {created} Money Merchant records")
