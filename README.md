# Spree Store API 自动化测试框架

针对 **Spree Commerce v6 Store API** 的接口自动化框架：pytest + requests + SQLAlchemy + Allure + GitHub Actions。

覆盖登录鉴权、用户、商品、购物车、订单、支付回调六大模块，断言分三层：**HTTP 状态 → 业务码/关键字段 → 数据库状态**。

---

## 1. 前置条件

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.12+ | 跑测试 |
| Docker Desktop | 最新版 | 跑被测系统 Spree |
| Git | 任意 | 拉代码 |

---

## 2. 五步跑起来

```powershell
# 1) 装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) 配环境变量
Copy-Item .env.example .env
#   打开 .env，把 API_KEY 换成你的 pk_ 开头的 key（拿法见 docs/sut-setup.md）

# 3) 自检：接口通不通、数据库通不通
python scripts/check_env.py

# 3.5) 修正示例数据，让商品对 Store API 可见（幂等，可重复执行）
python scripts/prepare_sut.py

# 4) 跑冒烟
pytest -m smoke

# 5) 出报告
pytest --alluredir=allure-results
allure serve allure-results

# 6) 清理测试数据（跑完必做，否则订单/购物车会一直累积）
python scripts/cleanup_test_data.py --yes
```

被测系统（Spree）怎么起、`pk_` key 怎么拿、数据库端口怎么暴露，全部写在 **[docs/sut-setup.md](docs/sut-setup.md)**。

> **第一次用 Allure 要先装 CLI**（它和 `allure-pytest` 是两回事：前者生成报告，后者产出结果）：
>
> ```powershell
> # Windows PowerShell 默认禁止运行 .ps1，不改策略会报「禁止运行脚本」
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> npm install -g allure-commandline
> allure --version
> ```
>
> 不想改执行策略，就把命令写成 `allure.cmd serve allure-results`。

---

## 3. 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BASE_URL` | ✅ | Spree 地址，如 `http://localhost:3000` |
| `API_KEY` | ✅ | Store API 的 publishable key，`pk_` 开头 |
| `CUSTOMER_EMAIL` | ✅ | 登录用的顾客账号 |
| `CUSTOMER_PASSWORD` | ✅ | 密码 |
| `DB_DSN` | 建议 | `postgresql+psycopg://user:pass@host:5432/db`，不填则跳过数据库断言 |
| `RUN_ID` | 否 | 数据隔离前缀；不填自动生成，CI 里用 `github.run_id` |
| `TIMEOUT` / `RETRIES` | 否 | 请求超时与重试次数 |
| `ATTACH_ALL` | 否 | `1` 时每个请求都写进 Allure |

---

## 4. 常用命令

```powershell
pytest                          # 全量
pytest -m smoke                 # 冒烟集合
pytest -m "order or payment"    # 按模块
pytest -m negative              # 只跑异常路径
pytest -n 4                     # 四进程并行（数据按 RUN_ID 隔离）
pytest -x --lf                  # 失败即停 + 只跑上次失败的
```

报告：

```powershell
pytest --alluredir=allure-results
allure generate allure-results -o allure-report --clean
allure open allure-report
```

数据清理（**每次跑完都要执行**）：

```powershell
python scripts/cleanup_test_data.py          # 只看统计，不删
python scripts/cleanup_test_data.py --yes    # 删除本次运行产生的数据
python scripts/cleanup_test_data.py --all --yes   # 连历史遗留一起清空（重装环境时用）
```

清理依据是 `customer_note = qa:<RUN_ID>` 标记：用例建购物车时写入，订单会继承，
所以只删测试数据，不碰真实业务数据。清理后 `订单/购物车/支付/明细/地址` 全部归零。

---

## 5. 目录结构与职责

