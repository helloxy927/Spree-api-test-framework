# 被测系统（SUT）启动手册

> 目标：从零到「能用 curl 打出商品列表 + 能连上数据库」，预计 30~60 分钟（首次拉镜像较慢）。

---

## 1. 启动 Spree

```powershell
cd D:\devSoftwareData\pythonData

# 生成一个 Spree 项目（首次会拉 1~2GB 镜像，20~40 分钟）
npx create-spree-app@latest my-store

cd my-store
```

创建完成后，终端会打印启动方式（形如 `npm run dev` 或 `spree dev`），**以它打印的为准**。启动成功后：

- 后台：<http://localhost:3000/dashboard>
- Store API：`http://localhost:3000/api/v3/store/*`

验证：

```powershell
curl.exe -X GET "http://localhost:3000/api/v3/store/products" -H "X-Spree-Api-Key: pk_xxx"
```

---

## 2. 拿 publishable key

两种方式，任选：

```powershell
# 方式一：CLI
npx spree api-key create
```

方式二：后台 <http://localhost:3000/dashboard> → **Settings → API Keys** → 新建，复制 `pk_` 开头的值。

填到 `.env`：

```ini
API_KEY=pk_xxxxxxxx
```

> Store API 的规则：**所有请求都必须带** `X-Spree-Api-Key`，缺失返回 `401 invalid_token`。

---

## 3. 准备测试账号

框架的登录用例需要一个已存在的顾客账号，注册一次即可：

```powershell
curl.exe -X POST "http://localhost:3000/api/v3/store/customers" `
  -H "X-Spree-Api-Key: pk_xxx" `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"customer@example.com\",\"password\":\"password123\",\"password_confirmation\":\"password123\",\"first_name\":\"QA\",\"last_name\":\"Bot\"}'
```

然后确认能登录：

```powershell
curl.exe -X POST "http://localhost:3000/api/v3/store/auth/login" `
  -H "X-Spree-Api-Key: pk_xxx" `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"customer@example.com\",\"password\":\"password123\"}'
```

返回里有 `token` 就对了，把邮箱密码填进 `.env` 的 `CUSTOMER_EMAIL` / `CUSTOMER_PASSWORD`。

---

## 4. 数据库连接（三层断言必需）

Spree 的 Postgres 跑在容器里，默认**没有把 5432 暴露到宿主机**，需要手动加端口映射。

1. 打开 Spree 项目里的 `docker-compose.yml`（或 `compose.yaml`）
2. 找到 Postgres 服务（通常叫 `db` / `postgres`）
3. 在它下面加：

```yaml
    ports:
      - "5432:5432"
```

4. 重启：`docker compose up -d`
5. 从 Spree 项目的 `.env` 里抄出数据库名、用户名、密码（常见是 `spree` / `spree` / `spree_development`，**以实际为准**）

`.env` 里填：

```ini
DB_DSN=postgresql+psycopg://spree:spree@localhost:5432/spree_development
```

验证：

```powershell
python scripts/check_env.py
# [DB]   SELECT 1 -> 1
```

> 注意：容器里的 `localhost` 指容器自己，宿主机要用 `localhost:5432` 的前提是上面做了端口映射。

---

## 5. 让 CI 能访问 SUT（三选一）

GitHub 托管 Runner 在公网，**访问不到你电脑的 `localhost:3000`**。三种方案：

### 方案 A：自托管 Runner（推荐，满足「连续两周定时执行」）

1. 仓库 → Settings → Actions → Runners → New self-hosted runner → Windows
2. 按页面给的命令注册，`./run.cmd` 启动
3. 把 workflow 的 `runs-on: ubuntu-latest` 改成 `runs-on: self-hosted`
4. Secrets 里 `BASE_URL=http://localhost:3000`

优点：SUT 就在本机，无需公网暴露；缺点：电脑关机时定时任务会排队/失败。

### 方案 B：CI 里用 docker compose 拉起 SUT

把 Spree 项目放进本仓库（如 `sut/`），workflow 里先 `docker compose -f sut/docker-compose.yml up -d`，等健康检查通过再跑 pytest。

优点：完全自包含，任何人 clone + push 就能跑；缺点：每次冷启动慢（3~8 分钟），对免费额度消耗大。

### 方案 C：把 SUT 部署到公网

Spree 官方支持 Render / Railway / Fly.io（项目自带 `render.yaml`），部署后用公网地址做 `BASE_URL`，数据库用托管 Postgres。

优点：最接近真实生产；缺点：要花钱或用心免费额度，且数据清理要想清楚。

---

## 6. 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| `docker compose up` 卡在拉镜像 | 国内访问 Docker Hub 慢 | Docker Desktop → Settings → Docker Engine 配 `registry-mirrors` |
| 端口 3000 被占用 | 本机已有服务 | 改 Spree 的端口映射，同步改 `BASE_URL` |
| `spree api-key create` 找不到命令 | 没在项目目录、或 CLI 未安装 | 回到 `my-store` 目录；或直接用后台创建 |
| 数据库连不上 | 没做端口映射 / 密码不对 | 回到第 4 节；`docker compose exec db psql -U spree` 验证 |
| 登录 401 | 账号没注册 | 先执行第 3 节的注册请求 |

---

## 7. 测试环境必须做的两项 SUT 侧配置

这两项改动在 Spree 项目里（不在本仓库），换一台机器重搭环境时**必须重做**，否则会出现「接口全对但商品列表是空的」「测试被 429 打断」这类假失败。

### 7.1 让示例商品对 Store API 可见

`spree sample-data` 灌进去的数据默认不可见，缺四样东西：products↔stores 关联、`available_on`、`published_at`、店铺币种下的基价（示例数据的 CNY 价格全挂在 price_list 上）。

不用手工补，本仓库提供了幂等脚本：

```powershell
python scripts/prepare_sut.py
```

它会补齐上述四项、清一次 `solid_cache`、并确保测试顾客存在，最后打印 Store API 的商品数。**商品数必须 > 0**，否则 product 模块会失败。

### 7.2 放宽测试环境的限流

Spree 默认对 `POST /auth/login` 限流 **5 次/分钟/IP**、`POST /customers` **3 次/分钟/IP**。自动化测试集中打这两个接口，会把自己打成 `429 rate_limit_exceeded`，看起来像用例失败，其实是限流。

在 Spree 项目里加一个 initializer，并挂进 web 容器：

```powershell
# my-store/spree_extra/zz_test_rate_limits.rb
Spree::Api::Config[:rate_limit_login] = 1_000
Spree::Api::Config[:rate_limit_register] = 1_000
Spree::Api::Config[:rate_limit_refresh] = 1_000
Spree::Api::Config[:rate_limit_per_key] = 10_000
```

```yaml
# my-store/docker-compose.yml → services.web.volumes 追加
      - ./spree_extra/zz_test_rate_limits.rb:/rails/config/initializers/zz_test_rate_limits.rb:ro
```

改完重建一次容器：

```powershell
docker compose up -d web
```

> 生产环境不要这么配。测试环境放宽限流是常见做法，目的是让「失败」只代表真实缺陷。

### 7.3 顾客相关接口路径（v6）

| 能力 | 路径 |
|---|---|
| 当前用户资料 | `GET /api/v3/store/customers/me` |
| 我的订单 | `GET /api/v3/store/customers/me/orders` |
| 我的地址 | `GET /api/v3/store/customers/me/addresses` |
| 当前店铺 | `GET /api/v3/store/store` |

> 注意：`/account`、`/orders`、`/addresses` 这几个 v2 时代的路径在 v3 里是 404，别踩。

