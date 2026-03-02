# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Operaciones de Caja',
    'version': '19.0.2.0.0',
    'category': 'Accounting/Treasury',
    'summary': 'Gestión Integral de Cajas Operativas — multiempresa, multisucursal, multi-moneda',
    'description': """
Treasury Cash Operations
========================
Módulo profesional de gestión de cajas operativas para clínicas y organizaciones complejas.

Funcionalidades principales:
- Múltiples cajas (tesorería general, cajas chicas, fondos fijos)
- Sesiones diarias con apertura, movimientos y cierre con arqueo
- Multi-moneda (1 diario por divisa por caja)
- Transferencias atómicas entre cajas con cuenta puente
- Pagos a proveedor simplificados (reutiliza account.payment)
- Dashboard con KPIs y alertas
- Reportes PDF con hash de integridad
- Roles diferenciados (Tesorero, Responsable, Auditor)
- Wizard Quickstart para configuración inicial
- Integración opcional con módulo Sign para firma digital
    """,
    'author': 'Grupo Orange SRL',
    'website': 'https://grupoorange.ar',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'analytic',
        'mail',
    ],
    'data': [
        # Security
        'security/treasury_cash_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/treasury_cash_sequence.xml',
        'data/treasury_cash_bill_data.xml',
        # Wizards
        'wizard/treasury_cash_quickstart_views.xml',
        # Views
        'views/treasury_cash_box_views.xml',
        'views/treasury_cash_session_views.xml',
        'views/treasury_cash_move_views.xml',
        'views/treasury_cash_transfer_views.xml',
        'views/treasury_cash_session_cashbox_views.xml',
        'views/treasury_cash_bill_views.xml',
        'views/treasury_cash_denomination_views.xml',
        'views/treasury_cash_dashboard_views.xml',
        'views/treasury_cash_menus.xml',
        # Reports
        'report/treasury_cash_report.xml',
        'report/treasury_cash_move_report_template.xml',
        'report/treasury_cash_session_close_report_template.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
