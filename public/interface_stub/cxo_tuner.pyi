"""CXOTuner 接口契约存根。

定义 CXO-Tuner 自适应微调服务的接口签名 + 数据模型。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

服务职责：
  - 收集偏好反馈（live_danmaku/judge/distillation 三类来源）
  - 维护 DPO 数据集统计（来源分布 / 正负比例 / 锚点数量）
  - 空闲窗口 / 在线触发 LoRA 训练并产出适配器
  - 管理适配器（列出 / 删除 / 路由应用到在线 vLLM）

数据模型对齐 public/schema/ 下契约：
  - cxo_tuner_feedback.schema.json      -> FeedbackIn
  - cxo_tuner_dpo_dataset.schema.json   -> DatasetStats 统计口径
  - cxo_tuner_config.schema.json        -> 服务自身配置（不含接口签名）

@version 1.0.0
@see public/schema/cxo_tuner_feedback.schema.json
@see public/schema/cxo_tuner_dpo_dataset.schema.json
@see public/schema/cxo_tuner_config.schema.json
@see public/config_template/cxo_tuner_config.schema.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

__all__ = [
    "FeedbackIn",
    "FeedbackResponse",
    "DatasetStats",
    "TrainTriggerRequest",
    "TrainStatus",
    "AdapterInfo",
    "ApplyAdapterResponse",
    "CXOTunerAPI",
]

# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    """单条偏好反馈输入。字段与 cxo_tuner_feedback.schema.json 一致。

    source 枚举：live_danmaku / judge / distillation。
    root 额外字段禁止（additionalProperties=false）。
    """
    prompt: str
    response_chosen: str
    response_rejected: str
    source: str  # enum: live_danmaku / judge / distillation
    timestamp: str  # ISO 8601 date-time
    session_id: Optional[str] = None
    quality_score: Optional[float] = None  # 0-1
    metadata: Optional[Dict[str, Any]] = None


class FeedbackResponse(BaseModel):
    """提交反馈后的服务响应。"""
    feedback_id: str
    accepted: bool
    reason: str


class DatasetStats(BaseModel):
    """DPO 数据集统计视图。覆盖 dpo_dataset 记录集合的聚合口径。"""
    total: int
    source_breakdown: Dict[str, int]  # key=live_danmaku/judge/distillation
    positive_ratio: float  # 0-1，正样本（chosen 被采纳）占比
    negative_ratio: float  # 0-1，负样本（rejected）占比
    anchor_count: int  # anchor=True 的记录数


class TrainTriggerRequest(BaseModel):
    """触发训练请求。base_model 为空时回退配置 base_model。"""
    base_model: Optional[str] = None
    epochs: int
    sample_ratio: float  # 0-1，训练样本比例
    anchor_ratio: float  # 0-1，锚点样本占比
    job_id: str


class TrainStatus(BaseModel):
    """训练任务状态。"""
    job_id: str
    status: str  # enum: idle / running / completed / failed
    progress: float  # 0-1
    loss_curve: List[float]
    memory_usage_mb: int
    error: Optional[str] = None


class AdapterInfo(BaseModel):
    """训练产物（LoRA 适配器）元信息。"""
    id: str
    name: str
    created_at: str  # ISO 8601 date-time
    base_model: str
    epochs: int
    size_bytes: int


class ApplyAdapterResponse(BaseModel):
    """路由应用适配器到在线模型的响应。"""
    adapter_id: str
    applied: bool
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# CXO-Tuner API 接口
# ---------------------------------------------------------------------------


class CXOTunerAPI:
    """CXOTuner 接口契约。

    统一异常契约（所有方法可能抛出）：
      - ConnectionError_503: 上游 vLLM / 裁判模型 / 存储端点不可用（503）
      - ValueError_422: 输入无效、校验失败（422）
      - RuntimeError_500: 内部服务错误、训练或文件操作失败（500）
    """

    def health(self) -> Dict[str, Any]:
        """健康检查。

        Returns:
            状态字典（含 status、服务版本等）

        Raises:
            ConnectionError_503: 依赖端点不可达
            RuntimeError_500: 服务内部异常
        """
        ...

    def submit_feedback(self, feedback: FeedbackIn) -> FeedbackResponse:
        """提交一条偏好反馈。

        Args:
            feedback: 偏好反馈（对齐 cxo_tuner_feedback.schema.json）

        Returns:
            FeedbackResponse: 反馈入库结果（feedback_id + accepted + reason）

        Raises:
            ConnectionError_503: 存储端点不可用
            ValueError_422: feedback 校验失败（缺必填 / 类型 / 枚举错误）
            RuntimeError_500: 写入失败
        """
        ...

    def get_dataset_stats(self) -> DatasetStats:
        """获取 DPO 数据集统计视图。

        Returns:
            DatasetStats: total / source_breakdown / positive_ratio /
                negative_ratio / anchor_count 聚合结果

        Raises:
            ConnectionError_503: 存储端点不可用
            RuntimeError_500: 统计计算失败
        """
        ...

    def trigger_train(self, req: TrainTriggerRequest) -> TrainStatus:
        """触发 LoRA 训练任务。

        Args:
            req: 训练请求（base_model 可选回退配置默认）

        Returns:
            TrainStatus: 初始 running 状态与 job_id

        Raises:
            ConnectionError_503: 训练运行环境不可用
            ValueError_422: req 校验失败（epochs/ratio 越界、job_id 重复）
            RuntimeError_500: 训练启动失败
        """
        ...

    def get_train_status(self, job_id: str) -> TrainStatus:
        """查询训练任务状态。

        Args:
            job_id: 训练任务 ID

        Returns:
            TrainStatus: 当前训练进度 / loss_curve / 显存占用

        Raises:
            ConnectionError_503: 任务服务不可用
            ValueError_422: job_id 不存在
            RuntimeError_500: 状态读取失败
        """
        ...

    def list_adapters(self) -> List[AdapterInfo]:
        """列出全部训练产物适配器。

        Returns:
            List[AdapterInfo]: 适配器元信息列表

        Raises:
            ConnectionError_503: 产物存储不可用
            RuntimeError_500: 列表读取失败
        """
        ...

    def delete_adapter(self, id: str) -> bool:
        """删除一个适配器产物。

        Args:
            id: 适配器 ID

        Returns:
            bool: 是否已删除

        Raises:
            ConnectionError_503: 产物存储不可用
            ValueError_422: id 不存在
            RuntimeError_500: 删除失败
        """
        ...

    def apply_adapter(self, id: str) -> ApplyAdapterResponse:
        """路由应用适配器到在线 vLLM。

        Args:
            id: 适配器 ID

        Returns:
            ApplyAdapterResponse: 应用结果（adapter_id + applied + detail）

        Raises:
            ConnectionError_503: vLLM 端点不可达 / 换装失败
            ValueError_422: id 不存在或与配置 base_model 不匹配
            RuntimeError_500: 应用过程内部异常
        """
        ...