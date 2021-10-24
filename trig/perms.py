#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import stat
import re
import tempfile


help_string = """
USAGE:
    perms.py [OPTIONS] [ path [ path ... ]

SYNOPSIS:
    Running this file as a program is deprecated. Use chperms instead.

    This script sets file and directory permissions and group.  Its main use
is as a python module for file & directory manipulation utilities.  The command
line interface is similar in functionality to the shell commands chmod and
chgrp.

If a 'path' is not given, the current working directory is assumed.  Operations
are specified using the -p option, such as

        o=-     : set world permissions to none
        g=r-x   : set group to read, no write, execute
        g+rX    : add read to group, add execute to group if owner has execute
        o-w     : remove write to world
        u+rw    : add read & write to owner
        wg-name : set the group name on the file or directory

If the specification does not start with one of u=, g=, o=, u+, g+, o+, u-, g-,
or o-, then it is assumed to be a group name, and the group is set on the path.

OPTIONS:
    -h, --help : this help
    -p <spec>  : permission specification for files and directories
    -f <spec>  : permission specification for files
    -d <spec>  : permission specification for directories
    -R         : apply permissions recursively; DEPRECATED (now the default)

Note that the -p, -f, and -d arguments may be repeated.
"""


def main():

    from getopt import getopt
    optL,argL = getopt( sys.argv[1:], 'hp:f:d:R',
                        longopts=['help','prefix='] )
    optD ={}
    for n,v in optL:
        if n in ['-p','-f','-d']:
            optD[n] = optD.get( n, [] ) + [v]
        else:
            optD[n] = v

    if '-h' in optD or '--help' in optD:
        print3( help_string )
        return

    pspecs = optD.get( '-p', [] )
    fspecs = optD.get( '-f', [] )
    dspecs = optD.get( '-d', [] )

    if len(pspecs) + len(fspecs) + len(dspecs) > 0:

        if len(argL) == 0:
            argL = ['.']

        for path in argL:
            apply_itemized_chmod( path,
                                  pspecs+fspecs,
                                  pspecs+dspecs,
                                  recurse=True )


####################################################################

class PermissionSpecificationError( Exception ):
    pass


def filemode( path ):
    """
    Returns the integer containing the file mode permissions for the
    given pathname.
    """
    return stat.S_IMODE( os.stat(path)[stat.ST_MODE] )


def permission( path_or_fmode, which ):
    """
    Answers a permissions question about the given file name (a string) or
    a file mode (an integer).

    Values for 'which':

        read    : True if the file has read permission; 'path' must be a string
        write   : True if the file has write permission; 'path' a string
        execute : True if the file has execute permission; 'path' a string

        setuid  : True if the file is marked set-uid

        owner <mode> : True if the file satisfies the given mode for owner
        group <mode> : True if the file satisfies the given mode for group
        world <mode> : True if the file satisfies the given mode for world

    where <mode> specifies the file mode, such as rx, rwx, r-x, r, w, x, s.
    If a minus sign is in the <mode> then an exact match of the file mode
    must be true for this function to return True.
    """
    if which == 'read':
        if type(path_or_fmode) != type(''):
            raise PermissionSpecificationError(
                    'arg1 must be a filename when \'which\' == "read"' )
        return os.access( path_or_fmode, os.R_OK )
    
    elif which == 'write':
        if type(path_or_fmode) != type(''):
            raise PermissionSpecificationError(
                    'arg1 must be a filename when \'which\' == "write"' )
        return os.access( path_or_fmode, os.W_OK )
    
    elif which == 'execute':
        if type(path_or_fmode) != type(''):
            raise PermissionSpecificationError(
                    'arg1 must be a filename when \'which\' == "execute"' )
        return os.access( path_or_fmode, os.X_OK )

    else:
        
        if type(path_or_fmode) == type(2):
            fmode = path_or_fmode
        else:
            fmode = filemode( path_or_fmode )

        if which == 'setuid':
            if fmode & stat.S_ISUID: return True
            return False

        elif which == 'setgid':
            if fmode & stat.S_ISGID: return True
            return False

        elif which.startswith( 'owner ' ):
            s = which.split()[1]
            if '-' in s:
                return (fmode & owner_mask) == owner_bits[s]
            return (fmode & owner_bits[s]) == owner_bits[s]

        elif which.startswith( 'group ' ):
            s = which.split()[1]
            if '-' in s:
                return (fmode & group_mask) == group_bits[s]
            return (fmode & group_bits[s]) == group_bits[s]

        elif which.startswith( 'world ' ):
            s = which.split()[1]
            if '-' in s:
                return (fmode & world_mask) == world_bits[s]
            return (fmode & world_bits[s]) == world_bits[s]

        raise PermissionSpecificationError( "unknown 'which' value: "+str(which) )


