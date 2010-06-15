import os
import copy

from yaku.task \
    import \
        Task
from yaku.task_manager \
    import \
        extension, create_tasks, CompiledTaskGen
from yaku.utils \
    import \
        find_deps, ensure_dir
from yaku.compiled_fun \
    import \
        compile_fun

ccompile, cc_vars = compile_fun("cc", "${CC} ${CFLAGS} ${INCPATH} ${CC_TGT_F}${TGT[0]} ${CC_SRC_F}${SRC}", False)

ccprogram, ccprogram_vars = compile_fun("ccprogram", "${LINK} ${LINKFLAGS} ${LINK_TGT_F}${TGT[0]} ${LINK_SRC_F}${SRC}", False)

cshlink, cshlink_vars = compile_fun("cshlib", "${SHLINK} ${SHLINKFLAGS} ${APP_LIBDIR} ${APP_LIBS} -o ${TGT[0]} ${SRC}", False)

@extension('.c')
def c_hook(self, node):
    tasks = ccompile_task(self, node)
    self.object_tasks.extend(tasks)
    return tasks

def ccompile_task(self, node):
    base = os.path.splitext(node)[0]
    # XXX: hack to avoid creating build/build/... when source is
    # generated. Dealing with this most likely requires a node concept
    if not os.path.commonprefix([self.env["BLDDIR"], base]):
        target = os.path.join(self.env["BLDDIR"], base + ".o")
    else:
        target = base + ".o"
    ensure_dir(target)
    task = Task("cc", inputs=node, outputs=target)
    task.env_vars = cc_vars
    #print find_deps("foo.c", ["."])
    #task.scan = lambda : find_deps(node, ["."])
    #task.deps.extend(task.scan())
    task.env = self.env
    task.func = ccompile
    return [task]

def link_task(self, name):
    objects = [tsk.outputs[0] for tsk in self.object_tasks]
    target = os.path.join(self.env["BLDDIR"], name + ".so")
    ensure_dir(target)
    task = Task("cc_link", inputs=objects, outputs=target)
    task.env = self.env
    task.func = cshlink
    task.env_vars = cshlink_vars
    return [task]

def ccprogram_task(self, name):
    objects = [tsk.outputs[0] for tsk in self.object_tasks]
    target = os.path.join(self.env["BLDDIR"], name)
    ensure_dir(target)
    task = Task("ccprogram", inputs=objects, outputs=target)
    task.env = self.env
    task.func = ccprogram
    task.env_vars = ccprogram_vars
    return [task]

def apply_cpppath(task_gen):
    paths = task_gen.env["CPPPATH"]
    task_gen.env["INCPATH"] = [
            task_gen.env["CPPPAT_FMT"] % p for p in paths]

def apply_libs(task_gen):
    libs = task_gen.env["LIBS"]
    task_gen.env["APP_LIBS"] = [
            task_gen.env["LIBS_FMT"] % lib for lib in libs]

def apply_libdir(task_gen):
    libdir = task_gen.env["LIBDIR"]
    implicit_paths = set([
        os.path.join(task_gen.env["BLDDIR"], os.path.dirname(s))
        for s in task_gen.sources])
    libdir = list(implicit_paths) + libdir
    task_gen.env["APP_LIBDIR"] = [
            task_gen.env["LIBDIR_FMT"] % d for d in libdir]

class CCBuilder(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.env = copy.deepcopy(ctx.env)

    def program(self, name, sources, env=None):
        _env = copy.deepcopy(self.env)
        if env is not None:
            _env.update(env)

        task_gen = CompiledTaskGen("ccprogram", sources, name)
        task_gen.env = _env
        apply_cpppath(task_gen)
        apply_libdir(task_gen)
        apply_libs(task_gen)

        tasks = create_tasks(task_gen, sources)
        ltask = ccprogram_task(task_gen, name)
        tasks.extend(ltask)
        for t in tasks:
            t.env = task_gen.env
        self.ctx.tasks.extend(tasks)

        outputs = []
        for t in ltask:
            outputs.extend(t.outputs)
        return outputs

def get_builder(ctx):
    return CCBuilder(ctx)
