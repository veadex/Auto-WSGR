import time
from types import SimpleNamespace as SN

import AutoWSGR.fight.exercise as ef
from AutoWSGR.constants import literals
from AutoWSGR.fight.battle import BattlePlan
from AutoWSGR.fight.normal_fight import NormalFightPlan
from AutoWSGR.game.game_operation import (
    Expedition,
    RepairByBath,
    SetSupport,
    get_rewards,
)
from AutoWSGR.ocr.digit import get_loot_and_ship, get_resources
from AutoWSGR.scripts.main import start_script


class DailyOperation:
    def __init__(self, setting_path) -> None:
        self.timer = start_script(setting_path)

        self.config = SN(**self.timer.config.daily_automation)
        self.config.DEBUG = False

        if self.config.auto_expedition:
            self.expedition_plan = Expedition(self.timer)

        if self.config.auto_battle:
            self.battle_plan = BattlePlan(
                self.timer, plan_path=f"battle/{self.config.battle_type}.yaml"
            )

        if self.config.auto_normal_fight:
            self.fight_plans = []
            self.fight_complete_times = []
            for plan in self.config.normal_fight_tasks:
                self.fight_plans.append(
                    NormalFightPlan(
                        self.timer,
                        plan_path=f"normal_fight/{plan[0]}.yaml",
                        fleet_id=plan[1],
                    )
                )
                self.fight_complete_times.append([0, plan[2]])  # 二元组， [已完成次数, 目标次数]

        self.start_time = self.last_time = time.time()

    def run(self):
        # 自动战役，直到超过次数
        if self.config.auto_battle:
            ret = literals.OPERATION_SUCCESS_FLAG
            while ret == literals.OPERATION_SUCCESS_FLAG:
                ret = self.battle_plan.run()

        # 自动开启支援
        if self.config.auto_set_support:
            SetSupport(self.timer, True)

        get_loot_and_ship(self.timer)  # 获取胖次掉落和船只掉落数据
        get_resources(self.timer)

        exf = ef.NormalExercisePlan(self.timer, "exercise/plan_1.yaml")
        exf.run()

        # 自动出征
        if self.config.auto_normal_fight:
            while self._has_unfinished() and self._ship_max():
                task_id = self._get_unfinished()

                plan = self.fight_plans[task_id]
                ret = plan.run()

                if ret == literals.OPERATION_SUCCESS_FLAG:
                    self.fight_complete_times[task_id][0] += 1
                elif ret == literals.DOCK_FULL_FLAG:
                    break  # 不解装则结束出征

                if time.time() - self.last_time >= 5 * 60:
                    self._expedition()
                    self._gain_bonus()
                    self.last_time = time.time()

        # 自动远征
        while True:
            self._bath_repair()
            self._expedition()
            self._gain_bonus()
            time.sleep(360)

    def _has_unfinished(self):
        return any(times[0] < times[1] for times in self.fight_complete_times)

    def _get_unfinished(self):
        for i, times in enumerate(self.fight_complete_times):
            if times[0] < times[1]:
                return i

    def _expedition(self):
        if self.config.auto_expedition:
            self.expedition_plan.run(True)

    def _gain_bonus(self):
        if self.config.auto_gain_bonus:
            get_rewards(self.timer)

    def _bath_repair(self):
        if self.config.auto_bath_repair:
            RepairByBath(self.timer)

    def _ship_max(self):
        if self.config.stop_maxship:
            if self.timer.got_ship_num < 500:
                return True
            else:
                return False
        else:
            return True
