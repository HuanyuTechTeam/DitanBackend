# API 文档

本文档以当前代码实现为准，覆盖 `app/api/doctor.py`、`app/api/patient.py`、`app/api/chat.py` 中实际暴露的接口。

## 基础信息

- Base URL: `http://localhost:8000`
- API Prefix: `/api/v1`
- 默认运行时版本: `3.0.0`
- 在线文档:
  - Swagger UI: `/docs`
  - ReDoc: `/redoc`

## 认证

受保护接口接受 Bearer token。默认 token 来自本地医生登录；开启 `APKIO_AUTH_ENABLED=True` 后，也接受 Apkio `/api/auth/login` 返回的 Org 用户 `accessToken`。

```http
Authorization: Bearer <access_token>
```

Apkio token 必须满足：

- `aud` 为 `APKIO_ORG_TOKEN_AUDIENCE`，默认 `org`
- 包含 `sub`、`orgId`、`email`
- `permissions` 包含 `APKIO_REQUIRED_PERMISSION`，默认 `ditan.access`
- `sub + orgId` 已绑定到本地 `Doctor`；如果 `APKIO_AUTO_CREATE_DOCTOR=True`，首次访问会自动创建本地 `Doctor`

当前需要医生 JWT 的接口：

- `/api/v1/chat/*`

- `/api/v1/doctor/me`
- `/api/v1/doctor/change-password`
- `/api/v1/patient/query`
- `/api/v1/medical-record/{record_id}`
- `/api/v1/medical-record/{record_id}/ai-diagnosis`
- `/api/v1/medical-record/{record_id}/ai-diagnosis/stream`
- `/api/v1/medical-record/{record_id}/doctor-diagnosis`
- `/api/v1/doctor-diagnosis/{diagnosis_id}`
- `/api/v1/medical-record/{record_id}/confirm`

当前无需 JWT 的接口：

- `/health`
- `/`
- `/api/v1/doctor/register`
- `/api/v1/doctor/login`
上传 `POST /api/v1/medical-record` 默认需要独立 `medicalUploadToken`。Ditan 每次在线验票后采用服务端返回的组织和上传者身份，票据不能用于医生、查询、诊断或聊天。

医生访问按 `Doctor.apkio_org_id` 隔离；未绑定组织的本地医生仅访问 `__legacy__`。跨组织资源与不存在资源均返回 404。

## 响应约定

### 业务成功 / 业务异常

大部分业务接口返回统一结构：

```json
{
  "success": true,
  "message": "操作成功",
  "data": {}
}
```

自定义业务异常也会返回同结构：

```json
{
  "success": false,
  "message": "资源未找到",
  "detail": null
}
```

### 认证异常

医生认证由 FastAPI `HTTPException` 直接返回，结构为：

```json
{
  "detail": "未提供认证凭证"
}
```

常见 `detail` 值：

- `未提供认证凭证`
- `无效的认证凭证`
- `医生账户不存在`
- `缺少 Ditan 访问权限`
- `Apkio 账号未绑定医生身份`
- `用户名/手机号或密码错误`

上传错误保留 `success/message/detail` 并附加 `code/requestId`；响应头 `X-Request-Id` 由服务器生成。兼容模式仅完全没有 Authorization 的请求可写 legacy，空凭证或无效凭证仍然失败。

