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

from .resource_manager import ResourceManager, ParamType, Level
from .image_generator import ImageGenerator

@register("chunithm_bot", "Ku2uka", "CHUNITHM机器人", "1.0.1")
class ChunithmBot(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_root = Path(get_astrbot_data_path())
        self.res_mgr = ResourceManager("astrbot_plugin_chunithm_bot", data_root)
        self.img_gen = ImageGenerator("astrbot_plugin_chunithm_bot", self.res_mgr, data_root)
        asyncio.create_task(self.initialize())
    
    async def initialize(self):
        """初始化加载数据"""
        await self.res_mgr.load_data()
        logger.info(f"导入曲目列表成功，共 {len(self.res_mgr.songs)} 首歌曲")

        self.res_mgr.load_user_data()
        logger.info(f"导入用户数据成功，共 {len(self.res_mgr.user_data)} 个用户账号记录")

        self.res_mgr.load_api_key()
    
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

            # 分析参数           
            param_type = ParamType.CONST
            level = Level.L14
            const = 14.2

            # 调用create_dsb生成图片
            image_path = await self.img_gen.create_dsb(param_type, const)  # 假设把参数传给create_dsb
            
            # 检查图片是否生成成功
            if image_path and os.path.exists(image_path):
                # 返回图片
                yield event.image_result(image_path)
                
                # 可选：清理临时文件
                # self.image_gen.cleanup_old_files()
            else:
                yield event.plain_result("图片生成失败")
        else:
            yield event.plain_result("指令格式错误，正确格式：/chu dsb [难度或定数]")

    @filter.command("bind")
    async def cmd_bind(self, event: AstrMessageEvent):
        """绑定落雪账号。用法：/bind 或 /bind [好友码]"""
        qq_number = event.get_sender_id()
        full_message = event.message_str
        parts = full_message.split()
        if len(parts) <= 1:
            reply = await self.res_mgr.get_friend_code(qq_number)
            yield event.plain_result(reply)

            oauth_url = "https://maimai.lxns.net/oauth/authorize?response_type=code&client_id=a4f37a4e-c6c4-4ab4-a48a-4b815f06b8d4&redirect_uri=urn%3Aietf%3Awg%3Aoauth%3A2.0%3Aoob&scope=read_user_profile+read_player"
            yield event.plain_result(oauth_url)

    @filter.command("b30")
    async def cmd_b30(self, event: AstrMessageEvent):
        """查询b30。用法：/b30"""
        qq_number = event.get_sender_id()
        friend_code = await self.res_mgr.get_friend_code(qq_number)
        if friend_code == None:
            yield event.plain_result("你还未绑定你的账号！")
            return
        data = await self.res_mgr.get_b30(friend_code)
        song = data['bests'][0]['song_name']
        yield event.plain_result(song)

    @filter.command("aj30")
    async def cmd_aj30(self, event: AstrMessageEvent):
        """查询aj30。用法：/aj30"""
        pass

    @filter.command("overpower")
    async def cmd_overpower(self, event: AstrMessageEvent):
        """查询overpower。用法：/overpower"""
        qq_number = event.get_sender_id()
        friend_code = await self.res_mgr.get_friend_code(qq_number)
        full_message = event.message_str
        parts = full_message.split()
        if len(parts) <= 1 or (len(parts) >= 2 and parts[1] == 'level'):
            data = await self.res_mgr.get_overpower_level(friend_code)
        elif parts[1] == 'version':
            pass
    
    @filter.command("s_refresh")
    async def cmd_refresh(self, event: AstrMessageEvent):
        '''手动刷新数据（管理员用）'''
        await self.res_mgr.load_data(force_refresh=True)
        yield event.plain_result(f"数据刷新完成！当前共 {len(self.res_mgr.songs)} 首歌曲")
    
    @filter.command("s_debug")
    async def cmd_debug(self, event: AstrMessageEvent):
        '''调试模式：显示搜索分数'''
        message = event.message_str.strip()
        parts = message.split(maxsplit=1)
        
        if len(parts) < 2:
            yield event.plain_result("请提供搜索关键词")
            return
        
        keyword = parts[1]
        
        if not self.res_mgr.songs:
            yield event.plain_result("数据正在加载中...")
            return
        
        # 获取带分数的结果
        if not keyword or not self.res_mgr.songs:
            yield event.plain_result("无结果")
            return
        
        keyword = keyword.lower().strip()
        debug_results = []
        
        for song in self.res_mgr.songs[:50]:  # 只检查前50首，避免刷屏
            if song.get('id', 9999) >= 8000:
                continue

            title = song.get('title', '').lower()
            aliases = [a.lower() for a in song.get('aliases', [])]
            
            # 计算分数（用同样的逻辑）
            score = 0
            if keyword == 'c' + str(song.get('id', 9999)):
                score = 100
            elif keyword == title:
                score = 100
            elif keyword in aliases:
                score = 95
            elif keyword in title:
                score = 90
            elif any(keyword in alias for alias in aliases):
                score = 85
            else:
                title_score = fuzz.token_sort_ratio(keyword, title)
                alias_scores = [fuzz.token_sort_ratio(keyword, alias) for alias in aliases]
                alias_score = max(alias_scores) if alias_scores else 0
                raw_score = max(title_score, alias_score)
                score = min(raw_score, 89)
            
            if score >= 60:
                debug_results.append((score, song))
        
        debug_results.sort(key=lambda x: x[0], reverse=True)
        
        reply = f"调试结果（关键词：{keyword}）：\n\n"
        for score, song in debug_results[:10]:
            reply += f"[{score}分] {song.get('title')}\n"
        
        yield event.plain_result(reply)