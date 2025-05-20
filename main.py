import requests
import base64
import json
import os
import io
from PIL import Image
from datetime import datetime
import uuid

# 正确的导入方式
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("draw-md", "xiaohan", "使用ModelScope API生成图像的AstrBot插件", "v1.5", "https://github.com/yourusername/astrbot_plugin_draw-md")
class DrawMD(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        
        # 从配置文件加载配置
        self.load_config()
        
        # 创建保存图片的目录
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)
    
    def load_config(self):
        """从配置文件加载配置"""
        # 首先尝试读取用户配置文件
        config_file = os.path.join(os.path.dirname(__file__), "config.json")
        schema_file = os.path.join(os.path.dirname(__file__), "_conf_schema.json")
        
        # 读取schema以获取默认值
        try:
            with open(schema_file, "r", encoding="utf-8") as f:
                config_schema = json.load(f)
                
            # 设置默认值
            self.API_URL = config_schema["API_URL"]["default"]
            self.API_KEY = config_schema["API_KEY"]["default"]
            self.MODEL = config_schema["MODEL"]["default"]
            self.OUTPUT_DIR = config_schema["OUTPUT_DIR"]["default"]
            
            # 尝试读取用户配置文件并覆盖默认值
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    
                # 使用用户配置覆盖默认值
                if "API_URL" in user_config:
                    self.API_URL = user_config["API_URL"]
                if "API_KEY" in user_config:
                    self.API_KEY = user_config["API_KEY"]
                if "MODEL" in user_config:
                    self.MODEL = user_config["MODEL"]
                if "OUTPUT_DIR" in user_config:
                    self.OUTPUT_DIR = user_config["OUTPUT_DIR"]
                    
                logger.info("从用户配置文件加载配置成功")
            else:
                logger.info("未找到用户配置文件，使用默认值")
                
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            # 使用硬编码的默认值
            self.API_URL = "https://api-inference.modelscope.cn/v1/images/generations"
            self.API_KEY = "a8440c49-e85b-4971-b9c6-3843de7ea75a"
            self.MODEL = "MusePublic/14_ckpt_SD_XL"
            self.OUTPUT_DIR = "generated_images"
    
    # 处理绘图命令
    @filter.command("draw")
    async def draw_command(self, event: AstrMessageEvent):
        '''使用ModelScope API生成图像'''
        message_str = event.message_str
        
        # 提取提示词（去掉命令前缀）
        prompt = message_str.replace("/draw", "", 1).strip()
        if not prompt:
            yield event.plain_result("请提供图像描述，例如：/draw 一只可爱的猫")
            return
        
        # 默认参数
        size = "1024x1024"
        n = 1
        
        # 检查是否有额外参数
        if "--size" in prompt:
            parts = prompt.split("--size")
            prompt = parts[0].strip()
            size_part = parts[1].strip()
            
            # 提取尺寸参数
            if size_part:
                if size_part.startswith("small"):
                    size = "512x512"
                elif size_part.startswith("large"):
                    size = "1024x1024"
                elif "x" in size_part:
                    size = size_part.split()[0]
        
        # 检查是否指定数量
        if "--n" in prompt:
            parts = prompt.split("--n")
            prompt = parts[0].strip()
            count_part = parts[1].strip()
            
            # 提取数量参数
            if count_part:
                try:
                    n = int(count_part.split()[0])
                    if n < 1:
                        n = 1
                    elif n > 4:  # 限制最大数量
                        n = 4
                except ValueError:
                    n = 1
        
        # 发送等待消息
        yield event.plain_result(f"正在生成图像: '{prompt}'，请稍候...")
        
        # 生成图像
        result = await self.generate_image(prompt, n, size)
        
        if result["success"]:
            # 发送成功消息和图片
            for img_path in result["images"]:
                # 根据文档，使用正确的方式创建消息结果
                # 使用plain_result方法创建文本消息
                text_result = event.plain_result(f"生成的图像 - '{prompt}'")
                yield text_result
                
                # 创建图片消息
                # 根据文档，我们需要设置事件结果
                # 这里我们直接使用set_result方法设置图片路径
                image_result = MessageEventResult()
                event.set_result(image_result)
                # 添加图片路径到结果中
                image_result.image_path = img_path
                yield image_result
        else:
            # 发送失败消息
            yield event.plain_result(f"图像生成失败: {result['error']}")
    
    # 帮助命令
    @filter.command("draw_help")
    async def draw_help(self, event: AstrMessageEvent):
        '''显示绘图插件的帮助信息'''
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
    
    # 生成图像的方法
    async def generate_image(self, prompt, n=1, size="1024x1024"):
        """
        使用ModelScope API生成图像
        
        参数:
        - prompt: 图像描述
        - n: 生成图像数量
        - size: 图像尺寸
        
        返回:
        - 包含结果信息的字典
        """
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 使用OpenAI风格的请求格式
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
            response.raise_for_status()  # 检查HTTP错误
            
            # 解析响应
            api_result = response.json()
            
            # 适应ModelScope返回的格式
            image_items = None
            if "data" in api_result:
                image_items = api_result["data"]
            elif "images" in api_result:
                image_items = api_result["images"]
            else:
                result["error"] = f"API返回了意外的格式，找不到图像数据"
                return result
                
            # 保存生成的图像
            for i, item in enumerate(image_items):
                image_data = None
                
                if "b64_image" in item:
                    # 直接使用b64_image
                    image_data = base64.b64decode(item["b64_image"])
                elif "url" in item:
                    # 下载URL中的图像
                    img_response = requests.get(item["url"])
                    img_response.raise_for_status()
                    image_data = img_response.content
                else:
                    continue
                    
                # 生成唯一文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                filename = f"{self.OUTPUT_DIR}/{timestamp}_{unique_id}_{i+1}.png"
                
                # 保存图像
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
        """插件终止时的清理工作"""
        logger.info("绘图插件已卸载")