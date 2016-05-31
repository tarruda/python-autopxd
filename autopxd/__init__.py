#!/usr/bin/env python

import os
import os.path
import subprocess
import sys

import click
from pycparser import c_parser, c_ast

BUILTIN_HEADERS_DIR = os.path.join(os.path.dirname(__file__), 'include')
# Types declared by pycparser fake headers that we should ignore
IGNORE_DECLARATIONS = set((
    'size_t', '__builtin_va_list', '__gnuc_va_list', '__int8_t', '__uint8_t',
    '__int16_t', '__uint16_t', '__int_least16_t', '__uint_least16_t',
    '__int32_t', '__uint32_t', '__int64_t', '__uint64_t', '__int_least32_t',
    '__uint_least32_t', '__s8', '__u8', '__s16', '__u16', '__s32', '__u32',
    '__s64', '__u64', '_LOCK_T', '_LOCK_RECURSIVE_T', '_off_t', '__dev_t',
    '__uid_t', '__gid_t', '_off64_t', '_fpos_t', '_ssize_t', 'wint_t',
    '_mbstate_t', '_flock_t', '_iconv_t', '__ULong', '__FILE', 'ptrdiff_t',
    'wchar_t', '__off_t', '__pid_t', '__loff_t', 'u_char', 'u_short', 'u_int',
    'u_long', 'ushort', 'uint', 'clock_t', 'time_t', 'daddr_t', 'caddr_t',
    'ino_t', 'off_t', 'dev_t', 'uid_t', 'gid_t', 'pid_t', 'key_t', 'ssize_t',
    'mode_t', 'nlink_t', 'fd_mask', '_types_fd_set', 'clockid_t', 'timer_t',
    'useconds_t', 'suseconds_t', 'FILE', 'fpos_t', 'cookie_read_function_t',
    'cookie_write_function_t', 'cookie_seek_function_t',
    'cookie_close_function_t', 'cookie_io_functions_t', 'div_t', 'ldiv_t',
    'lldiv_t', 'sigset_t', '__sigset_t', '_sig_func_ptr', 'sig_atomic_t',
    '__tzrule_type', '__tzinfo_type', 'mbstate_t', 'sem_t', 'pthread_t',
    'pthread_attr_t', 'pthread_mutex_t', 'pthread_mutexattr_t',
    'pthread_cond_t', 'pthread_condattr_t', 'pthread_key_t', 'pthread_once_t',
    'pthread_rwlock_t', 'pthread_rwlockattr_t', 'pthread_spinlock_t',
    'pthread_barrier_t', 'pthread_barrierattr_t', 'jmp_buf', 'rlim_t',
    'sa_family_t', 'sigjmp_buf', 'stack_t', 'siginfo_t', 'z_stream', 'int8_t',
    'uint8_t', 'int16_t', 'uint16_t', 'int32_t', 'uint32_t', 'int64_t',
    'uint64_t', 'int_least8_t', 'uint_least8_t', 'int_least16_t',
    'uint_least16_t', 'int_least32_t', 'uint_least32_t', 'int_least64_t',
    'uint_least64_t', 'int_fast8_t', 'uint_fast8_t', 'int_fast16_t',
    'uint_fast16_t', 'int_fast32_t', 'uint_fast32_t', 'int_fast64_t',
    'uint_fast64_t', 'intptr_t', 'uintptr_t', 'intmax_t', 'uintmax_t', 'bool',
    'va_list',
))


class PxdNode(object):
    indent = '    '

    def __str__(self):
        return '\n'.join(self.lines())


class IdentifierType(PxdNode):
    def __init__(self, name, type_name):
        self.name = name or ''
        self.type_name = type_name

    def lines(self):
        if self.name:
            return ['{0} {1}'.format(self.type_name, self.name)]
        else:
            return [self.type_name]


class Function(PxdNode):
    def __init__(self, return_type, name, args):
        self.return_type = return_type
        self.name = name
        self.args = args

    def argstr(self):
        l = []
        for arg in self.args:
            lines = arg.lines()
            assert len(lines) == 1
            l.append(lines[0])
        return ', '.join(l)

    def lines(self):
        return [
            '{0} {1}({2})'.format(self.return_type, self.name, self.argstr())
        ]


class Ptr(IdentifierType):
    def __init__(self, node):
        self.node = node

    @property
    def name(self):
        return self.node.name

    @property
    def type_name(self):
        return self.node.type_name + '*'

    def lines(self):
        if isinstance(self.node, Function):
            f = self.node
            args = f.argstr()
            return ['{0} (*{1})({2})'.format(f.return_type, f.name, args)]
        else:
            return super(Ptr, self).lines()


class Array(IdentifierType):
    def __init__(self, node):
        self.node = node

    @property
    def name(self):
        return self.node.name + '[1]'

    @property
    def type_name(self):
        return self.node.type_name


class Type(PxdNode):
    def __init__(self, node):
        self.node = node

    def lines(self):
        lines = self.node.lines()
        lines[0] = 'ctypedef ' + lines[0]
        return lines


class Block(PxdNode):
    def __init__(self, name, fields, kind):
        self.name = name
        self.fields = fields
        self.kind = kind

    def lines(self):
        rv = ['cdef {0} {1}:'.format(self.kind, self.name)]
        for field in self.fields:
            for line in field.lines():
                rv.append(self.indent + line)
        return rv


class Enum(PxdNode):
    def __init__(self, name, items):
        self.name = name
        self.items = items

    def lines(self):
        rv = []
        if self.name:
            rv.append('cdef enum {0}:'.format(self.name))
        else:
            rv.append('cdef enum:')
        for item in self.items:
            rv.append(self.indent + item)
        return rv


