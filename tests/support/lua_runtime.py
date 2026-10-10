"""Execute production Lua; record planned actions without inventing postconditions."""
from pathlib import Path
from lupa import LuaRuntime
from tests.support.touchsprite_adapter import Screen

ROOT = Path(__file__).resolve().parents[2]
SEMANTICS = {'wild': '野鬼', 'horse': '马面', 'zombie': '僵尸', 'skeleton': '骷髅怪',
             'snake_wine': '蛇胆酒', 'dew_wine': '珍露酒', 'tiger_wine': '虎骨酒',
             'plum_wine': '梅花酒', 'wine': '酒', 'weapon': '兵器'}


def semantic_target(name, category):
    if not name:
        return None
    return SEMANTICS.get(name, {'香炉': '香'}.get(category, category))


class Runtime:
    def __init__(self, screen, capture_hook=None, planning=False):
        self.screen = screen
        self.actions = []
        self.logs = []
        self.capture_hook = capture_hook
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.getScreenSize = lambda: (self.screen.frame.shape[1], self.screen.frame.shape[0])
        g.keepScreen = lambda value: None
        g.getColor = lambda x, y: self.screen.color(x, y)
        g.findMultiColorInRegionFuzzy = lambda *args: self.screen.find(*args)
        g.offline_log = lambda c, kind, detail: self.logs.append({'kind': kind, 'detail': detail})
        g.offline_capture = self.capture
        g.tap = lambda x, y: self.actions.append({'kind': 'tap', 'point': [int(x), int(y)]})
        g.mSleep = lambda milliseconds: None
        g.touchDown = lambda *args: None
        g.touchMove = lambda *args: None
        g.touchUp = lambda *args: None
        self.lua.execute(f"package.path='{ROOT.as_posix()}/src/?.lua;'..package.path")
        self.lua.execute("""
            package.preload['dfx.log']=function() return {write=offline_log} end
            package.preload['dfx.snapshot']=function() return {capture=offline_capture} end
        """)
        if planning:
            g.offline_plan_tap = self.plan_tap
            g.offline_plan_swipe = lambda *args: self.actions.append({'kind': 'scroll'}) or False
            self.lua.execute("""
                package.preload['common.device']=function() return {
                    tap=offline_plan_tap, swipe=offline_plan_swipe,
                    wait=function() return false end
                } end
            """)

    def capture(self, ctx, label):
        if self.capture_hook:
            self.capture_hook(self, label)

    def require(self, module):
        result = self.lua.eval(f"require('{module}')")
        return result[0] if isinstance(result, tuple) else result

    def page(self, task):
        return self.require(f'tasks.{task}.pages').state()

    def question(self):
        result = self.require('tasks.zhuagui.find').identify()
        name, category, *reason = result if isinstance(result, tuple) else (result, None)
        return semantic_target(name, category)

    def count(self):
        return self.require('tasks.zhuagui.counter').read()

    def locate(self):
        # Only simulate the input transport, not the subsequent game's success.
        return self.require('tasks.zhuagui.find').solve(self.lua.table())

    def plan_tap(self, ctx, feature, label):
        found = self.require('common.detector').find(feature)
        if not found:
            return False
        self.actions.append({'kind': 'tap', 'point': [int(found['x'] + feature['tap_offset'][1]),
                                                    int(found['y'] + feature['tap_offset'][2])]})
        return True
