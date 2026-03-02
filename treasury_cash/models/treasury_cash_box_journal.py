from odoo import fields, models


class TreasuryCashBoxJournal(models.Model):
    _name = 'treasury.cash.box.journal'
    _description = 'Diario de Caja (por Divisa)'
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    box_id = fields.Many2one(
        comodel_name='treasury.cash.box',
        string='Caja',
        required=True,
        ondelete='cascade',
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario',
        required=True,
        domain="[('type', '=', 'cash')]",
        check_company=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa',
        required=True,
    )
    company_id = fields.Many2one(
        related='box_id.company_id',
        store=True,
    )

    _uniq_box_currency = models.Constraint(
        'unique(box_id, currency_id)',
        'Solo se permite un diario por divisa por caja.',
    )