class AutoPxd(c_ast.NodeVisitor, PxdNode):
    def __init__(self, hdrname):
        self.hdrname = hdrname
        self.decl_stack = [[]]
        self.visit_stack = []

    def visit(self, node):
        self.visit_stack.append(node)
        rv = super(AutoPxd, self).visit(node)
        n = self.visit_stack.pop()
        assert n == node
        return rv

    def visit_IdentifierType(self, node):
        self.append(' '.join(node.names))

    def visit_Block(self, node, kind):
        name = node.name
        if not name:
            name = self.path_name(kind[0])
        if not node.decls:
            if self.child_of(c_ast.TypeDecl, -2):
                # not a definition, must be a reference
                self.append(name)
            return
        fields = self.collect(node)
        # add the struct/union definition to the top level
        self.decl_stack[0].append(Block(name, fields, kind))
        if self.child_of(c_ast.TypeDecl, -2):
            # inline struct/union, add a reference to whatever name it was
            # defined on the top level
            self.append(name)

    def visit_Enum(self, node):
        items = []
        for item in node.values.enumerators:
            items.append(item.name)
        name = node.name
        type_decl = self.child_of(c_ast.TypeDecl, -2)
        if not name and type_decl:
            name = self.path_name('e')
        # add the enum definition to the top level
        self.decl_stack[0].append(Enum(name, items))
        if type_decl:
            self.append(name)

    def visit_Struct(self, node):
        return self.visit_Block(node, 'struct')

    def visit_Union(self, node):
        return self.visit_Block(node, 'union')

    def visit_TypeDecl(self, node):
        decls = self.collect(node)
        if not decls:
            return
        assert len(decls) == 1
        if isinstance(decls[0], basestring):
            self.append(IdentifierType(node.declname, decls[0]))
        else:
            self.append(decls[0])

    def visit_Decl(self, node):
        decls = self.collect(node)
        if not decls:
            return
        assert len(decls) == 1
        if isinstance(decls[0], basestring):
            self.append(IdentifierType(node.name, decls[0]))
        else:
            self.append(decls[0])

    def visit_FuncDecl(self, node):
        decls = self.collect(node)
        return_type = decls[-1].type_name
        fname = decls[-1].name
        args = decls[:-1]
        if (len(args) == 1 and isinstance(args[0], IdentifierType) and
            args[0].type_name == 'void'):
            args = []
        if (self.child_of(c_ast.PtrDecl, -2) and not
            self.child_of(c_ast.Typedef, -3)):
            # declaring a variable or parameter
            name = self.path_name('ft'.format(fname))
            self.decl_stack[0].append(Type(Ptr(Function(return_type, name, args))))
            self.append(name)
        else:
            self.append(Function(return_type, fname, args))


    def visit_PtrDecl(self, node):
        decls = self.collect(node)
        assert len(decls) == 1
        if isinstance(decls[0], basestring):
            self.append(decls[0])
        else:
            self.append(Ptr(decls[0]))

    def visit_ArrayDecl(self, node):
        decls = self.collect(node)
        assert len(decls) == 1
        self.append(Array(decls[0]))

    def visit_Typedef(self, node):
        decls = self.collect(node)
        if len(decls) != 1:
            return
        self.decl_stack[0].append(Type(decls[0]))

    def collect(self, node):
        decls = []
        self.decl_stack.append(decls)
        name = self.generic_visit(node)
        assert self.decl_stack.pop() == decls
        return decls

    def path_name(self, tag):
        names = []
        for node in self.visit_stack[:-2]:
            if hasattr(node, 'declname') and node.declname:
                names.append(node.declname)
            elif hasattr(node, 'name') and node.name:
                names.append(node.name)
        return '_{0}_{1}'.format('_'.join(names), tag)

    def child_of(self, type, index=None):
        if index is None:
            for node in reversed(self.visit_stack):
                if isinstance(node, type):
                    return True
            return False
        else:
            return isinstance(self.visit_stack[index], type)

    def append(self, node):
        self.decl_stack[-1].append(node)

    def lines(self):
        rv = ['cdef extern from "{0}":'.format(self.hdrname), '']
        for decl in self.decl_stack[0]:
            for line in decl.lines():
                rv.append(self.indent + line)
            rv.append('')
        return rv


def preprocess(code, extra_cpp_args=[]):
    proc = subprocess.Popen([
        'cpp', '-nostdinc', '-D__attribute__(x)=', '-I', BUILTIN_HEADERS_DIR,
    ] + extra_cpp_args + ['-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    result = []
    result.append(proc.communicate(input=code)[0])
    while proc.poll() is None:
        result.append(proc.communicate()[0])
    if proc.returncode:
        raise Exception('Invoking C preprocessor failed')
    return ''.join(result)


def parse(code, extra_cpp_args=[]):
    preprocessed = preprocess(code, extra_cpp_args=extra_cpp_args)
    parser = c_parser.CParser()
    ast = parser.parse(preprocessed)
    decls = []
    for decl in ast.ext:
        if hasattr(decl, 'name') and decl.name not in IGNORE_DECLARATIONS:
            decls.append(decl)
    ast.ext = decls
    return ast


def translate(code, hdrname, extra_cpp_args=[]):
    extra_incdir = os.path.dirname(hdrname)
    p = AutoPxd(hdrname)
    p.visit(parse(code, extra_cpp_args=['-I', extra_incdir]))
    return str(p)


@click.command()
@click.argument('infile', type=click.File('rb'), default=sys.stdin)
@click.argument('outfile', type=click.File('wb'), default=sys.stdout)
def cli(infile, outfile):
    outfile.write(translate(infile.read(), infile.name))
