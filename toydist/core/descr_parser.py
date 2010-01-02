import sys
import ast
import re
import platform

from toydist.core.reader import \
        Reader, NextParser, ParseError
from toydist.core.pkg_objects import \
        PathOption, FlagOption, DataFiles, Executable
from toydist.core.parse_utils import \
        comma_list_split

indent_width = 4
header_titles = ['flag', 'library', 'executable', 'extension', 'path',
                 'datafiles']
list_fields = ['sources', 'packages', 'modules', 'buildrequires', 'platforms',
               'extrasourcefiles']
path_fields = ['sources', 'default', 'target', 'extrasourcefiles']
multiline_fields = ['description']

def strip_indents(data):
    lines = [l.rstrip() for l in data]
    cur_indent = 0
    out = []
    for l in lines:
        if l.strip():
            first_char = l.lstrip()[0]
            if first_char in ['"', "'", "#"]:
                continue

            # If line is not a comment or a string, parse
            # its indentation
            indent = (len(l) - len(l.lstrip())) / indent_width - cur_indent
            if indent > 0:
                out.extend(["{"] * indent)
            elif indent < 0:
                out.extend(["}"] * -indent)

            cur_indent += indent

        out.append(l.lstrip())

    out.extend(["}"] * cur_indent)

    return out

# --- expression functions ------------------------------------------------

def flag(foo):
    return bool(foo)

def os_var(name):
    return platform.system().lower() == name

def arch(name):
    return platform.machine() == name

def impl(comparison):
    return bool(comparison)

class VersionCompare(object):
    """Compare version strings, e.g., 2.6.1 >= 2.6.0.

    """
    def __init__(self, ver):
        self._ver = self._parse_ver(ver)

    def _parse_ver(self, ver):
        if not isinstance(ver, tuple):
            ver = ver.split('.')
        ver = [int(v) for v in ver]
        return ver

    def __cmp__(self, ver):
        """Provide the comparison operators."""
        new_ver = self._parse_ver(ver)
        if new_ver == self._ver:
            return 0
        elif self._ver > self._parse_ver(ver):
            return 1
        else:
            return -1

expr_funcs = {'flag': flag,
              'os': os_var,
              'arch': arch,
              'impl': impl}

expr_constants = {'darwin': 'darwin',
                  'macosx': 'darwin',
                  'linux': 'linux',
                  'windows': 'windows',
                  'java': 'java',

                  'i386': 'i386',
                  'i686': 'i686',

                  'python': VersionCompare(sys.version_info[:3]),

                  'true': True,
                  'false': False}

# --- parsers start -------------------------------------------------------

# Refer to http://www.haskell.org/cabal/release/cabal-latest/doc/users-guide/

def key_value(r, store, opt_arg=None):
    line = r.peek()
    if not ':' in line:
        raise NextParser

    if line.split(':')[0].lower() in header_titles:
        raise NextParser

    l = r.pop()
    fields = l.split(':', 1)
    if not len(fields) >= 2:
        r.parse_error('invalid key-value pair')

    if ' ' in fields[0]:
        r.parse_error('key-value cannot contain spaces')

    # Allow flexible text indentation
    key = fields[0].lower()
    value = fields[1]

    # FIXME: this whole stuff to maintain formatting in multi-line is a mess
    if key in multiline_fields:
        long_field = []
        # FIXME: hack to get raw first line of description if the multiline
        # string starts at the same line as the field, i.e.
        # description: some long
        #      string
        oline = r._original_data[r.line-1]
        if ":" in oline:
            value = oline.split(":", 1)[1]
            if value.lstrip():
                long_field.append(value.lstrip())

        istack = []
        while r.peek() == '{':
            istack.append(r.pop())

        if istack:
            while istack and not r.eof():
                line = r.pop(blank=True)
                if line == '{':
                    istack.append(line)
                elif line == '}':
                    istack.pop(-1)
                else:
                    raw_line = r._original_data[r.line-1]
                    # FIXME: remove leading indentation only, do this correctly
                    if raw_line.startswith(" " * indent_width):
                        pline = raw_line[4:]
                    else:
                        pline = raw_line
                    long_field.append(pline)
            long_field[-1] = long_field[-1].rstrip()
            value = "".join(long_field)
        else:
            value = value.strip()
    else:
        long_str_indentation = 0
        while r.peek() == '{':
            r.parse(open_brace)
            long_str_indentation += 1

        for i in range(long_str_indentation):
            while r.wait_for('}'):
                this_line = r.pop(blank=True)
                if not this_line.strip():
                    value += '\n\n'
                else:
                    value += this_line + ' '
            r.parse(close_brace)

        value = value.strip()

    # Packages and modules are lists, handle them specially
    if key in list_fields:
        value = comma_list_split(value)
    elif key == "classifiers":
        value = [v.strip() for v in value.split(",") if v.strip()]
    elif key in ["installdepends"]:
        value = [v.strip() for v in value.split(",") if v.strip()]

    # Handle path(path_variable). Ugly
    if key in path_fields:
        if opt_arg:
            paths = opt_arg.get('paths')
        else:
            paths = {}

    # If the key exists, append the new value, otherwise
    # create a new key-value pair
    if store.has_key(key):
        if key in list_fields:
            store[key].extend(value)
        else:
            raise ParseError("Double entry '%s' (old: %s, new: %s)" % \
                             (key, store[key], value))
    else:
        store[key] = value

