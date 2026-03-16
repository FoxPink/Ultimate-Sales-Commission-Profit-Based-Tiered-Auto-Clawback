# Ultimate Sales Commission: Profit-Based, Tiered & Auto-Clawback (Odoo 18)

An Odoo 18 module to automate sales commission calculations with:

- Tiered commission plans (Flat or Marginal)
- Commission base on Net Sales or Gross Profit (using product cost)
- Automatic clawback on refunds (credit notes)
- Settlement periods with lock flow
- Sales portal page to view accrued/payable totals

## Installation

1. Copy this folder (`advanced_sales_commission`) into your Odoo `addons_path`.
2. Update Apps list.
3. Install **Ultimate Sales Commission**.

## Usage (high level)

1. Configure a commission plan:
   - Sales Commission → Configuration → Commission Plans
2. Post a customer invoice with a salesperson.
3. Register payment: ledger transitions to payable based on invoice payment status.
4. Review ledgers and settlement periods.

## Compatibility

- Odoo 18.0 Community & Enterprise

