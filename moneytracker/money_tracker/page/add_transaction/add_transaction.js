frappe.pages['add-transaction'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Add Transaction',
		single_column: true,
	});

	new AddTransaction(page);
};

class AddTransaction {
	constructor(page) {
		this.page = page;
		this.make();
	}

	make() {
		this.wrapper = $('<div style="max-width: 500px; margin-top: 20px;"></div>').appendTo(this.page.body);
		this.controls = {};

		const fields = [
			{
				fieldname: 'transaction_type',
				label: 'Type',
				fieldtype: 'Select',
				options: 'Expense\nIncome\nTransfer',
				reqd: 1,
				default: 'Expense',
			},
			{ fieldname: 'date', label: 'Date', fieldtype: 'Date', reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: 'amount', label: 'Amount', fieldtype: 'Currency', reqd: 1 },
			{ fieldname: 'account', label: 'Account', fieldtype: 'Link', options: 'Money Account', reqd: 1 },
			{
				fieldname: 'destination_account',
				label: 'Destination Account',
				fieldtype: 'Link',
				options: 'Money Account',
			},
			{ fieldname: 'category', label: 'Category', fieldtype: 'Link', options: 'Category' },
			{ fieldname: 'notes', label: 'Notes', fieldtype: 'Small Text' },
		];

		fields.forEach((df) => {
			const $field = $('<div class="frappe-control" style="margin-bottom: 12px;"></div>').appendTo(this.wrapper);
			const control = frappe.ui.form.make_control({
				parent: $field,
				df: {
					...df,
					onchange: () => this.refresh_dependencies(),
				},
				render_input: true,
			});
			control.refresh();
			if (df.default) control.set_value(df.default);
			this.controls[df.fieldname] = control;
		});

		this.refresh_dependencies();

		this.page.set_primary_action('Save Transaction', () => this.submit());
	}

	refresh_dependencies() {
		const type = this.controls.transaction_type.get_value();
		this.controls.destination_account.$wrapper.toggle(type === 'Transfer');
		this.controls.category.$wrapper.toggle(type !== 'Transfer');
	}

	submit() {
		const values = {};
		Object.keys(this.controls).forEach((fieldname) => {
			values[fieldname] = this.controls[fieldname].get_value();
		});

		if (!values.transaction_type || !values.date || !values.amount || !values.account) {
			frappe.msgprint('Please fill all required fields.');
			return;
		}
		if (values.transaction_type === 'Transfer' && !values.destination_account) {
			frappe.msgprint('Destination Account is required for a Transfer.');
			return;
		}
		if (values.transaction_type !== 'Transfer' && !values.category) {
			frappe.msgprint('Category is required.');
			return;
		}

		frappe.call({
			method: 'moneytracker.money_tracker.transaction_service.create_transaction',
			args: values,
			freeze: true,
			freeze_message: 'Posting transaction...',
			callback: (r) => {
				if (r.message) {
					frappe.show_alert({ message: `Transaction ${r.message.name} posted`, indicator: 'green' });
					this.reset();
				}
			},
		});
	}

	reset() {
		Object.keys(this.controls).forEach((fieldname) => this.controls[fieldname].set_value(''));
		this.controls.transaction_type.set_value('Expense');
		this.controls.date.set_value(frappe.datetime.get_today());
		this.refresh_dependencies();
	}
}
