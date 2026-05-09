#!/usr/bin/env python3
"""
使用 Codex 生成图片的封装脚本。

Codex 通过编写 Python 代码（PIL 库）来绘制图片，支持各种场景：
- 风景图（夕阳、山水、星空等）
- 几何艺术
- 数据可视化
- 自定义插画

用法:
    python scripts/codex_image.py "生成一张夕阳下的湖面风景图"
    python scripts/codex_image.py "生成一张科技感十足的抽象几何图案" -o output/tech.png
    python scripts/codex_image.py "生成一张卡通风格的小猫钓鱼图" -s 1024x768
"""

import argparse
import os
import subprocess
import sys
import tempfile


def build_prompt(description: str, size: str = "1400x900") -> str:
    """构建给 Codex 的提示词。"""
    width, height = size.split("x")
    return f"""生成一张图片，保存到指定路径。

要求：
- 图片内容：{description}
- 尺寸：{width}x{height} 像素
- 使用 Python 的 PIL/Pillow 库绘制
- 确保图片美观、色彩丰富、细节充足
- 如果包含自然场景，使用渐变、多层渲染增加真实感
- 保存后验证文件是否存在并输出文件路径

请直接执行 Python 代码生成图片，不要只给出代码。"""


def run_codex(prompt: str, output_file: str, model: str = "gpt-5.4") -> bool:
    """调用 codex exec 生成图片。"""
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)

    # 构建 codex 命令
    # 使用 danger-full-access 和 bypass 来允许文件写入
    cmd = [
        "codex", "exec",
        "-m", model,
        "-s", "danger-full-access",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o", "/tmp/codex_last_output.txt",
        prompt,
    ]

    # 设置环境变量，让 Codex 知道输出路径
    env = os.environ.copy()
    env["CODEX_IMAGE_OUTPUT"] = output_file

    print(f"🎨 调用 Codex 生成图片...")
    print(f"   描述: {prompt[:80]}...")
    print(f"   输出: {output_file}")
    print()

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=False,
            text=True,
            timeout=300,  # 5 分钟超时
        )

        # 检查输出文件是否生成
        if os.path.exists(output_file):
            size = os.path.getsize(output_file)
            print(f"\n✅ 图片生成成功！")
            print(f"   路径: {output_file}")
            print(f"   大小: {size / 1024:.1f} KB")
            return True
        else:
            # 可能在 /tmp 下，尝试查找
            print(f"\n⚠️  指定路径未找到图片，尝试查找...")
            return False

    except subprocess.TimeoutExpired:
        print("\n❌ Codex 执行超时（5分钟）")
        return False
    except FileNotFoundError:
        print("\n❌ 未找到 codex 命令，请确认已安装: npm install -g @openai/codex")
        return False
    except Exception as e:
        print(f"\n❌ 执行出错: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="使用 Codex 生成图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "夕阳下的湖面风景"
  %(prog)s "卡通小猫钓鱼" -o output/cat.png
  %(prog)s "科技感几何图案" -s 1920x1080 -m gpt-5.4
        """
    )
    parser.add_argument("description", help="图片描述（支持中文）")
    parser.add_argument("-o", "--output", default=None, help="输出文件路径（默认: output/codex_<timestamp>.png）")
    parser.add_argument("-s", "--size", default="1400x900", help="图片尺寸，格式: 宽x高（默认: 1400x900）")
    parser.add_argument("-m", "--model", default="gpt-5.4", help="Codex 模型（默认: gpt-5.4）")
    parser.add_argument("--sandbox", action="store_true", help="使用沙箱模式（可能无法保存文件）")

    args = parser.parse_args()

    # 确定输出路径
    if args.output:
        output_file = args.output
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_desc = "".join(c if c.isalnum() else "_" for c in args.description[:20])
        output_file = f"output/codex_{safe_desc}_{timestamp}.png"

    # 构建提示词
    prompt = build_prompt(args.description, args.size)

    # 运行 Codex
    success = run_codex(prompt, output_file, args.model)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
