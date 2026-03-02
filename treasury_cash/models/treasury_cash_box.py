from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TreasuryCashBox(models.Model):
    _name = 'treasury.cash.box'
    _description = 'Caja Operativa'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Código',
        required=True,
        tracking=True,
    )
    box_type = fields.Selection(
        selection=[
            ('general', 'Tesorería General'),
            ('petty_cash', 'Caja Chica'),
            ('fixed_fund', 'Fondo Fijo'),
        ],
        string='Tipo',
        required=True,
        default='general',
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    branch_id = fields.Many2one(
        comodel_name='res.partner',
        string='Sucursal',
        domain="[('is_company', '=', True)]",
        tracking=True,
        help='Sucursal o ubicación donde opera esta caja.',
    )
    journal_ids = fields.One2many(
        comodel_name='treasury.cash.box.journal',
        inverse_name='box_id',
        string='Diarios por Divisa',
    )
    responsible_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsable',
        tracking=True,
        default=lambda self: self.env.uid,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa Principal',
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    min_balance = fields.Monetary(
        string='Saldo Mínimo',
        currency_field='currency_id',
        help='Umbral de alerta cuando el saldo cae por debajo de este monto.',
    )
    max_movement_amount = fields.Monetary(
        string='Monto Máximo por Movimiento',
        currency_field='currency_id',
        help='Monto máximo por movimiento individual. 0 = sin límite.',
    )
    require_approval_above = fields.Monetary(
        string='Requiere Aprobación Superior a',
        currency_field='currency_id',
        help='Movimientos por encima de este monto requieren aprobación del tesorero. 0 = sin aprobación requerida.',
    )
    sequence = fields.Integer(string='Secuencia', default=10)
    sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia de Movimientos',
        copy=False,
        help='Secuencia usada para numerar movimientos en esta caja.',
    )
    session_sequence_id = fields.Many2one(
        comodel_name='ir.sequence',
        string='Secuencia de Sesiones',
        copy=False,
        help='Secuencia usada para numerar sesiones en esta caja.',
    )
    bill_ids = fields.Many2many(
        comodel_name='treasury.cash.bill',
        relation='treasury_cash_bill_box_rel',
        column1='box_id',
        column2='bill_id',
        string='Billetes/Monedas',
        help='Denominaciones disponibles para el arqueo de esta caja. Si está vacío, se usan todas las denominaciones configuradas.',
    )
    active = fields.Boolean(default=True, tracking=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('active', 'Activa'),
            ('suspended', 'Suspendida'),
        ],
        string='Estado',
        default='draft',
        required=True,
        tracking=True,
    )

    # Computed fields
    current_session_id = fields.Many2one(
        comodel_name='treasury.cash.session',
        string='Sesión Actual',
        compute='_compute_current_session',
    )
    current_balance = fields.Monetary(
        string='Saldo Actual',
        currency_field='currency_id',
        compute='_compute_current_balance',
    )
    session_count = fields.Integer(
        string='Sesiones',
        compute='_compute_session_count',
    )

    # KPI fields
    today_income = fields.Monetary(
        string='Ingresos del Día',
        currency_field='currency_id',
        compute='_compute_today_kpis',
    )
    today_expense = fields.Monetary(
        string='Egresos del Día',
        currency_field='currency_id',
        compute='_compute_today_kpis',
    )
    current_balance_by_currency = fields.Text(
        string='Saldo Actual por Divisa',
        compute='_compute_currency_state_texts',
    )
    today_income_by_currency = fields.Text(
        string='Ingresos del Día por Divisa',
        compute='_compute_currency_state_texts',
    )
    today_expense_by_currency = fields.Text(
        string='Egresos del Día por Divisa',
        compute='_compute_currency_state_texts',
    )
    balance_alert = fields.Boolean(
        string='Alerta de Saldo',
        compute='_compute_balance_alert',
    )

    _uniq_code_company = models.Constraint(
        'unique(code, company_id)',
        'El código debe ser único por empresa.',
    )

    def _compute_current_session(self):
        for box in self:
            box.current_session_id = self.env['treasury.cash.session'].search([
                ('box_id', '=', box.id),
                ('state', 'not in', ['closed']),
            ], limit=1)

    def _compute_current_balance(self):
        for box in self:
            last_session = self.env['treasury.cash.session'].search([
                ('box_id', '=', box.id),
                ('state', '=', 'closed'),
            ], limit=1, order='stop_at desc')
            if last_session:
                box.current_balance = last_session.closing_balance_real
            else:
                # Check if there's an open session
                open_session = box.current_session_id
                if open_session:
                    box.current_balance = open_session.closing_balance_theoretical
                else:
                    box.current_balance = 0.0

    def _compute_session_count(self):
        data = self.env['treasury.cash.session']._read_group(
            [('box_id', 'in', self.ids)],
            ['box_id'],
            ['__count'],
        )
        mapped = {box.id: count for box, count in data}
        for box in self:
            box.session_count = mapped.get(box.id, 0)

    def _compute_today_kpis(self):
        today = fields.Date.context_today(self)
        for box in self:
            moves = self.env['treasury.cash.move'].search([
                ('box_id', '=', box.id),
                ('date', '=', today),
                ('state', '=', 'posted'),
            ])
            box.today_income = sum(m.amount for m in moves if m.move_type in ('income', 'transfer_in', 'bank_withdrawal'))
            box.today_expense = sum(m.amount for m in moves if m.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit'))

    @api.depends(
        'current_session_id',
        'current_session_id.cashbox_ids.currency_id',
        'current_session_id.cashbox_ids.closing_amount_theoretical',
        'current_session_id.cashbox_ids.closing_amount',
    )
    def _compute_currency_state_texts(self):
        today = fields.Date.context_today(self)
        for box in self:
            # Balance by currency: current open session (theoretical) or last closed session (real)
            balance_lines = []
            session = box.current_session_id
            if session:
                for cb in session.cashbox_ids.sorted(key=lambda c: c.currency_id.name):
                    balance_lines.append('%s: %s' % (cb.currency_id.name, cb.closing_amount_theoretical))
            else:
                last_session = self.env['treasury.cash.session'].search([
                    ('box_id', '=', box.id),
                    ('state', '=', 'closed'),
                ], limit=1, order='stop_at desc')
                for cb in last_session.cashbox_ids.sorted(key=lambda c: c.currency_id.name):
                    balance_lines.append('%s: %s' % (cb.currency_id.name, cb.closing_amount or 0.0))

            # Daily totals by currency
            moves = self.env['treasury.cash.move'].search([
                ('box_id', '=', box.id),
                ('date', '=', today),
                ('state', '=', 'posted'),
            ])
            currencies = moves.mapped('currency_id')
            income_lines = []
            expense_lines = []
            for currency in currencies.sorted(key=lambda c: c.name):
                cmoves = moves.filtered(lambda m: m.currency_id == currency)
                income = sum(
                    m.amount for m in cmoves
                    if m.move_type in ('income', 'transfer_in', 'bank_withdrawal')
                )
                expense = sum(
                    m.amount for m in cmoves
                    if m.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit')
                )
                income_lines.append('%s: %s' % (currency.name, income))
                expense_lines.append('%s: %s' % (currency.name, expense))

            box.current_balance_by_currency = '\n'.join(balance_lines) if balance_lines else '-'
            box.today_income_by_currency = '\n'.join(income_lines) if income_lines else '-'
            box.today_expense_by_currency = '\n'.join(expense_lines) if expense_lines else '-'

    def _compute_balance_alert(self):
        for box in self:
            box.balance_alert = box.min_balance > 0 and box.current_balance < box.min_balance

    def action_activate(self):
        for box in self:
            if not box.journal_ids:
                raise ValidationError(_('Debe configurar al menos un diario antes de activar la caja.'))
            if not box.sequence_id:
                box._create_sequences()
            box.state = 'active'

    def action_suspend(self):
        for box in self:
            if box.current_session_id:
                raise ValidationError(_('No puede suspender una caja con una sesión abierta.'))
            box.state = 'suspended'

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_open_sessions(self):
        self.ensure_one()
        return {
            'name': _('Sesiones — %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.session',
            'view_mode': 'list,form',
            'domain': [('box_id', '=', self.id)],
            'context': {'default_box_id': self.id},
        }

    def action_new_session(self):
        self.ensure_one()
        if self.state != 'active':
            raise ValidationError(_('La caja debe estar activa para abrir una nueva sesión.'))
        if self.current_session_id:
            raise ValidationError(_('Ya existe una sesión abierta para esta caja.'))
        session = self.env['treasury.cash.session'].create({
            'box_id': self.id,
        })
        return {
            'name': _('Sesión — %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.session',
            'view_mode': 'form',
            'res_id': session.id,
        }

    def _create_sequences(self):
        self.ensure_one()
        IrSequence = self.env['ir.sequence']
        if not self.sequence_id:
            self.sequence_id = IrSequence.create({
                'name': _('Mov. Tesorería — %s', self.name),
                'code': 'treasury.cash.move.%s' % self.code.lower(),
                'prefix': '%s/%%(year)s/' % self.code.upper(),
                'padding': 5,
                'company_id': self.company_id.id,
            })
        if not self.session_sequence_id:
            self.session_sequence_id = IrSequence.create({
                'name': _('Sesión Tesorería — %s', self.name),
                'code': 'treasury.cash.session.%s' % self.code.lower(),
                'prefix': 'S-%s/%%(year)s/' % self.code.upper(),
                'padding': 4,
                'company_id': self.company_id.id,
            })

    def get_journal_for_currency(self, currency):
        self.ensure_one()
        box_journal = self.journal_ids.filtered(lambda bj: bj.currency_id == currency)
        if not box_journal:
            # Fallback: try company currency with journal that has no specific currency
            box_journal = self.journal_ids.filtered(
                lambda bj: bj.currency_id == self.company_id.currency_id
            )
        if not box_journal:
            raise ValidationError(
                _('No hay diario configurado para la divisa %s en la caja %s.', currency.name, self.name)
            )
        return box_journal[0].journal_id
