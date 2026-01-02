#!/usr/bin/env python3
"""
Gradio WebUI应用（带后端控制）

功能：
- 聊天页面
- 设置页面（后端启动/停止）
- 记忆管理页面
- 弹幕监控页面
"""

import gradio as gr
from gradio import themes
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GradioApp:
    """Gradio WebUI应用"""
    
    def __init__(self, config: dict, backend_port: int = 8000):
        """
        初始化WebUI应用
        
        Args:
            config: 全局配置
            backend_port: 后端服务端口
        """
        self.config = config
        self.backend_port = backend_port
        self._backend_status = gr.State(value={"is_running": False})
        
        # 创建Blocks
        with gr.Blocks(
            title="🌅 晨曦Origins Agent",
            theme=themes.Soft()
        ) as self.app:
            self._build_ui()
    
    def _build_ui(self):
        """构建UI"""
        # 标题
        gr.Markdown("# 🌅 晨曦Origins Agent")
        gr.Markdown("人格化AI助手 | 长期记忆 | 多模态交互 | 弹幕互动")
        
        # 状态显示
        status_display = gr.Markdown("❌ 后端服务未启动")
        
        # 后端控制
        with gr.Row():
            start_backend_btn = gr.Button("🚀 启动后端", variant="primary", scale=2)
            stop_backend_btn = gr.Button("⏹️ 停止后端", variant="stop", scale=2)
            refresh_status_btn = gr.Button("🔄 刷新状态", scale=1)
        
        # 选项卡
        with gr.Tabs():
            self._build_chat_tab()
            self._build_settings_tab()
            self._build_memory_tab()
            self._build_danmaku_tab()
        
        # 后端控制事件
        def start_backend(port):
            from main import BackendManager
            backend_port = 8000  # 后端固定使用8000端口
            BackendManager.start_backend(backend_port)
            import time
            time.sleep(1)
            status = BackendManager.get_status()
            return f"✅ 后端服务运行中 (API: 8000)" if status["is_running"] else "❌ 后端服务启动失败"
        
        def stop_backend():
            from main import BackendManager
            BackendManager.stop_backend()
            return "❌ 后端服务已停止"
        
        def refresh_status():
            from main import BackendManager
            status = BackendManager.get_status()
            return f"✅ 后端服务运行中" if status["is_running"] else "❌ 后端服务未启动"
        
        start_backend_btn.click(start_backend, None, status_display)
        stop_backend_btn.click(stop_backend, None, status_display)
        refresh_status_btn.click(refresh_status, None, status_display)
    
    # ========== 聊天页面 ==========
    
    def _build_chat_tab(self):
        with gr.TabItem("💬 聊天"):
            with gr.Column(scale=1):
                # 聊天历史
                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    type="messages",
                    avatar_images=("🤖", "👤")
                )
                
                # 输入区域
                with gr.Row():
                    with gr.Column(scale=4):
                        text_input = gr.Textbox(
                            placeholder="输入消息...（支持多行输入）",
                            lines=3,
                            elem_id="text_input",
                            show_label=False
                        )
                    
                    with gr.Column(scale=1):
                        audio_input = gr.Audio(
                            sources=["microphone"],
                            type="filepath",
                            label="🎤 语音"
                        )
                
                # 按钮
                with gr.Row():
                    submit_btn = gr.Button("发送", variant="primary", scale=2)
                    clear_btn = gr.Button("清空对话", variant="stop", scale=1)
                
                # 音频输出
                audio_output = gr.Audio(
                    elem_id="audio_output",
                    label="🔊 语音输出",
                    autoplay=True
                )
                
                # 快捷指令
                with gr.Accordion("📝 快捷指令", open=False):
                    quick_prompts = [
                        "今天有什么新闻？",
                        "讲个笑话",
                        "帮我记住...",
                        "搜索相关记忆"
                    ]
                    gr.Examples(
                        examples=quick_prompts,
                        inputs=text_input,
                        label="点击使用"
                    )
    
    # ========== 设置页面 ==========
    
    def _build_settings_tab(self):
        with gr.TabItem("⚙️ 设置"):
            with gr.Column():
                gr.Markdown("## 系统配置")
                
                # 主模型选择
                with gr.Group():
                    gr.Markdown("### 🤖 主模型（负责对话）")
                    
                    llm_provider = gr.Dropdown(
                        ["vllm", "ollama"],
                        value=self.config.get('system', {}).get('llm_provider', 'vllm'),
                        label="选择LLM提供商",
                        info="vllm适合本地高性能推理，ollama适合轻量部署"
                    )
                    
                    # vLLM配置（默认显示）
                    with gr.Column(visible=True) as vllm_config:
                        vllm_host = gr.Textbox(
                            value=self.config.get('system', {}).get('vllm', {}).get('host', 'localhost'),
                            label="vLLM Host"
                        )
                        vllm_port = gr.Number(
                            value=self.config.get('system', {}).get('vllm', {}).get('port', 8000),
                            label="vLLM Port"
                        )
                        vllm_model = gr.Textbox(
                            value=self.config.get('system', {}).get('vllm', {}).get('model', 'Qwen2.5-7B-Instruct'),
                            label="模型名称"
                        )
                    
                    # Ollama配置（默认隐藏）
                    with gr.Column(visible=False) as ollama_config:
                        ollama_host = gr.Textbox(
                            value=self.config.get('system', {}).get('ollama', {}).get('host', 'http://localhost:11434'),
                            label="Ollama Host"
                        )
                        ollama_model = gr.Textbox(
                            value=self.config.get('system', {}).get('ollama', {}).get('model', 'llama3.2'),
                            label="模型名称"
                        )
                    
                    # 切换显示/隐藏
                    def toggle_provider(provider):
                        return {
                            vllm_config: gr.update(visible=provider == "vllm"),
                            ollama_config: gr.update(visible=provider == "ollama")
                        }
                    
                    llm_provider.change(toggle_provider, llm_provider, [vllm_config, ollama_config])
                
                # 副模型选择
                with gr.Group():
                    gr.Markdown("### 🔧 副模型（负责记忆管理/弹幕审核）")
                    
                    assistant_provider = gr.Dropdown(
                        ["vllm", "ollama"],
                        value=self.config.get('system', {}).get('assistant_provider', 'vllm'),
                        label="选择LLM提供商"
                    )
                    
                    with gr.Column() as assistant_vllm_config:
                        assistant_vllm_host = gr.Textbox(
                            value=self.config.get('system', {}).get('assistant_vllm', {}).get('host', 'localhost'),
                            label="vLLM Host"
                        )
                        assistant_vllm_model = gr.Textbox(
                            value=self.config.get('system', {}).get('assistant_vllm', {}).get('model', 'Qwen2.5-1.5B-Instruct'),
                            label="模型名称"
                        )
                    
                    with gr.Column(visible=False) as assistant_ollama_config:
                        assistant_ollama_host = gr.Textbox(
                            value=self.config.get('system', {}).get('assistant_ollama', {}).get('host', 'http://localhost:11434'),
                            label="Ollama Host"
                        )
                        assistant_ollama_model = gr.Textbox(
                            value=self.config.get('system', {}).get('assistant_ollama', {}).get('model', 'llama3.2'),
                            label="模型名称"
                        )
                    
                    def toggle_assistant_provider(provider):
                        return {
                            assistant_vllm_config: gr.update(visible=provider == "vllm"),
                            assistant_ollama_config: gr.update(visible=provider == "ollama")
                        }
                    
                    assistant_provider.change(toggle_assistant_provider, assistant_provider, [assistant_vllm_config, assistant_ollama_config])
                
                # 记忆配置
                with gr.Group():
                    gr.Markdown("### 记忆配置")
                    
                    archive_interval = gr.Number(
                        value=self.config.get('memory', {}).get('archive_interval', 3600),
                        label="归档间隔（秒）"
                    )
                    retrieval_limit = gr.Slider(
                        minimum=1,
                        maximum=20,
                        value=self.config.get('memory', {}).get('retrieval_limit', 10),
                        label="检索数量"
                    )
                    max_history_rounds = gr.Slider(
                        minimum=5,
                        maximum=50,
                        value=self.config.get('memory', {}).get('max_history_rounds', 20),
                        label="保留历史轮数"
                    )
                
                # 弹幕配置
                with gr.Group():
                    gr.Markdown("### 弹幕配置")
                    
                    danmaku_enable = gr.Checkbox(
                        value=self.config.get('danmaku', {}).get('enabled', True),
                        label="启用弹幕监听"
                    )
                    danmaku_uri = gr.Textbox(
                        value=self.config.get('danmaku', {}).get('websocket_uri', 'ws://localhost:9898'),
                        label="弹幕服务器URI"
                    )
                    danmaku_room_id = gr.Textbox(
                        value=",".join(self.config.get('danmaku', {}).get('task_ids', [])),
                        label="房间号（逗号分隔）"
                    )
                    audit_enabled = gr.Checkbox(
                        value=self.config.get('danmaku', {}).get('audit_enabled', True),
                        label="启用弹幕审核"
                    )
                
                # 语音配置
                with gr.Group():
                    gr.Markdown("### 🎤 语音配置")
                    
                    # TTS配置
                    gr.Markdown("#### TTS（语音合成）")
                    tts_provider = gr.Dropdown(
                        ["edge", "f5-tts"],
                        value=self.config.get('tts', {}).get('provider', 'edge'),
                        label="TTS提供商",
                        info="edge=微软语音，f5-tts=开源克隆"
                    )
                    
                    with gr.Column(visible=True) as edge_tts_config:
                        tts_voice = gr.Dropdown(
                            ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-XiaoyouNeural"],
                            value=self.config.get('tts', {}).get('voice', 'zh-CN-XiaoxiaoNeural'),
                            label="语音角色"
                        )
                    
                    with gr.Column(visible=False) as f5_tts_config:
                        tts_voice_ref = gr.Textbox(
                            value=self.config.get('tts', {}).get('voice_ref', ''),
                            label="参考音频路径",
                            info="F5-TTS需要提供参考音频"
                        )
                    
                    def toggle_tts_provider(provider):
                        return {
                            edge_tts_config: gr.update(visible=provider == "edge"),
                            f5_tts_config: gr.update(visible=provider == "f5-tts")
                        }
                    
                    tts_provider.change(toggle_tts_provider, tts_provider, [edge_tts_config, f5_tts_config])
                    
                    # ASR配置
                    gr.Markdown("#### ASR（语音识别）")
                    asr_provider = gr.Dropdown(
                        ["sensevoice", "whisper"],
                        value=self.config.get('asr', {}).get('provider', 'sensevoice'),
                        label="ASR提供商",
                        info="sensevoice=开源实时识别，whisper=OpenAI"
                    )
                    asr_use_gpu = gr.Checkbox(
                        value=self.config.get('asr', {}).get('use_gpu', True),
                        label="使用GPU加速"
                    )
                
                # 保存按钮
                save_btn = gr.Button("保存配置", variant="primary")
                
                # 保存状态
                save_status = gr.Markdown()
                
                # 保存配置函数
                def save_config(
                    provider, vllm_host, vllm_port, vllm_model,
                    ollama_host, ollama_model,
                    assistant_provider, assistant_vllm_host, assistant_vllm_model,
                    assistant_ollama_host, assistant_ollama_model,
                    archive_interval, retrieval_limit, max_history_rounds,
                    danmaku_enable, danmaku_uri, danmaku_room_id, audit_enabled,
                    tts_provider, tts_voice, tts_voice_ref,
                    asr_provider, asr_use_gpu
                ):
                    config = {
                        "system": {
                            "llm_provider": provider,
                            "vllm": {
                                "host": vllm_host,
                                "port": vllm_port,
                                "model": vllm_model
                            },
                            "ollama": {
                                "host": ollama_host,
                                "model": ollama_model
                            },
                            "assistant_provider": assistant_provider,
                            "assistant_vllm": {
                                "host": assistant_vllm_host,
                                "model": assistant_vllm_model
                            },
                            "assistant_ollama": {
                                "host": assistant_ollama_host,
                                "model": assistant_ollama_model
                            }
                        },
                        "memory": {
                            "archive_interval": archive_interval,
                            "retrieval_limit": retrieval_limit,
                            "max_history_rounds": max_history_rounds
                        },
                        "danmaku": {
                            "enabled": danmaku_enable,
                            "websocket_uri": danmaku_uri,
                            "task_ids": [x.strip() for x in danmaku_room_id.split(",") if x.strip()],
                            "audit_enabled": audit_enabled
                        },
                        "tts": {
                            "provider": tts_provider,
                            "voice": tts_voice,
                            "voice_ref": tts_voice_ref
                        },
                        "asr": {
                            "provider": asr_provider,
                            "use_gpu": asr_use_gpu
                        }
                    }
                    
                    config_path = Path(__file__).parent / "config.json"
                    with open(config_path, "w", encoding="utf-8") as f:
                        import json
                        json.dump(config, f, ensure_ascii=False, indent=2)
                    
                    return "✅ 配置已保存到 config.json"
                
                save_btn.click(
                    save_config,
                    inputs=[
                        llm_provider, vllm_host, vllm_port, vllm_model,
                        ollama_host, ollama_model,
                        assistant_provider, assistant_vllm_host, assistant_vllm_model,
                        assistant_ollama_host, assistant_ollama_model,
                        archive_interval, retrieval_limit, max_history_rounds,
                        danmaku_enable, danmaku_uri, danmaku_room_id, audit_enabled,
                        tts_provider, tts_voice, tts_voice_ref,
                        asr_provider, asr_use_gpu
                    ],
                    outputs=save_status
                )
    
    # ========== 记忆管理页面 ==========
    
    def _build_memory_tab(self):
        with gr.TabItem("🧠 记忆管理"):
            with gr.Column():
                gr.Markdown("## 记忆管理")
                
                # 搜索
                with gr.Row():
                    search_input = gr.Textbox(
                        placeholder="搜索记忆...",
                        label="搜索",
                        scale=4
                    )
                    search_btn = gr.Button("搜索", scale=1)
                
                # 添加记忆
                with gr.Accordion("➕ 添加记忆", open=False):
                    new_content = gr.Textbox(
                        lines=3,
                        placeholder="输入要记忆的内容...",
                        label="记忆内容"
                    )
                    
                    with gr.Row():
                        memory_type = gr.Dropdown(
                            ["permanent", "long_term", "short_term"],
                            value="long_term",
                            label="记忆类型",
                            scale=2
                        )
                        importance = gr.Slider(
                            minimum=1,
                            maximum=5,
                            value=3,
                            label="重要性",
                            step=1,
                            scale=1
                        )
                    
                    tags = gr.Textbox(
                        placeholder="标签（逗号分隔）",
                        label="标签"
                    )
                    
                    add_btn = gr.Button("添加记忆", variant="primary")
                
                # 记忆列表
                memory_list = gr.Dataframe(
                    headers=["ID", "类型", "内容", "重要性", "标签", "创建时间"],
                    interactive=True,
                    label="记忆列表"
                )
                
                # 操作按钮
                with gr.Row():
                    delete_btn = gr.Button("🗑️ 删除选中", variant="stop")
                    export_btn = gr.Button("📤 导出")
                    import_btn = gr.Button("📥 导入")
                
                # 统计信息
                with gr.Row():
                    total_memories = gr.Number(value=0, label="总记忆数")
                    permanent_count = gr.Number(value=0, label="永久记忆")
                    long_term_count = gr.Number(value=0, label="长期记忆")
    
    # ========== 弹幕监控页面 ==========
    
    danmaku_status = gr.State(value={"connected": False, "plugin": None})
    
    def _build_danmaku_tab(self):
        with gr.TabItem("📊 弹幕监控"):
            with gr.Column():
                gr.Markdown("## 弹幕监控")
                
                # 状态显示
                danmaku_status_display = gr.Markdown("❌ 未连接")
                
                # 连接控制
                with gr.Row():
                    danmaku_uri = gr.Textbox(
                        value=self.config.get('danmaku', {}).get('websocket_uri', 'ws://localhost:9898'),
                        label="弹幕服务器URI",
                        scale=3
                    )
                    connect_btn = gr.Button("🔗 连接", variant="primary", scale=1)
                    disconnect_btn = gr.Button("❌ 断开", variant="stop", scale=1)
                
                # 实时弹幕流
                gr.Markdown("### 实时弹幕")
                danmaku_feed = gr.Dataframe(
                    headers=["时间", "用户", "内容", "审核状态"],
                    label="弹幕流"
                )
                
                # 统计信息
                with gr.Row():
                    total_count = gr.Number(value=0, label="总弹幕数")
                    approved_count = gr.Number(value=0, label="已通过")
                    rejected_count = gr.Number(value=0, label="已拒绝")
                    pending_count = gr.Number(value=0, label="待审核")
                
                # 审核日志
                with gr.Accordion("📋 审核日志", open=False):
                    audit_log = gr.Dataframe(
                        headers=["时间", "用户", "内容", "审核结果", "原因"]
                    )
                
                # 连接/断开事件
                def connect_danmaku(uri):
                    from plugins.danmaku import DanmakuPlugin
                    from core.danmaku_cache import DanmakuCacheManager
                    
                    cache = DanmakuCacheManager()
                    plugin = DanmakuPlugin(cache)
                    
                    try:
                        # 在后台任务中连接
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_loop(loop)
                        loop.run_until_complete(plugin.connect(uri, []))
                        
                        self.danmaku_status = {"connected": True, "plugin": plugin}
                        return "✅ 已连接到弹幕服务器"
                    except Exception as e:
                        return f"❌ 连接失败: {str(e)}"
                
                def disconnect_danmaku():
                    plugin = self.danmaku_status.get("value", {}).get("plugin")
                    if plugin:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_loop(loop)
                        loop.run_until_complete(plugin.disconnect())
                    
                    self.danmaku_status = {"connected": False, "plugin": None}
                    return "❌ 已断开连接"
                
                connect_btn.click(connect_danmaku, danmaku_uri, danmaku_status_display)
                disconnect_btn.click(disconnect_danmaku, None, danmaku_status_display)
    
    def launch(self, host="0.0.0.0", port=7860, share=True):
        """
        启动WebUI
        
        Args:
            host: 监听地址（0.0.0.0支持外部访问）
            port: 端口
            share: 是否创建公共链接（用于外部访问）
        """
        logger.info(f"启动WebUI: http://{host}:{port}")
        
        self.app.launch(
            server_name=host,
            server_port=port,
            share=share,
            show_api=False
        )


def create_gradio_app_with_backend(config: dict, webui_port: int = 7860) -> GradioApp:
    """创建带后端控制的Gradio应用"""
    return GradioApp(config, webui_port)


if __name__ == "__main__":
    # 默认配置
    default_config = {
        "system": {
            "llm_provider": "vllm",
            "vllm": {
                "host": "localhost",
                "port": 8000,
                "model": "Qwen2.5-7B-Instruct"
            },
            "ollama": {
                "host": "http://localhost:11434",
                "model": "llama3.2"
            },
            "main_port": 8000,
            "webui_port": 7860,
            "log_level": "INFO"
        },
        "memory": {
            "context_dir": "data/contexts",
            "vector_dimension": 1024,
            "archive_interval": 3600,
            "retrieval_limit": 10,
            "max_history_rounds": 20
        },
        "danmaku": {
            "enabled": True,
            "websocket_uri": "ws://localhost:9898",
            "task_ids": [],
            "audit_enabled": True
        },
        "audio": {
            "effects_dir": "data/effects"
        }
    }
    
    app = create_gradio_app_with_backend(default_config)
    app.launch()
