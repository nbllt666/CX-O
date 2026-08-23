"""CX-O-Dream 生理信号子包（physio）。

- estimator.py：HeartRateSleepEstimator（后端内存滑动窗口估计入睡置信度）
- store.py：PhysioSignalStore（只存衍生指标，禁止原始 HR 落盘）
- runtime.py：PhysioRuntime（physio REST 路由的运行时依赖注入容器）
"""
