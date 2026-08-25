"""ASR 容器引擎包：流式分句 + 并行识别/声纹 + 在线聚类。

与服务端共享同一份代码（CX-O-SERVER 通过挂载 asr_container/ 进容器 /app/asr_container:ro，
同时 pytest 可直接 import 本包做纯逻辑单测）。
"""