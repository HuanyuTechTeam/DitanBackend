import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, cast

from dotenv import load_dotenv
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionUserMessageParam

from openai_chat import OpenAIChatCompletion
from prompt_template import (
    MEDICAL_RECORD_PROMPT_TEMPLATE,
    TYPE_INFER_PROMPT_TEMPLATE,
    PRESCRIPTION_PROMPT_TEMPLATE,
)


# CLI美观输出工具类
class CLIFormatter:
    """CLI格式化工具类，提供美观的控制台输出"""

    # 颜色定义
    COLORS = {
        "RED": "\033[91m",
        "GREEN": "\033[92m",
        "YELLOW": "\033[93m",
        "BLUE": "\033[94m",
        "MAGENTA": "\033[95m",
        "CYAN": "\033[96m",
        "WHITE": "\033[97m",
        "BOLD": "\033[1m",
        "UNDERLINE": "\033[4m",
        "END": "\033[0m",
    }

    @classmethod
    def colored_text(cls, text: str, color: str) -> str:
        """返回带颜色的文本"""
        return f"{cls.COLORS.get(color, '')}{text}{cls.COLORS['END']}"

    @classmethod
    def print_section_header(cls, title: str, width: int = 60):
        """打印章节标题"""
        border = "=" * width
        print(f"\n{cls.colored_text(border, 'CYAN')}")
        print(f"{cls.colored_text(title.center(width), 'BOLD')}")
        print(f"{cls.colored_text(border, 'CYAN')}")

    @classmethod
    def print_step(cls, step_num: int, total_steps: int, title: str):
        """打印步骤信息"""
        step_info = f"步骤 {step_num}/{total_steps}: {title}"
        print(
            f"\n{cls.colored_text('▶', 'GREEN')} {cls.colored_text(step_info, 'BOLD')}"
        )

    @classmethod
    def print_status(cls, status: str, message: str, duration: Optional[float] = None):
        """打印状态信息"""
        if status == "成功":
            icon = cls.colored_text("✓", "GREEN")
        elif status == "错误":
            icon = cls.colored_text("✗", "RED")
        elif status == "进行中":
            icon = cls.colored_text("⚡", "YELLOW")
        else:
            icon = cls.colored_text("ℹ", "BLUE")

        duration_str = f" [耗时: {duration:.2f}s]" if duration else ""
        print(f"{icon} {message}{cls.colored_text(duration_str, 'MAGENTA')}")

    @classmethod
    def print_progress(cls, current: int, total: int, prefix: str = "进度"):
        """打印进度信息"""
        percentage = (current / total) * 100
        progress_bar = "█" * int(percentage // 5) + "░" * (20 - int(percentage // 5))
        print(
            f"\r{cls.colored_text(prefix, 'BLUE')}: [{cls.colored_text(progress_bar, 'GREEN')}] {current}/{total} ({percentage:.1f}%)",
            end="",
            flush=True,
        )
        if current == total:
            print()  # 换行

    @classmethod
    def print_streaming_content(cls, content: str, prefix: str = ""):
        """打印流式内容"""
        if prefix:
            print(f"{cls.colored_text(prefix, 'CYAN')}: ", end="")
        print(content, end="", flush=True)


class TCMDiagnosisSystem:
    """
    中医诊疗系统
    整合病历生成、证型判断和处方生成的完整管道
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str = "deepseek-chat",
        max_workers: int = 5,
        verbose: bool = False,
    ):
        """
        初始化中医诊疗系统

        Args:
            api_key (str): OpenAI API密钥
            base_url (str): API基础URL
            model_name (str): 模型名称
            max_workers (int): 最大并发工作线程数，默认为5
            verbose (bool): 是否启用详细输出模式（流式输出）
        """
        self.llm = OpenAIChatCompletion(api_key, base_url, model_name)
        self.max_workers = max_workers
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.verbose = verbose
        self.cli = CLIFormatter()

        init_msg = "中医诊疗系统初始化成功"
        if verbose:
            init_msg += " (详细模式已启用)"
        self.cli.print_status("成功", init_msg)

    def extract_answer_from_response(self, response: str) -> str:
        """
        从LLM响应中提取答案

        Args:
            response (str): LLM的完整响应

        Returns:
            str: 提取的答案内容
        """
        # 使用正则表达式提取<answer>标签中的内容
        answer_pattern = r"<answer>(.*?)</answer>"
        match = re.search(answer_pattern, response, re.DOTALL | re.IGNORECASE)

        if match:
            answer = match.group(1).strip()
            return answer
        else:
            # 如果没有找到answer标签，返回整个响应
            if self.verbose:
                self.cli.print_status("错误", "未找到<answer>标签，返回完整响应")
            return response.strip()

    def generate_medical_record_from_transcript(
        self, transcript: str
    ) -> Dict[str, Any]:
        """
        从对话转录文本生成病历

        Args:
            transcript (str): 对话转录文本

        Returns:
            Dict[str, Any]: 包含病历内容和状态的字典
        """
        try:
            # 构建最终的prompt
            final_prompt = MEDICAL_RECORD_PROMPT_TEMPLATE.format(transcript=transcript)

            # 调用LLM生成病历
            start_time = time.time()
            if self.verbose:
                self.cli.print_status("进行中", "正在生成病历...")
                print(f"{self.cli.colored_text('AI输出', 'CYAN')}: ", end="")
            else:
                print("正在生成病历...")

            messages: List[ChatCompletionMessageParam] = [
                cast(
                    ChatCompletionUserMessageParam,
                    {"role": "user", "content": final_prompt},
                )
            ]

            medical_record = ""
            for chunk in self.llm.stream_chat(messages=messages, temperature=0.6):
                if self.verbose:
                    print(chunk, end="", flush=True)
                medical_record += chunk

            end_time = time.time()
            duration = round(end_time - start_time, 2)

            # 提取答案
            extracted_medical_record = self.extract_answer_from_response(medical_record)

            if self.verbose:
                print()  # 换行
                self.cli.print_status("成功", "病历生成完成", duration)
            else:
                print(f"\n病历生成完成 [耗时: {duration}s]")

            return {
                "input_transcript": transcript,
                "medical_record": extracted_medical_record,
                "llm_response": medical_record,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }

        except Exception as e:
            error_msg = f"病历生成出错: {str(e)}"
            self.cli.print_status("错误", error_msg)
            return {
                "input_transcript": transcript,
                "medical_record": "Generation failed",
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def judge_symptom_type(self, medical_record: str) -> Dict[str, Any]:
        """
        对病历进行证型判断

        Args:
            medical_record (str): 格式化的病历文本

        Returns:
            Dict[str, Any]: 包含证型判断结果的字典
        """
        try:
            # 使用模板格式化提示词
            prompt = TYPE_INFER_PROMPT_TEMPLATE.format(medical_record=medical_record)

            # 调用LLM进行判断
            start_time = time.time()
            if self.verbose:
                self.cli.print_status("进行中", "正在进行证型判断...")
                print(f"{self.cli.colored_text('AI输出', 'CYAN')}: ", end="")

                # 使用流式输出
                messages: List[ChatCompletionMessageParam] = [
                    cast(
                        ChatCompletionUserMessageParam,
                        {"role": "user", "content": prompt},
                    )
                ]

                response = ""
                for chunk in self.llm.stream_chat(messages=messages, temperature=0.3):
                    print(chunk, end="", flush=True)
                    response += chunk
                print()  # 换行
            else:
                print("正在进行证型判断...")
                response = self.llm.simple_chat(prompt)

            end_time = time.time()
            duration = round(end_time - start_time, 2)

            # 提取答案
            diagnosis_result = self.extract_answer_from_response(response)

            result = {
                "input_medical_record": medical_record,
                "diagnosis": diagnosis_result,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }

            if self.verbose:
                self.cli.print_status(
                    "成功", f"证型判断完成: {diagnosis_result}", duration
                )
            else:
                print(f"证型判断完成 [耗时: {duration}s]: {diagnosis_result}")

            return result

        except Exception as e:
            error_msg = f"证型判断出错: {str(e)}"
            self.cli.print_status("错误", error_msg)
            return {
                "input_medical_record": medical_record,
                "diagnosis": "Diagnosis failed",
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def generate_prescription(
        self, medical_record: str, diagnosis_result: str
    ) -> Dict[str, Any]:
        """
        根据病历和证型判断结果生成处方

        Args:
            medical_record (str): 格式化的病历文本
            diagnosis_result (str): 证型判断结果

        Returns:
            Dict[str, Any]: 包含处方结果的字典
        """
        try:
            # 使用模板格式化提示词
            prompt = PRESCRIPTION_PROMPT_TEMPLATE.format(
                medical_record=medical_record, diagnosis_result=diagnosis_result
            )

            # 调用LLM生成处方
            start_time = time.time()
            if self.verbose:
                self.cli.print_status("进行中", "正在生成处方...")
                print(f"{self.cli.colored_text('AI输出', 'CYAN')}: ", end="")

                # 使用流式输出
                messages: List[ChatCompletionMessageParam] = [
                    cast(
                        ChatCompletionUserMessageParam,
                        {"role": "user", "content": prompt},
                    )
                ]

                response = ""
                for chunk in self.llm.stream_chat(messages=messages, temperature=0.3):
                    print(chunk, end="", flush=True)
                    response += chunk
                print()  # 换行
            else:
                print("正在生成处方...")
                response = self.llm.simple_chat(prompt)

            end_time = time.time()
            duration = round(end_time - start_time, 2)

            # 提取处方
            prescription = self.extract_answer_from_response(response)

            result = {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "prescription": prescription,
                "llm_response": response,
                "status": "success",
                "processing_time": duration,
                "timestamp": time.time(),
            }

            if self.verbose:
                self.cli.print_status("成功", "处方生成完成", duration)
            else:
                print(f"处方生成完成 [耗时: {duration}s]")

            return result

        except Exception as e:
            error_msg = f"处方生成出错: {str(e)}"
            self.cli.print_status("错误", error_msg)
            return {
                "input_medical_record": medical_record,
                "input_diagnosis": diagnosis_result,
                "prescription": "Prescription generation failed",
                "status": "error",
                "error_message": str(e),
                "timestamp": time.time(),
            }

    def process_single_transcript(self, transcript: str) -> Dict[str, Any]:
        """
        处理单个转录文本的完整管道

        Args:
            transcript (str): 对话转录文本

        Returns:
            Dict[str, Any]: 包含完整处理结果的字典
        """
        self.cli.print_section_header("开始处理转录文本")

        start_time = time.time()

        # 1. 生成病历
        self.cli.print_step(1, 3, "病历生成")
        medical_result = self.generate_medical_record_from_transcript(transcript)
        if medical_result["status"] != "success":
            self.cli.print_status("错误", "处理流程中断：病历生成失败")
            return {
                "input_transcript": transcript,
                "medical_record_result": medical_result,
                "diagnosis_result": {
                    "status": "skipped",
                    "reason": "medical_record_generation_failed",
                },
                "prescription_result": {
                    "status": "skipped",
                    "reason": "medical_record_generation_failed",
                },
                "overall_status": "failed",
                "timestamp": time.time(),
            }

        medical_record = medical_result["medical_record"]

        # 2. 证型判断
        self.cli.print_step(2, 3, "证型判断")
        diagnosis_result = self.judge_symptom_type(medical_record)
        if diagnosis_result["status"] != "success":
            self.cli.print_status("错误", "处理流程中断：证型判断失败")
            return {
                "input_transcript": transcript,
                "medical_record_result": medical_result,
                "diagnosis_result": diagnosis_result,
                "prescription_result": {
                    "status": "skipped",
                    "reason": "diagnosis_failed",
                },
                "overall_status": "failed",
                "timestamp": time.time(),
            }

        diagnosis = diagnosis_result["diagnosis"]

        # 3. 处方生成
        self.cli.print_step(3, 3, "处方生成")
        prescription_result = self.generate_prescription(medical_record, diagnosis)

        # 4. 整合结果
        end_time = time.time()
        total_duration = round(end_time - start_time, 2)

        overall_result = {
            "input_transcript": transcript,
            "medical_record_result": medical_result,
            "diagnosis_result": diagnosis_result,
            "prescription_result": prescription_result,
            "overall_status": "success"
            if prescription_result["status"] == "success"
            else "failed",
            "total_processing_time": total_duration,
            "timestamp": time.time(),
        }

        # 显示完成状态
        if overall_result["overall_status"] == "success":
            self.cli.print_status("成功", "所有步骤处理完成")
        else:
            self.cli.print_status("错误", "处理过程中出现错误")

        self.cli.print_section_header("处理完成")

        return overall_result

    def process_multiple_transcripts(
        self, transcripts: List[str], use_concurrent: bool = True
    ) -> List[Dict[str, Any]]:
        """
        处理多个转录文本

        Args:
            transcripts (List[str]): 转录文本列表
            use_concurrent (bool): 是否使用并发处理

        Returns:
            List[Dict[str, Any]]: 处理结果列表
        """
        total = len(transcripts)
        concurrent_mode = "开启" if use_concurrent else "关闭"

        self.cli.print_section_header(f"批量处理 {total} 个转录文本")
        print(f"{self.cli.colored_text('并发模式', 'BLUE')}: {concurrent_mode}")
        if use_concurrent:
            print(f"{self.cli.colored_text('最大并发数', 'BLUE')}: {self.max_workers}")

        start_time = time.time()

        if use_concurrent and total > 1:
            # 使用并发处理
            results = self._process_concurrent(transcripts)
        else:
            # 使用顺序处理
            results = self._process_sequential(transcripts)

        end_time = time.time()
        total_duration = round(end_time - start_time, 2)
        self.cli.print_status("成功", "所有任务处理完成", total_duration)

        return results

    def _process_sequential(self, transcripts: List[str]) -> List[Dict[str, Any]]:
        """
        顺序处理转录文本
        """
        results = []
        total = len(transcripts)

        for i, transcript in enumerate(transcripts, 1):
            self.cli.print_progress(i - 1, total, "顺序处理进度")
            print(
                f"\n{self.cli.colored_text(f'正在处理第 {i}/{total} 个转录文本', 'BOLD')}"
            )
            result = self.process_single_transcript(transcript)
            results.append(result)

        self.cli.print_progress(total, total, "顺序处理进度")
        return results

    def _process_concurrent(self, transcripts: List[str]) -> List[Dict[str, Any]]:
        """
        并发处理转录文本
        """
        results: List[Optional[Dict[str, Any]]] = [None] * len(transcripts)
        completed_count = 0
        total = len(transcripts)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_index = {
                executor.submit(self.process_single_transcript, transcript): i
                for i, transcript in enumerate(transcripts)
            }

            # 处理完成的任务
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                completed_count += 1

                try:
                    result = future.result()
                    results[index] = result
                    self.cli.print_progress(completed_count, total, "并发处理进度")
                except Exception as e:
                    self.cli.print_status(
                        "错误", f"并发任务执行失败 (索引: {index + 1}): {str(e)}"
                    )
                    error_result = {
                        "input_transcript": transcripts[index],
                        "error_message": str(e),
                        "overall_status": "error",
                        "timestamp": time.time(),
                    }
                    results[index] = error_result

        # 确保所有位置都有值，对于None值提供默认错误结果
        final_results: List[Dict[str, Any]] = []
        for i, item in enumerate(results):
            if item is None:
                # 为未处理的任务提供默认错误结果
                default_error = {
                    "input_transcript": transcripts[i],
                    "error_message": "Task not completed",
                    "overall_status": "error",
                    "timestamp": time.time(),
                }
                final_results.append(default_error)
            else:
                final_results.append(item)

        return final_results

    def load_transcripts_from_files(self, file_paths: List[str]) -> List[str]:
        """
        从文件列表加载转录文本

        Args:
            file_paths (List[str]): 文件路径列表

        Returns:
            List[str]: 转录文本列表
        """
        transcripts = []
        total_files = len(file_paths)

        for i, file_path in enumerate(file_paths, 1):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        transcripts.append(content)
                        self.cli.print_status("成功", f"加载文件: {file_path}")
                    else:
                        self.cli.print_status("错误", f"文件为空: {file_path}")

                self.cli.print_progress(i, total_files, "加载文件进度")
            except Exception as e:
                self.cli.print_status("错误", f"加载文件失败 {file_path}: {str(e)}")

        return transcripts

    def save_results(self, results: List[Dict[str, Any]], output_file: str):
        """
        保存处理结果到JSON文件

        Args:
            results (List[Dict[str, Any]]): 处理结果列表
            output_file (str): 输出文件路径
        """
        try:
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            self.cli.print_status("成功", f"结果已保存到: {output_file}")

        except Exception as e:
            self.cli.print_status("错误", f"保存结果失败: {str(e)}")

    def print_summary(self, results: List[Dict[str, Any]]):
        """
        打印处理结果摘要

        Args:
            results (List[Dict[str, Any]]): 处理结果列表
        """
        total = len(results)
        success_count = sum(1 for r in results if r.get("overall_status") == "success")
        error_count = total - success_count

        self.cli.print_section_header("处理摘要统计")

        print(f"{self.cli.colored_text('总数', 'BLUE')}: {total}")
        print(f"{self.cli.colored_text('成功', 'GREEN')}: {success_count}")
        print(f"{self.cli.colored_text('失败', 'RED')}: {error_count}")

        if results:
            # 计算各阶段处理时间
            medical_times = []
            diagnosis_times = []
            prescription_times = []

            for r in results:
                if r.get("medical_record_result", {}).get("processing_time"):
                    medical_times.append(r["medical_record_result"]["processing_time"])
                if r.get("diagnosis_result", {}).get("processing_time"):
                    diagnosis_times.append(r["diagnosis_result"]["processing_time"])
                if r.get("prescription_result", {}).get("processing_time"):
                    prescription_times.append(
                        r["prescription_result"]["processing_time"]
                    )

            if medical_times:
                avg_medical = round(sum(medical_times) / len(medical_times), 2)
                print(
                    f"{self.cli.colored_text('病历生成平均耗时', 'MAGENTA')}: {avg_medical}s"
                )
            if diagnosis_times:
                avg_diagnosis = round(sum(diagnosis_times) / len(diagnosis_times), 2)
                print(
                    f"{self.cli.colored_text('证型判断平均耗时', 'MAGENTA')}: {avg_diagnosis}s"
                )
            if prescription_times:
                avg_prescription = round(
                    sum(prescription_times) / len(prescription_times), 2
                )
                print(
                    f"{self.cli.colored_text('处方生成平均耗时', 'MAGENTA')}: {avg_prescription}s"
                )


def load_config():
    """
    从.env文件加载配置参数

    Returns:
        tuple: (API_KEY, BASE_URL, MODEL_NAME)
    """
    # 加载.env文件
    load_dotenv()

    # 从环境变量读取配置
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("API_BASE_URL")
    model_name = os.getenv("MODEL_NAME", "deepseek-chat")

    # 检查必要的配置是否存在
    if not api_key:
        print("错误：未找到API_KEY环境变量")
        print("请确保.env文件存在并包含API_KEY配置")
        return None, None, None

    if not base_url:
        print("错误：未找到API_BASE_URL环境变量")
        print("请确保.env文件存在并包含API_BASE_URL配置")
        return None, None, None

    return api_key, base_url, model_name


def main():
    """
    主函数，演示完整的中医诊疗管道
    """
    # 加载配置
    API_KEY, BASE_URL, MODEL_NAME = load_config()

    if not all([API_KEY, BASE_URL, MODEL_NAME]):
        print("配置加载失败，程序退出")
        return

    cli = CLIFormatter()
    cli.print_section_header("中医诊疗系统启动")

    # 初始化中医诊疗系统 - 启用verbose模式
    tcm_system = TCMDiagnosisSystem(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_name=MODEL_NAME,
        max_workers=8,
        verbose=True,  # 启用详细模式，显示流式输出
    )

    # 示例1：处理单个转录文本文件
    transcript_file = "transcript.txt"
    if os.path.exists(transcript_file):
        cli.print_status("成功", f"找到转录文件: {transcript_file}")
        try:
            with open(transcript_file, "r", encoding="utf-8") as f:
                transcript = f.read()

            # 处理单个转录
            result = tcm_system.process_single_transcript(transcript)

            # 保存结果
            tcm_system.save_results([result], "output/single_result.json")

            # 打印摘要
            tcm_system.print_summary([result])

        except Exception as e:
            cli.print_status("错误", f"处理转录文件失败: {str(e)}")

    # 示例2：批量处理多个转录文件
    # transcript_files = ["transcript1.txt", "transcript2.txt", "transcript3.txt"]
    # existing_files = [f for f in transcript_files if os.path.exists(f)]

    # if existing_files:
    #     cli.print_status("成功", f"找到 {len(existing_files)} 个转录文件进行批量处理")

    #     # 加载转录文本
    #     transcripts = tcm_system.load_transcripts_from_files(existing_files)

    #     if transcripts:
    #         # 批量处理
    #         results = tcm_system.process_multiple_transcripts(transcripts, use_concurrent=True)

    #         # 保存结果
    #         tcm_system.save_results(results, "output/batch_results.json")

    #         # 打印摘要
    #         tcm_system.print_summary(results)

    cli.print_section_header("程序执行完成")


if __name__ == "__main__":
    main()
