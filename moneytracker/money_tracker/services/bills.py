# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Bills: money that is owed, tracked until it is settled.

**Where this stops, and why it is not `Money Recurring Transaction`.** A plan is a schedule
that posts by itself: rent leaves the account on the 1st whether anybody is looking or not,
and nothing is ever waiting on a human. A bill is a *claim* — it arrives, it has a due date,
and it stays open until somebody settles it. The two are not the same object wearing different
hats, and the giveaway is that a bill has a state a plan cannot have: **overdue**. A plan is
never overdue; if it has not posted, the scheduler is broken. A bill is overdue when a person
has not paid it, which is a fact about them and not about the software.

They compose rather than compete: a bill may name the plan that settles it, so a standing order
can pay the electricity and the bill still records that it was owed and is now not.

Outcomes are derived, never stored — the same rule goals, budgets and plans follow. `status` on
the document is the user's own decision (Unpaid / Paid / Skipped / Cancelled); whether an unpaid
bill is *Due Soon* or *Overdue* is read off the calendar every time it is asked for.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, getdate, today

from moneytracker.money_tracker.services import settings as settings_service

# Derived outcomes.
UPCOMING = "Upcoming"
DUE_SOON = "Due Soon"
DUE_TODAY = "Due Today"
OVERDUE = "Overdue"
PAID = "Paid"
SKIPPED = "Skipped"
CANCELLED = "Cancelled"

# What counts as nothing to worry about. `Due Soon` is deliberately not in it — that is the
# whole point of a reminder.
HEALTHY_OUTCOMES = (PAID, UPCOMING, SKIPPED, CANCELLED)
OPEN_STATUSES = ("Unpaid",)

DEFAULT_REMINDER_DAYS = 3


@dataclass(frozen=True)
class BillFrequency:
	"""How a bill repeats. `step` is one occurrence, as `add_to_date` keywords."""

	step: dict


NO_REPEAT = "Does Not Repeat"

# The same table `recurring.FREQUENCIES` keeps, minus the per-month arithmetic a bill has no
# use for, plus the one entry a plan cannot have: a bill that happens once.
FREQUENCIES = {
	NO_REPEAT: BillFrequency({}),
	"Daily": BillFrequency({"days": 1}),
	"Weekly": BillFrequency({"days": 7}),
	"Fortnightly": BillFrequency({"days": 14}),
	"Monthly": BillFrequency({"months": 1}),
	"Quarterly": BillFrequency({"months": 3}),
	"Yearly": BillFrequency({"years": 1}),
}
FREQUENCY_OPTIONS = tuple(FREQUENCIES)


def get_frequency(frequency):
	spec = FREQUENCIES.get(frequency or NO_REPEAT)
	if not spec:
		frappe.throw(
			_("{0} is not a bill frequency. Supported: {1}.").format(frequency, ", ".join(FREQUENCY_OPTIONS))
		)
	return spec


def measure(bill, as_of=None):
	"""One bill's outcome and the days between now and its due date.

	The user's own decision wins first — a bill they marked Paid or Cancelled is not overdue,
	whatever the calendar says, because reporting somebody's own decision back to them as a
	fault is the mistake `recurring.measure` was careful to avoid too.
	"""
	if isinstance(bill, str):
		bill = frappe.get_doc("Money Bill", bill)
	as_of = getdate(as_of or today())
	due = getdate(bill.due_date)
	days = (due - as_of).days

	if bill.status == "Paid":
		outcome = PAID
	elif bill.status == "Skipped":
		outcome = SKIPPED
	elif bill.status == "Cancelled":
		outcome = CANCELLED
	elif days < 0:
		outcome = OVERDUE
	elif days == 0:
		outcome = DUE_TODAY
	elif days <= (bill.reminder_days_before or DEFAULT_REMINDER_DAYS):
		outcome = DUE_SOON
	else:
		outcome = UPCOMING

	return frappe._dict(
		{
			"bill": bill.name,
			"bill_name": bill.bill_name,
			"tracker": bill.tracker,
			"status": bill.status,
			"outcome": outcome,
			"due_date": due,
			"days_until_due": days,
			"amount": flt(bill.amount),
			"amount_varies": bool(bill.amount_varies),
			"currency": bill.currency,
			"category": bill.category,
			"merchant": bill.merchant,
			"linked_transaction": bill.linked_transaction,
			"is_open": bill.status in OPEN_STATUSES,
		}
	)


def measure_bills(tracker, as_of=None, status=None):
	"""Every bill on a tracker, soonest first."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status

	names = frappe.get_all("Money Bill", filters=filters, order_by="due_date asc", pluck="name")
	return [measure(name, as_of) for name in names]


def get_upcoming(tracker, days=30, as_of=None):
	"""Open bills falling due within `days`, plus anything already overdue.

	Overdue bills are included however old they are: a bill nobody paid in March is more
	worth showing than one due next week, and dropping it out of the window would make it
	quietly disappear at exactly the point it started to matter.
	"""
	as_of = getdate(as_of or today())
	horizon = add_to_date(as_of, days=days)

	measured = [
		row for row in measure_bills(tracker, as_of, status="Unpaid") if row.due_date <= getdate(horizon)
	]
	measured.sort(key=lambda row: row.due_date)
	return measured


def get_total_due(tracker, days=30, as_of=None):
	"""What is owed over the window. A varying bill contributes nothing — its amount is unknown,
	and guessing last month's would be a figure nobody entered."""
	return flt(sum(row.amount for row in get_upcoming(tracker, days, as_of) if not row.amount_varies))


def next_due_date(bill, after=None):
	"""When this bill comes round again, or `None` if it does not.

	Stepped from the bill's own due date rather than from the day it was paid — paying the
	electricity late does not move the next bill.
	"""
	spec = get_frequency(bill.frequency)
	if not spec.step:
		return None

	nxt = getdate(add_to_date(getdate(after or bill.due_date), **spec.step))
	if bill.end_date and nxt > getdate(bill.end_date):
		return None
	return nxt


def send_bill_reminders(as_of=None):
	"""Daily: tell people about bills coming due, and about bills they have missed.

	Idempotent in the way `send_budget_alerts` is — a `<due_date>|<outcome>` stamp, so a fact
	is announced once and announced again only when it changes. An overdue bill therefore
	nags exactly once rather than every morning forever.
	"""
	as_of = getdate(as_of or today())
	sent = 0

	bills = frappe.get_all(
		"Money Bill",
		filters={"status": "Unpaid", "notify_on_due": 1},
		fields=["name", "tracker", "last_reminder"],
	)
	for row in bills:
		measured = measure(row.name, as_of)
		if measured.outcome not in (DUE_SOON, DUE_TODAY, OVERDUE):
			continue

		stamp = f"{measured.due_date}|{measured.outcome}"
		if row.last_reminder == stamp:
			continue

		owner = frappe.db.get_value("Tracker", row.tracker, "owner_user")
		if owner:
			_notify(measured, owner)
			sent += 1
		frappe.db.set_value("Money Bill", row.name, "last_reminder", stamp, update_modified=False)

	return sent


def _notify(measured, owner):
	if measured.outcome == OVERDUE:
		subject = _("{0} was due on {1}").format(measured.bill_name, measured.due_date)
	elif measured.outcome == DUE_TODAY:
		subject = _("{0} is due today").format(measured.bill_name)
	else:
		subject = _("{0} is due in {1} days").format(measured.bill_name, measured.days_until_due)

	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": owner,
			"type": "Alert",
			"document_type": "Money Bill",
			"document_name": measured.bill,
			"subject": subject,
		}
	).insert(ignore_permissions=True)