## 路由总览

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/health` | 否 | 健康检查 |
| `GET` | `/` | 否 | 根路径 |
| `POST` | `/api/v1/doctor/register` | 否 | 医生注册 |
| `POST` | `/api/v1/doctor/login` | 否 | 医生登录 |
| `GET` | `/api/v1/doctor/me` | 是 | 获取当前医生信息 |
| `PUT` | `/api/v1/doctor/me` | 是 | 更新当前医生信息 |
| `POST` | `/api/v1/doctor/change-password` | 是 | 修改密码 |
| `GET` | `/api/v1/patient/query?phone=...` | 是 | 按手机号查询患者 |
| `POST` | `/api/v1/medical-record` | 上传票据 | 创建就诊记录 |
| `GET` | `/api/v1/medical-record/{record_id}` | 是 | 获取完整就诊记录 |
| `POST` | `/api/v1/medical-record/{record_id}/ai-diagnosis` | 是 | 同步 AI 诊断 |
| `POST` | `/api/v1/medical-record/{record_id}/ai-diagnosis/stream` | 是 | 流式 AI 诊断 |
| `POST` | `/api/v1/medical-record/{record_id}/doctor-diagnosis` | 是 | 创建医生诊断 |
| `PUT` | `/api/v1/doctor-diagnosis/{diagnosis_id}` | 是 | 更新医生诊断 |
| `GET` | `/api/v1/doctor-diagnosis/{diagnosis_id}` | 是 | 获取医生诊断详情 |
| `POST` | `/api/v1/medical-record/{record_id}/confirm` | 是 | 确认就诊完成 |
| `POST` | `/api/v1/chat/conversation` | 医生 JWT | 创建聊天会话 |
| `GET` | `/api/v1/chat/conversation/{session_id}` | 医生 JWT | 获取会话详情 |
| `POST` | `/api/v1/chat/chat` | 医生 JWT | 非流式聊天 |
| `POST` | `/api/v1/chat/chat/stream` | 医生 JWT | 流式聊天 |
| `DELETE` | `/api/v1/chat/conversation/{session_id}` | 医生 JWT | 关闭会话 |

## 系统接口

### `GET /health`

```json
{
  "status": "healthy",
  "service": "DitanBackend",
  "version": "3.0.0"
}
```

### `GET /`

```json
{
  "message": "欢迎使用 DitanBackend",
  "version": "3.0.0",
  "docs": "/docs"
}
```

## 医生接口

### `POST /api/v1/doctor/register`

请求体：

```json
{
  "username": "doctor_zhang",
  "password": "password123",
  "name": "张医生",
  "gender": "MALE",
  "phone": "13800138000",
  "department": "中医科",
  "position": "主治医师",
  "bio": "擅长脾胃病调理"
}
```

约束：

- `username`: 3 到 50 位，只允许字母、数字、下划线
- `password`: 至少 6 位
- `phone`: 中国大陆 11 位手机号

### `POST /api/v1/doctor/login`

请求体：

```json
{
  "username": "doctor_zhang",
  "password": "password123"
}
```

`username` 字段也可以直接传手机号。

成功响应中的 `data`：

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "doctor": {
    "doctor_id": 1,
    "username": "doctor_zhang",
    "name": "张医生",
    "gender": "MALE",
    "phone": "13800138000",
    "department": "中医科",
    "position": "主治医师",
    "bio": "擅长脾胃病调理",
    "created_at": "2026-04-02T08:00:00",
    "updated_at": "2026-04-02T08:00:00",
    "last_login": "2026-04-02T08:05:00"
  }
}
```

### `GET /api/v1/doctor/me`

返回当前登录医生信息，结构与登录响应中的 `doctor` 一致。

### `PUT /api/v1/doctor/me`

请求体字段均可选：

```json
{
  "name": "张伟",
  "gender": "MALE",
  "phone": "13800138009",
  "department": "中医科",
  "position": "副主任医师",
  "bio": "擅长体质辨识和康复调理"
}
```

说明：

- 不能修改 `username`
- 如果更换手机号，会检查是否与其他医生冲突

### `POST /api/v1/doctor/change-password`

```json
{
  "old_password": "password123",
  "new_password": "new_password456"
}
```

## 患者与就诊接口

### `GET /api/v1/patient/query?phone=13800138001`

成功时 `data` 结构：

```json
{
  "patient": {
    "patient_id": 1,
    "name": "张三",
    "sex": "MALE",
    "birthday": "1985-05-20",
    "phone": "13800138001"
  },
  "medical_records": [
    {
      "record_id": 1,
      "uuid": "550e8400-e29b-41d4-a716-446655440001",
      "status": "pending",
      "created_at": "2026-04-02T08:10:00",
      "patient_name": "张三",
      "patient_phone": "13800138001"
    }
  ]
}
```

### `POST /api/v1/medical-record`

该接口由预问诊系统携带 `Authorization: Bearer <medicalUploadToken>` 调用。缺票/无效/过期为 401，身份禁用为 403，验票不可达或响应不符合协议为 503。

相同组织、病例 UUID 和规范化内容的重传仍返回 201 和原 ID；内容冲突或历史记录缺少内容摘要时返回 409。`patient_phone` 与 `patient_info.phone` 必须一致。组织、上传者、设备、来源会话均来自在线验票，body/query/header 自报身份不参与授权。

