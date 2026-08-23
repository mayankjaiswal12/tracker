# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Subscriptions: the terms of an arrangement, where a plan holds only its money.

**The boundary, and it was drawn before this module existed.** `services/recurring.py` says
it in so many words: a `Money Recurring Transaction` is the money and the calendar — this
amount, this account, this category, every month — and it knows nothing about *who* is being
paid or on what terms. This module owns exactly that other half: the vendor, the tier, the
trial that ends, the notice you have to give, and the price that went up in June. It **links
to** a plan for the money and grows no schedule of its own, which is why there is no posting
code below and no `generate()`.

So a subscription is the first thing in this app that is neither a measurement nor a posting.
Three consequences follow, and they are the whole design:

1. **It writes nothing to the ledger, ever.** The money either comes from the linked plan or
   from somebody paying by hand. That is what keeps `Subscription Spend` from double-counting
   `Fixed Costs`: the two figures are the same money seen twice, one by arrangement and one by
   standing order, in the way a tag total overlaps a category total.
2. **Price history is stored, and it is the one series in this app that has to be.** Every
   other figure is measured from `GL Entry` on read, because a stored copy drifts. A price
   cannot be: nothing in the ledger says Netflix went from 499 to 649 in June — a month
   somebody forgot to pay looks exactly like a month the price was zero. So
   `Money Subscription Price` is the source of truth for price, and `amount` on the parent is
   a cache of the current one, the same relationship `Money Account.current_balance` has with
   the ledger.
3. **Everything else is still derived.** The renewal date, the cancel-by date, the monthly
   equivalent and the outcome word are all worked out on read from the dates and the
   frequency. There is no stored next-renewal, exactly as a plan stores no next date.

**The frequency table is `recurring.FREQUENCIES`, deliberately not a second copy.** A
subscription's clock is the same clock a plan runs on, and two tables of the same six words
are two tables that will disagree.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, flt, getdate, today

from moneytracker.money_tracker.services import recurring

# Derived outcomes. Never stored — worked out from the dates on every read, and worded for an
# arrangement rather than for an envelope, a goal or a plan: a subscription is not something
# you are filling up or spending down, it is something that renews unless you stop it.
ACTIVE = "Active"
NOT_STARTED = "Not Started"
TRIALING = "Trialing"
TRIAL_ENDING = "Trial Ending"
CANCEL_BY = "Cancel By"
NOTICE_PASSED = "Notice Passed"
RENEWING_SOON = "Renewing Soon"
PAUSED = "Paused"
CANCELLED = "Cancelled"
EXPIRED = "Expired"

# Nothing to do about it today. `Trialing` is in here and `Trial Ending` is not, which is the
# only distinction that matters about a trial: one is free money, the other is a deadline.
HEALTHY_OUTCOMES = (ACTIVE, TRIALING, NOT_STARTED, PAUSED, CANCELLED, EXPIRED)

# The outcomes worth putting in front of somebody. `Notice Passed` is deliberately absent: it
# is a fact nobody can act on any more, and a reminder you cannot do anything about is noise.
ANNOUNCED_OUTCOMES = (TRIAL_ENDING, CANCEL_BY, RENEWING_SOON)

# The user's own decisions.
OPEN_STATUSES = ("Active",)

DEFAULT_REMINDER_DAYS = 7

# One month's worth of days, for the annual figure. Borrowed rather than restated.
FREQUENCY_OPTIONS = recurring.FREQUENCY_OPTIONS


def get_frequency(frequency):
	"""One row of `recurring.FREQUENCIES`, by name.

	Delegated rather than duplicated: a subscription billed quarterly and a plan running
	quarterly are on the same calendar, and keeping one table means adding a frequency in one
	place.
	"""
	return recurring.get_frequency(frequency)


# --- price -----------------------------------------------------------------------------


def price_rows(subscription):
	"""The price history oldest first, as (date, amount, note) dicts.

	Sorted here rather than trusted from the grid: a row added by hand for a rise somebody is
	recording after the fact lands at the bottom of the table and is not the newest price.
	"""
	rows = [
		frappe._dict(
			{
				"effective_from": getdate(row.effective_from),
				"amount": flt(row.amount),
				"note": row.get("note"),
			}
		)
		for row in (subscription.get("price_history") or [])
		if row.effective_from
	]
	rows.sort(key=lambda row: row.effective_from)
	return rows


