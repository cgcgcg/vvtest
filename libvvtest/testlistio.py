#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import stat
import shutil

from . import testspec
from .paramset import ParameterSet
from .testcase import TestCase

version = 34


class TestListWriter:

    def __init__(self, filename):
        ""
        self.filename = filename

    def start(self, **file_attrs):
        ""
        datestamp = repr( [ time.ctime(), time.time() ] )

        remove_attrs_with_None_for_a_value( file_attrs )

        with open( self.filename, 'w' ) as fp:
            fp.write( '#VVT: Version = '+str(version)+'\n' )
            fp.write( '#VVT: Start = '+datestamp+'\n' )
            fp.write( '#VVT: Attrs = '+repr( file_attrs )+'\n\n' )

    def addIncludeFile(self, include_filename):
        ""
        with open( self.filename, 'a' ) as fp:
            fp.write( '#VVT: Include = '+include_filename+'\n' )

    def includeFileCompleted(self, include_filename):
        ""
        with open( self.filename, 'a' ) as fp:
            fp.write( '#VVT: Completed = '+include_filename+'\n' )

    def append(self, tcase, extended=False):
        ""
        with open( self.filename, 'a' ) as fp:
            fp.write( test_to_string( tcase, extended ) + '\n' )

    def finish(self):
        ""
        datestamp = repr( [ time.ctime(), time.time() ] )

        with open( self.filename, 'a' ) as fp:
            fp.write( '\n#VVT: Finish = '+datestamp+'\n' )


class TestListReader:

    def __init__(self, filename):
        ""
        self.filename = filename

        self.vers = None
        self.start = None
        self.attrs = {}
        self.finish = None

        self.incl = set()
        self.tests = {}

    def read(self, testctor):
        ""
        for key,val in self._iterate_file_lines():
            try:
                if key == 'Version':
                    self.vers = int( val )
                elif key == 'Start':
                    self.start = eval( val )[1]
                elif key == 'Attrs':
                    self.attrs = eval( val )
                elif key == 'Include':
                    self.incl.add( val )
                elif key == 'Completed':
                    if val in self.incl:
                        self.incl.remove( val )
                elif key == 'Finish':
                    self.finish = eval( val )[1]
                else:
                    tcase = string_to_test( val, testctor )
                    self.tests[ tcase.getSpec().getID() ] = tcase

            except Exception:
                pass
                raise #magic

        assert self.vers in [32, 33, 34], \
            'corrupt test list file or older format: '+str(self.filename)

        for incl_file in self.incl:
            self._read_include_file( incl_file, testctor )

    def getFileVersion(self):
        ""
        return self.vers

    def getStartDate(self):
        ""
        return self.start

    def getFinishDate(self):
        ""
        return self.finish

    def getAttr(self, name, *default):
        ""
        if len(default) > 0:
            return self.attrs.get( name, default[0] )
        return self.attrs[name]

    def getAttrs(self):
        ""
        return dict( self.attrs.items() )

    def getTests(self):
        """
        Returns dictionary mapping (file name, execute dir) to TestCase object.
        """
        return self.tests

    def scanForFinishDate(self):
        """
        If the file has a finish date it is returned, otherwise None.
        """
        finish = None

        for key,val in self._iterate_file_lines():
            try:
                if key == 'Finish':
                    finish = eval( val )[1]
            except Exception:
                pass

        return finish

    def _iterate_file_lines(self):
        ""
        with open( self.filename, 'r' ) as fp:

            for line in fp:

                line = line.strip()

                try:
                    if line.startswith( '#VVT: ' ):
                        n,v = line[5:].split( '=', 1 )
                        yield ( n.strip(), v.strip() )

                    elif line:
                        yield ( None, line )

                except Exception:
                    pass

    def _read_include_file(self, fname, testctor):
        ""
        if not os.path.isabs( fname ):
            # include file is relative to self.filename
            fname = os.path.join( os.path.dirname( self.filename ), fname )

        if os.path.exists( fname ):

            tlr = TestListReader( fname )
            tlr.read( testctor )
            self.tests.update( tlr.getTests() )


def file_is_marked_finished( filename ):
    ""
    finished = False

    try:
        tlr = TestListReader( filename )
        if tlr.scanForFinishDate() != None:
            finished = True
    except Exception:
        pass

    return finished


def remove_attrs_with_None_for_a_value( attrdict ):
    ""
    for k,v in list( attrdict.items() ):
        if v == None:
            attrdict.pop( k )


def test_to_string( tcase, extended=False ):
    """
    Returns a string with no newlines containing the file path, parameter
    names/values, and attribute names/values.
    """
    tspec = tcase.getSpec()
    tstat = tcase.getStat()

    assert tspec.getName() and tspec.getRootpath() and tspec.getFilepath()

    testdict = {}

    testdict['name'] = tspec.getName()
    testdict['root'] = tspec.getRootpath()
    testdict['path'] = tspec.getFilepath()
    testdict['keywords'] = tspec.getKeywords( include_implicit=False )

    if tspec.isAnalyze():
        testdict['paramset'] = tspec.getParameterSet().getParameters()
    else:
        testdict['params'] = tspec.getParameters()

    testdict['attrs'] = tstat.getAttrs()

    if extended:
        insert_extended_test_info( tcase, testdict )

    s = repr( testdict )

    return s


def string_to_test( strid, testctor ):
    """
    Creates and returns a partially filled TestSpec object from a string
    produced by the test_to_string() method.
    """
    testdict = eval( strid.strip() )

    name = testdict['name']
    root = testdict['root']
    path = testdict['path']

    tspec = testctor.makeTestSpec( name, root, path )

    if 'paramset' in testdict:
        pset = tspec.getParameterSet()
        for T,L in testdict['paramset'].items():
            pset.addParameterGroup( T, L )
        tspec.setIsAnalyze()
    else:
        tspec.setParameters( testdict['params'] )

    tspec.setKeywordList( testdict['keywords'] )

    tcase = TestCase( tspec )
    tstat = tcase.getStat()

    for k,v in testdict['attrs'].items():
        tstat.setAttr( k, v )

    check_load_extended_info( tcase, testdict )

    return tcase


def insert_extended_test_info( tcase, testdict ):
    ""
    if tcase.hasDependent():
        testdict['hasdependent'] = True

    depL = tcase.getDepDirectories()
    if len( depL ) > 0:
        testdict['depdirs'] = depL


def check_load_extended_info( tcase, testdict ):
    ""
    if testdict.get( 'hasdependent', False ):
        tcase.setHasDependent()

    depL = testdict.get( 'depdirs', None )
    if depL:
        for pat,xdir in depL:
            tcase.addDepDirectory( pat, xdir )