def open_brace(r, opt_arg=None):
    r.expect('{', 'Expected indentation to increase')

def close_brace(r, opt_arg=None):
    r.expect('}', 'Expected indentation to decrease')

def _parse_section_header(r, line):
    header = [s.strip() for s in line.split(':')]
    if not len(header) == 2:
        r.parse_error("Invalid section header")
    type = header[0].lower()
    return header, type, header[1]

def section(r, store, flags={}):
    section_header = r.peek()
    if section_header.count(':') < 1: raise NextParser

    section_header, type, name = _parse_section_header(r, section_header)
    if not type in header_titles:
        raise NextParser
    elif type in ['path', 'flag', 'datafiles', 'executable']:
        raise NextParser

    r.pop()
    if not len(section_header) == 2:
        r.parse_error('Invalid section header')

    if not type in store:
        store[type] = {}

    store[type][name] = {}
    store = store[type][name]

    r.parse(open_brace)

    while r.wait_for('}'):
        r.parse((if_statement, section, key_value), store, opt_arg=flags)
    r.parse(close_brace)

def executable_parser(r, store, flags={}):
    line = r.peek()

    section_header, type, name = _parse_section_header(r, line)
    if not type == 'executable':
        raise NextParser

    line = r.pop()

    if not store.has_key("executables"):
        store["executables"] = {}
    elif store["executables"].has_key(name):
        raise ParseError("Executable %s already defined" % name)

    e_store = {}
    r.parse(open_brace)
    while r.wait_for('}'):
        r.parse((if_statement, key_value), e_store, opt_arg=flags)
    r.parse(close_brace)

    for k in ["function", "module"]:
        if not e_store.has_key(k):
            r.parse_error("Each executable section should have a %s field." % k)

    store["executables"][name] = Executable.from_parse_dict(name, e_store)

def datafiles_parser(r, store, flags={}):
    line = r.peek()

    section_header, type, name = _parse_section_header(r, line)
    if not type == 'datafiles':
        raise NextParser

    line = r.pop()

    if not store.has_key("datafiles"):
        store["datafiles"] = {}
    elif store['datafiles'].has_key(name):
        raise ParseError("DataFiles section %s already defined" % name)

    d_store = {}
    r.parse(open_brace)
    while r.wait_for('}'):
        r.parse((if_statement, key_value), d_store, opt_arg=flags)
    r.parse(close_brace)

    store["datafiles"][name] = DataFiles.from_parse_dict(name, d_store)

def path_parser(r, store, flags={}):
    line = r.peek()

    section_header, type, name = _parse_section_header(r, line)
    if not type == 'path':
        raise NextParser

    line = r.pop()
    for key in ['path', 'path_options']:
        if not key in store:
            store[key] = {}

    if store['path_options'].has_key(name):
        raise ParseError("Path %s already defined" % name)

    p_store = {}
    r.parse(open_brace)
    while r.wait_for('}'):
        r.parse((if_statement, key_value), p_store, opt_arg=flags)
    r.parse(close_brace)

    try:
        default = p_store['default']
    except KeyError:
        raise ParseError("Path %s has not default value" % name)

    try:
        descr = p_store['description']
    except KeyError:
        descr = None

    store['path'][name] = default
    store['path_options'][name] = PathOption(name, default, descr)

