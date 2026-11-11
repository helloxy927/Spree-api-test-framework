# 项目复盘：Spree 接口自动化测试框架

> 记录时间：2026-11-11　|　代码量：framework 485 行 / tests 915 行　|　提交：27 个

---

## 1. 项目定位与成果

**一句话**：针对真实开源电商系统 Spree Commerce v6 的接口自动化框架，覆盖登录、用户、商品、购物车、订单、支付六个模块，三层断言，Allure 报告，GitHub Actions 自托管 Runner 每日定时执行，并保证测试数据零残留。

| 指标 | 数值 |
|---|---|
| 用例数 | **60**（正常 42 / 异常 18 = 7:3） |
| 代码量 | framework 485 行 + tests 915 行 |
| 三层断言 | 19 条用例带数据库校验（关键链路全覆盖） |
| 单次全量执行 | 约 35 秒（本地）/ 约 2 分钟（CI 含环境准备） |
| 数据清理 | 跑完 34 单/48 车/40 支付/80 明细/69 地址 → 全部归零 |
| 报告 | 本地 Allure + GitHub Pages 在线版 |
| 流水线 | push 跑冒烟（2 条）/ 每日 02:00 跑全量（60 条） |

在线报告：<https://helloxy927.github.io/Spree-api-test-framework/>

---

## 2. 验收项对照

| 验收项 | 状态 | 说明 |
|---|---|---|
| 用例 50+ | ✅ | 60 条 |
| 正常:异常 ≈ 7:3 | ✅ | 42:18 |
| 断言至少三层 | ✅（部分） | 19/60 带 DB 校验；关键链路（价格、库存、订单、支付）已覆盖 |
| 数据库校验 | ✅ | 价格精度、订单状态、支付状态、库存分配、清理结果 |
| Allure / HTML 报告 | ✅ | 每请求 3 个附件：请求 / 响应 / curl |
| GitHub Actions 自动执行 | ✅ | 自托管 Runner |
| 失败日志与环境留存 | ✅ | `environment.properties` + 附件 |
| 连续两周定时执行 | ⏳ | 进行中，第 0 天 |
| 任何人 clone 能跑 | ⚠️ | 未做换机验证；README 已补 SUT 侧配置 |

---

## 3. 问题台账

### 3.1 环境搭建（Windows + Docker + WSL）

| # | 现象 | 根因 | 修复 | 预防 |
|---|---|---|---|---|
| 1 | Docker 安装失败：Virtual Machine Platform 未启用 | 单用户安装无权限开启系统功能 | 管理员 PowerShell `dism /online /enable-feature /featurename:VirtualMachinePlatform` + 重启 | 装 Docker 前先查 `wsl --status` |
| 2 | Ubuntu 发行版是 WSL1（`VERSION 1`） | 旧发行版未转换 | `wsl --set-default-version 2` + `wsl --set-version Ubuntu-20.04 2` | 装完先验证 `wsl -l -v` |
| 3 | `wsl --update` 报 403 | 微软 CDN 被拦截 | `wsl --update --web-download` | 国内环境优先用 web-download |
| 4 | 拉 Docker 镜像极慢 | Docker Hub 直连 | 配 registry mirror | — |

### 3.2 被测系统（Spree）——最曲折的一段

**现象**：Store API `GET /products` 返回 `200`，但 `data: []`，数据库里明明有 38 个商品。

**排查方式**：读 Spree 6.0.3 源码（`ProductsController` → `StorefrontProducts` → `Product.available`），逐条核对可见性条件，而不是靠猜。

| 缺失条件 | 说明 | 修复 |
|---|---|---|
| `spree_products_stores` 关联 | 商品没挂到店铺 | 补 38 行关联 |
| `available_on` 为空 | 未上架时间 | 补 `now()` |
| `product_publications.published_at` 为空 | 未发布到渠道 | 补发布时间 |
| **店铺币种下没有基价** | CNY 价格全部挂在 price_list 上（B2B 定价），`with_currency` 只认 `price_list_id IS NULL` 的零售价 | 从 USD 基价复制出 88 条 CNY 基价 |

> 最后一条最隐蔽：接口返回 200、结构正确，只是数据被静默过滤。**只断言状态码永远发现不了。**

