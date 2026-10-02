"""
医生管理相关API测试
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestDoctorRegistration:
    """医生注册测试"""

    async def test_register_doctor_success(self, client: AsyncClient):
        """测试成功注册医生"""
        doctor_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
            "department": "中医科",
            "position": "主治医师",
            "bio": "擅长中医诊疗",
        }

        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "医生注册成功"
        assert data["data"]["username"] == "doctor_zhang"
        assert data["data"]["name"] == "张医生"
        assert "password" not in data["data"]
        assert "password_hash" not in data["data"]

    async def test_register_doctor_duplicate_username(self, client: AsyncClient):
        """测试重复用户名注册"""
        doctor_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }

        # 第一次注册
        await client.post("/api/v1/doctor/register", json=doctor_data)

        # 第二次注册，用户名相同
        doctor_data["phone"] = "13800138001"  # 修改手机号
        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert "用户名" in data["message"]

    async def test_register_doctor_duplicate_phone(self, client: AsyncClient):
        """测试重复手机号注册"""
        doctor_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }

        # 第一次注册
        await client.post("/api/v1/doctor/register", json=doctor_data)

        # 第二次注册，手机号相同
        doctor_data["username"] = "doctor_li"  # 修改用户名
        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert "手机号" in data["message"]

    async def test_register_doctor_invalid_username(self, client: AsyncClient):
        """测试无效用户名"""
        doctor_data = {
            "username": "doctor-zhang",  # 包含不允许的字符
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }

        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 422  # Validation error

    async def test_register_doctor_invalid_phone(self, client: AsyncClient):
        """测试无效手机号"""
        doctor_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "12345678901",  # 无效手机号
        }

        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 422  # Validation error

    async def test_register_doctor_short_password(self, client: AsyncClient):
        """测试密码过短"""
        doctor_data = {
            "username": "doctor_zhang",
            "password": "12345",  # 少于6位
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }

        response = await client.post("/api/v1/doctor/register", json=doctor_data)

        assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
class TestDoctorLogin:
    """医生登录测试"""

    async def test_login_success(self, client: AsyncClient):
        """测试成功登录"""
        # 先注册医生
        register_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        # 使用用户名登录
        login_data = {"username": "doctor_zhang", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "登录成功"
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["doctor"]["username"] == "doctor_zhang"
        assert "password" not in data["data"]["doctor"]

    async def test_login_with_phone_success(self, client: AsyncClient):
        """测试使用手机号成功登录"""
        # 先注册医生
        register_data = {
            "username": "doctor_li",
            "password": "password123",
            "name": "李医生",
            "gender": "FEMALE",
            "phone": "13800138001",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        # 使用手机号登录
        login_data = {"username": "13800138001", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "登录成功"
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["doctor"]["username"] == "doctor_li"
        assert data["data"]["doctor"]["phone"] == "13800138001"
        assert "password" not in data["data"]["doctor"]

    async def test_login_wrong_password(self, client: AsyncClient):
        """测试错误密码"""
        # 先注册医生
        register_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        # 使用错误密码登录
        login_data = {"username": "doctor_zhang", "password": "wrongpassword"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "用户名/手机号或密码错误"

    async def test_login_with_phone_wrong_password(self, client: AsyncClient):
        """测试使用手机号但密码错误"""
        # 先注册医生
        register_data = {
            "username": "doctor_wang",
            "password": "password123",
            "name": "王医生",
            "gender": "MALE",
            "phone": "13800138002",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        # 使用手机号但错误密码登录
        login_data = {"username": "13800138002", "password": "wrongpassword"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "用户名/手机号或密码错误"

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """测试不存在的用户"""
        login_data = {"username": "nonexistent_user", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "用户名/手机号或密码错误"

    async def test_login_nonexistent_phone(self, client: AsyncClient):
        """测试不存在的手机号"""
        login_data = {"username": "13999999999", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "用户名/手机号或密码错误"


@pytest.mark.asyncio
class TestDoctorInfo:
    """医生信息管理测试"""

    async def register_and_login(self, client: AsyncClient) -> str:
        """辅助方法：注册并登录，返回access_token"""
        register_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
            "department": "中医科",
            "position": "主治医师",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        login_data = {"username": "doctor_zhang", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)
        return response.json()["data"]["access_token"]

    async def test_get_current_doctor_info(self, client: AsyncClient):
        """测试获取当前医生信息"""
        access_token = await self.register_and_login(client)

        response = await client.get(
            "/api/v1/doctor/me", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["username"] == "doctor_zhang"
        assert data["data"]["name"] == "张医生"
        assert data["data"]["department"] == "中医科"

    async def test_get_current_doctor_info_without_auth(self, client: AsyncClient):
        """测试未认证获取医生信息"""
        response = await client.get("/api/v1/doctor/me")

        assert response.status_code == 401  # Unauthorized (no authorization header)

    async def test_get_current_doctor_info_invalid_token(self, client: AsyncClient):
        """测试使用无效token"""
        response = await client.get(
            "/api/v1/doctor/me", headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == 401

    async def test_update_doctor_info(self, client: AsyncClient):
        """测试更新医生信息"""
        access_token = await self.register_and_login(client)

        update_data = {
            "name": "张伟",
            "position": "副主任医师",
            "bio": "擅长中医诊疗和运动康复",
        }

        response = await client.put(
            "/api/v1/doctor/me",
            json=update_data,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "张伟"
        assert data["data"]["position"] == "副主任医师"
        assert data["data"]["bio"] == "擅长中医诊疗和运动康复"
        assert data["data"]["username"] == "doctor_zhang"  # username不可修改

    async def test_update_doctor_phone_duplicate(self, client: AsyncClient):
        """测试更新为已存在的手机号"""
        # 注册第一个医生
        access_token1 = await self.register_and_login(client)

        # 注册第二个医生
        register_data2 = {
            "username": "doctor_li",
            "password": "password123",
            "name": "李医生",
            "gender": "FEMALE",
            "phone": "13800138001",
        }
        await client.post("/api/v1/doctor/register", json=register_data2)

        # 尝试将第一个医生的手机号改为第二个医生的
        update_data = {"phone": "13800138001"}

        response = await client.put(
            "/api/v1/doctor/me",
            json=update_data,
            headers={"Authorization": f"Bearer {access_token1}"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert "手机号" in data["message"]


@pytest.mark.asyncio
class TestPasswordChange:
    """密码修改测试"""

    async def register_and_login(self, client: AsyncClient) -> str:
        """辅助方法：注册并登录，返回access_token"""
        register_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        login_data = {"username": "doctor_zhang", "password": "password123"}
        response = await client.post("/api/v1/doctor/login", json=login_data)
        return response.json()["data"]["access_token"]

    async def test_change_password_success(self, client: AsyncClient):
        """测试成功修改密码"""
        access_token = await self.register_and_login(client)

        password_data = {
            "old_password": "password123",
            "new_password": "newpassword456",
        }

        response = await client.post(
            "/api/v1/doctor/change-password",
            json=password_data,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "密码修改成功"

        # 验证可以使用新密码登录
        login_data = {"username": "doctor_zhang", "password": "newpassword456"}
        login_response = await client.post("/api/v1/doctor/login", json=login_data)
        assert login_response.status_code == 200

        # 验证旧密码不能使用
        old_login_data = {"username": "doctor_zhang", "password": "password123"}
        old_login_response = await client.post(
            "/api/v1/doctor/login", json=old_login_data
        )
        assert old_login_response.status_code == 401

    async def test_change_password_wrong_old_password(self, client: AsyncClient):
        """测试旧密码错误"""
        access_token = await self.register_and_login(client)

        password_data = {
            "old_password": "wrongpassword",
            "new_password": "newpassword456",
        }

        response = await client.post(
            "/api/v1/doctor/change-password",
            json=password_data,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "旧密码不正确" in data["message"]

    async def test_change_password_without_auth(self, client: AsyncClient):
        """测试未认证修改密码"""
        password_data = {
            "old_password": "password123",
            "new_password": "newpassword456",
        }

        response = await client.post(
            "/api/v1/doctor/change-password", json=password_data
        )

        assert response.status_code == 401  # Unauthorized


@pytest.mark.asyncio
@pytest.mark.usefixtures("legacy_uploads")
class TestDoctorDiagnosisIntegration:
    """医生诊断集成测试"""

    async def test_doctor_diagnosis_workflow(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """测试完整的医生诊断工作流"""
        # 1. 注册并登录医生
        register_data = {
            "username": "doctor_zhang",
            "password": "password123",
            "name": "张医生",
            "gender": "MALE",
            "phone": "13800138000",
        }
        await client.post("/api/v1/doctor/register", json=register_data)

        login_data = {"username": "doctor_zhang", "password": "password123"}
        login_response = await client.post("/api/v1/doctor/login", json=login_data)
        access_token = login_response.json()["data"]["access_token"]
        doctor_id = login_response.json()["data"]["doctor"]["doctor_id"]

        # 2. 创建患者和就诊记录
        medical_record_data = {
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
                "weight": 80.0,
            },
        }
        record_response = await client.post(
            "/api/v1/medical-record", json=medical_record_data
        )
        assert record_response.status_code == 201

        # 验证医生信息可以正常访问
        doctor_info_response = await client.get(
            "/api/v1/doctor/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert doctor_info_response.status_code == 200
        assert doctor_info_response.json()["data"]["doctor_id"] == doctor_id
