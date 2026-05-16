#!/usr/bin/env python3
"""生成PWA图标 - PNG格式，兼容iOS"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, output_path):
    """创建一个简单的图标"""
    # 创建透明背景
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 画圆形背景
    padding = size // 10
    draw.ellipse([padding, padding, size - padding, size - padding], fill='#4F46E5')
    
    # 画书本emoji (简化版，用文字代替)
    # 由于emoji在不同系统显示不一致，我们画一个简单的书形状
    center = size // 2
    book_width = size * 0.5
    book_height = size * 0.4
    
    # 书脊
    left = center - book_width // 2
    top = center - book_height // 2
    right = center + book_width // 2
    bottom = center + book_height // 2
    
    # 书本形状（两页）
    draw.rectangle([left, top, right, bottom], fill='white', outline='#3B82F6', width=3)
    
    # 书脊线
    mid = (left + right) // 2
    draw.line([mid, top, mid, bottom], fill='#3B82F6', width=2)
    
    # 保存
    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")

def main():
    web_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 生成多个尺寸的图标
    sizes = [48, 72, 96, 128, 144, 152, 192, 384, 512]
    
    for size in sizes:
        output_path = os.path.join(web_dir, f'icon-{size}.png')
        create_icon(size, output_path)
    
    print("\n✓ 图标生成完成！")
    print(f"位置: {web_dir}")

if __name__ == '__main__':
    main()