后续连带问题：

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 5 | 建地址报「国家不能为空」 | `spree_countries` 是空表 | 播种 CN + 省份 |
| 6 | 传 `country_id` 仍报国家为空 | v3 用 `country_iso`，不是 id | 改传 `country_iso: "CN"` |
| 7 | 地址挂不到购物车 | 需要先建地址，再把 `ship_address_id` 挂到 cart | 两步走 |
| 8 | 订单邮箱与预期不符 | 已登录下单时订单邮箱取**账号邮箱**，不是购物车临时邮箱 | 断言改为账号邮箱 |
| 9 | 库存没减少 | 下单只做**分配**（`allocated_count`），发货才减 `count_on_hand` | 断言改 `allocated_count` |
| 10 | 订单详情 404 | v3 按 prefixed id（`or_xxx`）查，传订单号无效 | 改用 id |
| 11 | 分页参数无效 | v3 是 `limit`，不是 `per_page` | 全局替换 |

这些全部固化进 `scripts/prepare_sut.py`（幂等），换机器跑一次即可。

### 3.3 限流：测试把自己打挂了

**现象**：本地跑全量时 4 条用例报 `429 rate_limit_exceeded`。

**根因**：Spree 默认 `POST /auth/login` 限流 **5 次/分钟/IP**、`POST /customers` **3 次/分钟/IP**。测试集中请求必然触发。

**修复**：
1. `TokenManager` 会话级缓存 JWT（60 个用例只登录一次）—— 这是设计上就该做的事
2. 测试环境通过 initializer 放宽限流（生产保持默认），并在 compose 里挂载

**收获**：限流不是「环境噪音」，而是被测系统真实行为；框架必须尊重它，否则测试结果不可信。

### 3.4 数据清理：订单删不掉

**现象**：跑几天后订单累积到 119 条，订单列表分页把新单挤到第 2 页，断言开始随机失败。

**难点**：订单有外键（支付、明细、履约单），不能直接 `DELETE`。

**方案**：
1. 建购物车时写入 `customer_note = qa:<RUN_ID>`，订单会**继承**这个字段
2. 清理时按 `qa:%` 前缀删除，先子表后主表
3. 地址用「不被任何订单/购物车引用的孤儿地址」规则删除
4. 提供 `--all` 模式清理历史遗留

**结果**：跑完 34 单 / 48 车 / 40 支付 / 80 明细 / 69 地址 → **全部归零**，并在 CI 里 `if: always()` 执行。

### 3.5 编码：一个 BOM 让 CI 1 秒失败

**现象**：CI 的「运行接口测试」步骤 1 秒就失败，连用例都没开始。

**根因**：用 PowerShell 的 `Set-Content -Encoding utf8` 写 `pytest.ini`，Windows PowerShell 5.1 会**写入 BOM**（`EF BB BF`），pytest 解析配置首行报 `unexpected line: '\ufeff#'`，exit code 4。

连带 `.env.example`（注释乱码）、`.gitattributes`（首条规则失效）也被同样手法写坏。

**修复**：全部重写为 UTF-8 无 BOM，并在 `pytest.ini` 里留了一行注释警告后人。

**教训**：写配置文件用编辑器/工具，不要用 shell 的重定向编码；跨平台项目应在 CI 加 BOM 检查。

### 3.6 CI / 流水线（踩坑最多）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 12 | 托管 Runner 全部失败 | 云端访问不到本机 `localhost:3000` | 改用**自托管 Runner** |
| 13 | `setup-python` 步骤失败 | 要从 GitHub 下载 Python 发行包，直连被墙 | 删掉，用机器自带的 Python 3.12 |
| 14 | 每个 bash 步骤 1 秒失败 | `bash` 解析到 `C:\WINDOWS\system32\bash.exe`（WSL 启动器） | 把 `C:\Program Files\Git\bin` 放到 PATH 最前 |
| 15 | pip/npm 安装超时 | 直连 PyPI / npm 官方源 | 配清华 PyPI + npmmirror |
| 16 | `npm install` 报 `EBUSY` | 本地开着的 Allure 报告服务**锁住了 jar** | 已安装则跳过 |
| 17 | 发布 gh-pages 报 403 | 缺 `contents: write` 权限 | 加 `permissions` |
| 18 | 定时任务全部 `ConnectionRefused` | 重启后 Docker / Spree 未启动 | `start-stack.cmd` 按序拉起 |
| 19 | Runner 连不上 `127.0.0.1:7897` | 代理未启动，脚本却写死了代理 | 检测端口，没有就直连 |
| 20 | 02:00 定时因机器睡眠而延迟 | 插电 5 分钟就睡眠 | `powercfg /change standby-timeout-ac 0` |
| 21 | Runner 偶发掉线 | 代理重启导致长连接断开 | 每 5 分钟守护任务，缺失则拉起 |
| 22 | 重启 Runner 报 `Error: Conflict` | 旧会话未在服务端过期 | 等待 1~2 分钟自动恢复；避免强杀 |

