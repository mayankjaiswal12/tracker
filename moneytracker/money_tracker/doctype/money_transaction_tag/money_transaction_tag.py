# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MoneyTransactionTag(Document):
	"""One tag on one transaction — the join row behind a `Table MultiSelect`.

	It exists so that "spend by tag" is a GROUP BY over real rows. Frappe's own tagging keeps
	tags in `_user_tags`, a comma-joined text column: it filters, but it cannot be grouped or
	summed, so every tag report would be a LIKE scan. Core's `Tag Link`, which would fix that,
	is not in this Frappe version.

	**Deliberately not registered in `permissions.py`.** It carries no `tracker` field, so
	`tracker_scoped_query_conditions` would emit SQL against a column that is not there. A
	child row is reachable only through its parent, and the parent is scoped.
	"""

	pass
