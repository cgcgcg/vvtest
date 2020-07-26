#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys, os
import time


RESULTS_KEYWORDS = [ 'notrun', 'notdone',
                     'fail', 'diff', 'pass',
                     'timeout', 'skip' ]


# this is the exit status that tests use to indicate a diff
DIFF_EXIT_STATUS = 64

PARAM_SKIP = 'param'
RESTART_PARAM_SKIP = 'restartparam'
KEYWORD_SKIP = 'keyword'
RESULTS_KEYWORD_SKIP = 'resultskeyword'
SUBDIR_SKIP = 'subdir'

SKIP_REASON = {
        PARAM_SKIP           : 'excluded by parameter expression',
        RESTART_PARAM_SKIP   : 'excluded by parameter expression',
        KEYWORD_SKIP         : 'excluded by keyword expression',
        RESULTS_KEYWORD_SKIP : 'previous result keyword expression',
        SUBDIR_SKIP          : 'current working directory',
        'enabled'            : 'disabled',
        'platform'           : 'excluded by platform expression',
        'option'             : 'excluded by option expression',
        'tdd'                : 'TDD test',
        'search'             : 'excluded by file search expression',
        'maxprocs'           : 'exceeds max processors',
        'maxdevices'         : 'exceeds max devices',
        'runtime'            : 'runtime too low or too high',
        'nobaseline'         : 'no rebaseline specification',
        'depskip'            : 'analyze dependency skipped',
        'tsum'               : 'cummulative runtime exceeded',
    }