def price_at(subscription, as_of=None):
	"""What it cost on `as_of` — the newest price that had started applying by then.

	Falls back to the current `amount` when the history says nothing about a date, which is
	the case for any date before the first recorded price. Reading zero there would be worse
	than reading the current figure: it would claim the thing was free.
	"""
	as_of = getdate(as_of or today())
	applicable = [row for row in price_rows(subscription) if row.effective_from <= as_of]
	if not applicable:
		return flt(subscription.amount)
	return flt(applicable[-1].amount)


def current_price(subscription):
	return price_at(subscription, today())


def price_change(subscription):
	"""How much the price has moved since the first one recorded, as an amount and a percent.

	`None` when there is only one price on record — a subscription that has never gone up has
	no rise to report, and reporting 0% would suggest somebody checked and it held.
	"""
	rows = price_rows(subscription)
	if len(rows) < 2:
		return None

	first, latest = rows[0].amount, rows[-1].amount
	return frappe._dict(
		{
			"from_amount": first,
			"to_amount": latest,
			"from_date": rows[0].effective_from,
			"to_date": rows[-1].effective_from,
			"delta": flt(latest - first),
			"percent": flt((latest - first) / first * 100, 1) if first else None,
			"changes": len(rows) - 1,
		}
	)


# --- the calendar ----------------------------------------------------------------------


def billing_start(subscription):
	"""The day the *charges* start, which is not the day the arrangement started.

	A free trial means the first charge lands the day after it ends, so the whole billing
	calendar is anchored there. Anchoring on `start_date` instead and treating the trial as a
	special case in every caller would give a subscription two calendars, one during the trial
	and one after it, that disagree about which day of the month it renews on.
	"""
	if subscription.trial_end_date:
		return getdate(add_days(getdate(subscription.trial_end_date), 1))
	return getdate(subscription.start_date)


def next_renewal(subscription, after=None):
	"""The next date it will be charged, or `None` once it is over.

	`recurring.next_date` does the arithmetic, which means a subscription billed on the 31st
	gets the same month-end rule a standing order gets: 31 Jan → 28 Feb → **31** Mar, because
	every occurrence is counted from the anchor rather than stepped off the last one.
	"""
	return recurring.next_date(
		frappe._dict(
			{
				"start_date": billing_start(subscription),
				"frequency": subscription.billing_frequency,
				"end_date": subscription.end_date,
			}
		),
		after,
	)


def cancel_by(subscription, after=None):
	"""The last day you can give notice and not be charged again. `None` without a notice
	period, because then there is nothing to be late for.

	This is the one date only a subscription knows. A plan cannot have it — a standing order
	has no counterparty and nothing to give notice to — and it is the reason somebody writes
	an annual subscription down months before they care what it costs.
	"""
	days = int(subscription.notice_period_days or 0)
	if days <= 0:
		return None

	renewal = next_renewal(subscription, after)
	if not renewal:
		return None
	return getdate(add_days(renewal, -days))


# --- measurement -----------------------------------------------------------------------


def measure(subscription, as_of=None):
	"""Every derived figure for one subscription, as a `frappe._dict`.

	`as_of` moves the whole measurement in time, the same handle every other service in this
	app offers, which is what makes the outcome words testable without waiting for a renewal.
	"""
	subscription = (
		subscription
		if hasattr(subscription, "doctype")
		else frappe.get_doc("Money Subscription", subscription)
	)
	spec = get_frequency(subscription.billing_frequency)
	as_of = getdate(as_of or today())

	price = price_at(subscription, as_of)
	renewal = next_renewal(subscription, as_of)
	notice_date = cancel_by(subscription, as_of)
	trial_end = getdate(subscription.trial_end_date) if subscription.trial_end_date else None

	result = frappe._dict(
		{
			"subscription": subscription.name,
			"subscription_name": subscription.subscription_name,
			"tracker": subscription.tracker,
			"status": subscription.status,
			"vendor": subscription.vendor,
			"plan_name": subscription.plan_name,
			"category": subscription.category,
			"account": subscription.account,
			"currency": subscription.currency,
			"color": subscription.color,
			"billing_frequency": subscription.billing_frequency,
			"frequency_noun": spec.noun,
			"recurring_transaction": subscription.recurring_transaction,
			"as_of": as_of,
			"amount": price,
			# What it costs in an average month whatever it is billed on — the one figure that
			# lets a yearly domain renewal be compared with a monthly music service.
			"monthly_equivalent": flt(price * spec.per_month, 2),
			"annual_equivalent": flt(price * spec.per_month * 12, 2),
			"start_date": getdate(subscription.start_date),
			"billing_start": billing_start(subscription),
			"trial_end_date": trial_end,
			"end_date": getdate(subscription.end_date) if subscription.end_date else None,
			"notice_period_days": int(subscription.notice_period_days or 0),
			"reminder_days_before": int(subscription.reminder_days_before or DEFAULT_REMINDER_DAYS),
			"next_renewal": renewal,
			"days_until_renewal": (renewal - as_of).days if renewal else None,
			"cancel_by": notice_date,
			"days_until_cancel_by": (notice_date - as_of).days if notice_date else None,
			"in_trial": bool(trial_end and as_of <= trial_end),
			"days_until_trial_end": (trial_end - as_of).days if trial_end else None,
			"price_change": price_change(subscription),
			"prices_recorded": len(price_rows(subscription)),
		}
	)

	result.outcome = _outcome(result)
	result.is_committed = _is_committed(result)
	result.plan_agrees = _plan_agrees(subscription, price)
	return result


