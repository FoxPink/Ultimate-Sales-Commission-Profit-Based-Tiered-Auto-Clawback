# Part of YourBrand. See LICENSE file for full copyright and licensing details.
import base64
import csv
from io import StringIO

from odoo import api, fields, models
from odoo.exceptions import UserError


class CommissionSettlementPeriod(models.Model):
    _name = "commission.settlement.period"
    _description = "Commission Settlement Period"
    _order = "date_start desc, id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("open", "Open"), ("locked", "Locked")],
        default="draft",
        required=True,
        index=True,
    )
    ledger_ids = fields.One2many("commission.ledger", "period_id", string="Ledgers")
    ledger_count = fields.Integer(compute="_compute_ledger_count")
    amount_accrued = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=False)
    amount_payable = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=False)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)

    def _compute_ledger_count(self):
        for rec in self:
            rec.ledger_count = len(rec.ledger_ids)

    def _compute_amounts(self):
        for rec in self:
            rec.amount_accrued = sum(rec.ledger_ids.filtered(lambda l: l.state == "accrued").mapped("commission_amount"))
            rec.amount_payable = sum(rec.ledger_ids.filtered(lambda l: l.state in ("payable", "locked", "paid")).mapped("commission_amount"))

    def action_open(self):
        self.write({"state": "open"})

    def action_lock(self):
        for rec in self:
            if rec.state != "open":
                raise UserError("Only open periods can be locked.")
            rec.ledger_ids.filtered(lambda l: l.state in ("accrued", "payable")).action_lock()
        self.write({"state": "locked"})

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    def action_export_payout(self):
        self.ensure_one()
        payout_ledgers = self.ledger_ids.filtered(lambda l: l.state in ("payable", "locked", "paid"))
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Salesperson", "Period", "Total Commission"])
        totals = {}
        for ledger in payout_ledgers:
            key = ledger.salesperson_id.id
            if key not in totals:
                totals[key] = {"name": ledger.salesperson_id.name, "amount": 0.0}
            totals[key]["amount"] += ledger.commission_amount
        for values in totals.values():
            writer.writerow([values["name"], self.name, values["amount"]])
        csv_content = buffer.getvalue().encode("utf-8")
        attachment = self.env["ir.attachment"].create(
            {
                "name": "commission_payout_{}.csv".format(self.name),
                "type": "binary",
                "datas": base64.b64encode(csv_content),
                "mimetype": "text/csv",
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/{}?download=true".format(attachment.id),
            "target": "self",
        }

    @classmethod
    def _month_name(cls, date_value):
        return "{}-{:02d}".format(date_value.year, date_value.month)

    @api.model
    def get_or_create_open_period(self, date_value, company):
        date_start = date_value.replace(day=1)
        date_end = fields.Date.end_of(date_start, "month")
        period = self.search(
            [
                ("company_id", "=", company.id),
                ("date_start", "=", date_start),
                ("date_end", "=", date_end),
            ],
            limit=1,
        )
        if period:
            if period.state == "draft":
                period.action_open()
            return period
        return self.create(
            {
                "name": self._month_name(date_start),
                "company_id": company.id,
                "date_start": date_start,
                "date_end": date_end,
                "state": "open",
            }
        )
