"""
AI分析服务
支持通义千问、文心一言等国内大模型API
"""
import os
import json
import re
from pathlib import Path
from typing import Optional, Dict
from dotenv import load_dotenv

# 固定从 backend 目录加载 .env
_backend_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(_backend_dir / ".env", override=False)

from ..logger import get_logger
logger = get_logger(__name__)


PLAIN_TEXT_OUTPUT_INSTRUCTION = """输出为适合直接阅读的纯中文文本。请使用“核心含义：”“辨证要点：”等普通段落，不要使用 Markdown、星号、井号、反引号、长横线、分隔线、项目符号或代码块。"""


def clean_analysis_output(text: str) -> str:
    """将模型的 Markdown 风格输出收敛为界面可直接展示的纯文本。"""
    if not text:
        return ""

    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"```[^\n]*", "", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*>\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-+*•]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*(?:[-—–_=*]){3,}\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"~~([^~\n]+)~~", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_{1,3}([^_\n]+)_{1,3}(?!\w)", r"\1", cleaned)
    cleaned = cleaned.replace("*", "").replace("`", "")
    cleaned = re.sub(r"[—–]{2,}", "，", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class AIService:
    """AI分析服务基类"""
    
    def __init__(self, api_key: str = None, api_type: str = "dashscope"):
        """
        初始化AI服务
        
        Args:
            api_key: API密钥
            api_type: API类型，支持 "dashscope"（通义千问）或 "baidu"（文心一言）
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("BAIDU_API_KEY")
        self.api_type = api_type
        
        if not self.api_key:
            logger.warning("未配置AI API密钥，AI分析功能将不可用")
    
    def analyze_text_case_relation(
        self, 
        text: str, 
        case: str,
        model_override: str = None
    ) -> Dict[str, any]:
        """
        分析条文与病案的关联关系
        
        Args:
            text: 条文内容
            case: 病案内容（可为空，仅分析条文）
        
        Returns:
            分析结果字典
        """
        if not self.api_key:
            return self._default_analysis(text, case)
        
        if self.api_type == "dashscope":
            result = self._dashscope_analyze(text, case, model_override)
            if not result.get("success") and self.api_key:
                result = self._openai_compatible_analyze(text, case, model_override)
            return result
        elif self.api_type == "openai":
            return self._openai_compatible_analyze(text, case, model_override)
        elif self.api_type == "baidu":
            return self._baidu_analyze(text, case)
        else:
            return self._default_analysis(text, case)
    
    def analyze_text_only(self, text: str, model_override: str = None) -> Dict[str, any]:
        """仅分析条文内容（无病案时调用）"""
        return self.analyze_text_case_relation(text, "", model_override)
    
    def _dashscope_analyze(self, text: str, case: str, model_override: str = None) -> Dict[str, any]:
        """使用通义千问API分析"""
        try:
            import dashscope
            from http import HTTPStatus
            dashscope.api_key = self.api_key
            
            if case:
                user_content = f"""请作为中医专家，分析以下经典条文与病案的关联关系：

【经典条文】
{text}

【病案】
{case}

请从以下角度进行详细分析：
1. 病机对应关系：分析条文描述的病机与病案中患者病机的对应关系
2. 症状匹配度：对比条文中的症状描述与病案中患者症状的匹配程度
3. 方剂应用合理性：如果病案中使用了方剂，分析其与条文方剂的关联性
4. 辨证要点：总结辨证的关键要点
5. 临床应用价值：说明这个条文对理解此病案的指导意义

请用专业但易懂的中文回答，结构清晰，条理分明。
{PLAIN_TEXT_OUTPUT_INSTRUCTION}"""
            else:
                user_content = f"""请作为中医专家，对以下经典条文进行解读分析：

【经典条文】
{text}

请从以下角度进行分析：
1. 条文出处与背景
2. 病机与证候要点
3. 症状特征
4. 辨证要点与临床应用
5. 学习建议

请用专业但易懂的中文回答，结构清晰，条理分明。
{PLAIN_TEXT_OUTPUT_INSTRUCTION}"""
            
            # 使用 messages + result_format=text，直接返回 output.text
            response = dashscope.Generation.call(
                model="qwen-turbo",
                messages=[{"role": "user", "content": user_content}],
                result_format="text",
                max_tokens=2000,
                temperature=0.7
            )
            
            if response.status_code == HTTPStatus.OK:
                analysis = None
                if hasattr(response.output, "text") and response.output.text:
                    analysis = response.output.text
                elif hasattr(response.output, "choices") and response.output.choices:
                    analysis = getattr(response.output.choices[0].message, "content", None)
                if not analysis and hasattr(response.output, "__dict__"):
                    d = response.output.__dict__ if hasattr(response.output, "__dict__") else {}
                    analysis = d.get("text") or (d.get("choices", [{}])[0].get("message", {}).get("content") if d.get("choices") else None)
                if not analysis:
                    analysis = str(response.output) if response.output else "分析结果为空"
                return {
                    "analysis": clean_analysis_output(analysis),
                    "model": "qwen-turbo",
                    "success": True
                }
            else:
                err_msg = getattr(response, "message", None) or getattr(response, "code", None) or str(response)
                logger.error("通义千问API调用失败: status=%s, %s", response.status_code, err_msg)
                return self._default_analysis(text, case, error=f"API调用失败: {err_msg}")
                
        except ImportError:
            logger.error("dashscope未安装")
            return self._default_analysis(text, case, error="dashscope 未安装")
        except Exception as e:
            logger.exception("AI分析出错")
            import traceback
            traceback.print_exc()
            return self._default_analysis(text, case, error=str(e))
    
    def _openai_compatible_analyze(self, text: str, case: str, model_override: str = None) -> Dict[str, any]:
        """使用 OpenAI 兼容接口（DashScope 或 OpenAI 官方）"""
        try:
            from openai import OpenAI
            api_key = (self.api_key or os.getenv("OPENAI_API_KEY") or "").strip()
            if not api_key:
                return self._default_analysis(text, case, error="未配置 API 密钥")
            base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
            # 有自定义 BASE_URL 则用；sk-proj- 且无 BASE_URL 用 OpenAI 官方
            use_openai_official = (
                not base_url and
                ((self.api_type == "openai") or api_key.startswith("sk-proj-"))
            )
            if use_openai_official:
                base_url = None
            elif not base_url:
                base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            from .llm_client import build_openai_client
            # trust_env=False：内网端点不能被系统代理劫持（见 llm_client 模块说明）
            client = build_openai_client(api_key=api_key, base_url=base_url)
            if case:
                user_content = f"""请作为中医专家，分析以下经典条文与病案的关联关系：

【经典条文】
{text}

【病案】
{case}

请从病机对应、症状匹配、方剂应用、辨证要点、临床应用价值等角度详细分析。用专业但易懂的中文回答。
{PLAIN_TEXT_OUTPUT_INSTRUCTION}"""
            else:
                user_content = f"""请作为中医专家，对以下经典条文进行解读分析：

【经典条文】
{text}

请从条文出处、病机证候、症状特征、辨证要点、临床应用等角度分析。用专业但易懂的中文回答。
{PLAIN_TEXT_OUTPUT_INSTRUCTION}"""
            # 自定义端点：Linvk 等用 deepseek-chat；官方 OpenAI 用 gpt-3.5-turbo
            default_model = "gpt-3.5-turbo" if use_openai_official else os.getenv("AI_MODEL", "deepseek-chat")
            model = (model_override or default_model).strip()
            # 备选模型：只尝试 AI_FALLBACK_MODELS 中显式列出的模型。
            # 不再内置 DeepSeek 默认值 —— 不同平台的模型名不通用，猜名字会让失败请求
            # 多等几轮，并把"模型不存在"伪装成故障原因。
            fallbacks = [] if use_openai_official else [
                m.strip()
                for m in (os.getenv("AI_FALLBACK_MODELS") or "").split(",")
                if m.strip()
            ]
            models_to_try = [model] + [m for m in fallbacks if m != model]
            last_err = None
            for m in models_to_try:
                try:
                    resp = client.chat.completions.create(
                        model=m,
                        messages=[{"role": "user", "content": user_content}],
                        max_tokens=2000,
                        temperature=0.7
                    )
                    analysis = resp.choices[0].message.content
                    return {"analysis": clean_analysis_output(analysis), "model": m, "success": True}
                except Exception as e:
                    last_err = str(e)
                    logger.warning("模型 %s 调用失败: %s", m, last_err)
                    continue
            return self._default_analysis(text, case, error=last_err or "所有模型均调用失败")
        except ImportError:
            return self._default_analysis(text, case, error="openai 未安装，请运行: pip install openai")
        except Exception as e:
            err = str(e)
            logger.error("OpenAI兼容接口调用失败: %s", err)
            return self._default_analysis(text, case, error=err)
    
    def _baidu_analyze(self, text: str, case: str) -> Dict[str, any]:
        """使用文心一言API分析"""
        try:
            import requests
            
            # 获取access_token
            secret_key = os.getenv("BAIDU_SECRET_KEY")
            if not secret_key:
                return self._default_analysis(text, case)
            
            # 获取access_token
            token_url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={self.api_key}&client_secret={secret_key}"
            token_response = requests.post(token_url)
            access_token = token_response.json().get("access_token")
            
            if not access_token:
                return self._default_analysis(text, case)
            
            prompt = f"""请作为中医专家，分析以下经典条文与病案的关联关系：

【经典条文】
{text}

【病案】
{case}

请从以下角度进行详细分析：
1. 病机对应关系
2. 症状匹配度
3. 方剂应用合理性
4. 辨证要点
5. 临床应用价值

请用专业但易懂的中文回答。
{PLAIN_TEXT_OUTPUT_INSTRUCTION}"""
            
            api_url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={access_token}"
            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_output_tokens": 2000
            }
            
            response = requests.post(api_url, json=payload)
            result = response.json()
            
            if "result" in result:
                return {
                    "analysis": clean_analysis_output(result["result"]),
                    "model": "ernie-bot",
                    "success": True
                }
            else:
                err = result.get("error_msg", result.get("error", str(result)))
                logger.error("文心一言API调用失败: %s", err)
                return self._default_analysis(text, case, error=f"文心一言: {err}")
                
        except ImportError:
            logger.error("requests未安装")
            return self._default_analysis(text, case, error="requests 未安装")
        except Exception as e:
            logger.exception("AI分析出错")
            return self._default_analysis(text, case, error=str(e))
    
    def _default_analysis(self, text: str, case: str, error: str = None) -> Dict[str, any]:
        """默认分析（当AI不可用时）"""
        text_preview = (text[:200] + "...") if len(text) > 200 else text
        case_preview = (case[:200] + "...") if case and len(case) > 200 else (case or "（无）")
        err_note = f"\n\n【错误信息】{error}" if error else ""
        analysis = f"""
条文分析：

【条文内容】
{text_preview}

【病案内容】
{case_preview}

【基础分析】
1. 病机对应：需要AI深度分析
2. 症状匹配：需要AI深度分析
3. 方剂应用：需要AI深度分析
4. 辨证要点：需要AI深度分析

注意：AI API 未配置或调用失败，以上为占位分析。{err_note}
        """
        return {
            "analysis": clean_analysis_output(analysis),
            "model": "default",
            "success": False,
            "message": error or "未配置AI API"
        }


# 创建全局AI服务实例
def get_ai_service() -> AIService:
    """获取AI服务实例"""
    # 自定义端点（如 ai.linvk.com）优先
    if os.getenv("OPENAI_BASE_URL") and (os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")):
        key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        return AIService(api_key=key, api_type="openai")
    if os.getenv("DASHSCOPE_API_KEY"):
        return AIService(api_key=os.getenv("DASHSCOPE_API_KEY"), api_type="dashscope")
    if os.getenv("OPENAI_API_KEY"):
        return AIService(api_key=os.getenv("OPENAI_API_KEY"), api_type="openai")
    if os.getenv("BAIDU_API_KEY"):
        return AIService(api_type="baidu")
    return AIService()
