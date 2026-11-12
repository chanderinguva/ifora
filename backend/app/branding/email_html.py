"""Safe, table-based, MIME-ready HTML for Ifora's transactional identity mail.

The editor stores plain text intentionally. We HTML-escape every user-controlled value
and apply one maintained, email-client-compatible layout. No custom HTML, CSS, or JS
from tenants is executed, and mail always has an independent text/plain part.
"""
import base64
from html import escape
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from backend.app.branding.models import OrgBranding, OrgLogo
from backend.app.branding.templates import org_name
from backend.app.environment import label, name

_MARK = Path(__file__).resolve().parent / "assets" / "ifora-mark.png"
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_CID = "ifora-identity-logo"


def logo(db: Session) -> tuple[bytes, str]:
    custom = db.query(OrgLogo).first()
    if custom is None:
        return _MARK.read_bytes(), "image/png"
    if custom.content_type in ("image/png", "image/jpeg"):
        return custom.data, custom.content_type
    # Uploaded WebP works in the web UI but not in some Outlook desktop versions.
    if custom.content_type == "image/webp":
        from PIL import Image
        output = BytesIO()
        with Image.open(BytesIO(custom.data)) as img:
            img.convert("RGBA").save(output, format="PNG")
        return output.getvalue(), "image/png"
    return _MARK.read_bytes(), "image/png"


def _safe_link(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
            return url
        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1") and not parsed.username:
            return url
    except ValueError:
        pass
    return ""


def _text_html(body: str, link: str) -> str:
    paragraphs = []
    safe_url = _safe_link(link)
    for paragraph in body.strip().split("\n\n"):
        lines = []
        for line in paragraph.splitlines():
            item = escape(line, quote=True)
            if safe_url and link in line:
                item = item.replace(escape(link, quote=True),
                                    '<a href="' + escape(safe_url, quote=True) + '" style="color:#2563eb;text-decoration:underline;overflow-wrap:anywhere;">Open secure link</a>')
            lines.append(item)
        paragraphs.append('<p style="margin:0 0 18px;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:24px;color:#334155;">'
                          + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)


def _contrast(hex_color: str) -> str:
    n = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    luminance = 0.2126 * lin(n[0]) + 0.7152 * lin(n[1]) + 0.0722 * lin(n[2])
    return "#0f172a" if luminance > 0.179 else "#ffffff"


def render(db: Session, *, title: str, body: str, link: str = "",
           code: str = "", action_label: str = "", preview: bool = False) -> str:
    brand = db.query(OrgBranding).first()
    color = brand.primary_color if brand and brand.primary_color and _COLOR.fullmatch(brand.primary_color) else "#4F46E5"
    foreground = _contrast(color)
    organisation = escape(org_name(db), quote=True)
    mode = name()
    badge = ('' if mode == "production" else
             '<tr><td style="padding:12px 32px;background:#fff7ed;color:#9a3412;font:700 12px Arial,Helvetica,sans-serif;letter-spacing:1px;">'
             + escape(label()) + ' ENVIRONMENT — Not production</td></tr>')
    target = _safe_link(link)
    button = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:10px 0 26px;"><tr><td bgcolor="' + color +
              '" style="border-radius:6px;"><a href="' + escape(target, quote=True) +
              '" style="display:inline-block;padding:14px 24px;font:700 15px Arial,Helvetica,sans-serif;color:' + foreground +
              ';text-decoration:none;border-radius:6px;">' + escape(action_label or "Continue securely") + '</a></td></tr></table>') if target else ''
    code_card = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:8px 0 24px;">'
                 '<tr><td style="padding:18px;background:#f1f5f9;border:1px solid #e2e8f0;text-align:center;'
                 'font:700 24px Consolas,Menlo,monospace;letter-spacing:2px;color:#0f172a;">'
                 + escape(code) + '</td></tr></table>') if code else ''
    image_data, image_type = logo(db)
    image_src = ('data:' + image_type + ';base64,' + base64.b64encode(image_data).decode("ascii")) if preview else 'cid:' + _CID
    # Word/Outlook-safe presentation tables and inline styles; no JS, SVG or CSS grid.
    return (('<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="color-scheme" content="light"></head>'
             '<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">'
             '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#f1f5f9">'
             '<tr><td align="center" style="padding:32px 12px;">'
             '<table role="presentation" width="600" border="0" cellpadding="0" cellspacing="0" '
             'style="width:100%;max-width:600px;background:#ffffff;border:1px solid #e2e8f0;">'
             '<tr><td style="padding:28px 32px;border-bottom:1px solid #e2e8f0;">'
             '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
             '<td width="42" valign="middle"><img src="' + image_src +
             '" alt="" width="38" height="38" style="width:38px;height:38px;display:block;border:0;object-fit:contain;"></td>'
             '<td valign="middle" style="padding-left:12px;font:700 21px Georgia,Times New Roman,serif;color:#0f172a;">'
             + organisation + '</td></tr></table></td></tr>')
            + badge +
            ('<tr><td style="padding:30px 32px 18px;"><h1 style="margin:0 0 22px;font:700 24px Arial,Helvetica,sans-serif;'
             'line-height:32px;color:#0f172a;">' + escape(title) + '</h1>'
             + _text_html(body, link) + code_card + button +
             '<p style="margin:0 0 8px;font:13px Arial,Helvetica,sans-serif;line-height:20px;color:#64748b;">'
             'For your security, never share one-time codes or passwords. If this request was unexpected, '
             'contact your organization administrator directly.</p></td></tr>'
             '<tr><td style="padding:20px 32px;border-top:1px solid #e2e8f0;background:#f8fafc;">'
             '<p style="margin:0;font:12px Arial,Helvetica,sans-serif;color:#64748b;">'
             + organisation + ' · Powered by Ifora · ' + escape(mode.title()) +
             '</p><p style="margin:8px 0 0;font:12px Arial,Helvetica,sans-serif;color:#64748b;">'
             'This is an automated identity notification. Please do not reply.</p></td></tr>'
             '</table></td></tr></table></body></html>'))


def logo_attachment(db: Session) -> tuple[bytes, str, str]:
    data, content_type = logo(db)
    return data, content_type, _CID
