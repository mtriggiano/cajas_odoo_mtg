from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TreasuryCashSessionCashbox(models.Model):
    _name = 'treasury.cash.session.cashbox'
    _description = 'Caja por Divisa en Sesión'
    _order = 'currency_id'

    session_id = fields.Many2one(
        comodel_name='treasury.cash.session',
        string='Sesión',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa',
        required=True,
    )
    # Opening
    suggested_opening = fields.Monetary(
        string='Sugerido Apertura',
        currency_field='currency_id',
        readonly=True,
        help='Saldo real de cierre de la sesión anterior para esta divisa.',
    )
    opening_amount = fields.Monetary(
        string='Monto Apertura',
        currency_field='currency_id',
        help='Monto de apertura para esta divisa.',
    )
    # Closing
    closing_amount_theoretical = fields.Monetary(
        string='Teórico Cierre',
        currency_field='currency_id',
        compute='_compute_closing_theoretical',
        store=True,
    )
    closing_amount = fields.Monetary(
        string='Monto Cierre',
        currency_field='currency_id',
    )
    difference = fields.Monetary(
        string='Diferencia',
        currency_field='currency_id',
        compute='_compute_difference',
        store=True,
    )
    # Moves for this currency
    move_ids = fields.One2many(
        comodel_name='treasury.cash.move',
        inverse_name='cashbox_id',
        string='Movimientos',
    )
    move_count = fields.Integer(
        string='Cant. Movimientos',
        compute='_compute_move_count',
    )
    # Denomination lines (optional counting tool)
    denomination_ids = fields.One2many(
        comodel_name='treasury.cash.denomination',
        inverse_name='cashbox_id',
        string='Detalle de Billetes',
    )
    denomination_total = fields.Monetary(
        string='Total Conteo',
        currency_field='currency_id',
        compute='_compute_denomination_total',
        store=True,
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
    state = fields.Selection(
        related='session_id.state',
        store=False,
    )
    box_id = fields.Many2one(
        related='session_id.box_id',
        store=False,
    )

    def _compute_move_count(self):
        for cb in self:
            cb.move_count = len(cb.move_ids)

    @api.depends('move_ids.amount', 'move_ids.move_type', 'move_ids.state')
    def _compute_move_totals(self):
        for cb in self:
            posted = cb.move_ids.filtered(lambda m: m.state == 'posted')
            cb.total_income = sum(
                m.amount for m in posted
                if m.move_type in ('income', 'transfer_in', 'bank_withdrawal')
            )
            cb.total_expense = sum(
                m.amount for m in posted
                if m.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit')
            )

    @api.depends('denomination_ids.subtotal')
    def _compute_denomination_total(self):
        for line in self:
            line.denomination_total = sum(line.denomination_ids.mapped('subtotal'))

    @api.depends('opening_amount', 'move_ids.amount',
                 'move_ids.move_type', 'move_ids.state')
    def _compute_closing_theoretical(self):
        for cb in self:
            posted_moves = cb.move_ids.filtered(
                lambda m: m.state == 'posted'
            )
            income = sum(
                m.amount for m in posted_moves
                if m.move_type in ('income', 'transfer_in', 'bank_withdrawal', 'adjustment')
                and m.amount > 0
            )
            expense = sum(
                m.amount for m in posted_moves
                if m.move_type in ('expense', 'transfer_out', 'supplier_payment', 'bank_deposit')
            )
            negative_adj = sum(
                abs(m.amount) for m in posted_moves
                if m.move_type == 'adjustment' and m.amount < 0
            )
            cb.closing_amount_theoretical = cb.opening_amount + income - expense - negative_adj

    @api.depends('closing_amount', 'closing_amount_theoretical')
    def _compute_difference(self):
        for cb in self:
            if cb.closing_amount:
                cb.difference = cb.closing_amount - cb.closing_amount_theoretical
            else:
                cb.difference = 0.0

    def action_open_cashbox(self):
        """Open the cashbox form with embedded moves for this currency."""
        self.ensure_one()
        return {
            'name': _('Caja %s — %s', self.currency_id.name, self.session_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.session.cashbox',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {
                'form_view_ref': 'treasury_cash.treasury_cash_session_cashbox_view_form',
                'create': False,
            },
        }

    def action_count_bills(self):
        """Open denomination counting wizard for this cashbox line."""
        self.ensure_one()
        count_type = 'opening' if self.session_id.state == 'opening_control' else 'closing'
        # Populate denomination lines if empty
        if not self.denomination_ids:
            self._populate_denominations(count_type)
        return {
            'name': _('Conteo de Billetes — %s', self.currency_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.session.cashbox',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {'form_view_ref': 'treasury_cash.treasury_cash_session_cashbox_count_form'},
        }

    def action_apply_count(self):
        """Apply denomination total to the opening or closing amount."""
        self.ensure_one()
        total = self.denomination_total
        if self.session_id.state == 'opening_control':
            self.opening_amount = total
        elif self.session_id.state == 'closing_control':
            self.closing_amount = total
        return {'type': 'ir.actions.act_window_close'}

    def _populate_denominations(self, count_type):
        """Create denomination lines from configured bills."""
        self.ensure_one()
        Bill = self.env['treasury.cash.bill']
        bills = Bill.get_bills_for_box(self.session_id.box_id, self.currency_id)
        lines = []
        for bill in bills:
            lines.append({
                'cashbox_id': self.id,
                'session_id': self.session_id.id,
                'count_type': count_type,
                'bill_id': bill.id,
                'currency_id': self.currency_id.id,
                'denomination': bill.value,
                'quantity': 0,
            })
        if lines:
            self.env['treasury.cash.denomination'].create(lines)
