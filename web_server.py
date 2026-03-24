"""
Web 服务器 - 处理 OAuth 回调
"""
from flask import Flask, request, redirect, url_for, jsonify
import threading
from astrbot.api import logger
from urllib.parse import urlencode
import asyncio

from .resource_manager import ResourceManager

class OAuthWebServer:
    """OAuth Web 服务器类"""
    
    def __init__(self, resource_manager, host='0.0.0.0', port=5000):
        """
        初始化 Web 服务器
        
        Args:
            resource_manager: ResourceManager 实例
            host: 监听地址
            port: 监听端口
        """
        self.res_mgr = resource_manager
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self._setup_routes()
        self.server_thread = None
        
    def _setup_routes(self):
        """设置路由"""
        
        @self.app.route('/')
        def home():
            """首页 - 获取授权码"""
            state = request.args.get('state') # 用户QQ号
            code = request.args.get('code') # 授权码
            
            if code and state:
                # 如果有 code 和 state，说明是授权回调
                logger.info(f"收到授权回调 - state: {state}, code: {code}")
                try:
                    # 在同步函数中调用异步方法
                    success = asyncio.run(self.res_mgr.handle_oauth(qq_number=state, code=code))
                    if success:
                        return "✅ 授权成功！"
                    return "❌ 授权失败：token保存失败或授权码无效，请查看日志。"
                except Exception as e:
                    logger.error(f"处理授权失败: {e}")
                    return f"❌ 授权失败: {str(e)}"
            else:
                logger.info("授权失败：没有收到code或state")
                return "授权失败"
        
    
    def start(self):
        """启动 Web 服务器（非阻塞）"""
        if self.server_thread and self.server_thread.is_alive():
            logger.warning("Web 服务器已在运行")
            return
        
        def run():
            logger.info(f"在 {self.host}:{self.port} 启动 Web 服务器")
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        
        self.server_thread = threading.Thread(target=run, daemon=True)
        self.server_thread.start()
        logger.info(f"✅ Web 服务器已启动，访问 http://{self.host}:{self.port}")
    
    def stop(self):
        """停止 Web 服务器"""
        # Flask 没有简单的停止方法，这里只是记录日志
        logger.info("Web 服务器将在主程序退出时停止")