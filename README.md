# 股票分析适配器插件

这是一个为Astrbot设计的股票分析报告适配器插件，可以接收外部系统的股票分析HTML报告，并通过Astrbot将其发送给指定的群组或用户。

## 功能特性

- ✅ 接收HTTP Webhook请求
- ✅ 支持请求签名验证
- ✅ HTML内容渲染为图片
- ✅ 发送消息到指定群组和用户
- ✅ 可配置的安全设置
- ✅ 管理指令支持

## 安装方式

1. 将整个插件文件夹复制到Astrbot的`data/plugins/`目录下
2. 重启Astrbot
3. 在Astrbot配置文件中添加插件配置（参考config_example.yaml）
4. 在插件管理界面启用插件

## 配置说明

在Astrbot的主配置文件中添加以下配置：

```yaml
daily_stock_analysis_adapter:
  webhook_port: 8080
  webhook_path: "/stock-analysis"
  secret_key: "your_secret_key_here"
  enable_signature_verification: true
  target_groups:
    - "group_id_1"
    - "group_id_2"
  target_users:
    - "user_id_1"
    - "user_id_2"
```

## 使用方法

### 1. 发送Webhook请求

向插件暴露的HTTP接口发送POST请求：

```bash
curl -X POST http://your-server:8080/stock-analysis \
  -H "Content-Type: application/json" \
  -H "X-Signature: your_signature" \
  -H "X-Timestamp: $(date +%s)" \
  -d '{
    "content": "<html>...</html>",
    "description": "今日股票分析报告"
  }'
```

### 2. 签名计算方法

签名使用HMAC-SHA256算法计算：

```
signature = HMAC-SHA256(secret_key, timestamp + "." + JSON(payload))
```

Python示例：
```python
import hmac
import hashlib
import json
import time

def calculate_signature(secret_key, payload):
    timestamp = str(int(time.time()))
    payload_json = json.dumps(payload, sort_keys=True)
    sign_data = f"{timestamp}.{payload_json}".encode('utf-8')
    signature = hmac.new(
        secret_key.encode('utf-8'),
        sign_data,
        hashlib.sha256
    ).hexdigest()
    return signature, timestamp
```

### 3. 管理指令

在聊天中使用以下指令管理插件：

- `/stockconfig help` - 显示帮助信息
- `/stockconfig show` - 显示当前配置

## API接口

### POST /stock-analysis

接收股票分析报告的Webhook接口

**请求头:**
- `Content-Type: application/json`
- `X-Signature: <signature>` (可选，当启用签名验证时必需)
- `X-Timestamp: <timestamp>` (可选，用于签名计算)

**请求体:**
```json
{
  "content": "<html>股票分析报告HTML内容</html>",
  "description": "报告描述信息"
}
```

**响应:**
```json
{
  "status": "success"
}
```

### GET /stock-analysis

健康检查接口

**响应:**
```json
{
  "status": "ok",
  "plugin": "daily_stock_analysis_adapter",
  "timestamp": 1234567890
}
```

## 开发依赖

- aiohttp>=3.8.0
- cryptography>=3.4.0

## 注意事项

1. 确保配置的端口没有被其他服务占用
2. 建议在生产环境中启用签名验证
3. HTML渲染功能依赖Astrbot的HTML渲染器
4. 目标群组和用户ID需要根据实际使用的平台获取

## 支持

如有问题，请提交Issue或联系开发者。
