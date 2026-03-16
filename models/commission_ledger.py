# Part of YourBrand. See LICENSE file for full copyright and licensing details.
import hashlib

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CommissionLedger(models.Model):
    _name = "commission.ledger"
    _description = "Commission Ledger"
    _order = "create_date desc, id desc"
    _sql_constraints = [
        ("calculation_key_uniq", "unique(calculation_key)", "Calculation key must be unique."),
    ]

    name = fields.Char(required=True, copy=False, default="New")
    calculation_key = fields.Char(required=True, copy=False, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    plan_id = fields.Many2one("commission.plan", required=True, index=True)
    period_id = fields.Many2one("commission.settlement.period", required=True, index=True)
    salesperson_id = fields.Many2one("res.users", required=True, index=True)
    source_move_id = fields.Many2one("account.move", index=True)
    source_model = fields.Char(required=True, index=True)
    source_id = fields.Integer(required=True, index=True)
    source_line_id = fields.Integer(index=True)
    invoice_date = fields.Date(index=True)
    product_categ_id = fields.Many2one("product.category", index=True)
    source_ref = fields.Reference(
        selection=[("sale.order", "Sales Order"), ("account.move", "Invoice")],
        compute="_compute_source_ref",
        store=False,
    )
    net_sales = fields.Monetary(required=True, default=0.0)
    cogs = fields.Monetary(required=True, default=0.0)
    gross_profit = fields.Monetary(required=True, default=0.0)
    adjustment_amount = fields.Monetary(required=True, default=0.0)
    commissionable_profit = fields.Monetary(compute="_compute_commissionable_profit", store=True)
    commission_amount = fields.Monetary(required=True, default=0.0)
    state = fields.Selection(
        [("accrued", "Accrued"), ("payable", "Payable"), ("paid", "Paid"), ("locked", "Locked"), ("cancel", "Cancelled")],
        default="accrued",
        required=True,
        index=True,
    )
    is_clawback = fields.Boolean(default=False, index=True)
    origin_ledger_id = fields.Many2one("commission.ledger", index=True)

    @api.depends("source_model", "source_id")
    def _compute_source_ref(self):
        for rec in self:
            rec.source_ref = False
            if rec.source_model and rec.source_id:
                rec.source_ref = "{},{}".format(rec.source_model, rec.source_id)

    @api.depends("gross_profit", "adjustment_amount")
    def _compute_commissionable_profit(self):
        for rec in self:
            rec.commissionable_profit = rec.gross_profit - rec.adjustment_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("commission.ledger") or "New"
            vals.setdefault("calculation_key", self._build_calculation_key(vals))
        return super().create(vals_list)

    def write(self, vals):
        if self.filtered(lambda r: r.state == "locked"):
            raise UserError("Locked ledger cannot be modified.")
        if any(k in vals for k in ("company_id", "salesperson_id", "source_model", "source_id", "source_line_id", "plan_id", "period_id")):
            for rec in self:
                merged = {
                    "company_id": vals.get("company_id", rec.company_id.id),
                    "salesperson_id": vals.get("salesperson_id", rec.salesperson_id.id),
                    "source_model": vals.get("source_model", rec.source_model),
                    "source_id": vals.get("source_id", rec.source_id),
                    "source_line_id": vals.get("source_line_id", rec.source_line_id or 0),
                    "plan_id": vals.get("plan_id", rec.plan_id.id),
                    "period_id": vals.get("period_id", rec.period_id.id),
                    "currency_id": rec.currency_id.id,
                }
                rec.calculation_key = self._build_calculation_key(merged)
        return super().write(vals)

    @api.model
    def _build_calculation_key(self, values):
        raw = "|".join(
            [
                str(values.get("company_id") or ""),
                str(values.get("salesperson_id") or ""),
                str(values.get("source_model") or ""),
                str(values.get("source_id") or ""),
                str(values.get("source_line_id") or 0),
                str(values.get("plan_id") or ""),
                str(values.get("period_id") or ""),
                str(values.get("currency_id") or ""),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @api.constrains("source_model", "source_id")
    def _check_source(self):
        for rec in self:
            if not rec.source_model or not rec.source_id:
                raise ValidationError("Source model and source id are required.")

    def action_set_payable(self):
        self.write({"state": "payable"})

    def action_set_paid(self):
        self.write({"state": "paid"})

    def action_lock(self):
        self.write({"state": "locked"})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_to_accrued(self):
        self.write({"state": "accrued"})

    @api.model
    def cancel_accrued_for_source(self, source_model, source_ids):
        if not source_ids:
            return self.browse()
        ledgers = self.search(
            [
                ("source_model", "=", source_model),
                ("source_id", "in", source_ids),
                ("state", "=", "accrued"),
            ]
        )
        if ledgers:
            ledgers.write({"state": "cancel"})
        return ledgers

    @api.model
    def update_state_for_source(self, source_model, source_id, state):
        ledgers = self.search(
            [
                ("source_model", "=", source_model),
                ("source_id", "=", source_id),
                ("state", "!=", "cancel"),
            ]
        )
        if ledgers:
            ledgers.write({"state": state})
        return ledgers

    @api.model
    def create_or_update_idempotent(self, vals):
        calculation_key = vals.get("calculation_key") or self._build_calculation_key(vals)
        ledger = self.search([("calculation_key", "=", calculation_key)], limit=1)
        if ledger:
            if ledger.state == "locked":
                next_period = self.env["commission.settlement.period"].search(
                    [
                        ("state", "=", "open"),
                        ("company_id", "=", ledger.company_id.id),
                        ("date_start", ">", ledger.period_id.date_end),
                    ],
                    limit=1,
                    order="date_start asc",
                )
                if not next_period:
                    raise UserError("No open period is available for adjustment after locked period.")
                adjustment_vals = dict(vals)
                adjustment_vals["period_id"] = next_period.id
                adjustment_vals["origin_ledger_id"] = ledger.id
                adjustment_vals["state"] = "accrued"
                adjustment_key = self._build_calculation_key(adjustment_vals)
                existing_adjustment = self.search([("calculation_key", "=", adjustment_key)], limit=1)
                if existing_adjustment:
                    existing_adjustment.write(adjustment_vals)
                    return existing_adjustment
                adjustment_vals["calculation_key"] = adjustment_key
                return self.create(adjustment_vals)
            ledger.write(vals)
            return ledger
        vals["calculation_key"] = calculation_key
        return self.create(vals)

    @api.model
    def _cron_recompute_accrued_ledgers(self):
        draft_period = self.env["commission.settlement.period"].search(
            [("state", "=", "open"), ("company_id", "=", self.env.company.id)],
            limit=1,
            order="date_start asc",
        )
        if not draft_period:
            return
        ledgers = self.search([("period_id", "=", draft_period.id), ("state", "=", "accrued")], limit=1000)
        for ledger in ledgers:
            if ledger.source_model == "account.move" and ledger.source_id:
                move = self.env["account.move"].browse(ledger.source_id)
                if move.exists():
                    computed = move._compute_commission_values(ledger.plan_id)
                    ledger.net_sales = computed["net_sales"]
                    ledger.cogs = computed["cogs"]
                    ledger.gross_profit = computed["gross_profit"]
                    ledger.invoice_date = computed["invoice_date"]
                    ledger.product_categ_id = computed["product_categ_id"]
                    ledger.is_clawback = computed["is_clawback"]
                    ledger.state = "payable" if move.payment_state in ("paid", "in_payment") else "accrued"
            if ledger.plan_id.commission_on == "net_sales":
                base_amount = ledger.net_sales
            else:
                base_amount = ledger.gross_profit - ledger.adjustment_amount
            ledger.commission_amount = ledger.plan_id._calculate_tiered_amount(base_amount)

    def action_create_clawback(self, clawback_ratio):
        self.ensure_one()
        if not 0 < clawback_ratio <= 1:
            raise UserError("Clawback ratio must be between 0 and 1.")
        next_period = self.env["commission.settlement.period"].search(
            [
                ("state", "=", "open"),
                ("company_id", "=", self.company_id.id),
                ("date_start", ">", self.period_id.date_end),
            ],
            limit=1,
            order="date_start asc",
        )
        if not next_period:
            raise UserError("No open next settlement period found for clawback.")
        clawback_amount = abs(self.commission_amount) * clawback_ratio * -1
        values = {
            "company_id": self.company_id.id,
            "plan_id": self.plan_id.id,
            "period_id": next_period.id,
            "salesperson_id": self.salesperson_id.id,
            "source_model": self.source_model,
            "source_id": self.source_id,
            "source_line_id": self.source_line_id,
            "net_sales": self.net_sales * clawback_ratio * -1,
            "cogs": self.cogs * clawback_ratio * -1,
            "gross_profit": self.gross_profit * clawback_ratio * -1,
            "adjustment_amount": self.adjustment_amount * clawback_ratio * -1,
            "commission_amount": clawback_amount,
            "is_clawback": True,
            "origin_ledger_id": self.id,
            "state": "accrued",
            "currency_id": self.currency_id.id,
        }
        return self.create_or_update_idempotent(values)
