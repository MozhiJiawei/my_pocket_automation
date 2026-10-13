"""Execute production Lua; record planned actions without inventing postconditions."""
from pathlib import Path
from functools import lru_cache
from lupa import LuaRuntime
from tests.support.touchsprite_adapter import Screen

ROOT = Path(__file__).resolve().parents[2]
MODULE_VERSIONS=None

def freeze_module_versions():
    """One evaluator worker uses one source version throughout its run."""
    global MODULE_VERSIONS
    MODULE_VERSIONS={}
    for path in (ROOT/'src').rglob('*.lua'):
        name='.'.join(path.relative_to(ROOT/'src').with_suffix('').parts)
        version=path.stat();MODULE_VERSIONS[name]=(path.as_posix(),version.st_mtime_ns,version.st_size)


@lru_cache(maxsize=256)
def compiled_source(path, source):
    # Cache executable code, never module tables or predictions. Each frame
    # still loads modules into a fresh Lua VM with its own globals and state.
    compiler=LuaRuntime(encoding=None)
    dump=compiler.eval(b'function(source,name) return string.dump(assert(load(source,name))) end')
    return dump(source,('@'+path).encode('utf-8'))


@lru_cache(maxsize=256)
def versioned_module_code(path, modified_ns, size):
    # Reuse immutable executable bytes across fresh VMs. File changes invalidate
    # this cache; Lua module tables and recognition results are never shared.
    source=Path(path).read_bytes()
    return compiled_source(path,source),path


def module_code(name):
    if MODULE_VERSIONS is not None:
        version=MODULE_VERSIONS.get(name)
        return versioned_module_code(*version) if version else (None,None)
    path=ROOT/'src'/Path(name.replace('.','/')+'.lua')
    try:version=path.stat()
    except FileNotFoundError:return None,None
    return versioned_module_code(path.as_posix(),version.st_mtime_ns,version.st_size)
SEMANTICS = {'wild': '野鬼', 'horse': '马面', 'bull': '牛头', 'paper': '黄纸', 'zombie': '僵尸', 'skeleton': '骷髅怪',
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
        self.shimen_observation=None
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
        g.offline_module_code=module_code
        self.lua.execute("""
            local original=package.searchers[2]
            package.searchers[2]=function(name)
                local code,path=offline_module_code(name)
                if not code then return original(name) end
                return assert(load(code,'@'..path,'b')),path
            end
        """)
        if hasattr(screen,'configure_catalog') and screen.groups is None:
            entries=self.lua.table_from({'task_card':self.lua.table_from([
                self.require('tasks.zhuagui.assets.task_card')])})
            catalogs=[self.require('tasks.zhuagui.assets.catalog'),
                      self.require('tasks.zhuagui.assets.puzzle')['families'],entries]
            extra=[]
            if (ROOT/'src/tasks/shimen/assets/catalog.lua').is_file():
                factories=self.require('tasks.shimen.assets.catalog')
                extra=[self.lua.table_from({name:factory() for name,factory in factories.items()})];catalogs.extend(extra)
                bank=[]
                for entry in self.require('tasks.shimen.assets.questions')['topics'].values():
                    bank.extend(entry['features'].values())
                entries['shimen_questions']=self.lua.table_from(bank)
            screen.configure_catalog(*catalogs,enumerate_catalogs=extra)
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

    def capture(self, ctx, label, kind=None):
        if self.capture_hook:
            self.capture_hook(self, label)

    def close(self):
        # Lua-held Python callbacks otherwise keep this VM and its frame alive.
        if self.lua is None:return
        self.shimen_observation=None
        globals=self.lua.globals()
        for name in ('getScreenSize','keepScreen','getColor','findMultiColorInRegionFuzzy',
                     'offline_log','offline_capture','tap','mSleep','touchDown','touchMove','touchUp',
                     'offline_plan_tap','offline_plan_swipe'):
            globals[name]=None
        self.lua.execute('for k in pairs(package.loaded) do package.loaded[k]=nil end; for k in pairs(package.preload) do package.preload[k]=nil end; collectgarbage("collect")')
        self.lua=None

    def require(self, module):
        result = self.lua.eval(f"require('{module}')")
        return result[0] if isinstance(result, tuple) else result

    def page(self, task):
        return self.require(f'tasks.{task}.pages').state()

    def question(self, task='zhuagui'):
        if task=='shimen':
            return self.read_shimen()[0]
        result = self.require('tasks.zhuagui.find').identify()
        name, category, *reason = result if isinstance(result, tuple) else (result, None)
        return semantic_target(name, category)

    def count(self):
        return self.require('tasks.zhuagui.counter').read()

    def locate(self, task='zhuagui'):
        if task=='shimen':
            topic,matches,reason=self.read_shimen()
            self.actions.extend({'kind':'tap','point':[int(matches[i]['x']),int(matches[i]['y'])]}
                                for i in range(1,len(matches)+1))
            return topic,reason
        # Only simulate the input transport, not the subsequent game's success.
        return self.require('tasks.zhuagui.find').solve(self.lua.table())

    def read_shimen(self):
        # One immutable frame, one production observation. Both assertions
        # inspect that observation; no truth or result crosses frame/VM boundaries.
        if self.shimen_observation is None:
            self.shimen_observation=self.require('tasks.shimen.find').read()
        return self.shimen_observation

    def plan_tap(self, ctx, feature, label):
        found = self.require('common.detector').find(feature)
        if not found:
            return False
        offset=found['tap_offset'] or feature['tap_offset']
        self.actions.append({'kind': 'tap', 'point': [int(found['x'] + offset[1]),
                                                    int(found['y'] + offset[2])]})
        return True
