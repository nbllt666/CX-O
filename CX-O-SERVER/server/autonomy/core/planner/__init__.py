"""规划器子包：ActionPlanner（LLM 驱动的自主行动规划器，P1-T6）。

规划器接收动机/时段/热点/上下文快照，调用 LLM 输出结构化 JSON 行动决策，
对齐 public/schema/autonomy_action.schema.json（action/target/payload/reason/
expected_outcome），并支持可选的工具调用循环与记忆注入。
"""
