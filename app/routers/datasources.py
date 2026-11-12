from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DataSource
from ..schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate

router = APIRouter(prefix="/datasources", tags=["数据源"])


@router.post("", response_model=DataSourceOut, status_code=201)
def create_datasource(payload: DataSourceCreate, db: Session = Depends(get_db)):
    exists = db.query(DataSource).filter(DataSource.name == payload.name).first()
    if exists:
        raise HTTPException(400, detail="数据源名称已存在")
    obj = DataSource(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("", response_model=list[DataSourceOut])
def list_datasources(
    skip: int = 0,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    return db.query(DataSource).offset(skip).limit(limit).all()


@router.get("/{ds_id}", response_model=DataSourceOut)
def get_datasource(ds_id: int, db: Session = Depends(get_db)):
    obj = db.get(DataSource, ds_id)
    if not obj:
        raise HTTPException(404, detail="数据源不存在")
    return obj


@router.put("/{ds_id}", response_model=DataSourceOut)
def update_datasource(ds_id: int, payload: DataSourceUpdate, db: Session = Depends(get_db)):
    obj = db.get(DataSource, ds_id)
    if not obj:
        raise HTTPException(404, detail="数据源不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{ds_id}", status_code=204)
def delete_datasource(ds_id: int, db: Session = Depends(get_db)):
    obj = db.get(DataSource, ds_id)
    if not obj:
        raise HTTPException(404, detail="数据源不存在")
    db.delete(obj)
    db.commit()
