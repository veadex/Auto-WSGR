import gc
import os

import easyocr
import numpy as np
import pytesseract

from AutoWSGR.controller.run_timer import Timer
from AutoWSGR.ocr.ship_name import recognize_number

# import pytesseract
# from AutoWSGR.ocr.ship_name import recognize_number
from AutoWSGR.utils.api_image import crop_image
from AutoWSGR.utils.io import yaml_to_dict

POS = yaml_to_dict(os.path.join(os.path.dirname(__file__), "relative_location.yaml"))


def load_easyocr():
    global en_reader
    print("1")
    en_reader = easyocr.Reader(["en"], gpu=False)


def image_to_number(image: np.ndarray):
    """根据图片返回数字

    Args:
        image (np.ndarray): 图片

    Returns:
        int, None: 存在则返回数字,否则为 None
    """
    # result = pytesseract.image_to_string(image).strip()
    result = recognize_number(image)
    result = result[0][1]
    if len(result) == 0:
        return None
    scale = 1

    if "K" in result:
        result = result[:-2]
        scale = 1000
    if "M" in result:
        result = result[:-2]
        scale = 10**6

    return scale * int(result)


def get_resources(timer: Timer):
    """根据 timer 所处界面获取对应资源数据
    部分 case 会没掉,请重写
    """
    timer.goto_game_page("main_page")
    # timer.Android.click(650,15)
    timer.update_screen()
    image = timer.screen
    ret = {}
    for key in POS["main_page"]["resources"]:
        image_crop = crop_image(
            image,
            *POS["main_page"]["resources"][key],
            resolution=timer.config.resolution,
        )
        raw_str = pytesseract.image_to_string(
            image_crop, config="--oem 1"
        ).strip()  # 原始字符串
        # image_crop = crop_image(image, *POS["main_page"]["resources"][key],resolution= timer.config.resolution)
        # ex_list = "KM/.mk."
        # raw_str = recognize_number(image_crop, ex_list=ex_list)
        try:
            # raw_str = raw_str[0][1]
            if raw_str[-1] == "K":
                num = raw_str[:-1]
                unit = 1000
            elif raw_str[-1] == "M":
                num = raw_str[:-1]
                unit = 1000000
            else:
                num = raw_str
                unit = 1

            ret[key] = eval(num) * unit
            timer.logger.info(f"{key}:{ret[key]}")
        except:
            # 容错处理，如果监测出来不是数字则出错了
            timer.logger.error(f"读取资源失败：{raw_str}")
            timer.logger.error(f"读取资源失败：{ret}")
    return ret


def get_loot_and_ship(timer: Timer):
    """获取掉落数据"""
    timer.goto_game_page("map_page")
    timer.update_screen()
    image = timer.screen
    ret = {}
    for key in POS["map_page"]:
        image_crop = crop_image(
            image, *POS["map_page"][key], resolution=timer.config.resolution
        )
        raw_str = pytesseract.image_to_string(
            image_crop, config="--oem 1"
        ).strip()  # 原始字符串
        # easyocr 识别

        # ex_list = "/"
        # image_crop = crop_image(image, *POS["map_page"][key],resolution= timer.config.resolution)
        # raw_str = recognize_number(image_crop, ex_list=ex_list)
        # char_list = "0123456789"
        # for ch in ex_list:
        #    if char_list.find(ch) == -1:
        #        char_list += ch
        # raw_str = en_reader.readtext(
        #    image_crop,
        #    allowlist=char_list,
        #    min_size=7,
        #    text_threshold=0.55,
        #    low_text=0.3,
        #    )
        try:
            # raw_str = raw_str[0][1]
            ret[key] = eval(raw_str.split("/")[0])  # 当前值
            timer.logger.debug(f"今日打捞:{ret}")
            ret[key + "_max"] = eval(raw_str.split("/")[1])  # 最大值
            timer.logger.debug(f"今日打捞:{ret}")
        except:
            if key == "loot":
                timer.logger.error("读今日战利品失败！")
            else:
                timer.logger.error("读今日捞船数量失败！")
            # quit()
    try:
        timer.got_ship_num = ret.get("ship")
    except:
        timer.logger.error("赋值给got_ship_num失败")
        timer.got_ship_num = 0

    try:
        timer.got_loot_num = ret.get("loot")
        if timer.got_loot_num == None:
            timer.got_loot_num = 0
    except:
        timer.logger.error("赋值给got_loot_num失败")
        timer.got_loot_num = 0
    timer.logger.info(f"已掉落胖次:{timer.got_loot_num}")
    timer.logger.info(f"已掉落舰船:{timer.got_ship_num}")
    return ret
