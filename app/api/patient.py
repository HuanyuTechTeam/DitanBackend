"""病人数据和诊断相关 API 路由"""

import json

from fastapi import APIRouter, Body, Depends, Query, Path
from fastapi.responses import StreamingResponse

from app.api.deps import RequestContext, get_upload_context, get_auth_context
from app.core import get_settings
from app.core.exceptions import DatabaseException
from app.schemas import APIResponse
from app.schemas.patient import (
    MedicalRecordCreate,
    AIDiagnosisCreate,
    DoctorDiagnosisCreate,
    DoctorDiagnosisUpdate,
)
from app.services import (
    PatientService,
    MedicalRecordService,
    DiagnosisService,
    get_tcm_service,
)

router = APIRouter()
settings = get_settings()


@router.get("/patient/query", response_model=APIResponse, status_code=200)
async def query_patient_by_phone(
    phone: str = Query(..., description="患者手机号"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """通过手机号查询患者信息和历史就诊记录"""
    try:
        ctx.log_info("查询患者")

        service = PatientService(ctx.db, ctx.organization)
        result = await service.query_by_phone(phone)

        ctx.log_info(f"查询成功: records={len(result.medical_records)}")
        return APIResponse(
            success=True,
            message="患者信息查询成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("查询患者信息失败", e)
        raise DatabaseException("查询患者信息时发生错误", str(e))


@router.post("/medical-record", response_model=APIResponse, status_code=201)
async def create_medical_record(
    record_data: MedicalRecordCreate,
    ctx: RequestContext = Depends(get_upload_context),
):
    """创建就诊记录（专用上传票据）"""
    service = MedicalRecordService(ctx.db, ctx.organization)
    try:
        result = await service.create_medical_record(
            record_data,
            ctx.current_upload,
            ctx.request.state.request_id,
        )
        ctx.request.state.upload_result = (
            "replayed" if service.upload_replayed else "created"
        )
        return APIResponse(
            success=True, message="就诊记录创建成功", data=result.model_dump()
        )
    except Exception as exc:
        if hasattr(exc, "message"):
            raise
        # SQL exception strings may contain clinical values; never log or echo them.
        raise DatabaseException("创建就诊记录时发生错误") from None
    finally:
        ctx.request.state.upload_record_id = service.upload_record_id


@router.get("/medical-record/{record_id}", response_model=APIResponse, status_code=200)
async def get_medical_record(
    record_id: int = Path(..., description="就诊记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """获取完整的就诊记录信息"""
    try:
        ctx.log_info(f"查询就诊记录: record_id={record_id}")

        service = MedicalRecordService(ctx.db, ctx.organization)
        result = await service.get_complete_record(record_id)

        ctx.log_info(f"查询成功: record_id={record_id}")
        return APIResponse(
            success=True,
            message="就诊记录查询成功",
            data=result,
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("查询就诊记录失败", e)
        raise DatabaseException("查询就诊记录时发生错误", str(e))


@router.post(
    "/medical-record/{record_id}/ai-diagnosis",
    response_model=APIResponse,
    status_code=201,
)
async def create_ai_diagnosis(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: AIDiagnosisCreate = Body(...),
    ctx: RequestContext = Depends(get_auth_context),
):
    """为就诊记录生成AI诊断"""
    try:
        ctx.log_info(f"生成AI诊断: record_id={record_id}")

        service = DiagnosisService(ctx.db, ctx.organization)
        result = await service.create_ai_diagnosis(
            record_id,
            diagnosis_data,
            tcm_service_factory=get_tcm_service,
        )

        ctx.log_info(f"AI诊断完成: diagnosis_id={result.diagnosis_id}")
        return APIResponse(
            success=True,
            message="AI诊断完成",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("生成AI诊断失败", e)
        raise DatabaseException("生成AI诊断时发生错误", str(e))


@router.post("/medical-record/{record_id}/ai-diagnosis/stream", status_code=200)
async def create_ai_diagnosis_stream(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: AIDiagnosisCreate = Body(...),
    ctx: RequestContext = Depends(get_auth_context),
):
    """为就诊记录生成AI诊断（流式返回）"""
    ctx.log_info(f"流式AI诊断: record_id={record_id}")

    service = DiagnosisService(ctx.db, ctx.organization)
    medical_record, params = await service.stream_ai_diagnosis(
        record_id, diagnosis_data
    )

    diagnosis_result_holder = {"data": None}

    async def generate_stream():
        tcm_service = get_tcm_service()
        try:
            async for event_data in tcm_service.stream_complete_diagnosis(
                transcript=diagnosis_data.asr_text,
                **params,
            ):
                yield event_data
                if event_data.startswith("event: complete"):
                    lines = event_data.strip().split("\n")
                    for line in lines:
                        if line.startswith("data: "):
                            diagnosis_result_holder["data"] = json.loads(line[6:])
                            break
        except Exception as e:
            ctx.log_error("流式诊断出错", e)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    async def stream_and_save():
        async for event_data in generate_stream():
            yield event_data

        if (
            diagnosis_result_holder["data"]
            and diagnosis_result_holder["data"].get("status") == "success"
        ):
            try:
                ai_diagnosis = await service.save_stream_diagnosis_result(
                    record_id, diagnosis_result_holder["data"]
                )
                ctx.log_info(
                    f"流式AI诊断保存成功: diagnosis_id={ai_diagnosis.diagnosis_id}"
                )
                yield f"event: saved\ndata: {json.dumps({'diagnosis_id': ai_diagnosis.diagnosis_id, 'message': '诊断记录已保存'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                ctx.log_error("保存诊断记录失败", e)
                yield f"event: save_error\ndata: {json.dumps({'message': f'保存诊断记录失败: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream_and_save(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/medical-record/{record_id}/doctor-diagnosis",
    response_model=APIResponse,
    status_code=201,
)
async def create_doctor_diagnosis(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: DoctorDiagnosisCreate = Body(...),
    ctx: RequestContext = Depends(get_auth_context),
):
    """创建医生诊断记录"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(
            f"创建医生诊断: record_id={record_id}, doctor_id={doctor.doctor_id}"
        )

        service = DiagnosisService(ctx.db, ctx.organization)
        result = await service.create_doctor_diagnosis(
            record_id, doctor, diagnosis_data
        )

        ctx.log_info(f"医生诊断创建成功: diagnosis_id={result.diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录创建成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("创建医生诊断失败", e)
        raise DatabaseException("创建医生诊断记录时发生错误", str(e))


@router.put(
    "/doctor-diagnosis/{diagnosis_id}", response_model=APIResponse, status_code=200
)
async def update_doctor_diagnosis(
    diagnosis_id: int = Path(..., description="诊断记录ID"),
    diagnosis_data: DoctorDiagnosisUpdate = Body(...),
    ctx: RequestContext = Depends(get_auth_context),
):
    """更新医生诊断记录"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(f"更新医生诊断: diagnosis_id={diagnosis_id}")

        service = DiagnosisService(ctx.db, ctx.organization)
        result = await service.update_doctor_diagnosis(
            diagnosis_id, doctor, diagnosis_data
        )

        ctx.log_info(f"医生诊断更新成功: diagnosis_id={diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录更新成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("更新医生诊断失败", e)
        raise DatabaseException("更新医生诊断记录时发生错误", str(e))


@router.get(
    "/doctor-diagnosis/{diagnosis_id}", response_model=APIResponse, status_code=200
)
async def get_doctor_diagnosis(
    diagnosis_id: int = Path(..., description="诊断记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """获取医生诊断记录详情"""
    try:
        ctx.log_info(f"查询医生诊断: diagnosis_id={diagnosis_id}")

        service = DiagnosisService(ctx.db, ctx.organization)
        result = await service.get_doctor_diagnosis(diagnosis_id)

        ctx.log_info(f"查询成功: diagnosis_id={diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录查询成功",
            data=result.model_dump(),
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("查询医生诊断失败", e)
        raise DatabaseException("查询医生诊断记录时发生错误", str(e))


@router.post(
    "/medical-record/{record_id}/confirm", response_model=APIResponse, status_code=200
)
async def confirm_medical_record(
    record_id: int = Path(..., description="就诊记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """确认就诊完成"""
    try:
        doctor = ctx.current_doctor
        ctx.log_info(f"确认就诊: record_id={record_id}, doctor_id={doctor.doctor_id}")

        service = MedicalRecordService(ctx.db, ctx.organization)
        result = await service.confirm_record(record_id, doctor.name)

        ctx.log_info(f"就诊确认成功: record_id={record_id}")
        return APIResponse(
            success=True,
            message="就诊已确认完成",
            data=result,
        )
    except Exception as e:
        if hasattr(e, "message"):
            raise
        ctx.log_error("确认就诊失败", e)
        raise DatabaseException("确认就诊记录时发生错误", str(e))
