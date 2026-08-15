# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from dataclasses import dataclass


@dataclass(frozen=True)
class Leg:
	"""One side of a journal entry.

	`ledger_account` is an ERPNext Account. `money_account` is the user-facing account it
	came from, kept only so the engine can report a readable "against" description; it is
	not part of the accounting.
	"""

	ledger_account: str
	debit: float = 0.0
	credit: float = 0.0
	money_account: str | None = None
	party_type: str | None = None
	party: str | None = None

	def __post_init__(self):
		if self.debit and self.credit:
			raise ValueError("A leg carries either a debit or a credit, never both")
		if not self.debit and not self.credit:
			raise ValueError("A leg must carry a non-zero debit or credit")
