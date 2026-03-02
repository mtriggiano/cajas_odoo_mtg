from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TreasuryCashMove(models.Model):
    _name = 'treasury.cash.move'
    _description = 'Movimiento de Caja'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    MOVE_TYPES = [
        ('income', 'Ingreso'),
        ('expense', 'Egreso'),
        ('transfer_out', 'Transferencia Salida'),
        ('transfer_in', 'Transferencia Entrada'),
        ('supplier_payment', 'Pago a Proveedor'),
        ('bank_deposit', 'Depósito Bancario'),
        ('bank_withdrawal', 'Retiro Bancario'),
        ('adjustment', 'Ajuste'),
    ]

    name = fields.Char(
        string='Número',
        readonly=True,
        default='/',
        copy=False,
    )
    session_id = fields.Many2one(
        comodel_name='treasury.cash.session',
        string='Sesión',
        required=True,
        index=True,
        ondelete='restrict',
    )
    cashbox_id = fields.Many2one(
        comodel_name='treasury.cash.session.cashbox',
        string='Caja Divisa',
        index=True,
        ondelete='restrict',
    )
    box_id = fields.Many2one(
        related='session_id.box_id',
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='session_id.company_id',
        store=True,
    )
    move_type = fields.Selection(
        selection=MOVE_TYPES,
        string='Tipo',
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
    account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta Contable',
        check_company=True,
        domain="[('account_type', 'in', "
               "('expense', 'expense_direct_cost', 'income', 'income_other', "
               "'asset_current', 'liability_current', 'asset_cash'))]",
        help='Cuenta contrapartida para este movimiento. '
             'La cuenta de caja se determina automáticamente del diario.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contacto',
        tracking=True,
    )
    description = fields.Char(
        string='Descripción',
        required=True,
        tracking=True,
    )
    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('posted', 'Contabilizado'),
            ('cancelled', 'Cancelado'),
        ],
        string='Estado',
        default='draft',
        required=True,
        readonly=True,
        tracking=True,
        copy=False,
    )

    # Accounting link
    account_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento Contable',
        readonly=True,
        copy=False,
        index=True,
    )
    payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Pago',
        readonly=True,
        copy=False,
        help='Registro de pago vinculado al pagar una factura de proveedor.',
    )

    # Transfer link
    transfer_id = fields.Many2one(
        comodel_name='treasury.cash.transfer',
        string='Transferencia',
        readonly=True,
        copy=False,
    )

    # Analytics
    analytic_distribution = fields.Json(
        string='Distribución Analítica',
    )

    # Attachments
    attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        string='Adjuntos',
    )
    attachment_count = fields.Integer(
        string='Cant. Archivos',
        compute='_compute_attachment_count',
    )

    # Approval
    requires_approval = fields.Boolean(
        string='Requiere Aprobación',
        compute='_compute_requires_approval',
        store=True,
    )
    approved_by = fields.Many2one(
        comodel_name='res.users',
        string='Aprobado por',
        readonly=True,
        copy=False,
    )
    approved_date = fields.Datetime(
        string='Fecha de Aprobación',
        readonly=True,
        copy=False,
    )

    # Supplier payment fields
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Factura',
        domain="[('move_type', 'in', ('in_invoice', 'in_refund')), "
               "('state', '=', 'posted'), "
               "('payment_state', 'in', ('not_paid', 'partial'))]",
        help='Seleccione una factura de proveedor a pagar.',
    )

    _check_amount_positive = models.Constraint(
        'CHECK(amount != 0)',
        'El monto del movimiento no puede ser cero.',
    )

    def _compute_attachment_count(self):
        for move in self:
            move.attachment_count = len(move.attachment_ids)

    @api.depends('amount', 'box_id.require_approval_above', 'box_id.max_movement_amount')
    def _compute_requires_approval(self):
        for move in self:
            threshold = move.box_id.require_approval_above
            if threshold and move.amount > threshold:
                move.requires_approval = True
            else:
                move.requires_approval = False

    @api.constrains('amount', 'box_id')
    def _check_max_amount(self):
        for move in self:
            max_amount = move.box_id.max_movement_amount
            if max_amount and move.amount > max_amount:
                raise ValidationError(
                    _('El monto %s excede el máximo permitido %s para la caja "%s".',
                      move.amount, max_amount, move.box_id.name)
                )

    @api.constrains('session_id')
    def _check_session_open(self):
        if self.env.context.get('skip_session_check'):
            return
        for move in self:
            if move.session_id.state not in ('opened',):
                raise ValidationError(
                    _('Solo puede agregar movimientos a sesiones que estén en progreso.')
                )

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move in moves:
            if move.name == '/':
                box = move.box_id
                if box.sequence_id:
                    move.name = box.sequence_id.next_by_id()
                else:
                    move.name = self.env['ir.sequence'].next_by_code('treasury.cash.move') or '/'
            # Auto-assign cashbox_id based on currency
            if not move.cashbox_id and move.session_id:
                cashbox = move.session_id.cashbox_ids.filtered(
                    lambda cb: cb.currency_id == move.currency_id
                )
                if cashbox:
                    move.cashbox_id = cashbox[0]
        return moves

    def action_post(self):
        for move in self:
            if move.state != 'draft':
                raise UserError(_('Solo los movimientos en borrador pueden contabilizarse.'))
            if move.session_id.state != 'opened':
                raise UserError(_('La sesión debe estar en progreso para contabilizar movimientos.'))
            if move.requires_approval and not move.approved_by:
                raise UserError(
                    _('Este movimiento requiere aprobación antes de contabilizar (monto: %s).', move.amount)
                )

            # Handle supplier payment with invoice
            if move.move_type == 'supplier_payment' and move.invoice_id:
                move._create_supplier_payment()
            else:
                move._create_account_move()

            move.state = 'posted'

    def action_cancel(self):
        for move in self:
            if move.state != 'posted':
                raise UserError(_('Solo los movimientos contabilizados pueden cancelarse.'))
            if move.session_id.is_locked:
                raise UserError(_('No se pueden cancelar movimientos en una sesión bloqueada.'))
            # Reverse the journal entry
            if move.account_move_id and move.account_move_id.state == 'posted':
                move.account_move_id._reverse_moves(
                    default_values_list=[{
                        'ref': _('Reversión de: %s', move.account_move_id.ref or ''),
                        'date': fields.Date.context_today(self),
                    }],
                    cancel=True,
                )
            if move.payment_id:
                move.payment_id.action_cancel()
            move.state = 'cancelled'

    def action_approve(self):
        for move in self:
            if not move.requires_approval:
                raise UserError(_('Este movimiento no requiere aprobación.'))
            move.write({
                'approved_by': self.env.uid,
                'approved_date': fields.Datetime.now(),
            })

    def _create_account_move(self):
        self.ensure_one()
        journal = self.box_id.get_journal_for_currency(self.currency_id)

        cash_account = journal.default_account_id
        if not cash_account:
            raise UserError(
                _('No hay cuenta predeterminada configurada en el diario "%s".', journal.name)
            )

        # Counterpart: explicit account or journal suspense account (pending reconciliation)
        counterpart_account = self.account_id
        if not counterpart_account:
            counterpart_account = journal.suspense_account_id or self.company_id.account_journal_suspense_account_id
            if not counterpart_account:
                raise UserError(
                    _('No hay cuenta de suspensión configurada en el diario "%s". '
                      'Configure una cuenta contrapartida o una cuenta de suspensión.', journal.name)
                )

        # Determine debit/credit based on move type
        if self.move_type in ('income', 'transfer_in', 'bank_withdrawal'):
            # Cash increases: debit cash, credit counterpart
            line_vals = [
                fields.Command.create({
                    'name': self.description,
                    'account_id': cash_account.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'debit': self.amount,
                    'credit': 0.0,
                    'analytic_distribution': self.analytic_distribution,
                }),
                fields.Command.create({
                    'name': self.description,
                    'account_id': counterpart_account.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ]
        elif self.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit'):
            # Cash decreases: credit cash, debit counterpart
            line_vals = [
                fields.Command.create({
                    'name': self.description,
                    'account_id': cash_account.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
                fields.Command.create({
                    'name': self.description,
                    'account_id': counterpart_account.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'debit': self.amount,
                    'credit': 0.0,
                    'analytic_distribution': self.analytic_distribution,
                }),
            ]
        elif self.move_type == 'adjustment':
            if self.amount > 0:
                line_vals = [
                    fields.Command.create({
                        'name': self.description,
                        'account_id': cash_account.id,
                        'debit': self.amount,
                        'credit': 0.0,
                    }),
                    fields.Command.create({
                        'name': self.description,
                        'account_id': counterpart_account.id,
                        'debit': 0.0,
                        'credit': self.amount,
                    }),
                ]
            else:
                abs_amount = abs(self.amount)
                line_vals = [
                    fields.Command.create({
                        'name': self.description,
                        'account_id': cash_account.id,
                        'debit': 0.0,
                        'credit': abs_amount,
                    }),
                    fields.Command.create({
                        'name': self.description,
                        'account_id': counterpart_account.id,
                        'debit': abs_amount,
                        'credit': 0.0,
                    }),
                ]
        else:
            raise UserError(_('Tipo de movimiento no soportado: %s', self.move_type))

        account_move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': self.date,
            'ref': '%s — %s' % (self.name, self.description),
            'line_ids': line_vals,
        })
        account_move._post()
        self.account_move_id = account_move

    def _create_supplier_payment(self):
        self.ensure_one()
        journal = self.box_id.get_journal_for_currency(self.currency_id)

        payment_vals = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': journal.id,
            'date': self.date,
            'memo': self.description,
            'invoice_ids': [(4, self.invoice_id.id)],
        }
        payment = self.env['account.payment'].create(payment_vals)
        payment.action_post()
        self.payment_id = payment
        self.account_move_id = payment.move_id

    def action_view_journal_entry(self):
        self.ensure_one()
        if self.account_move_id:
            return {
                'name': _('Asiento Contable'),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': self.account_move_id.id,
            }

    def action_print_voucher(self):
        self.ensure_one()
        return self.env.ref('treasury_cash.action_report_move_voucher').report_action(self)
