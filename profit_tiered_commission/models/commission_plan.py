# Part of YourBrand. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionPlan(models.Model):
    _name = "commission.plan"
    _description = "Commission Plan"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    tier_method = fields.Selection(
        [("marginal", "Marginal"), ("flat", "Flat")],
        required=True,
        default="marginal",
    )
    commission_on = fields.Selection(
        [("gross_profit", "Gross Profit"), ("net_sales", "Net Sales")],
        required=True,
        default="gross_profit",
    )
    tier_line_ids = fields.One2many("commission.plan.tier", "plan_id", string="Tiers")

    def _calculate_tiered_amount(self, total_profit):
        self.ensure_one()
        if total_profit <= 0:
            return 0.0
        tiers = self.tier_line_ids.sorted("from_amount")
        if not tiers:
            return 0.0
        if self.tier_method == "flat":
            applicable = tiers.filtered(lambda t: total_profit >= t.from_amount).sorted("from_amount", reverse=True)[:1]
            return total_profit * (applicable.rate / 100.0) if applicable else 0.0
        total_calculated = 0.0
        for tier in tiers:
            range_start = tier.from_amount
            range_end = tier.to_amount or float("inf")
            amount_in_tier = max(0.0, min(total_profit, range_end) - range_start)
            if amount_in_tier > 0:
                total_calculated += amount_in_tier * (tier.rate / 100.0)
        return total_calculated


class CommissionPlanTier(models.Model):
    _name = "commission.plan.tier"
    _description = "Commission Plan Tier"
    _order = "from_amount asc, id asc"

    plan_id = fields.Many2one("commission.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="plan_id.currency_id", store=True)
    sequence = fields.Integer(default=10)
    from_amount = fields.Monetary(required=True)
    to_amount = fields.Monetary()
    rate = fields.Float(required=True, digits=(16, 4))

    @api.constrains("from_amount", "to_amount", "rate")
    def _check_tier_values(self):
        for rec in self:
            if rec.from_amount < 0:
                raise ValidationError("From amount must be greater than or equal to zero.")
            if rec.to_amount and rec.to_amount <= rec.from_amount:
                raise ValidationError("To amount must be greater than from amount.")
            if rec.rate < 0:
                raise ValidationError("Rate must be greater than or equal to zero.")

    @api.constrains("plan_id", "from_amount", "to_amount")
    def _check_no_overlap(self):
        for rec in self:
            tiers = rec.plan_id.tier_line_ids.sorted("from_amount")
            for idx, tier in enumerate(tiers):
                if idx == len(tiers) - 1:
                    continue
                next_tier = tiers[idx + 1]
                if tier.to_amount and tier.to_amount > next_tier.from_amount:
                    raise ValidationError("Tier ranges cannot overlap.")
