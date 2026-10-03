# 问诊后端迁移 M1 交接记录

进度更新（2026-10-04）：T0～T12 的代码与自动化验证已完成，T9 已用两条真实脱敏样本完成回放。
对照发现一处新模型提问偏题和旧对话年龄表述不一致，详见文末 T9 记录；M2 的模型效果业务审阅、
M3/M4 的真机验收仍待完成，不能将工具执行成功视为这些验收已通过。

日期：2026-10-03。依据 avatarhuman 的《问诊后端迁移执行计划》与《四诊问诊后端迁移设计》。
本次范围是 T1～T8；M0 已由所有者确认。两个业务仓库均使用从 main 创建的
`feature/consultation-backend` 分支，只做本地提交。

## 完成行为

- Apkio 签发最长 300 秒的专用问诊票据；来源会话失效即拒绝，不能与病历票据混用。
- Ditan 按机构保存问诊、轮次、消息和模型调用记录，提供创建、快照、提交、查询、放弃和归档接口。
- 按 Coze 原顺序和女性分支执行 v1 问卷，16 份原始提示词随版本保存。
- 模型不可用时以固定问题继续问诊；报告失败可重试；报告只由显式 report 命令触发。
- 轮次任务与 HTTP 连接独立，通过数据库锁、version 和 attempt 保证并发受理与提交一致性。
- SSE 支持缓冲回放、心跳、reset 和 Unicode 码点 offset；其他 worker 可查询持久化结果。
- 原病历上传、重传规则及原上传票据回归测试保持不变。

## 任务记录

以下路径除 T1 外均相对 DitanBackend；每项“无”指该任务范围内没有遗留实现或待定业务规则。

### T1 Apkio 问诊票据

提交：`d8776bf`。

改动文件（相对 Apkio）：

- `services/control-plane/app/services/medical_upload.py`
- `services/control-plane/app/api/deps.py`
- `services/control-plane/app/api/v1/routes/client.py`
- `services/control-plane/tests/test_consultation_token.py`
- `docs/CONSULTATION_AUTH_CONTRACT.md`
- `CODEX.md`

验证：通过 `uv run python -` 先拦截 httpx 真实 HTTP transport，再执行
`pytest services/control-plane/tests -q -p no:cacheprovider --basetemp=.pytest-tmp-consultation`：
`66 passed`。`uv run ruff check --no-cache .` 通过；
`uv run mypy --cache-dir=nul services`：`Success: no issues found in 75 source files`。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T2 Ditan 问诊票据验证

提交：`b01b5c0`。

改动文件：

- `app/core/upload_auth.py`
- `app/core/consultation_auth.py`
- `app/core/exceptions.py`
- `app/api/deps.py`
- `tests/test_consultation_auth.py`

验证：`uv run pytest tests/test_consultation_auth.py tests/test_medical_upload.py tests/test_apkio_auth.py -q -p no:cacheprovider`：
`100 passed`。包括缺票、重复请求头、audience/scope 不匹配、过期与超时；原两份鉴权测试未修改。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T3 数据模型与迁移

提交：`b74f016`。

改动文件：

- `app/models/consultation.py`
- `app/models/__init__.py`
- `alembic/versions/005_consultation.py`
- `tests/test_consultation_models_postgres.py`
- `tests/test_org_postgres.py`（将测试 head 更新为 005）

验证：设置一次性 PostgreSQL 17 的 `DITAN_TEST_POSTGRES_URL`，运行
`uv run pytest tests/test_org_postgres.py tests/test_consultation_models_postgres.py -q -p no:cacheprovider`：
`22 passed`。覆盖迁移升降级、模型与数据库一致、活动问诊唯一性、processing 唯一性、跨机构复合外键。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T4 v1 流程、提示词和渲染

提交：`bb5037c`。

改动文件：

