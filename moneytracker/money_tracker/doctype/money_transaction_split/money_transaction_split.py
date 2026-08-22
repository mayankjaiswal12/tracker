# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MoneyTransactionSplit(Document):
	"""One category's share of one transaction.

	A supermarket run is 80% Groceries and 20% Household, and before this it had to be entered
	as two transactions against one receipt — which is a lie about how the money moved, and
	makes the bank line impossible to reconcile against the statement.

	`base_amount` is stored rather than derived, following `Transaction.base_amount`: the
	transaction's exchange rate is a fact about the day it happened, and recomputing a split's
	share against today's rate would quietly restate last year's category totals.

	**Not registered in `permissions.py`** — no `tracker` field, and a child row is reachable
	only through its parent, which is scoped. Same reasoning as `Money Transaction Tag`.
	"""

	pass
