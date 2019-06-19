#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import fnmatch


class TestDependency:

    def __init__(self, tcase, matchpat, wordexpr):
        ""
        self.tcase = tcase
        self.matchpat = matchpat
        self.wordexpr = wordexpr

    def getTestCase(self):
        ""
        return self.tcase

    def hasTestExec(self):
        ""
        return self.tcase.getExec() != None

    def hasSameExecuteDirectory(self, testdep):
        ""
        xdir1 = self.tcase.getSpec().getExecuteDirectory()
        xdir2 = testdep.tcase.getSpec().getExecuteDirectory()

        return xdir1 == xdir2

    def satisfiesResult(self, result):
        ""
        if self.wordexpr == None:
            if result not in ['pass','diff']:
                return False

        elif not self.wordexpr.evaluate( lambda word: word == result ):
            return False

        return True

    def getMatchDirectory(self):
        ""
        return self.matchpat, self.tcase.getSpec().getExecuteDirectory()

    def isBlocking(self):
        ""
        tcase = self.getTestCase()
        tstat = tcase.getStat()

        if tstat.isDone() or tstat.skipTest():
            result = tstat.getResultStatus()
            if not self.satisfiesResult( result ):
                return True

        elif tstat.isNotDone():
            return True

        else:
            assert tstat.isNotrun()

            if tcase.willNeverRun():
                result = tstat.getResultStatus()
                if not self.satisfiesResult( result ):
                    return True
            else:
                return True

        return False

    def willNeverRun(self):
        ""
        tcase = self.getTestCase()
        tstat = tcase.getStat()

        if tstat.isDone() or tstat.skipTest():
            result = tstat.getResultStatus()
            if not self.satisfiesResult( result ):
                return True

        elif tstat.isNotrun():
            if tcase.willNeverRun():
                result = tstat.getResultStatus()
                if not self.satisfiesResult( result ):
                    return True

        return False


def connect_dependency( from_tcase, to_tcase, pattrn=None, expr=None ):
    ""
    assert from_tcase.getExec() != None

    from_tcase.addDependency( to_tcase, pattrn, expr )

    if to_tcase.getExec() != None:
        to_tcase.setHasDependent()


def find_tests_by_execute_directory_match( xdir, pattern, xdir2tcase ):
    """
    Given 'xdir' dependent execute directory, the shell glob 'pattern' is
    matched against the execute directories in the 'xdir2tcase', in this order:

        1. basename(xdir)/pat
        2. basename(xdir)/*/pat
        3. pat
        4. *pat

    The first of these that matches at least one test will be returned.

    A python set of xdir is returned.
    """
    tbase = os.path.dirname( xdir )
    if tbase == '.':
        tbase = ''
    elif tbase:
        tbase += '/'

    L1 = [] ; L2 = [] ; L3 = [] ; L4 = []

    for xdir in xdir2tcase.keys():

        p1 = os.path.normpath( tbase+pattern )
        if fnmatch.fnmatch( xdir, p1 ):
            L1.append( xdir )

        if fnmatch.fnmatch( xdir, tbase+'*/'+pattern ):
            L2.append( xdir )

        if fnmatch.fnmatch( xdir, pattern ):
            L3.append( xdir )

        if fnmatch.fnmatch( xdir, '*'+pattern ):
            L4.append( xdir )

    for L in [ L1, L2, L3, L4 ]:
        if len(L) > 0:
            return set(L)

    return set()


def connect_analyze_dependencies( analyze, tcaseL, xdir2testexec ):
    ""
    for tcase in tcaseL:
        tspec = tcase.getSpec()
        if not tspec.isAnalyze():
            connect_dependency( analyze, tcase )
            gxt = xdir2testexec.get( tspec.getExecuteDirectory(), None )
            if gxt != None:
                gxt.setHasDependent()


def check_connect_dependencies( tcase, xdir2tcase, xdir2testexec ):
    ""
    tspec = tcase.getSpec()

    for dep_pat,expr in tspec.getDependencies():
        xdir = tspec.getExecuteDirectory()
        depL = find_tests_by_execute_directory_match(
                                        xdir, dep_pat, xdir2tcase )
        for dep_xdir in depL:
            bakup = xdir2tcase.get( dep_xdir, None )
            dep_obj = xdir2testexec.get( dep_xdir, bakup )
            if dep_obj != None:
                connect_dependency( tcase, dep_obj, dep_pat, expr )