- `.gitattributes`
- `app/services/consultation/__init__.py`
- `app/services/consultation/workflows/__init__.py`
- `app/services/consultation/workflows/v1.py`
- `app/services/consultation/rendering.py`
- `app/services/consultation/prompts/v1/L03_core_history.txt`
- `app/services/consultation/prompts/v1/L04_family_health.txt`
- `app/services/consultation/prompts/v1/L05_work_stress.txt`
- `app/services/consultation/prompts/v1/L06_energy_mood.txt`
- `app/services/consultation/prompts/v1/L07_sleep_quality.txt`
- `app/services/consultation/prompts/v1/L08_diet_core.txt`
- `app/services/consultation/prompts/v1/L09_diet_extra.txt`
- `app/services/consultation/prompts/v1/L10_digestion.txt`
- `app/services/consultation/prompts/v1/L11_nocturia.txt`
- `app/services/consultation/prompts/v1/L12_exercise_habit.txt`
- `app/services/consultation/prompts/v1/L13_exercise_tolerance.txt`
- `app/services/consultation/prompts/v1/L14_report.txt`
- `app/services/consultation/prompts/v1/L15_children.txt`
- `app/services/consultation/prompts/v1/L16_menstruation.txt`
- `app/services/consultation/prompts/v1/L17_menstruation_detail.txt`
- `app/services/consultation/prompts/v1/L18_leukorrhea.txt`
- `tests/fixtures/coze_prompts_v1.txt`
- `tests/test_consultation_workflow.py`

验证：`uv run pytest tests/test_consultation_workflow.py -q -p no:cacheprovider`：`50 passed`。
原文仅规范化 USER_INPUT 的复制转义；L18 原有末尾空格保留，Git attributes 固定 LF。
L14 的两段 system 在原文中被 user 段隔开，测试校验逐行无丢失、无重复及各部分相对顺序。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T5 模型适配

提交：`06ca840`。

改动文件：

- `app/core/config.py`
- `app/services/consultation/llm.py`
- `app/services/consultation/llm_fake.py`
- `tests/test_consultation_llm.py`

验证：`uv run pytest tests/test_consultation_llm.py -q -p no:cacheprovider`：`12 passed`。
覆盖 SDK 参数不含 temperature、禁用 SDK 重试、问题首 token/全程时限、空输出、熔断、
报告首 token 前重试、并发上限和调用日志失败不影响结果。全部使用假实现或假 SDK。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T6 轮次服务与执行器

提交：`b775294`。

改动文件：

- `app/services/consultation/service.py`
- `app/services/consultation/runner.py`
- `main.py`
- `tests/consultation_helpers.py`
- `tests/test_consultation_service.py`

验证：`uv run pytest tests/test_consultation_service.py -q -p no:cacheprovider`：`5 passed`。
并发、接管与断流验收在 T8 补齐。
开场期间若尚可编辑的 inputs 被并发更新，旧资料生成结果不提交，该轮返回可重试的
`INPUTS_CHANGED`；原 turn_id 重试使用新资料。该技术处理保持 version=0 时可更新资料的规则。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T7 API 与 SSE

提交：`0489d18`。

改动文件：

- `app/api/consultation.py`
- `app/schemas/consultation.py`
- `app/api/router.py`
- `main.py`
- `docs/API.md`
- `tests/test_consultation_api.py`

验证：`uv run pytest tests/test_consultation_api.py -q -p no:cacheprovider`：初次 `6 passed`，
T8 增加冒烟脚本验证后纳入最终全量测试。涵盖 SSE、心跳、Unicode offset、JSON 受理错误、
所有子资源的跨机构 404、验证错误信封、归档与放弃。

与设计不一致或未完成：无。需要仓库所有者决定的问题：无。

### T8 M1 验收

新增文件：

- `app/repositories/consultation_repository.py`（按设计分层集中机构范围内的查询）
- `tests/test_consultation_recovery.py`
- `tests/test_consultation_postgres.py`
- `tests/test_consultation_runner.py`
- `scripts/consultation_smoke.py`
- `docs/CONSULTATION_M1_HANDOVER.md`

集成检查修订文件：

- `app/api/deps.py`（收窄可选 principal 类型）
- `app/api/router.py`（格式）
- `app/core/upload_auth.py`（格式）
- `app/models/__init__.py`（格式）
- `app/services/consultation/llm.py`（SDK / generator 类型、审计日志关联字段）
- `app/services/consultation/runner.py`（将取消清理纳入同一关闭时限、日志关联字段）
- `app/services/consultation/service.py`（使用查询仓储、受理日志与 lint）
- `app/services/consultation/workflows/v1.py`（步骤类型声明）
- `main.py`（格式）
- `tests/test_consultation_api.py`（用 ASGI 假服务运行冒烟脚本）
- `tests/test_consultation_service.py`（相同 kind、不同回答的 turn_id 冲突）
- `tests/test_consultation_workflow.py`（lint）

