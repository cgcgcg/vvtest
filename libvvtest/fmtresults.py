#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import join as pjoin, basename, dirname
import time
import glob

from . import listwriter


class LookupCache:

    def __init__(self, rtinfo, resultsdir):
        ""
        self.rtinfo = rtinfo
        self.resultsdir = resultsdir

        # magic: save results from file reads for fast lookup and on-demand
        self.tinfo = None
        self.pathcache = listwriter.TestPathIdentification()

    def load(self):
        ""
        if self.resultsdir is not None:
            # magic: filename parser to get results files that match
            #        the current platform and options plus separate by date
            fpat = listwriter.make_filename_glob_pattern( self.rtinfo )
            fnL = glob.glob( pjoin( self.resultsdir, fpat ) )
            fnL.sort()
            # print('magic: load',fnL)
            if len(fnL) > 0:
                # magic: currently only read most recent file
                finfo,self.tinfo = listwriter.read_results_file( fnL[-1] )

    def getRunTime(self, testspec):
        """
        Looks in the testing directory and the test source tree for files that
        contain a runtime for the given test.  If an entry is not found then
        None,None is returned.

        The 'cache' must be a LookupCache instance and should be the same instance
        for a set of tests (which helps performance).  Also, this same cache
        should be given/used by any approximate execution time algorithms if this
        function fails to find a runtime for the test.

        The algorithm looks for the test in this order:

          1. The TESTING_DIRECTORY directory multiplatform results file
          2. A test source tree runtimes file
        """
        if self.tinfo:
            pathid = self.pathcache.get_path_id( testspec.getFilename() )
            # print('magic: check runtime for',testspec.getDisplayString(),pathid)
            if pathid:
                # magic: for fast lookup, each file results contents
                #        should be stored as a dict with keys being the
                #        pathid plus test name plus test params
                for D in self.tinfo:
                    # print('magic: cmp D',D,testspec.getID(),pathid)
                    if D['pathid'] == pathid:
                        if D['testid'][1:] == list( testspec.getID()[1:] ):
                            # print('magic: found',D)
                            return D.get('runtime',None),D.get('result',None)
        return None,None
