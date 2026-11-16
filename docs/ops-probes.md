# 探针与 JWT 加固（0.5.0）

## 一、三个探针的边界

| 端点 | 是否鉴权 | 返回 | 用途 |
| --- | --- | --- | --- |
| `GET /health` | 公开 | `{"status":"ok"}` | 存活：只回答“进程还在不在”，不含版本/服务名 |
| `GET /ready` | 公开 | `{"status":"ready","db":"ok","audit":"ok"}` | 就绪：数据库 + 审计目录都通才算 ready |
| `GET /health/detail` | 仅 admin | 版本/认证模式/审计路径/可写性/JWKS | 排障：一次问清，不必逐个试接口 |

`/ready` 返回 503 的两种情形：

```json
{"status":"unavailable","db":"error","audit":"ok"}       // 数据库连不上
{"status":"unavailable","db":"ok","audit":"readonly"}     // 审计目录写不进去
```

第二种是 0.5.0 新增的判断。审计写失败时服务不阻断请求（只打 ERROR），所以
“服务能跑但审计全丢”曾是一种静默故障；把它变成不就绪，编排层才能发现。

```bash
# 验证降级：把审计路径指到一个不可写的位置
AUDIT_LOG_PATH=/proc/audit.jsonl ./start.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/ready   # 503
```

## 二、文档开关 DOCS_ENABLED

```bash
DOCS_ENABLED=1   # 默认，开发用：/docs、/openapi.json 可用
DOCS_ENABLED=0   # 生产用：两者都返回 404，接口结构不对外
```

关闭后 `/` 也只回四个字段，不报版本：

```json
{"status":"ok","service":"data-catalog","docs":null,"health":"/health","ready":"/ready"}
```

要版本号就走 admin 的 `/health/detail`：

```bash
curl -s -H "X-API-Key: $AKEY" http://127.0.0.1:8000/health/detail
```

## 三、JWT 验签缓存

同一 token 的并发请求不再重复做 RSA 验签：

```text
缓存键 = sha256(token | 配置指纹)
配置指纹 = OIDC_DEV_HS256_SECRET + OIDC_ISSUER + OIDC_AUDIENCE
有效期 = min(OIDC_TOKEN_CACHE_SECONDS=60, token.exp)
```

三条设计取舍：

1. **不缓过期 token**：有效期上界取 token 自己的 `exp`，不会出现“缓存比 token 活得久”。
2. **改配置即失效**：配置指纹进键，换密钥/换 issuer 后旧 token 不会因缓存继续通过。
3. **kid 未命中强制刷新**：身份源轮换密钥时，第一次遇到新 `kid` 就刷新 JWKS 再验，
   不必重启服务，也不因 5 分钟 TTL 把合法新 token 挡在门外。

```python
from app.core.oidc import token_cache_stats, clear_caches
token_cache_stats()   # {"hits": 12, "misses": 3, "evictions": 0, "size": 3}
clear_caches()        # 运维排查“为什么旧 token 还能过”时清一次
```

## 四、验收

```bash
python -m pytest -q      # 54 passed
python -m ruff check .   # All checks passed
```
