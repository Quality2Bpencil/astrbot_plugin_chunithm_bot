from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import aiohttp
import asyncio
import json
import re
from pathlib import Path
from thefuzz import fuzz

@register("chunithm_bot", "Ku2uka", "CHUNITHM机器人", "1.0.1")
class ChunithmBot(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.songs = []
        # 获取 AstrBot 数据根目录，并拼接出插件专属的数据目录
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        # 确保目录存在
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        # 数据文件路径
        self.data_file = plugin_data_dir / "songs.json"
        
        # 启动时异步加载数据
        asyncio.create_task(self.initialize())
    
    async def initialize(self):
        """初始化插件"""
        try:
            await self.load_data()
            logger.info(f"曲目数据加载成功，共 {len(self.songs)} 首歌曲")
        except Exception as e:
            logger.error(f"曲目数据加载失败: {e}")
    
    async def load_data(self, force_refresh=False):
        """加载数据（先从本地，没有再请求API）"""
        if force_refresh:
            await self.load_data_from_api()
            return
        
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.songs = data.get('songs', [])
                logger.info(f"从本地加载了 {len(self.songs)} 首歌曲")
                return
            except Exception as e:
                logger.info(f"本地数据加载失败: {e}，将重新从API获取")
        
        await self.load_data_from_api()
    
    async def load_data_from_api(self):
        """从API导入数据"""
        logger.info("正在从API加载曲目数据...")
        
        url_songs = "https://maimai.lxns.net/api/v0/chunithm/song/list"
        url_alias = "https://maimai.lxns.net/api/v0/chunithm/alias/list"
        
        try:
            async with aiohttp.ClientSession() as session:
                # 获取歌曲列表
                async with session.get(url_songs, params={"version": 23000, "notes": "true"}) as resp:
                    if resp.status != 200:
                        raise Exception(f"歌曲API返回错误: {resp.status}")
                    data = await resp.json()
                    songs = data.get("songs", [])
                
                # 获取别名
                async with session.get(url_alias) as resp_alias:
                    if resp_alias.status == 200:
                        alias_data = await resp_alias.json()
                        alias_map = {item['song_id']: item['aliases'] 
                                for item in alias_data.get('aliases', [])}
                        
                        for song in songs:
                            song['aliases'] = alias_map.get(song['id'], [])
                        logger.info(f"获取到 {len(alias_map)} 首歌曲的别名")
                    else:
                        for song in songs:
                            song['aliases'] = []
                        logger.warning(f"别名API返回错误: {resp_alias.status}")
                
                    # 保存到本地
                self.songs = songs
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump({"songs": self.songs}, f, ensure_ascii=False, indent=2)
                
                logger.info(f"从API加载了 {len(self.songs)} 首歌曲")
                
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            self.songs = []
    
    def search_song(self, keyword, threshold=60):
        """
        搜索歌曲（按优先级：完全匹配 > 包含匹配 > 模糊匹配）
        
        Args:
            keyword: 搜索关键词
            threshold: 模糊匹配阈值 (0-100)
        
        Returns:
            list: 匹配的歌曲列表（按分数排序）
        """
        if not keyword or not self.songs:
            return []
        
        keyword = keyword.lower().strip()
        scored_results = []
        
        for song in self.songs:
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
        '''搜索歌曲，用法：xxx是什么歌'''      
        # 从消息文本中提取关键词
        message = event.message_str.strip()
        
        match = re.search(r"^(.*?)是什么歌$", message)
        if not match:
            return
        
        keyword = match.group(1).strip()

        # 确保数据已加载
        if not self.songs:
            yield event.plain_result("数据正在加载中，请稍后重试...")
            return
            
        # 执行搜索
        results = self.search_song(keyword)
        
        if not results:
            yield event.plain_result(f"没有找到与「{keyword}」相关的歌曲")
            return
        
        # 构建回复
        if len(results) == 1:
            reply = f"找到 1 首相关歌曲：\n\n"
        else:
            reply = f"找到 {len(results)} 首相关歌曲：\n\n"
        
        for i, song in enumerate(results, 1):
            reply += f"{i}. 🎵 {song.get('title')}\n"
            
            # 显示别名
            aliases = song.get('aliases', [])
            if aliases:
                alias_text = '、'.join(aliases[:3])
                if len(aliases) > 3:
                    alias_text += f'等{len(aliases)}个'
                reply += f"   📝 别名：{alias_text}\n"
            
            if i < len(results):
                reply += "   ────────────\n"
        
        yield event.plain_result(reply)
    
    @filter.command("s_refresh")
    async def cmd_refresh(self, event: AstrMessageEvent):
        '''手动刷新数据（管理员用）'''
        await self.load_data(force_refresh=True)
        yield event.plain_result(f"数据刷新完成！当前共 {len(self.songs)} 首歌曲")
    
    @filter.command("s_debug")
    async def cmd_debug(self, event: AstrMessageEvent):
        '''调试模式：显示搜索分数'''
        message = event.message_str.strip()
        parts = message.split(maxsplit=1)
        
        if len(parts) < 2:
            yield event.plain_result("请提供搜索关键词")
            return
        
        keyword = parts[1]
        
        if not self.songs:
            yield event.plain_result("数据正在加载中...")
            return
        
        # 获取带分数的结果
        if not keyword or not self.songs:
            yield event.plain_result("无结果")
            return
        
        keyword = keyword.lower().strip()
        debug_results = []
        
        for song in self.songs[:50]:  # 只检查前50首，避免刷屏
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