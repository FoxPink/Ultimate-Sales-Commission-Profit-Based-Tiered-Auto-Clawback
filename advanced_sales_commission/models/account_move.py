# Part of YourBrand. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    commission_ledger_count = fields.Integer(compute="_compute_commission_ledger_count")

    def _compute_commission_ledger_count(self):
        ledger_obj = self.env["commission.ledger"]
        for move in self:
            move.commission_ledger_count = ledger_obj.search_count(
                [("source_model", "=", "account.move"), ("source_id", "=", move.id)]
            )

    def action_view_commission_ledgers(self):
        self.ensure_one()
        action = self.env.ref("advanced_sales_commission.action_commission_ledger").read()[0]
        action["domain"] = [("source_model", "=", "account.move"), ("source_id", "=", self.id)]
        action["context"] = {"default_source_model": "account.move", "default_source_id": self.id}
        return action

    def action_post(self):
        result = super().action_post()
        for move in self:
            if move.move_type in ("out_invoice", "out_refund"):
                move._generate_commission_ledger()
        return result

    def button_draft(self):
        result = super().button_draft()
        moves = self.filtered(lambda m: m.move_type in ("out_invoice", "out_refund"))
        if moves:
            self.env["commission.ledger"].cancel_accrued_for_source("account.move", moves.ids)
        return result

    def _compute_payment_state(self):
        super()._compute_payment_state()
        ledger_obj = self.env["commission.ledger"]
        for move in self.filtered(lambda m: m.move_type in ("out_invoice", "out_refund") and m.state == "posted"):
            target_state = "payable" if move.payment_state in ("paid", "in_payment") else "accrued"
            ledger_obj.update_state_for_source("account.move", move.id, target_state)

    def _get_commission_plan(self):
        self.ensure_one()
        return self.env["commission.plan"].search(
            [("active", "=", True), ("company_id", "=", self.company_id.id)],
            limit=1,
        )

    def _compute_commission_values(self, plan):
        self.ensure_one()
        sign = -1 if self.move_type == "out_refund" else 1
        total_net_sales = 0.0
        total_cogs = 0.0
        product_totals = {}
        currency = self.currency_id or self.company_currency_id
        conversion_date = self.invoice_date or fields.Date.context_today(self)

        amount_untaxed = abs(getattr(self, "amount_untaxed", 0.0) or 0.0)
        if amount_untaxed:
            total_net_sales = currency._convert(amount_untaxed, self.company_currency_id, self.company_id, conversion_date)
        else:
            for line in self.invoice_line_ids.filtered(lambda l: not l.display_type):
                qty = abs(line.quantity or 0.0)
                subtotal = abs(line.price_subtotal or 0.0)
                subtotal_company = currency._convert(subtotal, self.company_currency_id, self.company_id, conversion_date)
                total_net_sales += subtotal_company
                total_cogs += abs((line.product_id.standard_price or 0.0) * qty)
                category = line.product_id.categ_id
                if category:
                    product_totals[category.id] = product_totals.get(category.id, 0.0) + subtotal_company

        if not total_cogs:
            for line in self.invoice_line_ids.filtered(lambda l: not l.display_type):
                qty = abs(line.quantity or 0.0)
                total_cogs += abs((line.product_id.standard_price or 0.0) * qty)
                if not product_totals:
                    category = line.product_id.categ_id
                    if category:
                        product_totals[category.id] = product_totals.get(category.id, 0.0) + abs(line.price_subtotal or 0.0)
        gross_profit = total_net_sales - total_cogs
        base_amount = total_net_sales if plan.commission_on == "net_sales" else gross_profit
        commission_amount = plan._calculate_tiered_amount(base_amount)
        product_categ_id = False
        if product_totals:
            product_categ_id = max(product_totals.items(), key=lambda item: item[1])[0]
        return {
            "net_sales": total_net_sales * sign,
            "cogs": total_cogs * sign,
            "gross_profit": gross_profit * sign,
            "commission_amount": commission_amount * sign,
            "is_clawback": sign < 0,
            "invoice_date": conversion_date,
            "product_categ_id": product_categ_id,
        }

    def _generate_commission_ledger(self):
        self.ensure_one()
        if not self.invoice_user_id:
            return
        plan = self._get_commission_plan()
        if not plan:
            return
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        period = self.env["commission.settlement.period"].get_or_create_open_period(invoice_date, self.company_id)
        computed_values = self._compute_commission_values(plan)
        origin_ledger_id = False
        if self.move_type == "out_refund" and self.reversed_entry_id:
            origin_ledger = self.env["commission.ledger"].search(
                [
                    ("source_model", "=", "account.move"),
                    ("source_id", "=", self.reversed_entry_id.id),
                    ("salesperson_id", "=", self.invoice_user_id.id),
                ],
                limit=1,
                order="id desc",
            )
            origin_ledger_id = origin_ledger.id
        ledger_values = {
            "company_id": self.company_id.id,
            "plan_id": plan.id,
            "period_id": period.id,
            "salesperson_id": self.invoice_user_id.id,
            "source_model": "account.move",
            "source_id": self.id,
            "source_line_id": 0,
            "source_move_id": self.id,
            "net_sales": computed_values["net_sales"],
            "cogs": computed_values["cogs"],
            "gross_profit": computed_values["gross_profit"],
            "adjustment_amount": 0.0,
            "commission_amount": computed_values["commission_amount"],
            "invoice_date": computed_values["invoice_date"],
            "product_categ_id": computed_values["product_categ_id"],
            "is_clawback": computed_values["is_clawback"],
            "origin_ledger_id": origin_ledger_id,
            "state": "payable" if self.payment_state in ("paid", "in_payment") else "accrued",
            "currency_id": self.company_currency_id.id,
        }
        self.env["commission.ledger"].with_context(tracking_disable=True).create_or_update_idempotent(ledger_values)
