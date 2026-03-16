# Part of YourBrand. See LICENSE file for full copyright and licensing details.
from odoo import http
from odoo.http import request


class CommissionPortal(http.Controller):
    @http.route("/my/commissions", type="http", auth="user", website=True)
    def portal_my_commissions(self, **kwargs):
        user = request.env.user
        ledger_domain = [
            ("salesperson_id", "=", user.id),
            ("state", "!=", "cancel"),
        ]
        ledgers = request.env["commission.ledger"].sudo().search(ledger_domain, order="invoice_date desc, id desc", limit=200)
        amounts = {
            "accrued": sum(ledgers.filtered(lambda l: l.state == "accrued").mapped("commission_amount")),
            "payable": sum(ledgers.filtered(lambda l: l.state in ("payable", "locked", "paid")).mapped("commission_amount")),
            "clawback": sum(ledgers.filtered(lambda l: l.is_clawback).mapped("commission_amount")),
        }
        return request.render(
            "advanced_sales_commission.portal_my_commissions",
            {
                "ledgers": ledgers,
                "amounts": amounts,
            },
        )