最终全量验证（一次性 PostgreSQL 17.7，真实 HTTP 被测试夹具拦截）：

```text
uv run pytest -q -p no:cacheprovider --basetemp=.consultation-pytest-tmp
310 passed, 8 warnings in 48.30s

uv run ruff check --no-cache .
All checks passed!

uv run mypy --cache-dir=nul .
Success: no issues found in 95 source files

uv run python scripts/consultation_smoke.py --help
exit code 0
```

Pytest 运行前设置 `DITAN_TEST_POSTGRES_URL`，指向本次临时容器内专用的
`ditan_org_upload_test` 数据库。310 项中包含 48 项真实 PostgreSQL 测试；没有跳过项。
8 条警告来自既有 Pydantic Config 和 Starlette 422 常量弃用提示。
冒烟脚本的完整执行由 `test_smoke_script_with_fake_provider` 覆盖，包含在上述 310 项中。

与设计不一致或未完成：无。需要仓库所有者决定的问题：按 M1 检查点审查后，再进入后续里程碑。

迭代中出现并已修正的验证失败，原始输出摘要：

```text
E   AssertionError: assert ('heartbeat' == 'reset'
E     - reset
E     + heartbeat)

tests\test_consultation_recovery.py:97: in test_circuit_breaker_keeps_collecting_answers
    assert all(
E   assert False
```

第一处改为只对协议事件断言顺序，心跳是注释；第二处将本来就不调用模型的 report_gate
排除在“模型失败降级”断言之外。修正后 SQLite 与 PostgreSQL 均通过。
集成静态检查曾报告可选 principal、异构步骤列表、SDK messages/参数和异步 generator 的类型问题，
已补齐类型声明；未通过忽略错误或修改原鉴权测试绕过检查。

## 19 项验收对应关系

`service` 指 `tests/test_consultation_service.py`，`recovery` 指 `tests/test_consultation_recovery.py`，
`postgres` 指 `tests/test_consultation_postgres.py`，`api` 指 `tests/test_consultation_api.py`。
postgres 会重新执行 service/recovery 的主要场景，并执行只适合 PostgreSQL 的竞态测试。

| 编号 | 要求 | 测试函数 |
| --- | --- | --- |
| 1 | 男性完整流程与归档 | service / postgres `test_male_complete_flow_and_archive` |
| 2 | 女 25、女 15、女 8、性别缺失 | recovery / postgres `test_female_and_missing_sex_flows`（4 组） |
| 3 | 相同 turn_id 不重复推进 | service / postgres `test_turn_identity_and_completed_replay`；postgres `test_concurrent_create_and_same_turn_are_idempotent` |
| 4 | 相同 turn_id 内容冲突 | service / postgres `test_turn_identity_and_completed_replay` |
| 5 | 不同 turn_id 并发只有一个成功 | postgres `test_concurrent_different_turns_have_one_winner` |
| 6 | 过期 base_version 附最新快照 | recovery / postgres `test_stale_version_returns_snapshot`；api `test_admission_errors_are_json_before_stream` |
| 7 | SSE 断开后任务继续 | recovery / postgres `test_real_sse_disconnect_does_not_cancel_turn` |
| 8 | 崩溃后超时接管 attempt=2 | postgres `test_crashed_attempt_is_taken_over_after_deadline`（首 token 前 / 中途两组） |
| 9 | 旧 attempt 晚到不能提交 | postgres `test_old_attempt_cannot_commit_after_takeover`（断言 version 仍为 0 时旧提交已被拒绝） |
| 10 | 新 turn_id 清理旧超时轮次 | postgres `test_new_turn_replaces_expired_processing_turn` |
| 11 | 首 token 前失败降级 | recovery / postgres `test_question_failure_falls_back_atomically[0]` |
| 12 | 中途失败先 reset 后固定问题 | recovery / postgres `test_question_failure_falls_back_atomically[1]` |
| 13 | 熔断期间不调用问题模型 | recovery / postgres `test_circuit_breaker_keeps_collecting_answers`（固定问题问完 11 问） |
| 14 | 报告前补充回答进入上下文 | service / postgres `test_gate_supplement_is_saved_and_used_in_report` |
| 15 | 连续报告仅保存一份 | recovery / postgres `test_report_cannot_be_generated_twice` |
| 16 | 报告失败后原 turn_id 重试 | recovery / postgres `test_report_failure_retries_same_turn` |
| 17 | 放弃后重建，进行中结果不能提交 | recovery / postgres `test_abandon_is_idempotent_and_allows_recreation`；postgres `test_abandon_fences_inflight_result` |
| 18 | 开场前可更新，之后资料固定 | service / postgres `test_inputs_update_only_before_start`；postgres `test_changed_inputs_during_start_require_retry` |
| 19 | 跨机构访问返回 404 | api `test_all_consultation_resources_are_org_scoped` |

