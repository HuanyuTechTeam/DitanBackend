# Ditan 组织隔离与病例上传交接

日期：2026-09-22。分支：`feat/org-medical-upload`。

## 基线与提交

开始时工作区干净，fetch 后 `origin/main` 仍为 `2910561`；功能分支从该提交创建。

- `528a0ce`：独立上传验票、不可变身份及配置。
- `3b632de`：组织迁移、病例/诊断/聊天访问隔离、原子幂等上传和审计。
- 包含本文档的提交 `test(medical): cover upload isolation and PostgreSQL migrations`：新增回归、CI PostgreSQL 服务、运行配置及交接。完整提交可用 `git log origin/main..feat/org-medical-upload --oneline` 查看。

依据 Apkio `feat/org-device-auth` 分支的[开发任务](https://github.com/HuanyuTechTeam/Apkio/blob/distribution-provider-strategy/docs/DITAN_ORG_MEDICAL_UPLOAD_TASK.md)与[上传协议 v1](https://github.com/HuanyuTechTeam/Apkio/blob/distribution-provider-strategy/docs/MEDICAL_UPLOAD_AUTH_CONTRACT.md)。

## 已实现行为

- 保留 `POST /api/v1/medical-record`、原临床 DTO、APIResponse 和首次/重传的 201。
- 每次上传向固定 Apkio 地址在线验票；校验信封、active、audience、scope、四项身份与带时区到期时间。不解析未验签 JWT，不缓存授权，不创建 Doctor。
- 缺票/无效/过期 401；明确禁用 403；网络错误、5xx/429、重定向和畸形协议响应 503。原错误结构增加 code/requestId，不回显上游消息或凭证。
- 组织上下文在请求、service 和 repository 中显式传递。患者/病例/预诊按组织查询；诊断与三诊经父记录授权；会话和消息按组织授权。流式请求在开始响应前检查，保存继续使用原固定组织。
- 患者、病例、预诊、三诊一次事务写入。数据库复合唯一约束处理竞争；冲突 rollback 后重新查询，最多三轮。相同 UUID/规范化内容返回原记录；临床内容、图片、患者信息等变化返回 409，历史无摘要也返回 409。
- SHA-256 摘要覆盖 Pydantic 完整规范化 DTO；键序、显式 null 与等价缺省不影响结果。两个手机号必须一致，已有患者资料及诊断不会因上传重试而覆盖。
- 首次上传者 user/device/client-session/request ID 保存在病例上；每次尝试另记安全审计。requestId 由服务器生成，响应头为 X-Request-Id。日志无票据、病例/问诊全文或原手机号。
- 已检查 API 路由及直接 select：当前没有临床导出/跨组织管理路由；普通本地医生没有全组织访问能力。

## 配置

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| MEDICAL_UPLOAD_AUTH_REQUIRED | True | 上传必须验票；False 仅允许完全没有 Authorization 的旧上传进入 legacy |
| APKIO_BASE_URL | 空 | 服务端固定 API 根地址，路径为 /api，如 https://apkio.example.com/api；未配置时带票上传返回 503 |
| APKIO_ALLOW_LOOPBACK_HTTP | False | 仅开发显式允许 localhost、127.0.0.1 或 ::1 的 HTTP |
| 现有 APKIO_AUTH_ENABLED / APKIO_JWT_* 等 | 原值 | 仅用于原医生身份鉴权；独立上传验票不需要新签名密钥 |

追加路径为 `/client/medical-upload/current`。HTTPS 验证证书，禁用重定向与环境代理；连接超时 2 秒，整个网络阶段最多 5 秒。

httpx 已移入正式 dependencies；uv.lock 保留原镜像源和版本。Compose、开发 Compose、CI 生成配置已传递新增变量；未来部署需配置 APKIO_BASE_URL。生产配置保持 loopback HTTP 关闭。

## 迁移步骤

本次未连接生产数据库。上线时由负责部署的会话执行：

1. 备份数据库并检查 `uv run --frozen alembic current`。没有 Alembic 版本记录的旧库需先核实 schema，不得猜测 stamp，也不重建/清空数据库。
2. 停止旧版本写入，安装锁定依赖，配置验票地址及医生组织绑定。
3. 执行 `uv run --frozen alembic upgrade head`，确认 head 为 `003_org_medical_upload` 后启动新应用。
4. 检查组织 A/B、legacy 的访问及专用上传票据；旧客户端需要完成取票接入。

迁移链为 `000_initial_schema → 001_add_sanzhen_image_urls → 002_add_apkio_doctor_bindings → 003_org_medical_upload`。
000 固定历史建表结构，补齐空库升级入口；已经位于 001/002 的旧库不会重跑它。
003 从真实的 002 revision 接续，将患者/病例/预诊/聊天统一保留为非空 `__legacy__`，保留原 ID、诊断及消息关联。
三个原全局唯一约束/索引替换为组织复合唯一键；单列查询索引保留为非唯一。
父子组织一致有复合外键保障。新写入必须显式指定组织，迁移后的列不保留隐式 legacy 默认值。

应用启动只核对 Alembic 版本，不再 create_all；`scripts/init_db.py` 也改为 Alembic upgrade。
迁移需在线检查旧约束，不支持用离线 SQL 替代。
降级前锁表并检查重复手机号及两个 UUID；重复时整个降级明确拒绝，数据与版本不变。
即使无重复，降级会移除组织/上传审计字段，不能作为组织归属迁移方案。

## 兼容影响

- 匿名上传默认 401。临时启用兼容模式也只接纳完全没有 Authorization 的请求；空、损坏、过期、错误类型票据都不会回退匿名。
- 未绑定组织的本地医生只能访问 legacy。医生绑定到 Apkio 组织后只访问该组织，不能自动读取旧数据；历史归属需另行核实迁移。
- 聊天创建、详情、非流式、流式、关闭共五个入口全部要求现有医生身份。无 patient_id 的会话也有组织；历史匿名聊天只留给 legacy 医生。
- 上传 scope 不授予聊天、病例查询、诊断权限。依赖匿名聊天的外部调用方需升级为医生鉴权；仓库内旧匿名示例和测试已更新，未发现另一个实际匿名聊天客户端。
- Apkio、Android、HarmonyOS 未修改。客户端取票和真实联调由主会话继续。

## 验证结果

本机 Windows / Python 3.11.13：

- 全量 pytest：**173 passed**，包含原 61 项和新增 112 项。
- 新增：上传协议/幂等/审计 82 项，组织/legacy/诊断/聊天隔离 17 项，真实 PostgreSQL 17 迁移与并发 13 项。
- PostgreSQL 验证空库升级及完整降级再升级；含旧患者、三诊、AI/医生诊断、关联/匿名聊天与消息的迁移保留；旧唯一索引/约束/两者共存三种情况；各类重复下拒绝降级。
- PostgreSQL 6 路并发分别覆盖相同上传、同患者不同记录、同 UUID 内容冲突、同 UUID 患者冲突，均无孤儿/重复行。
- 真实 Alembic CLI upgrade/current、初始化脚本及启动 schema 检查通过。
- `uv run --frozen ruff check .` 通过；`uv run --frozen mypy .` 通过（69 个源文件）。
- 保留 8 条既有 Pydantic/FastAPI 弃用警告。CI 已加入 postgres:17 测试服务；PR 仅测试，构建发布和部署条件保持原有屏蔽。

全量复现需将 `DITAN_TEST_POSTGRES_URL` 指向专用临时 `ditan_org_upload_test` 数据库，再运行 `uv run --frozen pytest -q`。
未配置时 13 项 PostgreSQL 测试会明确 skip。夹具为每项测试创建随机 schema 并在结束时删除；拒绝其他数据库名。
测试 HTTP 出网被禁止，验票使用 httpx MockTransport，AI 使用 mock，全程使用合成数据。

## 真实联调与未验证项

**2026-09-22 统一复核补充：真实 Apkio → Ditan 联调已完成，两端真机仍待验证。**

在独立目录复跑 173 项测试（含 PostgreSQL 17 的 13 项迁移/并发）、Ruff、mypy 均通过。
使用 Apkio 682099a 的 scripts/verify_medical_upload_integration.py，两个真实后端进程与临时
PostgreSQL 数据库通过了 16 个 HTTP 检查点：成功/幂等/跨组织同号同 UUID、冲突、错误票据、
上传身份审计，以及 logout/replaced、解绑、设备/密钥/用户/组织/License 停用及会话到期后的拒绝。
每项撤销先证明同一张票据有效，拒绝后检查没有新增半条病例。仅使用合成数据和软件 EC 密钥。

Android、HarmonyOS 已由主会话接入专用取票/上传请求头，临床 DTO 保持原样。
两端通过各自 mock/构建验证，但尚未安装或做真实设备、硬件密钥、BLE 及四方上传联调。
统一分支和本地配置说明：
https://github.com/HuanyuTechTeam/Apkio/blob/distribution-provider-strategy/docs/ORG_AUTH_JOINT_DEBUG.md

补充联调的临时服务、容器、数据库与日志已清理；复用了本机既有 PostgreSQL 镜像，没有删除已有镜像。

后续真机复验：取票/上传成功；票据签发后 logout、业务会话 replaced/revoked、设备解绑、密钥吊销、组织/账号/License 停用后，下一次验票及上传失败（401 或 403）。已通过验票且执行中的事务按协议不追溯取消。

没有遗留协议实现疑问；以上联合状态变更和客户端队列行为需主会话复核。没有合并、部署、发布或手动触发 workflow。

## 本机清理

测试 schema 已逐项清理；任务专用 PostgreSQL 容器、tmpfs 数据库、此次新拉取的 postgres:17 镜像、生成的 __pycache__、测试日志和专用 mypy 缓存均已清理。
未删除已有 PostgreSQL/PostGIS 容器、原数据库卷或已有镜像，保留 .venv 依赖环境。
