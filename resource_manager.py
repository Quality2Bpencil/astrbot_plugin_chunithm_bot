import aiohttp
import json
from pathlib import Path
from astrbot.api import logger

class ResourceManager:
    """资源管理器：负责歌曲数据的加载"""
    VERSION_MAP = {0: '未知'}
    
    def __init__(self, plugin_name: str, data_root: Path):
        """
        Args:
            plugin_name: 插件名，用于创建插件专属目录
            data_root: AstrBot 数据根目录
        """
        self.plugin_dir = data_root / "plugin_data" / plugin_name
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.songs_file = self.plugin_dir / "songs.json"
        self.songs = []
    
    async def load_data(self, force_refresh: bool = False) -> list:
        """
        加载歌曲数据（优先本地，可选强制刷新）
        
        Returns:
            list: 歌曲列表
        """
        if force_refresh or len(self.VERSION_MAP) <= 1:
            await self.fetch_from_api()
            return self.songs
        
        # 尝试从本地加载
        if self.songs_file.exists():
            try:
                with open(self.songs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.songs = data.get('songs', [])
                logger.info(f"从本地加载了 {len(self.songs)} 首歌曲")
                return self.songs
            except Exception as e:
                logger.error(f"读取本地文件失败: {e}")
        
        # 本地没有，从API获取
        await self.fetch_from_api()
        return self.songs
    
    async def fetch_from_api(self):
        """从API获取歌曲和别名数据"""
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
                    versions = data.get("versions")
                    for version in versions:
                        self.VERSION_MAP[version.get('version', 0)] = version.get('title', '未知')
                
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
                with open(self.songs_file, 'w', encoding='utf-8') as f:
                    json.dump({"songs": self.songs}, f, ensure_ascii=False, indent=2)
                
                logger.info(f"从API加载了 {len(self.songs)} 首歌曲")
                
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            self.songs = []