def _outcome(row):
	"""The single word for where an arrangement stands.

	The user's own decision wins first, the same rule plans, budgets and bills follow: a
	subscription somebody cancelled is not renewing next week, whatever the calendar says.
	Then the facts about the window, then the trial — because a trial ending is the sharpest
	deadline a subscription has and the one thing this doctype exists to catch — and only then
	the notice and renewal states.
	"""
	if row.status == "Cancelled":
		return CANCELLED
	if row.status == "Paused":
		return PAUSED
	if row.end_date and row.end_date < row.as_of:
		return EXPIRED
	if row.start_date > row.as_of:
		return NOT_STARTED

	reminder = row.reminder_days_before
	if row.in_trial:
		return TRIAL_ENDING if row.days_until_trial_end <= reminder else TRIALING

	if row.notice_period_days > 0 and row.cancel_by:
		if row.days_until_cancel_by < 0:
			# The window shut: this renewal is happening whether or not anybody wanted it.
			return NOTICE_PASSED
		if row.days_until_cancel_by <= reminder:
			return CANCEL_BY

	if row.next_renewal and row.days_until_renewal <= reminder:
		return RENEWING_SOON
	return ACTIVE


def _is_committed(row):
	"""Whether this subscription's price belongs in a spend figure.

	Decided by the **dates**, not by the outcome word, and the difference is the case that
	matters: a subscription cancelled in March with a notice period running to June is still
	being paid for until June. Reading `Cancelled` and dropping it out of the figure on the day
	somebody clicked the button would understate three months of real money.

	A trial contributes **nothing**: nobody is paying for it yet, and counting what it will
	cost afterwards reports money that has not been committed to as though it had. A
	subscription that has not started yet *is* counted, the same call `get_fixed_costs` makes —
	an annual renewal beginning next month is a commitment now, which is the whole reason
	somebody writes it down in advance.
	"""
	if row.status == "Paused" or row.in_trial:
		return False
	# Cancelled with no end date is cancelled as of now: they stopped it and did not say when.
	if row.status == "Cancelled" and not row.end_date:
		return False
	if row.end_date and row.end_date < row.as_of:
		return False
	return True


def _plan_agrees(subscription, price):
	"""Whether the linked standing order still charges what the subscription says it costs.

	Reported rather than refused. A price rise is known before the plan is updated — that is
	the normal order of events, not a mistake — so the form says the two disagree and leaves
	fixing it to somebody who knows which one is right. Refusing the save would mean the price
	could not be recorded until the plan had already been changed.
	"""
	if not subscription.recurring_transaction:
		return None

	plan = frappe.db.get_value(
		"Money Recurring Transaction",
		subscription.recurring_transaction,
		["amount", "frequency"],
		as_dict=True,
	)
	if not plan:
		return None
	return flt(plan.amount) == flt(price) and plan.frequency == subscription.billing_frequency


def measure_subscriptions(tracker, as_of=None, status=None):
	"""Every subscription on a tracker, dearest per month first."""
	filters = {"tracker": tracker}
	if status:
		filters["status"] = status

	names = frappe.get_all(
		"Money Subscription", filters=filters, order_by="amount desc, subscription_name asc", pluck="name"
	)
	measured = [measure(name, as_of) for name in names]
	measured.sort(key=lambda row: row.monthly_equivalent, reverse=True)
	return measured


