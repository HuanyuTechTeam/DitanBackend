"""病人数据和诊断相关 API 路由"""
import json

from fastapi import APIRouter, Depends, Query, Path
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import RequestContext, get_request_context, get_auth_context
from app.core import get_settings
from app.core.exceptions import ValidationException, DuplicateException, DatabaseException, NotFoundException
from app.models import (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
    AIDiagnosisRecord,
    DoctorDiagnosisRecord,
    DiagnosisType,
)
from app.schemas import APIResponse
from app.schemas.patient import (
    PatientResponse,
    PatientQueryResponse,
    MedicalRecordCreate,
    MedicalRecordResponse,
    MedicalRecordListItem,
    PreDiagnosisResponse,
    CompleteMedicalRecordResponse,
    AIDiagnosisCreate,
    AIDiagnosisResponse,
    DoctorDiagnosisCreate,
    DoctorDiagnosisUpdate,
    DoctorDiagnosisResponse,
)
from app.services.tcm_diagnosis_service import TCMDiagnosisService

router = APIRouter()
settings = get_settings()


def get_tcm_service() -> TCMDiagnosisService:
    """获取中医诊断服务实例"""
    return TCMDiagnosisService(
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_BASE_URL,
        model_name=settings.AI_MODEL_NAME,
    )


