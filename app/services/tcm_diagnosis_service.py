"""中医诊断服务"""

import json
import re
import time
from typing import Dict, Any, Optional, AsyncGenerator, List, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionUserMessageParam

from app.core import get_logger
from app.services.openai_client import OpenAIChatCompletion
from app.services.prompt_templates import (
    MEDICAL_RECORD_PROMPT_TEMPLATE,
    TYPE_INFER_PROMPT_TEMPLATE,
    PRESCRIPTION_PROMPT_TEMPLATE,
    EXERCISE_PRESCRIPTION_PROMPT_TEMPLATE,
)

logger = get_logger(__name__)


class DiagnosisStage:
    """诊断阶段常量"""

    MEDICAL_RECORD = "medical_record"
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    EXERCISE_PRESCRIPTION = "exercise_prescription"


class TCMDiagnosisService:
    """中医诊疗服务"""

    def __init__(self, api_key: str, base_url: str, model_name: str = "deepseek-chat"):
        self.llm = OpenAIChatCompletion(api_key, base_url, model_name)
        self.model_name = model_name
        logger.info(f"中医诊疗服务初始化: model={model_name}")

    def _extract_tag_content(self, response: str, tag: str) -> Optional[str]:
        """从响应中提取指定标签的内容"""
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _extract_answer(self, response: str) -> str:
        """提取答案内容"""
        answer = self._extract_tag_content(response, "answer")
        if answer:
            return answer
        logger.warning("未找到<answer>标签，返回完整响应")
        return response.strip()

    def _extract_think(self, response: str) -> Optional[str]:
        """提取思考过程"""
        return self._extract_tag_content(response, "think")

    def _call_llm(self, prompt: str, temperature: float = 0.7) -> tuple[str, float]:
        """调用 LLM 并返回响应和耗时"""
        start_time = time.time()
        response = self.llm.simple_chat(user_message=prompt, temperature=temperature)
        duration = round(time.time() - start_time, 2)
        return response, duration

    def generate_medical_record(
        self,
        transcript: str,
        coze_conversation_log: str,
        diagnosis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从对话转录文本生成病历"""
        try:
            logger.info("开始生成病历")
            prompt = MEDICAL_RECORD_PROMPT_TEMPLATE.format(
                transcript=transcript,
                log_string=coze_conversation_log,
                diagnosis=diagnosis or "未提供预问诊结论",
            )
            response, duration = self._call_llm(prompt, temperature=0.6)
            medical_record = self._extract_answer(response)

            logger.info(f"病历生成完成: {duration}s")
            return {
                "input_transcript": transcript,
                "medical_record": medical_record,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"病历生成失败: {e}")
            return {
                "input_transcript": transcript,
                "medical_record": None,
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def judge_symptom_type(
        self,
        medical_record: str,
        diagnosis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """证型判断"""
        try:
            logger.info("开始证型判断")
            prompt = TYPE_INFER_PROMPT_TEMPLATE.format(
                medical_record=medical_record,
                diagnosis=diagnosis or "未提供预问诊结论",
            )
            response, duration = self._call_llm(prompt, temperature=0.3)
            diagnosis = self._extract_answer(response)
            explanation = self._extract_think(response)

            logger.info(f"证型判断完成: {diagnosis}, {duration}s")
            return {
                "input_medical_record": medical_record,
                "diagnosis": diagnosis,
                "diagnosis_explanation": explanation,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"证型判断失败: {e}")
            return {
                "input_medical_record": medical_record,
                "diagnosis": None,
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def generate_prescription(
        self,
        medical_record: str,
        diagnosis_result: str,
        diagnosis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成处方"""
        try:
            logger.info("开始生成处方")
            prompt = PRESCRIPTION_PROMPT_TEMPLATE.format(
                medical_record=medical_record,
                diagnosis_result=diagnosis_result,
                diagnosis=diagnosis or "未提供预问诊结论",
            )
            response, duration = self._call_llm(prompt, temperature=0.3)
            prescription = self._extract_answer(response)

            logger.info(f"处方生成完成: {duration}s")
            return {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "prescription": prescription,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"处方生成失败: {e}")
            return {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "prescription": None,
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def generate_exercise_prescription(
        self,
        medical_record: str,
        diagnosis_result: str,
        height: Optional[float] = None,
        weight: Optional[float] = None,
        diagnosis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成运动处方"""
        try:
            logger.info("开始生成运动处方")

            bmi = "未提供"
            if height and weight:
                height_m = height / 100
                bmi = f"{weight / (height_m**2):.2f}"

            prompt = EXERCISE_PRESCRIPTION_PROMPT_TEMPLATE.format(
                medical_record=medical_record,
                diagnosis_result=diagnosis_result,
                diagnosis=diagnosis or "未提供预问诊结论",
                height=height or "未提供",
                weight=weight or "未提供",
                bmi=bmi,
            )
            response, duration = self._call_llm(prompt, temperature=0.5)
            exercise_prescription = self._extract_answer(response)

            logger.info(f"运动处方生成完成: {duration}s")
            return {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "exercise_prescription": exercise_prescription,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"运动处方生成失败: {e}")
            return {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "exercise_prescription": None,
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def process_complete_diagnosis(
        self,
        transcript: str,
        height: Optional[float] = None,
        weight: Optional[float] = None,
        coze_conversation_log: Optional[str] = None,
        sanzhen_diagnosis: Optional[str] = None,
    ) -> Dict[str, Any]:
        """处理完整的诊断流程"""
        logger.info("开始完整诊断流程")
        start_time = time.time()
        pre_diagnosis = sanzhen_diagnosis or "未提供预问诊结论"

        # 1. 生成病历
        logger.info("[1/4] 生成病历")
        medical_result = self.generate_medical_record(
            transcript,
            coze_conversation_log or "",
            diagnosis=pre_diagnosis,
        )
        if medical_result["status"] != "success":
            logger.error("病历生成失败")
            return self._build_failed_result(
                transcript, medical_result, "medical_record_generation_failed"
            )

        medical_record = medical_result["medical_record"]

        # 2. 证型判断
        logger.info("[2/4] 证型判断")
        diagnosis_result = self.judge_symptom_type(
            medical_record,
            diagnosis=pre_diagnosis,
        )
        if diagnosis_result["status"] != "success":
            logger.error("证型判断失败")
            return {
                "input_transcript": transcript,
                "medical_record_result": medical_result,
                "diagnosis_result": diagnosis_result,
                "prescription_result": {
                    "status": "skipped",
                    "reason": "diagnosis_failed",
                },
                "exercise_prescription_result": {
                    "status": "skipped",
                    "reason": "diagnosis_failed",
                },
                "overall_status": "failed",
                "timestamp": time.time(),
            }

        diagnosis = diagnosis_result["diagnosis"]

        # 3. 处方生成
        logger.info("[3/4] 处方生成")
        prescription_result = self.generate_prescription(
            medical_record,
            diagnosis,
            diagnosis=pre_diagnosis,
        )

        # 4. 运动处方生成
        logger.info("[4/4] 运动处方生成")
        exercise_result = self.generate_exercise_prescription(
            medical_record,
            diagnosis,
            height,
            weight,
            diagnosis=pre_diagnosis,
        )

        total_duration = round(time.time() - start_time, 2)
        overall_status = self._determine_overall_status(
            prescription_result, exercise_result
        )

        logger.info(f"完整诊断流程完成: {total_duration}s, 状态={overall_status}")
        return {
            "input_transcript": transcript,
            "medical_record_result": medical_result,
            "diagnosis_result": diagnosis_result,
            "prescription_result": prescription_result,
            "exercise_prescription_result": exercise_result,
            "overall_status": overall_status,
            "total_processing_time": total_duration,
            "timestamp": time.time(),
        }

    def _build_failed_result(
        self, transcript: str, medical_result: Dict, reason: str
    ) -> Dict[str, Any]:
        """构建失败结果"""
        return {
            "input_transcript": transcript,
            "medical_record_result": medical_result,
            "diagnosis_result": {"status": "skipped", "reason": reason},
            "prescription_result": {"status": "skipped", "reason": reason},
            "exercise_prescription_result": {"status": "skipped", "reason": reason},
            "overall_status": "failed",
            "timestamp": time.time(),
        }

    def _determine_overall_status(
        self, prescription_result: Dict, exercise_result: Dict
    ) -> str:
        """确定整体状态"""
        if (
            prescription_result["status"] == "success"
            and exercise_result["status"] == "success"
        ):
            return "success"
        elif prescription_result["status"] == "success":
            return "partial_success"
        return "failed"

    async def _async_stream_llm(
        self, prompt: str, temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """异步流式调用 LLM"""
        messages: List[ChatCompletionMessageParam] = [
            cast(ChatCompletionUserMessageParam, {"role": "user", "content": prompt})
        ]
        async for chunk in self.llm.async_stream_chat(
            messages=messages, temperature=temperature
        ):
            yield chunk

    async def stream_complete_diagnosis(
        self,
        transcript: str,
        height: Optional[float] = None,
        weight: Optional[float] = None,
        coze_conversation_log: Optional[str] = None,
        sanzhen_diagnosis: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式处理完整的诊断流程

        Args:
            transcript: 医患对话转录文本
            height: 患者身高(cm)
            weight: 患者体重(kg)
            coze_conversation_log: AI预问诊对话信息
            sanzhen_diagnosis: 预问诊结论（来自sanzhen_result的diagnosis_result），包含四诊信息和初步建议
        """
        logger.info("开始流式诊断流程")
        start_time = time.time()

        medical_record = ""
        diagnosis = ""
        diagnosis_explanation: Optional[str] = None
        prescription = ""
        exercise_prescription = ""

        # 预问诊结论，如果未提供则使用默认值
        pre_diagnosis = sanzhen_diagnosis or "未提供预问诊结论"

        def create_sse_event(event_type: str, data: Dict[str, Any]) -> str:
            return (
                f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            )

        try:
            # 阶段1: 生成病历
            yield create_sse_event(
                "stage_start",
                {
                    "stage": DiagnosisStage.MEDICAL_RECORD,
                    "stage_name": "生成病历",
                    "step": "1/4",
                },
            )

            prompt = MEDICAL_RECORD_PROMPT_TEMPLATE.format(
                transcript=transcript,
                log_string=coze_conversation_log or "",
                diagnosis=pre_diagnosis,
            )
            full_response = ""
            async for chunk in self._async_stream_llm(prompt, temperature=0.6):
                full_response += chunk
                yield create_sse_event(
                    "content", {"stage": DiagnosisStage.MEDICAL_RECORD, "chunk": chunk}
                )

            medical_record = self._extract_answer(full_response)
            yield create_sse_event(
                "stage_complete",
                {
                    "stage": DiagnosisStage.MEDICAL_RECORD,
                    "stage_name": "生成病历",
                    "result": medical_record,
                },
            )

            if not medical_record:
                yield create_sse_event(
                    "error",
                    {"stage": DiagnosisStage.MEDICAL_RECORD, "message": "病历生成失败"},
                )
                return

            # 阶段2: 证型判断
            yield create_sse_event(
                "stage_start",
                {
                    "stage": DiagnosisStage.DIAGNOSIS,
                    "stage_name": "证型判断",
                    "step": "2/4",
                },
            )

            prompt = TYPE_INFER_PROMPT_TEMPLATE.format(
                medical_record=medical_record, diagnosis=pre_diagnosis
            )
            full_response = ""
            async for chunk in self._async_stream_llm(prompt, temperature=0.3):
                full_response += chunk
                yield create_sse_event(
                    "content", {"stage": DiagnosisStage.DIAGNOSIS, "chunk": chunk}
                )

            diagnosis = self._extract_answer(full_response)
            diagnosis_explanation = self._extract_think(full_response)
            yield create_sse_event(
                "stage_complete",
                {
                    "stage": DiagnosisStage.DIAGNOSIS,
                    "stage_name": "证型判断",
                    "result": diagnosis,
                    "explanation": diagnosis_explanation,
                },
            )

            if not diagnosis:
                yield create_sse_event(
                    "error",
                    {"stage": DiagnosisStage.DIAGNOSIS, "message": "证型判断失败"},
                )
                return

            # 阶段3: 处方生成
            yield create_sse_event(
                "stage_start",
                {
                    "stage": DiagnosisStage.PRESCRIPTION,
                    "stage_name": "处方生成",
                    "step": "3/4",
                },
            )

            prompt = PRESCRIPTION_PROMPT_TEMPLATE.format(
                medical_record=medical_record,
                diagnosis_result=diagnosis,
                diagnosis=pre_diagnosis,
            )
            full_response = ""
            async for chunk in self._async_stream_llm(prompt, temperature=0.3):
                full_response += chunk
                yield create_sse_event(
                    "content", {"stage": DiagnosisStage.PRESCRIPTION, "chunk": chunk}
                )

            prescription = self._extract_answer(full_response)
            yield create_sse_event(
                "stage_complete",
                {
                    "stage": DiagnosisStage.PRESCRIPTION,
                    "stage_name": "处方生成",
                    "result": prescription,
                },
            )

            # 阶段4: 运动处方生成
            yield create_sse_event(
                "stage_start",
                {
                    "stage": DiagnosisStage.EXERCISE_PRESCRIPTION,
                    "stage_name": "运动处方生成",
                    "step": "4/4",
                },
            )

            bmi = "未提供"
            if height and weight:
                bmi = f"{weight / ((height / 100) ** 2):.2f}"

            prompt = EXERCISE_PRESCRIPTION_PROMPT_TEMPLATE.format(
                medical_record=medical_record,
                diagnosis_result=diagnosis,
                diagnosis=pre_diagnosis,
                height=height or "未提供",
                weight=weight or "未提供",
                bmi=bmi,
            )
            full_response = ""
            async for chunk in self._async_stream_llm(prompt, temperature=0.5):
                full_response += chunk
                yield create_sse_event(
                    "content",
                    {"stage": DiagnosisStage.EXERCISE_PRESCRIPTION, "chunk": chunk},
                )

            exercise_prescription = self._extract_answer(full_response)
            yield create_sse_event(
                "stage_complete",
                {
                    "stage": DiagnosisStage.EXERCISE_PRESCRIPTION,
                    "stage_name": "运动处方生成",
                    "result": exercise_prescription,
                },
            )

            # 完成
            total_duration = round(time.time() - start_time, 2)
            logger.info(f"流式诊断流程完成: {total_duration}s")

            yield create_sse_event(
                "complete",
                {
                    "status": "success",
                    "total_processing_time": total_duration,
                    "formatted_medical_record": medical_record,
                    "type_inference": diagnosis,
                    "diagnosis_explanation": diagnosis_explanation,
                    "prescription": prescription,
                    "exercise_prescription": exercise_prescription,
                },
            )

        except Exception as e:
            logger.error(f"流式诊断出错: {e}")
            yield create_sse_event("error", {"message": f"诊断过程出错: {str(e)}"})