def get_subscription_spend(tracker, as_of=None):
	"""What the tracker's live subscriptions cost in an average month.

	**Deliberately the same money `Fixed Costs` may already be counting.** A subscription paid
	by a standing order appears in both, and that is not a bug to be netted out: the two
	figures answer different questions — "what leaves the account every month" and "what am I
	subscribed to" — and a household cancels a subscription, not a standing order. It is the
	same overlap a tag total has with a category total, and it is honest for the same reason:
	nothing sums the two together.
	"""
	as_of = getdate(as_of or today())
	monthly = 0.0
	counted = 0
	trials = 0

	for row in measure_subscriptions(tracker, as_of):
		if row.in_trial:
			trials += 1
			continue
		if not row.is_committed:
			continue
		monthly += row.monthly_equivalent
		counted += 1

	return frappe._dict(
		{
			"tracker": tracker,
			"as_of": as_of,
			"monthly": flt(monthly, 2),
			"annual": flt(monthly * 12, 2),
			"subscriptions": counted,
			"in_trial": trials,
		}
	)


def get_renewals(tracker, days=30, as_of=None, status="Active"):
	"""Live subscriptions charging again inside the window, soonest first.

	The shape *Subscriptions by Renewal* will read when `report/` exists (A3). Built here
	rather than in the report so the figure has one implementation, the way every card in this
	app reads a service rather than counting for itself.
	"""
	as_of = getdate(as_of or today())
	horizon = getdate(add_to_date(as_of, days=int(days)))

	upcoming = [
		row
		for row in measure_subscriptions(tracker, as_of, status)
		if row.next_renewal and row.next_renewal <= horizon
	]
	upcoming.sort(key=lambda row: row.next_renewal)
	return upcoming


def get_trials_ending(tracker, days=None, as_of=None):
	"""Trials whose free period runs out inside the reminder window.

	The one thing a subscription tracker is actually for: a trial nobody cancels becomes a
	charge, and it is the only state in this app where doing nothing costs money.
	"""
	as_of = getdate(as_of or today())
	ending = []
	for row in measure_subscriptions(tracker, as_of, "Active"):
		if not row.in_trial:
			continue
		window = int(days) if days is not None else row.reminder_days_before
		if row.days_until_trial_end <= window:
			ending.append(row)
	ending.sort(key=lambda row: row.trial_end_date)
	return ending


# --- the daily job ---------------------------------------------------------------------


def send_subscription_reminders(as_of=None):
	"""Daily: a trial about to end, a notice window about to shut, a renewal about to land.

	Idempotent in the way `send_budget_alerts` and `send_bill_reminders` are — a
	`<date>|<outcome>` stamp, so a fact is announced once and announced again only when it
	changes. Which is the whole reason `last_reminder` is allowed to be the one mutable field
	here: it is bookkeeping about a message, not about the arrangement.
	"""
	as_of = getdate(as_of or today())
	sent = 0

	rows = frappe.get_all(
		"Money Subscription",
		filters={"status": "Active", "notify_on_renewal": 1},
		fields=["name", "tracker", "last_reminder"],
	)
	for row in rows:
		measured = measure(row.name, as_of)
		if measured.outcome not in ANNOUNCED_OUTCOMES:
			continue

		key_date = measured.trial_end_date if measured.outcome == TRIAL_ENDING else measured.next_renewal
		stamp = f"{key_date}|{measured.outcome}"
		if row.last_reminder == stamp:
			continue

		owner = frappe.db.get_value("Tracker", row.tracker, "owner_user")
		if owner:
			_notify(measured, owner)
			sent += 1
		frappe.db.set_value("Money Subscription", row.name, "last_reminder", stamp, update_modified=False)

	return sent


def _notify(measured, owner):
	if measured.outcome == TRIAL_ENDING:
		subject = _("{0}'s free trial ends on {1}").format(
			measured.subscription_name, measured.trial_end_date
		)
	elif measured.outcome == CANCEL_BY:
		subject = _("Cancel {0} by {1} to avoid the renewal on {2}").format(
			measured.subscription_name, measured.cancel_by, measured.next_renewal
		)
	else:
		subject = _("{0} renews on {1}").format(measured.subscription_name, measured.next_renewal)

	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": owner,
			"type": "Alert",
			"document_type": "Money Subscription",
			"document_name": measured.subscription,
			"subject": subject,
		}
	).insert(ignore_permissions=True)