附加覆盖：其他 worker 轮询完成结果、任务超时不留下半条消息、60 秒内关闭、缓冲到期清理、
模型审计、无温度参数、年龄边界、原始提示词逐字核对及病历上传原回归。

## 本地冒烟入口

`CONSULTATION_LLM_PROVIDER` 默认 `openai`，`CONSULTATION_LLM_CONCURRENCY` 默认 8。
启动本地服务做冒烟时显式设置 `CONSULTATION_LLM_PROVIDER=fake`，并取得有效的问诊票据：

```powershell
$env:CONSULTATION_SMOKE_TOKEN = '<本地问诊票据>'
uv run python scripts/consultation_smoke.py --base-url http://127.0.0.1:8000
```

脚本只接受 loopback 地址，演示首轮断流、查询恢复、重复提交、11 问、报告与归档；不输出票据。
自动化验收用 ASGITransport 和假验票服务运行同一脚本逻辑，不发真实 HTTP 请求。

## 检查点与后续边界

M1 初次交付后按执行计划停止供所有者审查。当时 T9 等待所有者提供脱敏样本，T10/T11 客户端与
T12 部署资料不在该阶段提交中；当时未访问生产数据库、调用真实模型、修改生产配置、推送、合并或部署。
后续授权、真实模型验证及 T9～T12 的完成情况记录于下文。
调用日志和已放弃问诊的保留期限仍是设计第 16 节列出的后续产品事项，本轮未自行设定清理期限。

本次只保留源码、测试、原提示词核对 fixture、API/鉴权协议和这份验收记录。
临时容器、测试数据库、测试产物与本次创建的开发环境在交付前清理；预先存在的共享镜像和 Apkio 环境保留。

## M1 审查修正与 T12（2026-10-03）

所有者已通过 M1 审查，并授权修正后并行执行 T10 / T11，不依赖 T9 的样本回放。

- 问题、报告使用独立信号量，每类采用 `CONSULTATION_LLM_CONCURRENCY` 的进程级上限。
  排队最多 10 秒，首 token 和生成时限在获得名额后开始；排队超时不累计熔断失败数。
  新增报告并发占满仍可提问、排队不消耗首 token 时限、排队超时不累计失败的测试。
- sex 有值时限定“男”“女”，MALE / FEMALE 大小写变体规范化为中文；其他值返回 422。
  原设计的缺省 / null 未知性别分支保留。新增 18 组 API 输入、规范化存储测试。
- 问诊兜底和任务异常改为 `logger.exception`，保留栈位置，隐藏异常消息、cause / context，
  避免把患者内容、提示词或底层异常中的请求内容写入普通日志。新增两处日志脱敏回归。
- T12 补齐问诊配置、nginx SSE 关闭缓冲与 240 秒读超时、发布顺序、uvicorn 60 秒关闭等待，
  并在 Compose app 服务设置 `stop_grace_period: 130s`。

验证结果：

```text
uv run pytest -q -p no:cacheprovider --basetemp=.consultation-review-tmp
333 passed, 8 warnings in 51.85s

uv run ruff check --no-cache .
All checks passed!

uv run mypy --cache-dir=nul .
Success: no issues found in 96 source files

docker compose config --quiet
exit code 0
stop_grace_period: 2m10s
consultation provider: openai
per-purpose concurrency: 8
```

全量测试使用本次一次性 PostgreSQL 数据库和假模型。Compose 仅做配置解析，没有启动或部署业务服务。

### 真实模型手工冒烟

