## Web API 接口

F5-TTS 还提供了基于 FastAPI 的 Web API 接口，支持通过 HTTP 请求调用文本转语音功能。

### Web API 概述

- **API 标题**: F5-TTS Web API
- **版本**: 1.0.0
- **描述**: 为 F5-TTS 文本转语音服务提供的 Web API
- **基础 URL**: http://your-host:8000

### Web API 端点

#### 1. 获取根路径信息

**端点**: `GET /`

**描述**: 返回 API 的基本信息和模型加载状态

**响应示例**:
```json
{
  "message": "Welcome to F5-TTS Web API",
  "status": "running",
  "model_available": true
}
```

**参数**: 无

---

#### 2. 健康检查

**端点**: `GET /health`

**描述**: 检查 API 服务的健康状态和模型加载情况

**响应示例**:
```json
{
  "status": "healthy",
  "model_loaded": true
}
```

**参数**: 无

---

#### 3. 文本转语音

**端点**: `POST /tts/`

**描述**: 使用参考音频将文本转换为语音

**请求方式**: POST (multipart/form-data)

**请求参数**:

| 参数名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| ref_audio | File | 是 | - | 参考音频文件，用于提取语音特征 |
| ref_text | String | 是 | - | 参考音频对应的文本内容 |
| gen_text | String | 是 | - | 需要生成语音的文本内容 |
| tts_model | String | 否 | "F5-TTS" | 模型类型，可选值："F5-TTS" 或 "E2-TTS" |
| remove_silence | Boolean | 否 | false | 是否移除生成音频中的静音部分 |
| cross_fade_duration | Float | 否 | 0.15 | 跨越淡入淡出持续时间（秒） |
| speed | Float | 否 | 1.0 | 语速倍率 |
| nfe_step | Integer | 否 | 32 | 数值函数评估步数 |
| cfg_strength | Integer | 否 | 2 | 配置强度 |
| seed | Integer | 否 | -1 | 随机种子，-1 表示随机 |

**成功响应**:
- **状态码**: 200 OK
- **内容类型**: audio/wav
- **响应头**: Content-Disposition: attachment; filename=generated.wav
- **响应体**: 生成的音频文件（WAV格式）

**错误响应**:
- **状态码**: 400 Bad Request - 当 tts_model 不是 "F5-TTS" 或 "E2-TTS" 时
- **状态码**: 500 Internal Server Error - 生成语音过程中发生错误

**请求示例** (使用 curl):
```bash
curl -X POST "http://your-host:8000/tts/" \
  -H "accept: audio/wav" \
  -F "ref_audio=@reference_audio.wav" \
  -F "ref_text=This is a reference text." \
  -F "gen_text=This is the text to be converted to speech." \
  -F "tts_model=F5-TTS" \
  -F "remove_silence=false" \
  -F "cross_fade_duration=0.15" \
  -F "speed=1.0" \
  -F "nfe_step=32" \
  -F "cfg_strength=2" \
  -F "seed=-1"
```

### 启动 Web API 服务

```bash
python webapi.py
```

服务将在 http://localhost:8000 上运行。

### Web API 注意事项

1. **模型可用性**: 如果模型未正确加载，API 仍会运行但会返回模拟音频。
2. **临时文件**: 所有上传的参考音频和生成的输出音频都会在处理完成后自动删除。
3. **音频格式**: 输入的参考音频和输出的生成音频均为 WAV 格式。
4. **采样率**: 输出音频的采样率为 24000 Hz。
