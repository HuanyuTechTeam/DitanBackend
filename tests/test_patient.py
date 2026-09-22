"""
病人和诊断相关 API 测试
"""

from unittest.mock import Mock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("legacy_uploads")


# ========== 患者查询测试 ==========
@pytest.mark.asyncio
async def test_query_patient_success(client: AsyncClient, auth_headers: dict):
    """测试成功查询患者信息"""
    # 先创建就诊记录（会自动创建患者）- 显式 legacy 兼容模式
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440001",
        "patient_phone": "13800138001",
        "patient_info": {
            "name": "张三",
            "sex": "MALE",
            "birthday": "1985-05-20",
            "phone": "13800138001",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440001",
            "height": 175.0,
            "weight": 70.0,
        },
    }

    create_response = await client.post("/api/v1/medical-record", json=record_data)
    assert create_response.status_code == 201

    # 查询患者 - 需要认证
    response = await client.get(
        "/api/v1/patient/query?phone=13800138001", headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["patient"]["phone"] == "13800138001"
    assert data["data"]["patient"]["name"] == "张三"
    assert isinstance(data["data"]["medical_records"], list)
    assert len(data["data"]["medical_records"]) == 1


@pytest.mark.asyncio
async def test_query_patient_not_found(client: AsyncClient, auth_headers: dict):
    """测试查询不存在的患者"""
    response = await client.get(
        "/api/v1/patient/query?phone=13800138999", headers=auth_headers
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "未找到" in data["message"]


@pytest.mark.asyncio
async def test_query_patient_unauthorized(client: AsyncClient):
    """测试未认证访问患者查询接口"""
    response = await client.get("/api/v1/patient/query?phone=13800138001")

    assert response.status_code == 401


# ========== 创建就诊记录测试 ==========
@pytest.mark.asyncio
async def test_create_medical_record_new_patient(client: AsyncClient):
    """测试为新患者创建就诊记录"""
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440010",
        "patient_phone": "13800138010",
        "patient_info": {
            "name": "新患者",
            "sex": "MALE",
            "birthday": "1985-01-01",
            "phone": "13800138010",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440010",
            "height": 175.0,
            "weight": 80.0,
            "coze_conversation_log": "患者：我最近体重增加了...",
            "sanzhen_analysis": {
                "face": "面色略黄",
                "tongue_front": "舌苔薄白",
                "tongue_bottom": "舌下正常",
                "pulse": "脉象沉细",
            },
        },
    }

    response = await client.post("/api/v1/medical-record", json=record_data)

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["uuid"] == "550e8400-e29b-41d4-a716-446655440010"
    assert data["data"]["patient"]["phone"] == "13800138010"


@pytest.mark.asyncio
async def test_create_medical_record_existing_patient(client: AsyncClient):
    """测试为现有患者创建就诊记录"""
    # 先创建患者（通过第一次就诊记录）
    first_record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440011",
        "patient_phone": "13800138011",
        "patient_info": {
            "name": "老患者",
            "sex": "FEMALE",
            "birthday": "1990-01-01",
            "phone": "13800138011",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440011",
            "height": 160.0,
            "weight": 55.0,
        },
    }

    first_response = await client.post("/api/v1/medical-record", json=first_record_data)
    assert first_response.status_code == 201

    # 为现有患者创建第二次就诊记录（不提供patient_info）
    second_record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440012",
        "patient_phone": "13800138011",
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440012",
            "height": 160.0,
            "weight": 54.0,
        },
    }

    response = await client.post("/api/v1/medical-record", json=second_record_data)

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["patient"]["name"] == "老患者"
    assert data["data"]["patient"]["phone"] == "13800138011"


@pytest.mark.asyncio
async def test_create_medical_record_duplicate_uuid(client: AsyncClient):
    """测试创建重复UUID的就诊记录"""
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440013",
        "patient_phone": "13800138012",
        "patient_info": {
            "name": "测试患者",
            "sex": "MALE",
            "birthday": "1985-01-01",
            "phone": "13800138012",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440013",
            "height": 170.0,
            "weight": 70.0,
        },
    }

    # 第一次创建
    response1 = await client.post("/api/v1/medical-record", json=record_data)
    assert response1.status_code == 201

    # 第二次创建（重复UUID）
    response2 = await client.post("/api/v1/medical-record", json=record_data)
    assert response2.status_code == 201
    data = response2.json()
    assert data["success"] is True
    assert data["data"]["record_id"] == response1.json()["data"]["record_id"]


