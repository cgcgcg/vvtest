#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from .TestExec import TestExec
from . import depend


class TestExecList:

    def __init__(self, usrplugin, tlist, runner):
        ""
        self.plugin = usrplugin
        self.tlist = tlist
        self.runner = runner

        self.xtlist = {}  # np -> list of TestCase objects
        self.started = {}  # TestSpec ID -> TestCase object
        self.stopped = {}  # TestSpec ID -> TestCase object

    def createTestExecs(self, perms):
        """
        Creates the set of TestExec objects from the active test list.
        """
        self._createTestExecList( perms )

        for tcase in self.getTestExecList():
            self.runner.initialize_for_execution( tcase )

    def _createTestExecList(self, perms):
        ""
        self.xtlist = {}

        for tcase in self.tlist.getTests():

            tspec = tcase.getSpec()

            if not tcase.getStat().skipTest():

                assert tspec.constructionCompleted()

                tcase.setExec( TestExec() )

                np = int( tspec.getParameters().get('np', 0) )
                if np in self.xtlist:
                    self.xtlist[np].append( tcase )
                else:
                    self.xtlist[np] = [ tcase ]

        # sort tests longest running first; 
        self.sortTestExecList()

        self._connect_execute_dependencies()

    def _connect_execute_dependencies(self):
        ""
        tmap = self.tlist.getTestMap()
        groups = self.tlist.getGroupMap()

        for tcase in self.getTestExecList():

            tspec = tcase.getSpec()

            if tspec.isAnalyze():
                grpL = groups.getGroup( tcase )
                depend.connect_analyze_dependencies( tcase, grpL, tmap )

            depend.check_connect_dependencies( tcase, tmap )

    def sortTestExecList(self):
        """
        Sort the TestExec objects by runtime, descending order.  This is so
        popNext() will try to avoid launching long running tests at the end
        of the testing sequence, which can add significantly to the total wall
        time.
        """
        for np,tcaseL in self.xtlist.items():
            sortL = []
            for tcase in tcaseL:
                tm = tcase.getStat().getRuntime( None )
                if tm == None: tm = 0
                xdir = tcase.getSpec().getDisplayString()
                sortL.append( (tm,xdir,tcase) )
            sortL.sort()
            sortL.reverse()
            tcaseL[:] = [ tcase for tm,xdir,tcase in sortL ]

    def getTestExecProcList(self):
        """
        Returns a list of integers; each integer is the number of processors
        needed by one or more tests in the TestExec list.
        """
        return self.xtlist.keys()

    def getTestExecList(self, numprocs=None):
        """
        If 'numprocs' is None, all TestExec objects are returned.  If 'numprocs'
        is not None, a list of TestExec objects is returned each of which need
        that number of processors to run.
        """
        xL = []

        if numprocs == None:
            for tcaseL in self.xtlist.values():
                xL.extend( tcaseL )
        else:
            xL.extend( self.xtlist.get(numprocs,[]) )

        return xL

    def popNext(self, platform):
        """
        Finds a test to execute.  Returns a TestExec object, or None if no
        test can run.  In this case, one of the following is true

            1. there are not enough free processors to run another test
            2. the only tests left are parent tests that cannot be run
               because one or more of their children did not pass or diff

        In the latter case, numRunning() will be zero.
        """
        npL = list( self.xtlist.keys() )
        npL.sort()
        npL.reverse()

        # find longest runtime test such that the num procs is available
        tcase = self._pop_next_test( npL, platform )
        if tcase == None and len(self.started) == 0:
            # search for tests that need more processors than platform has
            tcase = self._pop_next_test( npL )

        if tcase != None:
            self.started[ tcase.getSpec().getID() ] = tcase

        return tcase

    def startTest(self, tcase, platform, baseline=0):
        ""
        tspec = tcase.getSpec()
        texec = tcase.getExec()

        np = int( tspec.getParameters().get('np', 0) )

        obj = platform.obtainProcs( np )
        texec.setResourceObject( obj )

        texec.start( baseline )

        tcase.getStat().markStarted( texec.getStartTime() )

    def popRemaining(self):
        """
        All remaining tests are removed from the run list and returned.
        """
        tL = []
        for np,tcaseL in list( self.xtlist.items() ):
            tL.extend( tcaseL )
            del tcaseL[:]
            self.xtlist.pop( np )
        return tL

    def getRunning(self):
        """
        Return the list of TestCase that are still running.
        """
        return self.started.values()

    def testDone(self, tcase):
        ""
        xid = tcase.getSpec().getID()
        self.tlist.appendTestResult( tcase )
        self.started.pop( xid, None )
        self.stopped[ xid ] = tcase

    def numDone(self):
        """
        Return the number of tests that have been run.
        """
        return len(self.stopped)

    def numRunning(self):
        """
        Return the number of tests are currently running.
        """
        return len(self.started)

    def _pop_next_test(self, npL, platform=None):
        ""
        for np in npL:
            if platform == None or platform.queryProcs(np):
                tcaseL = self.xtlist[np]
                N = len(tcaseL)
                i = 0
                while i < N:
                    tcase = tcaseL[i]
                    if tcase.getBlockingDependency() == None:
                        self._pop_test_exec( np, i )
                        return tcase
                    i += 1
        return None

    def _pop_test_exec(self, np, i):
        ""
        tcaseL = self.xtlist[np]
        del tcaseL[i]
        if len(tcaseL) == 0:
            self.xtlist.pop( np )
