import os
import random
import string
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps
from pathlib import Path
import math
import time
from astrbot.api import logger
import unicodedata

from .resource_manager import ResourceManager

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

    def save_compact_webp(self, image: Image.Image, output_path):
        """优先保存为 WebP 以减小体积；失败时回退到 PNG。"""
        path = Path(output_path)
        if path.suffix.lower() != '.webp':
            path = path.with_suffix('.webp')

        # 已确认不需要透明通道时，统一转 RGB 可稳定减小体积
        img = image if image.mode == 'RGB' else image.convert('RGB')

        try:
            img.save(path, 'WEBP', quality=90, method=6)
            return path
        except Exception:
            # WEBP 编码失败时，回退为 PNG 以保证可用性
            fallback_path = path.with_suffix('.png')
            img.save(fallback_path, 'PNG', optimize=True, compress_level=9)
            return fallback_path

    def draw_blurred_text(self, image, position, text, font, fill, blur_radius,
                           blur_color=None, blur_offset=(0, 0), stroke_width=0,
                           stroke_fill=None, anchor=None):
        """在图像上叠加一个高斯模糊的文字底层，再绘制清晰文字。"""
        if blur_radius <= 0:
            return image

        if len(fill) == 3:
            base_fill = (*fill, 255)
        else:
            base_fill = fill

        if blur_color is None:
            blur_fill = base_fill[:-1] + (180,)
        elif len(blur_color) == 3:
            blur_fill = (*blur_color, 180)
        else:
            blur_fill = blur_color

        blur_layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
        blur_draw = ImageDraw.Draw(blur_layer)
        blur_position = (
            position[0] + blur_offset[0],
            position[1] + blur_offset[1]
        )
        blur_draw.text(
            blur_position,
            text,
            font=font,
            fill=blur_fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            anchor=anchor
        )
        blur_layer = blur_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        return Image.alpha_composite(image, blur_layer)
    
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
    
    def paste_gradient_polygon(self, canvas, points, colors, angle_deg=135):
        # colors: [(r,g,b,a), ...] 至少2个
        min_x = min(x for x, y in points)
        max_x = max(x for x, y in points)
        min_y = min(y for x, y in points)
        max_y = max(y for x, y in points)

        width = max_x - min_x + 1
        height = max_y - min_y + 1

        gradient = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        pixels = gradient.load()

        rad = math.radians(angle_deg)
        ux = math.cos(rad)
        uy = math.sin(rad)

        corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
        proj_vals = [x * ux + y * uy for x, y in corners]
        proj_min = min(proj_vals)
        proj_max = max(proj_vals)
        denom = max(proj_max - proj_min, 1e-6)

        n = len(colors)
        seg_count = n - 1

        for y in range(height):
            for x in range(width):
                proj = x * ux + y * uy
                t = (proj - proj_min) / denom
                t = max(0.0, min(1.0, t))

                # 分段：0..1 映射到 0..seg_count
                pos = t * seg_count
                i = min(int(pos), seg_count - 1)
                local_t = pos - i

                c1 = colors[i]
                c2 = colors[i + 1]

                pixels[x, y] = (
                    int(c1[0] * (1 - local_t) + c2[0] * local_t),
                    int(c1[1] * (1 - local_t) + c2[1] * local_t),
                    int(c1[2] * (1 - local_t) + c2[2] * local_t),
                    int(c1[3] * (1 - local_t) + c2[3] * local_t),
                )

        mask = Image.new('L', (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        local_points = [(x - min_x, y - min_y) for x, y in points]
        mask_draw.polygon(local_points, fill=255)

        canvas.paste(gradient, (min_x, min_y), mask)
    
    def draw_shadow_rounded_rect(self, base_img, xy, radius, fill,
                                    shadow_offset=(8, 8),
                                    shadow_color=(0, 0, 0, 120),
                                    blur_radius=12):
        """在 base_img 上绘制带阴影的圆角矩形。"""
        x1, y1, x2, y2 = xy
        shape_w = max(1, x2 - x1)
        shape_h = max(1, y2 - y1)

        shadow_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        sx = x1 + shadow_offset[0]
        sy = y1 + shadow_offset[1]
        shadow_draw.rounded_rectangle(
            (sx, sy, sx + shape_w, sy + shape_h),
            radius=radius,
            fill=shadow_color
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        shape_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        shape_draw = ImageDraw.Draw(shape_layer)
        shape_draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill)

        out = Image.alpha_composite(base_img, shadow_layer)
        out = Image.alpha_composite(out, shape_layer)
        return out

    def draw_shadow_gradient_rounded_rect(
        self,
        base_img,
        xy,                          # (x1, y1, x2, y2)
        radius=30,
        top_color=(165, 89, 255, 255),   # 上半颜色
        bottom_color=(255, 255, 255, 255), # 下半颜色
        transition_center=0.5,       # 过渡中心，0~1
        transition_width=0.22,       # 过渡带宽度，0~1，越大越柔和
        shadow_offset=(6, 6),
        shadow_color=(0, 0, 0, 120),
        shadow_blur=12
    ):
        x1, y1, x2, y2 = xy
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)

        # 1) 阴影层
        shadow_layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        sx1 = x1 + shadow_offset[0]
        sy1 = y1 + shadow_offset[1]
        sx2 = x2 + shadow_offset[0]
        sy2 = y2 + shadow_offset[1]
        sd.rounded_rectangle((sx1, sy1, sx2, sy2), radius=radius, fill=shadow_color)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))

        # 2) 渐变填充层（先做矩形渐变）
        grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gp = grad.load()

        c = max(0.0, min(1.0, transition_center))
        tw = max(0.001, min(1.0, transition_width))
        t0 = max(0.0, c - tw / 2.0)
        t1 = min(1.0, c + tw / 2.0)

        for yy in range(h):
            t = yy / max(h - 1, 1)

            # 上半固定颜色 -> 中间平滑过渡 -> 下半固定颜色
            if t <= t0:
                k = 0.0
            elif t >= t1:
                k = 1.0
            else:
                u = (t - t0) / (t1 - t0)
                # smoothstep，让过渡更自然
                k = u * u * (3 - 2 * u)

            r = int(top_color[0] * (1 - k) + bottom_color[0] * k)
            g = int(top_color[1] * (1 - k) + bottom_color[1] * k)
            b = int(top_color[2] * (1 - k) + bottom_color[2] * k)
            a = int(top_color[3] * (1 - k) + bottom_color[3] * k)

            for xx in range(w):
                gp[xx, yy] = (r, g, b, a)

        # 3) 圆角蒙版裁切
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)

        shape_layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        shape_layer.paste(grad, (x1, y1), mask)

        # 合成：底图 + 阴影 + 形状
        out = Image.alpha_composite(base_img.convert("RGBA"), shadow_layer)
        out = Image.alpha_composite(out, shape_layer)
        return out

    def draw_shadow_parallelogram(self, base_img, points, fill,
                                    shadow_offset=(8, 8),
                                    shadow_color=(0, 0, 0, 140),
                                    blur_radius=12):
        """在 base_img 上绘制带阴影的平行四边形。"""
        shadow_points = [
            (px + shadow_offset[0], py + shadow_offset[1])
            for px, py in points
        ]

        shadow_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.polygon(shadow_points, fill=shadow_color)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        shape_layer = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
        shape_draw = ImageDraw.Draw(shape_layer)
        shape_draw.polygon(points, fill=fill)

        out = Image.alpha_composite(base_img, shadow_layer)
        out = Image.alpha_composite(out, shape_layer)
        return out
    
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

    async def create_dsb_image(self, data, output_path=None):
        """
        生成定数表图片
        """
        background_path = self.bgs_dir / 'general_bg.png'

        # 画布尺寸
        canvas_width = 1600
        canvas_height = 85

        for const, songs in data.items():
            row_num = (len(songs) + 7) // 8
            canvas_height += 120 + row_num * 183 + 40

        # 加载背景图片
        if background_path and os.path.exists(background_path):
            # 加载背景图片并调整到画布大小
            background = Image.open(background_path).convert('RGBA')
            background = background.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            canvas = background.copy()
        else:
            # 没有背景图片，使用纯色背景
            canvas = Image.new('RGB', (canvas_width, canvas_height), (20, 20, 30))

        # 确保后续 alpha 合成稳定
        canvas = canvas.convert('RGBA')

        # 定数框参数
        frame_base = 250
        frame_height = 75
        frame_tan_a = 3

        # 圆角矩形底
        col_num = 8
        bg_x0, bg_y0 = 81, 120
        bg_width = 157
        bg_height = 157
        bg_spacing_x = 183
        bg_spacing_y = 183
        rect_specs = []

        top_y = 70
        
        for const, songs in data.items():
            # 在中间画一个平行四边形（定数框）
            p1_x, p1_y = 688, top_y
            p2_x, p2_y = p1_x + frame_base, p1_y
            p3_x, p3_y = round(p2_x - frame_height / frame_tan_a), p2_y + frame_height
            p4_x, p4_y = p3_x - frame_base, p3_y

            parallelogram_points = [
                (p1_x, p1_y),
                (p2_x, p2_y),
                (p3_x, p3_y),
                (p4_x, p4_y),
            ]
            canvas = self.draw_shadow_parallelogram(
                canvas,
                points=parallelogram_points,
                fill=(255, 255, 255, 235),
                shadow_offset=(3, 3),
                shadow_color=(15, 25, 70, 130),
                blur_radius=10,
            )

            # 圆角矩形底
            index = 0
            for song in songs:
                level_index = song.get('level_index', -1)
                x1 = bg_x0 + (index % col_num) * bg_spacing_x
                y1 = top_y + bg_y0 + (index // col_num) * bg_spacing_y
                x2 = x1 + bg_width
                y2 = y1 + bg_height

                # 背景颜色
                color = (255, 255, 255, 255) # 默认为白色
                if level_index == 4: 
                    color = (30, 30, 30, 255) # 灰色
                elif level_index == 3:
                    color = (165, 89, 255, 255) # 紫色
                elif level_index == 2:
                    color = (255, 0, 0, 255) # 红色
                elif level_index == 1:
                    color = (255, 192, 0, 255) # 橙色
                elif level_index == 0:
                    color = (0, 176, 80, 255) # 绿色

                rect_specs.append(
                    {
                        'xy': (x1, y1, x2, y2),
                        'radius': 31,
                        'top_color': color,
                        'bottom_color': (255, 255, 255, 255),
                        'transition_center': 0.65,
                        'transition_width': 0.28,
                        'shadow_offset': (3, 3),
                        'shadow_color': (15, 25, 70, 130),
                        'shadow_blur': 10,
                    }
                )
                index += 1

            row_num = (len(songs) + col_num - 1) // col_num
            top_y += bg_y0 + row_num * bg_spacing_y + 40

        for spec in rect_specs:
            canvas = self.draw_shadow_gradient_rounded_rect(canvas, **spec)    

        const_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 52)
        const_font.set_variation_by_name('Bold')

        text_data = []
        draw = ImageDraw.Draw(canvas, 'RGBA')
        
        small_base = 16
        jacket_size = 170
        jacket_radius = 26
        
        top_y = 70

        for const, songs in data.items():
            p1_x, p1_y = 688, top_y
            p2_x, p2_y = p1_x + frame_base, p1_y
            p3_x, p3_y = round(p2_x - frame_height / frame_tan_a), p2_y + frame_height
            p4_x, p4_y = p3_x - frame_base, p3_y

            # 左侧的绿色平行四边形
            parallelogram_points = [
                (p1_x, p1_y),
                (p1_x + small_base, p2_y),
                (p4_x + small_base, p3_y),
                (p4_x, p4_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(0, 204, 107, 255) # 绿色
            )
            
            # 右侧的紫色平行四边形
            parallelogram_points = [
                (p2_x - small_base, p1_y),
                (p2_x, p2_y),
                (p3_x, p3_y),
                (p3_x - small_base, p4_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(165, 89, 255, 255) # 紫色
            )

            const_x = canvas_width // 2
            const_y = top_y + 38

            text_data.append({
                'position': (const_x, const_y),
                'text': f'{const:.1f}',
                'color': (0, 0, 0, 255),
                'font': const_font,
                'anchor': 'mm'
            })

            # 每首歌
            index = 0
            for song in songs:
                # ========== 曲绘部分 ==========
                song_id = song.get('id', 2353) # 其实2353是幻想即兴曲（
                jacket_path = await self.res_mgr.get_jacket(song_id)
                level_index = song.get('level_index', -1)

                jacket_x = bg_x0 + (index % col_num) * bg_spacing_x + 12
                jacket_y = top_y + bg_y0 + (index // col_num) * bg_spacing_y + 12

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
                        blur_radius=6 * scale_factor,
                        shadow_opacity=110
                    )

                    # 最后再缩小回目标尺寸
                    final_size = (jacket_size, jacket_size)
                    jacket_with_shadow = jacket_with_shadow.resize(final_size, Image.Resampling.LANCZOS)

                    # 计算偏移（因为有扩展区域）
                    blur_extension = 6 * 3  # blur_radius * 3
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
                
                index += 1
            
            row_num = (len(songs) + col_num - 1) // col_num
            top_y += bg_y0 + row_num * bg_spacing_y + 40

        # 添加文字
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font=item['font'],
                    anchor=item.get('anchor'))
        
        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"dsb_{random_name}.webp"
        
        output_path = self.save_compact_webp(canvas, output_path)
        return str(output_path)

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
        
        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"song_info_{random_name}.webp"
        
        output_path = self.save_compact_webp(canvas, output_path)
        return str(output_path)

    async def create_b30_image(self, songs_data, player_name="CHUNITHM", output_path=None):
        """
        生成曲目信息图片（复用基础函数）
        """

        background_path = self.bgs_dir / 'b30.png'
        
        # 画布尺寸
        canvas_width = 1800
        canvas_height = 2400
        
        # 加载背景图片
        if background_path and os.path.exists(background_path):
            # 加载背景图片并调整到画布大小
            background = Image.open(background_path).convert('RGBA')
            background = background.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            canvas = background.copy()
        else:
            # 没有背景图片，使用纯色背景
            canvas = Image.new('RGB', (canvas_width, canvas_height), (20, 20, 30))

        # 玩家昵称
        name_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 64)
        name_x = 334
        name_y = 150

        # 计算Rating
        b30, n20, b50 = 0, 0, 0
        for song in songs_data.get('bests', []):
            b30 += int(song.get('rating', 0) * 100 + 1e-10) / 100
            b50 += int(song.get('rating', 0) * 100 + 1e-10) / 100
        for song in songs_data.get('new_bests', []):
            n20 += int(song.get('rating', 0) * 100 + 1e-10) / 100
            b50 += int(song.get('rating', 0) * 100 + 1e-10) / 100
        b30 /= 30
        n20 /= 20
        b50 /= 50
        
        jacket_size = 140
        jacket_radius = 15
        jacket_x0 = 40
        jacket_y0 = 394
        
        delta_x = 353
        delta_y = 182

        # 处理Rating
        rating_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 56)
        rating_font.set_variation_by_name('Bold')
        rating_x = 930
        rating_y = 196
        rating_text = f"{int(b50 * 100 + 1e-10) / 100:.2f}"

        # Rating的小数点后3~4位
        rating_mant_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 40)
        rating_mant_font.set_variation_by_name('Bold')
        rating_mant_x = rating_x + 6
        rating_mant_y = rating_y
        rating_mant_text = f"{int(b50 * 10000 + 1e-10) % 100:02d}"

        # B30 N20
        rating_small_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 48)
        rating_small_font.set_variation_by_name('Bold')
        rating_small_x = 1033
        b30_y = 319
        n20_y = 1532
        b30_text = f"{int(b30 * 100 + 1e-10) / 100:.2f}"
        n20_text = f"{int(n20 * 100 + 1e-10) / 100:.2f}"

        rating_small_mant_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 38)
        rating_small_mant_font.set_variation_by_name('Bold')
        rating_small_mant_x = rating_small_x + 5
        b30_mant_y = b30_y
        n20_mant_y = n20_y
        b30_mant_text = f"{int(b30 * 10000 + 1e-10) % 100:02d}"
        n20_mant_text = f"{int(n20 * 10000 + 1e-10) % 100:02d}"

        # 给Rating加模糊
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_x, rating_y),
            text=rating_text,
            font=rating_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='rb'
        )
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_mant_x, rating_mant_y),
            text=rating_mant_text,
            font=rating_mant_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='lb'
        )
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_small_x, b30_y),
            text=b30_text,
            font=rating_small_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='rb'
        )
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_small_mant_x, b30_mant_y),
            text=b30_mant_text,
            font=rating_small_mant_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='lb'
        )
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_small_x, n20_y),
            text=n20_text,
            font=rating_small_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='rb'
        )
        canvas = self.draw_blurred_text(
            canvas,
            position=(rating_small_mant_x, n20_mant_y),
            text=n20_mant_text,
            font=rating_small_mant_font,
            fill=(255, 255, 255, 255),
            blur_radius=3,
            blur_color=(0, 0, 0, 140),
            blur_offset=(2, 2),
            anchor='lb'
        )
        
        # 文字信息
        text_data = [
            {
                # 昵称
                'text': unicodedata.normalize("NFKC", player_name), # 全角转半角
                'position': (name_x, name_y),
                'font': name_font,
                'color': 'black',
                'anchor': 'mm'
            },
            {
                # Rating
                'text': rating_text,
                'position': (rating_x, rating_y),
                'font': rating_font,
                'color': 'white',
                'anchor': 'rb'
            },
            {
                # Rating尾数
                'text': rating_mant_text,
                'position': (rating_mant_x, rating_mant_y),
                'font': rating_mant_font,
                'color': 'white',
                'anchor': 'lb'
            },
            {
                # B30
                'text': b30_text,
                'position': (rating_small_x, b30_y),
                'font': rating_small_font,
                'color': 'white',
                'anchor': 'rb'
            },
            {
                # B30尾数
                'text': b30_mant_text,
                'position': (rating_small_mant_x, b30_mant_y),
                'font': rating_small_mant_font,
                'color': 'white',
                'anchor': 'lb'
            },
            {
                # N20
                'text': n20_text,
                'position': (rating_small_x, n20_y),
                'font': rating_small_font,
                'color': 'white',
                'anchor': 'rb'
            },
            {
                # N20尾数
                'text': n20_mant_text,
                'position': (rating_small_mant_x, n20_mant_y),
                'font': rating_small_mant_font,
                'color': 'white',
                'anchor': 'lb'
            },
        ]
        
        # 创建绘图对象（使用RGBA模式支持透明度）
        draw = ImageDraw.Draw(canvas, 'RGBA')
        
        # 处理曲名
        title_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 24)
        title_x0 = 159
        title_y0 = 385

        # 处理分数
        score_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 39)
        score_font.set_variation_by_name('SemiBold')
        score_x0 = 162
        score_y0 = 443

        # 定数与Rating
        const_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 26)
        const_font.set_variation_by_name('SemiBold')
        const_x0 = 185
        const_y0 = 470

        # 角标
        right_x0 = 360
        bottom_y0 = 514
        leg_len1 = 25
        leg_len2 = 50
        p1_x0, p1_y0 = right_x0, bottom_y0 - leg_len2
        p2_x0, p2_y0 = right_x0, bottom_y0 - leg_len1
        p3_x0, p3_y0 = right_x0 - leg_len1, bottom_y0
        p4_x0, p4_y0 = right_x0 - leg_len2, bottom_y0

        # 难度标
        tan_a = 3
        width = 10
        height = 27
        p5_x0, p5_y0 = 170, 472
        p6_x0, p6_y0 = p5_x0 + width, p5_y0
        p7_x0, p7_y0 = round(p6_x0 - height / tan_a), p6_y0 + height
        p8_x0, p8_y0 = p7_x0 - width, p7_y0

        index = 0
        new_dy = 0

        if 'bests' not in songs_data:
            songs_data['bests'] = []
        while len(songs_data['bests']) < 30:
            songs_data['bests'].append(None)

        for song in songs_data.get('bests', []) + songs_data.get('new_bests', []):
            # New 20 要再往下一点
            if index == 30:
                new_dy = 123

            if song is None:
                index += 1
                continue

            song_id = song.get('id', 2353) # 其实2353是幻想即兴曲（
            jacket_path = await self.res_mgr.get_jacket(song_id)
            level_index = song.get('level_index', -1)
            if level_index != -1:
                const = self.res_mgr.song_map[song_id]['difficulties'][level_index]['level_value']
            
            # ========== 曲绘部分 ==========
            jacket_x = jacket_x0 + (index % 5) * delta_x
            jacket_y = jacket_y0 + (index // 5) * delta_y + new_dy

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
                    blur_radius=6 * scale_factor,
                    shadow_opacity=110
                )

                # 最后再缩小回目标尺寸
                final_size = (jacket_size, jacket_size)
                jacket_with_shadow = jacket_with_shadow.resize(final_size, Image.Resampling.LANCZOS)

                # 计算偏移（因为有扩展区域）
                blur_extension = 6 * 3  # blur_radius * 3
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

            # 文字部分
            title_text = self.truncate_text_to_fit(draw, song.get('song_name', 'Unknown Song'), title_font, 200)
            title_x = title_x0 + (index % 5) * delta_x
            title_y = title_y0 + (index // 5) * delta_y + new_dy

            score_x = score_x0 + (index % 5) * delta_x
            score_y = score_y0 + (index // 5) * delta_y + new_dy

            const_x = const_x0 + (index % 5) * delta_x
            const_y = const_y0 + (index // 5) * delta_y + new_dy

            text_data_extend = [
                {
                    # 曲名
                    'text': title_text,
                    'position': (title_x, title_y),
                    'font': title_font,
                    'color': 'black',
                },
                {
                    # 分数
                    'text': f"{song.get('score', 0):,}",
                    'position': (score_x, score_y),
                    'font': score_font,
                    'color': 'black',
                    'anchor': 'lm'
                },
                {
                    # 定数和Rating
                    'text': f"{const:.1f}   >  {int(song.get('rating', 0) * 100 + 1e-10) / 100:.2f}",
                    'position': (const_x, const_y),
                    'font': const_font,
                    'color': 'black',
                }
            ]

            text_data.extend(text_data_extend)

            # 难度标
            color = (255, 255, 255, 255) # 默认为白色
            if level_index == 4: 
                color = (0, 0, 0, 255) # 黑色
            elif level_index == 3:
                color = (165, 89, 255, 255) # 紫色
            elif level_index == 2:
                color = (255, 0, 0, 255) # 红色
            elif level_index == 1:
                color = (255, 192, 0, 255) # 橙色
            elif level_index == 0:
                color = (0, 176, 80, 255) # 绿色
            
            p5 = (p5_x0 + (index % 5) * delta_x, p5_y0 + (index // 5) * delta_y + new_dy)
            p6 = (p6_x0 + (index % 5) * delta_x, p6_y0 + (index // 5) * delta_y + new_dy)
            p7 = (p7_x0 + (index % 5) * delta_x, p7_y0 + (index // 5) * delta_y + new_dy)
            p8 = (p8_x0 + (index % 5) * delta_x, p8_y0 + (index // 5) * delta_y + new_dy)

            if color != (255, 255, 255, 255):
                # 绘制平行四边形
                draw.polygon(
                    [p5, p6, p7, p8],
                    fill=color # 填充颜色
                )

            # FC / AJ / AJC 标
            if song.get('full_combo') != None:
                # 添加右下角的等腰梯形缎带

                # 一些补正
                extra_dx, extra_dy = 0, 0
                if index % 5 == 1:
                    extra_dx = -1
                if index % 5 == 4:
                    extra_dx = 1
                if index // 5 == 5:
                    extra_dy = -1
                if index //5 == 6:
                    extra_dy = -1

                p1 = (p1_x0 + (index % 5) * delta_x + extra_dx, p1_y0 + (index // 5) * delta_y + extra_dy + new_dy)
                p2 = (p2_x0 + (index % 5) * delta_x + extra_dx, p2_y0 + (index // 5) * delta_y + extra_dy + new_dy)
                p3 = (p3_x0 + (index % 5) * delta_x + extra_dx, p3_y0 + (index // 5) * delta_y + extra_dy + new_dy)
                p4 = (p4_x0 + (index % 5) * delta_x + extra_dx, p4_y0 + (index // 5) * delta_y + extra_dy + new_dy)

                color = (255, 255, 255, 255) # 默认为白色
                if song['full_combo'] == 'fullcombo':
                    color = (86, 236, 24, 255) # 绿色
                elif song['full_combo'] == 'alljustice':
                    color = (251, 173, 29, 255) # 橙色
                elif song['full_combo'] == 'alljusticecritical':
                    self.paste_gradient_polygon(
                        canvas,
                        [p1, p2, p3, p4],
                        [
                            (255, 140, 140, 255),  # 柔和红
                            (255, 170, 150, 255),  # 橙红
                            (245, 180, 120, 255),  # 橙金
                            (230, 190, 110, 255),  # 暗橙黄
                            (200, 200, 130, 255),  # 黄绿
                            (160, 210, 180, 255),  # 蓝绿
                            (130, 200, 220, 255),  # 浅蓝
                            (100, 160, 210, 255),  # 中蓝
                            (80, 130, 200, 255),   # 深蓝
                        ],
                        angle_deg=135
                    )

                if color != (255, 255, 255, 255):
                    # 绘制梯形
                    draw.polygon(
                        [p1, p2, p3, p4],
                        fill=color # 填充颜色
                    )
            
            index += 1

        # 添加文字
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font=item['font'],
                    anchor=item.get('anchor'))
        
        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"b30_{random_name}.webp"
        
        output_path = self.save_compact_webp(canvas, output_path)
        return str(output_path)
    
    async def create_overpower_image(self, data, player_name="CHUNITHM", arg="level", output_path=None):
        background_path = self.bgs_dir / 'general_bg.png'

        # 画布尺寸
        line_num = len(data)
        bg_spacing = 230
        canvas_width = 1200
        canvas_height = 240 + line_num * bg_spacing

        # 加载背景图片
        if background_path and os.path.exists(background_path):
            # 加载背景图片并调整到画布大小
            background = Image.open(background_path).convert('RGBA')
            background = background.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            canvas = background.copy()
        else:
            # 没有背景图片，使用纯色背景
            canvas = Image.new('RGB', (canvas_width, canvas_height), (20, 20, 30))

        # 确保后续 alpha 合成稳定
        canvas = canvas.convert('RGBA')

        # 在顶部画一个平行四边形（ID框）
        frame_base = 400
        frame_height = 89
        frame_tan_a = 3
        p1_x, p1_y = 110, 60
        p2_x, p2_y = p1_x + frame_base, p1_y
        p3_x, p3_y = round(p2_x - frame_height / frame_tan_a), p2_y + frame_height
        p4_x, p4_y = p3_x - frame_base, p3_y

        parallelogram_points = [
            (p1_x, p1_y),
            (p2_x, p2_y),
            (p3_x, p3_y),
            (p4_x, p4_y),
        ]
        canvas = self.draw_shadow_parallelogram(
            canvas,
            points=parallelogram_points,
            fill=(255, 255, 255, 235),
            shadow_offset=(3, 3),
            shadow_color=(15, 25, 70, 130),
            blur_radius=10,
        )

        # 圆角矩形底
        bg_x0, bg_y0 = 90, 220
        bg_width = 1020
        bg_height = 175
        rect_specs = []

        # 进度条
        progress_bar_x0 = 60
        progress_bar_y0 = 100 # 进度条左上角的点在圆角矩形内的相对位置
        progress_bar_base = 915
        progress_bar_height = 45
        progress_bar_tan_a = 3
        parallelograms = []

        for index in range(len(data)):
            # 圆角矩形底
            rect_specs.append(
                {
                    'xy': (bg_x0, bg_y0 + index * bg_spacing, bg_x0 + bg_width, bg_y0 + bg_height + index * bg_spacing),
                    'radius': 34,
                    'fill': (255, 255, 255, 255),
                    'shadow_offset': (3, 3),
                    'shadow_color': (15, 25, 70, 130),
                    'blur_radius': 10,
                }
            )

            # 进度条
            p5_x, p5_y = bg_x0 + progress_bar_x0, bg_y0 + progress_bar_y0 + index * bg_spacing
            p6_x, p6_y = p5_x + progress_bar_base, p5_y
            p7_x, p7_y = round(p6_x - progress_bar_height / progress_bar_tan_a), p6_y + progress_bar_height
            p8_x, p8_y = p7_x - progress_bar_base, p7_y
            parallelogram_points = [
                (p5_x, p5_y),
                (p6_x, p6_y),
                (p7_x, p7_y),
                (p8_x, p8_y),
            ]
            parallelograms.append(
                {
                    'points': parallelogram_points,
                    'fill': (240, 240, 240, 255),
                    'shadow_offset': (3, 3),
                    'shadow_color': (15, 25, 70, 130),
                    'blur_radius': 7,
                }
            )

        for spec in rect_specs:
            canvas = self.draw_shadow_rounded_rect(canvas, **spec)    

        for parallelogram in parallelograms:
            canvas = self.draw_shadow_parallelogram(canvas, **parallelogram)

        # 玩家昵称
        name_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 48)
        name_x = 295
        name_y = 107

        text_data = [
            {
                # 昵称
                'text': unicodedata.normalize("NFKC", player_name), # 全角转半角
                'position': (name_x, name_y),
                'font': name_font,
                'color': 'black',
                'anchor': 'mm'
            },
        ]

        draw = ImageDraw.Draw(canvas, 'RGBA')

        small_base = 20

        # 左侧的绿色平行四边形
        parallelogram_points = [
            (p1_x, p1_y),
            (p1_x + small_base, p2_y),
            (p4_x + small_base, p3_y),
            (p4_x, p4_y),
        ]
        draw.polygon(
            parallelogram_points,
            fill=(0, 204, 107, 255) # 绿色
        )
        
        # 右侧的紫色平行四边形
        parallelogram_points = [
            (p2_x - small_base, p1_y),
            (p2_x, p2_y),
            (p3_x, p3_y),
            (p3_x - small_base, p4_y),
        ]
        draw.polygon(
            parallelogram_points,
            fill=(165, 89, 255, 255) # 紫色
        )

        level_sign_tan_a = 3
        if arg == "level":
            level_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 40)
            level_sign_x0 = 45
            level_sign_y0 = 30
            level_sign_base = 13
            level_sign_height = 40
        elif arg == "version":
            level_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 33)
            level_sign_x0 = 35
            level_sign_y0 = 35
            level_sign_base = 11
            level_sign_height = 34
        if arg == "genre":
            level_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 36)
            level_sign_x0 = 45
            level_sign_y0 = 30
            level_sign_base = 12
            level_sign_height = 37
        level_font.set_variation_by_name('SemiBold')

        if arg == "level" or arg == "genre":
            small_para_x0 = 160
        elif arg == "version":
            small_para_x0 = 165
        small_para_y0 = 26
        small_para_base = 7
        small_para_height = 21
        small_para_tan_a = 3
        small_para_spacing = 95
        small_para_color = [
            (0, 0, 0, 255), # 黑色
            (236, 48, 138, 255), # 玫红色
            (235, 155, 15, 255), # 橙色
            (70, 210, 20, 255), # 绿色
            (236, 48, 138, 255), # 玫红色
            (235, 155, 15, 255), # 橙色
            (0, 0, 0, 255), # 黑色
        ]

        small_texts = ["ALL", "AJC", "AJ", "FC", "SSS+", "SSS", "OVERPOWER"]
        small_text_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 22)
        small_texts_list = ["all", "ajc", "aj", "fc", "sssp", "sss"]

        num_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 30)
        num_font.set_variation_by_name('SemiBold')

        op_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 26)
        op_font.set_variation_by_name('SemiBold')

        # 进度条的进度
        progress_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 34)
        progress_font.set_variation_by_name('SemiBold')

        index = 0

        # 添加一些普通的平行四边形 以及 文字
        for key, value in data.items():
            # key 是 level，value 是 对应数据
            p9_x, p9_y = bg_x0 + level_sign_x0, bg_y0 + level_sign_y0 + index * bg_spacing
            p10_x, p10_y = p9_x + level_sign_base, p9_y
            p11_x, p11_y = round(p10_x - level_sign_height / level_sign_tan_a), p10_y + level_sign_height
            p12_x, p12_y = p11_x - level_sign_base, p11_y
            parallelogram_points = [
                (p9_x, p9_y),
                (p10_x, p10_y),
                (p11_x, p11_y),
                (p12_x, p12_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(165, 89, 255, 255) # 紫色
            )

            if arg == "level":
                text_data.append(
                    {
                        # 等级
                        'text': key,
                        'position': (p9_x + 18, p9_y - 3),
                        'font': level_font,
                        'color': 'black',
                    }
                )
            elif arg == "version":
                text_data.append(
                    {
                        # 版本
                        'text': self.res_mgr.version_abbr_map.get(key, key),
                        'position': (p9_x + 15, p9_y - 1),
                        'font': level_font,
                        'color': 'black',
                    }
                )
            elif arg == "genre":
                text_data.append(
                    {
                        # 分类
                        'text': self.res_mgr.genre_abbr_map.get(key, key),
                        'position': (p9_x + 17, p9_y - 1),
                        'font': level_font,
                        'color': 'black',
                    }
                )

            # 进度条
            progress_base = min(int(progress_bar_base * value['user_op'] / value['total_op']), progress_bar_base)
            p5_x, p5_y = bg_x0 + progress_bar_x0, bg_y0 + progress_bar_y0 + index * bg_spacing
            p6_x, p6_y = p5_x + progress_base, p5_y
            p7_x, p7_y = round(p6_x - progress_bar_height / progress_bar_tan_a), p6_y + progress_bar_height
            p8_x, p8_y = p7_x - progress_base, p7_y
            parallelogram_points = [
                (p5_x, p5_y),
                (p6_x, p6_y),
                (p7_x, p7_y),
                (p8_x, p8_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(86, 236, 24, 255), # 绿色
            )

            text_data.append(
                {
                    # OP百分比
                    'text': f"{math.floor(value['user_op'] / value['total_op'] * 10000 + 1e-10) / 10000:.2%}",
                    'position': (round((p5_x + p5_x + progress_bar_base) / 2), (p5_y + p7_y) // 2),
                    'font': progress_font,
                    'color': 'black',
                    'anchor': 'mm',
                }
            )

            for Index in range(7):
                p13_x, p13_y = bg_x0 + small_para_x0 + Index * small_para_spacing, bg_y0 + small_para_y0 + index * bg_spacing
                p14_x, p14_y = p13_x + small_para_base, p13_y
                p15_x, p15_y = round(p14_x - small_para_height / small_para_tan_a), p14_y + small_para_height
                p16_x, p16_y = p15_x - small_para_base, p15_y
                parallelogram_points = [
                    (p13_x, p13_y),
                    (p14_x, p14_y),
                    (p15_x, p15_y),
                    (p16_x, p16_y),
                ]
                draw.polygon(
                    parallelogram_points,
                    fill=small_para_color[Index]
                )

                text_data.append(
                    {
                        # 小标题
                        'text': small_texts[Index],
                        'position': (p13_x + 12, p13_y - 2),
                        'font': small_text_font,
                        'color': 'black',
                    }
                )

                if Index < 6:
                    text_data.append(
                        {
                            # 数字
                            'text': str(value[small_texts_list[Index]]),
                            'position': (p13_x + 10, p13_y + 21),
                            'font': num_font,
                            'color': 'black',
                        }
                    )
                else:
                    text_data.append(
                        {
                            # OVERPOWER数字
                            'text': f"{value['user_op']:.2f} / {value['total_op']:.1f}",
                            'position': (p13_x + 10, p13_y + 23),
                            'font': op_font,
                            'color': 'black',
                        }
                    )

            index += 1

        # 添加文字
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font=item['font'],
                    anchor=item.get('anchor'))

        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"overpower_{random_name}.webp"
        
        output_path = self.save_compact_webp(canvas, output_path)
        return str(output_path)
    
    async def create_list_image(self, data, player_name="CHUNITHM", output_path=None):
        background_path = self.bgs_dir / 'general_bg.png'

        # 画布尺寸
        canvas_width = 1600
        canvas_height = 245

        for const, value in data.items():
            songs = value['songs']
            row_num = (len(songs) + 7) // 8
            canvas_height += 120 + row_num * 221 + 25

        # 加载背景图片
        if background_path and os.path.exists(background_path):
            # 加载背景图片并调整到画布大小
            background = Image.open(background_path).convert('RGBA')
            background = background.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            canvas = background.copy()
        else:
            # 没有背景图片，使用纯色背景
            canvas = Image.new('RGB', (canvas_width, canvas_height), (20, 20, 30))

        # 确保后续 alpha 合成稳定
        canvas = canvas.convert('RGBA')

        # 在顶部画一个平行四边形（ID框）
        name_frame_base = 430
        name_frame_height = 100
        name_frame_tan_a = 3
        p5_x, p5_y = 110, 70
        p6_x, p6_y = p5_x + name_frame_base, p5_y
        p7_x, p7_y = round(p6_x - name_frame_height / name_frame_tan_a), p6_y + name_frame_height
        p8_x, p8_y = p7_x - name_frame_base, p7_y

        parallelogram_points = [
            (p5_x, p5_y),
            (p6_x, p6_y),
            (p7_x, p7_y),
            (p8_x, p8_y),
        ]
        canvas = self.draw_shadow_parallelogram(
            canvas,
            points=parallelogram_points,
            fill=(255, 255, 255, 235),
            shadow_offset=(3, 3),
            shadow_color=(15, 25, 70, 130),
            blur_radius=10,
        )

        # 玩家昵称
        name_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 64)
        name_x = 320
        name_y = 120

        text_data = [
            {
                # 昵称
                'text': unicodedata.normalize("NFKC", player_name), # 全角转半角
                'position': (name_x, name_y),
                'font': name_font,
                'color': 'black',
                'anchor': 'mm'
            },
        ]

        # 定数框参数
        frame_base = 250
        frame_height = 75
        frame_tan_a = 3

        # 圆角矩形底
        col_num = 8
        bg_x0, bg_y0 = 81, 120
        bg_width = 157
        bg_height = 195
        bg_spacing_x = 183
        bg_spacing_y = 221
        rect_specs = []
        long_rect_specs = []

        top_y = 220
        
        for const, value in data.items():
            songs = value['songs']
            # 在左边画一个平行四边形（定数框）
            p1_x, p1_y = 110, top_y
            p2_x, p2_y = p1_x + frame_base, p1_y
            p3_x, p3_y = round(p2_x - frame_height / frame_tan_a), p2_y + frame_height
            p4_x, p4_y = p3_x - frame_base, p3_y

            parallelogram_points = [
                (p1_x, p1_y),
                (p2_x, p2_y),
                (p3_x, p3_y),
                (p4_x, p4_y),
            ]
            canvas = self.draw_shadow_parallelogram(
                canvas,
                points=parallelogram_points,
                fill=(255, 255, 255, 235),
                shadow_offset=(3, 3),
                shadow_color=(15, 25, 70, 130),
                blur_radius=10,
            )

            # 统计信息的圆角矩形底
            long_rect_specs.append(
                {
                    'xy': (400, top_y - 5, 1515, top_y + 80),
                    'radius': 20,
                    'fill': (255, 255, 255, 255),
                    'shadow_offset': (3, 3),
                    'shadow_color': (15, 25, 70, 130),
                    'blur_radius': 10,
                }
            )

            # 单曲圆角矩形底
            index = 0
            for key, song in songs.items():
                level_index = song.get('level_index', -1)
                x1 = bg_x0 + (index % col_num) * bg_spacing_x
                y1 = top_y + bg_y0 + (index // col_num) * bg_spacing_y
                x2 = x1 + bg_width
                y2 = y1 + bg_height

                # 背景颜色
                color = (255, 255, 255, 255) # 默认为白色
                if level_index == 4: 
                    color = (30, 30, 30, 255) # 灰色
                elif level_index == 3:
                    color = (165, 89, 255, 255) # 紫色
                elif level_index == 2:
                    color = (255, 0, 0, 255) # 红色
                elif level_index == 1:
                    color = (255, 192, 0, 255) # 橙色
                elif level_index == 0:
                    color = (0, 176, 80, 255) # 绿色

                rect_specs.append(
                    {
                        'xy': (x1, y1, x2, y2),
                        'radius': 31,
                        'top_color': color,
                        'bottom_color': (255, 255, 255, 255),
                        'transition_center': 0.7,
                        'transition_width': 0.28,
                        'shadow_offset': (3, 3),
                        'shadow_color': (15, 25, 70, 130),
                        'shadow_blur': 10,
                    }
                )
                index += 1

            row_num = (len(songs) + col_num - 1) // col_num
            top_y += bg_y0 + row_num * bg_spacing_y + 25

        for spec in rect_specs:
            canvas = self.draw_shadow_gradient_rounded_rect(canvas, **spec)

        for spec in long_rect_specs:
            canvas = self.draw_shadow_rounded_rect(canvas, **spec)

        const_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 52)
        const_font.set_variation_by_name('Bold')

        # 玩家昵称
        name_font = ImageFont.truetype(self.fonts_dir / 'LINESeedJP_TTF_Bd.ttf', 52)
        name_x = 311
        name_y = 122

        text_data = [
            {
                # 昵称
                'text': unicodedata.normalize("NFKC", player_name), # 全角转半角
                'position': (name_x, name_y),
                'font': name_font,
                'color': 'black',
                'anchor': 'mm'
            },
        ]

        draw = ImageDraw.Draw(canvas, 'RGBA')
        
        small_base = 16
        jacket_size = 170
        jacket_radius = 26

        small_para_x0 = 440
        small_para_y0 = 13
        small_para_base = 7
        small_para_height = 21
        small_para_tan_a = 3
        small_para_spacing = 97
        small_para_color = [
            (0, 0, 0, 255), # 黑色
            (236, 48, 138, 255), # 玫红色
            (235, 155, 15, 255), # 橙色
            (70, 210, 20, 255), # 绿色
            (236, 48, 138, 255), # 玫红色
            (235, 155, 15, 255), # 橙色
            (48, 139, 236, 255), # 蓝色
            (0, 0, 0, 255), # 黑色
        ]

        small_texts = ["ALL", "AJC", "AJ", "FC", "SSS+", "SSS", "SS+", "OVERPOWER (只计算最高难度谱)"]
        small_text_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 22)
        small_texts_list = ["all", "ajc", "aj", "fc", "sssp", "sss", "ssp"]

        num_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 30)
        num_font.set_variation_by_name('SemiBold')

        op_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 26)
        op_font.set_variation_by_name('SemiBold')

        score_font = ImageFont.truetype(self.fonts_dir / 'OPPO Sans 4.0.ttf', 28)
        score_font.set_variation_by_name('SemiBold')

        # 角标
        right_x0 = 144
        bottom_y0 = 183
        leg_len1 = 27
        leg_len2 = 54
        p9_x0, p9_y0 = right_x0, bottom_y0 - leg_len2
        p10_x0, p10_y0 = right_x0, bottom_y0 - leg_len1
        p11_x0, p11_y0 = right_x0 - leg_len1, bottom_y0
        p12_x0, p12_y0 = right_x0 - leg_len2, bottom_y0

        top_y = 220

        for const, value in data.items():
            songs = value['songs']
            count = value['count']

            p1_x, p1_y = 110, top_y
            p2_x, p2_y = p1_x + frame_base, p1_y
            p3_x, p3_y = round(p2_x - frame_height / frame_tan_a), p2_y + frame_height
            p4_x, p4_y = p3_x - frame_base, p3_y

            # 左侧的绿色平行四边形
            parallelogram_points = [
                (p1_x, p1_y),
                (p1_x + small_base, p2_y),
                (p4_x + small_base, p3_y),
                (p4_x, p4_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(0, 204, 107, 255) # 绿色
            )
            
            # 右侧的紫色平行四边形
            parallelogram_points = [
                (p2_x - small_base, p1_y),
                (p2_x, p2_y),
                (p3_x, p3_y),
                (p3_x - small_base, p4_y),
            ]
            draw.polygon(
                parallelogram_points,
                fill=(165, 89, 255, 255) # 紫色
            )

            const_x = 220
            const_y = top_y + 38

            if isinstance(const, str):
                const_text = const
            else:
                const_text = f"{const:.1f}"

            text_data.append(
                {
                    'position': (const_x, const_y),
                    'text': const_text,
                    'color': (0, 0, 0, 255),
                    'font': const_font,
                    'anchor': 'mm'
                }
            )

            # 统计信息
            for index in range(8):
                p13_x, p13_y = small_para_x0 + index * small_para_spacing, top_y + small_para_y0
                p14_x, p14_y = p13_x + small_para_base, p13_y
                p15_x, p15_y = round(p14_x - small_para_height / small_para_tan_a), p14_y + small_para_height
                p16_x, p16_y = p15_x - small_para_base, p15_y
                parallelogram_points = [
                    (p13_x, p13_y),
                    (p14_x, p14_y),
                    (p15_x, p15_y),
                    (p16_x, p16_y),
                ]
                draw.polygon(
                    parallelogram_points,
                    fill=small_para_color[index]
                )

                text_data.append(
                    {
                        # 小标题
                        'text': small_texts[index],
                        'position': (p13_x + 12, p13_y - 2),
                        'font': small_text_font,
                        'color': 'black',
                    }
                )

                if index < 7:
                    text_data.append(
                        {
                            # 数字
                            'text': str(count.get(small_texts_list[index], 0)),
                            'position': (p13_x + 10, p13_y + 23),
                            'font': num_font,
                            'color': 'black',
                        }
                    )
                else:
                    if count['total_op'] < 1e-10:
                        text_data.append(
                            {
                                # OVERPOWER数字
                                'text': "0.00 / 0.0 ( - %)",
                                'position': (p13_x + 10, p13_y + 25),
                                'font': op_font,
                                'color': 'black',
                            }
                        )
                    else:
                        text_data.append(
                            {
                                # OVERPOWER数字
                                'text': f"{count['user_op']:.2f} / {count['total_op']:.1f} ({math.floor(count['user_op'] / count['total_op'] * 10000 + 1e-10) / 10000:.2%})",
                                'position': (p13_x + 10, p13_y + 25),
                                'font': op_font,
                                'color': 'black',
                            }
                        )

            # 每首歌
            index = 0
            for key, song in songs.items():
                # ========== 曲绘部分 ==========
                song_id = song.get('id', 2353) # 其实2353是幻想即兴曲（
                jacket_path = await self.res_mgr.get_jacket(song_id)
                level_index = song.get('level_index', -1)

                jacket_x = bg_x0 + (index % col_num) * bg_spacing_x + 12
                jacket_y = top_y + bg_y0 + (index // col_num) * bg_spacing_y + 12

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
                        blur_radius=6 * scale_factor,
                        shadow_opacity=110
                    )

                    # 最后再缩小回目标尺寸
                    final_size = (jacket_size, jacket_size)
                    jacket_with_shadow = jacket_with_shadow.resize(final_size, Image.Resampling.LANCZOS)

                    # 计算偏移（因为有扩展区域）
                    blur_extension = 6 * 3  # blur_radius * 3
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

                # 成绩
                if song.get('score', 0) < 1000:
                    delta_y = 161
                else:
                    delta_y = 160
                text_data.append(
                    {
                        # 分数
                        'text': f"{song.get('score', 0):,}",
                        'position': (jacket_x + 68, jacket_y + delta_y),
                        'font': score_font,
                        'color': 'black',
                        'anchor': 'mm',
                    }
                )

                # FC / AJ / AJC标识
                p9 = (jacket_x + p9_x0, jacket_y + p9_y0)
                p10 = (jacket_x + p10_x0, jacket_y + p10_y0)
                p11 = (jacket_x + p11_x0, jacket_y + p11_y0)
                p12 = (jacket_x + p12_x0, jacket_y + p12_y0)

                color = (255, 255, 255, 255) # 默认为白色
                if song['full_combo'] == 'fullcombo':
                    color = (86, 236, 24, 255) # 绿色
                elif song['full_combo'] == 'alljustice':
                    color = (251, 173, 29, 255) # 橙色
                elif song['full_combo'] == 'alljusticecritical':
                    self.paste_gradient_polygon(
                        canvas,
                        [p9, p10, p11, p12],
                        [
                            (255, 140, 140, 255),  # 柔和红
                            (255, 170, 150, 255),  # 橙红
                            (245, 180, 120, 255),  # 橙金
                            (230, 190, 110, 255),  # 暗橙黄
                            (200, 200, 130, 255),  # 黄绿
                            (160, 210, 180, 255),  # 蓝绿
                            (130, 200, 220, 255),  # 浅蓝
                            (100, 160, 210, 255),  # 中蓝
                            (80, 130, 200, 255),   # 深蓝
                        ],
                        angle_deg=135
                    )

                if color != (255, 255, 255, 255):
                    # 绘制梯形
                    draw.polygon(
                        [p9, p10, p11, p12],
                        fill=color # 填充颜色
                    )

                index += 1
            
            row_num = (len(songs) + col_num - 1) // col_num
            top_y += bg_y0 + row_num * bg_spacing_y + 25

        small_name_base = 20

        # 左侧的绿色平行四边形
        parallelogram_points = [
            (p5_x, p5_y),
            (p5_x + small_name_base, p6_y),
            (p8_x + small_name_base, p7_y),
            (p8_x, p8_y),
        ]
        draw.polygon(
            parallelogram_points,
            fill=(0, 204, 107, 255) # 绿色
        )
        
        # 右侧的紫色平行四边形
        parallelogram_points = [
            (p6_x - small_name_base, p5_y),
            (p6_x, p6_y),
            (p7_x, p7_y),
            (p7_x - small_name_base, p8_y),
        ]
        draw.polygon(
            parallelogram_points,
            fill=(165, 89, 255, 255) # 紫色
        )

        # 添加文字
        for item in text_data:
            draw.text(item['position'], item['text'], 
                    fill=item['color'], font=item['font'],
                    anchor=item.get('anchor'))

        # 保存图片
        if output_path is None:
            random_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            output_path = self.temp_dir / f"list_{random_name}.webp"
        
        output_path = self.save_compact_webp(canvas, output_path)
        return str(output_path)