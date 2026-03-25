from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TreasuryCashBill(models.Model):
    _name = 'treasury.cash.bill'
    _description = 'Billete/Moneda'
    _order = 'currency_id, value'

    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True,
    )
    value = fields.Float(
        string='Valor',
        required=True,
        digits=(16, 4),
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    box_ids = fields.Many2many(
        comodel_name='treasury.cash.box',
        relation='treasury_cash_bill_box_rel',
        column1='bill_id',
        column2='box_id',
        string='Cajas',
        help='Si está vacío, se usa en todas las cajas.',
    )
    active = fields.Boolean(default=True)

    @api.depends('value', 'currency_id')
    def _compute_name(self):
        for bill in self:
            if bill.currency_id and bill.value:
                bill.name = '%s %s' % (bill.currency_id.symbol, bill.value)
            else:
                bill.name = str(bill.value)

    @api.model
    def name_create(self, name):
        try:
            value = float(name)
        except ValueError:
            raise UserError(_('El nombre del billete/moneda debe ser un número.'))
        result = super().create({'name': name, 'value': value})
        return result.id, result.display_name

    def get_bills_for_box(self, box, currency=None):
        """Return bills applicable to a given box and optional currency."""
        domain = [
            '|',
            ('box_ids', '=', False),
            ('box_ids', 'in', box.ids),
        ]
        if currency:
            domain.append(('currency_id', '=', currency.id))
        return self.search(domain, order='currency_id, value desc')