def change_filemode( fmode, spec, *more_specs ):
    """
    Modifies the given file mode according to one or more specifications.
    A specification is a string with format

        {u|g|o}{=|+|-}{one two or three letter sequence}

    where

        the first character: u=user/owner, g=group, o=other/world
        the second character: '=' means set, '+' means add, '-' means remove
        the permission characters: r=read, w=write, x=execute, s=sticky

    For example, "u+x" means add user execute permission, and "g=rx" means
    set the group permissions to exactly read, no write, execute.
    """
    for s in (spec,)+more_specs:
        if len(s) < 2:
            raise PermissionSpecificationError( 'invalid specification: '+s )
        who = s[0]
        if who not in 'ugo':
            raise PermissionSpecificationError( 'invalid specification: '+s )
        op = s[1]
        if op not in '=+-':
            raise PermissionSpecificationError( 'invalid specification: '+s )
        if len(s) == 2:
            what = '-'
        else:
            what = s[2:]
        if who == 'u':
            mask = owner_mask
            if what not in owner_bits:
                raise PermissionSpecificationError( 'invalid specification: '+s )
            bits = owner_bits[what]
        elif who == 'g':
            if 'X' in what:
                what = replace_conditional_execute( what, fmode )
            mask = group_mask
            if what not in group_bits:
                raise PermissionSpecificationError( 'invalid specification: '+s )
            bits = group_bits[what]
        else:
            if 'X' in what:
                what = replace_conditional_execute( what, fmode )
            mask = world_mask
            if what not in world_bits:
                raise PermissionSpecificationError( 'invalid specification: '+s )
            bits = world_bits[what]

        if op == '=':   fmode = ( fmode & (~mask) ) | bits
        elif op == '+': fmode = fmode | bits
        else:           fmode = fmode & ( ~(bits) )

    return fmode


def replace_conditional_execute( what, fmode ):
    ""
    if permission( fmode, 'owner x' ):
        what = what.replace( 'X', 'x' )
    elif '-' in what:
        what = what.replace( 'X', '-' )
    else:
        what = what.replace( 'X', '' )

    return what


def fileowner( path ):
    """
    Returns the user name of the owner of the given pathname.  If the user
    id of the file is not in the password database (and so a user name
    cannot associated with the user id), then None is returned.
    """
    uid = os.stat( path ).st_uid
    try:
        import pwd
        ent = pwd.getpwuid( uid )
    except Exception:
        return None
    return ent[0]


def filegroup( path ):
    """
    Returns the group name of the given pathname.  If the group id of
    the file is not in the group database (and so a group name cannot
    associated with the group id), then None is returned.
    """
    gid = os.stat( path ).st_gid
    try:
        import grp
        ent = grp.getgrgid( gid )
    except Exception:
        return None
    return ent[0]


def change_group( path, group_id ):
    """
    Changes the group of 'path' to the given group id (an integer), or
    'group_id' can be the group name as a string.
    """
    if type(group_id) == type(''):
        import grp
        group_id = grp.getgrnam( group_id ).gr_gid
    uid = os.stat( path ).st_uid
    os.chown( path, uid, group_id )


def i_own( path ):
    """
    Returns True if the current user owns the given pathname.
    """
    fuid = os.stat( path ).st_uid
    uid = os.getuid()
    return uid == fuid


