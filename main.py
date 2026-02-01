import asyncio

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, Image, File
from astrbot.core.message.message_event_result import MessageChain
from aiohttp import web
import hashlib
import hmac
import json
import time
import os
from typing import Dict, List, Optional

@register("astrbot_plugin_daily_stock_analysis_adapter", "棒棒糖", "DailyStockAnalysis适配器插件", "1.0.0")
class DailyStockAnalysisAdapter(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.webhook_port = config.get("webhook_port", 8080)
        self.webhook_path = config.get("webhook_path", "/stock-analysis")
        self.secret_key = config.get("secret_key")
        self.enable_signature_verification = config.get("enable_signature_verification", False)
        self.target_groups = config.get("target_groups", [])  # List[str]
        self.web_app = None
        self.today_stock_report = None
        self.runner = None
        self.site = None

        if self.enable_signature_verification and self.secret_key is None:
            raise ValueError("每日股票分析适配器:密钥未配置！")

        
    async def initialize(self):
        """初始化插件，启动HTTP服务"""
        try:

            # 启动HTTP服务
            await self.start_http_server()
            
            logger.info(f"每日股票分析适配器:股票分析适配器插件已启动，监听端口: {self.webhook_port}")
            logger.info(f"每日股票分析适配器:Webhook路径: {self.webhook_path}")
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:插件初始化失败: {e}")
            raise

    async def start_http_server(self):
        """启动HTTP服务"""
        self.web_app = web.Application()
        
        # 注册路由
        self.web_app.router.add_post(self.webhook_path, self.handle_webhook)
        self.web_app.router.add_get(self.webhook_path, self.health_check)
        
        # 启动服务
        self.runner = web.AppRunner(self.web_app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.webhook_port)
        await self.site.start()
        
        logger.info(f"每日股票分析适配器:HTTP服务已启动在端口 {self.webhook_port}")

    async def health_check(self, request):
        """健康检查接口"""
        return web.json_response({
            'status': 'ok',
            'plugin': 'daily_stock_analysis_adapter',
            'timestamp': time.time()
        })

    async def handle_webhook(self, request):
        """处理Webhook请求"""
        try:
            # 获取请求数据
            data = await request.json()
            headers = dict(request.headers)
            
            logger.info(f"每日股票分析适配器:收到Webhook请求: {data}")
            
            # 验证签名
            if self.enable_signature_verification:
                if not await self.verify_signature(data, headers):
                    logger.warning("签名验证失败")
                    return web.json_response(
                        {'error': 'Signature verification failed'}, 
                        status=401
                    )
            
            # 处理消息
            await self.process_stock_analysis(data)
            
            return web.json_response({'status': 'success'})
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:处理Webhook请求时出错: {e}")
            return web.json_response(
                {'error': str(e)}, 
                status=500
            )

    async def verify_signature(self, data: dict, headers: dict) -> bool:
        """验证请求签名"""
        try:
            # 获取签名
            logger.info(f"header:{headers}")
            signature = headers.get('X-Signature') or headers.get('Signature')
            if not signature:
                logger.warning("每日股票分析适配器:请求缺少签名")
                return False
            
            # 准备签名数据
            timestamp = headers.get('X-Timestamp')
            if not timestamp:
                logger.warning("每日股票分析适配器:请求缺少时间戳")
                return False
            if not self.secret_key:
                logger.warning("每日股票分析适配器:服务端缺少密钥")
                return False
            payload = json.dumps(data, sort_keys=True)
            sign_data = f"{timestamp}.{payload}".encode('utf-8')
            
            # 计算期望签名
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                sign_data,
                hashlib.sha256
            ).hexdigest()
            
            # 比较签名
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:签名验证出错: {e}")
            return False

    async def process_stock_analysis(self, data: dict):
        """处理股票分析数据"""
        try:
            # 提取HTML内容
            html_content = data.get('content', '')
            if not html_content:
                logger.warning("每日股票分析适配器:缺少content字段")
                return
            
            # 渲染HTML为图片
            rendered_image_url = await self.render_html_to_image(html_content)
            self.today_stock_report = rendered_image_url
            # 发送给目标群组和用户
            await self.send_to_targets(rendered_image_url)
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:处理股票分析数据时出错: {e}")
            raise

    async def render_html_to_image(self, html_content: str) -> str:
        """将HTML渲染为图片"""
        try:
            # 使用Astrbot的HTML渲染器
            # 这里假设Astrbot提供了HTML渲染功能
            options = {"quality": 95, "device_scale_factor_level": "ultra", "viewport_width": 800}
            rendered_image_url = await self.html_render(html_content,{}, options=options)
            return rendered_image_url

        except Exception as e:
            logger.error(f"每日股票分析适配器:HTML渲染失败: {e}")
            raise

    async def send_to_targets(self, image_data: str):
        """发送消息给目标群组和用户"""
        try:
            message_chain = MessageChain([Image.fromURL(image_data)])
            # 发送到配置的群
            for group_id in self.target_groups:
                logger.info(f"每日股票分析适配器:股票分析：向群组 {group_id} 发送图片")
                await self.context.send_message(group_id, message_chain)
                await asyncio.sleep(1)  # 防风控延迟
                
        except Exception as e:
            logger.error(f"每日股票分析适配器:发送消息时出错: {e}")
            raise

    @filter.command("今天股票")
    async def manual_report(self, event: AstrMessageEvent):
        try:
            if not self.today_stock_report:
                yield event.plain_result("每日股票分析适配器:没有今天股票分析")
            # 生成HTML图片
            logger.info("每日股票分析适配器:股票分析：手动报告生成成功")
            yield event.image_result(self.today_stock_report)
        except Exception as e:
            logger.error(f"每日股票分析适配器:股票分析：手动报告生成失败: {e}", exc_info=True)
            yield event.plain_result(f"每日股票分析适配器:生成报告失败: {str(e)}")

    async def terminate(self):
        """插件销毁时清理资源"""
        try:
            if self.runner:
                await self.runner.shutdown()
            if self.web_app:
                await self.web_app.shutdown()
                await self.web_app.cleanup()
                self.web_app = None
            logger.info("每日股票分析适配器:股票分析适配器插件已停止")
        except Exception as e:
            logger.error(f"每日股票分析适配器:插件终止时出错: {e}")
