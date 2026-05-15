"""医生用户相关 API 路由"""

from fastapi import APIRouter, Depends

from app.api.deps import RequestContext, get_request_context, get_auth_context
from app.core.exceptions import DatabaseException
from app.schemas import APIResponse
from app.schemas.doctor import (
    DoctorRegister,
    DoctorLogin,
    DoctorUpdate,
    PasswordChange,
)
from app.services import DoctorService

router = APIRouter()


@router.post("/register", response_model=APIResponse, status_code=201)
async def register_doctor(
    doctor_data: DoctorRegister,
    ctx: RequestContext = Depends(get_request_context),
):
    """医生注册"""
    try:
        ctx.log_info(f"注册请求: username={doctor_data.username}")

        service = DoctorService(ctx.db)
        result = await service.register(doctor_data)

        ctx.log_info(f"注册成功: doctor_id={result.doctor_id}")
        return APIResponse(
            success=True,
            message="医生注册成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("注册失败", e)
        raise DatabaseException("医生注册时发生错误", str(e))


@router.post("/login", response_model=APIResponse, status_code=200)
async def login_doctor(
    login_data: DoctorLogin,
    ctx: RequestContext = Depends(get_request_context),
):
    """医生登录"""
    try:
        ctx.log_info(f"登录请求: {login_data.username}")

        service = DoctorService(ctx.db)
        result = await service.login(login_data)

        ctx.log_info(f"登录成功: doctor_id={result.doctor.doctor_id}")
        return APIResponse(
            success=True,
            message="登录成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message") or hasattr(e, "status_code"):
            raise
        ctx.log_error("登录失败", e)
        raise DatabaseException("登录时发生错误", str(e))


@router.get("/me", response_model=APIResponse, status_code=200)
async def get_current_doctor_info(ctx: RequestContext = Depends(get_auth_context)):
    """获取当前登录医生的信息"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(f"查询信息: doctor_id={doctor.doctor_id}")

        service = DoctorService(ctx.db)
        result = await service.get_doctor_info(doctor)

        return APIResponse(
            success=True,
            message="获取医生信息成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("获取医生信息失败", e)
        raise DatabaseException("获取医生信息时发生错误", str(e))


@router.put("/me", response_model=APIResponse, status_code=200)
async def update_current_doctor_info(
    update_data: DoctorUpdate,
    ctx: RequestContext = Depends(get_auth_context),
):
    """更新当前登录医生的信息"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(f"更新信息: doctor_id={doctor.doctor_id}")

        service = DoctorService(ctx.db)
        result = await service.update_doctor_info(doctor, update_data)

        ctx.log_info(f"更新成功: doctor_id={doctor.doctor_id}")
        return APIResponse(
            success=True,
            message="医生信息更新成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("更新医生信息失败", e)
        raise DatabaseException("更新医生信息时发生错误", str(e))


@router.post("/change-password", response_model=APIResponse, status_code=200)
async def change_password(
    password_data: PasswordChange,
    ctx: RequestContext = Depends(get_auth_context),
):
    """修改当前登录医生的密码"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(f"修改密码: doctor_id={doctor.doctor_id}")

        service = DoctorService(ctx.db)
        await service.change_password(doctor, password_data)

        ctx.log_info(f"密码修改成功: doctor_id={doctor.doctor_id}")
        return APIResponse(success=True, message="密码修改成功", data=None)
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("修改密码失败", e)
        raise DatabaseException("修改密码时发生错误", str(e))
