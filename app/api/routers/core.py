"""Auth, companies, employees, RPN import."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user, get_db, require
from app.api.schemas import CompanyIn, CompanyOut, EmployeeIn, EmployeeOut, Token
from app.core.security import Perm, create_token, mask_ppsn, verify_password
from app.db.base import utcnow
from app.db.models import Company, Employee, User
from app.services.audit import audit
from app.services.employees import create_employee, import_rpn_csv, update_employee

router = APIRouter()


@router.post("/auth/token", response_model=Token, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username, User.is_active.is_(True)))
    if not user or not verify_password(form.password, user.password_hash):
        audit(db, None, "LOGIN_FAILED", "user", None, None, {"email": form.username})
        raise HTTPException(401, "Incorrect email or password")
    user.last_login_at = utcnow()
    audit(db, user, "LOGIN", "user", user.user_id)
    return Token(access_token=create_token(user.email, user.role), role=user.role)


@router.get("/auth/me", tags=["auth"])
def me(user: User = Depends(current_user)):
    return {"email": user.email, "name": user.full_name, "role": user.role}


# ------------------------------------------------------------------ companies


@router.post("/companies", response_model=CompanyOut, tags=["companies"])
def create_company(body: CompanyIn, db: Session = Depends(get_db), user=Depends(require(Perm.COMPANY_WRITE))):
    co = Company(**body.model_dump())
    db.add(co)
    db.flush()
    audit(db, user, "COMPANY_CREATED", "company", co.company_id, None, body.model_dump())
    return co


@router.get("/companies/{company_id}", response_model=CompanyOut, tags=["companies"])
def get_company(company_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    co = db.get(Company, company_id)
    if not co:
        raise HTTPException(404, "Company not found")
    return co


# ------------------------------------------------------------------ employees


def _emp_out(e: Employee) -> EmployeeOut:
    return EmployeeOut(employee_id=e.employee_id, employee_number=e.employee_number, name=e.full_name,
                       ppsn_masked=mask_ppsn(e.ppsn), department=e.department.name if e.department else None,
                       job_title=e.job_title, pay_frequency=e.pay_frequency, salary_type=e.salary_type,
                       annual_salary=e.annual_salary, prsi_class=e.prsi_class, employment_status=e.employment_status,
                       has_rpn=bool(e.tax_profile and e.tax_profile.rpn_number))


@router.post("/employees", response_model=EmployeeOut, tags=["employees"])
def add_employee(body: EmployeeIn, db: Session = Depends(get_db), user=Depends(require(Perm.EMPLOYEE_WRITE))):
    try:
        e = create_employee(db, user, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.refresh(e)
    return _emp_out(e)


@router.get("/employees", response_model=list[EmployeeOut], tags=["employees"])
def list_employees(company_id: int | None = None, search: str | None = None, department: str | None = None,
                   limit: int = 500, offset: int = 0, db: Session = Depends(get_db),
                   user=Depends(require(Perm.EMPLOYEE_READ))):
    q = select(Employee).options(selectinload(Employee.department), selectinload(Employee.tax_profile))
    if company_id:
        q = q.where(Employee.company_id == company_id)
    if search:
        like = f"%{search.lower()}%"
        from sqlalchemy import func, or_
        q = q.where(or_(func.lower(Employee.first_name).like(like), func.lower(Employee.last_name).like(like),
                        func.lower(Employee.employee_number).like(like)))
    rows = [e for e in db.scalars(q.order_by(Employee.employee_number).limit(limit).offset(offset))]
    if department:
        rows = [e for e in rows if e.department and e.department.name == department]
    return [_emp_out(e) for e in rows]


@router.get("/employees/{employee_id}", tags=["employees"])
def get_employee(employee_id: int, db: Session = Depends(get_db), user=Depends(require(Perm.EMPLOYEE_READ))):
    e = db.scalar(select(Employee).where(Employee.employee_id == employee_id)
                  .options(selectinload(Employee.department), selectinload(Employee.tax_profile), selectinload(Employee.benefits)))
    if not e:
        raise HTTPException(404, "Employee not found")
    out = _emp_out(e).model_dump()
    tp = e.tax_profile
    out["tax_profile"] = None if tp is None else {
        "tax_basis": tp.tax_basis, "annual_tax_credits": tp.annual_tax_credits, "annual_srcop": tp.annual_srcop,
        "usc_status": tp.usc_status, "lpt_annual": tp.lpt_annual, "rpn_number": tp.rpn_number,
        "rpn_effective_date": tp.rpn_effective_date, "rpn_source": tp.rpn_source}
    out["benefits"] = [{"type": b.benefit_type, "description": b.description} for b in e.benefits]
    return out


@router.patch("/employees/{employee_id}", response_model=EmployeeOut, tags=["employees"])
def patch_employee(employee_id: int, changes: dict, reason: str | None = None, db: Session = Depends(get_db),
                   user=Depends(require(Perm.EMPLOYEE_WRITE))):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    allowed = set(EmployeeIn.model_fields) - {"company_id", "employee_number"}
    bad = set(changes) - allowed
    if bad:
        raise HTTPException(422, f"Fields not editable: {sorted(bad)}")
    try:
        update_employee(db, user, e, changes, reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.flush()
    db.refresh(e)
    return _emp_out(e)


# ------------------------------------------------------------------ RPN


@router.post("/rpn/import", tags=["rpn"])
async def rpn_import(company_id: int, tax_year: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                     user=Depends(require(Perm.TAX_PROFILE_WRITE))):
    content = (await file.read()).decode("utf-8-sig")
    try:
        return import_rpn_csv(db, user, company_id, content, tax_year)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
