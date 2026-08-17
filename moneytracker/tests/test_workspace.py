# Copyright (c) 2026, Mayank Jaiswal and contributors
# For license information, please see license.txt

"""Whether the workspace's widgets actually render.

Every other fixture test in this suite checks that a card or chart *works* — that its method
is whitelisted, its source exists, its figures are right. None of them checked the last step:
that the workspace lays the widget out in a way Desk can find.

It could not, for the first two months of this app's life. `frappe/public/js/frappe/views/
workspace/blocks/block.js` resolves a content block like this:

    let block_data = this.config.page_data[block + "s"].items.find(
        (obj) => unescape_html(obj.label) == unescape_html(__(block_name))
    );
    if (!block_data) return false;      // renders nothing at all

`block_name` is the content block's `number_card_name` / `chart_name`, but it is matched
against the **label of the workspace's own child row** — and `desktop.py:get_number_cards`
sets that label from the child row, falling back to the widget's name. So a workspace that
names a card `Money Total Balance` in `content` while labelling it `Total Balance` in
`number_cards` renders a heading with nothing underneath, silently, with no console error and
no failing test. Six widgets did exactly that until 2026-08-17.

The label is also what the widget *prints* as its title (`base_widget.js:set_title` →
`this.title || this.label || this.name`), so it cannot be a prefixed internal name either.
Both constraints resolve the same way, and it is the way every workspace frappe and erpnext
ship already does it: **a widget's name is its label.**

These tests read the shipped JSON *and* the live site, because the two can disagree —
`import_file_by_path` skips a non-DocType file whose `modified` is not newer than the row
already in the database.
"""

import json

import frappe

from moneytracker.tests.utils import MoneyTrackerTestCase

# (content block type, the key it carries, the workspace child table, the link field on it)
WIDGET_KINDS = (
	("number_card", "number_card_name", "number_cards", "number_card_name"),
	("chart", "chart_name", "charts", "chart_name"),
)


def workspace_path():
	return frappe.get_app_path(
		"moneytracker", "money_tracker", "workspace", "money_tracker", "money_tracker.json"
	)


def shipped_workspace():
	with open(workspace_path()) as f:
		return json.load(f)


def blocks_of(workspace, block_type):
	return [b for b in json.loads(workspace["content"]) if b["type"] == block_type]


class TestWorkspaceWidgetsRender(MoneyTrackerTestCase):
	def test_every_widget_block_finds_its_row_the_way_desk_does(self):
		"""The exact lookup `block.js` performs. A miss renders nothing, so this is the whole bug."""
		workspace = shipped_workspace()

		for block_type, block_key, table, _link in WIDGET_KINDS:
			labels = [row["label"] for row in workspace[table]]
			for block in blocks_of(workspace, block_type):
				wanted = block["data"][block_key]
				with self.subTest(block=wanted):
					self.assertIn(
						wanted,
						labels,
						f"{wanted} is laid out in `content` but no {table} row is labelled that, "
						f"so block.js finds nothing and the widget renders as empty space",
					)

	def test_every_widget_is_named_what_it_is_labelled(self):
		"""What keeps the lookup working *and* the title readable.

		The label is matched against the name and printed as the title, so the two have to be
		the same string. Prefixing the record name — `Money Total Balance` — breaks the first;
		prefixing the label breaks the second.
		"""
		workspace = shipped_workspace()

		for _block_type, _block_key, table, link in WIDGET_KINDS:
			for row in workspace[table]:
				with self.subTest(widget=row[link]):
					self.assertEqual(row["label"], row[link])

	def test_every_row_points_at_a_widget_on_the_site(self):
		"""Laid out, labelled, and actually imported — `sync_dashboards` runs late in migrate."""
		workspace = shipped_workspace()

		for doctype, table, link in (
			("Number Card", "number_cards", "number_card_name"),
			("Dashboard Chart", "charts", "chart_name"),
		):
			for row in workspace[table]:
				with self.subTest(widget=row[link]):
					self.assertTrue(
						frappe.db.exists(doctype, row[link]),
						f"{row[link]} is missing — run `bench --site <site> migrate`",
					)

	def test_the_site_agrees_with_the_shipped_file(self):
		"""Guards the other half: a stale `modified` makes migrate a silent no-op.

		`import_file_by_path` skips any non-DocType file whose timestamp is not newer than the
		row in the database, so an edited workspace can migrate cleanly and change nothing —
		leaving the site laid out the old way while the repo looks correct.
		"""
		live = frappe.get_doc("Workspace", "Money Tracker")
		shipped = shipped_workspace()

		for _block_type, _block_key, table, link in WIDGET_KINDS:
			self.assertEqual(
				[(row.label, row.get(link)) for row in live.get(table)],
				[(row["label"], row[link]) for row in shipped[table]],
				f"the site's {table} differ from the shipped file — did `modified` get bumped?",
			)

		self.assertEqual(
			json.loads(live.content),
			json.loads(shipped["content"]),
			"the site's workspace layout differs from the shipped file",
		)

	def test_desk_would_render_every_widget(self):
		"""End to end, through Frappe's own API: what the browser is handed.

		`get_desktop_page` is what Desk calls, and its `items` are what `block.js` searches. If
		this passes, the widgets appear; if it fails, the workspace paints empty headings.
		"""
		from frappe.desk.desktop import get_desktop_page

		page = get_desktop_page(json.dumps({"name": "Money Tracker"}))
		workspace = shipped_workspace()

		for block_type, block_key, table, _link in WIDGET_KINDS:
			served = [frappe.utils.cstr(item.get("label")) for item in page[table]["items"]]
			for block in blocks_of(workspace, block_type):
				wanted = block["data"][block_key]
				with self.subTest(widget=wanted):
					self.assertIn(wanted, served, f"Desk serves no {table} row labelled {wanted}")
