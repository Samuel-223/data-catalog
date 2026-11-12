from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ColumnMeta, QualityResult, QualityRule, TableMeta
from ..schemas import QualityResultOut, QualityRuleCreate, QualityRuleOut, RunPayload

router = APIRouter(prefix="/rules", tags=["质量规则"])

VALID_TYPES = {"not_null", "unique", "range"}

def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

@router.post("", response_model=QualityRuleOut, status_code=201)
def create_rule(payload: QualityRuleCreate, db: Session = Depends(get_db)):
    if not db.get(TableMeta, payload.table_id):
        raise HTTPException(404, detail="关联的数据表不存在")
    if payload.column_id is not None and not db.get(ColumnMeta, payload.column_id):
        raise HTTPException(404, detail="关联的字段不存在")
    if payload.rule_type not in VALID_TYPES:
        raise HTTPException(400, detail="rule_type 只能是 not_null / unique / range")
    obj = QualityRule(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@router.get("", response_model=list[QualityRuleOut])
def list_rules(
    table_id: int | None = None,
    enabled: bool | None = None,
    skip: int = 0,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(QualityRule)
    if table_id is not None:
        q = q.filter(QualityRule.table_id == table_id)
    if enabled is not None:
        q = q.filter(QualityRule.enabled == enabled)
    return q.offset(skip).limit(limit).all()

@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    obj = db.get(QualityRule, rule_id)
    if not obj:
        raise HTTPException(404, detail="规则不存在")
    db.delete(obj)
    db.commit()

@router.post("/{rule_id}/run", response_model=QualityResultOut)
def run_rule(
    rule_id: int,
    payload: RunPayload | None = None,
    db: Session = Depends(get_db),
):
    rule = db.get(QualityRule, rule_id)
    if not rule:
        raise HTTPException(404, detail="规则不存在")
    if not rule.enabled:
        raise HTTPException(400, detail="规则已禁用")

    values = payload.values if (payload and payload.values) else []
    abnormal = 0
    detail = ""

    if rule.rule_type == "not_null":
        abnormal = sum(1 for v in values if v is None or str(v).strip() == "")
        detail = f"总数 {len(values)}，空值 {abnormal}"
    elif rule.rule_type == "unique":
        abnormal = len(values) - len(set(str(v) for v in values))
        detail = f"总数 {len(values)}，重复 {abnormal}"
    elif rule.rule_type == "range":
        upper = rule.threshold if rule.threshold is not None else float("inf")
        bad = [v for v in values if v is not None and (_to_float(v) is None or _to_float(v) > upper)]
        abnormal = len(bad)
        detail = f"总数 {len(values)}，超出上界 {upper} 的有 {abnormal}"

    result = QualityResult(
        rule_id=rule.id,
        passed=(abnormal == 0),
        abnormal_count=abnormal,
        detail=detail,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result

@router.get("/{rule_id}/results", response_model=list[QualityResultOut])
def list_results(
    rule_id: int,
    skip: int = 0,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    if not db.get(QualityRule, rule_id):
        raise HTTPException(404, detail="规则不存在")
    return (
        db.query(QualityResult)
        .filter(QualityResult.rule_id == rule_id)
        .order_by(QualityResult.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
