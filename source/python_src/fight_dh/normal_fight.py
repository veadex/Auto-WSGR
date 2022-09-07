from .common import FightInfo, FightPlan, NodeLevelDecisionBlock, Ship
from utils.math_functions import CalcDis
from utils.logger import logit
from utils.io import recursive_dict_update
import copy
import time

import yaml
from constants.custom_expections import ImageNotFoundErr
from constants.image_templates import (ChapterImage, FightImage,
                                       IdentifyImages, NumberImage,
                                       SymbolImage)
from constants.keypoint_info import FIGHT_CONDITIONS_POSITON, POINT_POSITION
from constants.other_constants import INFO1, INFO2, INFO3, NODE_LIST
from game.game_operation import ConfirmOperation, MoveTeam, QuickRepair
from game.get_game_info import DetectShipStatu, GetEnemyCondition
from game.identify_pages import identify_page
from game.switch_page import goto_game_page, process_bad_network
from controller.run_timer import Timer, ClickImage, GetImagePosition, ImagesExist, WaitImage


"""
常规战决策模块
TODO: 1.资源点
"""


class NormalFightInfo(FightInfo):
    # ==================== Unified Interface ====================
    def __init__(self, timer: Timer) -> None:
        super().__init__(timer)

        self.start_page = "map_page"
        self.chapter = 1  # 章节名,战役为 'battle', 演习为 'exercise'
        self.map = 1  # 节点名
        self.ship_position = (0, 0)
        self.node = "A"  # 常规地图战斗中,当前战斗点位的编号

        self.successor_states = {
            "proceed": {
                "yes": ["fight_condition", "spot_enemy_success", "formation", "fight_period"],
                "no": ["map_page"]
            },
            "fight_condition": ["spot_enemy_success", "formation", "fight_period"],
            "spot_enemy_success": {
                "detour": ["fight_condition", "spot_enemy_success", "formation"],
                "retreat": ["map_page"],
                "fight": ["formation"],
            },
            "formation": ["fight_period"],
            "fight_period": ["night", "result"],
            "night": {
                "yes": ["night_fight_period"],
                "no": [["result", 5]],
            },
            "night_fight_period": ["result"],
            "result": ["proceed", "map_page", "get_ship", "flagship_severe_damage"],    # 两页战果
            "get_ship": ["proceed", "map_page", "flagship_severe_damage"],  # 捞到舰船
            "flagship_severe_damage": ["map_page"],
        }

        self.state2image = {
            "proceed": [FightImage[5], 5],
            "fight_condition": [FightImage[10], 15],
            "spot_enemy_success": [FightImage[2], 15],
            "formation": [FightImage[1], 15],
            "fight_period": [SymbolImage[4], 3],
            "night": [FightImage[6], 120],
            "night_fight_period": [SymbolImage[4], 3],
            "result": [FightImage[3], 60],
            "get_ship": [SymbolImage[8], 5],
            "flagship_severe_damage": [FightImage[4], 5],
            "map_page": [IdentifyImages["map_page"][0], 5]
        }

    def reset(self):
        self.last_state = "proceed"
        self.last_action = "yes"
        self.state = "proceed"  # 初始状态等同于 proceed选择yes

        # TODO: 舰船信息，暂时不用
        self.ally_ships = [Ship() for _ in range(6)]  # 我方舰船状态
        self.enemy_ships = [Ship() for _ in range(6)]  # 敌方舰船状态

    def _before_match(self):
        # 点击加速
        if self.state in ["proceed", "fight_condition"]:
            p = self.timer.Android.click(380, 520, delay=0, enable_subprocess=True, print=0, no_log=True)

        self.timer.UpdateScreen()

        # 在地图上走的过程中获取舰船位置
        if self.state in ["proceed"]:
            self._update_ship_position(self.timer)
            self._update_ship_point(self.timer)

        # 1. proceed, 资源点 (TODO 验证)
        # 2. get_ship, 锁定新船 (OK)
        if self.state in ["proceed", "get_ship"]:
            ConfirmOperation(self.timer, delay=0)

    def _after_match(self):
        # 在某些State下可以记录额外信息
        if self.state == "spot_enemy_success":
            GetEnemyCondition(self.timer, 'fight')
        elif self.state == "result":
            DetectShipStatu(self.timer, 'sumup')
            self.fight_result.detect_result()

    # ======================== Functions ========================
    @logit(level=INFO1)
    def _update_ship_position(self):
        """在战斗移动界面(有一个黄色小船在地图上跑)更新黄色小船的位置

        Args:
            timer (Timer): 记录器
        """
        pos = GetImagePosition(self.timer, FightImage[7], 0, 0.8)
        if pos is None:
            pos = GetImagePosition(self.timer, FightImage[8], 0, 0.8)
        if pos is None:
            return
        self.ship_position = pos

    def _update_ship_point(self):
        """更新黄色小船(战斗地图上那个)所在的点位 (1-1A 这种,'A' 就是点位) 

        Args:
            timer (Timer): 记录器

        """

        self.node = "A"
        for i in range(26):
            ch = chr(ord('A') + i)
            node1 = (self.chapter, self.map, ch)
            node2 = (self.chapter, self.map, self.node)
            if node1 not in POINT_POSITION:
                break
            if (CalcDis(POINT_POSITION[node1], self.ship_position) < CalcDis(POINT_POSITION[node2], self.ship_position)):
                self.node = ch