请求体：

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440001",
  "patient_phone": "13800138001",
  "patient_info": {
    "name": "张三",
    "sex": "MALE",
    "birthday": "1985-05-20",
    "phone": "13800138001"
  },
  "pre_diagnosis": {
    "uuid": "660e8400-e29b-41d4-a716-446655440001",
    "height": 175.0,
    "weight": 70.0,
    "coze_conversation_log": "患者自述近期乏力、腹胀",
    "sanzhen_analysis": {
      "face": "面色偏黄",
      "face_image_url": "https://example.com/face.jpg",
      "tongue_front": "舌苔薄白",
      "tongue_front_image_url": "https://example.com/tongue-front.jpg",
      "tongue_bottom": "舌下络脉轻度迂曲",
      "tongue_bottom_image_url": "https://example.com/tongue-bottom.jpg",
      "pulse": "脉沉细",
      "diagnosis_result": "脾虚湿困倾向"
    }
  }
}
```

说明：

- 首次就诊且患者不存在时，必须提供 `patient_info`
- `patient_info.phone` 应与 `patient_phone` 保持一致
- `uuid` 和 `pre_diagnosis.uuid` 都必须是合法 UUID

成功响应中的 `data` 为 `MedicalRecordResponse`：

```json
{
  "record_id": 1,
  "patient_id": 1,
  "uuid": "550e8400-e29b-41d4-a716-446655440001",
  "status": "pending",
  "created_at": "2026-04-02T08:10:00",
  "updated_at": "2026-04-02T08:10:00",
  "patient": {
    "patient_id": 1,
    "name": "张三",
    "sex": "MALE",
    "birthday": "1985-05-20",
    "phone": "13800138001"
  },
  "pre_diagnosis": {
    "pre_diagnosis_id": 1,
    "record_id": 1,
    "uuid": "660e8400-e29b-41d4-a716-446655440001",
    "height": 175.0,
    "weight": 70.0,
    "coze_conversation_log": "患者自述近期乏力、腹胀",
    "sanzhen_result": {
      "sanzhen_id": 1,
      "face": "面色偏黄",
      "face_image_url": "https://example.com/face.jpg",
      "tongue_front": "舌苔薄白",
      "tongue_front_image_url": "https://example.com/tongue-front.jpg",
      "tongue_bottom": "舌下络脉轻度迂曲",
      "tongue_bottom_image_url": "https://example.com/tongue-bottom.jpg",
      "pulse": "脉沉细",
      "diagnosis_result": "脾虚湿困倾向"
    },
    "created_at": "2026-04-02T08:10:00",
    "updated_at": "2026-04-02T08:10:00"
  }
}
```

### `GET /api/v1/medical-record/{record_id}`

返回完整就诊记录，`diagnoses` 数组中会混合出现 AI 诊断和医生诊断，按 `created_at` 排序。

就诊记录状态当前可能为：

- `pending`
- `in_progress`
- `completed`
- `confirmed`

## AI 诊断接口

### `POST /api/v1/medical-record/{record_id}/ai-diagnosis`

请求体：

```json
{
  "asr_text": "医生：您好，请问哪里不舒服？患者：最近总是疲劳，饭后腹胀。"
}
```

成功响应中的 `data`：

```json
{
  "diagnosis_id": 1,
  "record_id": 1,
  "type": "AI_DIAGNOSIS",
  "formatted_medical_record": "主诉：疲劳、腹胀...",
  "type_inference": "脾虚湿困型",
  "treatment": null,
  "prescription": "党参 10g\n白术 15g\n茯苓 15g",
  "exercise_prescription": "快走 30 分钟，每周 5 次",
  "diagnosis_explanation": "患者以脾失健运、湿困中焦为主。",
  "response_time": 10.5,
  "model_name": "deepseek-chat",
  "created_at": "2026-04-02T08:20:00",
  "updated_at": "2026-04-02T08:20:00"
}
```

说明：

- 同步 AI 诊断会读取预诊中的 `height`、`weight`、`coze_conversation_log`
- 生成成功后会将就诊记录状态更新为 `completed`

### `POST /api/v1/medical-record/{record_id}/ai-diagnosis/stream`

同样请求：

```json
{
  "asr_text": "医生：您好，请问哪里不舒服？患者：最近总是疲劳，饭后腹胀。"
}
```

返回类型：`text/event-stream`

当前 SSE 事件名：

- `stage_start`
- `content`
- `stage_complete`
- `complete`
- `saved`
- `save_error`
- `error`

`complete` 事件示例：

```text
event: complete
data: {"status":"success","total_processing_time":10.5,"formatted_medical_record":"主诉：疲劳","type_inference":"脾虚湿困型","diagnosis_explanation":"患者疲劳...","prescription":"党参 10g...","exercise_prescription":"快走30分钟..."}
```

`saved` 事件示例：

```text
event: saved
data: {"diagnosis_id":1,"message":"诊断记录已保存"}
```

## 医生诊断与确认接口

### `POST /api/v1/medical-record/{record_id}/doctor-diagnosis`

请求体：

```json
{
  "based_on_ai_diagnosis_id": 1,
  "formatted_medical_record": null,
  "type_inference": null,
  "treatment": "健脾化湿",
  "prescription": null,
  "exercise_prescription": null,
  "comments": "结合舌脉后建议先调脾胃"
}
```

说明：

- `based_on_ai_diagnosis_id` 可选
- 如果提供该字段，缺失的诊断内容会从对应 AI 诊断复制
- 创建成功后，如果就诊状态原本是 `pending` 或 `completed`，会更新为 `in_progress`

### `PUT /api/v1/doctor-diagnosis/{diagnosis_id}`

请求体字段均可选：

```json
{
  "treatment": "健脾化湿，和中理气",
  "comments": "复诊时关注睡眠和纳食"
}
```

限制：

- 只能修改自己创建的医生诊断
- 已确认完成的就诊记录不可再修改

### `GET /api/v1/doctor-diagnosis/{diagnosis_id}`

返回 `DoctorDiagnosisResponse`，会带 `doctor_name`。

### `POST /api/v1/medical-record/{record_id}/confirm`

无需请求体。

成功响应：

```json
{
  "success": true,
  "message": "就诊已确认完成",
  "data": {
    "record_id": 1,
    "status": "confirmed",
    "confirmed_by": "张医生",
    "confirmed_at": "2026-04-02T08:40:00"
  }
}
```

前提：

- 该就诊记录必须存在
- 至少已经创建 1 条医生诊断
- 已确认的记录不可重复确认

## 聊天接口

### `POST /api/v1/chat/conversation`

请求体字段均可选：

```json
{
  "system_prompt": "你是一位中医健康顾问。",
  "patient_id": 1,
  "initial_context": "患者，35 岁，主诉疲劳、腹胀。"
}
```

成功响应中的 `data`：

```json
{
  "conversation_id": 1,
  "session_id": "d1b8f83d-1f6a-49b2-9330-ef64c5b8bd0c",
  "title": null,
  "is_active": true,
  "created_at": "2026-04-02T09:00:00",
  "updated_at": "2026-04-02T09:00:00"
}
```

### `GET /api/v1/chat/conversation/{session_id}`

返回会话详情以及消息历史：

```json
{
  "conversation_id": 1,
  "session_id": "d1b8f83d-1f6a-49b2-9330-ef64c5b8bd0c",
  "title": "最近总是疲劳，饭后腹胀",
  "system_prompt": "你是一位专业的中医健康顾问...",
  "is_active": true,
  "created_at": "2026-04-02T09:00:00",
  "updated_at": "2026-04-02T09:05:00",
  "messages": [
    {
      "message_id": 1,
      "role": "user",
      "content": "最近总是疲劳，饭后腹胀",
      "created_at": "2026-04-02T09:01:00"
    },
    {
      "message_id": 2,
      "role": "assistant",
      "content": "请问睡眠和食欲情况如何？",
      "created_at": "2026-04-02T09:01:03"
    }
  ]
}
```

### `POST /api/v1/chat/chat`

```json
{
  "session_id": "d1b8f83d-1f6a-49b2-9330-ef64c5b8bd0c",
  "content": "最近总是疲劳，饭后腹胀"
}
```

成功响应：

```json
{
  "success": true,
  "message": "发送成功",
  "data": {
    "response": "请问睡眠和食欲情况如何？"
  }
}
```

### `POST /api/v1/chat/chat/stream`

请求体与非流式聊天一致，返回 `text/event-stream`。

当前 SSE 事件格式：

```text
data: {"content":"您好！"}

data: {"content":"我是小康。"}

event: done
data: {"message":"completed"}
```

错误时：

```text
event: error
data: {"message":"会话已关闭"}
```

### `DELETE /api/v1/chat/conversation/{session_id}`

成功响应：

```json
{
  "success": true,
  "message": "会话已关闭",
  "data": {
    "session_id": "d1b8f83d-1f6a-49b2-9330-ef64c5b8bd0c"
  }
}
```
