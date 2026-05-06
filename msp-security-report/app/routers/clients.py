"""Client CRUD routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, selectinload

from app.dependencies import get_db, template_context, templates
from app.models import Assessment, Client
from app.routers.assessments import _delete_assessment_files


router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_class=HTMLResponse)
def list_clients(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    clients = db.query(Client).order_by(Client.name).all()
    ctx = template_context(request, db, clients=clients)
    return templates.TemplateResponse("clients/list.html", ctx)


@router.get("/new", response_class=HTMLResponse)
def new_client_form(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    ctx = template_context(request, db, client=None, errors=[])
    return templates.TemplateResponse("clients/create.html", ctx)


@router.post("/new")
def create_client(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    industry: Optional[str] = Form(None),
    primary_contact_name: Optional[str] = Form(None),
    primary_contact_email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    name_clean = (name or "").strip()
    if not name_clean:
        ctx = template_context(
            request,
            db,
            client=None,
            errors=["Client name is required."],
            form={
                "name": name,
                "industry": industry,
                "primary_contact_name": primary_contact_name,
                "primary_contact_email": primary_contact_email,
                "phone": phone,
                "address": address,
                "notes": notes,
            },
        )
        return templates.TemplateResponse(
            "clients/create.html", ctx, status_code=400
        )

    client = Client(
        name=name_clean,
        industry=(industry or "").strip() or None,
        primary_contact_name=(primary_contact_name or "").strip() or None,
        primary_contact_email=(primary_contact_email or "").strip() or None,
        phone=(phone or "").strip() or None,
        address=(address or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return RedirectResponse(url=f"/clients/{client.id}", status_code=303)


@router.get("/{client_id}", response_class=HTMLResponse)
def client_detail(
    client_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    # Eagerly load assessments and their reports so the page never relies on
    # lazy-load timing and always reflects the latest state of the database
    # (including reports generated moments before this request).
    client = (
        db.query(Client)
        .options(
            selectinload(Client.assessments).selectinload(Assessment.reports)
        )
        .filter(Client.id == client_id)
        .first()
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    ctx = template_context(request, db, client=client)
    return templates.TemplateResponse("clients/detail.html", ctx)


@router.get("/{client_id}/edit", response_class=HTMLResponse)
def edit_client_form(
    client_id: int, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    ctx = template_context(request, db, client=client, errors=[])
    return templates.TemplateResponse("clients/create.html", ctx)


@router.post("/{client_id}/edit")
def update_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    industry: Optional[str] = Form(None),
    primary_contact_name: Optional[str] = Form(None),
    primary_contact_email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    name_clean = (name or "").strip()
    if not name_clean:
        ctx = template_context(
            request,
            db,
            client=client,
            errors=["Client name is required."],
        )
        return templates.TemplateResponse(
            "clients/create.html", ctx, status_code=400
        )

    client.name = name_clean
    client.industry = (industry or "").strip() or None
    client.primary_contact_name = (primary_contact_name or "").strip() or None
    client.primary_contact_email = (primary_contact_email or "").strip() or None
    client.phone = (phone or "").strip() or None
    client.address = (address or "").strip() or None
    client.notes = (notes or "").strip() or None

    db.commit()
    return RedirectResponse(url=f"/clients/{client.id}", status_code=303)


@router.post("/{client_id}/delete")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # The DB cascade will drop assessments + answers + report rows, but the
    # files on disk would otherwise be orphaned. Clean them up best-effort
    # before the cascade runs.
    for assessment in list(client.assessments):
        _delete_assessment_files(assessment)

    db.delete(client)
    db.commit()
    return RedirectResponse(url="/clients", status_code=303)
