from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TreasuryCashTransfer(models.Model):
    _name = 'treasury.cash.transfer'
    _description = 'Transferencia entre Cajas'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    name = fields.Char(
        string='Número',
        readonly=True,
        default='/',
        copy=False,
    )
    source_box_id = fields.Many2one(
        comodel_name='treasury.cash.box',
        string='Caja Origen',
        required=True,
        tracking=True,
    )
    dest_box_id = fields.Many2one(
        comodel_name='treasury.cash.box',
        string='Caja Destino',
        required=True,
        tracking=True,
    )
    amount = fields.Monetary(
        string='Monto',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
    )
    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    description = fields.Char(
        string='Descripción',
        required=True,
    )
    bridge_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta Puente',
        check_company=True,
        domain="[('account_type', '=', 'asset_current')]",
        help='Cuenta de transferencia interna usada como puente entre las dos cajas.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('confirmed', 'Confirmada'),
            ('cancelled', 'Cancelada'),
        ],
        string='Estado',
        default='draft',
        required=True,
        readonly=True,
        tracking=True,
    )

    # Linked records
    source_move_id = fields.Many2one(
        comodel_name='treasury.cash.move',
        string='Movimiento Origen',
        readonly=True,
        copy=False,
    )
    dest_move_id = fields.Many2one(
        comodel_name='treasury.cash.move',
        string='Movimiento Destino',
        readonly=True,
        copy=False,
    )
    account_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento Contable',
        readonly=True,
        copy=False,
    )

    _check_amount_positive = models.Constraint(
        'CHECK(amount > 0)',
        'El monto de la transferencia debe ser positivo.',
    )

    @api.constrains('source_box_id', 'dest_box_id')
    def _check_different_boxes(self):
        for transfer in self:
            if transfer.source_box_id == transfer.dest_box_id:
                raise ValidationError(_('Las cajas de origen y destino deben ser diferentes.'))

    def action_confirm(self):
        for transfer in self:
            if transfer.state != 'draft':
                raise UserError(_('Solo las transferencias en borrador pueden confirmarse.'))

            # Validate both boxes have open sessions
            source_session = transfer.source_box_id.current_session_id
            dest_session = transfer.dest_box_id.current_session_id
            if not source_session or source_session.state != 'opened':
                raise UserError(
                    _('La caja "%s" debe tener una sesión abierta.', transfer.source_box_id.name)
                )
            if not dest_session or dest_session.state != 'opened':
                raise UserError(
                    _('La caja "%s" debe tener una sesión abierta.', transfer.dest_box_id.name)
                )

            # Get bridge account
            bridge_account = transfer.bridge_account_id
            if not bridge_account:
                bridge_account = transfer.company_id.transfer_account_id
            if not bridge_account:
                raise UserError(
                    _('No hay cuenta puente configurada. Configure una en la transferencia o '
                      'configure la cuenta de transferencia interna en Ajustes de Contabilidad.')
                )

            # Assign sequence
            if transfer.name == '/':
                transfer.name = self.env['ir.sequence'].next_by_code('treasury.cash.transfer') or '/'

            # Create atomic journal entry
            source_journal = transfer.source_box_id.get_journal_for_currency(transfer.currency_id)
            source_cash_account = source_journal.default_account_id
            dest_journal = transfer.dest_box_id.get_journal_for_currency(transfer.currency_id)
            dest_cash_account = dest_journal.default_account_id

            account_move = self.env['account.move'].create({
                'journal_id': source_journal.id,
                'date': transfer.date,
                'ref': _('Transferencia %s: %s → %s',
                         transfer.name, transfer.source_box_id.name, transfer.dest_box_id.name),
                'line_ids': [
                    # Credit source cash
                    fields.Command.create({
                        'name': _('Salida transferencia — %s', transfer.description),
                        'account_id': source_cash_account.id,
                        'debit': 0.0,
                        'credit': transfer.amount,
                    }),
                    # Debit bridge
                    fields.Command.create({
                        'name': _('Puente transferencia — %s', transfer.description),
                        'account_id': bridge_account.id,
                        'debit': transfer.amount,
                        'credit': 0.0,
                    }),
                    # Credit bridge
                    fields.Command.create({
                        'name': _('Puente transferencia — %s', transfer.description),
                        'account_id': bridge_account.id,
                        'debit': 0.0,
                        'credit': transfer.amount,
                    }),
                    # Debit dest cash
                    fields.Command.create({
                        'name': _('Entrada transferencia — %s', transfer.description),
                        'account_id': dest_cash_account.id,
                        'debit': transfer.amount,
                        'credit': 0.0,
                    }),
                ],
            })
            account_move._post()
            transfer.account_move_id = account_move

            # Create source treasury move (transfer_out)
            source_move = self.env['treasury.cash.move'].with_context(
                skip_session_check=True,
            ).create({
                'session_id': source_session.id,
                'move_type': 'transfer_out',
                'amount': transfer.amount,
                'currency_id': transfer.currency_id.id,
                'account_id': bridge_account.id,
                'description': _('Transferencia a %s — %s', transfer.dest_box_id.name, transfer.description),
                'date': transfer.date,
                'transfer_id': transfer.id,
                'account_move_id': account_move.id,
            })
            source_move.write({'state': 'posted'})

            # Create dest treasury move (transfer_in)
            dest_move = self.env['treasury.cash.move'].with_context(
                skip_session_check=True,
            ).create({
                'session_id': dest_session.id,
                'move_type': 'transfer_in',
                'amount': transfer.amount,
                'currency_id': transfer.currency_id.id,
                'account_id': bridge_account.id,
                'description': _('Transferencia desde %s — %s', transfer.source_box_id.name, transfer.description),
                'date': transfer.date,
                'transfer_id': transfer.id,
                'account_move_id': account_move.id,
            })
            dest_move.write({'state': 'posted'})

            transfer.write({
                'source_move_id': source_move.id,
                'dest_move_id': dest_move.id,
                'state': 'confirmed',
            })

    def action_cancel(self):
        for transfer in self:
            if transfer.state != 'confirmed':
                raise UserError(_('Solo las transferencias confirmadas pueden cancelarse.'))
            # Reverse the journal entry
            if transfer.account_move_id and transfer.account_move_id.state == 'posted':
                transfer.account_move_id._reverse_moves(
                    default_values_list=[{
                        'ref': _('Reversión de transferencia: %s', transfer.name),
                        'date': fields.Date.context_today(self),
                    }],
                    cancel=True,
                )
            # Cancel linked treasury moves
            if transfer.source_move_id:
                transfer.source_move_id.write({'state': 'cancelled'})
            if transfer.dest_move_id:
                transfer.dest_move_id.write({'state': 'cancelled'})
            transfer.state = 'cancelled'
