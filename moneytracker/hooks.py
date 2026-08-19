app_name = "moneytracker"
app_title = "Money Tracker"
app_publisher = "Mayank Jaiswal"
app_description = "A personal finance tracker with a double-entry ledger core"
app_email = "mayank.j@vidarbhainfotech.com"
app_license = "mit"

# Apps
# ------------------

# The ledger is ERPNext's (Account / Journal Entry / GL Entry). Declaring the dependency
# makes a missing ERPNext fail at install time rather than at the first posting attempt.
required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "moneytracker",
# 		"logo": "/assets/moneytracker/logo.png",
# 		"title": "Money Tracker",
# 		"route": "/moneytracker",
# 		"has_permission": "moneytracker.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/moneytracker/css/moneytracker.css"
# app_include_js = "/assets/moneytracker/js/moneytracker.js"

# include js, css files in header of web template
# web_include_css = "/assets/moneytracker/css/moneytracker.css"
# web_include_js = "/assets/moneytracker/js/moneytracker.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "moneytracker/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "moneytracker/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "moneytracker.utils.jinja_methods",
# 	"filters": "moneytracker.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "moneytracker.install.before_install"
after_install = "moneytracker.money_tracker.setup.after_install"

# Uninstallation
# ------------

# before_uninstall = "moneytracker.uninstall.before_uninstall"
# after_uninstall = "moneytracker.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "moneytracker.utils.before_app_install"
# after_app_install = "moneytracker.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "moneytracker.utils.before_app_uninstall"
# after_app_uninstall = "moneytracker.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "moneytracker.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# All finance data lives in one shared ERPNext Company, so row-level scoping by Tracker is
# the ONLY thing isolating one user's books from another's. These hooks are load-bearing
# security, not a convenience — see moneytracker/money_tracker/permissions.py.
permission_query_conditions = {
	"Tracker": "moneytracker.money_tracker.permissions.tracker_query_conditions",
	"Transaction": "moneytracker.money_tracker.permissions.tracker_scoped_query_conditions",
	"Money Account": "moneytracker.money_tracker.permissions.tracker_scoped_query_conditions",
	"Category": "moneytracker.money_tracker.permissions.tracker_scoped_query_conditions",
	"Money Goal": "moneytracker.money_tracker.permissions.tracker_scoped_query_conditions",
	"Money Budget": "moneytracker.money_tracker.permissions.tracker_scoped_query_conditions",
}

has_permission = {
	"Tracker": "moneytracker.money_tracker.permissions.tracker_has_permission",
	"Transaction": "moneytracker.money_tracker.permissions.tracker_scoped_has_permission",
	"Money Account": "moneytracker.money_tracker.permissions.tracker_scoped_has_permission",
	"Category": "moneytracker.money_tracker.permissions.tracker_scoped_has_permission",
	"Money Goal": "moneytracker.money_tracker.permissions.tracker_scoped_has_permission",
	"Money Budget": "moneytracker.money_tracker.permissions.tracker_scoped_has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# Once a day is the right cadence for a budget alert: an envelope is measured against a
# period, and nobody needs to hear about the same month twice before lunch. The job is
# idempotent anyway — it stamps each budget with the period and outcome it last announced,
# so a second run on the same figures sends nothing.
scheduler_events = {
	"daily": [
		"moneytracker.money_tracker.services.budgets.send_budget_alerts",
	],
}

# Testing
# -------

before_tests = "moneytracker.money_tracker.setup.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "moneytracker.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "moneytracker.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["moneytracker.utils.before_request"]
# after_request = ["moneytracker.utils.after_request"]

# Job Events
# ----------
# before_job = ["moneytracker.utils.before_job"]
# after_job = ["moneytracker.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"moneytracker.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