class TestStatus:

    def __init__(self):
        ""
        self.attrs = {}

    def setAttr(self, name, value):
        """
        Set a name to value pair.  The name can only contain a-zA-Z0-9 and _.
        """
        check_valid_attr_name( name )
        self.attrs[name] = value

    def hasAttr(self, name):
        return name in self.attrs

    def getAttr(self, name, *args):
        """
        Returns the attribute value corresponding to the attribute name.
        If the attribute name does not exist, an exception is thrown.  If
        the attribute name does not exist and a default value is given, the
        default value is returned.
        """
        if len(args) > 0:
            return self.attrs.get( name, args[0] )
        return self.attrs[name]

    def removeAttr(self, name):
        ""
        self.attrs.pop( name, None )

    def getAttrs(self):
        """
        Returns a copy of the test attributes (a name->value dictionary).
        """
        return dict( self.attrs )

    def resetResults(self):
        ""
        self.attrs['state'] = 'notrun'
        self.removeAttr( 'xtime' )
        self.removeAttr( 'xdate' )

    def getResultsKeywords(self):
        ""
        kL = []

        skip = self.attrs.get( 'skip', None )
        if skip != None:
            kL.append( 'skip' )

        state = self.attrs.get('state',None)
        if state == None:
            kL.append( 'notrun' )
        else:
            if state == "notrun":
                kL.append( 'notrun' )
            elif state == "notdone":
                kL.extend( ['notdone', 'running'] )

        result = self.attrs.get('result',None)
        if result != None:
            if result == 'timeout':
                kL.append( 'fail' )
            kL.append( result )

        return kL

    def markSkipByParameter(self, permanent=True):
        ""
        if permanent:
            self.attrs['skip'] = PARAM_SKIP
        else:
            self.attrs['skip'] = RESTART_PARAM_SKIP

    def skipTestByParameter(self):
        ""
        return self.attrs.get( 'skip', None ) == PARAM_SKIP

    def markSkipByKeyword(self, with_results=False):
        ""
        if with_results:
            self.attrs['skip'] = RESULTS_KEYWORD_SKIP
        else:
            self.attrs['skip'] = KEYWORD_SKIP

    def markSkipBySubdirectoryFilter(self):
        ""
        self.attrs['skip'] = SUBDIR_SKIP

    def markSkipByEnabled(self):
        ""
        self.attrs['skip'] = 'enabled'

    def markSkipByPlatform(self):
        ""
        self.attrs['skip'] = 'platform'

    def markSkipByOption(self):
        ""
        self.attrs['skip'] = 'option'

    def markSkipByTDD(self):
        ""
        self.attrs['skip'] = 'tdd'

    def markSkipByFileSearch(self):
        ""
        self.attrs['skip'] = 'search'

    def markSkipByMaxProcessors(self):
        ""
        self.attrs['skip'] = 'maxprocs'

    def markSkipByMaxDevices(self):
        ""
        self.attrs['skip'] = 'maxdevices'

    def markSkipByRuntime(self):
        ""
        self.attrs['skip'] = 'runtime'

    def markSkipByBaselineHandling(self):
        ""
        self.attrs['skip'] = 'nobaseline'

    def markSkipByAnalyzeDependency(self):
        ""
        self.attrs['skip'] = 'depskip'

    def markSkipByCummulativeRuntime(self):
        ""
        self.attrs['skip'] = 'tsum'

    def markSkipByUserValidation(self, reason):
        ""
        self.attrs['skip'] = reason

    def skipTestCausingAnalyzeSkip(self):
        ""
        skipit = False

        skp = self.attrs.get( 'skip', None )
        if skp != None:
            if skp.startswith( PARAM_SKIP ) or \
               skp.startswith( RESTART_PARAM_SKIP ) or \
               skp.startswith( RESULTS_KEYWORD_SKIP ) or \
               skp.startswith( SUBDIR_SKIP ):
                skipit = False
            else:
                skipit = True

        return skipit

    def skipTest(self):
        ""
        return self.attrs.get( 'skip', False )

    def getReasonForSkipTest(self):
        ""
        skip = self.skipTest()
        assert skip
        # a shortened skip reason is mapped to a longer description, but
        # if not found, then just return the skip value itself
        return SKIP_REASON.get( skip, skip )

    def isNotrun(self):
        ""
        # a test without a state is assumed to not have been run
        return self.attrs.get( 'state', 'notrun' ) == 'notrun'

    def isDone(self):
        ""
        return self.attrs.get( 'state', None ) == 'done'

    def isNotDone(self):
        ""
        return self.attrs.get( 'state', None ) == 'notdone'

    def passed(self):
        ""
        return self.isDone() and \
               self.attrs.get( 'result', None ) == 'pass'

    def getResultStatus(self):
        ""
        st = self.attrs.get( 'state', 'notrun' )

        if st == 'notrun':
            return 'notrun'

        elif st == 'done':
            return self.attrs.get( 'result', 'fail' )

        else:
            return 'notdone'

    def markStarted(self, start_time):
        ""
        self.attrs['state'] = 'notdone'
        self.attrs['xtime'] = -1
        self.attrs['xdate'] = int( 100 * start_time ) * 0.01

    def getStartDate(self, *default):
        ""
        if len( default ) > 0:
            return self.attrs.get( 'xdate', default[0] )
        return self.attrs.get( 'xdate' )

    def getRuntime(self, *default):
        ""
        xt = self.attrs.get( 'xtime', None )
        if xt == None or xt < 0:
            if len( default ) > 0:
                return default[0]
            raise KeyError( "runtime attribute not set" )
        return xt

    def setRuntime(self, num_seconds):
        ""
        self.attrs['xtime'] = num_seconds

    def markDone(self, exit_status):
        ""
        tzero = self.getStartDate()

        self.attrs['state'] = 'done'
        self.setRuntime( int(time.time()-tzero) )

        self.attrs['xvalue'] = exit_status

        result = translate_exit_status_to_result_string( exit_status )
        self.attrs['result'] = result

    def markTimedOut(self):
        ""
        self.markDone( 1 )
        self.attrs['result'] = 'timeout'


valid_varname_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"

def check_valid_attr_name( name ):
    ""
    for c in name:
        if c not in valid_varname_chars:
            raise ValueError( "character '" + c + "' not allowed in name" )


def copy_test_results( to_tcase, from_tcase ):
    ""
    for k,v in from_tcase.getStat().getAttrs().items():
        if k in ['state','xtime','xdate','xvalue','result']:
            to_tcase.getStat().setAttr( k, v )


def translate_exit_status_to_result_string( exit_status ):
    ""
    if exit_status == 0:
        return 'pass'

    elif exit_status == DIFF_EXIT_STATUS:
        return 'diff'

    else:
        return 'fail'
