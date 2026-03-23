import aiohttp
import asyncio
import json
from pathlib import Path
from astrbot.api import logger
from curl_cffi.requests import AsyncSession
from enum import Enum
import time

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
        self.user_data = {'qq_number': {}, 'token': {}}
        self.user_data_file = self.plugin_dir / "user_data.json" # 用户QQ号对应好友码与token的dict
        self.developer_api_key = ""
        self.oauth_app = {}
        self.config_file = self.plugin_dir / "config.json"
        self.version_abbr_map = {
            10000: "ORI",
            10500: "ORI+",
            11000: "AIR",
            11500: "AIR+",
            12000: "STAR",
            12500: "STAR+",
            13000: "AMZ",
            13500: "AMZ+",
            14000: "CRY",
            14500: "CRY+",
            15000: "PARA",
            15500: "PARA×",
            20000: "NEW",
            20500: "NEW+",
            21000: "SUN",
            21500: "SUN+",
            22000: "LMN",
            22500: "LMN+",
            23000: "VRS",
            23500: "VRSX"
        }
        self.genre_abbr_map = {
            "流行 & 动漫": "P&A",
            "niconico": "nico",
            "东方Project": "东方",
            "其他游戏": "其他",
            "彩绿": "彩绿",
            "音击舞萌": "击舞",
            "原创": "原创"
        }

    def load_config(self):
        """获取开发者API密钥与OAuth应用信息"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.developer_api_key = data.get("developer_api_key")
                    self.oauth_app = data.get('oauth_app')
            except Exception as e:
                logger.error(f"读取API密钥与OAuth应用信息失败: {e}")

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

    async def handle_oauth(self, qq_number, code):
        """
        处理 OAuth 授权回调
        
        Args:
            qq_number: 用户的QQ号
            code: 授权码      
        """
        try:
            # 1. 用 code 换取 token（异步HTTP请求）
            token_data = await self._exchange_code(code)
            
            # 2. 验证token数据
            if not token_data or 'access_token' not in token_data:
                return None
            
            # 3. 计算过期时间
            current_time = int(time.time())
            token_data['expires_at'] = current_time + token_data.get('expires_in', 900) # 默认过期时间是15min
            token_data['updated_at'] = current_time
            
            # 4. 保存到用户token字典
            self.user_data['token'][qq_number] = token_data
            
            # 5. 保存到文件
            self.save_user_data()
            
            # 6. 记录成功日志
            logger.info(f"✅ 用户 {qq_number} 授权成功！")
            logger.info(f"   access_token: {token_data['access_token'][:20]}...")
            
        except asyncio.TimeoutError:
            logger.error("请求超时，服务器可能暂时无法访问")
        except aiohttp.ClientConnectorError:
            logger.error("网络连接失败，请检查服务器网络")
        except aiohttp.ClientResponseError as e:
            logger.error(f"服务器返回错误: {e.status}")
        except json.JSONDecodeError:
            logger.error("服务器返回数据格式错误")
        except Exception as e:
            logger.error(f"未知错误: {str(e)}")

    async def _exchange_code(self, code: str):
        """
        异步用授权码换取token
        
        Args:
            code: 授权码
            
        Returns:
            token数据字典
        """
        # 设置超时
        timeout = aiohttp.ClientTimeout(total=30)
        url = "https://maimai.lxns.net/api/v0/oauth/token"
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url=url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.oauth_app.get('client_id'),
                    "client_secret": self.oauth_app.get('client_secret'),
                    "redirect_uri": self.oauth_app.get('redirect_uri')
                }
            ) as response:
                # 检查响应状态
                if response.status != 200:
                    error_text = await response.text()
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=response.status,
                        message=error_text
                    )
                
                # 解析JSON
                result = await response.json()
                
                # 处理嵌套的data字段
                if 'data' in result:
                    return result['data']
                return result

    async def get_access_token(self, qq_number: str):
        logger.info("进行111：get access token")
        if qq_number not in self.user_data['token']:
            return None

        logger.info("进行222：get access token")

        try:
            # 1. 刷新token
            refresh_token = self.user_data['token'][qq_number].get('refresh_token')
            token_data = await self._refresh_access_token(refresh_token)
            
            # 2. 验证token数据
            if not token_data or 'access_token' not in token_data:
                return None
            
            # 3. 计算过期时间
            current_time = int(time.time())
            token_data['expires_at'] = current_time + token_data.get('expires_in', 900) # 默认过期时间是15min
            token_data['updated_at'] = current_time
            
            # 4. 保存到用户token字典
            self.user_data['token'][qq_number] = token_data
            
            # 5. 保存到文件
            self.save_user_data()
            
            # 6. 记录成功日志
            logger.info(f"✅ 用户 {qq_number} 刷新token成功！")

            return token_data
            
        except asyncio.TimeoutError:
            logger.error("请求超时，服务器可能暂时无法访问")
        except aiohttp.ClientConnectorError:
            logger.error("网络连接失败，请检查服务器网络")
        except aiohttp.ClientResponseError as e:
            logger.error(f"服务器返回错误: {e.status}")
        except json.JSONDecodeError:
            logger.error("服务器返回数据格式错误")
        except Exception as e:
            logger.error(f"未知错误: {str(e)}")
        
    async def _refresh_access_token(self, refresh_token: str):
        """
        刷新访问令牌
        """
        # 设置超时
        timeout = aiohttp.ClientTimeout(total=30)
        url = "https://maimai.lxns.net/api/v0/oauth/token"

        logger.info("获取刷新令牌……")
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url=url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.oauth_app.get('client_id'),
                    "client_secret": self.oauth_app.get('client_secret'),
                    "refresh_token": refresh_token
                }
            ) as response:
                # 检查响应状态
                if response.status != 200:
                    error_text = await response.text()
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=response.status,
                        message=error_text
                    )
                
                # 解析JSON
                result = await response.json()
                
                # 处理嵌套的data字段
                if 'data' in result:
                    return result['data']
                return result
    
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
                        self.song_map[song.get('id', 0)] = song
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
                    for song in songs:
                        self.song_map[song.get('id', 0)] = song
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
        
    async def get_from_developer_api(self, url, total_time=10, headers={}):
        if headers == {}:
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
        if self.user_data.get("qq_number", {}).get(qq_number):
            logger.info(f"成功在本地查询到{qq_number}的好友码")
            return self.user_data["qq_number"][qq_number]
        else:
            logger.info(f"没有在本地查询到{qq_number}的好友码，正在向落雪查询好友码...")
            return await self.bind_by_qq(qq_number, total_time=total_time)

    async def bind_by_qq(self, qq_number, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/qq/{qq_number}"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data != None and data.get('friend_code'):
            if data['friend_code'] == self.user_data.get("qq_number", {}).get(qq_number):
                logger.info(f"QQ号{qq_number}已与落雪账号绑定，不需重复绑定")
                return data['friend_code']
            else:
                logger.info(f"QQ号{qq_number}绑定落雪账号成功！")
                self.user_data['qq_number'][qq_number] = data['friend_code']
                self.save_user_data()
                return data['friend_code']
        else:
            logger.error("绑定失败！")
        
    async def get_player(self, friend_code, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/{friend_code}"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data == None:
            logger.error("查询玩家信息失败！")
        else:
            logger.info("查询玩家信息成功！")

        return data

    async def get_b30(self, friend_code, total_time=10):
        url = f"https://maimai.lxns.net/api/v0/chunithm/player/{friend_code}/bests"
        data = await self.get_from_developer_api(url=url, total_time=total_time)

        if data == None:
            logger.error("查询b30失败！")
        else:
            logger.info("查询b30成功！")

        for score in data.get('bests', []):
            if 'id' in score:
                jacket_path = await self.get_jacket(score['id'])
                score['jacket_path'] = jacket_path

        for score in data.get('new_bests', []):
            if 'id' in score:
                jacket_path = await self.get_jacket(score['id'])
                score['jacket_path'] = jacket_path

        return data
        
    async def get_overpower_level(self, qq_number: str, total_time=10):
        token_data = await self.get_access_token(qq_number)
        url = "https://maimai.lxns.net/api/v0/user/chunithm/player/scores"
        headers = {
            "Authorization": token_data.get("token_type","") + " " + token_data.get("access_token","")
        }
        data = await self.get_from_developer_api(url=url, total_time=total_time, headers=headers)

        if data == None:
            logger.error("查询overpower失败！")
            return None
        
        #score = data[0]
        #logger.info(f"overpwer: {score.get('over_power', 0)}")
        
        level_list = []
        total_op = {}
        user_op = {}
        all_cnt = {}
        ajc_cnt = {}
        aj_cnt = {}
        fc_cnt = {}
        sssp_cnt = {}
        sss_cnt = {}

        for song in self.songs:
            # 紫谱
            if len(song.get("difficulties", [{}])) == 4:
                level = song.get("difficulties", [{}])[3].get("level", '0')
                const = song.get("difficulties", [{}])[3].get("level_value", 0)
                if level not in level_list:
                    level_list.append(level)
                    total_op[level] = 0
                    user_op[level] = 0
                    all_cnt[level] = 0
                    ajc_cnt[level] = 0
                    aj_cnt[level] = 0
                    fc_cnt[level] = 0
                    sssp_cnt[level] = 0
                    sss_cnt[level] = 0
                total_op[level] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[level] += 1

            # 黑谱
            if len(song.get("difficulties", [{}])) == 5:
                level = song.get("difficulties", [{}])[4].get("level", '0')
                const = song.get("difficulties", [{}])[4].get("level_value", 0)
                if level not in level_list:
                    level_list.append(level)
                    total_op[level] = 0
                    user_op[level] = 0
                    all_cnt[level] = 0
                    ajc_cnt[level] = 0
                    aj_cnt[level] = 0
                    fc_cnt[level] = 0
                    sssp_cnt[level] = 0
                    sss_cnt[level] = 0
                total_op[level] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[level] += 1

        op_list = {} # 防止有重复的成绩，dict的格式为：(song_id, level_index): (overpower, full_combo, rank)
        
        for score in data:
            song_id = score.get('id')
            level_index = score.get('level_index')
            overpower = self.calc_overpower(score)
            full_combo = score.get('full_combo')
            rank = score.get('rank')
            if (level_index != 3 and level_index != 4) or song_id is None or overpower is None:
                continue
            # 必须要是最高难度
            if level_index != len(self.song_map[song_id].get("difficulties", [])) - 1:
                continue
            
            if (song_id, level_index) not in op_list:
                op_list[(song_id, level_index)] = (overpower, full_combo, rank)
            # 如果有重复成绩，保留更好的成绩
            elif op_list[(song_id, level_index)][0] < overpower:
                op_list[(song_id, level_index)] = (overpower, full_combo, rank)

        for key, value in op_list.items(): # value 为 (overpower, full_combo, rank)
            song_id, level_index = key
            overpower, full_combo, rank = value
            level = self.song_map[song_id]['difficulties'][level_index].get('level', '0')

            user_op[level] += overpower

            if full_combo == "alljusticecritical":
                ajc_cnt[level] += 1
                aj_cnt[level] += 1
                fc_cnt[level] += 1
            elif full_combo == "alljustice":
                aj_cnt[level] += 1
                fc_cnt[level] += 1
            elif full_combo == "fullcombo":
                fc_cnt[level] += 1

            if rank == "sssp":
                sssp_cnt[level] += 1
                sss_cnt[level] += 1
            elif rank == "sss":
                sss_cnt[level] += 1

        result = {
            "ALL": {
                "all": 0,
                "ajc": 0,
                "aj": 0,
                "fc": 0,
                "sssp": 0,
                "sss": 0,
                "user_op": 0,
                "total_op": 0
            }
        }
        level_list.sort(reverse=True)
        
        for level in level_list:
            result[level] = {
                "all": all_cnt[level],
                "ajc": ajc_cnt[level],
                "aj": aj_cnt[level],
                "fc": fc_cnt[level],
                "sssp": sssp_cnt[level],
                "sss": sss_cnt[level],
                "user_op": user_op[level],
                "total_op": total_op[level]
            }
            result["ALL"]['all'] += all_cnt[level]
            result["ALL"]['ajc'] += ajc_cnt[level]
            result["ALL"]['aj'] += aj_cnt[level]
            result["ALL"]['fc'] += fc_cnt[level]
            result["ALL"]['sssp'] += sssp_cnt[level]
            result["ALL"]['sss'] += sss_cnt[level]
            result["ALL"]['user_op'] += user_op[level]
            result["ALL"]['total_op'] += total_op[level]

        logger.info("计算OVERPOWER完成")

        return result
    
    async def get_overpower_version(self, qq_number: str, total_time=10):
        token_data = await self.get_access_token(qq_number)
        url = "https://maimai.lxns.net/api/v0/user/chunithm/player/scores"
        headers = {
            "Authorization": token_data.get("token_type","") + " " + token_data.get("access_token","")
        }
        data = await self.get_from_developer_api(url=url, total_time=total_time, headers=headers)

        if data == None:
            logger.error("查询overpower失败！")
            return None
        
        version_list = []
        total_op = {}
        user_op = {}
        all_cnt = {}
        ajc_cnt = {}
        aj_cnt = {}
        fc_cnt = {}
        sssp_cnt = {}
        sss_cnt = {}

        for song in self.songs:
            # 紫谱
            if len(song.get("difficulties", [{}])) == 4:
                version = song.get("difficulties", [{}])[3].get("version", '0')
                const = song.get("difficulties", [{}])[3].get("level_value", 0)
                if version not in version_list:
                    version_list.append(version)
                    total_op[version] = 0
                    user_op[version] = 0
                    all_cnt[version] = 0
                    ajc_cnt[version] = 0
                    aj_cnt[version] = 0
                    fc_cnt[version] = 0
                    sssp_cnt[version] = 0
                    sss_cnt[version] = 0
                total_op[version] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[version] += 1

            # 黑谱
            if len(song.get("difficulties", [{}])) == 5:
                version = song.get("difficulties", [{}])[4].get("version", '0')
                const = song.get("difficulties", [{}])[4].get("level_value", 0)
                if version not in version_list:
                    version_list.append(version)
                    total_op[version] = 0
                    user_op[version] = 0
                    all_cnt[version] = 0
                    ajc_cnt[version] = 0
                    aj_cnt[version] = 0
                    fc_cnt[version] = 0
                    sssp_cnt[version] = 0
                    sss_cnt[version] = 0
                total_op[version] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[version] += 1

        op_list = {} # 防止有重复的成绩，dict的格式为：song_id: (overpower, full_combo, rank)
        
        for score in data:
            song_id = score.get('id')
            level_index = score.get('level_index')
            overpower = self.calc_overpower(score)
            full_combo = score.get('full_combo')
            rank = score.get('rank')
            if (level_index != 3 and level_index != 4) or song_id is None or overpower is None:
                continue
            # 必须要是最高难度
            if level_index != len(self.song_map[song_id].get("difficulties", [])) - 1:
                continue

            if song_id not in op_list:
                op_list[song_id] = (overpower, full_combo, rank)
            # 如果有重复成绩，保留更好的成绩
            elif op_list[song_id][0] < overpower:
                op_list[song_id] = (overpower, full_combo, rank)

        for key, value in op_list.items(): # value 为 (overpower, full_combo, rank)
            song_id = key
            overpower, full_combo, rank = value
            version = self.song_map[song_id].get('version', 0)

            user_op[version] += overpower

            if full_combo == "alljusticecritical":
                ajc_cnt[version] += 1
                aj_cnt[version] += 1
                fc_cnt[version] += 1
            elif full_combo == "alljustice":
                aj_cnt[version] += 1
                fc_cnt[version] += 1
            elif full_combo == "fullcombo":
                fc_cnt[version] += 1

            if rank == "sssp":
                sssp_cnt[version] += 1
                sss_cnt[version] += 1
            elif rank == "sss":
                sss_cnt[version] += 1

        result = {
            "ALL": {
                "all": 0,
                "ajc": 0,
                "aj": 0,
                "fc": 0,
                "sssp": 0,
                "sss": 0,
                "user_op": 0,
                "total_op": 0
            }
        }
        version_list.sort()
        
        for version in version_list:
            result[version] = {
                "all": all_cnt[version],
                "ajc": ajc_cnt[version],
                "aj": aj_cnt[version],
                "fc": fc_cnt[version],
                "sssp": sssp_cnt[version],
                "sss": sss_cnt[version],
                "user_op": user_op[version],
                "total_op": total_op[version]
            }
            result["ALL"]['all'] += all_cnt[version]
            result["ALL"]['ajc'] += ajc_cnt[version]
            result["ALL"]['aj'] += aj_cnt[version]
            result["ALL"]['fc'] += fc_cnt[version]
            result["ALL"]['sssp'] += sssp_cnt[version]
            result["ALL"]['sss'] += sss_cnt[version]
            result["ALL"]['user_op'] += user_op[version]
            result["ALL"]['total_op'] += total_op[version]

        logger.info("计算OVERPOWER完成")

        return result
    
    async def get_overpower_genre(self, qq_number: str, total_time=10):
        token_data = await self.get_access_token(qq_number)
        url = "https://maimai.lxns.net/api/v0/user/chunithm/player/scores"
        headers = {
            "Authorization": token_data.get("token_type","") + " " + token_data.get("access_token","")
        }
        data = await self.get_from_developer_api(url=url, total_time=total_time, headers=headers)

        if data == None:
            logger.error("查询overpower失败！")
            return None
        
        genre_list = []
        total_op = {}
        user_op = {}
        all_cnt = {}
        ajc_cnt = {}
        aj_cnt = {}
        fc_cnt = {}
        sssp_cnt = {}
        sss_cnt = {}

        for song in self.songs:
            # 紫谱
            if len(song.get("difficulties", [{}])) == 4:
                genre = song.get("genre", '未知')
                const = song.get("difficulties", [{}])[3].get("level_value", 0)
                if genre not in genre_list:
                    genre_list.append(genre)
                    total_op[genre] = 0
                    user_op[genre] = 0
                    all_cnt[genre] = 0
                    ajc_cnt[genre] = 0
                    aj_cnt[genre] = 0
                    fc_cnt[genre] = 0
                    sssp_cnt[genre] = 0
                    sss_cnt[genre] = 0
                total_op[genre] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[genre] += 1

            # 黑谱
            if len(song.get("difficulties", [{}])) == 5:
                genre = song.get("genre", '未知')
                const = song.get("difficulties", [{}])[4].get("level_value", 0)
                if genre not in genre_list:
                    genre_list.append(genre)
                    total_op[genre] = 0
                    user_op[genre] = 0
                    all_cnt[genre] = 0
                    ajc_cnt[genre] = 0
                    aj_cnt[genre] = 0
                    fc_cnt[genre] = 0
                    sssp_cnt[genre] = 0
                    sss_cnt[genre] = 0
                total_op[genre] += (const + 3) * 5 # 单曲理论值OP = (定数 + 3) * 5
                all_cnt[genre] += 1

        genre_list = ["流行 & 动漫", "niconico", "东方Project", "其他游戏", "彩绿", "音击舞萌", "原创"]
        op_list = {} # 防止有重复的成绩，dict的格式为：song_id: (overpower, full_combo, rank)
        
        for score in data:
            song_id = score.get('id')
            level_index = score.get('level_index')
            overpower = self.calc_overpower(score)
            full_combo = score.get('full_combo')
            rank = score.get('rank')
            if (level_index != 3 and level_index != 4) or song_id is None or overpower is None:
                continue
            # 必须要是最高难度
            if level_index != len(self.song_map[song_id].get("difficulties", [])) - 1:
                continue

            if song_id not in op_list:
                op_list[song_id] = (overpower, full_combo, rank)
            # 如果有重复成绩，保留更好的成绩
            elif op_list[song_id][0] < overpower:
                op_list[song_id] = (overpower, full_combo, rank)

        for key, value in op_list.items(): # value 为 (overpower, full_combo, rank)
            song_id = key
            overpower, full_combo, rank = value
            genre = self.song_map[song_id].get('genre', '未知')

            user_op[genre] += overpower

            if full_combo == "alljusticecritical":
                ajc_cnt[genre] += 1
                aj_cnt[genre] += 1
                fc_cnt[genre] += 1
            elif full_combo == "alljustice":
                aj_cnt[genre] += 1
                fc_cnt[genre] += 1
            elif full_combo == "fullcombo":
                fc_cnt[genre] += 1

            if rank == "sssp":
                sssp_cnt[genre] += 1
                sss_cnt[genre] += 1
            elif rank == "sss":
                sss_cnt[genre] += 1

        result = {
            "ALL": {
                "all": 0,
                "ajc": 0,
                "aj": 0,
                "fc": 0,
                "sssp": 0,
                "sss": 0,
                "user_op": 0,
                "total_op": 0
            }
        }
        
        for genre in genre_list:
            result[genre] = {
                "all": all_cnt[genre],
                "ajc": ajc_cnt[genre],
                "aj": aj_cnt[genre],
                "fc": fc_cnt[genre],
                "sssp": sssp_cnt[genre],
                "sss": sss_cnt[genre],
                "user_op": user_op[genre],
                "total_op": total_op[genre]
            }
            result["ALL"]['all'] += all_cnt[genre]
            result["ALL"]['ajc'] += ajc_cnt[genre]
            result["ALL"]['aj'] += aj_cnt[genre]
            result["ALL"]['fc'] += fc_cnt[genre]
            result["ALL"]['sssp'] += sssp_cnt[genre]
            result["ALL"]['sss'] += sss_cnt[genre]
            result["ALL"]['user_op'] += user_op[genre]
            result["ALL"]['total_op'] += total_op[genre]

        logger.info("计算OVERPOWER完成")

        return result
    
    def calc_overpower(self, score) -> float:
        score_point = score.get('score', 0)
        level_index = score.get('level_index', 0)
        song_id = score.get('id', 0)
        const = self.song_map[song_id]['difficulties'][level_index].get('level_value', 0)
        rating = score.get('rating', 0)
        full_combo = score.get('full_combo', '')
        fc_bonus = 0
        if full_combo == "alljusticecritical":
            fc_bonus = 1.25
        elif full_combo == "alljustice":
            fc_bonus = 1
        elif full_combo == "fullcombo":
            fc_bonus = 0.5
        if score_point < 1007500:
            return rating * 5 + fc_bonus
        else:
            return (const + 2) * 5 + fc_bonus + (score_point - 1007500) * 0.0015
    
    async def get_max_best(self):
        b30_list = []
        n20_list = []
        new_version1 = 22500 # LUMINOUS PLUS
        new_version2 = 23000 # VERSE
        b30_lowest = 0
        n20_lowest = 0

        for song in self.songs:
            if song.get('id', 9999) >= 8000: # WE谱
                continue
            if song['version'] == new_version1 or song['version'] == new_version2:
                # 新曲
                for difficulty in song['difficulties']:
                    const = difficulty['level_value']
                    if const <= n20_lowest:
                        continue

                    if n20_list == []:
                        tmp_score = {
                            'id': song['id'],
                            'song_name': song['title'],
                            'level_index': difficulty['difficulty'],
                            'score': 1010000,
                            'level_value': difficulty['level_value'],
                            'rating': difficulty['level_value'] + 2.15,
                            'full_combo': 'alljusticecritical'
                        }
                        n20_list.insert(0, tmp_score)
                        continue
                    
                    index = 0
                    for score in n20_list:
                        if index >= 20:
                            break
                        if const <= score['level_value']:
                            index += 1
                            continue
                        tmp_score = {
                            'id': song['id'],
                            'song_name': song['title'],
                            'level_index': difficulty['difficulty'],
                            'score': 1010000,
                            'level_value': difficulty['level_value'],
                            'rating': difficulty['level_value'] + 2.15,
                            'full_combo': 'alljusticecritical'
                        }
                        n20_list.insert(index, tmp_score)
                        break
                    
                    if len(n20_list) >= 20:
                        n20_lowest = n20_list[19]['level_value']
            else:
                # 老曲
                for difficulty in song['difficulties']:
                    const = difficulty['level_value']
                    if const <= b30_lowest:
                        continue

                    if b30_list == []:
                        tmp_score = {
                            'id': song['id'],
                            'song_name': song['title'],
                            'level_index': difficulty['difficulty'],
                            'score': 1010000,
                            'level_value': difficulty['level_value'],
                            'rating': difficulty['level_value'] + 2.15,
                            'full_combo': 'alljusticecritical'
                        }
                        b30_list.insert(0, tmp_score)
                        continue
                    
                    index = 0
                    for score in b30_list:
                        if index >= 30:
                            break
                        if const <= score['level_value']:
                            index += 1
                            continue
                        tmp_score = {
                            'id': song['id'],
                            'song_name': song['title'],
                            'level_index': difficulty['difficulty'],
                            'score': 1010000,
                            'level_value': difficulty['level_value'],
                            'rating': difficulty['level_value'] + 2.15,
                            'full_combo': 'alljusticecritical'
                        }
                        b30_list.insert(index, tmp_score)
                        break
                    
                    if len(b30_list) >= 30:
                        b30_lowest = b30_list[29]['level_value']

        return {"bests": b30_list[:30], "new_bests": n20_list[:20]}
        
class ParamType(Enum):
    LEVEL = 0
    CONST = 1

class Level(Enum):
    L14 = (14.0, 14.4)
    L14P = (14.5, 14.9)
    L15 = (15.0, 15.4)
    L15P = (15.5, 15.9)