"""
智能匹配服务
用于条文与病案的智能匹配
"""
import re
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from ..models import ClassicText, MedicalCase


class TextCaseMatcher:
    """条文-病案匹配器"""
    
    def __init__(self):
        """初始化匹配器"""
        # 中医常见症状关键词
        self.symptom_keywords = [
            "恶寒", "发热", "头痛", "咳嗽", "腹痛", "腹泻", "呕吐",
            "口渴", "口苦", "口淡", "纳差", "乏力", "自汗", "盗汗",
            "胸闷", "心悸", "失眠", "烦躁", "便秘", "尿频", "尿急"
        ]
        
        # 病机关键词
        self.pathogenesis_keywords = [
            "太阳", "阳明", "少阳", "太阴", "少阴", "厥阴",
            "表证", "里证", "半表半里", "寒证", "热证", "虚证", "实证",
            "气滞", "血瘀", "痰湿", "湿热", "阴虚", "阳虚"
        ]
        
        # 方剂关键词
        self.prescription_keywords = [
            "桂枝", "麻黄", "柴胡", "半夏", "人参", "甘草",
            "四逆", "承气", "白虎", "小青龙", "大青龙", "真武"
        ]
    
    def find_related_cases(
        self, 
        text: ClassicText, 
        db: Session, 
        limit: int = 5
    ) -> List[Tuple[MedicalCase, float]]:
        """
        为条文查找相关病案
        
        Args:
            text: 条文对象
            db: 数据库会话
            limit: 返回数量限制
        
        Returns:
            病案和相似度分数的列表
        """
        all_cases = db.query(MedicalCase).all()
        scored_cases = []
        
        for case in all_cases:
            score = self._calculate_similarity(text, case)
            if score > 0:  # 只返回有相似度的
                scored_cases.append((case, score))
        
        # 按分数排序
        scored_cases.sort(key=lambda x: x[1], reverse=True)
        
        return scored_cases[:limit]
    
    def find_related_texts(
        self,
        case: MedicalCase,
        db: Session,
        limit: int = 5
    ) -> List[Tuple[ClassicText, float]]:
        """
        为病案查找相关条文
        
        Args:
            case: 病案对象
            db: 数据库会话
            limit: 返回数量限制
        
        Returns:
            条文和相似度分数的列表
        """
        all_texts = db.query(ClassicText).all()
        scored_texts = []
        
        for text in all_texts:
            score = self._calculate_similarity(text, case)
            if score > 0:
                scored_texts.append((text, score))
        
        # 按分数排序
        scored_texts.sort(key=lambda x: x[1], reverse=True)
        
        return scored_texts[:limit]
    
    def _calculate_similarity(
        self, 
        text: ClassicText, 
        case: MedicalCase
    ) -> float:
        """
        计算条文与病案的相似度
        
        Args:
            text: 条文对象
            case: 病案对象
        
        Returns:
            相似度分数 (0-1)
        """
        score = 0.0
        total_weight = 0.0
        
        # 1. 症状匹配 (权重: 0.4)
        symptom_score = self._match_symptoms(text.content, case.symptoms or case.content)
        score += symptom_score * 0.4
        total_weight += 0.4
        
        # 2. 病机匹配 (权重: 0.3)
        pathogenesis_score = self._match_pathogenesis(text.content, case.content)
        score += pathogenesis_score * 0.3
        total_weight += 0.3
        
        # 3. 方剂匹配 (权重: 0.2)
        prescription_score = self._match_prescription(text.content, case.prescription or case.content)
        score += prescription_score * 0.2
        total_weight += 0.2
        
        # 4. 关键词匹配 (权重: 0.1)
        keyword_score = self._match_keywords(text.keywords or "", case.content)
        score += keyword_score * 0.1
        total_weight += 0.1
        
        # 归一化分数
        if total_weight > 0:
            score = score / total_weight
        
        return min(score, 1.0)  # 确保不超过1.0
    
    def _match_symptoms(self, text: str, case: str) -> float:
        """匹配症状"""
        if not case:
            return 0.0
        
        text_symptoms = [kw for kw in self.symptom_keywords if kw in text]
        case_symptoms = [kw for kw in self.symptom_keywords if kw in case]
        
        if not text_symptoms and not case_symptoms:
            return 0.5  # 都没有症状关键词，给中等分数
        
        if not text_symptoms or not case_symptoms:
            return 0.0
        
        # 计算交集比例
        common = set(text_symptoms) & set(case_symptoms)
        total = set(text_symptoms) | set(case_symptoms)
        
        if not total:
            return 0.0
        
        return len(common) / len(total)
    
    def _match_pathogenesis(self, text: str, case: str) -> float:
        """匹配病机"""
        if not case:
            return 0.0
        
        text_patho = [kw for kw in self.pathogenesis_keywords if kw in text]
        case_patho = [kw for kw in self.pathogenesis_keywords if kw in case]
        
        if not text_patho and not case_patho:
            return 0.3
        
        if not text_patho or not case_patho:
            return 0.0
        
        common = set(text_patho) & set(case_patho)
        total = set(text_patho) | set(case_patho)
        
        if not total:
            return 0.0
        
        return len(common) / len(total)
    
    def _match_prescription(self, text: str, case: str) -> float:
        """匹配方剂"""
        if not case:
            return 0.0
        
        text_pres = [kw for kw in self.prescription_keywords if kw in text]
        case_pres = [kw for kw in self.prescription_keywords if kw in case]
        
        if not text_pres and not case_pres:
            return 0.2
        
        if not text_pres or not case_pres:
            return 0.0
        
        common = set(text_pres) & set(case_pres)
        total = set(text_pres) | set(case_pres)
        
        if not total:
            return 0.0
        
        return len(common) / len(total)
    
    def _match_keywords(self, keywords: str, case: str) -> float:
        """匹配关键词"""
        if not keywords or not case:
            return 0.0
        
        keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        if not keyword_list:
            return 0.0
        
        matched = sum(1 for kw in keyword_list if kw in case)
        return matched / len(keyword_list) if keyword_list else 0.0


# 创建全局匹配器实例
def get_matcher() -> TextCaseMatcher:
    """获取匹配器实例"""
    return TextCaseMatcher()