@router.get("/patient/query", response_model=APIResponse, status_code=200)
async def query_patient_by_phone(
    phone: str = Query(..., description="患者手机号"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """通过手机号查询患者信息和历史就诊记录"""
    try:
        ctx.log_info(f"查询患者: phone={phone}")

        result = await ctx.db.execute(select(Patient).where(Patient.phone == phone))
        patient = result.scalar_one_or_none()

        if not patient:
            raise NotFoundException(f"未找到手机号为 {phone} 的患者")

        records_result = await ctx.db.execute(
            select(PatientMedicalRecord)
            .where(PatientMedicalRecord.patient_id == patient.patient_id)
            .order_by(PatientMedicalRecord.created_at.desc())
        )
        medical_records = records_result.scalars().all()

        medical_records_list = [
            MedicalRecordListItem(
                record_id=record.record_id,
                uuid=record.uuid,
                status=record.status,
                created_at=record.created_at,
                patient_name=patient.name,
                patient_phone=patient.phone,
            )
            for record in medical_records
        ]

        ctx.log_info(f"查询成功: patient_id={patient.patient_id}, records={len(medical_records_list)}")
        return APIResponse(
            success=True,
            message="患者信息查询成功",
            data=PatientQueryResponse(
                patient=PatientResponse.model_validate(patient),
                medical_records=medical_records_list,
            ).model_dump(),
        )

    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("查询患者信息失败", e)
        raise DatabaseException("查询患者信息时发生错误", str(e))


@router.post("/medical-record", response_model=APIResponse, status_code=201)
async def create_medical_record(
    record_data: MedicalRecordCreate,
    ctx: RequestContext = Depends(get_request_context),
):
    """创建就诊记录（预就诊系统调用）"""
    try:
        ctx.log_info(f"创建就诊记录: uuid={record_data.uuid}")

        result = await ctx.db.execute(select(Patient).where(Patient.phone == record_data.patient_phone))
        patient = result.scalar_one_or_none()

        if not patient:
            if not record_data.patient_info:
                raise ValidationException("患者不存在，请提供患者信息", f"手机号 {record_data.patient_phone} 未注册")

            patient = Patient(
                name=record_data.patient_info.name,
                sex=record_data.patient_info.sex,
                birthday=record_data.patient_info.birthday,
                phone=record_data.patient_info.phone,
            )
            ctx.db.add(patient)
            await ctx.db.flush()
            ctx.log_info(f"创建新患者: patient_id={patient.patient_id}")

        result = await ctx.db.execute(
            select(PatientMedicalRecord).where(PatientMedicalRecord.uuid == record_data.uuid)
        )
        if result.scalar_one_or_none():
            raise DuplicateException(f"就诊记录 UUID {record_data.uuid} 已存在")

        medical_record = PatientMedicalRecord(
            patient_id=patient.patient_id,
            uuid=record_data.uuid,
            status="pending",
        )
        ctx.db.add(medical_record)
        await ctx.db.flush()

        pre_diagnosis = PreDiagnosisRecord(
            record_id=medical_record.record_id,
            uuid=record_data.pre_diagnosis.uuid,
            height=record_data.pre_diagnosis.height,
            weight=record_data.pre_diagnosis.weight,
            coze_conversation_log=record_data.pre_diagnosis.coze_conversation_log,
        )
        ctx.db.add(pre_diagnosis)
        await ctx.db.flush()

        if record_data.pre_diagnosis.sanzhen_analysis:
            sanzhen = SanzhenAnalysisResult(
                pre_diagnosis_id=pre_diagnosis.pre_diagnosis_id,
                face=record_data.pre_diagnosis.sanzhen_analysis.face,
                face_image_url=record_data.pre_diagnosis.sanzhen_analysis.face_image_url,
                tongue_front=record_data.pre_diagnosis.sanzhen_analysis.tongue_front,
                tongue_front_image_url=record_data.pre_diagnosis.sanzhen_analysis.tongue_front_image_url,
                tongue_bottom=record_data.pre_diagnosis.sanzhen_analysis.tongue_bottom,
                tongue_bottom_image_url=record_data.pre_diagnosis.sanzhen_analysis.tongue_bottom_image_url,
                pulse=record_data.pre_diagnosis.sanzhen_analysis.pulse,
                diagnosis_result=record_data.pre_diagnosis.sanzhen_analysis.diagnosis_result,
            )
            ctx.db.add(sanzhen)

        await ctx.db.commit()
        await ctx.db.refresh(medical_record, ["patient", "pre_diagnosis"])
        if medical_record.pre_diagnosis:
            await ctx.db.refresh(medical_record.pre_diagnosis, ["sanzhen_result"])

        ctx.log_info(f"创建成功: record_id={medical_record.record_id}")
        return APIResponse(
            success=True,
            message="就诊记录创建成功",
            data=MedicalRecordResponse.model_validate(medical_record).model_dump(),
        )

    except (DuplicateException, ValidationException):
        raise
    except Exception as e:
        ctx.log_error("创建就诊记录失败", e)
        raise DatabaseException("创建就诊记录时发生错误", str(e))


@router.get("/medical-record/{record_id}", response_model=APIResponse, status_code=200)
async def get_medical_record(
    record_id: int = Path(..., description="就诊记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """获取完整的就诊记录信息"""
    try:
        ctx.log_info(f"查询就诊记录: record_id={record_id}")

        # 加载医疗记录基本信息（不加载多态诊断记录，避免懒加载问题）
        result = await ctx.db.execute(
            select(PatientMedicalRecord)
            .options(
                selectinload(PatientMedicalRecord.patient),
                selectinload(PatientMedicalRecord.pre_diagnosis).selectinload(PreDiagnosisRecord.sanzhen_result),
            )
            .where(PatientMedicalRecord.record_id == record_id)
        )
        medical_record = result.scalar_one_or_none()

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        # 分别查询不同类型的诊断记录，避免多态继承的懒加载问题
        ai_diagnoses_result = await ctx.db.execute(
            select(AIDiagnosisRecord).where(AIDiagnosisRecord.record_id == record_id)
        )
        ai_diagnoses = ai_diagnoses_result.scalars().all()

        doctor_diagnoses_result = await ctx.db.execute(
            select(DoctorDiagnosisRecord)
            .options(selectinload(DoctorDiagnosisRecord.doctor))
            .where(DoctorDiagnosisRecord.record_id == record_id)
        )
        doctor_diagnoses = doctor_diagnoses_result.scalars().all()

        # 构建诊断列表
        diagnoses_list = []
        for d in ai_diagnoses:
            diagnoses_list.append(AIDiagnosisResponse.model_validate(d).model_dump())
        for d in doctor_diagnoses:
            diagnoses_list.append(DoctorDiagnosisResponse(
                diagnosis_id=d.diagnosis_id,
                record_id=d.record_id,
                type=d.type,
                doctor_id=d.doctor_id,
                doctor_name=d.doctor.name if d.doctor else None,
                formatted_medical_record=d.formatted_medical_record,
                type_inference=d.type_inference,
                treatment=d.treatment,
                prescription=d.prescription,
                exercise_prescription=d.exercise_prescription,
                comments=d.comments,
                created_at=d.created_at,
                updated_at=d.updated_at,
            ).model_dump())

        # 按创建时间排序
        diagnoses_list.sort(key=lambda x: x["created_at"])

        ctx.log_info(f"查询成功: record_id={record_id}")
        return APIResponse(
            success=True,
            message="就诊记录查询成功",
            data={
                "record_id": medical_record.record_id,
                "uuid": medical_record.uuid,
                "status": medical_record.status,
                "created_at": medical_record.created_at.isoformat(),
                "updated_at": medical_record.updated_at.isoformat(),
                "patient": PatientResponse.model_validate(medical_record.patient).model_dump(),
                "pre_diagnosis": PreDiagnosisResponse.model_validate(medical_record.pre_diagnosis).model_dump() if medical_record.pre_diagnosis else None,
                "diagnoses": diagnoses_list,
            },
        )

    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("查询就诊记录失败", e)
        raise DatabaseException("查询就诊记录时发生错误", str(e))


@router.post("/medical-record/{record_id}/ai-diagnosis", response_model=APIResponse, status_code=201)
async def create_ai_diagnosis(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: AIDiagnosisCreate = ...,
    ctx: RequestContext = Depends(get_auth_context),
):
    """为就诊记录生成AI诊断"""
    try:
        ctx.log_info(f"生成AI诊断: record_id={record_id}")

        result = await ctx.db.execute(
            select(PatientMedicalRecord)
            .options(selectinload(PatientMedicalRecord.pre_diagnosis))
            .where(PatientMedicalRecord.record_id == record_id)
        )
        medical_record = result.scalar_one_or_none()

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        height, weight, coze_conversation_log = None, None, None
        if medical_record.pre_diagnosis:
            height = medical_record.pre_diagnosis.height
            weight = medical_record.pre_diagnosis.weight
            coze_conversation_log = medical_record.pre_diagnosis.coze_conversation_log

        tcm_service = get_tcm_service()
        diagnosis_result = tcm_service.process_complete_diagnosis(
            transcript=diagnosis_data.asr_text,
            height=height,
            weight=weight,
            coze_conversation_log=coze_conversation_log,
        )

        if diagnosis_result["overall_status"] == "failed":
            raise DatabaseException("AI诊断失败", diagnosis_result.get("error_message", "未知错误"))

        ai_diagnosis = AIDiagnosisRecord(
            record_id=record_id,
            formatted_medical_record=diagnosis_result["medical_record_result"].get("medical_record"),
            type_inference=diagnosis_result["diagnosis_result"].get("diagnosis"),
            prescription=diagnosis_result["prescription_result"].get("prescription"),
            exercise_prescription=diagnosis_result["exercise_prescription_result"].get("exercise_prescription"),
            diagnosis_explanation=diagnosis_result["diagnosis_result"].get("diagnosis_explanation"),
            response_time=diagnosis_result.get("total_processing_time"),
            model_name=settings.AI_MODEL_NAME,
        )

        ctx.db.add(ai_diagnosis)
        medical_record.status = "completed"
        await ctx.db.commit()
        await ctx.db.refresh(ai_diagnosis)

        ctx.log_info(f"AI诊断完成: diagnosis_id={ai_diagnosis.diagnosis_id}")
        return APIResponse(
            success=True,
            message="AI诊断完成",
            data=AIDiagnosisResponse.model_validate(ai_diagnosis).model_dump(),
        )

    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("生成AI诊断失败", e)
        raise DatabaseException("生成AI诊断时发生错误", str(e))


@router.post("/medical-record/{record_id}/ai-diagnosis/stream", status_code=200)
async def create_ai_diagnosis_stream(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: AIDiagnosisCreate = ...,
    ctx: RequestContext = Depends(get_auth_context),
):
    """为就诊记录生成AI诊断（流式返回）"""
    try:
        ctx.log_info(f"流式AI诊断: record_id={record_id}")

        result = await ctx.db.execute(
            select(PatientMedicalRecord)
            .options(
                selectinload(PatientMedicalRecord.pre_diagnosis)
                .selectinload(PreDiagnosisRecord.sanzhen_result)
            )
            .where(PatientMedicalRecord.record_id == record_id)
        )
        medical_record = result.scalar_one_or_none()

        if not medical_record:
            ctx.log_error(f"未找到就诊记录 ID: {record_id}")
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        height, weight, coze_conversation_log, sanzhen_diagnosis = None, None, None, None
        if medical_record.pre_diagnosis:
            height = medical_record.pre_diagnosis.height
            weight = medical_record.pre_diagnosis.weight
            coze_conversation_log = medical_record.pre_diagnosis.coze_conversation_log
            if medical_record.pre_diagnosis.sanzhen_result:
                sanzhen_diagnosis = medical_record.pre_diagnosis.sanzhen_result.diagnosis_result

        diagnosis_result_holder = {"data": None}

        async def generate_stream():
            tcm_service = get_tcm_service()
            try:
                async for event_data in tcm_service.stream_complete_diagnosis(
                    transcript=diagnosis_data.asr_text,
                    height=height,
                    weight=weight,
                    coze_conversation_log=coze_conversation_log,
                    sanzhen_diagnosis=sanzhen_diagnosis,
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

            if diagnosis_result_holder["data"] and diagnosis_result_holder["data"].get("status") == "success":
                try:
                    final_result = diagnosis_result_holder["data"]
                    ai_diagnosis = AIDiagnosisRecord(
                        record_id=record_id,
                        formatted_medical_record=final_result.get("formatted_medical_record"),
                        type_inference=final_result.get("type_inference"),
                        prescription=final_result.get("prescription"),
                        exercise_prescription=final_result.get("exercise_prescription"),
                        diagnosis_explanation=final_result.get("diagnosis_explanation"),
                        response_time=final_result.get("total_processing_time"),
                        model_name=settings.AI_MODEL_NAME,
                    )

                    ctx.db.add(ai_diagnosis)
                    medical_record.status = "completed"
                    await ctx.db.commit()
                    await ctx.db.refresh(ai_diagnosis)

                    ctx.log_info(f"流式AI诊断保存成功: diagnosis_id={ai_diagnosis.diagnosis_id}")
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

    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("流式AI诊断失败", e)
        raise DatabaseException("生成流式AI诊断时发生错误", str(e))


@router.post("/medical-record/{record_id}/doctor-diagnosis", response_model=APIResponse, status_code=201)
async def create_doctor_diagnosis(
    record_id: int = Path(..., description="就诊记录ID"),
    diagnosis_data: DoctorDiagnosisCreate = ...,
    ctx: RequestContext = Depends(get_auth_context),
):
    """创建医生诊断记录"""
    try:
        ctx.log_info(f"创建医生诊断: record_id={record_id}, doctor_id={ctx.doctor.doctor_id}")

        result = await ctx.db.execute(
            select(PatientMedicalRecord).where(PatientMedicalRecord.record_id == record_id)
        )
        medical_record = result.scalar_one_or_none()

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        if medical_record.status == "confirmed":
            raise ValidationException("无法创建医生诊断记录", "就诊记录已确认完成，不能再添加新的诊断记录")

        formatted_medical_record = diagnosis_data.formatted_medical_record
        type_inference = diagnosis_data.type_inference
        treatment = diagnosis_data.treatment
        prescription = diagnosis_data.prescription
        exercise_prescription = diagnosis_data.exercise_prescription

        if diagnosis_data.based_on_ai_diagnosis_id:
            ai_result = await ctx.db.execute(
                select(AIDiagnosisRecord).where(
                    AIDiagnosisRecord.diagnosis_id == diagnosis_data.based_on_ai_diagnosis_id,
                    AIDiagnosisRecord.record_id == record_id,
                )
            )
            ai_diagnosis = ai_result.scalar_one_or_none()

            if not ai_diagnosis:
                raise NotFoundException(f"未找到AI诊断记录 ID: {diagnosis_data.based_on_ai_diagnosis_id}")

            formatted_medical_record = formatted_medical_record or ai_diagnosis.formatted_medical_record
            type_inference = type_inference or ai_diagnosis.type_inference
            treatment = treatment or ai_diagnosis.treatment
            prescription = prescription or ai_diagnosis.prescription
            exercise_prescription = exercise_prescription or ai_diagnosis.exercise_prescription

        doctor_diagnosis = DoctorDiagnosisRecord(
            record_id=record_id,
            doctor_id=ctx.doctor.doctor_id,
            formatted_medical_record=formatted_medical_record,
            type_inference=type_inference,
            treatment=treatment,
            prescription=prescription,
            exercise_prescription=exercise_prescription,
            comments=diagnosis_data.comments,
        )

        ctx.db.add(doctor_diagnosis)

        if medical_record.status in ("pending", "completed"):
            medical_record.status = "in_progress"

        await ctx.db.commit()
        await ctx.db.refresh(doctor_diagnosis)

        ctx.log_info(f"医生诊断创建成功: diagnosis_id={doctor_diagnosis.diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录创建成功",
            data=DoctorDiagnosisResponse(
                diagnosis_id=doctor_diagnosis.diagnosis_id,
                record_id=doctor_diagnosis.record_id,
                type=doctor_diagnosis.type,
                doctor_id=doctor_diagnosis.doctor_id,
                doctor_name=ctx.doctor.name,
                formatted_medical_record=doctor_diagnosis.formatted_medical_record,
                type_inference=doctor_diagnosis.type_inference,
                treatment=doctor_diagnosis.treatment,
                prescription=doctor_diagnosis.prescription,
                exercise_prescription=doctor_diagnosis.exercise_prescription,
                comments=doctor_diagnosis.comments,
                created_at=doctor_diagnosis.created_at,
                updated_at=doctor_diagnosis.updated_at,
            ).model_dump(),
        )

    except (NotFoundException, ValidationException):
        raise
    except Exception as e:
        ctx.log_error("创建医生诊断失败", e)
        raise DatabaseException("创建医生诊断记录时发生错误", str(e))


@router.put("/doctor-diagnosis/{diagnosis_id}", response_model=APIResponse, status_code=200)
async def update_doctor_diagnosis(
    diagnosis_id: int = Path(..., description="诊断记录ID"),
    diagnosis_data: DoctorDiagnosisUpdate = ...,
    ctx: RequestContext = Depends(get_auth_context),
):
    """更新医生诊断记录"""
    try:
        ctx.log_info(f"更新医生诊断: diagnosis_id={diagnosis_id}")

        result = await ctx.db.execute(
            select(DoctorDiagnosisRecord)
            .options(selectinload(DoctorDiagnosisRecord.medical_record))
            .where(DoctorDiagnosisRecord.diagnosis_id == diagnosis_id)
        )
        doctor_diagnosis = result.scalar_one_or_none()

        if not doctor_diagnosis:
            raise NotFoundException(f"未找到医生诊断记录 ID: {diagnosis_id}")

        if doctor_diagnosis.doctor_id != ctx.doctor.doctor_id:
            raise ValidationException("无权修改此诊断记录", "只能修改自己创建的诊断记录")

        if doctor_diagnosis.medical_record.status == "confirmed":
            raise ValidationException("无法修改已确认的诊断记录", "就诊记录已确认完成，不能再修改")

        for field, value in diagnosis_data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(doctor_diagnosis, field, value)

        await ctx.db.commit()
        await ctx.db.refresh(doctor_diagnosis)

        ctx.log_info(f"医生诊断更新成功: diagnosis_id={diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录更新成功",
            data=DoctorDiagnosisResponse(
                diagnosis_id=doctor_diagnosis.diagnosis_id,
                record_id=doctor_diagnosis.record_id,
                type=doctor_diagnosis.type,
                doctor_id=doctor_diagnosis.doctor_id,
                doctor_name=ctx.doctor.name,
                formatted_medical_record=doctor_diagnosis.formatted_medical_record,
                type_inference=doctor_diagnosis.type_inference,
                treatment=doctor_diagnosis.treatment,
                prescription=doctor_diagnosis.prescription,
                exercise_prescription=doctor_diagnosis.exercise_prescription,
                comments=doctor_diagnosis.comments,
                created_at=doctor_diagnosis.created_at,
                updated_at=doctor_diagnosis.updated_at,
            ).model_dump(),
        )

    except (NotFoundException, ValidationException):
        raise
    except Exception as e:
        ctx.log_error("更新医生诊断失败", e)
        raise DatabaseException("更新医生诊断记录时发生错误", str(e))


@router.get("/doctor-diagnosis/{diagnosis_id}", response_model=APIResponse, status_code=200)
async def get_doctor_diagnosis(
    diagnosis_id: int = Path(..., description="诊断记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """获取医生诊断记录详情"""
    try:
        ctx.log_info(f"查询医生诊断: diagnosis_id={diagnosis_id}")

        result = await ctx.db.execute(
            select(DoctorDiagnosisRecord)
            .options(selectinload(DoctorDiagnosisRecord.doctor))
            .where(DoctorDiagnosisRecord.diagnosis_id == diagnosis_id)
        )
        doctor_diagnosis = result.scalar_one_or_none()

        if not doctor_diagnosis:
            raise NotFoundException(f"未找到医生诊断记录 ID: {diagnosis_id}")

        ctx.log_info(f"查询成功: diagnosis_id={diagnosis_id}")
        return APIResponse(
            success=True,
            message="医生诊断记录查询成功",
            data=DoctorDiagnosisResponse(
                diagnosis_id=doctor_diagnosis.diagnosis_id,
                record_id=doctor_diagnosis.record_id,
                type=doctor_diagnosis.type,
                doctor_id=doctor_diagnosis.doctor_id,
                doctor_name=doctor_diagnosis.doctor.name if doctor_diagnosis.doctor else None,
                formatted_medical_record=doctor_diagnosis.formatted_medical_record,
                type_inference=doctor_diagnosis.type_inference,
                treatment=doctor_diagnosis.treatment,
                prescription=doctor_diagnosis.prescription,
                exercise_prescription=doctor_diagnosis.exercise_prescription,
                comments=doctor_diagnosis.comments,
                created_at=doctor_diagnosis.created_at,
                updated_at=doctor_diagnosis.updated_at,
            ).model_dump(),
        )

    except NotFoundException:
        raise
    except Exception as e:
        ctx.log_error("查询医生诊断失败", e)
        raise DatabaseException("查询医生诊断记录时发生错误", str(e))


@router.post("/medical-record/{record_id}/confirm", response_model=APIResponse, status_code=200)
async def confirm_medical_record(
    record_id: int = Path(..., description="就诊记录ID"),
    ctx: RequestContext = Depends(get_auth_context),
):
    """确认就诊完成"""
    try:
        ctx.log_info(f"确认就诊: record_id={record_id}, doctor_id={ctx.doctor.doctor_id}")

        result = await ctx.db.execute(
            select(PatientMedicalRecord)
            .options(selectinload(PatientMedicalRecord.diagnoses))
            .where(PatientMedicalRecord.record_id == record_id)
        )
        medical_record = result.scalar_one_or_none()

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        if medical_record.status == "confirmed":
            raise ValidationException("就诊记录已确认", "此就诊记录已经确认完成，无需重复确认")

        has_doctor_diagnosis = any(d.type == DiagnosisType.DOCTOR_DIAGNOSIS for d in medical_record.diagnoses)
        if not has_doctor_diagnosis:
            raise ValidationException("无法确认就诊", "请先创建医生诊断记录后再确认")

        medical_record.status = "confirmed"
        await ctx.db.commit()
        await ctx.db.refresh(medical_record)

        ctx.log_info(f"就诊确认成功: record_id={record_id}")
        return APIResponse(
            success=True,
            message="就诊已确认完成",
            data={
                "record_id": medical_record.record_id,
                "status": medical_record.status,
                "confirmed_by": ctx.doctor.name,
                "confirmed_at": medical_record.updated_at.isoformat(),
            },
        )

    except (NotFoundException, ValidationException):
        raise
    except Exception as e:
        ctx.log_error("确认就诊失败", e)
        raise DatabaseException("确认就诊记录时发生错误", str(e))
