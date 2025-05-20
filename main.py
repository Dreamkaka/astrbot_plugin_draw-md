import requests
import base64
import json
import os
import io
from PIL import Image
from datetime import datetime
import uuid

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("draw-md", "xiaohan", "使用ModelScope API生成图像的AstrBot插件", "v1.5", "https://github.com/yourusername/astrbot_plugin_draw-md")
class DrawMD(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.load_config()
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)

    def load_config(self):
        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        schema_file = os.path.join(os.path.dirname(__file__), "_conf_schema.json")
        try:
            with open(schema_file, "r", encoding="utf-8") as f:
                config_schema = json.load(f)
            self.API_URL = config_schema["API_URL"]["default"]
            self.API_KEY = config_schema["API_KEY"]["default"]
            self.MODEL = config_schema["MODEL"]["default"]
            self.OUTPUT_DIR = config_schema["OUTPUT_DIR"]["default"]
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                self.API_URL = user_config.get("API_URL", self.API_URL)
                self.API_KEY = user_config.get("API_KEY", self.API_KEY)
                self.MODEL = user_config.get("MODEL", self.MODEL)
                self.OUTPUT_DIR = user_config.get("OUTPUT_DIR", self.OUTPUT_DIR)
                logger.info("从用户配置文件加载配置成功")
            else:
                logger.info("未找到用户配置文件，使用默认值")
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            self.API_URL = "https://api-inference.modelscope.cn/v1/images/generations"
            self.API_KEY = "a8440c49-e85b-4971-b9c6-3843de7ea75a"
            self.MODEL = "MusePublic/14_ckpt_SD_XL"
            self.OUTPUT_DIR = "generated_images"

    @filter.command("draw")
    async def draw_command(self, event: AstrMessageEvent, *args):
        message_str = event.message_str
        prompt = message_str.replace("/draw", "", 1).strip()
        if not prompt:
            yield event.plain_result("请提供图像描述，例如：/draw 一只可爱的猫")
            return

        size = "1024x1024"
        n = 1

        # 解析参数
        if "--size" in prompt:
            parts = prompt.split("--size")
            prompt = parts[0].strip()
            size_part = parts[1].strip()
            if size_part:
                if size_part.startswith("small"):
                    size = "512x512"
                elif size_part.startswith("large"):
                    size = "1024x1024"
                elif "x" in size_part:
                    size = size_part.split()[0]
        if "--n" in prompt:
            parts = prompt.split("--n")
            prompt = parts[0].strip()
            count_part = parts[1].strip()
            if count_part:
                try:
                    n = int(count_part.split()[0])
                    n = max(1, min(n, 4))
                except ValueError:
                    n = 1

        yield event.plain_result(f"正在生成图像: '{prompt}'，请稍候...")

        result = await self.generate_image(prompt, n, size)
        if result["success"]:
            for img_path in result["images"]:
                result_obj = MessageEventResult()
                result_obj.text = f"生成的图像 - '{prompt}'"
                result_obj.image_path = img_path
                yield result_obj
        else:
            yield event.plain_result(f"图像生成失败: {result['error']}")

    @filter.command("draw_help")
    async def draw_help(self, event: AstrMessageEvent, *args):
        help_text = """绘图插件使用帮助:
/draw [描述] - 生成图像
  可选参数:
  --size small - 生成512x512的图像
  --size large - 生成1024x1024的图像(默认)
  --size 宽x高 - 生成自定义尺寸的图像
  --n 数量 - 生成指定数量的图像(1-4)

示例:
/draw 一只可爱的猫
/draw 一座山脉风景 --size small
/draw 科幻城市 --size 768x512 --n 2

/draw_help - 显示此帮助信息"""
        yield event.plain_result(help_text)

    async def generate_image(self, prompt, n=1, size="1024x1024"):
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.MODEL,
            "prompt": prompt,
            "n": n,
            "size": size
        }
        result = {
            "success": False,
            "images": [],
            "error": ""
        }
        try:
            response = requests.post(self.API_URL, headers=headers, json=payload)
            response.raise_for_status()
            api_result = response.json()
            image_items = api_result.get("data") or api_result.get("images")
            if not image_items:
                result["error"] = "API返回了意外的格式，找不到图像数据"
                return result

            for i, item in enumerate(image_items):
                image_data = None
                if "b64_image" in item:
                    image_data = base64.b64decode(item["b64_image"])
                elif "url" in item:
                    img_response = requests.get(item["url"])
                    img_response.raise_for_status()
                    image_data = img_response.content
                else:
                    continue

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                filename = os.path.join(self.OUTPUT_DIR, f"{timestamp}_{unique_id}_{i+1}.png")
                try:
                    image = Image.open(io.BytesIO(image_data))
                    image.save(filename)
                    result["images"].append(filename)
                except Exception as e:
                    result["error"] = f"保存图像时出错: {str(e)}"
                    return result

            if result["images"]:
                result["success"] = True
            return result

        except requests.exceptions.RequestException as e:
            error_msg = f"API请求失败: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f" (状态码: {e.response.status_code})"
            result["error"] = error_msg
            return result
        except Exception as e:
            result["error"] = f"发生错误: {str(e)}"
            return result

    async def terminate(self):
        logger.info("绘图插件已卸载")