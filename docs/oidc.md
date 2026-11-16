# 接入 OIDC 单点登录

## 一、先划清一条界线

本服务**不做登录**，只做验 token。

```text
浏览器/前端 → 身份源登录（Keycloak / Azure AD / 统一认证，含 MFA）
            → 拿到 access_token
            → 带 Authorization: Bearer <token> 调本服务
            → 本服务：验签 + 校验 iss/aud/exp + 角色映射 → 放行或 401/403
```

原因是：API 一旦自己做登录，就要存会话、管口令、扛钓鱼，等于重新造一个身份系统。
央企环境里身份源通常是现成的，接进来比自建安全得多。

## 二、配置

```bash
export AUTH_MODE=oidc                      # off | apikey | oidc | both
export OIDC_ISSUER=https://sso.corp.com/realms/data-catalog
export OIDC_AUDIENCE=data-catalog-api
export OIDC_JWKS_URI=                      # 留空走 .well-known 自动发现
export OIDC_ROLES_CLAIM=realm_access.roles # 支持 a.b.c 路径
export OIDC_ROLE_MAP=data-catalog-admin:admin,data-catalog-editor:editor,data-catalog-viewer:viewer
```

对应关系：

```text
身份源里的 data-catalog-admin  → 本服务 admin（可删）
身份源里的 data-catalog-editor → 本服务 editor（可写）
身份源里的 data-catalog-viewer → 本服务 viewer（只读）
用户若有多个角色，取权限最高的那个
```

`AUTH_MODE=both` 时 Bearer token 与 `X-API-Key` 都能用，适合切换期：老脚本用 key，
人用 SSO，跑稳两周再关掉 apikey。

## 三、Keycloak 落地命令

```bash
# 1) 装 kcadm（Keycloak 自带，在 /opt/keycloak/bin 下）
KCADM=/opt/keycloak/bin/kcadm.sh
$KCADM config credentials --server https://sso.corp.com --realm master \
  --user admin --password "$KC_ADMIN_PW"

# 2) 建 realm 与三个角色
$KCADM create realms -s realm=data-catalog -s enabled=true
for r in data-catalog-viewer data-catalog-editor data-catalog-admin; do
  $KCADM create roles -r data-catalog -s name=$r
done

# 3) 建 API 客户端（confidential，开 service account 才好取测试 token）
$KCADM create clients -r data-catalog \
  -s clientId=data-catalog-api -s enabled=true \
  -s protocol=openid-connect -s publicClient=false \
  -s serviceAccountsEnabled=true -s standardFlowEnabled=true \
  -s 'redirectUris=["https://catalog.corp.com/*"]'

# 4) 建用户并授角色
$KCADM create users -r data-catalog -s username=zhangsan \
  -s email=zhangsan@corp.com -s enabled=true
$KCADM add-roles -r data-catalog --uusername zhangsan --rolename data-catalog-editor

# 5) 取一个 token 验证映射
TOKEN=$(curl -s -X POST https://sso.corp.com/realms/data-catalog/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=data-catalog-api -d client_secret="$SECRET" | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/auth/whoami
```

Keycloak 默认把角色放在 `realm_access.roles`，正好是本服务的默认 `OIDC_ROLES_CLAIM`。
Azure AD 把角色放在 `roles`，改一下即可：

```bash
export OIDC_ROLES_CLAIM=roles
export OIDC_ROLE_MAP=Catalog.Admin:admin,Catalog.Editor:editor,Catalog.Viewer:viewer
```

## 四、本地自测（不连身份源）

用对称密钥伪造一个 token，只为验证验签以外的全部逻辑（含角色映射、过期、aud）：

```bash
export AUTH_MODE=oidc OIDC_ISSUER=http://localhost/realms/dev \
       OIDC_AUDIENCE=data-catalog-api OIDC_DEV_HS256_SECRET=dev-secret-at-least-32-bytes-long-0123

make token ROLE=admin      # 或 python scripts/dev_token.py viewer
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/auth/whoami
```

HS256 分支只在 `OIDC_DEV_HS256_SECRET` 存在时启用，生产用了它就等于把签发权交给了这个环境变量，
所以生产必须 RS256 + JWKS，`OIDC_DEV_HS256_SECRET` 留空。

## 五、实测结果

见 [`docs/demo/oidc_demo.txt`](demo/oidc_demo.txt)：

```text
admin token GET    → 200
admin token POST   → 201
viewer token POST  → 403 当前角色 viewer 无权执行 POST，需要 editor
过期 token         → 401 token 已过期
/auth/whoami       → {"actor":"dev@corp.com","role":"admin","mode":"oidc","scheme":"bearer"}
无 token           → 401
```

审计里 `actor` 记的是人的邮箱而不是密钥指纹，这是接 SSO 最直接的收益——
出事能追到人，追不到再回头加一层审批流。

## 六、401/403 对照表（排障用）

| 返回 | 含义 | 处理 |
|---|---|---|
| `token 已过期` | exp 过期 | 前端刷新 token |
| `token 不属于本服务` | aud 不匹配 | 检查 OIDC_AUDIENCE 与客户端 clientId 是否一致 |
| `token 签发方不匹配` | iss 不匹配 | 检查 OIDC_ISSUER（注意要不要带 `/realms/xxx`） |
| `签名校验失败` | 公钥不对 | 检查 JWKS 地址；密钥轮换期最多 5 分钟缓存 |
| `公钥获取失败` / `身份源发现失败` | 网络或身份源不可用 | 返回 503，不要改成本地放行 |
| `token 未包含本服务角色` | 角色没配或没映射 | 看 `OIDC_ROLE_MAP` 与 `whoami` 返回的原角色 |
| `不支持的签名算法` | alg=none 等攻击 | 保持拒绝 |

## 七、这层还差什么

1. 只支持 JWT，不支持不透明 token 的 introspection（有些身份源只发随机串）
2. 没有 token 缓存：高并发下每请求都验签，量大了要加本地缓存（按 token 哈希 + exp）
3. 没有登出联动：身份源吊销后，token 到期前仍可用（把 exp 控制在 15 分钟内可缓解）
4. 没有细到接口的权限（如「只能改自己建的规则」），现在是角色级
