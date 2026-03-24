from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import astrbot.api.message_components as Comp
from astrbot.api.event import MessageChain
import aiohttp
import asyncio
import json
import re
import os
from pathlib import Path
from thefuzz import fuzz

from .resource_manager import ResourceManager
from .image_generator import ImageGenerator
from .web_server import OAuthWebServer

@register("chunithm_bot", "Ku2uka", "CHUNITHM机器人", "1.0.1")
class ChunithmBot(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_root = Path(get_astrbot_data_path())
        self.res_mgr = ResourceManager("astrbot_plugin_chunithm_bot", data_root)
        self.img_gen = ImageGenerator("astrbot_plugin_chunithm_bot", self.res_mgr, data_root)
        self.web_server = OAuthWebServer(self.res_mgr)
        asyncio.create_task(self.initialize())
    
    async def initialize(self):
        """初始化加载数据"""
        await self.res_mgr.load_data()
        logger.info(f"导入曲目列表成功，共 {len(self.res_mgr.songs)} 首歌曲")

        self.res_mgr.load_config()
        logger.info(f"导入config成功！")

        self.web_server.start()
        logger.info(f"启动OAuth网页成功")
    
    def search_song(self, keyword, threshold=60):
        """
        搜索歌曲（按优先级：完全匹配 > 包含匹配 > 模糊匹配）
        
        Args:
            keyword: 搜索关键词
            threshold: 模糊匹配阈值 (0-100)
        
        Returns:
            list: 匹配的歌曲列表（按分数排序）
        """
        if not keyword or not self.res_mgr.songs:
            return []
        
        keyword = keyword.lower().strip()
        scored_results = []
        
        for song in self.res_mgr.songs:
            # 跳过特定ID范围的歌曲（保留你的逻辑）
            if song.get('id', 9999) >= 8000:
                continue

            title = song.get('title', '').lower()
            aliases = [a.lower() for a in song.get('aliases', [])]
            
            score = 0

            # 0. 通过ID搜索（格式：c1234）
            if keyword == 'c' + str(song.get('id', 9999)):
                score = 100
            
            # 1. 完全匹配曲名 (100分)
            elif keyword == title:
                score = 100
            
            # 2. 完全匹配别称 (95分)
            elif keyword in aliases:
                score = 95
            
            # 3. 关键词在曲名中 (90分)
            elif keyword in title:
                score = 90
            
            # 4. 关键词在别称中 (85分)
            elif any(keyword in alias for alias in aliases):
                score = 85
            
            # 5. 模糊匹配 (最高89分)
            else:
                # 和曲名模糊匹配
                title_score = fuzz.token_sort_ratio(keyword, title)
                # 和别称模糊匹配
                alias_scores = [fuzz.token_sort_ratio(keyword, alias) for alias in aliases]
                alias_score = max(alias_scores) if alias_scores else 0
                
                raw_score = max(title_score, alias_score)
                score = min(raw_score, 89)  # 模糊匹配不超过89分
            
            # 只有分数达到阈值才加入结果
            if score >= threshold:
                scored_results.append((score, song))
        
        # 按分数从高到低排序
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        # 只选出分数最高的曲子（可以并列）
        result = []
        if scored_results:
            max_score = scored_results[0][0]
            for score, song in scored_results:
                if score < max_score:
                    break
                result.append(song)
        
        return result
    
    @filter.regex(r"^(.*?)是什么歌$")
    async def cmd_search(self, event: AstrMessageEvent):
        '''搜索歌曲。用法：xxx是什么歌'''      
        # 从消息文本中提取关键词
        message = event.message_str.strip()
        
        match = re.search(r"^(.*?)是什么歌$", message)
        if not match:
            return
        
        keyword = match.group(1).strip()

        # 确保数据已加载
        if not self.res_mgr.songs:
            yield event.plain_result("数据正在加载中，请稍后重试...")
            return
            
        # 执行搜索
        results = self.search_song(keyword)
        
        if not results:
            yield event.plain_result(f"没有找到相关的歌曲")
            return
        
        # 构建回复
        if len(results) == 1: # 只有一个结果时，回复带曲绘的消息链
            song = results[0]
            song_id = song.get('id', 0)
            title = song.get('title', '未知曲名')
            # 文字部分
            text_part = f"c{song_id} - {title}\n"
            # 信息图
            img_path = await self.img_gen.create_song_info_image(results[0])

            # 发送图文消息
            yield event.chain_result([
                Comp.Plain(text_part),
                Comp.Image.fromFileSystem(str(img_path))  # 从本地调用
            ])
            
        else:
            text_part = f"搜索到了 {len(results)} 首不同的曲目：\n"
            for song in results:
                song_id = song.get('id', 0)
                title = song.get('title', '未知曲名')
                text_part += f"c{song_id} - {title}\n"
            yield event.plain_result(text_part)

    @filter.command("dsb")
    async def cmd_dsb(self, event: AstrMessageEvent):
        """生成定数表。用法：/dsb [难度或定数]"""
        full_message = event.message_str
        parts = full_message.split()
        if len(parts) >= 2:
            param = parts[1]  # 获取难度或定数参数

            song_list = self.res_mgr.get_dsb(param)

            if song_list is None or song_list == {}:
                yield event.plain_result("未找到符合条件的歌曲，请检查输入的难度或定数是否正确。")
                return

            # 调用create_dsb生成图片
            image_path = await self.img_gen.create_dsb_image(data=song_list)
            
            # 检查图片是否生成成功
            if image_path and os.path.exists(image_path):
                # 返回图片
                yield event.image_result(image_path)
                
                # 清理临时文件
                self.res_mgr.cleanup_old_files()
            else:
                yield event.plain_result("图片生成失败")
        else:
            yield event.plain_result("指令格式错误，正确格式：/dsb [难度或定数]")

    @filter.command("bind")
    async def cmd_bind(self, event: AstrMessageEvent):
        """绑定落雪账号。用法：/bind"""
        full_message = event.message_str
        parts = full_message.split()
        qq_number = str(event.get_sender_id())
        if len(parts) <= 1:
            status = await self.res_mgr.bind_by_qq(qq_number)
            if status == None:
                reply = "你的落雪账号没有绑定你的QQ账号！请前往 落雪官网 -> 账号详情 -> 第三方应用 -> 第三方账号绑定 以绑定你的QQ账号！\n"
            else:
                reply = "好友码绑定成功！\n"

            if event.is_private_chat():
                oauth_link = self.res_mgr.oauth_app.get('oauth_link') + self.res_mgr.encode(qq_number)
                reply += f"如果想要使用完整功能（如/list），请点击以下链接以授权：\n{oauth_link}\n"
            else:
                reply += "如果想要使用完整功能（如/list），请在私聊中发送 /bind 来获取授权链接！"

            yield event.plain_result(reply)

    async def _get_best_result(self, event: AstrMessageEvent):
        """查询best成绩的核心逻辑，返回 (error_msg, image_path)"""
        qq_number = str(event.get_sender_id())
        friend_code = await self.res_mgr.get_friend_code(qq_number)
        if friend_code is None:
            return "你还未绑定你的账号！", None
        data = await self.res_mgr.get_b30(friend_code)
        player = await self.res_mgr.get_player(friend_code)
        if data is None or player is None:
            return "你的账号数据异常！", None
        image_path = await self.img_gen.create_b30_image(data, player_name=player.get("name", "CHUNITHM"))
        return None, image_path

    @filter.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息。用法：/help"""
        image_path = str(self.res_mgr.help_image)
        yield event.image_result(image_path)

    @filter.command("b30")
    async def cmd_b30(self, event: AstrMessageEvent):
        """查询b30。用法：/b30"""
        error, image_path = await self._get_best_result(event)
        if error:
            yield event.plain_result(error)
        else:
            yield event.image_result(image_path)
            # 清理临时文件
            self.res_mgr.cleanup_old_files()

    @filter.command("b50")
    async def cmd_b50(self, event: AstrMessageEvent):
        """查询b50。用法：/b50"""
        error, image_path = await self._get_best_result(event)
        if error:
            yield event.plain_result(error)
        else:
            yield event.image_result(image_path)
            # 清理临时文件
            self.res_mgr.cleanup_old_files()

    async def _get_max_best(self, event: AstrMessageEvent):
        """查询理论b30"""
        data = await self.res_mgr.get_max_best()
        image_path = await self.img_gen.create_b30_image(data, player_name="Max Rating")
        if image_path is None:
            return "查询理论Rating失败！", None
        else:
            return None, image_path

    @filter.command("max30")
    async def cmd_max30(self, event: AstrMessageEvent):
        """查询理论b30。用法：/max30"""
        error, image_path = await self._get_max_best(event)
        if error:
            yield event.plain_result(error)
        else:
            yield event.image_result(image_path)
            # 清理临时文件
            self.res_mgr.cleanup_old_files()

    @filter.command("max50")
    async def cmd_max50(self, event: AstrMessageEvent):
        """查询理论b50。用法：/max50"""
        error, image_path = await self._get_max_best(event)
        if error:
            yield event.plain_result(error)
        else:
            yield event.image_result(image_path)
            # 清理临时文件
            self.res_mgr.cleanup_old_files()

    @filter.command("overpower")
    async def cmd_overpower(self, event: AstrMessageEvent):
        """查询overpower。用法：/overpower"""
        qq_number = str(event.get_sender_id())
        friend_code = await self.res_mgr.get_friend_code(qq_number)
        if friend_code is None:
            yield event.plain_result("你还未绑定你的账号！")
            return
        full_message = event.message_str
        parts = full_message.split()
        if len(parts) <= 1 or (len(parts) >= 2 and parts[1] == 'level'):
            data = await self.res_mgr.get_overpower_level(qq_number)
            player = await self.res_mgr.get_player(friend_code)
            if data is None or player is None:
                yield event.plain_result("你还未绑定你的账号！")
                return
            image_path = await self.img_gen.create_overpower_image(data=data, player_name=player.get("name", "CHUNITHM"), arg="level")
            yield event.image_result(image_path)
            self.res_mgr.cleanup_old_files()
        elif parts[1] == 'version' or parts[1] == 'ver':
            data = await self.res_mgr.get_overpower_version(qq_number)
            player = await self.res_mgr.get_player(friend_code)
            if data is None or player is None:
                yield event.plain_result("你还未绑定你的账号！")
                return
            image_path = await self.img_gen.create_overpower_image(data=data, player_name=player.get("name", "CHUNITHM"), arg="version")
            yield event.image_result(image_path)
            self.res_mgr.cleanup_old_files()
        elif parts[1] == 'genre' or parts[1] == 'type':
            data = await self.res_mgr.get_overpower_genre(qq_number)
            player = await self.res_mgr.get_player(friend_code)
            if data is None or player is None:
                yield event.plain_result("你还未绑定你的账号！")
                return
            image_path = await self.img_gen.create_overpower_image(data=data, player_name=player.get("name", "CHUNITHM"), arg="genre")
            yield event.image_result(image_path)
            self.res_mgr.cleanup_old_files()
        else:
            yield event.plain_result("指令格式错误，正确格式：/overpower level/version/genre")

    @filter.command("list")
    async def cmd_list(self, event: AstrMessageEvent):
        """查询list。用法：/list"""
        qq_number = str(event.get_sender_id())
        logger.info(f"用户 {qq_number} 请求查询list")
        friend_code = await self.res_mgr.get_friend_code(qq_number)
        if friend_code is None:
            yield event.plain_result("你还未绑定你的账号！")
            return
        
        full_message = event.message_str
        parts = full_message.split()

        if len(parts) >= 2:
            param = parts[1]  # 获取难度或定数参数

            song_list = await self.res_mgr.get_list(param, qq_number)

            if song_list is None or song_list == {}:
                yield event.plain_result("未找到符合条件的歌曲，请检查输入的难度或定数是否正确。")
                return
            
            player = await self.res_mgr.get_player(friend_code)
            if player is None:
                yield event.plain_result("你还未绑定你的账号！")
                return

            # 调用create_dsb生成图片
            image_path = await self.img_gen.create_list_image(data=song_list, player_name=player.get("name", "CHUNITHM"))
            
            # 检查图片是否生成成功
            if image_path and os.path.exists(image_path):
                # 返回图片
                yield event.image_result(image_path)
                
                # 清理临时文件
                self.res_mgr.cleanup_old_files()
            else:
                yield event.plain_result("图片生成失败")
        else:
            yield event.plain_result("指令格式错误，正确格式：/list [难度或定数]")

    @filter.command("s_refresh")
    async def cmd_refresh(self, event: AstrMessageEvent):
        '''手动刷新数据（管理员用）'''
        # 检查是否是管理员
        if not event.is_admin():
            yield event.plain_result("抱歉，只有管理员才能使用此命令。")
        else:
            await self.res_mgr.load_data(force_refresh=True)
            yield event.plain_result(f"数据刷新完成！当前共 {len(self.res_mgr.songs)} 首歌曲")

            self.res_mgr.load_config()
            logger.info(f"导入config成功！")