def my_user_name():
    """
    Returns the name of the user running this process.
    """
    uid = os.getuid()
    try:
        usr = pwd.getpwuid( uid )[0]
    except Exception:
        import getpass
        usr = getpass.getuser()
    return usr


def can_map_group_name_to_group_id( group_name ):
    ""
    try:
        import grp
        gid = grp.getgrnam( group_name )
    except KeyError:
        return False

    return True


def apply_chmod( path, *spec ):
    """
    Change the group and/or the file mode permissions of the given file 'path'.
    The 'spec' argument(s) must be one or more string specifications.  If a
    specification starts with a character from "ugo" then a letter from "=+-",
    then it is treated as a file mode.  Otherwise it is treated as a group
    name.

    Examples of values for 'spec',

        u+x : file mode setting to add execute for owner
        g=rX : set read for group and execute if execute for owner
        wg-alegra : change file group to "wg-alegra"
    """
    if spec:

        mL = []
        for s in spec:
            if len(s)>=2 and s[0] in 'ugo' and s[1] in '=+-':
                mL.append(s)
            else:
                change_group( path, s )

        if len(mL) > 0:
            os.chmod( path, change_filemode( filemode( path ), *mL ) )


def chmod_recurse( path, filespecs=[], dirspecs=[], setgroup=None ):
    ""
    apply_itemized_chmod( path, filespecs, dirspecs, setgroup, recurse=True )


def apply_itemized_chmod( path, filespecs=[], dirspecs=[],
                          setgroup=None, recurse=True ):
    """
    Applies 'filespecs' to files and 'dirspecs' to directories.  Each spec
    is the same as for change_filemode(), such as

        u+x   : add execute for owner
        g-w   : remove write for group
        o=--- : set other to no read, no write, no execute

    If 'recurse' is true, then recurses into directories.  Sets the file group
    if 'setgroup' is given.  Ignores soft links.
    """
    if os.path.islink( path ):
        pass

    elif os.path.isdir( path ):
        if setgroup:
            change_group( path, setgroup )
        if dirspecs:
            apply_chmod( path, *dirspecs )

        if recurse:
            for f in os.listdir( path ):
                fp = os.path.join( path, f )
                apply_itemized_chmod( fp, filespecs, dirspecs, setgroup, recurse )

    else:
        if filespecs:
            apply_chmod( path, *filespecs )
        if setgroup:
            change_group( path, setgroup )


##############################################################################

"""
This section defines a mapping from permission strings to file mode bit masks
for owner, group, and world.  For example, an owner "rx" is mapped to the
integer stat.S_IRUSR|stat.S_IXUSR.
"""

owner_mask = (stat.S_ISUID|stat.S_IRWXU)
owner_bits = {
        'r' : stat.S_IRUSR,
        'w' : stat.S_IWUSR,
        'x' : stat.S_IXUSR,
        's' : stat.S_IXUSR|stat.S_ISUID,
        'rw' : stat.S_IRUSR|stat.S_IWUSR,
        'rx' : stat.S_IRUSR|stat.S_IXUSR,
        'rs' : stat.S_IRUSR|stat.S_IXUSR|stat.S_ISUID,
        'wx' : stat.S_IWUSR|stat.S_IXUSR,
        'ws' : stat.S_IWUSR|stat.S_IXUSR|stat.S_ISUID,
        'rwx' : stat.S_IRWXU,
        'rws' : stat.S_IRWXU|stat.S_ISUID,
    }
owner_bits['-'] = 0
owner_bits['---'] = 0
owner_bits['r--'] = owner_bits['r']
owner_bits['-w-'] = owner_bits['w']
owner_bits['--x'] = owner_bits['x']
owner_bits['--s'] = owner_bits['s']
owner_bits['rw-'] = owner_bits['rw']
owner_bits['r-x'] = owner_bits['rx']
owner_bits['r-s'] = owner_bits['rs']
owner_bits['-wx'] = owner_bits['wx']
owner_bits['-ws'] = owner_bits['ws']

