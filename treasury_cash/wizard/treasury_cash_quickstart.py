from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TreasuryCashQuickstart(models.TransientModel):
    _name = 'treasury.cash.quickstart'
    _description = 'Asistente de Configuración Rápida'

    name = fields.Char(
        string='Nombre de la Caja',
        required=True,
        default='Tesorería General',
    )
    code = fields.Char(
        string='Código',
        required=True,
        default='TG',
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
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_ids = fields.Many2many(
        comodel_name='res.currency',
        string='Divisas',
        required=True,
        default=lambda self: self.env.company.currency_id,
        help='Seleccione todas las divisas que manejará esta caja. Se creará un diario por divisa.',
    )
    responsible_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsable',
        default=lambda self: self.env.uid,
    )
    branch_id = fields.Many2one(
        comodel_name='res.partner',
        string='Sucursal',
        domain="[('is_company', '=', True)]",
    )
    create_accounts = fields.Boolean(
        string='Crear Cuentas Automáticamente',
        default=True,
        help='Crear cuentas de efectivo, cuentas de diferencia y cuentas de transferencia dedicadas si no existen.',
    )
    cash_account_prefix = fields.Char(
        string='Prefijo de Cuenta de Efectivo',
        default='1.1.1.02',
        help='Prefijo para nuevas cuentas de efectivo (ej. 1.1.1.02.001 para ARS, 1.1.1.02.002 para USD).',
    )
    difference_account_code = fields.Char(
        string='Código de Cuenta de Diferencias',
        default='5.9.9.01',
        help='Código de cuenta para diferencias de arqueo (pérdida/ganancia).',
    )
    transfer_account_code = fields.Char(
        string='Código de Cuenta de Transferencias',
        default='1.1.1.99',
        help='Código de cuenta para transferencias internas entre cajas.',
    )

    def action_quickstart(self):
        self.ensure_one()

        created_items = []

        # 1. Create or find accounts
        accounts_by_currency = {}
        difference_account = None
        transfer_account = None

        if self.create_accounts:
            accounts_by_currency, difference_account, transfer_account = self._create_accounts()
            if accounts_by_currency:
                created_items.append(_('%d cuenta(s) de efectivo', len(accounts_by_currency)))
            if difference_account:
                created_items.append(_('Cuenta de diferencias: %s', difference_account.code))
            if transfer_account:
                created_items.append(_('Cuenta de transferencias: %s', transfer_account.code))

        # 2. Create journals (one per currency)
        journals = self._create_journals(accounts_by_currency, difference_account)
        created_items.append(_('%d diario(s)', len(journals)))

        # 3. Create the cash box
        box = self._create_box(journals)
        created_items.append(_('Caja: %s', box.name))

        # 4. Activate the box
        box.action_activate()

        # Post summary message as plain text (avoid raw HTML in chatter)
        summary = '\n'.join(created_items)
        box.message_post(
            body=_('Configuración rápida completada:\n%s', summary),
            message_type='comment',
        )

        return {
            'name': _('Caja — %s', box.name),
            'type': 'ir.actions.act_window',
            'res_model': 'treasury.cash.box',
            'view_mode': 'form',
            'res_id': box.id,
        }

    def _create_accounts(self):
        AccountAccount = self.env['account.account']
        accounts_by_currency = {}

        for currency in self.currency_ids:
            account = AccountAccount.create({
                'name': self.name,
                'code': self._next_cash_account_code(),
                'account_type': 'asset_cash',
                'currency_id': currency.id if currency != self.company_id.currency_id else False,
                'reconcile': False,
            })
            accounts_by_currency[currency] = account

        # Difference account (expense type for losses)
        difference_account = None
        if self.difference_account_code:
            existing = AccountAccount.search([
                ('code', '=', self.difference_account_code),
                ('company_ids', 'in', self.company_id.id),
            ], limit=1)
            if existing:
                difference_account = existing
            else:
                difference_account = AccountAccount.create({
                    'name': _('Diferencias de Arqueo'),
                    'code': self.difference_account_code,
                    'account_type': 'expense',
                    'reconcile': False,
                })

        # Transfer account (current asset for bridge)
        transfer_account = None
        if self.transfer_account_code:
            existing = AccountAccount.search([
                ('code', '=', self.transfer_account_code),
                ('company_ids', 'in', self.company_id.id),
            ], limit=1)
            if existing:
                transfer_account = existing
            else:
                transfer_account = AccountAccount.create({
                    'name': _('Transferencias Internas de Caja'),
                    'code': self.transfer_account_code,
                    'account_type': 'asset_current',
                    'reconcile': True,
                })

        return accounts_by_currency, difference_account, transfer_account

    def _next_cash_account_code(self):
        """Return next available account code for the configured cash prefix."""
        self.ensure_one()
        AccountAccount = self.env['account.account']
        like_pattern = '%s.%%' % self.cash_account_prefix
        accounts = AccountAccount.search([
            ('code', '=like', like_pattern),
            ('company_ids', 'in', self.company_id.id),
        ])
        max_suffix = 0
        for account in accounts:
            if not account.code or not account.code.startswith('%s.' % self.cash_account_prefix):
                continue
            suffix = account.code[len(self.cash_account_prefix) + 1:]
            if suffix.isdigit():
                max_suffix = max(max_suffix, int(suffix))
        return '%s.%03d' % (self.cash_account_prefix, max_suffix + 1)

    def _create_journals(self, accounts_by_currency, difference_account):
        AccountJournal = self.env['account.journal']
        journals = {}

        for currency in self.currency_ids:
            # Check if journal already exists
            journal_code = 'C%s%s' % (
                self.code[:2].upper(),
                currency.name[:3].upper() if len(self.currency_ids) > 1 else '',
            )
            # Ensure code is max 5 chars
            journal_code = journal_code[:5]

            existing = AccountJournal.search([
                ('code', '=', journal_code),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            if existing:
                journals[currency] = existing
            else:
                vals = {
                    'name': _('Efectivo %s — %s', currency.name, self.name) if len(self.currency_ids) > 1
                            else _('Efectivo — %s', self.name),
                    'code': journal_code,
                    'type': 'cash',
                    'company_id': self.company_id.id,
                }
                # Set default account if we created one
                if currency in accounts_by_currency:
                    vals['default_account_id'] = accounts_by_currency[currency].id

                # Set currency if not company currency
                if currency != self.company_id.currency_id:
                    vals['currency_id'] = currency.id

                # Set profit/loss accounts for differences
                if difference_account:
                    vals['profit_account_id'] = difference_account.id
                    vals['loss_account_id'] = difference_account.id

                journal = AccountJournal.create(vals)
                journals[currency] = journal

        return journals

    def _create_box(self, journals):
        box = self.env['treasury.cash.box'].create({
            'name': self.name,
            'code': self.code,
            'box_type': self.box_type,
            'company_id': self.company_id.id,
            'currency_id': self.company_id.currency_id.id,
            'responsible_user_id': self.responsible_user_id.id if self.responsible_user_id else False,
            'branch_id': self.branch_id.id if self.branch_id else False,
            'journal_ids': [
                fields.Command.create({
                    'journal_id': journal.id,
                    'currency_id': currency.id,
                })
                for currency, journal in journals.items()
            ],
        })
        return box
