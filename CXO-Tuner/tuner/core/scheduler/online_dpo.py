"""在线 DPO（探索，实验性）执行桩。

概念：在用户打字停顿间隙，以极小学习率（max_lr，默认 1e-6）对活跃会话的偏好信号做
迷你梯度更新（在线增量 DPO）。这依赖真实在线推理环境提供：
  - 活跃模型参数句柄（可微分量）；
  - 逐会话的实时偏好 pair（chosen/rejected）。
本工程为离线开发/测试环境，不具备上述实算条件，故本模块仅提供可开关的执行入口/桩：
  - should_step()：判定是否允许步进（受 enabled 开关约束）；
  - step()：名义执行一次迷你更新，仅做开关断言，不做任何实算。
真实在线推理环境接入时应由外部为 step() 供应模型句柄与实时偏好，再填充真实梯度更新。
"""
from __future__ import annotations

from tuner.config import OnlineDpoConfig


class OnlineDpo:
    """在线 DPO 执行桩（experimental）。

    enabled 默认 False（配置约束）。任何会对外部模型产生梯度更新的路径都必须先通过
    should_step() / enabled 断言，防止未显式开启时对模型产生副作用。
    """

    def __init__(self, config: OnlineDpoConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        """是否开启在线 DPO（默认 False）。"""
        return self.config.enabled

    def should_step(self) -> bool:
        """是否允许对空闲会话执行一次迷你 DPO 更新。

        仅当配置 enabled=True 时返回 True；离线（默认）恒为 False。
        """
        return self.config.enabled

    def step(self) -> None:
        """执行一次迷你 DPO 梯度更新（桩）。

        依赖真实在线推理环境（活跃模型句柄 + 实时偏好 pair）方可实算；本环境只做
        开关断言，不做任何实算。关闭状态下调用会抛 AssertionError。
        """
        assert self.config.enabled, (
            "OnlineDpo 未启用（enabled=False），禁止执行 step()。"
            "请在配置中显式开启 online_dpo.enabled 后再运行。"
        )
        # TODO(experimental)：在此处以 self.config.max_lr 对活跃会话的偏好 pair
        # 做极小学习率迷你 DPO 更新。需真实推理环境提供模型参数句柄与实时偏好，
        # 本环境不做实算。
        _ = self.config.max_lr