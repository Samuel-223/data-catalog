from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ColumnMeta
from ..schemas import LineageCreate

router = APIRouter(prefix="/lineage", tags=["数据血缘"])

def _node(col: ColumnMeta, depth: int):
    return {
        "column_id": col.id,
        "column_name": col.column_name,
        "table_id": col.table_id,
        "depth": depth,
    }

@router.post("", status_code=201)
def link(payload: LineageCreate, db: Session = Depends(get_db)):
    col = db.get(ColumnMeta, payload.column_id)
    if not col:
        raise HTTPException(404, detail="下游字段不存在")
    up = db.get(ColumnMeta, payload.upstream_column_id)
    if not up:
        raise HTTPException(404, detail="上游字段不存在")
    if payload.column_id == payload.upstream_column_id:
        raise HTTPException(400, detail="不能指向自己")
    col.upstream_column_id = payload.upstream_column_id
    db.commit()
    db.refresh(col)
    return {"column_id": col.id, "upstream_column_id": col.upstream_column_id}

@router.get("/{column_id}/upstream")
def upstream(
    column_id: int,
    max_depth: int = Query(5, le=20),
    db: Session = Depends(get_db),
):
    col = db.get(ColumnMeta, column_id)
    if not col:
        raise HTTPException(404, detail="字段不存在")
    chain, depth, cur = [], 0, col
    while depth < max_depth:
        nxt_id = cur.upstream_column_id
        if not nxt_id:
            break
        nxt = db.get(ColumnMeta, nxt_id)
        if not nxt:
            break
        depth += 1
        chain.append(_node(nxt, depth))
        cur = nxt
    return {"column_id": column_id, "upstream": chain}

@router.get("/{column_id}/downstream")
def downstream(
    column_id: int,
    max_depth: int = Query(5, le=20),
    db: Session = Depends(get_db),
):
    if not db.get(ColumnMeta, column_id):
        raise HTTPException(404, detail="字段不存在")
    result, frontier, depth = [], [column_id], 0
    while frontier and depth < max_depth:
        depth += 1
        nxt = []
        for pid in frontier:
            children = db.query(ColumnMeta).filter(ColumnMeta.upstream_column_id == pid).all()
            for c in children:
                result.append(_node(c, depth))
                nxt.append(c.id)
        frontier = nxt
    return {"column_id": column_id, "downstream": result}
