from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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

    @api.onchange('currency_id', 'company_id')
    def _onchange_currency_id(self):
        domain = [('type', '=', 'cash')]
        for line in self:
            if not line.currency_id or not line.company_id:
                continue
            domain = [('type', '=', 'cash'), ('company_id', '=', line.company_id.id)]
            if line.currency_id == line.company_id.currency_id:
                domain = domain + ['|', ('currency_id', '=', False), ('currency_id', '=', line.currency_id.id)]
            else:
                domain = domain + [('currency_id', '=', line.currency_id.id)]

            if not line.journal_id or line.journal_id.type != 'cash' or line.journal_id not in self.env['account.journal'].search(domain):
                line.journal_id = self.env['account.journal'].search(domain, limit=1)
        return {'domain': {'journal_id': domain}}

    @api.constrains('journal_id', 'currency_id', 'company_id')
    def _check_journal_currency_consistency(self):
        for line in self:
            if not line.journal_id or not line.currency_id:
                continue
            if line.journal_id.company_id != line.company_id:
                raise ValidationError(_('El diario debe pertenecer a la misma empresa de la caja.'))

            if line.currency_id == line.company_id.currency_id:
                valid = not line.journal_id.currency_id or line.journal_id.currency_id == line.currency_id
            else:
                valid = line.journal_id.currency_id == line.currency_id

            if not valid:
                raise ValidationError(
                    _('El diario "%s" no es compatible con la divisa %s.\n'
                      'Use un diario de caja en esa divisa (o sin divisa para la moneda de la empresa).',
                      line.journal_id.display_name, line.currency_id.name)
                )
