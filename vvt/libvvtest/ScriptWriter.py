#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import join as pjoin
from os.path import dirname, normpath


def writeScript( testcase, filename, lang, rtconfig, plat, test_dir ):
    """
    Writes a helper script for the test.  The script language is based on
    the 'lang' argument.
    """
    testobj = testcase.getSpec()
    tname = testobj.getName()

    troot = testobj.getRootpath()
    assert os.path.isabs( troot )
    trel = dirname( testobj.getFilepath() )
    srcdir = normpath( pjoin( troot, trel ) )
    
    configdir = rtconfig.getAttr('configdir')

    tdir = rtconfig.getAttr('vvtestdir')
    assert tdir
    vvtlib = pjoin( tdir, 'libvvtest' )

    trigdir = normpath( pjoin( tdir, '..', 'trig' ) )

    projdir = rtconfig.getAttr('exepath')
    if not projdir: projdir = ''

    onopts = rtconfig.getAttr('onopts')
    offopts = rtconfig.getAttr('offopts')

    platname = plat.getName()
    cplrname = plat.getCompiler()

    dep_list = testcase.getDepDirectories()

    w = LineWriter()

    if lang == 'py':

        w.add( 'import os, sys',
               '',
               'NAME = "'+tname+'"',
               'TESTID = "'+testobj.getDisplayString()+'"',
               'PLATFORM = "'+platname+'"',
               'COMPILER = "'+cplrname+'"',
               'VVTESTSRC = "'+tdir+'"',
               'TESTROOT = "'+test_dir+'"',
               'PROJECT = "'+projdir+'"',
               'OPTIONS = '+repr( onopts ),
               'OPTIONS_OFF = '+repr( offopts ),
               'SRCDIR = "'+srcdir+'"' )

        if configdir:
            w.add( 'CONFIGDIR = "'+configdir+'"' )
        else:
            w.add( 'CONFIGDIR = ""' )

        # order matters; configdir should be the first entry in sys.path
        w.add( '',
               'sys.path.insert( 0, "'+trigdir+'" )',
               'sys.path.insert( 0, "'+tdir+'" )',
               'sys.path.insert( 0, "'+tdir+'/config" )' )
        if configdir and configdir != tdir+'/config':
            w.add( 'sys.path.insert( 0, "'+configdir+'" )' )

        w.add( '',
               'diff_exit_status = 64',
               'opt_analyze = "--execute_analysis_sections" in sys.argv[1:] ' + \
                          'or "--execute-analysis-sections" in sys.argv[1:]' )

        platenv = plat.getEnvironment()
        w.add( '',
               '# platform settings',
               'PLATFORM_VARIABLES = '+repr(platenv),
               'def apply_platform_variables():',
               '    "sets the platform variables in os.environ"' )
        for k,v in platenv.items():
            w.add( '    os.environ["'+k+'"] = "'+v+'"' )

        w.add( '', '# parameters defined by the test' )
        paramD = testobj.getParameters( typed=True )
        w.add( 'PARAM_DICT = '+repr( paramD ) )
        for k,v in paramD.items():
            w.add( k+' = '+repr(v) )

        if testobj.isAnalyze():
            # the parameter names and values of the children tests
            w.add( '', '# parameters comprising the children' )
            psetD = testobj.getParameterSet().getParameters( typed=True )
            for n,L in psetD.items():
                if len(n) == 1:
                    L2 = [ T[0] for T in L ]
                    w.add( 'PARAM_'+n[0]+' = ' + repr(L2) )
                else:
                    n2 = '_'.join( n )
                    w.add( 'PARAM_'+n2+' = ' + repr(L) )

        L = [ pjoin( test_dir, T[1] ) for T in dep_list ]
        w.add( '', 'DEPDIRS = '+repr(L) )

        # generate a multi-valued map of the dependencies
        D = {}
        for T in dep_list:
            S = D.get( T[0], None )
            if S == None:
                S = set()
                D[ T[0] ] = S
            S.add( pjoin( test_dir, T[1] ) )
        for k,S in D.items():
            D[ k ] = list( S )
            D[ k ].sort()
        w.add( '', 'DEPDIRMAP = '+repr(D) )

        w.add( """
            # to avoid circular imports in python, the script_util.py
            # or the script_util_plugin.py must be imported by the
            # test manually; those scripts then import this script
            """ )

        ###################################################################
    
    elif lang in ['sh','bash']:

        w.add( """
            # save the command line arguments into variables
            NUMCMDLINE=0
            CMDLINE_VARS=
            for arg in "$@" ; do
              NUMCMDLINE=$((NUMCMDLINE+1))
              eval CMDLINE_${NUMCMDLINE}='$arg'
              CMDLINE_VARS="$CMDLINE_VARS CMDLINE_${NUMCMDLINE}"
            done

            # this function returns true if the given string was an
            # argument on the command line
            cmdline_option() {
                optname=$1
                for var in $CMDLINE_VARS ; do
                    eval val="\$$var"
                    [ "X$val" = "X$optname" ] && return 0
                done
                return 1
            }

            opt_analyze=0
            cmdline_option --execute_analysis_sections && opt_analyze=1
            cmdline_option --execute-analysis-sections && opt_analyze=1
            """ )

        w.add( '',
               'NAME="'+tname+'"',
               'TESTID="'+testobj.getDisplayString()+'"',
               'PLATFORM="'+platname+'"',
               'COMPILER="'+cplrname+'"',
               'VVTESTSRC="'+tdir+'"',
               'TESTROOT="'+test_dir+'"',
               'PROJECT="'+projdir+'"',
               'OPTIONS="'+' '.join( onopts )+'"',
               'OPTIONS_OFF="'+' '.join( offopts )+'"',
               'SRCDIR="'+srcdir+'"',
               'PYTHONEXE="'+sys.executable+'"' )

        if configdir:
            w.add( 'CONFIGDIR="'+configdir+'"' )
        else:
            w.add( 'CONFIGDIR=""' )

        w.add( '',
               'diff_exit_status=64' )

        platenv = plat.getEnvironment()
        w.add( '',
               '# platform settings',
               'PLATFORM_VARIABLES="'+' '.join( platenv.keys() )+'"' )
        for k,v in platenv.items():
            w.add( 'PLATVAR_'+k+'="'+v+'"' )
        w.add( 'apply_platform_variables() {',
               '    # sets the platform variables in the environment' )
        for k,v in platenv.items():
            w.add( '    export '+k+'="'+v+'"' )
        if len(platenv) == 0:
            w.add( '    :' )  # cannot have an empty function
        w.add( '}' )

        w.add( '', '# parameters defined by the test' )
        paramD = testobj.getParameters()
        s = ' '.join( [ n+'/'+v for n,v in paramD.items() ] )
        w.add( 'PARAM_DICT="'+s+'"' )
        for k,v in paramD.items():
            w.add( k+'="'+v+'"' )

        if testobj.isAnalyze():
            w.add( '', '# parameters comprising the children' )
            psetD = testobj.getParameterSet().getParameters()
            if len(psetD) > 0:
                # the parameter names and values of the children tests
                for n,L in psetD.items():
                    n2 = '_'.join( n )
                    L2 = [ '/'.join( v ) for v in L ]
                    w.add( 'PARAM_'+n2+'="' + ' '.join(L2) + '"' )

        L = [ pjoin( test_dir, T[1] ) for T in dep_list ]
        w.add( '', 'DEPDIRS="'+' '.join(L)+'"' )

        # for sh/bash, all variables go into a global namespace; therefore,
        # we can just source the utility scripts from here
        if configdir:
            w.add( """
                if [ -e $CONFIGDIR/script_util_plugin.sh ]
                then
                    source $CONFIGDIR/script_util_plugin.sh
                else
                    source $VVTESTSRC/config/script_util.sh
                fi
                """ )
        else:
            w.add( '',
                   'source $VVTESTSRC/config/script_util.sh )' )
    
    w.write( filename )


#########################################################################

class LineWriter:

    def __init__(self):
        self.lineL = []

    def add(self, *args):
        """
        """
        if len(args) > 0:
            indent = ''
            if type(args[0]) == type(2):
                n = args.pop(0)
                indent = '  '*n
            for line in args:
                if line.startswith('\n'):
                    for line in self._split( line ):
                        self.lineL.append( indent+line )
                else:
                    self.lineL.append( indent+line )

    def _split(self, s):
        """
        """
        off = None
        lineL = []
        for line in s.split( '\n' ):
            line = line.strip( '\r' )
            lineL.append( line )
            if off == None and line.strip():
                i = 0
                for c in line:
                    if c != ' ':
                        off = i
                        break
                    i += 1
        if off == None:
            return lineL
        return [ line[off:] for line in lineL ]

    def write(self, filename):
        """
        """
        fp = open( filename, 'w' )
        fp.write( '\n'.join( self.lineL ) + '\n' )
        fp.close()
