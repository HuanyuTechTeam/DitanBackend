# 快速上手指南

本文档给出一条与当前代码一致的最短使用路径：启动服务、注册医生、写入就诊记录、生成诊断、确认就诊，以及可选的聊天能力。

## 1. 启动项目

```bash
uv sync
uv sync --extra dev
cp .env.example .env
uv run python scripts/run_dev.py
```

启动后访问：

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## 2. 注册医生

```bash
curl -X POST "http://localhost:8000/api/v1/doctor/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "doctor_zhang",
    "password": "password123",
    "name": "张医生",
    "gender": "MALE",
    "phone": "13800138000",
    "department": "中医科",
    "position": "主治医师"
  }'
```

## 3. 登录并保存 JWT

```bash
curl -X POST "http://localhost:8000/api/v1/doctor/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "doctor_zhang",
    "password": "password123"
  }'
```

把响应中的 `data.access_token` 保存为后续请求头：

```http
Authorization: Bearer <access_token>
```

## 4. 创建就诊记录

该接口通常由预问诊系统调用，不需要 JWT。

```bash
curl -X POST "http://localhost:8000/api/v1/medical-record" \
  -H "Content-Type: application/json" \
  -d '{
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
      "coze_conversation_log": "患者主诉近期疲劳、腹胀",
      "sanzhen_analysis": {
        "face": "面色偏黄",
        "tongue_front": "舌苔薄白",
        "tongue_bottom": "舌下络脉轻度迂曲",
        "pulse": "脉沉细",
        "diagnosis_result": "脾虚湿困倾向"
      }
    }
  }'
```

说明：

- 首次创建患者时必须带 `patient_info`
- `patient_info.phone` 应与 `patient_phone` 保持一致

## 5. 医生查询患者与就诊记录

### 按手机号查询患者

```bash
curl -X GET "http://localhost:8000/api/v1/patient/query?phone=13800138001" \
  -H "Authorization: Bearer <access_token>"
```

### 获取完整就诊记录

```bash
curl -X GET "http://localhost:8000/api/v1/medical-record/1" \
  -H "Authorization: Bearer <access_token>"
```

## 6. 生成 AI 诊断

### 同步模式

```bash
curl -X POST "http://localhost:8000/api/v1/medical-record/1/ai-diagnosis" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "asr_text": "医生：您好，请问哪里不舒服？患者：最近总是疲劳，饭后腹胀。"
  }'
```

### 流式模式

```bash
curl -N -X POST "http://localhost:8000/api/v1/medical-record/1/ai-diagnosis/stream" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "asr_text": "医生：您好，请问哪里不舒服？患者：最近总是疲劳，饭后腹胀。"
  }'
```

当前流式事件包括：

- `stage_start`
- `content`
- `stage_complete`
- `complete`
- `saved`
- `save_error`
- `error`

## 7. 创建医生诊断

可以直接填写，也可以基于 AI 诊断补齐字段。

```bash
curl -X POST "http://localhost:8000/api/v1/medical-record/1/doctor-diagnosis" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "based_on_ai_diagnosis_id": 1,
    "treatment": "健脾化湿，和中理气",
    "comments": "结合舌脉信息，建议先调脾胃"
  }'
```

如果需要修改：

```bash
curl -X PUT "http://localhost:8000/api/v1/doctor-diagnosis/1" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "comments": "复诊时重点观察睡眠与纳食"
  }'
```

## 8. 确认就诊完成

确认前必须至少已有 1 条医生诊断。

```bash
curl -X POST "http://localhost:8000/api/v1/medical-record/1/confirm" \
  -H "Authorization: Bearer <access_token>"
```

确认成功后，该就诊记录状态会变为 `confirmed`。

## 9. 可选：创建 AI 聊天会话

聊天接口当前无需 JWT。

### 创建会话

```bash
curl -X POST "http://localhost:8000/api/v1/chat/conversation" \
  -H "Content-Type: application/json" \
  -d '{
    "initial_context": "患者，35岁，主诉疲劳、腹胀。"
  }'
```

### 非流式聊天

```bash
curl -X POST "http://localhost:8000/api/v1/chat/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id>",
    "content": "最近总是疲劳，饭后腹胀"
  }'
```

### 流式聊天

```bash
curl -N -X POST "http://localhost:8000/api/v1/chat/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id>",
    "content": "最近总是疲劳，饭后腹胀"
  }'
```

当前聊天流式事件：

- 普通内容块: `data: {"content":"..."}`
- 结束事件: `event: done`
- 异常事件: `event: error`

## 10. 下一步

更详细的字段定义和响应示例见：

- [API.md](API.md)
- [DATABASE.md](DATABASE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
