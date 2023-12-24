#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys


class TimeHandler:

    def __init__(self, userplugin, cmdline_timeout,
                       timeout_multiplier, max_timeout,
                       cache):
        ""
        self.plugin = userplugin
        self.cmdline_timeout = cmdline_timeout
        self.tmult = timeout_multiplier
        self.maxtime = max_timeout
        self.cache = cache

    def loadExternalRuntimes(self, tcaselist):
        """
        For each test, the user plugin will be queried or a "runtimes" file
        will be read (if it exists) and the run time for this platform extracted.
        This run time is saved in the 'xtime' test attribute (accessed via the
        TestStatus.getRuntime() method).
        """
        self.cache.load()

        for tcase in tcaselist:

            tspec = tcase.getSpec()
            tstat = tcase.getStat()

            tout = self.plugin.testRuntime( tcase )
            if tout is not None:
                # Prefer plugin value
                tstat.setRuntime( int(tout) )
            else:
                tlen, _ = self.cache.getRunTime( tspec )
                if tlen is not None:
                    rt = tstat.getRuntime( None )
                    if rt is None:
                        tstat.setRuntime( int(tlen) )

    def setTimeouts(self, tcaselist):
        """
        A timeout is calculated for each test and placed in the 'timeout'
        test attribute.
        """
        for tcase in tcaselist:

            tspec = tcase.getSpec()
            tstat = tcase.getStat()

            tout = self.plugin.testTimeout( tcase )
            if tout is None:
                # grab explicit timeout value, if the test specifies it
                tout = tspec.getTimeout()

            # look for a previous runtime value
            tlen,tresult = self.cache.getRunTime( tspec )

            if tlen is not None:

                if tout is None:
                    if tresult == "timeout":
                        tout = self._timeout_if_test_timed_out( tspec, tlen )
                    else:
                        tout = self._timeout_from_previous_runtime( tlen )

            elif tout is None:
                tout = self._default_timeout( tspec )

            tout = self._apply_timeout_options( tout )

            tstat.setTimeout( tout )

    def _timeout_if_test_timed_out(self, tspec, runtime):
        ""
        # for tests that timed out, make timeout much larger
        if tspec.hasKeyword( "long" ):
            # only long tests get timeouts longer than an hour
            if runtime < 60*60:
                tm = 4*60*60
            elif runtime < 5*24*60*60:  # even longs are capped
                tm = 4*runtime
            else:
                tm = 5*24*60*60
        else:
            tm = 60*60

        return tm

    def _timeout_from_previous_runtime(self, runtime):
        ""
        # pick timeout to allow for some runtime variability
        if runtime < 120:
            tm = max( 120, 2*runtime )
        elif runtime < 300:
            tm = max( 300, 1.5*runtime )
        elif runtime < 4*60*60:
            tm = int( float(runtime)*1.5 )
        else:
            tm = int( float(runtime)*1.3 )

        return tm

    def _default_timeout(self, tspec):
        ""
        # with no information, the default depends on 'long' keyword
        if tspec.hasKeyword("long"):
            tm = 5*60*60  # five hours
        else:
            tm = 60*60  # one hour

        return tm

    def _apply_timeout_options(self, timeout):
        ""
        if self.cmdline_timeout is not None:
            timeout = self.cmdline_timeout

        if self.tmult is not None and timeout and timeout > 0:
            timeout = max( 1, int( float(timeout) * self.tmult + 0.5 ) )

        if self.maxtime is not None and timeout:
            timeout = min( timeout, self.maxtime )

        return timeout


def parse_timeout_value( value ):
    """
    A negative value is snapped to zero (an integer). A positive value will
    result in an integer greater than or equal to one.
    """
    err = ''
    nsecs = None

    try:
        nsecs = parse_num_seconds( value, negatives=True )
    except Exception as e:
        err = str(e)
    else:
        if nsecs is not None:
            if nsecs < 0 or not nsecs > 0.0:
                nsecs = 0
            else:
                nsecs = int( max( 1, nsecs ) + 0.5 )

    return nsecs,err


def parse_timeout_multiplier( value ):
    ""
    val,err = parse_number( value )
    if not err and val is not None and ( val < 0 or not val > 0.0 ):
        err = 'cannot be negative or zero: '+repr(value)

    return val,err


def parse_max_time( value ):
    """
    Negative values and zero will be None. A positive value will result in
    an integer greater than or equal to one.
    """
    err = ''
    nsecs = None

    try:
        nsecs = parse_num_seconds( value, negatives=True )
    except Exception as e:
        err = str(e)
    else:
        if nsecs is not None:
            if nsecs < 0 or not nsecs > 0.0:
                nsecs = None
            else:
                nsecs = int( max( 1, nsecs ) + 0.5 )

    return nsecs,err


def parse_num_seconds( value, round_to_int=False, negatives=False ):
    """
    Parse a string to num seconds. The string can be an integer or floating
    point number, or format HH:MM:SS, or 3d 10h 26m 10s. A value of None
    just returns None. A plain Exception is raised on error.

    'round' True means make the value an integer if parsed as a float
    'negatives' True means allow negative number of seconds
    """
    val = None

    if value != None:

        value = value.strip()
        if not value:
            raise Exception( 'empty string not allowed' )

        nval,err = parse_number( value )
        if err:
            if ':' in value:
                nval = parse_HH_MM_SS_to_seconds( value )
            else:
                nval = parse_h_m_s_to_seconds( value )

        if not negatives and nval < 0:
            raise Exception( 'cannot be negative: '+repr(value) )
        if round_to_int:
            nval = int( float(nval) + 0.5 )
        val = nval

    return val


def parse_number( value ):
    ""
    val = None
    err = ''

    if value != None:
        try:
            ival = int(value)
        except Exception:
            try:
                fval = float(value)
            except Exception:
                err = 'could not cast to a number: '+repr(value)
            else:
                val = fval
        else:
            val = ival

    return val,err


def parse_integer( value ):
    ""
    val = None
    err = ''

    if value != None:
        try:
            ival = int(value)
        except Exception:
            err = 'could not cast to an integer: '+repr(value)
        else:
            val = ival

    return val,err


def parse_h_m_s_to_seconds( value ):
    """
    such as "17s" or "2h 10m 30s"
    """
    sumval = 0

    for tok in value.split():
        if tok.endswith('s'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += n
        elif tok.endswith('m'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 60 )
        elif tok.endswith('h'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 60*60 )
        elif tok.endswith('d'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 24*60*60 )
        else:
            raise Exception( 'could not parse to seconds: '+repr(value) )

    return sumval


def parse_HH_MM_SS_to_seconds( value ):
    ""
    if not value.strip():
        raise Exception( 'empty string not allowed' )

    sL = value.strip().split(':')

    sumval = 0

    n,e = parse_number( sL[-1] )
    if e or n < 0 or ( ':' in value and n >= 60 ):
        raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
    sumval += n

    if len(sL) > 1:
        n,e = parse_integer( sL[-2] )
        if e or n < 0 or n >= 60:
            raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
        sumval += ( n * 60 )

    if len(sL) > 2:
        n,e = parse_integer( sL[-3] )
        if e or n < 0:
            raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
        sumval += ( n * 60*60 )

    return sumval
