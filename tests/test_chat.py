"""
聊天 API 测试
"""

from unittest.mock import Mock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("legacy_uploads")


# ========== 创建会话测试 ==========
@pytest.mark.asyncio
async def test_create_conversation_success(client: AsyncClient, auth_headers: dict):
    """测试成功创建会话"""
    response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "session_id" in data["data"]
    assert data["data"]["is_active"] is True


@pytest.mark.asyncio
async def test_create_conversation_with_initial_context(
    client: AsyncClient, auth_headers: dict
):
    """测试带初始上下文创建会话"""
    request_data = {
        "initial_context": "患者信息：男性，35岁，体重85kg，身高175cm",
        "system_prompt": None,
    }

    response = await client.post(
        "/api/v1/chat/conversation", json=request_data, headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "session_id" in data["data"]


@pytest.mark.asyncio
async def test_create_conversation_with_custom_system_prompt(
    client: AsyncClient, auth_headers: dict
):
    """测试带自定义系统提示词创建会话"""
    request_data = {
        "system_prompt": "你是一个专业的营养顾问。",
        "initial_context": None,
    }

    response = await client.post(
        "/api/v1/chat/conversation", json=request_data, headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True


# ========== 获取会话测试 ==========
@pytest.mark.asyncio
async def test_get_conversation_success(client: AsyncClient, auth_headers: dict):
    """测试成功获取会话详情"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # 获取会话详情
    response = await client.get(
        f"/api/v1/chat/conversation/{session_id}", headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["session_id"] == session_id
    assert isinstance(data["data"]["messages"], list)


@pytest.mark.asyncio
async def test_get_conversation_not_found(client: AsyncClient, auth_headers: dict):
    """测试获取不存在的会话"""
    response = await client.get(
        "/api/v1/chat/conversation/non-existent-session-id", headers=auth_headers
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False


# ========== 非流式聊天测试 ==========
@pytest.mark.asyncio
async def test_chat_success(client: AsyncClient, auth_headers: dict):
    """测试成功发送消息（非流式）"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # Mock AI客户端
    with patch("app.services.chat_service.OpenAIChatCompletion") as mock_ai_class:
        mock_ai_instance = Mock()
        mock_ai_instance.client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content="您好！我是小康，很高兴为您服务。"))]
        )
        mock_ai_class.return_value = mock_ai_instance

        # 发送消息
        chat_data = {"session_id": session_id, "content": "你好"}

        response = await client.post(
            "/api/v1/chat/chat", json=chat_data, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "response" in data["data"]


@pytest.mark.asyncio
async def test_chat_session_not_found(client: AsyncClient, auth_headers: dict):
    """测试向不存在的会话发送消息"""
    chat_data = {"session_id": "non-existent-session-id", "content": "你好"}

    response = await client.post(
        "/api/v1/chat/chat", json=chat_data, headers=auth_headers
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_empty_content(client: AsyncClient, auth_headers: dict):
    """测试发送空消息"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    session_id = create_response.json()["data"]["session_id"]

    chat_data = {"session_id": session_id, "content": ""}

    response = await client.post(
        "/api/v1/chat/chat", json=chat_data, headers=auth_headers
    )

    # Pydantic验证会拒绝空字符串
    assert response.status_code == 422


# ========== 流式聊天测试 ==========
@pytest.mark.asyncio
async def test_chat_stream_success(client: AsyncClient, auth_headers: dict):
    """测试成功发送消息（流式）"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # Mock AI客户端的异步流式聊天
    async def mock_stream():
        yield "您好！"
        yield "我是小康。"
        yield "很高兴为您服务。"

    with patch("app.services.chat_service.OpenAIChatCompletion") as mock_ai_class:
        mock_ai_instance = Mock()
        mock_ai_instance.async_stream_chat = Mock(return_value=mock_stream())
        mock_ai_class.return_value = mock_ai_instance

        # 发送流式消息
        chat_data = {"session_id": session_id, "content": "你好"}

        response = await client.post(
            "/api/v1/chat/chat/stream", json=chat_data, headers=auth_headers
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


@pytest.mark.asyncio
async def test_chat_stream_session_not_found(client: AsyncClient, auth_headers: dict):
    """测试向不存在的会话发送流式消息"""
    chat_data = {"session_id": "non-existent-session-id", "content": "你好"}

    response = await client.post(
        "/api/v1/chat/chat/stream", json=chat_data, headers=auth_headers
    )

    assert response.status_code == 404


# ========== 关闭会话测试 ==========
@pytest.mark.asyncio
async def test_close_conversation_success(client: AsyncClient, auth_headers: dict):
    """测试成功关闭会话"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # 关闭会话
    response = await client.delete(
        f"/api/v1/chat/conversation/{session_id}", headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["session_id"] == session_id

    # 验证会话已关闭
    get_response = await client.get(
        f"/api/v1/chat/conversation/{session_id}", headers=auth_headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["data"]["is_active"] is False


@pytest.mark.asyncio
async def test_close_conversation_not_found(client: AsyncClient, auth_headers: dict):
    """测试关闭不存在的会话"""
    response = await client.delete(
        "/api/v1/chat/conversation/non-existent-session-id", headers=auth_headers
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_to_closed_conversation(client: AsyncClient, auth_headers: dict):
    """测试向已关闭的会话发送消息"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # 关闭会话
    close_response = await client.delete(
        f"/api/v1/chat/conversation/{session_id}", headers=auth_headers
    )
    assert close_response.status_code == 200

    # 尝试向已关闭的会话发送流式消息
    chat_data = {"session_id": session_id, "content": "你好"}

    response = await client.post(
        "/api/v1/chat/chat/stream", json=chat_data, headers=auth_headers
    )

    # 应该返回错误（会话已关闭）- ValidationException返回400
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False


# ========== 会话消息历史测试 ==========
@pytest.mark.asyncio
async def test_conversation_message_history(client: AsyncClient, auth_headers: dict):
    """测试会话消息历史记录"""
    # 创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["data"]["session_id"]

    # Mock AI客户端并发送多条消息
    with patch("app.services.chat_service.OpenAIChatCompletion") as mock_ai_class:
        mock_ai_instance = Mock()
        mock_ai_instance.client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content="这是AI的回复。"))]
        )
        mock_ai_class.return_value = mock_ai_instance

        # 发送第一条消息
        await client.post(
            "/api/v1/chat/chat",
            json={"session_id": session_id, "content": "第一条消息"},
            headers=auth_headers,
        )

        # 发送第二条消息
        await client.post(
            "/api/v1/chat/chat",
            json={"session_id": session_id, "content": "第二条消息"},
            headers=auth_headers,
        )

    # 获取会话历史
    response = await client.get(
        f"/api/v1/chat/conversation/{session_id}", headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    messages = data["data"]["messages"]

    # 应该有4条消息（2条用户消息 + 2条AI回复）
    assert len(messages) == 4

    # 验证消息角色交替
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "user"
    assert messages[3]["role"] == "assistant"


# ========== 输入验证测试 ==========
@pytest.mark.asyncio
async def test_chat_content_too_long(client: AsyncClient, auth_headers: dict):
    """测试消息内容超长"""
    # 先创建会话
    create_response = await client.post(
        "/api/v1/chat/conversation", json={}, headers=auth_headers
    )
    session_id = create_response.json()["data"]["session_id"]

    # 发送超长消息（超过10000字符）
    chat_data = {"session_id": session_id, "content": "a" * 10001}

    response = await client.post(
        "/api/v1/chat/chat", json=chat_data, headers=auth_headers
    )

    # Pydantic验证会拒绝超长内容
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_conversation_with_patient_id(
    client: AsyncClient, auth_headers: dict
):
    """测试创建关联患者的会话"""
    # 先创建患者（通过创建就诊记录）
    record_data = {
        "uuid": "550e8400-e29b-41d4-a716-446655440100",
        "patient_phone": "13800138100",
        "patient_info": {
            "name": "聊天测试患者",
            "sex": "MALE",
            "birthday": "1985-01-01",
            "phone": "13800138100",
        },
        "pre_diagnosis": {
            "uuid": "660e8400-e29b-41d4-a716-446655440100",
            "height": 175.0,
            "weight": 70.0,
        },
    }

    await client.post("/api/v1/medical-record", json=record_data)

    # 创建关联患者的会话（patient_id=1，假设是第一个创建的患者）
    request_data = {
        "patient_id": 1,
        "initial_context": "患者姓名：聊天测试患者，身高175cm，体重70kg",
    }

    response = await client.post(
        "/api/v1/chat/conversation", json=request_data, headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
