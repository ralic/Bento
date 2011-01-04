import os
import shutil
import subprocess
import errno

from bento._config \
    import \
        IPKG_PATH
from bento.installed_package_description import \
    InstalledPkgDescription, iter_files

from bento.commands.errors \
    import \
        UsageException
from bento.commands.configure \
    import \
        get_configured_state
from bento.commands.core import \
    Command
from bento.core.utils import \
    pprint

def _rollback_operation(line):
    operation, arg = line.split()
    if operation == "MKDIR":
        try:
            os.rmdir(arg)
        except OSError, e:
            if e.errno != 66:
                raise
    elif operation == "COPY":
        os.remove(arg)
    else:
        raise ValueError("Unknown operation: %s" % operation)

def rollback_transaction(f):
    fid = open(f)
    try:
        lines = fid.readlines()
        for i in range(len(lines)-1, -1, -1):
            _rollback_operation(lines[i])
            lines.pop(i)
    finally:
        fid.close()
        if len(lines) < 1:
            os.remove(f)
        else:
            fid = open(f, "w")
            try:
                fid.writelines(lines)
            finally:
                fid.close()

class TransactionLog(object):
    def __init__(self, f):
        if os.path.exists(f):
            raise IOError("file %s already exists" % f)
        open(f, "w").close()
        self.f = open(f, "r+w")

    def copy(self, source, target, category):
        if os.path.exists(target):
            self.rollback()
            raise ValueError("File %s already exists, rolled back installation" % target)
        d = os.path.dirname(target)
        if not os.path.exists(d):
            self.makedirs(d)
        self.f.write("COPY %s\n" % target)
        shutil.copy(source, target)
        if category == "executables":
            os.chmod(target, 0755)

    def makedirs(self, name, mode=0777):
        head, tail = os.path.split(name)
        if not tail:
            head, tail = os.path.split(head)
        if head and tail and not os.path.exists(head):
            try:
                self.makedirs(head, mode)
            except OSError, e:
                if e.errno != errno.EEXIST:
                    raise
            if tail == os.curdir:
                return
        self.mkdir(name, mode)

    def mkdir(self, name, mode=0777):
        self.f.write("MKDIR %s\n" % name) 
        self.f.flush()
        os.mkdir(name, mode)

    def close(self):
        self.f.close()

    def rollback(self):
        self.f.flush()
        self.f.seek(0, 0)
        lines = self.f.readlines()
        for line in lines[::-1]:
            _rollback_operation(line.strip())

def copy_installer(source, target, kind):
    dtarget = os.path.dirname(target)
    if not os.path.exists(dtarget):
        os.makedirs(dtarget)
    shutil.copy(source, target)
    if kind == "executables":
        os.chmod(target, 0755)

def unix_installer(source, target, kind):
    if kind in ["executables"]:
        mode = "755"
    else:
        mode = "644"
    cmd = ["install", "-m", mode, source, target]
    strcmd = "INSTALL %s -> %s" % (source, target)
    pprint('GREEN', strcmd)
    if not os.path.exists(os.path.dirname(target)):
        os.makedirs(os.path.dirname(target))
    subprocess.check_call(cmd)

class InstallCommand(Command):
    long_descr = """\
Purpose: install the project
Usage:   bentomaker install [OPTIONS]."""
    short_descr = "install the project."
    def run(self, ctx):
        opts = ctx.cmd_opts
        o, a = self.parser.parse_args(opts)
        if o.help:
            self.parser.print_help()
            return

        if not os.path.exists(IPKG_PATH):
            msg = "%s file not found ! (Did you run build ?)" % IPKG_PATH
            raise UsageException(msg)

        ipkg = InstalledPkgDescription.from_file(IPKG_PATH)
        s = get_configured_state()
        scheme = dict([(k, s.paths[k]) for k in s.paths])
        ipkg.update_paths(scheme)
        file_sections = ipkg.resolve_paths()

        trans = TransactionLog("transaction.log")
        try:
            for kind, source, target in iter_files(file_sections):
                trans.copy(source, target, kind)
        finally:
            trans.close()