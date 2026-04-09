import asyncio

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, Image, File
from astrbot.core.message.message_event_result import MessageChain
from aiohttp import web, ClientSession, ClientError
import hashlib
import hmac
import json
import time
import markdown


@register("astrbot_plugin_daily_stock_analysis_adapter", "棒棒糖", "DailyStockAnalysis适配器插件", "1.1.0")
class DailyStockAnalysisAdapter(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.webhook_port = config.get("webhook_port", 8080)
        self.webhook_path = config.get("webhook_path", "/stock-analysis")
        self.secret_key = config.get("secret_key")
        self.enable_signature_verification = config.get("enable_signature_verification", False)
        self.target_groups = config.get("target_groups", [])  # List[str]
        
        # API相关配置
        self.api_base_url = config.get("api_base_url", "").strip()
        self.api_auth_password = config.get("api_auth_password", "")
        self.enable_batch_analysis = config.get("enable_batch_analysis", False)
        self.default_report_type = config.get("default_report_type", "detailed")
        self.report_extra_content = config.get("report_extra_content", "")
        self.http_session = None
        self.session_cookie = None  # 存储登录session
        
        # Web服务相关
        self.web_app = None
        self.today_stock_report = None
        self.runner = None
        self.site = None
        
        # 验证配置
        if not self.enable_signature_verification:
            logger.warning(f"每日股票分析适配器:警告！当前未启用签名验证，请自行服务仅可内部网络访问")
        if self.enable_signature_verification and self.secret_key is None:
            raise ValueError("每日股票分析适配器:密钥未配置！")
        
        # 记录API配置状态
        if self.api_base_url:
            logger.info(f"每日股票分析适配器:API功能已启用，API地址: {self.api_base_url}")
            logger.info(f"每日股票分析适配器:批量分析功能: {'已启用' if self.enable_batch_analysis else '未启用'}")
            logger.info(f"每日股票分析适配器:默认报告类型: {self.default_report_type}")
            if self.report_extra_content:
                logger.info(f"每日股票分析适配器:已配置报告额外内容，长度: {len(self.report_extra_content)}")
        else:
            logger.info("每日股票分析适配器:API功能未启用，dsa系列命令将不可用")

        
    async def initialize(self):
        """初始化插件，启动HTTP服务"""
        try:
            # 初始化HTTP session（用于API调用）
            if self.api_base_url:
                self.http_session = ClientSession()
                logger.info("每日股票分析适配器:HTTP客户端已初始化")
                
                # 如果配置了密码，尝试登录获取session
                if self.api_auth_password:
                    await self._api_login()

            # 启动HTTP服务
            await self.start_http_server()
            
            logger.info(f"每日股票分析适配器:股票分析适配器插件已启动，监听端口: {self.webhook_port}")
            logger.info(f"每日股票分析适配器:Webhook路径: {self.webhook_path}")
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:插件初始化失败: {e}")
            raise

    async def _api_login(self):
        """登录API获取session cookie"""
        if not self.api_base_url or not self.api_auth_password:
            return
        
        try:
            url = f"{self.api_base_url}/api/v1/auth/login"
            payload = {"password": self.api_auth_password}
            logger.info(f"每日股票分析适配器:正在登录API: {url}")
            
            async with self.http_session.post(url, json=payload) as resp:
                if resp.status == 200:
                    # 从响应头中获取cookie
                    cookies = resp.cookies
                    if "dsa_session" in cookies:
                        self.session_cookie = cookies["dsa_session"].value
                        logger.info("每日股票分析适配器:API登录成功，已获取session")
                    else:
                        logger.warning("每日股票分析适配器:API登录成功但未收到session cookie")
                elif resp.status == 401:
                    error_data = await resp.json()
                    logger.error(f"每日股票分析适配器:API登录失败，密码错误: {error_data}")
                else:
                    error_text = await resp.text()
                    logger.error(f"每日股票分析适配器:API登录失败，状态码: {resp.status}, 响应: {error_text}")
        except Exception as e:
            logger.error(f"每日股票分析适配器:API登录异常: {e}")

    def _get_api_headers(self):
        """获取API请求头，包含认证cookie"""
        headers = {}
        if self.session_cookie:
            headers["Cookie"] = f"dsa_session={self.session_cookie}"
        return headers

    async def _api_request(self, method, url, **kwargs):
        """发送API请求，自动处理401重登，返回(status, data)元组"""
        if not self.http_session:
            raise Exception("HTTP session未初始化")
        
        # 添加认证头
        headers = kwargs.pop("headers", {})
        headers.update(self._get_api_headers())
        
        logger.debug(f"每日股票分析适配器:发送{method}请求到: {url}")
        
        async with self.http_session.request(method, url, headers=headers, **kwargs) as resp:
            status = resp.status
            
            # 如果是401且配置了密码，尝试重新登录后重试
            if status == 401 and self.api_auth_password:
                logger.warning("每日股票分析适配器:API返回401，尝试重新登录")
                await self._api_login()
                
                # 使用新session重试
                headers.update(self._get_api_headers())
                async with self.http_session.request(method, url, headers=headers, **kwargs) as retry_resp:
                    retry_status = retry_resp.status
                    if retry_status == 200:
                        try:
                            retry_data = await retry_resp.json()
                        except:
                            retry_data = await retry_resp.text()
                        return retry_status, retry_data
                    else:
                        try:
                            retry_data = await retry_resp.json()
                        except:
                            retry_data = await retry_resp.text()
                        return retry_status, retry_data
            
            # 正常处理响应
            if status == 200:
                try:
                    data = await resp.json()
                except:
                    data = await resp.text()
                return status, data
            else:
                try:
                    data = await resp.json()
                except:
                    data = await resp.text()
                return status, data

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
                    logger.warning("每日股票分析适配器:签名验证失败")
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
                {'error': "服务发生异常"},
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
            #提取markdown内容
            content = data.get('content') or data.get('message') or data.get('text', '')
            if not content:
                logger.warning("每日股票分析适配器:缺少content/message/text字段")
                return
            #渲染图片
            rendered_image_url = await self.render_html_to_image(content)
            self.today_stock_report = rendered_image_url
            # 发送给目标群组和用户
            await self.send_to_targets(rendered_image_url)
            
        except Exception as e:
            logger.error(f"每日股票分析适配器:处理股票分析数据时出错: {e}")
            raise

    async def render_html_to_image(self, markdown_content: str) -> str:
        """将Markdown渲染为图片，自动拼接报告额外内容"""
        try:
            # 拼接报告额外内容
            if self.report_extra_content:
                markdown_content = markdown_content + self.report_extra_content
                logger.debug(f"每日股票分析适配器:已拼接报告额外内容，最终长度: {len(markdown_content)}")
            
            md = markdown.Markdown(extensions=['tables', 'fenced_code', 'nl2br'])
            html_content = md.convert(markdown_content)
            
            options = {"quality": 95, "device_scale_factor_level": "ultra", "viewport_width": 1200}
            rendered_image_url = await self.html_render(html_content, {}, options=options)
            return rendered_image_url

        except Exception as e:
            logger.error(f"每日股票分析适配器:Markdown渲染失败: {e}")
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
                await self.runner.cleanup()
            if self.site:
                await self.site.stop()
            if self.web_app:
                await self.web_app.shutdown()
                await self.web_app.cleanup()
                self.web_app = None
            if self.http_session:
                await self.http_session.close()
                logger.info("每日股票分析适配器:HTTP客户端已关闭")
            logger.info("每日股票分析适配器:股票分析适配器插件已停止")
        except Exception as e:
            logger.error(f"每日股票分析适配器:插件终止时出错: {e}")

    # ==================== API 命令 ====================

    def _check_api_enabled(self):
        """检查API是否启用"""
        if not self.api_base_url:
            return False, "api未启用"
        return True, None

    @filter.command("dsa健康检查")
    async def dsa_health_check(self, event: AstrMessageEvent):
        """检查API服务健康状态"""
        user_id = event.get_sender_id()
        logger.info(f"每日股票分析适配器:[dsa健康检查] 用户 {user_id} 调用命令")
        
        # 检查API是否启用
        enabled, msg = self._check_api_enabled()
        if not enabled:
            logger.warning(f"每日股票分析适配器:[dsa健康检查] API未启用，用户: {user_id}")
            yield event.plain_result(msg)
            return
        
        try:
            url = f"{self.api_base_url}/api/health"
            logger.info(f"每日股票分析适配器:[dsa健康检查] 发送请求到: {url}")
            
            status, data = await self._api_request("GET", url)
            logger.info(f"每日股票分析适配器:[dsa健康检查] 响应状态码: {status}")
            
            if status == 200:
                status_text = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
                timestamp = data.get("timestamp", "N/A") if isinstance(data, dict) else "N/A"
                
                result = f"✅ API服务健康\n状态: {status_text}\n时间: {timestamp}"
                logger.info(f"每日股票分析适配器:[dsa健康检查] 健康检查成功: {data}")
                yield event.plain_result(result)
            else:
                logger.error(f"每日股票分析适配器:[dsa健康检查] 健康检查失败，状态码: {status}, 响应: {data}")
                yield event.plain_result(f"❌ API服务异常，状态码: {status}")
                    
        except ClientError as e:
            logger.error(f"每日股票分析适配器:[dsa健康检查] 连接失败: {e}")
            yield event.plain_result(f"❌ 无法连接到API服务: {str(e)}")
        except Exception as e:
            logger.error(f"每日股票分析适配器:[dsa健康检查] 发生异常: {e}", exc_info=True)
            yield event.plain_result(f"❌ 健康检查失败: {str(e)}")

    @filter.command("dsa分析")
    async def dsa_analyze(self, event: AstrMessageEvent, stock_code: str = None, report_type: str = None):
        """
        触发股票分析
        用法: dsa分析 <股票代码> [报告类型]
        示例: dsa分析 600519
              dsa分析 600519,000858 detailed
        """
        user_id = event.get_sender_id()
        logger.info(f"每日股票分析适配器:[dsa分析] 用户 {user_id} 调用命令，参数: stock_code={stock_code}, report_type={report_type}")
        
        # 检查API是否启用
        enabled, msg = self._check_api_enabled()
        if not enabled:
            logger.warning(f"每日股票分析适配器:[dsa分析] API未启用，用户: {user_id}")
            yield event.plain_result(msg)
            return
        
        # 验证参数
        if not stock_code:
            help_text = """用法: dsa分析 <股票代码> [报告类型]
示例:
  dsa分析 600519            # 分析单只股票
  dsa分析 00100.HK detailed # 使用指定报告类型
  dsa分析 TSLA,NVDA         # 批量分析（需开启批量分析功能）（使用英文逗号分隔）

报告类型: simple, detailed, full, brief"""
            yield event.plain_result(help_text)
            return
        
        try:
            # 确保stock_code是字符串类型
            stock_code = str(stock_code)
            logger.debug(f"每日股票分析适配器:[dsa分析] 处理后的stock_code: {stock_code}, 类型: {type(stock_code)}")
            
            # 解析股票代码
            stock_codes = [code.strip() for code in stock_code.split(",")]
            is_batch = len(stock_codes) > 1
            
            # 检查批量分析权限
            if is_batch and not self.enable_batch_analysis:
                logger.warning(f"每日股票分析适配器:[dsa分析] 用户 {user_id} 尝试批量分析但未启用该功能")
                yield event.plain_result("❌ 批量分析功能未启用，请联系管理员")
                return
            
            # 确定报告类型
            final_report_type = report_type or self.default_report_type
            if final_report_type not in ["simple", "detailed", "full", "brief"]:
                logger.warning(f"每日股票分析适配器:[dsa分析] 无效的报告类型: {final_report_type}")
                yield event.plain_result(f"❌ 无效的报告类型: {final_report_type}，可选: simple, detailed, full, brief")
                return
            
            # 构建请求体
            url = f"{self.api_base_url}/api/v1/analysis/analyze"
            if is_batch:
                payload = {
                    "stock_codes": stock_codes,
                    "report_type": final_report_type,
                    "async_mode": True
                }
            else:
                payload = {
                    "stock_code": stock_codes[0],
                    "report_type": final_report_type,
                    "async_mode": True
                }
            
            logger.info(f"每日股票分析适配器:[dsa分析] 发送请求到: {url}, 参数: {payload}")
            
            status, data = await self._api_request("POST", url, json=payload)
            logger.info(f"每日股票分析适配器:[dsa分析] 响应状态码: {status}")
            
            if status == 202 and isinstance(data, dict):
                if is_batch:
                    # 批量任务响应
                    accepted = data.get("accepted", [])
                    duplicates = data.get("duplicates", [])
                    message = data.get("message", "")
                    
                    result_parts = [f"✅ 批量分析任务已提交\n{message}\n"]
                    
                    if accepted:
                        result_parts.append("\n📋 已接受的任务:")
                        for task in accepted:
                            result_parts.append(f"  • {task.get('stock_code', 'N/A')}: {task.get('status', 'N/A')} (ID: {task.get('task_id', 'N/A')})")
                    
                    if duplicates:
                        result_parts.append("\n⚠️ 重复的任务:")
                        for dup in duplicates:
                            result_parts.append(f"  • {dup.get('stock_code', 'N/A')}: {dup.get('message', 'N/A')}")
                    
                    result = "\n".join(result_parts)
                    logger.info(f"每日股票分析适配器:[dsa分析] 批量任务提交成功，已接受: {len(accepted)}, 重复: {len(duplicates)}")
                else:
                    # 单任务响应
                    task_id = data.get("task_id", "N/A")
                    task_status = data.get("status", "N/A")
                    message = data.get("message", "分析任务已接受")
                    
                    result = f"✅ {message}\n\n任务ID: {task_id}\n状态: {task_status}\n\n可使用 'dsa任务列表' 查看进度"
                    logger.info(f"每日股票分析适配器:[dsa分析] 单任务提交成功，任务ID: {task_id}")
                
                yield event.plain_result(result)
                
            elif status == 409 and isinstance(data, dict):
                # 重复提交
                error_msg = data.get("message", "股票正在分析中")
                existing_task_id = data.get("existing_task_id", "N/A")
                logger.warning(f"每日股票分析适配器:[dsa分析] 重复提交: {error_msg}, 现有任务ID: {existing_task_id}")
                yield event.plain_result(f"⚠️ {error_msg}\n现有任务ID: {existing_task_id}")
                
            elif status == 400:
                logger.error(f"每日股票分析适配器:[dsa分析] 请求参数错误: {data}")
                yield event.plain_result(f"❌ 请求参数错误: {data}")
                
            else:
                logger.error(f"每日股票分析适配器:[dsa分析] 请求失败，状态码: {status}, 响应: {data}")
                yield event.plain_result(f"❌ 分析请求失败，状态码: {status}")
                    
        except ClientError as e:
            logger.error(f"每日股票分析适配器:[dsa分析] 连接失败: {e}")
            yield event.plain_result(f"❌ 无法连接到API服务: {str(e)}")
        except Exception as e:
            logger.error(f"每日股票分析适配器:[dsa分析] 发生异常: {e}", exc_info=True)
            yield event.plain_result(f"❌ 分析请求失败: {str(e)}")

    @filter.command("dsa任务列表")
    async def dsa_task_list(self, event: AstrMessageEvent, status_filter: str = None):
        """
        获取股票分析任务列表
        用法: dsa任务列表 [状态筛选]
        示例: dsa任务列表
              dsa任务列表 processing
              dsa任务列表 pending,processing
        """
        user_id = event.get_sender_id()
        logger.info(f"每日股票分析适配器:[dsa任务列表] 用户 {user_id} 调用命令，状态筛选: {status_filter}")
        
        # 检查API是否启用
        enabled, msg = self._check_api_enabled()
        if not enabled:
            logger.warning(f"每日股票分析适配器:[dsa任务列表] API未启用，用户: {user_id}")
            yield event.plain_result(msg)
            return
        
        try:
            # 构建查询参数
            params = {}
            if status_filter:
                params["status"] = status_filter
            params["limit"] = 5  # 只显示最近5个任务
            
            url = f"{self.api_base_url}/api/v1/analysis/tasks"
            logger.info(f"每日股票分析适配器:[dsa任务列表] 发送请求到: {url}, 参数: {params}")
            
            status, data = await self._api_request("GET", url, params=params)
            logger.info(f"每日股票分析适配器:[dsa任务列表] 响应状态码: {status}")
            
            if status == 200 and isinstance(data, dict):
                total = data.get("total", 0)
                pending = data.get("pending", 0)
                processing = data.get("processing", 0)
                tasks = data.get("tasks", [])
                
                if not tasks:
                    result = "📋 当前没有分析任务"
                    logger.info(f"每日股票分析适配器:[dsa任务列表] 任务列表为空")
                else:
                    result_parts = [
                        f"📋 分析任务列表",
                        f"总计: {total} | 等待中: {pending} | 处理中: {processing}\n"
                    ]
                    
                    # 状态图标映射
                    status_icons = {
                        "pending": "⏳",
                        "processing": "🔄",
                        "completed": "✅",
                        "failed": "❌"
                    }
                    
                    for task in tasks:
                        task_id = task.get("task_id", "N/A")[:8]  # 截取前8位
                        stock_code = task.get("stock_code", "N/A")
                        stock_name = task.get("stock_name", "")
                        task_status = task.get("status", "unknown")
                        progress = task.get("progress", 0)
                        message = task.get("message", "")
                        
                        icon = status_icons.get(task_status, "❓")
                        name_display = f" {stock_name}" if stock_name else ""
                        progress_display = f" {progress}%" if task_status == "processing" else ""
                        message_display = f" - {message}" if message else ""
                        
                        result_parts.append(f"{icon} {stock_code}{name_display} ({task_id}){progress_display}{message_display}")
                    
                    result = "\n".join(result_parts)
                    logger.info(f"每日股票分析适配器:[dsa任务列表] 获取到 {len(tasks)} 个任务")
                
                yield event.plain_result(result)
                
            else:
                logger.error(f"每日股票分析适配器:[dsa任务列表] 请求失败，状态码: {status}, 响应: {data}")
                yield event.plain_result(f"❌ 获取任务列表失败，状态码: {status}")
                    
        except ClientError as e:
            logger.error(f"每日股票分析适配器:[dsa任务列表] 连接失败: {e}")
            yield event.plain_result(f"❌ 无法连接到API服务: {str(e)}")
        except Exception as e:
            logger.error(f"每日股票分析适配器:[dsa任务列表] 发生异常: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取任务列表失败: {str(e)}")