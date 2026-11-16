"""身份信息查询：给前端和排障用，看一眼当前 token 被认成了谁、什么角色。"""

from fastapi import APIRouter, Depends, Request

from ..core.security import auth_mode, authorize

router = APIRouter(prefix="/auth", tags=["身份"], dependencies=[Depends(authorize)])


@router.get("/whoami", summary="我是谁：当前身份与角色")
def whoami(request: Request):
    scheme = (
        "bearer"
        if request.headers.get("Authorization", "").lower().startswith("bearer ")
        else "apikey"
    )
    return {
        "actor": getattr(request.state, "actor", "-"),
        "role": getattr(request.state, "role", "-"),
        "mode": auth_mode(),
        "scheme": scheme,
    }