# ========== 查询就诊记录测试 ==========
@pytest.mark.asyncio
async def test_get_medical_record_success(client: AsyncClient, auth_headers: dict):
    """测试成功查询就诊记录"""
    # 先创建就诊记录 - 显式 legacy 兼容模式
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440014",
        "patient_phone": "13800138013",
        "patient_info": {
            "name": "查询测试",
            "sex": "MALE",
            "birthday": "1985-01-01",
            "phone": "13800138013",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440014",
            "height": 175.0,
            "weight": 80.0,
        },
    }

    create_response = await client.post("/api/v1/medical-record", json=record_data)
    assert create_response.status_code == 201
    record_id = create_response.json()["data"]["record_id"]

    # 查询就诊记录 - 需要认证
    response = await client.get(
        f"/api/v1/medical-record/{record_id}", headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["record_id"] == record_id
    assert data["data"]["patient"]["phone"] == "13800138013"
    assert data["data"]["pre_diagnosis"] is not None


@pytest.mark.asyncio
async def test_get_medical_record_not_found(client: AsyncClient, auth_headers: dict):
    """测试查询不存在的就诊记录"""
    response = await client.get("/api/v1/medical-record/99999", headers=auth_headers)

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_get_medical_record_unauthorized(client: AsyncClient):
    """测试未认证访问就诊记录"""
    response = await client.get("/api/v1/medical-record/1")

    assert response.status_code == 401


# ========== AI诊断测试 ==========
@pytest.mark.asyncio
async def test_create_ai_diagnosis_success(client: AsyncClient, auth_headers: dict):
    """测试成功创建AI诊断"""
    # 先创建就诊记录 - 显式 legacy 兼容模式
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440015",
        "patient_phone": "13800138014",
        "patient_info": {
            "name": "AI诊断测试",
            "sex": "MALE",
            "birthday": "1985-01-01",
            "phone": "13800138014",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440015",
            "height": 175.0,
            "weight": 85.0,
        },
    }

    create_response = await client.post("/api/v1/medical-record", json=record_data)
    assert create_response.status_code == 201
    record_id = create_response.json()["data"]["record_id"]

    # Mock TCM诊断服务
    mock_diagnosis_result = {
        "overall_status": "success",
        "medical_record_result": {
            "medical_record": "主诉：体重增加\n病史：身高175cm，体重85kg..."
        },
        "diagnosis_result": {
            "diagnosis": "脾虚湿困型",
            "diagnosis_explanation": "患者肢体困重，懒言少动...",
        },
        "prescription_result": {"prescription": "党参 10g\n麸炒白术 15g\n茯苓 15g..."},
        "exercise_prescription_result": {
            "exercise_prescription": "第一周：快走30分钟，每周5次..."
        },
        "total_processing_time": 10.5,
    }

    with patch("app.api.patient.get_tcm_service") as mock_service:
        mock_instance = Mock()
        mock_instance.process_complete_diagnosis.return_value = mock_diagnosis_result
        mock_service.return_value = mock_instance

        # 创建AI诊断 - 需要认证
        diagnosis_data = {
            "asr_text": "医生：您好，请问有什么不舒服？\n患者：我最近体重增加了很多..."
        }

        response = await client.post(
            f"/api/v1/medical-record/{record_id}/ai-diagnosis",
            json=diagnosis_data,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["type_inference"] == "脾虚湿困型"
        assert data["data"]["prescription"] is not None
        assert data["data"]["exercise_prescription"] is not None


@pytest.mark.asyncio
async def test_create_ai_diagnosis_with_coze_conversation_log(
    client: AsyncClient, auth_headers: dict
):
    """测试带有coze_conversation_log的AI诊断生成"""
    # 创建包含coze_conversation_log的就诊记录
    coze_log = """AI: 您好，我是您的健康顾问。请问您今天感觉怎么样？
User: 我最近总是感觉疲劳，而且体重增加了不少。
AI: 明白了。您能描述一下您的饮食习惯吗？
User: 我食欲还可以，但吃完饭后经常感觉腹胀。
AI: 您最近睡眠质量如何？
User: 睡眠还行，但有时会失眠。"""

    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440016",
        "patient_phone": "13800138015",
        "patient_info": {
            "name": "测试患者coze对话",
            "sex": "FEMALE",
            "birthday": "1990-06-15",
            "phone": "13800138015",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440016",
            "height": 165.0,
            "weight": 68.0,
            "coze_conversation_log": coze_log,
        },
    }

    create_response = await client.post("/api/v1/medical-record", json=record_data)
    assert create_response.status_code == 201
    record_id = create_response.json()["data"]["record_id"]

    # Mock TCM诊断服务
    mock_diagnosis_result = {
        "overall_status": "success",
        "medical_record_result": {
            "medical_record": "主诉：疲劳、体重增加\n病史：身高165cm，体重68kg，食欲可，饭后腹胀..."
        },
        "diagnosis_result": {
            "diagnosis": "脾虚湿困型",
            "diagnosis_explanation": "根据预问诊和医患对话，患者疲劳、腹胀、体重增加...",
        },
        "prescription_result": {"prescription": "党参 10g\n麸炒白术 15g\n茯苓 15g..."},
        "exercise_prescription_result": {
            "exercise_prescription": "第一周：快走30分钟，每周5次..."
        },
        "total_processing_time": 12.3,
    }

    with patch("app.api.patient.get_tcm_service") as mock_service:
        mock_instance = Mock()
        mock_instance.process_complete_diagnosis.return_value = mock_diagnosis_result
        mock_service.return_value = mock_instance

        # 创建AI诊断
        diagnosis_data = {
            "asr_text": "医生：根据您的预问诊信息，您提到了疲劳和体重增加？\n患者：是的，而且我还觉得肢体有些困重。"
        }

        response = await client.post(
            f"/api/v1/medical-record/{record_id}/ai-diagnosis",
            json=diagnosis_data,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["type_inference"] == "脾虚湿困型"
        assert data["data"]["formatted_medical_record"] is not None
        assert data["data"]["prescription"] is not None

        # 验证process_complete_diagnosis被调用时传入了正确的参数
        mock_instance.process_complete_diagnosis.assert_called_once()
        call_args = mock_instance.process_complete_diagnosis.call_args

        # 验证coze_conversation_log参数被正确传递
        assert call_args.kwargs["coze_conversation_log"] == coze_log
        assert call_args.kwargs["height"] == 165.0
        assert call_args.kwargs["weight"] == 68.0
        assert (
            "疲劳" in call_args.kwargs["transcript"]
            or "肢体有些困重" in call_args.kwargs["transcript"]
        )


@pytest.mark.asyncio
async def test_create_ai_diagnosis_without_coze_log(
    client: AsyncClient, auth_headers: dict
):
    """测试没有coze_conversation_log时的AI诊断生成"""
    # 创建不包含coze_conversation_log的就诊记录
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440017",
        "patient_phone": "13800138016",
        "patient_info": {
            "name": "无coze对话测试",
            "sex": "MALE",
            "birthday": "1988-03-20",
            "phone": "13800138016",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440017",
            "height": 178.0,
            "weight": 90.0,
            # 注意：没有coze_conversation_log字段
        },
    }

    create_response = await client.post("/api/v1/medical-record", json=record_data)
    assert create_response.status_code == 201
    record_id = create_response.json()["data"]["record_id"]

    # Mock TCM诊断服务
    mock_diagnosis_result = {
        "overall_status": "success",
        "medical_record_result": {
            "medical_record": "主诉：体重过重\n病史：身高178cm，体重90kg..."
        },
        "diagnosis_result": {
            "diagnosis": "胃热燔脾型",
            "diagnosis_explanation": "患者食欲旺盛，体重超标...",
        },
        "prescription_result": {"prescription": "北柴胡 10g\n牡丹皮 10g\n知母 10g..."},
        "exercise_prescription_result": {
            "exercise_prescription": "第一周：慢跑20分钟，每周4次..."
        },
        "total_processing_time": 9.8,
    }

    with patch("app.api.patient.get_tcm_service") as mock_service:
        mock_instance = Mock()
        mock_instance.process_complete_diagnosis.return_value = mock_diagnosis_result
        mock_service.return_value = mock_instance

        # 创建AI诊断
        diagnosis_data = {
            "asr_text": "医生：您好，请问有什么不舒服？\n患者：我觉得自己体重太重了，想减肥。"
        }

        response = await client.post(
            f"/api/v1/medical-record/{record_id}/ai-diagnosis",
            json=diagnosis_data,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True

        # 验证process_complete_diagnosis被调用
        mock_instance.process_complete_diagnosis.assert_called_once()
        call_args = mock_instance.process_complete_diagnosis.call_args

        # 验证当没有coze_conversation_log时，传入的是None
        assert call_args.kwargs["coze_conversation_log"] is None
        assert call_args.kwargs["height"] == 178.0
        assert call_args.kwargs["weight"] == 90.0


@pytest.mark.asyncio
async def test_create_ai_diagnosis_record_not_found(
    client: AsyncClient, auth_headers: dict
):
    """测试为不存在的就诊记录创建AI诊断"""
    diagnosis_data = {"asr_text": "测试对话内容..."}

    response = await client.post(
        "/api/v1/medical-record/99999/ai-diagnosis",
        json=diagnosis_data,
        headers=auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_ai_diagnosis_unauthorized(client: AsyncClient):
    """测试未认证访问AI诊断接口"""
    diagnosis_data = {"asr_text": "测试对话内容..."}

    response = await client.post(
        "/api/v1/medical-record/1/ai-diagnosis", json=diagnosis_data
    )

    assert response.status_code == 401


# ========== 健康检查测试 ==========
@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """测试健康检查端点"""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """测试根端点"""
    response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "version" in data
