import os
import random
import string
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from pathlib import Path
import math
import time
from astrbot.api import logger

from .resource_manager import ResourceManager, ParamType, Level

class ImageGenerator:
    def __init__(self, plugin_name: str, resource_manager, data_root: Path):
        """
        初始化图片生成器
        
        Args:
            resource_manager: ResourceManager 实例，用于管理资源文件
        """
        self.res_mgr = resource_manager
        self.plugins_dir = data_root / "plugin_data" / plugin_name
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.plugins_dir / "temp_images"
        self.temp_dir.mkdir(exist_ok=True)
        self.jackets_dir = self.plugins_dir / "jackets"
        self.jackets_dir.mkdir(exist_ok=True)
        self.bgs_dir = self.plugins_dir / "bgs"
        self.bgs_dir.mkdir(exist_ok=True)
        self.fonts_dir = self.plugins_dir / "fonts"
        self.fonts_dir.mkdir(exist_ok=True)
        
    def add_rounded_corners(self, image, radius):
        """
        给图片添加圆角
        
        Args:
            image: PIL Image对象
            radius: 圆角半径
            
        Returns:
            处理后的PIL Image对象
        """
        # 创建圆角蒙版
        mask = Image.new('L', image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle(
            [(0, 0), image.size],
            radius=radius,
            fill=255
        )
        
        # 确保图片有 alpha 通道
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # 创建新图片，应用蒙版
        result = Image.new('RGBA', image.size, (0, 0, 0, 0))
        result.paste(image, (0, 0), mask)
        
        return result
    
    def add_shadow(self, image, offset=(5, 5), shadow_color=(0, 0, 0, 128), blur_radius=10):
        """
        给图片添加阴影
        
        Args:
            image: PIL Image对象（需要包含alpha通道）
            offset: 阴影偏移量 (x, y)
            shadow_color: 阴影颜色 (R, G, B, A)
            blur_radius: 模糊半径
            
        Returns:
            添加阴影后的PIL Image对象
        """
        # 确保图片有alpha通道
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # 创建阴影图层
        shadow = Image.new('RGBA', image.size, shadow_color)
        
        # 使用原图的alpha通道作为阴影的蒙版
        alpha = image.split()[3]
        shadow.putalpha(alpha)
        
        # 创建更大的画布来容纳阴影
        width, height = image.size
        shadow_offset_x, shadow_offset_y = offset
        
        new_width = width + abs(shadow_offset_x) + blur_radius * 2
        new_height = height + abs(shadow_offset_y) + blur_radius * 2
        
        result = Image.new('RGBA', (new_width, new_height), (0, 0, 0, 0))
        
        # 计算位置使阴影居中并应用偏移
        shadow_x = blur_radius + (shadow_offset_x if shadow_offset_x > 0 else 0)
        shadow_y = blur_radius + (shadow_offset_y if shadow_offset_y > 0 else 0)
        
        # 应用阴影模糊
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        # 粘贴阴影
        result.paste(shadow, (shadow_x, shadow_y), shadow)
        
        # 粘贴原图
        image_x = blur_radius + max(0, -shadow_offset_x)
        image_y = blur_radius + max(0, -shadow_offset_y)
        result.paste(image, (image_x, image_y), image)
        
        return result
    
    def add_rounded_corner_with_outer_blur(self, image, corner_radius=50, blur_radius=10, shadow_opacity=180):
        """
        给图片添加圆角矩形，并在外围添加模糊效果
        
        Args:
            image: PIL Image对象 或 图片路径
            corner_radius: 圆角半径
            blur_radius: 模糊半径（像素）
        
        Returns:
            带外围模糊阴影的圆角图片
        """
        
        # 如果是路径，加载图片
        if isinstance(image, str):
            original = Image.open(image).convert("RGBA")
        else:
            original = image.convert("RGBA")
        
        # 计算新图像的尺寸（扩大以容纳外围模糊）
        blur_extension = blur_radius * 3  # 模糊效果的扩展区域
        new_width = original.width + blur_extension * 2
        new_height = original.height + blur_extension * 2
        
        # 创建新的透明背景图像
        result = Image.new('RGBA', (new_width, new_height), (0, 0, 0, 0))
        
        # 创建圆角矩形的蒙版
        mask = Image.new('L', (original.width, original.height), 0)
        draw = ImageDraw.Draw(mask)
        
        # 绘制白色圆角矩形作为蒙版
        draw.rounded_rectangle(
            [(0, 0), (original.width, original.height)],
            radius=corner_radius,
            fill=255
        )
        
        # 将原始图像应用圆角蒙版
        rounded_image = Image.new('RGBA', original.size, (0, 0, 0, 0))
        rounded_image.paste(original, (0, 0), mask)
        
        # 创建模糊背景层
        blur_layer = Image.new('RGBA', (new_width, new_height), (0, 0, 0, 0))
        blur_draw = ImageDraw.Draw(blur_layer)
        
        # 在模糊层上绘制圆角矩形（比原图稍大，用于产生模糊效果）
        blur_margin = blur_radius
        blur_draw.rounded_rectangle(
            [
                (blur_extension - blur_margin, blur_extension - blur_margin),
                (blur_extension + original.width + blur_margin, blur_extension + original.height + blur_margin)
            ],
            radius=corner_radius + blur_margin,
            fill=(255, 255, 255, shadow_opacity)
        )
        
        # 对模糊层应用高斯模糊
        blur_layer = blur_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        
        # 将模糊层粘贴到结果图像上
        result.paste(blur_layer, (0, 0), blur_layer)
        
        # 将圆角矩形图片粘贴到中央
        paste_x = blur_extension
        paste_y = blur_extension
        result.paste(rounded_image, (paste_x, paste_y), rounded_image)
        
        return result
    
    def create_composite_image(self, background_image, images_data, output_path=None):
        """
        创建合成图片
        
        Args:
            background_image: 背景图片路径或PIL Image对象
            images_data: 图片数据列表，每个元素为字典，包含：
                - 'image': 图片路径或PIL Image对象
                - 'position': (x, y) 位置
                - 'size': (width, height) 可选，调整大小
                - 'radius': 圆角半径，可选
                - 'shadow': 是否添加阴影，可选
                - 'shadow_offset': 阴影偏移，可选
                - 'shadow_blur': 阴影模糊半径，可选
            output_path: 输出路径，如果不指定则自动生成
            
        Returns:
            生成的图片路径
        """
        # 加载背景图片
        if isinstance(background_image, str):
            bg = Image.open(background_image).convert('RGBA')
        else:
            bg = background_image.convert('RGBA')
        
        # 创建画布
        canvas = bg.copy()
        
        # 处理每张图片
        for img_data in images_data:
            # 加载图片
            if isinstance(img_data['image'], str):
                img = Image.open(img_data['image']).convert('RGBA')
            else:
                img = img_data['image'].convert('RGBA')
            
            # 调整大小
            if 'size' in img_data:
                img = img.resize(img_data['size'], Image.Resampling.LANCZOS)
            
            # 添加圆角
            if 'radius' in img_data and img_data['radius'] > 0:
                img = self.add_rounded_corners(img, img_data['radius'])
            
            # 添加阴影
            if img_data.get('shadow', False):
                shadow_offset = img_data.get('shadow_offset', (5, 5))
                shadow_blur = img_data.get('shadow_blur', 10)
                img = self.add_shadow(img, shadow_offset, blur_radius=shadow_blur)
            
            # 粘贴到画布
            canvas.paste(img, img_data['position'], img)
        
        # 保存图片
        if output_path is None:
            # 生成随机文件名
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            output_path = self.temp_dir / f"{random_name}.png"
        
        canvas.save(output_path, 'PNG')
        return str(output_path)
    
    def add_text_to_image(self, image, text_data):
        """
        向图片添加文字
        
        Args:
            image: 图片路径或PIL Image对象
            text_data: 文字数据，可以是单个字典或字典列表，每个字典包含：
                - 'text': 文字内容
                - 'position': (x, y) 位置
                - 'font_size': 字体大小
                - 'font_path': 字体路径（可选）
                - 'color': (R, G, B) 颜色
                - 'align': 对齐方式（'left', 'center', 'right'）
                - 'stroke_width': 描边宽度
                - 'stroke_color': 描边颜色
                
        Returns:
            添加文字后的图片路径
        """
        # 加载图片
        if isinstance(image, str):
            img = Image.open(image).convert('RGBA')
        else:
            img = image.convert('RGBA')
        
        # 创建绘图对象
        draw = ImageDraw.Draw(img)
        
        # 确保text_data是列表
        if isinstance(text_data, dict):
            text_data = [text_data]
        
        for text_item in text_data:
            try:
                # 加载字体
                if 'font_path' in text_item and os.path.exists(text_item['font_path']):
                    font = ImageFont.truetype(text_item['font_path'], text_item['font_size'])
                else:
                    # 使用默认字体
                    font = ImageFont.load_default()
                    # 如果字体大小需要调整，可以使用以下方法
                    if text_item['font_size'] > 10:
                        # 尝试加载系统字体
                        system_fonts = [
                            '/System/Library/Fonts/PingFang.ttc',  # macOS
                            'C:/Windows/Fonts/msyh.ttc',           # Windows
                            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'  # Linux
                        ]
                        for font_path in system_fonts:
                            if os.path.exists(font_path):
                                try:
                                    font = ImageFont.truetype(font_path, text_item['font_size'])
                                    break
                                except:
                                    continue
            
            except Exception as e:
                print(f"加载字体失败: {e}")
                font = ImageFont.load_default()
            
            # 计算文字位置
            position = text_item['position']
            if text_item.get('align') == 'center':
                # 计算文字宽度以居中
                bbox = draw.textbbox((0, 0), text_item['text'], font=font)
                text_width = bbox[2] - bbox[0]
                position = (position[0] - text_width // 2, position[1])
            elif text_item.get('align') == 'right':
                bbox = draw.textbbox((0, 0), text_item['text'], font=font)
                text_width = bbox[2] - bbox[0]
                position = (position[0] - text_width, position[1])
            
            # 绘制文字
            if 'stroke_width' in text_item and text_item['stroke_width'] > 0:
                # 带描边的文字
                draw.text(
                    position,
                    text_item['text'],
                    font=font,
                    fill=text_item.get('color', (0, 0, 0)),
                    stroke_width=text_item['stroke_width'],
                    stroke_fill=text_item.get('stroke_color', (255, 255, 255))
                )
            else:
                # 普通文字
                draw.text(
                    position,
                    text_item['text'],
                    font=font,
                    fill=text_item.get('color', (0, 0, 0))
                )
        
        # 保存图片
        output_path = self.temp_dir / f"text_{''.join(random.choices(string.ascii_letters + string.digits, k=8))}.png"
        img.save(output_path, 'PNG')
        return str(output_path)
    
    def create_grid_image(self, image_paths, output_path=None, 
                      item_size=200,           # 每个原图的大小（正方形边长）
                      bg_padding=20,           # 圆角矩形比原图大出的边距
                      corner_radius=30,        # 圆角矩形的圆角半径
                      margin=30,                # 整体之间的间距
                      rows=None,                 # 指定行数，如果不指定则自动计算
                      bg_color=(0, 255, 255)    # 背景颜色，青色
                      ):
        """
        生成网格排列的图片，每张原图底部添加圆角矩形背景
        
        Args:
            image_paths: 图片路径列表
            output_path: 输出路径，如果不指定则自动生成
            item_size: 每个原图的大小（正方形边长）
            bg_padding: 圆角矩形比原图大出的边距
            corner_radius: 圆角矩形的圆角半径
            margin: 整体之间的间距
            rows: 指定行数，如果不指定则自动计算
            bg_color: 背景颜色，RGB元组，默认青色 (0, 255, 255)
        
        Returns:
            生成的图片路径
        """
        
        # 计算布局
        num_images = len(image_paths)
        cols = 5  # 固定每行5个
        if rows is None:
            rows = math.ceil(num_images / cols)  # 自动计算行数
        
        # 计算每个整体的尺寸（原图 + 底部的圆角矩形）
        # 圆角矩形比原图大，所以要加上边距
        item_total_width = item_size + bg_padding * 2
        item_total_height = item_size + bg_padding * 2
        
        # 计算整个画布的尺寸
        canvas_width = cols * item_total_width + (cols + 1) * margin
        canvas_height = rows * item_total_height + (rows + 1) * margin
        
        # 创建背景画布
        canvas = Image.new('RGB', (canvas_width, canvas_height), bg_color)
        
        # 处理每张图片
        for idx, img_path in enumerate(image_paths):
            if idx >= rows * cols:
                break  # 超出布局范围的图片忽略
                
            # 计算当前图片的位置（行列）
            row = idx // cols
            col = idx % cols
            
            # 计算这个整体的左上角坐标
            base_x = margin + col * (item_total_width + margin)
            base_y = margin + row * (item_total_height + margin)
            
            # 计算圆角矩形的位置和大小
            rect_x = base_x
            rect_y = base_y
            rect_width = item_total_width
            rect_height = item_total_height
            
            # 创建圆角矩形遮罩
            rect_mask = Image.new('RGBA', (rect_width, rect_height), (0, 0, 0, 0))
            rect_draw = ImageDraw.Draw(rect_mask)
            
            # 绘制圆角矩形（白色，带透明度）
            rect_draw.rounded_rectangle(
                [(0, 0), (rect_width, rect_height)],
                radius=corner_radius,
                fill=(255, 255, 255, 200)  # 半透明白色背景
            )

            # 添加左上角的等腰梯形缎带
            p1 = (int(rect_width * 0.12), 0)
            p2 = (int(rect_width * 0.4), 0)
            p3 = (0, int(rect_height * 0.4))
            p4 = (0, int(rect_height * 0.12))

            # 绘制梯形（实际上是一个四边形，从p1->p2->p3->p4->p1）
            rect_draw.polygon(
                [p1, p2, p3, p4],
                fill=(128, 0, 128, 255)  # 紫色填充
            )
            
            # 将圆角矩形粘贴到画布上
            canvas.paste(rect_mask, (rect_x, rect_y), rect_mask)
            
            try:
                # 加载并处理原图
                img = Image.open(img_path).convert('RGBA')
                
                # 将原图调整为指定大小（保持正方形）
                img = img.resize((item_size, item_size), Image.Resampling.LANCZOS)
                
                # 计算原图的位置（在圆角矩形内部居中）
                img_x = base_x + bg_padding
                img_y = base_y + bg_padding  # 距离顶部bg_padding像素
                
                # 创建原图的圆角遮罩
                img_mask = Image.new('L', (item_size, item_size), 0)
                img_draw = ImageDraw.Draw(img_mask)
                img_draw.rounded_rectangle(
                    [(0, 0), (item_size, item_size)],
                    radius=corner_radius - bg_padding,
                    fill=255
                )
                img.putalpha(img_mask)
                
                # 将原图粘贴到画布上
                canvas.paste(img, (img_x, img_y), img if img.mode == 'RGBA' else None)
                
            except Exception as e:
                logger.error(f"处理图片 {img_path} 时出错: {e}")
                # 如果图片加载失败，在相应位置画一个灰色方块
                error_draw = ImageDraw.Draw(canvas)
                error_draw.rectangle(
                    [img_x, img_y, img_x + item_size, img_y + item_size],
                    fill=(128, 128, 128)
                )
                error_draw.text(
                    (img_x + 10, img_y + item_size//2 - 10),
                    "加载失败",
                    fill=(255, 255, 255)
                )
        
        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            output_path = self.temp_dir / f"grid_{random_name}.png"
        
        canvas.save(output_path, 'PNG')
        return str(output_path)
    
    def truncate_text_to_fit(self, draw, text, font, max_width, ellipsis="..."):
        """
        根据最大宽度截断文本，添加省略号
        """
        # 如果完整文本已经适合，直接返回
        if draw.textlength(text, font=font) <= max_width:
            return text
        
        # 逐字符尝试，找到合适的截断点
        for i in range(len(text), 0, -1):
            # 截取前 i 个字符 + 省略号
            truncated = text[:i] + ellipsis
            width = draw.textlength(truncated, font=font)
            
            if width <= max_width:
                return truncated
        
        # 极端情况：连一个字符都放不下
        return ellipsis
    
    def cleanup_old_files(self, max_age_hours=24):
        """
        清理过期的临时文件
        
        Args:
            max_age_hours: 文件最大保留时间（小时）
        """
        current_time = time.time()
        for file_path in self.temp_dir.glob("*"):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_hours * 3600:
                    file_path.unlink()

    async def create_dsb(self, param_type, param):
        """
        生成定数表

        Args:
            param_type: 参数类型（等级或定数）
            param: 等级或定数参数
        """
        min_const, max_const = 15.7, 15.7
        if param_type == ParamType.LEVEL:
            min_const, max_const = param.value
        elif param_type == ParamType.CONST:
            min_const, max_const = param, param

        image_paths = []
        for song in self.res_mgr.songs:
            for difficulty in song.get('difficulties', []):
                level_value =  difficulty.get('level_value', 0)
                if level_value >= min_const and level_value <= max_const:
                    song_id = song.get('id', 0)
                    image_paths.append(await self.res_mgr.get_jacket(song_id))

        return self.create_grid_image(image_paths)

    async def create_song_info_image(self, song_data, output_path=None):
        """
        生成曲目信息图片（复用基础函数）
        """

        if len(song_data['difficulties'])>=5: # 有黑谱
            background_path = self.bgs_dir / 'song_info_bg_1.png'
        else: # 没黑谱
            background_path = self.bgs_dir / 'song_info_bg_2.png'
        
        jacket_path = await self.res_mgr.get_jacket(song_data.get('id', 2353)) # 其实2353是幻想即兴曲（
        
        # 画布尺寸
        canvas_width = 1600
        canvas_height = 1200
        
        # 加载背景图片
        if background_path and os.path.exists(background_path):
            # 加载背景图片并调整到画布大小
            background = Image.open(background_path).convert('RGBA')
            background = background.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            canvas = background.copy()
        else:
            # 没有背景图片，使用纯色背景
            canvas = Image.new('RGB', (canvas_width, canvas_height), (20, 20, 30))

        # 创建绘图对象（使用RGBA模式支持透明度）
        draw = ImageDraw.Draw(canvas, 'RGBA')
        
        # ========== 曲绘部分 ==========
        jacket_size = 250
        jacket_radius = 50
        jacket_x = 145
        jacket_y = 257
        
        try:
            # 加载曲绘
            jacket = Image.open(jacket_path).convert('RGBA')
            jacket = jacket.resize((jacket_size, jacket_size), Image.Resampling.LANCZOS)
            
            # 在处理前先放大图片
            scale_factor = 2  # 放大2倍
            temp_size = (jacket_size * scale_factor, jacket_size * scale_factor)
            jacket = Image.open(jacket_path).convert('RGBA')
            jacket = jacket.resize(temp_size, Image.Resampling.LANCZOS)  # 使用高质量的缩放

            # 处理圆角和阴影
            jacket_with_shadow = self.add_rounded_corner_with_outer_blur(
                jacket,
                corner_radius=jacket_radius * scale_factor,  # 圆角半径也相应放大
                blur_radius=5 * scale_factor,
                shadow_opacity=180
            )

            # 最后再缩小回目标尺寸
            final_size = (jacket_size, jacket_size)
            jacket_with_shadow = jacket_with_shadow.resize(final_size, Image.Resampling.LANCZOS)

            # 计算偏移（因为有扩展区域）
            blur_extension = 5 * 3  # blur_radius * 3
            canvas.paste(
                jacket_with_shadow,
                (jacket_x - blur_extension, jacket_y - blur_extension),
                jacket_with_shadow
            )

        except Exception as e:
            # 如果加载失败，画一个灰色矩形
            fallback = Image.new('RGBA', (jacket_size, jacket_size), (200, 200, 200))
            canvas.paste(fallback, (jacket_x - 5, jacket_y - 5), fallback)
            
            # 添加文字
            text_img = Image.new('RGBA', (jacket_size, jacket_size), (0, 0, 0, 0))
            text_draw = ImageDraw.Draw(text_img)
            text_draw.text((jacket_size//2 - 40, jacket_size//2 - 10), 
                        "No Image", fill=(100, 100, 100))
            canvas.paste(text_img, (jacket_x, jacket_y), text_img)

        # 处理曲名
        title_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 70)
        title_text = self.truncate_text_to_fit(draw, song_data.get('title'), title_font, 1050)

        # 处理曲师
        artist_font = ImageFont.truetype(self.fonts_dir / 'LXGWWenKai-Medium.ttf', 38)
        artist_text = self.truncate_text_to_fit(draw, song_data.get('artist'), artist_font, 1050)

        # 处理info
        info_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 36)
        info_font.set_variation_by_name('Medium')

        # 处理定数和物量数字
        num_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 45)
        num_font.set_variation_by_name('SemiBold')

        # 处理谱师
        nd_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 34)
        exp_nd_text = self.truncate_text_to_fit(draw, song_data['difficulties'][2].get('note_designer', '未知'), nd_font, 700)
        mas_nd_text = self.truncate_text_to_fit(draw, song_data['difficulties'][3].get('note_designer', '未知'), nd_font, 700)
        if len(song_data['difficulties'])>=5:
            ult_nd_text = self.truncate_text_to_fit(draw, song_data['difficulties'][4].get('note_designer', '未知'), nd_font, 700)
        
        # 文字信息
        if len(song_data['difficulties'])>=5:
            # 有黑谱
            text_data = [
                {
                    # 曲名
                    'text': title_text,
                    'position': (390, 237),
                    'font': title_font,
                    'color': 'black',
                },
                {
                    # 曲师
                    'text': artist_text,
                    'position': (390, 339),
                    'font': artist_font,
                    'color': 'black',
                },
                {
                    # ID
                    'text': str(song_data.get('id', '未知')),
                    'position': (410, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # BPM
                    'text': str(song_data.get('bpm', '未知')),
                    'position': (592, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # 分类
                    'text': song_data.get('genre', '未知'),
                    'position': (784, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # 版本
                    'text': self.res_mgr.version_map.get(song_data.get('version', 0), '未知'),
                    'position': (1007, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # BASIC定数
                    'text': f"{song_data['difficulties'][0].get('level_value', 0):.1f}",
                    'position': (203, 1037),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ADVANCED定数
                    'text': f"{song_data['difficulties'][1].get('level_value', 0):.1f}",
                    'position': (203, 914),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT定数
                    'text': f"{song_data['difficulties'][2].get('level_value', 0):.1f}",
                    'position': (203, 792),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # MASTER定数
                    'text': f"{song_data['difficulties'][3].get('level_value', 0):.1f}",
                    'position': (203, 668),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ULTIMA定数
                    'text': f"{song_data['difficulties'][4].get('level_value', 0):.1f}",
                    'position': (205, 546),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # BASIC物量
                    'text': str(song_data['difficulties'][0].get('notes', {}).get('total', 0)),
                    'position': (500, 1037),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ADVANVED物量
                    'text': str(song_data['difficulties'][1].get('notes', {}).get('total', 0)),
                    'position': (500, 914),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT物量
                    'text': str(song_data['difficulties'][2].get('notes', {}).get('total', 0)),
                    'position': (500, 792),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # MASTER物量
                    'text': str(song_data['difficulties'][3].get('notes', {}).get('total', 0)),
                    'position': (500, 668),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ULTIMA物量
                    'text': str(song_data['difficulties'][4].get('notes', {}).get('total', 0)),
                    'position': (500, 546),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT谱师
                    'text': exp_nd_text,
                    'position': (795, 794),
                    'font': nd_font,
                    'color': 'black',
                },
                {
                    # MASTER谱师
                    'text': mas_nd_text,
                    'position': (795, 670),
                    'font': nd_font,
                    'color': 'black',
                },
                {
                    # ULTIMA谱师
                    'text': ult_nd_text,
                    'position': (795, 548),
                    'font': nd_font,
                    'color': 'black',
                },
            ]
        else:
            # 没黑谱
            delta_y = 72
            text_data = [
                {
                    # 曲名
                    'text': title_text,
                    'position': (390, 237),
                    'font': title_font,
                    'color': 'black',
                },
                {
                    # 曲师
                    'text': artist_text,
                    'position': (390, 339),
                    'font': artist_font,
                    'color': 'black',
                },
                {
                    # ID
                    'text': str(song_data.get('id', '未知')),
                    'position': (410, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # BPM
                    'text': str(song_data.get('bpm', '未知')),
                    'position': (592, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # 分类
                    'text': song_data.get('genre', '未知'),
                    'position': (784, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # 版本
                    'text': self.res_mgr.version_map.get(song_data.get('version', 0), '未知'),
                    'position': (1007, 435),
                    'font': info_font,
                    'color': 'black',
                },
                {
                    # BASIC定数
                    'text': f"{song_data['difficulties'][0].get('level_value', 0):.1f}",
                    'position': (203, 1037-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ADVANCED定数
                    'text': f"{song_data['difficulties'][1].get('level_value', 0):.1f}",
                    'position': (203, 914-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT定数
                    'text': f"{song_data['difficulties'][2].get('level_value', 0):.1f}",
                    'position': (203, 792-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # MASTER定数
                    'text': f"{song_data['difficulties'][3].get('level_value', 0):.1f}",
                    'position': (203, 668-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # BASIC物量
                    'text': str(song_data['difficulties'][0].get('notes', {}).get('total', 0)),
                    'position': (500, 1037-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # ADVANVED物量
                    'text': str(song_data['difficulties'][1].get('notes', {}).get('total', 0)),
                    'position': (500, 914-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT物量
                    'text': str(song_data['difficulties'][2].get('notes', {}).get('total', 0)),
                    'position': (500, 792-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # MASTER物量
                    'text': str(song_data['difficulties'][3].get('notes', {}).get('total', 0)),
                    'position': (500, 668-delta_y),
                    'font': num_font,
                    'color': 'black',
                },
                {
                    # EXPERT谱师
                    'text': exp_nd_text,
                    'position': (795, 794-delta_y),
                    'font': nd_font,
                    'color': 'black',
                },
                {
                    # MASTER谱师
                    'text': mas_nd_text,
                    'position': (795, 670-delta_y),
                    'font': nd_font,
                    'color': 'black',
                },
            ]

        # 添加文字
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font=item['font'])

        """
        
        # ========== 标题区域 ==========
        title_x = jacket_x + jacket_size + 40
        title_y = jacket_y
        title_width = main_rect_x + main_rect_width - title_x - 50
        title_height = 120
        
        await self.draw_fancy_rounded_rect(
            draw,
            title_x, title_y,
            title_width, title_height,
            radius=20,
            bg_color=(250, 250, 250),
            border_color=(128, 0, 128),
            border_width=3,
            shadow=True,
            shadow_offset=4,
            shadow_alpha=30
        )
        
        # 添加文字（复用 add_text_to_image 的逻辑）
        text_data = [
            {
                'text': song_data['title'],
                'position': (title_x + 20, title_y + 20),
                'font_size': 32,
                'color': (0, 0, 0)
            },
            {
                'text': song_data['artist'],
                'position': (title_x + 20, title_y + 70),
                'font_size': 20,
                'color': (80, 80, 80)
            }
        ]
        
        # 临时实现文字添加（因为 add_text_to_image 返回新图片，这里需要调整）
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font_size=item['font_size'])
        
        # ========== 元信息区域 ==========
        meta_x = title_x
        meta_y = title_y + title_height + 30
        meta_width = title_width
        meta_height = 80
        
        await self.draw_fancy_rounded_rect(
            draw,
            meta_x, meta_y,
            meta_width, meta_height,
            radius=20,
            bg_color=(245, 245, 245),
            border_color=(128, 0, 128),
            border_width=2,
            shadow=True,
            shadow_offset=3,
            shadow_alpha=25
        )
        
        # 元信息文字
        meta_items = [
            f"ID: {song_data['id']}",
            f"BPM: {song_data['bpm']}",
            f"分类: {song_data['category']}",
            f"版本: {song_data['version']}"
        ]
        
        for i, item in enumerate(meta_items):
            draw.text((meta_x + 20 + i * 200, meta_y + 30), 
                    item, fill=(60, 60, 60), font_size=18)
        
        # ========== 难度信息区域 ==========
        diff_x = main_rect_x + 50
        diff_y = meta_y + meta_height + 40
        diff_width = main_rect_width - 100
        diff_height = 400
        
        await self.draw_fancy_rounded_rect(
            draw,
            diff_x, diff_y,
            diff_width, diff_height,
            radius=30,
            bg_color=(255, 255, 255),
            border_color=(128, 0, 128),
            border_width=4,
            shadow=True,
            shadow_offset=6,
            shadow_alpha=40
        )
        
        # 难度标题
        draw.text((diff_x + 30, diff_y + 20), "难度信息", 
                fill=(128, 0, 128), font_size=28, font_weight='bold')
        
        # 难度列表
        difficulty_colors = {
            'BASIC': (68, 140, 80),
            'ADVANCED': (240, 170, 40),
            'EXPERT': (220, 70, 70),
            'MASTER': (170, 70, 200),
            'ULTIMA': (255, 215, 0)
        }
        
        difficulties = song_data['difficulties']
        start_x = diff_x + 30
        start_y = diff_y + 80
        block_width = 180
        block_height = 250
        spacing = 20
        
        for i, diff in enumerate(difficulties):
            x = start_x + i * (block_width + spacing)
            y = start_y
            
            if x + block_width > diff_x + diff_width - 30:
                break
            
            # 为每个难度块添加小框
            self.draw_fancy_rounded_rect(
                draw,
                x, y,
                block_width, block_height,
                radius=15,
                bg_color=(250, 250, 250),
                border_color=difficulty_colors.get(diff['level'], (150, 150, 150)),
                border_width=3,
                shadow=True,
                shadow_offset=4,
                shadow_alpha=30
            )
            
            # 难度文字
            draw.text((x + 15, y + 15), diff['level'], 
                    fill=(0, 0, 0), font_size=22, font_weight='bold')
            draw.text((x + 15, y + 60), str(diff['rating']), 
                    fill=(128, 0, 128), font_size=32, font_weight='bold')
            draw.text((x + 15, y + 110), f"{diff['notes']} notes", 
                    fill=(80, 80, 80), font_size=16)
            
            if 'charter' in diff and diff['charter']:
                charter = diff['charter']
                if len(charter) > 20:
                    charter = charter[:18] + "..."
                draw.text((x + 15, y + 150), charter, 
                        fill=(100, 100, 100), font_size=14)
        """
        
        # 保存图片
        if output_path is None:
            import random
            import string
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"song_info_{random_name}.png"
        
        canvas.save(output_path, 'PNG', quality=95)
        return str(output_path)