### 3.7 安全：一次误提交

**事件**：`git add -A` 把误生成在仓库内的 `my-store`（含 `.env`、396 个文件）提交了。

**处理**：`git reset --mixed HEAD~1` 回滚，`.gitignore` 加 `my-store/`，确认历史中无该目录、未推送。

**教训**：
1. 先 `git status` 再 `git add -A`
2. `.env` 必须在第一次提交前就进 `.gitignore`
3. 被墙的项目里，密钥（`sk_`）永远只放本地 `.env` 或 CI Secrets

---

## 4. 关键设计决策（面试重点）

| 决策 | 为什么 | 不这么做会怎样 |
|---|---|---|
| `framework/` 与 `tests/` 分层 | 换被测系统只改 client 层 | 换 SUT 要改 60 条用例 |
| Token 会话级缓存 + 过期刷新 | 避免 60 次登录触发限流 | 实测会 429 |
| `RUN_ID` 前缀 + 工厂登记 | 支持并行与重跑，数据可追溯 | 唯一索引冲突、数据互相污染 |
| 清理按 `qa:` 标记而非删表 | 只删自己造的数据 | 误删真实业务数据 |
| 三层断言 | 挡住「接口成功但没落库」 | 最贵的 bug 会漏过 |
| 每请求挂三个附件 | 失败能直接复现 | 只能看日志猜 |
| 自托管 Runner | 托管 Runner 够不到 localhost | CI 永远连不上 SUT |
| 定时全量 / push 冒烟 | 反馈速度与覆盖度分离 | 每次 push 等 2 分钟 |

---

## 5. 未完成事项

### P0（本周）
- [ ] **换目录 clone 验证**：模拟新人按 README 跑通
- [ ] 确认第一次定时全量（02:00）结果
- [ ] 补 `ADMIN_API_KEY` 到 GitHub Secrets（若 CI 要跑 `prepare_sut.py`）

### P1（下周）
- [ ] DB 断言从 19 条补到 25+（用户、购物车模块）
- [ ] 失败重试与分类：`pytest-rerunfailures` + `env` / `data` / `code` 标记
- [ ] 一次「故意失败」演练，截图失败报告

### P2（加分）
- [ ] 增量覆盖率（coverage + diff-cover）
- [ ] 从 Spree OpenAPI 规范生成用例骨架（呼应「接口文档解析」）
- [ ] Runner 装成 Windows 服务（当前是启动文件夹 + 守护任务）

---

## 6. 面试可用的故事（STAR）

1. **商品接口返回空列表**：现象 → 读源码定位四个可见性条件 → 补数据 → 固化为幂等脚本。
   *体现：系统化排查，而不是瞎试。*
2. **测试把自己打成 429**：发现限流 → token 缓存 + 测试环境放宽。
   *体现：理解被测系统约束，测试设计要尊重真实行为。*
3. **CI 1 秒失败**：BOM 编码问题 → 定位到 pytest 配置解析 → 全仓库排查同类文件。
   *体现：会看退出码和报错首行，不放过细节。*
4. **订单删不掉**：外键约束 → 用业务字段做标记 → 级联清理 → 实测归零。
   *体现：数据治理意识。*
5. **托管 Runner 够不到内网**：改自托管 → 又遇到 PATH/代理/睡眠/开机顺序一连串问题。
   *体现：环境工程能力，能把「跑通一次」变成「天天跑通」。*
6. **误提交 .env**：回滚 + 忽略规则 + 复盘。
   *体现：安全意识与工程规范。*
7. **三层断言发现数据没落库**：接口 200 但数据库状态不对。
   *体现：不迷信接口返回。*
8. **14 天稳定性**（待补）：失败分类、flaky 治理、趋势报告。

---

## 7. 可复用经验

1. 新系统先做「最小可通过请求」，再谈用例。
2. 接口返回空，先查数据可见性条件，别急着怀疑代码。
3. 任何「环境类失败」都要能一眼识别：报错发生在 fixture/连接层而非断言层。
4. 写配置文件别用 shell 重定向编码；跨平台项目警惕 BOM 与 CRLF。
5. CI 的环境变量、PATH、代理、工作目录，每一项都可能和本地不同。
6. 测试数据要么可删，要么可隔离；两者都没有，就别写会造数据的用例。
