# 数据库文档

本文档基于当前 SQLAlchemy 模型编写，主要对应：

- `app/models/doctor.py`
- `app/models/medical.py`
- `app/models/chat.py`

## 当前建表方式

项目启动时会执行：

```python
await init_db()
```

而 `init_db()` 内部调用的是：

```python
Base.metadata.create_all()
```

这意味着：

- 全新数据库可在应用启动时自动建表
- 应用启动时不会自动执行 Alembic migration
- 变更现有生产库时，仍然应该先评估迁移方案

## 核心实体

### Doctor

表名：`doctors`

主要字段：

- `doctor_id`
- `username`
- `password_hash`
- `name`
- `gender`
- `phone`
- `department`
- `position`
- `bio`
- `created_at`
- `updated_at`
- `last_login`

关系：

- 一个医生可以关联多条 `DoctorDiagnosisRecord`

### Patient

表名：`patients`

主要字段：

- `patient_id`
- `name`
- `sex`
- `birthday`
- `phone`

关系：

- 一个患者可以关联多条 `PatientMedicalRecord`

### PatientMedicalRecord

表名：`patient_medical_records`

主要字段：

- `record_id`
- `patient_id`
- `uuid`
- `status`
- `created_at`
- `updated_at`

当前状态值：

- `pending`
- `in_progress`
- `completed`
- `confirmed`

关系：

- 属于一个患者
- 有一个 `PreDiagnosisRecord`
- 有多条诊断记录

### PreDiagnosisRecord

表名：`pre_diagnosis_records`

主要字段：

- `pre_diagnosis_id`
- `record_id`
- `uuid`
- `height`
- `weight`
- `coze_conversation_log`
- `created_at`
- `updated_at`

关系：

- 属于一个 `PatientMedicalRecord`
- 可选关联一个 `SanzhenAnalysisResult`

### SanzhenAnalysisResult

表名：`sanzhen_analysis_results`

主要字段：

- `sanzhen_id`
- `pre_diagnosis_id`
- `face`
- `face_image_url`
- `tongue_front`
- `tongue_front_image_url`
- `tongue_bottom`
- `tongue_bottom_image_url`
- `pulse`
- `diagnosis_result`

说明：

- 当前模型已包含三诊图片 URL 字段
- 仓库中的 Alembic 文件 `001_add_sanzhen_image_urls.py` 也是围绕这三个 URL 字段

## 诊断记录模型

### DiagnosisRecord

表名：`diagnosis_records`

这是诊断记录基类，使用 joined-table inheritance。

主要字段：

- `diagnosis_id`
- `record_id`
- `type`
- `formatted_medical_record`
- `type_inference`
- `treatment`
- `prescription`
- `exercise_prescription`
- `created_at`
- `updated_at`

当前 `type` 枚举值：

- `AI_DIAGNOSIS`
- `DOCTOR_DIAGNOSIS`

### AIDiagnosisRecord

表名：`ai_diagnosis_records`

扩展字段：

- `diagnosis_explanation`
- `response_time`
- `model_name`

说明：

- 同步和流式 AI 诊断最终都会落库到该表

### DoctorDiagnosisRecord

表名：`doctor_diagnosis_records`

扩展字段：

- `doctor_id`
- `comments`

关系：

- 关联 `doctors`

## 聊天模型

### ChatConversation

表名：`chat_conversations`

主要字段：

- `conversation_id`
- `session_id`
- `patient_id`
- `title`
- `system_prompt`
- `is_active`
- `created_at`
- `updated_at`

说明：

- `session_id` 是外部接口使用的会话主标识
- `patient_id` 可空，不要求必须绑定患者

### ChatMessage

表名：`chat_messages`

主要字段：

- `message_id`
- `conversation_id`
- `role`
- `content`
- `tokens`
- `created_at`

当前 `role` 枚举值：

- `system`
- `user`
- `assistant`

## 表关系总览

```text
Doctor
  └── DoctorDiagnosisRecord

Patient
  └── PatientMedicalRecord
        ├── PreDiagnosisRecord
        │     └── SanzhenAnalysisResult
        ├── AIDiagnosisRecord
        └── DoctorDiagnosisRecord

Patient (optional)
  └── ChatConversation
        └── ChatMessage
```

## 初始化方式

### 方式一：应用启动时自动建表

```bash
uv run python main.py
```

### 方式二：显式执行脚本

```bash
uv run python scripts/init_db.py
```

## 迁移说明

仓库中当前有：

- `alembic/`
- `alembic.ini`
- `alembic/versions/001_add_sanzhen_image_urls.py`

但默认运行流程并不会自动执行 Alembic。对于已有数据库：

1. 先备份
2. 对照当前模型检查差异
3. 再决定是否使用 Alembic、手动 SQL 或重建开发库

## 开发环境重置

如果使用 Docker Compose，本仓库提供重置脚本：

Linux/macOS：

```bash
./scripts/manage_db.sh reset
```

Windows：

```powershell
.\scripts\manage_db.ps1 reset
```

注意：该操作会删除 Docker volume 中的数据库数据。