所有者提供未跟踪的本地 `.env` 后，2026-10-03 进行两次有界请求；使用同一合成男性资料和
原 L03 提示词，无真实患者资料，不读写任何数据库。配置中的 `AI_OPENAI_BASE_URL` 仅在冒烟
进程内映射为后端变量 `AI_BASE_URL`，未打印或提交密钥。实际端点 `https://api.deepseek.com`，
模型 `deepseek-flash`。正式启动后端时仍需提供其要求的 `AI_BASE_URL`。

两次均通过实际 OpenAITransport 发出 system / user 两条消息，`stream=true`、
`stream_options={"include_usage":true}`、`max_tokens=150`、SDK `max_retries=0`，未设置 temperature。

| 项目 | 第一次：默认模式 | 第二次：仅提问关闭思考 |
| --- | --- | --- |
| UTC 时间 | 2026-10-03 10:00:40 | 2026-10-03 10:03:39 |
| 结果 | 无正文，被适配器判为空输出失败 | 成功 |
| 流式正文片段 | 0 | 22 |
| 正文字数 | 0 | 43 |
| 首正文耗时 | 无 | 812 ms |
| 调用总耗时 | 1983 ms | 1030 ms |
| prompt_tokens / completion_tokens | 653 / 150 | 628 / 22 |

[DeepSeek 官方思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)说明该模型默认开启
思考模式，OpenAI SDK 通过 `extra_body` 控制 thinking。第一次返回 usage 但没有正文；
所有者据此明确批准对提问增加 `extra_body={"thinking":{"type":"disabled"}}`，报告保留默认模式。
该参数变更已进入适配器并补充回归：问题发送 disabled，报告不发送 thinking 扩展。
未修改提示词，没有采集、记录或展示模型思考正文。

结论：实际端点接受两条消息与 stream_options，并能在当前 150 token 上限内流式返回问题正文和 usage。
这次仅验证接口兼容性，不代替真实业务对照或报告质量审阅。当时 T9 等待脱敏样本，现已完成文末记录的真实回放。
参数修正后再次运行同一全量命令：`333 passed, 8 warnings in 49.26s`；Ruff 通过，
Mypy 仍为 `Success: no issues found in 96 source files`。

## T10 / T11 并行接入状态（2026-10-03）

所有者授权两端不依赖 T9，先按假模型协议完成开发验证。两端均已保留默认 Coze 路径，并完成
问诊票据、持久化待发轮次、按快照恢复、SSE、显式 report、归档与身份/媒体代际隔离。

| 仓库 | 本地功能提交 | 验证 |
| --- | --- | --- |
| MCT_Android | `1fd90a8c79824fff0db36eed301ad9c13bf355cd` | Debug / Release 各 397 项测试通过；test + assembleDebug 通过；四项门禁和硬编码门禁自测通过 |
| MCT_Harmonyos | `db25950610ac46cc2a34912b476684a1aac8d10f`；播放队列修正 `71876257d84a7ffdae37dfab204f140f43dce27e` | Node 129 项通过；发布脚本 8 项通过；release HAP 构建及签名通过 |

Android 的逐项回归、接口一致性和真机清单见
[15 号文档的 T10 记录](../../MCT_Android/refect_document/15_重构执行总方案与回归清单.md)。
HarmonyOS 的逐文件说明、测试与临时签名工具来源见
[问诊后端接入验收](../../MCT_Harmonyos/docs/问诊后端接入验收.md)。

交叉审查覆盖了本地待发丢失后接续服务端 processing、TURN_ID_CONFLICT 不误采旧结果、
归档失败只重取 archive、退出同身份重登与普通业务会话续期的区别，以及旧流后续 delta
不能借媒体重连重新获得播放权限。协议 reset 仅续仍有效的原播放租约；旧 TTS 请求未返回
也不会阻塞新媒体的派发链。

本轮临时 PostgreSQL 容器/数据库、后端新增虚拟环境和测试目录、Android 专用构建产物、
HarmonyOS 本次新增测试/编译文件及临时 manifest 工具均已清理；保留本机已有环境与用户文件。
HarmonyOS 预存 `build-profile.json5` 修改未提交，最终 SHA-256 仍为
`4BB1BAAAF6977E759DCBDFE415178C3C1D5517ADC3453526CC99B9CC234CDA51`。

源码与部署资料均只在本地 `feature/consultation-backend` 分支提交，没有 push、合并或部署。
T9 现已完成文末记录的真实回放；M3 / M4 的真机、实际音视频硬件与完整病历上传验收尚未执行，按两端清单后续验收。

