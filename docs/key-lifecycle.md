# 密钥生命周期

## 一、密钥长什么样

```text
dc_{role}_{key_id}_{secret}
dc_viewer_635e1940_800a9a2480f45ab65fbd8c19b1ff24fb0bc26f06c448a6f6
│  │      │        └ secret：48 位十六进制，192 bit 熵，明文只在签发时出现一次
│  │      └ key_id：8 位十六进制，明文可见，日志/审计/DB 都只认它
│  └ role：viewer / editor / admin，一眼看出权限级别
└ 前缀 dc：便于 GitHub/GitLab secret scanning 识别
```

存储的是 `HMAC-SHA256(secret, API_KEY_PEPPER)`，不是明文。校验用 `hmac.compare_digest`
恒时比较，避免计时攻击逐字节试探。

## 二、必配的环境变量

```bash
AUTH_MODE=apikey
API_KEY_PEPPER=<随机的 32 字节，例如 openssl rand -hex 32>
API_KEYS=admin:sk_admin_xxx        # 引导密钥（legacy），用于签发第一把托管密钥
```

```text
pepper 与数据库必须分开存放：拖库者拿到 DB 但没有 pepper，哈希依然不可用。
没配 pepper 时，数据库密钥整体停用（/keys 返回 500），legacy 环境变量密钥照常工作，
所以升级不会把已有部署打死。
```

## 三、三种签发方式

```bash
# ① HTTP（推荐，走审计）
curl -s -X POST http://127.0.0.1:8000/keys \
  -H "X-API-Key: $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"role":"editor","label":"CI Jenkins","days":90}'
# → {"key":"dc_editor_8a1c...","key_id":"8a1c9f2e","role":"editor","expires_at":"2027-02-15..."}

# ② CLI（离线排障，直接读库）
python -m app.core.keyring create --role admin --label "值班" --days 7
python -m app.core.keyring list
python -m app.core.keyring rotate 635e1940 --grace-hours 24
python -m app.core.keyring revoke 635e1940
```

```text
明文只返回一次，要立即存进密钥管理器（Vault / 1Password / CI 的 masked variable）。
列表接口永远不含明文，重看只能重新签发。
```

## 四、轮换为什么必须“新旧并存”

```bash
# 一次调用同时做两件事：签发新 key + 把旧 key 的 expires_at 设为 now+24h
curl -s -X POST http://127.0.0.1:8000/keys/635e1940/rotate \
  -H "X-API-Key: $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"grace_hours":24,"days":90}'
```

实测结果（宽限期内两把都可用）：

```text
旧 key → 200    新 key → 200
列表里旧 key expires_at = 次日同一时刻，status 仍为 active
```

```text
若直接删旧 key：调用方还在用旧 key 的瞬间会全量 401。
正确顺序：签发新 → 部署到调用方 → 观察旧 key 无流量 → 吊销旧 key。
宽限期就是给“部署窗口”留的时间。
```

## 五、吊销与生效窗口（要说清，而不是假装即时）

```bash
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" http://127.0.0.1:8000/keys/$KID/revoke
curl -s -H "X-API-Key: $REVOKED_KEY" http://127.0.0.1:8000/datasources
# → 401 {"error":{"code":"unauthorized","message":"密钥已吊销"}}
```

实测立刻 401：因为每次请求都要查库判定状态（我们没给密钥判定加缓存）。
代价是每个请求多一次主键查询；若后续加判定缓存，**吊销最坏延迟 = 缓存 TTL**，
必须在文档里写明天数，不能让运维以为“吊销即生效”。

## 六、三类密钥的建议有效期

| 用途 | 有效期 | 理由 |
| --- | --- | --- |
| 人用的排障 key | 1–7 天 | 用完即弃，泄露面最小 |
| 服务/CI key | 90 天 + 自动轮换 | 与 AWS/GitHub 的审计口径一致 |
| 引导 admin key | 90 天 | 只用于签发，平时不进业务路径 |

## 七、密钥泄露应急（按顺序执行）

```bash
# ① 立刻吊销（先止血，再排查）
curl -s -X POST -H "X-API-Key: $ADMIN_KEY" http://127.0.0.1:8000/keys/$LEAKED_ID/revoke

# ② 从审计里确认它被用在哪些路径、来自哪些 IP
curl -s -H "X-API-Key: $ADMIN_KEY" 'http://127.0.0.1:8000/audit?actor=viewer%3A635e1940&limit=50'

# ③ 换 pepper（会让所有托管密钥失效，等于全员重签，谨慎）
export API_KEY_PEPPER=$(openssl rand -hex 32)   # 重启服务后所有 dc_ key 立刻不可用

# ④ 复盘：这把 key 当初为什么会被拿到（贴聊天记录 / 写进代码 / 进了 CI 日志）
```

## 八、验收

```bash
python -m pytest -q        # 65 passed（密钥相关 11 项）
python -m ruff check .     # All checks passed
```
