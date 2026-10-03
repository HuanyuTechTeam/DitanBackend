"""API 路由汇总"""

from fastapi import APIRouter

from app.api.doctor import router as doctor_router
from app.api.patient import router as patient_router
from app.api.chat import router as chat_router
from app.api.consultation import router as consultation_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(patient_router, tags=["患者管理"])
api_v1_router.include_router(doctor_router, prefix="/doctor", tags=["医生管理"])
api_v1_router.include_router(chat_router, prefix="/chat", tags=["AI聊天"])
api_v1_router.include_router(
    consultation_router, prefix="/consultations", tags=["问诊"]
)
