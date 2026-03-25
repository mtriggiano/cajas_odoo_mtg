from odoo import api, fields, models


class TreasuryCashDenomination(models.Model):
    _name = 'treasury.cash.denomination'
    _description = 'Línea de Arqueo'
    _order = 'currency_id, denomination desc'

    COUNT_TYPE = [
        ('opening', 'Apertura'),
        ('closing', 'Cierre'),
    ]

    session_id = fields.Many2one(
        comodel_name='treasury.cash.session',
        string='Sesión',
        ondelete='cascade',
    )
    cashbox_id = fields.Many2one(
        comodel_name='treasury.cash.session.cashbox',
        string='Caja por Divisa',
        ondelete='cascade',
    )
    count_type = fields.Selection(
        selection=COUNT_TYPE,
        string='Tipo de Conteo',
        required=True,
        default='closing',
    )
    bill_id = fields.Many2one(
        comodel_name='treasury.cash.bill',
        string='Billete/Moneda',
        ondelete='set null',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    denomination = fields.Float(
        string='Denominación',
        required=True,
        help='Valor nominal del billete o moneda.',
    )
    quantity = fields.Integer(
        string='Cantidad',
        default=0,
    )
    subtotal = fields.Monetary(
        string='Subtotal',
        currency_field='currency_id',
        compute='_compute_subtotal',
        store=True,
    )

    @api.depends('denomination', 'quantity')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.denomination * line.quantity
