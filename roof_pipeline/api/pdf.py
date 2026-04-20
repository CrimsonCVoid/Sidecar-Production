"""PDF generation endpoints (API-PDF-01..04).

Four POST routes, each writes to a temp file, uploads to Supabase Storage
(bucket: ``pdf_output_bucket``), returns a signed URL. Auth model: the
Next.js proxy verifies the Supabase session and forwards the request
with ``x-api-key: INTERNAL_API_KEY``; this router validates the header.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from supabase import Client

from .config import Settings
from .deps import get_settings, get_supabase

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth — validate internal API key from the Next.js proxy layer
# ---------------------------------------------------------------------------


def require_internal_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    expected = settings.internal_api_key
    if not expected:
        # Dev default: no key configured -> allow.
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


# ---------------------------------------------------------------------------
# Storage helper
# ---------------------------------------------------------------------------


def _upload_and_sign(
    supabase: Client,
    settings: Settings,
    pdf_path: Path,
    object_key: str,
) -> dict[str, str]:
    """Upload a local PDF to Supabase Storage and return a signed URL."""
    data = pdf_path.read_bytes()
    supabase.storage.from_(settings.pdf_output_bucket).upload(
        path=object_key,
        file=data,
        file_options={
            "content-type": "application/pdf",
            "upsert": "true",
        },
    )
    signed = supabase.storage.from_(settings.pdf_output_bucket).create_signed_url(
        path=object_key,
        expires_in=settings.pdf_signed_url_ttl_seconds,
    )
    expires_at = datetime.now(timezone.utc).isoformat()
    url = signed.get("signedURL") or signed.get("signed_url")
    if not url:
        raise RuntimeError(f"No signed URL returned by Supabase: {signed!r}")
    return {"url": url, "expiresAt": expires_at}


# ---------------------------------------------------------------------------
# Proposal — matches target ProposalData from lib/pdf-api-client.ts
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    description: str | None = None
    quantity: float = 0
    unitPrice: float = 0


class ProposalData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    companyName: str
    companyLogoUrl: str | None = None
    companyPhone: str | None = None
    companyAddress: str | None = None
    companyEmail: str | None = None
    companyWebsite: str | None = None

    clientName: str | None = None
    clientEmail: str | None = None
    clientPhone: str | None = None
    clientAddress: str | None = None

    projectName: str
    projectAddress: str
    squareFootage: float = 0

    estimateName: str = "Estimate"
    estimateNumber: str | None = None
    materialsCost: float = 0
    laborCost: float = 0
    permitsFees: float = 0
    contingency: float = 0
    totalCost: float = 0
    notes: str = ""

    lineItems: list[LineItem] | None = None
    depositPercent: float | None = None
    discountAmount: float | None = None
    discountPercent: float | None = None
    taxRate: float | None = None

    estimateDate: str
    validUntil: str

    showTerms: bool = False
    customTerms: list[str] | None = None

    # Not used server-side (3D image). Accepted but ignored.
    roofImageDataUrl: str | None = None
    accentColor: dict | None = None


def _render_proposal_pdf(data: ProposalData, out: Path) -> None:
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle(
        "label",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.Color(100 / 255, 100 / 255, 100 / 255),
    )
    body_style = ParagraphStyle(
        "body",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.Color(55 / 255, 55 / 255, 55 / 255),
        leading=12,
    )
    heading_style = ParagraphStyle(
        "heading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.Color(28 / 255, 28 / 255, 28 / 255),
    )
    total_style = ParagraphStyle(
        "total",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.black,
        alignment=2,  # right
    )

    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Estimate — {data.projectName}",
    )
    flow: list = []

    flow.append(Paragraph(data.companyName, heading_style))
    contact_bits = [
        data.companyPhone,
        data.companyEmail,
        data.companyWebsite,
        data.companyAddress,
    ]
    contact = " · ".join(x for x in contact_bits if x)
    if contact:
        flow.append(Paragraph(contact, label_style))
    flow.append(Spacer(1, 6 * mm))

    title_row = [
        [
            Paragraph(f"<b>{data.estimateName}</b>", heading_style),
            Paragraph(
                f"# {data.estimateNumber or '—'}",
                ParagraphStyle(
                    "num", parent=body_style, fontSize=10, alignment=2
                ),
            ),
        ]
    ]
    flow.append(
        Table(title_row, colWidths=[doc.width * 0.6, doc.width * 0.4])
    )
    flow.append(Spacer(1, 4 * mm))

    proj_lines = [
        f"<b>{data.projectName}</b>",
        data.projectAddress,
    ]
    if data.squareFootage:
        proj_lines.append(f"{data.squareFootage:,.0f} sq ft")
    client_lines = [
        data.clientName or "",
        data.clientEmail or "",
        data.clientPhone or "",
        data.clientAddress or "",
    ]
    addr_table = [
        [Paragraph("PROJECT", label_style), Paragraph("CLIENT", label_style)],
        [
            Paragraph("<br/>".join(x for x in proj_lines if x), body_style),
            Paragraph("<br/>".join(x for x in client_lines if x), body_style),
        ],
    ]
    t = Table(addr_table, colWidths=[doc.width / 2, doc.width / 2])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ]
        )
    )
    flow.append(t)
    flow.append(Spacer(1, 6 * mm))

    # Line items table
    items: list[list] = [["Description", "Qty", "Unit", "Amount"]]
    if data.lineItems:
        for li in data.lineItems:
            desc = li.name + (f" — {li.description}" if li.description else "")
            amt = li.quantity * li.unitPrice
            items.append([desc, f"{li.quantity:g}", f"${li.unitPrice:,.2f}", f"${amt:,.2f}"])
    else:
        items.extend(
            [
                ["Materials", "1", f"${data.materialsCost:,.2f}", f"${data.materialsCost:,.2f}"],
                ["Labor", "1", f"${data.laborCost:,.2f}", f"${data.laborCost:,.2f}"],
                ["Permits & Fees", "1", f"${data.permitsFees:,.2f}", f"${data.permitsFees:,.2f}"],
                ["Contingency", "1", f"${data.contingency:,.2f}", f"${data.contingency:,.2f}"],
            ]
        )

    tbl = Table(items, colWidths=[doc.width * 0.55, doc.width * 0.1, doc.width * 0.15, doc.width * 0.2])
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(248 / 255, 248 / 255, 248 / 255)]),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(tbl)
    flow.append(Spacer(1, 6 * mm))

    subtotal = (
        data.materialsCost + data.laborCost + data.permitsFees + data.contingency
    )
    if data.lineItems:
        subtotal = sum((li.quantity * li.unitPrice) for li in data.lineItems)
    tax_rate = data.taxRate or 0
    tax = subtotal * tax_rate / 100
    total = data.totalCost or (subtotal + tax)

    totals = [
        [Paragraph("Subtotal", label_style), f"${subtotal:,.2f}"],
    ]
    if tax_rate:
        totals.append([Paragraph(f"Tax ({tax_rate:g}%)", label_style), f"${tax:,.2f}"])
    totals.append([Paragraph("<b>TOTAL</b>", total_style), Paragraph(f"<b>${total:,.2f}</b>", total_style)])

    tt = Table(totals, colWidths=[doc.width * 0.75, doc.width * 0.25])
    tt.setStyle(TableStyle([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    flow.append(tt)

    if data.notes:
        flow.append(Spacer(1, 6 * mm))
        flow.append(Paragraph("<b>Notes</b>", body_style))
        flow.append(Paragraph(data.notes.replace("\n", "<br/>"), body_style))

    flow.append(Spacer(1, 10 * mm))
    flow.append(
        Paragraph(
            f"Issued {data.estimateDate} · Valid until {data.validUntil}",
            label_style,
        )
    )

    if data.showTerms and data.customTerms:
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph("<b>Terms & Conditions</b>", heading_style))
        for term in data.customTerms:
            flow.append(Paragraph(term, body_style))

    doc.build(flow)


@router.post("/proposal", dependencies=[Depends(require_internal_key)])
async def generate_proposal(
    body: ProposalData,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Render the estimate PDF and return a signed Storage URL."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "proposal.pdf"
        _render_proposal_pdf(body, out)
        key = f"proposals/{uuid.uuid4()}.pdf"
        log.info("pdf.proposal: rendered %s -> %s", body.projectName, key)
        return _upload_and_sign(supabase, settings, out, key)


# ---------------------------------------------------------------------------
# Proposal Builder — rich sectioned layout
# ---------------------------------------------------------------------------


class ProposalBuilderPayload(BaseModel):
    """Permissive — UI forwards rich state; router consumes what it needs."""

    model_config = ConfigDict(extra="allow")

    proposalNumber: str
    projectName: str


def _hex_to_rgb(hex_s: str) -> tuple[float, float, float]:
    h = hex_s.lstrip("#")
    if len(h) != 6:
        return (0.96, 0.45, 0.09)  # fallback orange
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _render_proposal_builder_pdf(data: dict, out: Path) -> None:
    c = pdfcanvas.Canvas(str(out), pagesize=letter)
    pw, ph = letter
    ml, mr = 18 * mm, 18 * mm
    y = ph - 16 * mm

    accent_hex = str(data.get("accentColor") or "#f97316")
    ar, ag, ab = _hex_to_rgb(accent_hex)

    company = data.get("company") or {}
    client = data.get("client") or {}
    pm = data.get("projectMeta") or {}
    totals = data.get("totals") or {}

    # Accent bar top
    c.setFillColorRGB(ar, ag, ab)
    c.rect(0, ph - 4 * mm, pw, 4 * mm, fill=1, stroke=0)

    # Title
    c.setFillColorRGB(0.12, 0.12, 0.12)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(pw - mr, y, "PROPOSAL")
    y -= 6 * mm
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawRightString(pw - mr, y, f"#{data.get('proposalNumber', '—')}")
    y -= 4 * mm
    c.drawRightString(
        pw - mr,
        y,
        f"Valid for {data.get('validDays', 30)} days",
    )

    y = ph - 40 * mm

    # Company block
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(ar, ag, ab)
    c.drawString(ml, y, str(company.get("name") or data.get("projectName", "")))
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    for key in ("phone", "email", "address", "website"):
        val = company.get(key)
        if val:
            c.drawString(ml, y, str(val))
            y -= 3.5 * mm
    y -= 3 * mm
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.2)
    c.line(ml, y, pw - mr, y)
    y -= 6 * mm

    # Client
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(ml, y, "PREPARED FOR")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(0.12, 0.12, 0.12)
    c.drawString(ml, y, str(client.get("name") or "Property Owner"))
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    for key in ("address", "phone", "email"):
        val = client.get(key)
        if val:
            c.drawString(ml, y, str(val))
            y -= 4 * mm
    y -= 4 * mm

    # Project
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(ml, y, "PROJECT")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(0.12, 0.12, 0.12)
    c.drawString(ml, y, str(data.get("projectName", "")))
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    if pm.get("address"):
        c.drawString(ml, y, str(pm["address"]))
        y -= 4 * mm
    sqft = pm.get("squareFootage") or 0
    if sqft:
        c.setFillColorRGB(0.55, 0.55, 0.55)
        c.drawString(
            ml,
            y,
            f"{int(sqft):,} sq ft · {pm.get('planeCount', 0)} roof planes",
        )
        y -= 4 * mm
    y -= 6 * mm
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.line(ml, y, pw - mr, y)
    y -= 8 * mm

    # Line items
    line_items = data.get("lineItems") or []
    if line_items:
        c.setFillColorRGB(0.96, 0.96, 0.96)
        c.rect(ml, y - 2 * mm, pw - ml - mr, 7 * mm, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(ml + 2 * mm, y + 1, "ITEM")
        c.drawRightString(pw - mr - 50 * mm, y + 1, "QTY")
        c.drawRightString(pw - mr - 25 * mm, y + 1, "RATE")
        c.drawRightString(pw - mr, y + 1, "AMOUNT")
        y -= 9 * mm
        for item in line_items:
            qty = float(item.get("qty") or 0)
            up = float(item.get("unitPrice") or 0)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0.12, 0.12, 0.12)
            c.drawString(ml + 2 * mm, y, str(item.get("name") or "Item"))
            if item.get("description"):
                c.setFont("Helvetica", 7)
                c.setFillColorRGB(0.55, 0.55, 0.55)
                c.drawString(ml + 2 * mm, y - 3 * mm, str(item["description"]))
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.3, 0.3, 0.3)
            c.drawRightString(pw - mr - 50 * mm, y, f"{qty:g}")
            c.drawRightString(pw - mr - 25 * mm, y, f"${up:,.2f}")
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0.12, 0.12, 0.12)
            c.drawRightString(pw - mr, y, f"${qty * up:,.2f}")
            y -= 12 * mm
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(ml, y + 2 * mm, pw - mr, y + 2 * mm)
        y -= 4 * mm

    # Totals block
    subtotal = float(totals.get("subtotal") or 0)
    discount = float(totals.get("discount") or 0)
    discount_pct = float(totals.get("discountPercent") or 0)
    tax = float(totals.get("tax") or 0)
    tax_rate = float(totals.get("taxRate") or 0)
    total = float(totals.get("total") or 0)
    deposit = float(totals.get("deposit") or 0)
    deposit_pct = float(totals.get("depositPercent") or 0)

    right = pw - mr
    label_x = right - 55 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawRightString(label_x, y, "Subtotal")
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawRightString(right, y, f"${subtotal:,.2f}")
    y -= 5 * mm

    if discount > 0:
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawRightString(label_x, y, f"Discount ({discount_pct:g}%)")
        c.setFillColorRGB(0.13, 0.77, 0.37)
        c.drawRightString(right, y, f"-${discount:,.2f}")
        y -= 5 * mm
    if tax > 0:
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawRightString(label_x, y, f"Tax ({tax_rate:g}%)")
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawRightString(right, y, f"${tax:,.2f}")
        y -= 5 * mm

    y -= 2 * mm
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(label_x - 10 * mm, y, right, y)
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(0.12, 0.12, 0.12)
    c.drawRightString(label_x, y, "Total")
    c.drawRightString(right, y, f"${total:,.2f}")
    y -= 8 * mm

    if deposit:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawRightString(label_x, y, f"Deposit ({deposit_pct:g}%)")
        c.drawRightString(right, y, f"${deposit:,.2f}")
        y -= 4 * mm
        c.drawRightString(label_x, y, "Balance Due")
        c.drawRightString(right, y, f"${total - deposit:,.2f}")
        y -= 10 * mm

    notes = data.get("notesText") or ""
    if notes:
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.55, 0.55, 0.55)
        c.drawString(ml, y, "NOTES")
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        for line in str(notes).split("\n"):
            c.drawString(ml, y, line[:200])
            y -= 3.5 * mm

    # Footer
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawString(ml, 8 * mm, str(company.get("name") or ""))
    c.drawRightString(pw - mr, 8 * mm, f"Page 1")

    # Accent bar bottom
    c.setFillColorRGB(ar, ag, ab)
    c.rect(0, 0, pw, 3 * mm, fill=1, stroke=0)

    c.save()


@router.post("/proposal-builder", dependencies=[Depends(require_internal_key)])
async def generate_proposal_builder(
    body: ProposalBuilderPayload,
    request: Request,
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    """Render the richer section-driven proposal PDF and return a signed URL."""
    data = body.model_dump()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "proposal-builder.pdf"
        _render_proposal_builder_pdf(data, out)
        key = f"proposal-builder/{uuid.uuid4()}.pdf"
        log.info(
            "pdf.proposal-builder: rendered %s -> %s",
            data.get("projectName"),
            key,
        )
        return _upload_and_sign(supabase, settings, out, key)


# ---------------------------------------------------------------------------
# Cutsheets & shop drawings — wait on labeler→pipeline integration
# ---------------------------------------------------------------------------


@router.post("/cutsheets", dependencies=[Depends(require_internal_key)])
async def generate_cutsheets(request: Request):
    """Cut-sheets PDF.

    Requires the full pipeline output (polygons + planes + trimesh) —
    reached via the existing /api/pipeline/run_pipeline flow. The
    labeler's 'Generate PDF' button currently calls
    /api/pipeline/generate-pdf/{sample_id}; this endpoint is a placeholder
    for a future direct-from-geometry invocation.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Use /api/pipeline/generate-pdf/{sample_id} which runs the "
            "full pipeline and invokes write_cutsheets_pdf with real "
            "plane/mesh data."
        ),
    )


@router.post("/shop-drawings", dependencies=[Depends(require_internal_key)])
async def generate_shop_drawings_endpoint(request: Request):
    """Shop-drawings PDF.

    Same rationale as /cutsheets — needs roof_dict_from_pipeline inputs.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Requires pipeline output; wire through /api/pipeline/ once "
            "the labeler→pipeline integration is complete."
        ),
    )
