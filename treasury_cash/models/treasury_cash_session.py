from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TreasuryCashSession(models.Model):
    _name = 'treasury.cash.session'
    _description = 'Sesión de Caja'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    TREASURY_SESSION_STATE = [
        ('opening_control', 'Control de Apertura'),
        ('opened', 'En Progreso'),
        ('closing_control', 'Control de Cierre'),
        ('closed', 'Cerrada y Contabilizada'),
    ]

    name = fields.Char(
        string='ID de Sesión',
        readonly=True,
        default='/',
        copy=False,
    )
    box_id = fields.Many2one(
        comodel_name='treasury.cash.box',
        string='Caja',
        required=True,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Abierta por',
        required=True,
        default=lambda self: self.env.uid,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    closed_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Cerrada por',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='box_id.company_id',
        store=True,
    )
    currency_id = fields.Many2one(
        related='box_id.currency_id',
        store=True,
    )
    state = fields.Selection(
        selection=TREASURY_SESSION_STATE,
        string='Estado',
        required=True,
        readonly=True,
        index=True,
        copy=False,
        default='opening_control',
        tracking=True,
    )
    start_at = fields.Datetime(
        string='Fecha de Apertura',
        readonly=True,
    )
    stop_at = fields.Datetime(
        string='Fecha de Cierre',
        readonly=True,
        copy=False,
    )

    # Balance fields (main currency summary — computed from cashbox lines)
    opening_balance = fields.Monetary(
        string='Saldo Inicial',
        currency_field='currency_id',
        compute='_compute_balance_summary',
        store=True,
    )
    closing_balance_theoretical = fields.Monetary(
        string='Saldo Teórico de Cierre',
        currency_field='currency_id',
        compute='_compute_balance_summary',
        store=True,
        help='Saldo inicial más todos los movimientos contabilizados (divisa principal).',
    )
    closing_balance_real = fields.Monetary(
        string='Saldo Real de Cierre',
        currency_field='currency_id',
        compute='_compute_balance_summary',
        store=True,
    )
    difference = fields.Monetary(
        string='Diferencia',
        currency_field='currency_id',
        compute='_compute_balance_summary',
        store=True,
        help='Diferencia entre el saldo real y el saldo teórico de cierre.',
    )
    difference_justification = fields.Text(
        string='Justificación de Diferencia',
    )

    # Related records
    move_ids = fields.One2many(
        comodel_name='treasury.cash.move',
        inverse_name='session_id',
        string='Movimientos',
    )
    cashbox_ids = fields.One2many(
        comodel_name='treasury.cash.session.cashbox',
        inverse_name='session_id',
        string='Cajas por Divisa',
    )
    closing_account_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento de Cierre',
        readonly=True,
        copy=False,
    )

    # Notes
    opening_notes = fields.Text(string='Notas de Apertura')
    closing_notes = fields.Text(string='Notas de Cierre')

    # Lock
    is_locked = fields.Boolean(
        string='Bloqueada',
        default=False,
        help='Las sesiones bloqueadas no pueden ser modificadas.',
    )

    # Computed counts
    move_count = fields.Integer(
        string='Cant. Movimientos',
        compute='_compute_move_count',
    )
    total_income = fields.Monetary(
        string='Total Ingresos',
        currency_field='currency_id',
        compute='_compute_move_totals',
    )
    total_expense = fields.Monetary(
        string='Total Egresos',
        currency_field='currency_id',
        compute='_compute_move_totals',
    )
    opening_balance_by_currency = fields.Text(
        string='Saldo Inicial por Divisa',
        compute='_compute_balance_summary_by_currency',
    )
    total_income_by_currency = fields.Text(
        string='Ingresos por Divisa',
        compute='_compute_balance_summary_by_currency',
    )
    total_expense_by_currency = fields.Text(
        string='Egresos por Divisa',
        compute='_compute_balance_summary_by_currency',
    )
    closing_balance_theoretical_by_currency = fields.Text(
        string='Saldo Teórico por Divisa',
        compute='_compute_balance_summary_by_currency',
    )
    closing_balance_real_by_currency = fields.Text(
        string='Saldo Real por Divisa',
        compute='_compute_balance_summary_by_currency',
    )
    difference_by_currency = fields.Text(
        string='Diferencia por Divisa',
        compute='_compute_balance_summary_by_currency',
    )

    # Integrity
    integrity_hash = fields.Char(
        string='Hash de Integridad',
        readonly=True,
        copy=False,
    )

    @api.constrains('box_id', 'state')
    def _check_unique_open_session(self):
        for session in self:
            if session.state not in ('closed',):
                count = self.search_count([
                    ('box_id', '=', session.box_id.id),
                    ('state', 'not in', ['closed']),
                    ('id', '!=', session.id),
                ])
                if count > 0:
                    raise ValidationError(
                        _('Ya existe otra sesión abierta para la caja "%s".', session.box_id.name)
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            box_id = vals.get('box_id')
            if not box_id:
                raise UserError(_('Debe seleccionar una caja para la sesión.'))
            box = self.env['treasury.cash.box'].browse(box_id)
            if box.state != 'active':
                raise UserError(_('La caja "%s" debe estar activa para abrir una sesión.', box.name))
            open_session = self.search([
                ('box_id', '=', box_id),
                ('state', '!=', 'closed'),
            ], limit=1)
            if open_session:
                raise UserError(
                    _('La caja "%s" ya tiene una sesión en curso (%s). Debe cerrarla antes de abrir otra.',
                      box.name, open_session.name)
                )
        sessions = super().create(vals_list)
        for session in sessions:
            session._action_open()
        return sessions

    @api.depends('cashbox_ids.opening_amount', 'cashbox_ids.closing_amount',
                 'cashbox_ids.closing_amount_theoretical', 'cashbox_ids.difference')
    def _compute_balance_summary(self):
        """Summarize cashbox lines for the main currency."""
        for session in self:
            main_cb = session.cashbox_ids.filtered(
                lambda cb: cb.currency_id == session.currency_id
            )
            if main_cb:
                session.opening_balance = main_cb[0].opening_amount
                session.closing_balance_theoretical = main_cb[0].closing_amount_theoretical
                session.closing_balance_real = main_cb[0].closing_amount
                session.difference = main_cb[0].difference
            else:
                session.opening_balance = 0.0
                session.closing_balance_theoretical = 0.0
                session.closing_balance_real = 0.0
                session.difference = 0.0

    def _action_open(self):
        self.ensure_one()
        # Assign sequence name
        if self.name == '/':
            if self.box_id.session_sequence_id:
                self.name = self.box_id.session_sequence_id.next_by_id()
            else:
                self.name = self.env['ir.sequence'].next_by_code('treasury.cash.session') or '/'

        self.write({
            'state': 'opening_control',
        })

        # Create cashbox lines per currency from box journals
        self._create_cashbox_lines()

    def _create_cashbox_lines(self):
        """Create one cashbox line per currency configured in the box."""
        self.ensure_one()
        if self.cashbox_ids:
            return  # Already created

        currencies = self.box_id.journal_ids.mapped('currency_id')
        if not currencies:
            currencies = self.box_id.currency_id

        # Get last closed session for suggested amounts
        last_session = self.search([
            ('box_id', '=', self.box_id.id),
            ('state', '=', 'closed'),
            ('id', '!=', self.id),
        ], limit=1, order='stop_at desc')

        lines = []
        for currency in currencies:
            suggested = 0.0
            if last_session:
                last_cb = last_session.cashbox_ids.filtered(
                    lambda cb: cb.currency_id == currency
                )
                if last_cb:
                    suggested = last_cb[0].closing_amount or 0.0
            lines.append({
                'session_id': self.id,
                'currency_id': currency.id,
                'suggested_opening': suggested,
                'opening_amount': suggested,
            })
        if lines:
            self.env['treasury.cash.session.cashbox'].create(lines)

    def action_validate_opening(self):
        """Validate the opening amounts and move to 'opened' state."""
        self.ensure_one()
        if self.state != 'opening_control':
            raise UserError(_('La sesión ya fue abierta.'))
        if not self.cashbox_ids:
            raise UserError(_('No hay cajas por divisa configuradas.'))

        self.write({
            'start_at': fields.Datetime.now(),
            'state': 'opened',
        })
        lines = []
        for cb in self.cashbox_ids:
            lines.append('%s: %s' % (cb.currency_id.name, cb.opening_amount))
        self.message_post(body=_('Sesión abierta.<br/>%s', '<br/>'.join(lines)))


    def _compute_move_count(self):
        data = self.env['treasury.cash.move']._read_group(
            [('session_id', 'in', self.ids)],
            ['session_id'],
            ['__count'],
        )
        mapped = {session.id: count for session, count in data}
        for session in self:
            session.move_count = mapped.get(session.id, 0)

    def _compute_move_totals(self):
        for session in self:
            posted_moves = session.move_ids.filtered(lambda m: m.state == 'posted')
            session.total_income = sum(
                m.amount for m in posted_moves
                if m.move_type in ('income', 'transfer_in', 'bank_withdrawal')
            )
            session.total_expense = sum(
                m.amount for m in posted_moves
                if m.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit')
            )

    @api.depends(
        'cashbox_ids.currency_id',
        'cashbox_ids.opening_amount',
        'cashbox_ids.total_income',
        'cashbox_ids.total_expense',
        'cashbox_ids.closing_amount_theoretical',
        'cashbox_ids.closing_amount',
        'cashbox_ids.difference',
    )
    def _compute_balance_summary_by_currency(self):
        for session in self:
            opening_lines = []
            income_lines = []
            expense_lines = []
            theoretical_lines = []
            real_lines = []
            diff_lines = []

            for cb in session.cashbox_ids.sorted(key=lambda c: c.currency_id.name):
                currency = cb.currency_id
                opening_lines.append('%s: %s' % (currency.name, currency.format(cb.opening_amount or 0.0)))
                income_lines.append('%s: %s' % (currency.name, currency.format(cb.total_income or 0.0)))
                expense_lines.append('%s: %s' % (currency.name, currency.format(cb.total_expense or 0.0)))
                theoretical_lines.append('%s: %s' % (currency.name, currency.format(cb.closing_amount_theoretical or 0.0)))
                real_lines.append('%s: %s' % (currency.name, currency.format(cb.closing_amount or 0.0)))
                diff_lines.append('%s: %s' % (currency.name, currency.format(cb.difference or 0.0)))

            session.opening_balance_by_currency = '\n'.join(opening_lines) if opening_lines else '-'
            session.total_income_by_currency = '\n'.join(income_lines) if income_lines else '-'
            session.total_expense_by_currency = '\n'.join(expense_lines) if expense_lines else '-'
            session.closing_balance_theoretical_by_currency = '\n'.join(theoretical_lines) if theoretical_lines else '-'
            session.closing_balance_real_by_currency = '\n'.join(real_lines) if real_lines else '-'
            session.difference_by_currency = '\n'.join(diff_lines) if diff_lines else '-'

    def action_start_closing(self):
        self.ensure_one()
        if self.state != 'opened':
            raise UserError(_('Solo las sesiones en progreso pueden cerrarse.'))
        # Check for draft moves
        draft_moves = self.move_ids.filtered(lambda m: m.state == 'draft')
        if draft_moves:
            raise UserError(
                _('Hay %d movimientos en borrador. Contábilicelos o cancélelos antes de cerrar.', len(draft_moves))
            )
        self.write({
            'state': 'closing_control',
            'stop_at': fields.Datetime.now(),
        })

        # Prepare final counting lines by currency and force a fresh closing count.
        for cb in self.cashbox_ids:
            if cb.denomination_ids:
                cb.denomination_ids.write({'quantity': 0, 'count_type': 'closing'})
            else:
                cb._populate_denominations('closing')
            cb.closing_amount = 0.0

    def action_close(self):
        self.ensure_one()
        if self.state != 'closing_control':
            raise UserError(_('La sesión debe estar en control de cierre para cerrar.'))
        # Validate all cashbox lines have closing amounts
        for cb in self.cashbox_ids:
            if not cb.closing_amount and cb.closing_amount != 0:
                raise UserError(
                    _('Debe ingresar el monto de cierre para %s.', cb.currency_id.name)
                )

        # Validate difference justification (check all currencies)
        has_difference = any(
            not cb.currency_id.is_zero(cb.difference) for cb in self.cashbox_ids
        )
        if has_difference and not self.difference_justification:
            difference_lines = [
                '%s: %s' % (
                    cb.currency_id.name,
                    cb.currency_id.format(cb.difference),
                )
                for cb in self.cashbox_ids
                if not cb.currency_id.is_zero(cb.difference)
            ]
            raise UserError(
                _('Hay diferencias de cierre por divisa:\n%s\n\nDebe proporcionar una justificación.',
                  '\n'.join(difference_lines))
            )

        # Post difference entries per currency if any
        for cb in self.cashbox_ids:
            if not cb.currency_id.is_zero(cb.difference):
                self._post_difference_entry_for_currency(cb)

        # Generate integrity hash
        self._generate_integrity_hash()

        self.write({
            'state': 'closed',
            'closed_by_id': self.env.uid,
            'is_locked': True,
        })
        self._post_closing_message()

    def _post_difference_entry_for_currency(self, cashbox_line):
        """Post a difference journal entry for a specific currency cashbox line."""
        self.ensure_one()
        diff = cashbox_line.difference
        currency = cashbox_line.currency_id
        journal = self.box_id.get_journal_for_currency(currency)

        if diff < 0:
            if not journal.loss_account_id:
                raise UserError(
                    _('Configure una Cuenta de Pérdida en el diario "%s" para registrar diferencias de caja.', journal.name)
                )
            counterpart_account = journal.loss_account_id
            label = _('Diferencia de caja (Pérdida) — %s [%s]', self.name, currency.name)
        else:
            if not journal.profit_account_id:
                raise UserError(
                    _('Configure una Cuenta de Ganancia en el diario "%s" para registrar diferencias de caja.', journal.name)
                )
            counterpart_account = journal.profit_account_id
            label = _('Diferencia de caja (Ganancia) — %s [%s]', self.name, currency.name)

        move_vals = {
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': _('Diferencia de caja — %s [%s]', self.name, currency.name),
            'line_ids': [
                fields.Command.create({
                    'name': label,
                    'account_id': journal.default_account_id.id,
                    'debit': diff if diff > 0 else 0.0,
                    'credit': abs(diff) if diff < 0 else 0.0,
                }),
                fields.Command.create({
                    'name': label,
                    'account_id': counterpart_account.id,
                    'debit': abs(diff) if diff < 0 else 0.0,
                    'credit': diff if diff > 0 else 0.0,
                }),
            ],
        }
        account_move = self.env['account.move'].create(move_vals)
        account_move._post()
        self.closing_account_move_id = account_move

    def _generate_integrity_hash(self):
        import hashlib
        self.ensure_one()
        data = '|'.join([
            str(self.id),
            self.name or '',
            str(self.opening_balance),
            str(self.closing_balance_theoretical),
            str(self.closing_balance_real),
            str(self.difference),
            str(self.start_at),
            str(self.stop_at),
            str(self.user_id.id),
            str(len(self.move_ids)),
        ])
        self.integrity_hash = hashlib.sha256(data.encode('utf-8')).hexdigest()

    def _post_closing_message(self):
        self.ensure_one()
        body = _(
            'Sesión cerrada.<br/>'
            'Apertura: %(opening)s<br/>'
            'Teórico: %(theoretical)s<br/>'
            'Real: %(real)s<br/>'
            'Diferencia: %(diff)s',
            opening=self.opening_balance,
            theoretical=self.closing_balance_theoretical,
            real=self.closing_balance_real,
            diff=self.difference,
        )
        self.message_post(body=body)

    def action_view_moves(self):
        self.ensure_one()
        return {
            'name': _('Movimientos — %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.move',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {
                'default_session_id': self.id,
                'default_box_id': self.box_id.id,
            },
        }

    def action_reopen(self):
        self.ensure_one()
        if self.state != 'closing_control':
            raise UserError(_('Solo las sesiones en control de cierre pueden reabrirse.'))
        # Reset closing amounts on cashbox lines
        for cb in self.cashbox_ids:
            cb.closing_amount = 0
        self.write({
            'state': 'opened',
            'stop_at': False,
            'difference_justification': False,
        })

    def action_print_closing_report(self):
        self.ensure_one()
        return self.env.ref('treasury_cash.action_report_session_close').report_action(self)
