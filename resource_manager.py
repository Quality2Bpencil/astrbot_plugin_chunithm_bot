import aiohttp
import asyncio
import json
from pathlib import Path
from astrbot.api import logger
from curl_cffi.requests import AsyncSession
from enum import Enum

class ResourceManager:
    """资源管理器：负责歌曲数据的加载"""
    
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
        self.song_map = {}
        self.version_map = {0: "UNKNOWN"}
        self.jackets_dir = self.plugin_dir / "jackets"
        self.jackets_dir.mkdir(exist_ok=True)  # 确保目录存在
        self.user_data = {}
        self.user_data_file = self.plugin_dir / "user_data.json" # 用户QQ号对应好友码的dict
        self.developer_api_key = ""
        self.config_file = self.plugin_dir / "config.json"

    def load_api_key(self):
        """获取开发者API密钥"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.developer_api_key = data.get("developer_api_key")
            except Exception as e:
                logger.error(f"读取API密钥失败: {e}")

    def load_user_data(self):
        """加载用户列表"""
        if self.user_data_file.exists():
            try:
                with open(self.user_data_file, 'r', encoding='utf-8') as f:
                    self.user_data = json.load(f)
            except Exception as e:
                logger.error(f"读取用户列表失败: {e}")

        return self.user_data
    
    def save_user_data(self):
        """将用户列表导入json"""
        if self.user_data:
            try:
                with open(self.user_data_file, 'w', encoding='utf-8') as f:
                    json.dump(self.user_data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                logger.error(f"保存用户列表失败: {e}")
    
    async def load_data(self, force_refresh: bool = False) -> list:
        """
        加载歌曲数据（优先本地，可选强制刷新）
        
        Returns:
            list: 歌曲列表
        """
        if force_refresh: # or len(self.VERSION_MAP) <= 1:
            await self.fetch_from_api()
            return self.songs
        
        # 尝试从本地加载
        if self.songs_file.exists():
            try:
                with open(self.songs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.songs = data.get('songs', [])
                    for song in self.songs:
                        self.song_map[song.get('id',0)] = song
                    versions = data.get('versions', [])
                    for version in versions:
                        self.version_map[version.get('version', 0)] = version.get('title', '未知')
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
                versions = []
                # 获取歌曲列表
                async with session.get(url_songs, params={"version": 23000, "notes": "true"}) as resp:
                    if resp.status != 200:
                        raise Exception(f"歌曲API返回错误: {resp.status}")
                    data = await resp.json()
                    songs = data.get("songs", [])
                    for song in self.songs:
                        self.song_map[song.get('id',0)] = song
                    # 获取版本
                    versions = data.get("versions")
                    for version in versions:
                        self.version_map[version.get('version', 0)] = version.get('title', '未知')
                
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
                    json.dump({"songs": self.songs, "versions": versions}, f, ensure_ascii=False, indent=2)
                
                logger.info(f"从API加载了 {len(self.songs)} 首歌曲")
                
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            self.songs = []

    async def get_jacket(self, song_id: int) -> Path:
        """
        获取曲绘文件路径
        
        Args:
            song_id: 歌曲ID
        
        Returns:
            Path: 曲绘文件的本地路径
        """
        # 构造本地文件路径
        jacket_path = self.jackets_dir / f"{song_id}.png"
        
        # 1. 如果本地已有，直接返回
        if jacket_path.exists():
            logger.info(f"从本地加载曲绘: {song_id}")
            return jacket_path
        
        # 2. 本地没有，从API下载
        logger.info(f"正在下载曲绘: {song_id}")
        url = f"https://assets2.lxns.net/chunithm/jacket/{song_id}.png"
        
        try:
            async with AsyncSession(impersonate="chrome") as session:
                r = await session.get(url, timeout=10)
                
                if r.status_code == 200:
                    # 保存到本地
                    with open(jacket_path, 'wb') as f:
                        f.write(r.content)
                    logger.info(f"曲绘下载成功: {song_id}")
                    return jacket_path
                else:
                    logger.error(f"曲绘下载失败 {song_id}: {r.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"曲绘下载异常 {song_id}: {e}")
            return None
        
    async def get_from_developer_api(self, url, total_time=10):
        headers = {
            "Authorization": self.developer_api_key
        }
        # 创建超时配置（默认为10秒）
        timeout = aiohttp.ClientTimeout(total=total_time)
        
        try:
            # 使用aiohttp发起异步请求
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    # 获取响应状态码和文本
                    status = response.status
                    text = await response.text()
                    
                    logger.debug(f"HTTP状态码: {status}")
                    
                    # 处理HTTP错误
                    if status == 401:
                        logger.error("API密钥无效或未授权，请检查你的developer_api_key")
                        return None
                    elif status == 404:
                        logger.info(f"未查询到该用户！")
                        return None
                    elif status != 200:
                        logger.error(f"HTTP错误 {status}: {text[:200]}")  # 只记录前200字符
                        return None
                    
                    # 尝试解析JSON
                    try:
                        data = await response.json()
                        # 检查请求是否成功
                        if data.get("success"):
                            return data['data']
                        else:
                            error_msg = data.get("message", "未知错误")
                            logger.error(f"API返回错误: {error_msg}")
                            return None
                    except Exception as e:
                        logger.error(f"JSON解析失败: {e}, 响应内容: {text[:200]}")
                        return None
                        
            logger.error(f"请求超时 ({total_time}秒): {url}")
            return None
        except aiohttp.ClientConnectorError as e:
            logger.error(f"网络连接失败: {e}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"HTTP客户端错误: {e}")
            return None
        except Exception as e:
            logger.exception(f"发生未预期的错误: {e}")
            return None
        
    async def get_friend_code(self, qq_number, total_time=10):
        if self.user_data.get(qq_number):
            logger.info(f"成功在本地查询到{qq_number}的好友码")
            return self.user_data[qq_number]
        else:
            logger.info(f"没有在本地查询到{qq_number}的好友码，正在向落雪查询好友码...")
            return await self.bind_by_qq(qq_number, total_time=total_time)

    async def bind_by_qq(self, qq_number, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/qq/{qq_number}"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data.get('friend_code'):
            if data['friend_code'] == self.user_data.get(qq_number):
                logger.info(f"QQ号{qq_number}已与落雪账号绑定，不需重复绑定")
                return data['friend_code']
            else:
                logger.info(f"QQ号{qq_number}绑定落雪账号成功！")
                self.user_data[qq_number] = data['friend_code']
                self.save_user_data()
                return data['friend_code']
        else:
            logger.error("绑定失败！")

    async def get_b30(self, friend_code, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/{friend_code}/bests"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data == None:
            logger.error("查询b30失败！")
        else:
            logger.info("查询b30成功！")

        return data
        
    async def get_overpower_level(self, friend_code, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/{friend_code}/scores"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data == None:
            logger.error("查询overpower失败！")
            return None
        
        score = data[0].get('score', 'fail')
        logger.info(score)
        
        total_op = {}
        user_op = {}
        
        for score in data:
            if score.get('level_index') != 3 and score.get('level_index') != 4:
                continue
        
class ParamType(Enum):
    LEVEL = 0
    CONST = 1

class Level(Enum):
    L14 = (14.0, 14.4)
    L14P = (14.5, 14.9)
    L15 = (15.0, 15.4)
    L15P = (15.5, 15.9)