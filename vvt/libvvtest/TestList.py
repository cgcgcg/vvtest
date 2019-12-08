#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
import glob

from .errors import TestSpecError
from .testcase import TestCase
from . import testlistio
from .groups import ParameterizeAnalyzeGroups
from .teststatus import copy_test_results


class TestList:
    """
    Stores a set of TestCase objects.  Has utilities to read/write to a text
    file and to read from a test specification file.
    """

    def __init__(self, filename,
                       runtime_config=None,
                       testcreator=None,
                       testfilter=None):
        ""
        if filename:
            self.filename = os.path.normpath( filename )
        else:
            # use case: scanning tests, but never reading or writing
            self.filename = None

        self.rundate = None
        self.results_file = None

        self.datestamp = None
        self.finish = None

        self.groups = None  # a ParameterizeAnalyzeGroups class instance

        self.xdirmap = {}  # TestSpec xdir -> TestCase object
        self.tcasemap = {}  # TestSpec ID -> TestCase object

        self.rtconfig = runtime_config
        self.creator = testcreator
        self.testfilter = testfilter

    def setResultsSuffix(self, suffix=None):
        ""
        if suffix:
            self.rundate = suffix
        elif not self.rundate:
            self.rundate = time.strftime( "%Y-%m-%d_%H:%M:%S" )

        return self.rundate

    def getResultsSuffix(self):
        ""
        return self.rundate

    def stringFileWrite(self, extended=False):
        """
        Writes all the tests in this container to the test list file.  If
        'extended' is True, additional information is written to make the
        file more self-contained.
        """
        assert self.filename

        check_make_directory_containing_file( self.filename )

        tlw = testlistio.TestListWriter( self.filename )

        if extended:
            tlw.start( rundate=self.rundate )
        else:
            tlw.start()

        for tcase in self.tcasemap.values():
            tlw.append( tcase, extended=extended )

        tlw.finish()

    def initializeResultsFile(self):
        ""
        self.setResultsSuffix()

        rfile = self.filename + '.' + self.rundate
        
        self.results_file = testlistio.TestListWriter( rfile )

        self.results_file.start()

        return rfile

    def addIncludeFile(self, testlist_path):
        """
        Appends the given filename to the test results file.
        """
        assert self.rundate, 'suffix must have already been set'
        inclf = testlist_path + '.' + self.rundate
        self.results_file.addIncludeFile( inclf )

    def appendTestResult(self, tcase):
        """
        Appends the results file with the name and attributes of the given
        TestCase object.
        """
        self.results_file.append( tcase )

    def writeFinished(self):
        """
        Appends the results file with a finish marker that contains the
        current date.
        """
        self.results_file.finish()

    def readTestList(self):
        ""
        assert self.filename

        if os.path.exists( self.filename ):

            tlr = testlistio.TestListReader( self.filename )
            tlr.read()

            self.rundate = tlr.getAttr( 'rundate', None )

            for xdir,tcase in tlr.getTests().items():
                if xdir not in self.tcasemap:
                    self.tcasemap[ xdir ] = tcase

    def readTestResults(self, resultsfilename=None, preserve_skips=False):
        """
        If 'resultsfilename' is not None, only read that one file.  Otherwise,
        glob for results filenames and read them all in time stamp increasing
        order.

        If 'preserve_skips' is False, each test read in from a results file
        will have its skip setting removed from the test.
        """
        if resultsfilename == None:
            self._read_file_list( self.getResultsFilenames(), preserve_skips )
        else:
            self._read_file_list( [ resultsfilename ], preserve_skips )

    def getResultsFilenames(self):
        ""
        assert self.filename
        fileL = glob.glob( self.filename+'.*' )
        fileL.sort()
        return fileL

    def _read_file_list(self, files, preserve_skips):
        ""
        for fn in files:

            tlr = testlistio.TestListReader( fn )
            tlr.read()

            self.datestamp = tlr.getStartDate()
            self.finish = tlr.getFinishDate()

            for xdir,tcase in tlr.getTests().items():

                t = self.tcasemap.get( xdir, None )
                if t != None:
                    copy_test_results( t, tcase )
                    if not preserve_skips:
                        t.getSpec().attrs.pop( 'skip', None )

    def ensureInlinedTestResultIncludes(self):
        ""
        fL = self.getResultsFilenames()
        if len(fL) > 0:
            # only the most recent is checked
            testlistio.inline_include_files( fL[-1] )

    def inlineIncludeFiles(self):
        ""
        rfile = self.filename + '.' + self.rundate
        testlistio.inline_include_files( rfile )

    def getDateStamp(self, default=None):
        """
        Return the start date from the last test results file read using the
        readTestResults() function.  If a read has not been done, the 'default'
        argument is returned.
        """
        if self.datestamp:
            return self.datestamp
        return default

    def getFinishDate(self, default=None):
        """
        Return the finish date from the last test results file read using the
        readTestResults() function.  If a read has not been done, or vvtest is
        still running, or vvtest got killed in the middle of running, the
        'default' argument is returned.
        """
        if self.finish:
            return self.finish
        return default

    def getTests(self):
        """
        Returns, in a list, all tests either scanned or read from a file.
        """
        return self.tcasemap.values()

    def getTestMap(self):
        """
        Returns a map of xdir to TestCase containing all tests.
        """
        return self.tcasemap

    def getGroupMap(self):
        ""
        return self.groups

    def applyPermanentFilters(self):
        ""
        self._check_create_parameterize_analyze_group_map()

        self.testfilter.applyPermanent( self.tcasemap )

        for analyze, tcaseL in self.groups.iterateGroups():
            self.testfilter.checkAnalyze( analyze, tcaseL )

        self.numactive = count_active( self.tcasemap )

    def determineActiveTests(self, filter_dir=None,
                                   baseline=False,
                                   apply_filters=True,
                                   remove_skips=False):
        """
        If 'remove_skips' is True then every test skipped by the current
        filtering is removed entirely from the test list.
        """
        self._check_create_parameterize_analyze_group_map()

        if apply_filters:
            self.testfilter.applyRuntime( self.tcasemap, filter_dir,
                                          force_checks=remove_skips )

            for analyze, tcaseL in self.groups.iterateGroups():
                self.testfilter.checkAnalyze( analyze, tcaseL )

            if remove_skips:
                self.testfilter.removeNewSkips( self.tcasemap )

        refresh_active_tests( self.tcasemap, self.creator )

        if baseline:
            # baseline marking must come after TestSpecs are refreshed
            self.testfilter.applyBaselineSkips( self.tcasemap )

        self.numactive = count_active( self.tcasemap )

    def numActive(self):
        """
        Return the total number of active tests (the tests to be run).
        """
        return self.numactive

    def getActiveTests(self, sorting=''):
        """
        Get a list of the active tests (after filtering).  If 'sorting' is
        not an empty string, it should be a set of characters that control the
        way the test sorting is performed.
                n : test name
                x : execution directory name (the default)
                t : test run time
                d : execution date
                s : test status (such as pass, fail, diff, etc)
                r : reverse the order
        """
        if not sorting:
            sorting = 'xd'

        tL = []

        for idx,tcase in enumerate( self.tcasemap.values() ):
            t = tcase.getSpec()
            if not tcase.getStat().skipTest():
                subL = []
                for c in sorting:
                    if c == 'n':
                        subL.append( t.getName() )
                    elif c == 'x':
                        subL.append( t.getDisplayString() )
                    elif c == 't':
                        tm = tcase.getStat().getRuntime( None )
                        if tm == None: tm = 0
                        subL.append( tm )
                    elif c == 'd':
                        subL.append( tcase.getStat().getStartDate( 0 ) )
                    elif c == 's':
                        subL.append( tcase.getStat().getResultStatus() )

                subL.extend( [ idx, tcase ] )
                tL.append( subL )
        tL.sort()
        if 'r' in sorting:
            tL.reverse()
        tL = [ L[-1] for L in tL ]

        return tL

    def encodeIntegerWarning(self):
        ""
        ival = 0
        for tcase in self.tcasemap.values():
            if not tcase.getStat().skipTest():
                result = tcase.getStat().getResultStatus()
                if   result == 'diff'   : ival |= ( 2**1 )
                elif result == 'fail'   : ival |= ( 2**2 )
                elif result == 'timeout': ival |= ( 2**3 )
                elif result == 'notdone': ival |= ( 2**4 )
                elif result == 'notrun' : ival |= ( 2**5 )
        return ival

    def readTestFile(self, basepath, relfile, force_params):
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
          print3( "*** skipping file " + os.path.join( basepath, relfile ) + \
                  ": " + str( sys.exc_info()[1] ) )
          testL = []

        for tspec in testL:
            if not self._is_duplicate_execute_directory( tspec ):
                testid = tspec.getID()
                tcase = TestCase( tspec )
                self.tcasemap[testid] = tcase
                self.xdirmap[ tspec.getExecuteDirectory() ] = tcase

    def addTest(self, tcase):
        """
        Add/overwrite a test in the list.
        """
        self.tcasemap[ tcase.getSpec().getID() ] = tcase

    def _check_create_parameterize_analyze_group_map(self):
        ""
        if self.groups == None:
            self.groups = ParameterizeAnalyzeGroups()
            self.groups.rebuild( self.tcasemap )

    def _is_duplicate_execute_directory(self, tspec):
        ""
        xdir = tspec.getExecuteDirectory()

        tcase0 = self.xdirmap.get( xdir, None )

        if tcase0 != None and \
           not tests_are_related_by_staging( tcase0.getSpec(), tspec ):

            tspec0 = tcase0.getSpec()

            print3( '*** warning:',
                'ignoring test with duplicate execution directory\n',
                '      first   :', tspec0.getFilename() + '\n',
                '      second  :', tspec.getFilename() + '\n',
                '      exec dir:', xdir )

            ddir = tspec.getDisplayString()
            if ddir != xdir:
                print3( '       test id :', ddir )

            return True

        return False


def tests_are_related_by_staging( tspec1, tspec2 ):
    ""
    xdir1 = tspec1.getExecuteDirectory()
    disp1 = tspec1.getDisplayString()

    xdir2 = tspec2.getExecuteDirectory()
    disp2 = tspec2.getDisplayString()

    if xdir1 == xdir2 and \
       tspec1.getFilename() == tspec2.getFilename() and \
       xdir1 != disp1 and disp1.startswith( xdir1 ) and \
       xdir2 != disp2 and disp2.startswith( xdir2 ):
        return True

    return False


def check_make_directory_containing_file( filename ):
    ""
    d,b = os.path.split( filename )
    if d and d != '.':
        if not os.path.exists(d):
            os.mkdir( d )


def count_active( tcase_map ):
    ""
    cnt = 0
    for tcase in tcase_map.values():
        if not tcase.getStat().skipTest():
            cnt += 1
    return cnt


def refresh_active_tests( tcase_map, creator ):
    ""
    for xdir,tcase in tcase_map.items():
        tspec = tcase.getSpec()
        if not tcase.getStat().skipTest():
            if not tspec.constructionCompleted():
                creator.reparse( tspec )


###########################################################################

def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