```
Spree-api-test-framework/
├─ framework/            # 框架层：被测系统无关，换系统只改这里
│  ├─ config.py          #   环境变量 → Settings（含 RUN_ID）
│  ├─ client.py          #   请求封装：鉴权头/超时/重试/耗时/报文留存
│  ├─ auth.py            #   Token：session 级缓存 + 过期自动刷新
│  ├─ db.py              #   数据库访问 + wait_until 轮询等待
│  ├─ data_factory.py    #   造数：唯一化 + 登记 + 逆序清理
│  ├─ assertions.py      #   三层断言
│  └─ reporting.py       #   请求/响应/curl 落 Allure
├─ tests/                # 用例层：只写业务语义
│  ├─ conftest.py        #   fixture 与钩子
│  └─ test_*.py          #   按模块拆分
├─ scripts/check_env.py  # 启动自检
├─ docs/                 # SUT 启动手册、用例设计
└─ .github/workflows/    # 定时执行 + 报告发布
```

**为什么这么分**：框架层负责「怎么发请求、怎么断言、怎么清理」，用例层负责「测什么」。这样换被测系统（比如从 Spree 换成自建服务）只需要改 `client.py` 的 base_url 和鉴权头，60 条用例一条都不用动。

---

## 6. 三个关键设计（面试会问）

**① Token 只登录一次**
`TokenManager` 在 session 级缓存 JWT，读 `exp` 判断是否临近过期，过期才走 refresh。避免 60 个用例登录 60 次被限流，也避免 token 过期变成「随机失败」。

**② 测试数据用 RUN_ID 隔离**
每次运行（每个 CI run、每个 xdist worker）生成唯一 `RUN_ID`，所有造出来的数据带 `qa_{RUN_ID}_` 前缀。`DataFactory` 谁创建谁登记，用例结束逆序删除；清理失败只打印不抛异常。这就是「连续两周跑不残留脏数据」的实现方式。

**③ 失败必须能复现**
每个请求都以三个附件挂进 Allure：请求报文、响应报文、可直接复制的 curl。断言失败时，报告里点开用例就能看到完整现场，不需要再去翻日志。

---

## 7. 持续集成

- 定时：每天 UTC 18:00（北京时间 02:00）跑**全量 60 条**
- push 到 main：只跑**冒烟 2 条**，快速反馈
- 手动：Actions → api-tests → Run workflow，可指定 marker
- 报告：artifact 保留 30 天，同时发布到 `gh-pages` 分支

**必须在仓库 Settings → Secrets 里配**：`BASE_URL`、`API_KEY`、`CUSTOMER_EMAIL`、`CUSTOMER_PASSWORD`、`DB_DSN`。

> ⚠️ GitHub 托管 Runner **访问不到你本机的 localhost**，所以本项目使用**自托管 Runner**（跑在部署 Spree 的那台机器上）。

### 7.1 自托管 Runner 的开机顺序（很容易踩）

定时任务失败最常见的两个原因，都不是用例问题：

| 现象 | 原因 | 处理 |
|---|---|---|
| `ConnectionRefused localhost:3000` | 重启后 Docker / Spree 没起 | 先起 Docker Desktop，再 `docker compose up -d` |
| `ConnectionRefused 127.0.0.1:7897` | Runner 配了代理，但代理没启动 | 代理可选：脚本里检测端口，没开就直连 |

开机自启脚本（放在启动文件夹）：

```
D:\actions-runner\start-stack.cmd    # Docker → Spree → 等 3000 端口 → Runner
D:\actions-runner\start-runner.cmd   # 只起 Runner（代理可选、Git Bash 优先）
```

> 为什么强调 Git Bash：Windows 的 `bash` 默认解析到 `C:\WINDOWS\system32\bash.exe`（WSL 启动器），
> 会让每个 `shell: bash` 步骤 1 秒内失败。脚本里把 `C:\Program Files\Git\bin` 放在 PATH 最前面。

---

## 8. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `401 invalid_token` | API_KEY 缺失/错误 | 确认 `.env` 里是 `pk_` 开头的 key |
| `Connection refused` | Spree 没起 | `docker compose ps` 看容器状态 |
| 登录失败 401 | 账号不存在 | 先注册顾客，见 docs/sut-setup.md 第 3 节 |
| DB `password authentication failed` | DSN 账号密码不对 | 看 Spree 项目的 `.env` 或 compose 文件 |
| 报告里没有请求报文 | 没加 `--alluredir` | 命令里带上 `--alluredir=allure-results` |
| `allure : 无法加载文件 ... 禁止运行脚本` | PowerShell 执行策略禁止 `.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，或改用 `allure.cmd` |