## 本轮逐文件改动清单

下列仅列本轮已提交文件，路径相对各自仓库；不包含本机 .env、用户原签名配置或临时产物。

### DitanBackend（审查修正、真实冒烟与 T12）

```text
Dockerfile
app/core/logging.py
app/schemas/consultation.py
app/services/consultation/llm.py
app/services/consultation/runner.py
docker-compose.yml
docs/API.md
docs/CONSULTATION_M1_HANDOVER.md
docs/DEPLOYMENT.md
main.py
tests/test_consultation_api.py
tests/test_consultation_error_logging.py
tests/test_consultation_llm.py
```

### MCT_Android（T10）

```text
app/build.gradle.kts
app/src/main/java/com/example/mct/app/page/digitalhuman/DigitalHumanPageAssembly.kt
app/src/main/java/com/example/mct/app/page/patient/PatientTypePage.kt
app/src/main/java/com/example/mct/app/router/AppNavGraph.kt
app/src/main/java/com/example/mct/core/data/ConsultationModels.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/ConsultationConversationSession.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/ConsultationDeltaAccumulator.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/ConsultationSpeechQueue.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/DigitalHumanProviders.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/DigitalHumanSessionStateMachine.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/DigitalHumanStateCoordinator.kt
app/src/main/java/com/example/mct/feature/digitalhuman/domain/DigitalHumanUseCases.kt
app/src/main/java/com/example/mct/feature/digitalhuman/presentation/DigitalHumanViewModel.kt
app/src/main/java/com/example/mct/feature/digitalhuman/ui/DigitalHumanScreen.kt
app/src/main/java/com/example/mct/feature/digitalhuman/ui/DigitalHumanScreenContent.kt
app/src/main/java/com/example/mct/feature/patient/domain/PatientCaseProviders.kt
app/src/main/java/com/example/mct/feature/patient/domain/PatientCaseUseCases.kt
app/src/main/java/com/example/mct/feature/patient/session/PatientConsultationDraft.kt
app/src/main/java/com/example/mct/feature/patient/session/PatientSessionMapper.kt
app/src/main/java/com/example/mct/feature/patient/session/PatientSessionModels.kt
app/src/main/java/com/example/mct/feature/patient/session/PatientSessionProviders.kt
app/src/main/java/com/example/mct/feature/patient/session/PatientSessionStore.kt
app/src/main/java/com/example/mct/feature/patient/session/ScopedPatientSessionStore.kt
app/src/main/java/com/example/mct/feature/patient/ui/PatientTypeScreen.kt
app/src/main/java/com/example/mct/platform/network/BysRelayApi.kt
app/src/main/java/com/example/mct/platform/network/BysRelaySessionService.kt
app/src/main/java/com/example/mct/platform/network/ConsultationGateway.kt
app/src/main/java/com/example/mct/platform/network/ConsultationSseParser.kt
app/src/main/java/com/example/mct/platform/network/KtorHttpClientFactory.kt
app/src/test/java/com/example/mct/unit/auth/OrganizationDraftTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationDraftTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationGatewayTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationRecoveryTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationSpeechQueueTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationStreamTest.kt
app/src/test/java/com/example/mct/unit/consultation/ConsultationViewModelTest.kt
app/src/test/java/com/example/mct/unit/network/BysAnalysisGatewayRelayTest.kt
app/src/test/java/com/example/mct/unit/network/BysRelaySessionServiceTest.kt
app/src/test/java/com/example/mct/unit/network/ClientAuthProtocolTest.kt
gradle/libs.versions.toml
refect_document/15_重构执行总方案与回归清单.md
scripts/hardcoding-baseline.json
```

### MCT_Harmonyos（T11）

