# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from moneytracker.money_tracker.setup import seed_money_settings


def execute():
	"""Populate Money Settings on sites installed before `after_install` seeded it.

	Runs before the other v1_0 patches because anything that provisions a ledger account
	resolves the Company through Money Settings first.
	"""
	seed_money_settings()