class NormalFightPlan(FightPlan):
    """" 常规战斗的决策模块 """

    # ==================== Unified Interface ====================
    def __init__(self, timer: Timer, plan_path, default_path) -> None:
        super().__init__(timer)

        default_args = yaml.load(open(default_path, 'r', encoding='utf-8'), Loader=yaml.FullLoader)
        plan_defaults, node_defaults = default_args["normal_fight_defaults"], default_args["node_defaults"]
        # 加载地图计划
        plan_args = yaml.load(open(plan_path, 'r', encoding='utf-8'), Loader=yaml.FullLoader)
        args = recursive_dict_update(plan_defaults, plan_args, skip=['node_args'])
        self.__dict__.update(args)
        # 加载各节点计划
        self.nodes = {}
        for node_name in self.selected_nodes:
            node_args = copy.deepcopy(node_defaults)
            node_args = recursive_dict_update(node_args, plan_args['node_args'][node_name])
            self.nodes[node_name] = NodeLevelDecisionBlock(timer, node_args)

        # 构建信息存储结构
        self.Info = NormalFightInfo(self.timer)

    def _enter_fight(self) -> str:
        """
        从任意界面进入战斗.

        :return: 进入战斗状态信息，包括['success', 'dock is full].
        """
        goto_game_page(self.timer, 'map_page')
        self._change_fight_map(self.chapter, self.map)
        goto_game_page(self.timer, 'fight_prepare_page')
        MoveTeam(self.timer, self.fleet_id)
        QuickRepair(self.timer, self.repair_mode)
        start_time = time.time()
        self.timer.UpdateScreen()
        while identify_page(self.timer, 'fight_prepare_page', need_screen_shot=False):
            self.timer.Android.click(900, 500, delay=0)
            self.timer.UpdateScreen()
            if ImagesExist(self.timer, SymbolImage[3], need_screen_shot=0):
                return "dock is full"
            if time.time() - start_time > 15:
                if process_bad_network(self.timer):
                    if identify_page(self.timer, 'fight_prepare_page'):
                        return self._enter_fight(self.timer)
                else:
                    raise TimeoutError("map_fight prepare timeout")
        return "success"

    def _make_decision(self) -> str:

        self.Info.update_state()
        state = self.Info.state

        # 进行MapLevel的决策
        if state == "map_page":
            return "fight end"

        elif state == "fight_condition":
            value = self.fight_condition
            self.timer.Android.click(*FIGHT_CONDITIONS_POSITON[value])
            self.Info.last_action = value
            return "fight continue"

        elif state == "spot_enemy_success":
            if self.Info.node not in self.selected_nodes:  # 不在白名单之内直接SL
                self.timer.Android.click(677, 492, delay=0)
                self.Info.last_action = "retreat"
                return "fight end"

        elif state == "proceed":
            is_proceed = self.nodes[self.Info.node].proceed
            if is_proceed:
                self.timer.Android.click(325, 350)
                self.Info.last_action = "yes"
                return "fight continue"
            else:
                self.timer.Android.click(615, 350)
                self.Info.last_action = "no"
                return "fight end"

        elif state == "flagship_severe_damage":
            ClickImage(self.timer, FightImage[4], must_click=True, delay=0.25)
            return 'fight end'

        # 进行通用NodeLevel决策
        action, fight_stage = self.nodes[self.Info.node].make_decision(state, self.Info.last_state, self.Info.last_action)
        self.Info.last_action = action
        return fight_stage

    # ======================== Functions ========================
    @logit(level=INFO1)
    def _get_chapter(self):
        """在出征界面获取当前章节(远征界面也可获取)

        Raises:
            TimeoutError: 无法获取当前章节

        Returns:
            int: 当前章节
        """
        for try_times in range(5):
            time.sleep(0.15 * 2 ** try_times)
            self.timer.UpdateScreen()
            for i in range(1, len(ChapterImage)):
                if (ImagesExist(self.timer, ChapterImage[i], 0)):
                    return i
        raise TimeoutError("can't vertify chapter")

    @logit(level=INFO1)
    def _get_node(self, need_screen_shot=True):
        """不够完善"""
        """出征界面获取当前显示地图节点编号
        例如在出征界面显示的地图 2-5,则返回 5
        
        Returns:
            int: 节点编号
        """

        # TODO（已修复）: 你改了循环变量的名字，但没改下面
        for try_times in range(5):
            time.sleep(.15 * 2 ** try_times)
            if (need_screen_shot):
                self.timer.UpdateScreen()
            for try_times in range(1, 7):
                if (ImagesExist(self.timer, NumberImage[try_times], 0, confidence=0.95)):
                    return try_times
        raise TimeoutError("can't vertify map")

    @logit(level=INFO2)
    def _move_chapter(self, target, chapter_now=None):
        """移动地图章节到 target
        含错误检查

        Args:
            timer (Timer): _description_
            target (int): 目标
            chapter_now (_type_, optional): 现在的章节. Defaults to None.
        Raise:
            ImageNotFoundErr:如果没有找到章节标志或地图界面标志
        """
        if (identify_page(self.timer, 'map_page') == False):
            raise ImageNotFoundErr("not on page 'map_page' now")

        if (chapter_now == target):
            return
        try:
            if chapter_now is None:
                chapter_now = self._get_chapter()
            print("NowChapter:", chapter_now)
            if (chapter_now > target):
                if (chapter_now - target >= 3):
                    chapter_now -= 3
                    self.timer.Android.click(95, 97, delay=0)
                elif (chapter_now - target == 2):
                    chapter_now -= 2
                    self.timer.Android.click(95, 170, delay=0)
                elif (chapter_now - target == 1):
                    chapter_now -= 1
                    self.timer.Android.click(95, 229, delay=0)

            elif (chapter_now - target <= -3):
                chapter_now += 3
                self.timer.Android.click(95, 485, delay=0)
            elif (chapter_now - target == -2):
                chapter_now += 2
                self.timer.Android.click(95, 416, delay=0)
            elif (chapter_now - target == -1):
                chapter_now += 1
                self.timer.Android.click(95, 366, delay=0)

                if (WaitImage(self.timer, ChapterImage[chapter_now]) == False):
                    raise ImageNotFoundErr("after movechapter operation but the chapter do not move")
                time.sleep(0.15)
                self._move_chapter(target, chapter_now)
        except:
            print("can't move chapter, time now is", time.time)
            if process_bad_network(self.timer, 'move_chapter'):
                self._move_chapter(target)
            else:
                raise ImageNotFoundErr("unknow reason can't find chapter image")

    @logit(level=INFO2)
    def _move_node(self, target):
        """改变地图节点,不检查是否有该节点
        含网络错误检查
        Args:
            timer (Timer): _description_
            target (_type_): 目标节点

        """
        if (identify_page(self.timer, 'map_page') == False):
            raise ImageNotFoundErr("not on page 'map_page' now")

        NowNode = self._get_node()
        try:
            print("NowNode:", NowNode)
            if (target > NowNode):
                for i in range(1, target - NowNode + 1):
                    self.timer.Android.swipe(715, 147, 552, 147, duration=0.25)
                    if (WaitImage(self.timer, NumberImage[NowNode + i]) == False):
                        raise ImageNotFoundErr("after movechapter operation but the chapter do not move")
                    time.sleep(0.15)
            else:
                for i in range(1, NowNode - target + 1):
                    self.timer.Android.swipe(552, 147, 715, 147, duration=0.25)
                    if (WaitImage(self.timer, NumberImage[NowNode - i]) == False):
                        raise ImageNotFoundErr("after movechapter operation but the chapter do not move")
                    time.sleep(0.15)
        except:
            print("can't move chapter, time now is", time.time)
            if (process_bad_network(self.timer)):
                self._move_node(target)
            else:
                raise ImageNotFoundErr("unknow reason can't find number image" + str(target))

    @logit(level=INFO3)
    def _change_fight_map(self, chapter, map):
        """在地图界面改变战斗地图(通常是为了出征)
        可以处理网络错误
        Args:
            timer (Timer): _description_
            chapter (int): 目标章节
            map (int): 目标节点

        Raises:
            ValueError: 不在地图界面
            ValueError: 不存在的节点
        """
        if (self.timer.now_page.name != 'map_page'):
            raise ValueError("can't _change_fight_map at page:", self.timer.now_page.name)
        if map not in NODE_LIST[chapter]:
            raise ValueError('map' + str(map) + 'not in the list of chapter' + str(chapter))

        self._move_chapter(chapter)
        self._move_node(map)
        self.Info.chapter = self.chapter
        self.Info.map = self.map