def flag_parser(r, store, flags={}):
    line = r.peek()

    section_header, type, name = _parse_section_header(r, line)
    if not type == 'flag':
        raise NextParser

    line = r.pop()
    for key in ['flags', 'flag_options']:
        if not key in store:
            store[key] = {}

    if store['flag_options'].has_key(name):
        raise ParseError("Flag %s already defined" % name)

    f_store = {}
    r.parse(open_brace)
    while r.wait_for('}'):
        r.parse((if_statement, key_value), f_store, opt_arg=flags)
    r.parse(close_brace)

    try:
        default = f_store['default']
    except KeyError:
        raise ParseError("Flag %s has not default value" % name)

    try:
        descr = f_store['description']
    except KeyError:
        descr = None

    # Override default with user customization if customized
    if name in flags["flags"]:
        value = flags["flags"][name]
    else:
        value = default

    store['flags'][name] = value
    store['flag_options'][name] = FlagOption(name, default, descr)

def eval_statement(expr, vars):
    # replace version numbers with strings, e.g. 2.6.1 -> '2.6.1'
    ver_descr = re.compile('[^\'\."0-9](\d+\.)+\d+')
    match = ver_descr.search(expr)
    while match:
        start, end = match.start(), match.end()
        expr = expr[:start + 1] + '"' + expr[start + 1:end] + '"' + \
               expr[end:]
        match = ver_descr.match(expr)

    # Parse, compile and execute the expression
    expr_ast = ast.parse(expr, mode='eval')
    code = compile(expr_ast, filename=expr, mode='eval')
    expr_constants.update(vars['flags'])
    return eval(code, expr_funcs, expr_constants)

def if_statement(r, store, flags={}):
    if not r.peek().startswith('if '):
        raise NextParser

    expr = r.pop().lstrip('if').strip()
    expr_true = eval_statement(expr, flags)

    # Parse the contents of the if-statement
    r.parse(open_brace)
    while r.wait_for('}'):
        if expr_true:
            use_store = store
        else:
            use_store = {}

        r.parse((if_statement, section, key_value), use_store)

    r.parse(close_brace)

    if r.peek() != 'else':
        return

    r.pop()
    r.parse(open_brace)
    # Parse the else part of the statement
    while r.wait_for('}'):
        if expr_true:
            use_store = store
        else:
            use_store = {}

        r.parse((if_statement, section, key_value), use_store)

    r.parse(close_brace)


# --- parsers end -------------------------------------------------------

def get_flags(store, user_flags={}):
    """Given the variables returned by the parser, return the
    flags found.  If `user_flags` are provided, these override those
    found during parsing.

    """
    ret = {}
    flags = store.get('flags', {})
    for name, flag in flags.items():
        ret[name] = flag
    ret.update(user_flags)
    return ret

def get_flag_options(store):
    return store.get('flag_options', {})

def get_paths(store, user_paths={}):
    """Given the variables returned by the parser, return the paths found. If
    `user_paths` are provided, these override those found during parsing.
    """
    path_options = store.get('path_options', {})
    for name, path in path_options.items():
        user_paths[name] = path.default_value
    return user_paths

def get_path_options(store):
    return store.get('path_options', {})

def parse(data, user_flags={}, user_paths={}):
    """Given lines from a config file, parse them.  `user_flags` may
    optionally be given to override any flags found in the config
    file.

    """
    pdata = strip_indents(data)
    r = Reader(pdata, data)

    info = {}

    while not r.eof():
        opt_arg = {'flags': get_flags(info, user_flags),
                   'flag_options': get_flag_options(info),
                   'path_options': get_path_options(info),
                   'paths': get_paths(info, user_paths)}
        r.parse([key_value, section, executable_parser, datafiles_parser,
                 path_parser, flag_parser], store=info, opt_arg=opt_arg)

    return info

if __name__ == "__main__":

    def print_dict(d, indent=0):
        for (key, value) in d.items():
            indent_str = indent * ' '
            if isinstance(value, dict):
                if key.strip():
                    print '%s%s:' % (indent_str, key)
                print_dict(value, indent=indent + indent_width)
            else:
                out = indent_str + '%s: %s' % (key, value)
                print out

    f = open(sys.argv[1], 'r')
    data = f.readlines()
    meta_data = parse(data, {'flag1': False}, {})

    print_dict(meta_data)