```text
README.md
docs/问诊后端接入验收.md
entry/src/main/ets/app/AppController.ets
entry/src/main/ets/app/AppEntry.ets
entry/src/main/ets/pages/DigitalHumanPage.ets
entry/src/main/ets/platform/config/AppConfig.ets
entry/src/main/ets/platform/config/AppConfigModels.ets
entry/src/main/ets/platform/digitalhuman/ConsultationCoordinator.ets
entry/src/main/ets/platform/digitalhuman/ConsultationModels.ets
entry/src/main/ets/platform/digitalhuman/ConsultationService.ets
entry/src/main/ets/platform/digitalhuman/ConsultationSpeechQueue.ets
entry/src/main/ets/platform/digitalhuman/ConsultationSseParser.ets
entry/src/main/ets/platform/digitalhuman/DigitalHumanReportBuilder.ets
entry/src/main/ets/platform/digitalhuman/HarmonyDigitalHumanService.ets
entry/src/main/ets/platform/network/ApkioAuthSession.ets
entry/src/main/ets/platform/network/BusinessHttpPolicy.ets
entry/src/main/ets/platform/network/BysRelaySessionService.ets
entry/src/main/ets/platform/network/HttpClient.ets
entry/src/test/LocalUnit.test.ets
libs/common-domain/src/main/ets/model/PatientSession.ets
local.properties.example
scripts/generate-local-config.ps1
scripts/tests/consultation-regressions.cjs
scripts/tests/local-unit.test.cjs
scripts/tests/org-auth.test.cjs
```

## T9 真实样本脱敏导出与对照回放（2026-10-03～10-04）

### 数据授权与处理

所有者本轮明确授权通过 `ssh NewPlus` 从服务器 PostgreSQL 提取并脱敏，替代原执行计划中
“所有者提供样本、代理不访问生产数据库”的前提。本次生产操作仅为有超时限制的只读查询，
没有修改数据库、部署服务或在服务器保存原始导出文件。

`scripts/consultation_export.py` 通过 SSH 标准输入运行服务器端脱敏程序，在
`BEGIN TRANSACTION READ ONLY` 内查询，以 `ROLLBACK` 结束；查询超时 10 秒、锁等待 1 秒，
候选最多 500 条、单批导出最多 20 条，必须显式指定已授权的 SSH 别名。
数据库凭据只由服务器容器内部环境使用，不输出到终端或交接资料。

字段映射沿用 T9 设计：患者性别、生日来自 `patients`；身高、体重、Coze 对话来自
`pre_diagnosis_records`；四诊文本和旧报告来自 `sanzhen_analysis_results`；目标体重未知，保持
`null`。查询通过病历、患者和预诊记录的机构条件关联，不导出原病历、患者或机构标识。

姓名、电话以及自由文本中的已知身份信息、称呼、身份证号、邮箱、链接、UUID、长标识、
完整时间戳和带标签的地址等均在服务器内替换，再传回本机。使用合成的生日和就诊日期保留周岁；
年龄基准是病历 `created_at` 按 UTC 解释后转为北京时间的日期，原 Coze 开场时间没有保存，
因此无法消除原年龄计算方式或实际开场日期造成的偏差。保留原回答和语音识别误差，不补造回答。
文本规则不能证明彻底不可重识别，脱敏样本和对照报告仍按临床数据保管，只存本机；
`.gitignore` 与 `.dockerignore` 均排除 `.consultation-data/`，不会提交或打入应用镜像。

生产查询发现 42 条非空对话，其中 40 条有报告，39 条有至少 11 条 `User:` 消息。
可用样本覆盖成年女性 19 条、成年男性 21 条，没有儿童或青少年样本；本次选择四诊内容较完整、
回答数量匹配流程的成年女性和男性各一条。现场 `diagnosis_result` 已为 `TEXT`，最长已存报告
1259 字；原计划所述 1024 字现有限制已不适用，但无法判断更早上传失败造成的样本缺失。

### 工具与执行结果

`scripts/consultation_replay.py` 使用真实 v1 服务、提示词、模型适配器和临时 SQLite 逐轮回放，
不会连接业务数据库。按日志中最近的 `AI:` 关联原 `User:` 回答，忽略未配对介绍、摘要和
`Status:` 行；“获取报告”按钮作为报告控制命令处理。缺失回答时输出未完成结果，不强行补齐。
报告并排保留新旧提问、原回答、新旧报告；同时核对流程节点与新旧问题正文主题，标注可能的
顺序、分支、年龄、降级和报告格式差异。主题检查采用关键词规则，业务方仍须逐句审阅。

本次命令（在 DitanBackend 下执行；已有输出不会被覆盖）：

```powershell
uv run python scripts/consultation_export.py --ssh-host NewPlus --container ditan_db --count 2 --output .consultation-data/t9/samples-final.jsonl
uv run python scripts/consultation_replay.py --samples .consultation-data/t9/samples-final.jsonl --output-dir .consultation-data/t9/replay-real --provider openai --limit 2
```

