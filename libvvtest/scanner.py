#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from .errors import FatalError, TestSpecError
from .testcase import TestCase
from .staging import tests_are_related_by_staging


class TestFileScanner:

    def __init__(self, creator, path_list=[],
                       force_params_dict=None,
                       spectype=None,
                       warning_output_stream=sys.stdout):
        """
        If 'force_params_dict' is not None, it must be a dictionary mapping
        parameter names to a list of parameter values.  Any test that contains
        a parameter in this dictionary will take on the given values for that
        parameter.

        If 'spectype' is not None, it must be 'vvt' or 'xml'.  The scanner will
        only pick up files for those test specification types.  Default is
        both *.xml and *.vvt.
        """
        self.creator = creator
        self.path_list = path_list
        self.params = force_params_dict
        self.warnout = warning_output_stream

        self.extensions = make_test_extension_list( spectype )

        self.xdirmap = {}  # TestSpec xdir -> TestCase object

    def scanPaths(self, testlist):
        ""
        for d in self.path_list:
            if not os.path.exists(d):
                raise FatalError( 'scan path does not exist: ' + str(d) )

            self.scanPath( testlist, d )

    def scanPath(self, testlist, path):
        """
        Recursively scans for test XML or VVT files starting at 'path'.
        """
        bpath = os.path.normpath( os.path.abspath(path) )

        if os.path.isfile( bpath ):
            basedir,fname = os.path.split( bpath )
            self.readTestFile( testlist, basedir, fname, self.params )

        else:
            for root,dirs,files in os.walk( bpath ):
                self._scan_recurse( testlist, bpath, root, dirs, files )

    def completeTestParsing(self, testlist):
        ""
        for tcase in testlist.getActiveTests():
            tspec = tcase.getSpec()
            if not tspec.constructionCompleted():
                self.creator.reparse( tspec )

    def _scan_recurse(self, testlist, basedir, d, dirs, files):
        """
        This function is given to os.walk to recursively scan a directory
        tree for test XML files.  The 'basedir' is the directory originally
        sent to the os.walk function.
        """
        d = os.path.normpath(d)

        if basedir == d:
            reldir = '.'
        else:
            assert basedir+os.sep == d[:len(basedir)+1]
            reldir = d[len(basedir)+1:]

        # scan files with extension "xml" or "vvt"; soft links to directories
        # are skipped by os.walk so special handling is performed

        for f in files:
            bn,ext = os.path.splitext(f)
            if bn and ext in self.extensions:
                fname = os.path.join(reldir,f)
                self.readTestFile( testlist, basedir, fname, self.params )

        linkdirs = []
        for subd in list(dirs):
            rd = os.path.join( d, subd )
            if not os.path.exists(rd) or \
                    subd.startswith("TestResults.") or \
                    subd.startswith("Build_"):
                dirs.remove( subd )
            elif os.path.islink(rd):
                linkdirs.append( rd )

        # TODO: should check that the soft linked directories do not
        #       point to a parent directory of any of the directories
        #       visited thus far (to avoid an infinite scan loop)
        #       - would have to use os.path.realpath() or something because
        #         the actual path may be the softlinked path rather than the
        #         path obtained by following '..' all the way to root

        # manually recurse into soft linked directories
        for ld in linkdirs:
            for lroot,ldirs,lfiles in os.walk( ld ):
                self._scan_recurse( testlist, basedir, lroot, ldirs, lfiles )

    def readTestFile(self, testlist, basepath, relfile, force_params):
        """
        Initiates the parsing of a test file.  XML test descriptions may be
        skipped if they don't appear to be a test file.  Attributes from
        existing tests will be absorbed.
        """
        assert basepath
        assert relfile
        assert os.path.isabs( basepath )
        assert not os.path.isabs( relfile )

        basepath = os.path.normpath( basepath )
        relfile  = os.path.normpath( relfile )

        assert relfile

        try:
            testL = self.creator.fromFile( basepath, relfile, force_params )
        except TestSpecError:
            print_warning( self.warnout,
                           "skipping file", os.path.join( basepath, relfile ),
                           "because", str( sys.exc_info()[1] ) )
            testL = []

        for tspec in testL:
            if not self._is_duplicate_execute_directory( tspec ):
                tcase = TestCase( tspec )
                if tspec.hasKeyword( 'TDD' ):
                    tcase.getStat().setAttr( 'TDD', True )
                testlist.addTest( tcase )
                self.xdirmap[ tspec.getExecuteDirectory() ] = tcase

    def _is_duplicate_execute_directory(self, tspec):
        ""
        xdir = tspec.getExecuteDirectory()

        tcase0 = self.xdirmap.get( xdir, None )

        if tcase0 != None and \
           not tests_are_related_by_staging( tcase0.getSpec(), tspec ):

            tspec0 = tcase0.getSpec()

            warn = [ 'ignoring test with duplicate execution directory',
                     '      first   : ' + tspec0.getFilename(),
                     '      second  : ' + tspec.getFilename(),
                     '      exec dir: ' + xdir,
                     '      stringid: ' + tspec.getDisplayString() ]

            ddir = tspec.getDisplayString()
            if ddir != xdir:
                warn.append( '       test id : ' + ddir )

            print_warning( self.warnout, '\n'.join( warn ) )

            return True

        return False


def make_test_extension_list( spectype ):
    ""
    if spectype == 'vvt':
        return ['.vvt']
    elif spectype == 'xml':
        return ['.xml']
    else:
        return ['.xml','.vvt']


def print_warning( stream, *args ):
    ""
    stream.write( '*** warning: ' )
    stream.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    stream.flush()
