# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Idempotent site setup: roles and defaults.

Everything here is safe to re-run — it is called both from `after_install` and from a
patch, so a site that was installed before the patch existed converges to the same state.
"""

import frappe

# Tracker Owner / Tracker Member are deliberately NOT roles. Membership is row-level data
# (who is on which tracker), enforced by the permission hooks in moneytracker.permissions.
FINANCE_ROLES = (
	"Finance User",
	"Finance Manager",
	"Finance Admin",
	"Finance Viewer",
)


def create_finance_roles():
	for role_name in FINANCE_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)


def seed_money_settings():
	"""Point Money Settings at the site's Company so the app can resolve one at all.

	`company` and `base_currency` are mandatory and every posting path goes through
	`services.settings.get_company()`, so an unpopulated Single blocks the whole app. Only
	seeded when the site has exactly one Company — with several there is no safe guess, and
	silently picking the wrong one would post a user's books into somebody else's ledger.

	The CoA parent fields are deliberately left blank: `services.coa.resolve_parent_account`
	already falls back to well-known group names, and pinning them here would hardcode an
	assumption about which chart of accounts was installed.
	"""
	if frappe.db.get_single_value("Money Settings", "company"):
		return

	companies = frappe.get_all("Company", fields=["name", "default_currency"], limit=2)
	if len(companies) != 1:
		frappe.log_error(
			title="Money Settings not seeded",
			message=f"Expected exactly one Company, found {len(companies)}. Set Company in Money Settings manually.",
		)
		return

	company = companies[0]
	settings = frappe.get_doc("Money Settings")
	settings.company = company.name
	settings.base_currency = company.default_currency
	settings.flags.ignore_permissions = True
	settings.save()


def after_install():
	create_finance_roles()
	seed_money_settings()


def before_tests():
	"""Bring a bare site up to the minimum the suite needs, then say so if it cannot.

	Reuses the install path rather than adding a second seeding route. The Fiscal Year check
	is a hard stop on purpose: without one, ERPNext refuses every posting and the whole
	suite fails with an error that says nothing about the real cause.
	"""
	# Every fixture in the suite is built explicitly by moneytracker.tests.utils, so Frappe's
	# automatic test records buy nothing — and they are actively harmful here: the runner
	# walks link fields recursively, so a Money Account test drags in Account → Company →
	# … → Payment Gateway, which does not exist unless the payments app is installed, and
	# the whole run dies during collection.
	frappe.flags.skip_test_records = True

	create_finance_roles()
	seed_money_settings()
	frappe.db.commit()

	if not frappe.db.get_single_value("Money Settings", "company"):
		raise RuntimeError(
			"Money Settings has no Company. Every posting path throws without one — "
			"set it before running the tests."
		)
	if not frappe.db.count("Fiscal Year"):
		raise RuntimeError("No Fiscal Year on this site; ERPNext refuses every posting.")