group_mask = (stat.S_ISGID|stat.S_IRWXG)
group_bits = {
        'r' : stat.S_IRGRP,
        'w' : stat.S_IWGRP,
        'x' : stat.S_IXGRP,
        's' : stat.S_IXGRP|stat.S_ISGID,
        'rw' : stat.S_IRGRP|stat.S_IWGRP,
        'rx' : stat.S_IRGRP|stat.S_IXGRP,
        'rs' : stat.S_IRGRP|stat.S_IXGRP|stat.S_ISGID,
        'wx' : stat.S_IWGRP|stat.S_IXGRP,
        'ws' : stat.S_IWGRP|stat.S_IXGRP|stat.S_ISGID,
        'rwx' : stat.S_IRWXG,
        'rws' : stat.S_IRWXG|stat.S_ISGID,
    }
group_bits['-'] = 0
group_bits['---'] = 0
group_bits['r--'] = group_bits['r']
group_bits['-w-'] = group_bits['w']
group_bits['--x'] = group_bits['x']
group_bits['--s'] = group_bits['s']
group_bits['rw-'] = group_bits['rw']
group_bits['r-x'] = group_bits['rx']
group_bits['r-s'] = group_bits['rs']
group_bits['-wx'] = group_bits['wx']
group_bits['-ws'] = group_bits['ws']


world_mask = stat.S_IRWXO
world_bits = {
        'r' : stat.S_IROTH,
        'w' : stat.S_IWOTH,
        'x' : stat.S_IXOTH,
        'rw' : stat.S_IROTH|stat.S_IWOTH,
        'rx' : stat.S_IROTH|stat.S_IXOTH,
        'wx' : stat.S_IWOTH|stat.S_IXOTH,
        'rwx' : stat.S_IRWXO,
    }
world_bits['-'] = 0
world_bits['---'] = 0
world_bits['r--'] = world_bits['r']
world_bits['-w-'] = world_bits['w']
world_bits['--x'] = world_bits['x']
world_bits['rw-'] = world_bits['rw']
world_bits['r-x'] = world_bits['rx']
world_bits['-wx'] = world_bits['wx']


def get_user_name( path=None ):
    """
    Returns the owner of the given pathname, or the owner of the current
    process if 'path' is not given. If the numeric user id cannot be mapped
    to a user name, the numeric id is returned as a string.
    """
    if path is None:
        return my_user_name()

    uid = os.stat( path ).st_uid

    try:
        import pwd
        name = pwd.getpwuid( uid )[0]
    except Exception:
        name = str(uid)

    return name


def apply( path, *stringspecs, **kwargs ):
    """
    Parse and apply group and/or file mode specifications to a path. The
    only known keyword argument is 'recurse' which defaults to False.
    Examples:

        apply( 'some/path', '+rX', recurse=True )
        apply( 'some/path', 'some-group-name', 'g=rX', 'o=' )

    The syntax and behavior closely matches UNIX chmod, except that a group
    name or numerial ID can be given. Also, 'g+S' will only apply setgid on
    directories.
    """
    recurse = kwargs.pop( 'recurse', False )
    if len( kwargs ) > 0:
        raise PermissionSpecificationError(
                            'unknown keyword arguments: '+repr(kwargs) )

    specs = PermissionSpecifications( *stringspecs )
    specs.apply( path, recurse=recurse )


class PermissionSpecifications:

    def __init__(self, *stringspecs):
        ""
        self.specs = []
        for sspec in split_specs_by_commas( stringspecs ):
            self.specs.append( parse_string_spec(sspec) )

    def apply(self, path, recurse=False):
        ""
        if not os.path.islink( path ):

            for spec in self.specs:
                spec.apply( path )

            if recurse and os.path.isdir( path ):
                for fn in os.listdir( path ):
                    fp = os.path.join( path, fn )
                    self.apply( fp, recurse )


def split_specs_by_commas( stringspecs ):
    ""
    sL = []

    for sspec in stringspecs:
        for s in sspec.split(','):
            s = s.strip()
            if s:
                sL.append(s)

    return sL


