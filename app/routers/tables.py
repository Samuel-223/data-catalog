from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ColumnMeta, DataSource, TableMeta
from ..schemas import (
    ColumnMetaCreate, ColumnMetaOut,
    TableMetaCreate, TableMetaOut, TableMetaUpdate,
)

router = APIRouter(prefix="/tables", tags=["数据表与字段"])


@router.post("", response_model=TableMetaOut, status_code=201)
def create_table(payload: TableMetaCreate, db: Session = Depends(get_db)):
    if not db.get(DataSource, payload.datasource_id):
        raise HTTPException(404, detail="关联的数据源不存在")
    obj = TableMeta(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("", response_model=list[TableMetaOut])
def list_tables(
    datasource_id: int | None = None,
    skip: int = 0,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(TableMeta)
    if datasource_id is not None:
        q = q.filter(TableMeta.datasource_id == datasource_id)
    return q.offset(skip).limit(limit).all()


@router.get("/{table_id}", response_model=TableMetaOut)
def get_table(table_id: int, db: Session = Depends(get_db)):
    obj = db.get(TableMeta, table_id)
    if not obj:
        raise HTTPException(404, detail="数据表不存在")
    return obj


@router.put("/{table_id}", response_model=TableMetaOut)
def update_table(table_id: int, payload: TableMetaUpdate, db: Session = Depends(get_db)):
    obj = db.get(TableMeta, table_id)
    if not obj:
        raise HTTPException(404, detail="数据表不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{table_id}", status_code=204)
def delete_table(table_id: int, db: Session = Depends(get_db)):
    obj = db.get(TableMeta, table_id)
    if not obj:
        raise HTTPException(404, detail="数据表不存在")
    db.delete(obj)
    db.commit()


@router.post("/{table_id}/columns", response_model=ColumnMetaOut, status_code=201)
def create_column(table_id: int, payload: ColumnMetaCreate, db: Session = Depends(get_db)):
    if not db.get(TableMeta, table_id):
        raise HTTPException(404, detail="数据表不存在")
    obj = ColumnMeta(table_id=table_id, **payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{table_id}/columns", response_model=list[ColumnMetaOut])
def list_columns(table_id: int, db: Session = Depends(get_db)):
    if not db.get(TableMeta, table_id):
        raise HTTPException(404, detail="数据表不存在")
    return db.query(ColumnMeta).filter(ColumnMeta.table_id == table_id).all()
