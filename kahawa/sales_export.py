"""PDF download for the Manage sales report."""

from io import BytesIO

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor('#1A120C')
MUTED = colors.HexColor('#6B5E53')
LINE = colors.HexColor('#E7DDD2')
HEAD = colors.HexColor('#F6F0EA')
CARAMEL = colors.HexColor('#8C4A24')


def _safe(value) -> str:
    text = '' if value is None else str(value)
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .encode('latin-1', 'replace')
        .decode('latin-1')
    )


def _styles():
    cell = ParagraphStyle(
        'SalesCell',
        fontName='Helvetica',
        fontSize=9,
        textColor=INK,
        leading=12,
    )
    return {
        'kicker': ParagraphStyle(
            'SalesKicker',
            fontName='Helvetica',
            fontSize=9,
            textColor=MUTED,
            leading=12,
        ),
        'title': ParagraphStyle(
            'SalesTitle',
            fontName='Helvetica-Bold',
            fontSize=16,
            textColor=INK,
            leading=20,
            spaceBefore=1,
            spaceAfter=1,
        ),
        'section': ParagraphStyle(
            'SalesSection',
            fontName='Helvetica-Bold',
            fontSize=11,
            textColor=CARAMEL,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
        ),
        'cell': cell,
        'right': ParagraphStyle(
            'SalesCellRight',
            parent=cell,
            alignment=TA_RIGHT,
        ),
        'head': ParagraphStyle(
            'SalesHead',
            fontName='Helvetica-Bold',
            fontSize=8,
            textColor=MUTED,
            leading=10,
        ),
    }


def _styled(table, header=False):
    commands = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, LINE),
    ]
    if header:
        commands.append(('BACKGROUND', (0, 0), (-1, 0), HEAD))
    table.setStyle(TableStyle(commands))
    return table


def _summary_table(rows, styles):
    data = [
        [
            Paragraph(_safe(label), styles['cell']),
            Paragraph(_safe(amount), styles['right']),
            Paragraph(_safe(note), styles['right']),
        ]
        for label, amount, note in rows
    ]
    table = Table(data, colWidths=[62 * mm, 48 * mm, 68 * mm])
    return _styled(table)


def _item_table(rows, empty, styles):
    if not rows:
        return Paragraph(_safe(empty), styles['kicker'])
    data = [[
        Paragraph('Item', styles['head']),
        Paragraph('Qty', styles['head']),
        Paragraph('Amount', styles['head']),
    ]]
    for row in rows:
        data.append([
            Paragraph(_safe(row['name']), styles['cell']),
            Paragraph(_safe(row['qty']), styles['right']),
            Paragraph(f"KSh {_safe(row['revenue'])}", styles['right']),
        ])
    table = Table(data, colWidths=[112 * mm, 24 * mm, 42 * mm])
    return _styled(table, header=True)


def _order_table(rows, empty, styles, include_method):
    if not rows:
        return Paragraph(_safe(empty), styles['kicker'])
    header = [
        Paragraph('Order', styles['head']),
        Paragraph('Customer', styles['head']),
        Paragraph('When', styles['head']),
    ]
    if include_method:
        header.append(Paragraph('Method', styles['head']))
    header.append(Paragraph('Amount', styles['head']))
    data = [header]
    for row in rows:
        line = [
            Paragraph(_safe(row['code']), styles['cell']),
            Paragraph(_safe(row['name']), styles['cell']),
            Paragraph(_safe(row['when']), styles['cell']),
        ]
        if include_method:
            line.append(Paragraph(_safe(row.get('method') or ''), styles['cell']))
        line.append(Paragraph(f"KSh {_safe(row['total'])}", styles['right']))
        data.append(line)
    if include_method:
        widths = [36 * mm, 48 * mm, 32 * mm, 24 * mm, 38 * mm]
    else:
        widths = [40 * mm, 62 * mm, 36 * mm, 40 * mm]
    table = Table(data, colWidths=widths)
    return _styled(table, header=True)


def _logo():
    """Wordmark on white so the transparent PNG prints cleanly."""
    path = settings.BASE_DIR / 'static' / 'images' / 'kahawa-logo.png'
    if not path.is_file():
        return None
    from PIL import Image as PilImage

    mark = PilImage.open(path).convert('RGBA')
    sheet = PilImage.new('RGB', mark.size, (255, 255, 255))
    sheet.paste(mark, mask=mark.getchannel('A'))
    buf = BytesIO()
    sheet.save(buf, format='PNG')
    buf.seek(0)
    width = 52 * mm
    height = width * mark.size[1] / mark.size[0]
    image = Image(buf, width=width, height=height)
    image.hAlign = 'CENTER'
    return image


def render_sales_pdf(ctx) -> bytes:
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{settings.CAFE_NAME} sales",
    )
    logo = _logo()
    story = []
    if logo is not None:
        story.append(logo)
        story.append(Spacer(1, 4))
    else:
        story.append(Paragraph(_safe(settings.CAFE_NAME), styles['kicker']))
    story.extend([
        Paragraph('Sales', styles['title']),
        Paragraph(_safe(ctx['period_label']), styles['kicker']),
        Paragraph(
            _safe('Downloaded ' + timezone.localtime().strftime('%d %b %Y, %H:%M')),
            styles['kicker'],
        ),
    ])
    if ctx.get('error'):
        story.append(Spacer(1, 6))
        story.append(Paragraph(_safe(ctx['error']), styles['kicker']))
    summary = [
        ('Paid', f"KSh {ctx['paid_total']}", f"{ctx['paid_count']} in this period"),
        ('Cash', f"KSh {ctx['cash']['display']}", f"{ctx['cash']['count']} paid"),
        ('M-Pesa', f"KSh {ctx['mpesa']['display']}", f"{ctx['mpesa']['count']} paid"),
        ('Still unpaid', f"KSh {ctx['unpaid_total']}", f"{ctx['unpaid_count']} open, any day"),
        ('VAT included', f"KSh {ctx['tax_display']}", ''),
        ('Discounts', f"KSh {ctx['discount_display']}", ''),
        ('Opened', str(ctx['opened_count']), ''),
        ('Cancelled', str(ctx['cancelled_count']), ''),
    ]
    if ctx.get('show_other'):
        summary.append(
            (
                'Other payments',
                f"KSh {ctx['other']['display']}",
                f"{ctx['other']['count']} paid",
            )
        )
    story.append(Spacer(1, 10))
    story.append(_summary_table(summary, styles))
    story.append(Paragraph('Products', styles['section']))
    story.append(_item_table(ctx['products'], 'No product sales in this period.', styles))
    story.append(Paragraph('Packages', styles['section']))
    story.append(_item_table(ctx['packages'], 'No package sales in this period.', styles))
    story.append(Paragraph('Still to collect', styles['section']))
    story.append(
        _order_table(
            ctx['unpaid_orders'],
            'Nothing left unpaid.',
            styles,
            include_method=False,
        )
    )
    story.append(Paragraph('Paid orders', styles['section']))
    story.append(
        _order_table(
            ctx['orders'],
            'No paid orders in this period.',
            styles,
            include_method=True,
        )
    )
    doc.build(story)
    return buffer.getvalue()