class PermSpec:

    def __init__(self):
        ""
        self.bitsoff = 0
        self.bitson = 0
        self.xbits = 0
        self.dbits = 0

    def apply(self, path):
        ""
        md = os.stat(path)[stat.ST_MODE]

        isdir = stat.S_ISDIR( md )
        fm = stat.S_IMODE( md )
        xval = (fm & (stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH) )

        fm &= ( ~(self.bitsoff) )
        fm |= self.bitson
        if xval != 0 or isdir:
            fm |= self.xbits
        if isdir:
            fm |= self.dbits

        os.chmod( path, fm )


class GroupSpec:

    def __init__(self, groupid):
        ""
        self.groupid = groupid

    def apply(self, path):
        ""
        uid = os.stat( path ).st_uid
        os.chown( path, uid, self.groupid )


mask_off = { 'u':stat.S_IRWXU,
             'g':stat.S_IRWXG,
             'o':stat.S_IRWXO }

bit_map = {
    'u': {
        'r':stat.S_IRUSR,
        'w':stat.S_IWUSR,
        'x':stat.S_IXUSR,
        's':stat.S_ISUID,
        't':0,
    },
    'g': {
        'r':stat.S_IRGRP,
        'w':stat.S_IWGRP,
        'x':stat.S_IXGRP,
        's':stat.S_ISGID,
        't':0,
    },
    'o': {
        'r':stat.S_IROTH,
        'w':stat.S_IWOTH,
        'x':stat.S_IXOTH,
        's':0,
        't':stat.S_ISVTX,
    }
}

def parse_string_spec( strspec ):
    ""
    who = ''
    op = ''
    what = ''

    N = len(strspec)
    i = 0
    while i < N:
        c = strspec[i]
        if c in '=+-':
            op = c
            what = strspec[i+1:]
            break
        elif c == 'a':
            who += 'ugo'
        elif c in 'ugo':
            who += c
        else:
            break
        i += 1

    if op and check_bit_letters(what):
        spec = create_change_mode_spec( who, op, what )
    else:
        spec = parse_group_string_spec( strspec )

    return spec


def create_change_mode_spec( who, op, what ):
    ""
    spec = PermSpec()

    if who:
        umask = 0
    else:
        umask = get_umask()
        who = 'ugo'

    for w in who:

        if op == '=':
            spec.bitsoff |= mask_off[w]

        for v in what:
            if op == '-':
                if v == 'X':
                    spec.bitsoff |= bit_map[w]['x']
                else:
                    spec.bitsoff |= bit_map[w][v]
            else:
                if v == 'X':
                    spec.xbits |= bit_map[w]['x']
                elif v == 'S':
                    spec.dbits |= bit_map[w]['s']
                else:
                    spec.bitson |= bit_map[w][v]

    spec.bitson &= ( ~umask )
    spec.xbits &= ( ~umask )

    return spec


def parse_group_string_spec( strspec ):
    ""
    try:
        gid = int( strspec )
    except Exception:
        try:
            import grp
            gid = grp.getgrnam( strspec ).gr_gid
        except Exception:
            raise PermissionSpecificationError(
                    'Invalid specification or group name: "'+strspec+'"' )

    spec = GroupSpec( gid )

    # check that a path can be changed to the given group
    tmpd = tempfile.mkdtemp()
    try:
        try:
            spec.apply( tmpd )
        except Exception:
            raise PermissionSpecificationError(
                    'Invalid specification or group name: "'+strspec+'"' )
    finally:
        os.rmdir( tmpd )

    return spec


def check_bit_letters( what ):
    ""
    for c in what:
        if c not in 'rwxXsSt':
            return False

    return True


def get_umask():
    ""
    msk = os.umask(0)
    os.umask( msk )
    return msk


######################################################################

def print3( *args ):
    ""
    sys.stdout.write( ' '.join( [ str(x) for x in args ] ) + os.linesep )
    sys.stdout.flush()


######################################################################

if __name__ == "__main__":
    main()