真实回放从本机 `.env` 读取模型配置，兼容 `AI_OPENAI_BASE_URL` 到 `AI_BASE_URL` 的映射。
使用 `deepseek-flash`，提问关闭思考、报告保留默认模式，沿用已获同意的调整；没有修改 v1 提示词。
不在此记录密钥或患者正文。

| 样本 | 分支 | 原回答数 | 模型调用 | 问题降级 | 供应商 input / output tokens | 执行状态 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| S001 | 成年女性，33 岁 | 15 | 16 | 0 | 339196 / 6988 | 完成并生成报告 |
| S002 | 成年男性，30 岁 | 11 | 12 | 0 | 249892 / 7609 | 完成并生成报告 |

合计 28 次真实模型调用，供应商返回用量为 589088 input / 14597 output tokens。
样本文件 SHA-256：`9eeab17539274175fdbee9f2fa505783bd14fb9d3cf23e758ee8b331b9d74a3e`。

本机交付文件：

- `.consultation-data/t9/samples-final.jsonl`、`samples-final.summary.json`：脱敏样本与导出摘要。
- `.consultation-data/t9/replay-real/README.md`：报告索引与审阅重点。
- `.consultation-data/t9/replay-real/S001.md`、`S002.md`：逐轮提问和最终报告对照。
- `.consultation-data/t9/replay-real/summary.json`：执行结果、差异标记与用量。

### 发现与验收边界

1. S001 第 12 轮的流程节点是 `children`，但新模型正文问了月经；原回答针对生育问题，
   因而这处偏题可能影响后续报告的语义。流程节点顺序正确不能证明正文主题正确。
2. S001 的旧 Coze 问题先后提到 32 岁和 30 岁，按病历日期计算为 33 岁；原开场时间、
   旧年龄算法或模型表述可能存在差异，现有记录不足以归因。
3. S002 未检出主题或分支差异；这是规则检查结果，不代表报告医学内容已获业务认可。
   两条成年样本也不能代表儿童、青少年、未知年龄等全部分支的真实效果。

人工核对发现第 1 项后补充了新问题正文的主题检查及回归测试，并对同一次真实输出重新标注；
`summary.json` 标明 `analysis_version: 2`、`model_outputs_regenerated: false`。
重新标注保留原问题、原回答和报告正文，没有再次调用模型、筛选更好的输出或改写 v1 提示词。
T9 的“至少一条真实样本跑通并提供报告”已完成；M2 仍需业务方审阅这些差异，再决定是否通过
或另行发布 v2 提示词/增加模型输出约束。

### 验证与文件清单

新增 27 项自动化测试，覆盖脱敏、保龄日期、只读导出、错误不回显源数据、多行日志解析、
真实服务的假模型回放、回答不足、分支/主题差异、降级以及报告失败。测试不访问真实 HTTP 或 SSH。
全量 `pytest tests -q -p no:cacheprovider --basetemp=.consultation-t9-tests`：
`360 passed, 8 warnings`，其中 PostgreSQL 集成测试 48 项；`DITAN_TEST_POSTGRES_URL` 指向
本机 Docker 的临时 PostgreSQL 专用测试库，没有使用生产数据库。`ruff check --no-cache .` 通过；`mypy --cache-dir=nul .`：
`Success: no issues found in 100 source files`。

改动文件（均在 `feature/consultation-backend`）：

```text
.dockerignore
.gitignore
docs/CONSULTATION_M1_HANDOVER.md
scripts/consultation_export.py
scripts/consultation_replay.py
tests/test_consultation_export.py
tests/test_consultation_replay.py
```

收尾：已停止并自动移除本次本机 PostgreSQL 容器及其 tmpfs 数据，删除本次新建的 `.venv`、
`.consultation-t9-tests` 和两版已替代的导出草稿；回放临时 SQLite 已由工具删除。
本次没有构建临时镜像，保留原有共享 `postgres:17` 镜像、用户 `.env`、预存日志/缓存和最终脱敏交付物。
复查各仓库状态：avatarhuman、Apkio、Android 无新增改动，HarmonyOS 仅保留原有且哈希未变的
`build-profile.json5` 修改；DitanBackend 只提交上述七个文件，没有推送、合并或部署。
