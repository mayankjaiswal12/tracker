// Copyright (c) 2026, Mayank Jaiswal and contributors
// For license information, please see license.txt

// Everything the Desk loads on every page for this app. One entry only so far: the Number Cards
// on the Money Tracker workspace are all `type: "Custom"` and return a formatted string, which
// leaves Frappe with nothing to route on when one is clicked. See card_routes.js.
import "./card_routes.js";
