#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import platform
import re

from .errors import TestSpecError
from . import timehandler
from .testspec import TestSpec

from .ScriptReader import ScriptReader, check_parse_attributes_section

from .paramset import ParameterSet

from .wordcheck import allowable_variable, allowable_word

from .parseutil import (
        variable_expansion,
        evaluate_testname_expr,
        check_for_duplicate_parameter,
        create_dependency_result_expression,
        check_forced_group_parameter,
        parse_to_word_expression,
        evaluate_platform_expr,
        evaluate_option_expr,
        evaluate_parameter_expr,
    )


class ScriptTestParser:

    def __init__(self, filepath,
                       rootpath=None,
                       platname=None,
                       optionlist=[],
                       force_params=None ):
        ""
        self.fpath = filepath

        if not rootpath:
            rootpath = os.getcwd()
        self.root = rootpath

        self.platname = platname or platform.uname()[0]
        self.optionlist = optionlist
        self.force = force_params

        fname = os.path.join( rootpath, filepath )
        self.reader = ScriptReader( fname )

    def parseTestNames(self):
        ""
        return self.parse_test_names()

    def parseParameterSet(self, testname):
        ""
        return self.parse_parameterize( testname )

    def parseAnalyzeSpec(self, testname):
        ""
        return self.parse_analyze( testname )

    def makeTestInstance(self, testname, idtraits):
        ""
        return TestSpec( testname, self.root, self.fpath, idtraits )

    def parseTestInstance(self, tspec):
        ""
        self.parse_enable        ( tspec )
        self.parse_keywords      ( tspec )
        self.parse_working_files ( tspec )
        self.parse_timeouts      ( tspec )
        self.parse_baseline      ( tspec )
        self.parse_dependencies  ( tspec )
        self.parse_preload_label ( tspec )

        tspec.setSpecificationForm( 'script' )

    ############## end public interface #################

    def parse_test_names(self):
        """
        Determines the test name(s) and checks each for validity.
        Returns a list of test names.
        """
        L = []

        for spec in self.itr_specs( None, "testname", "name" ):

            if spec.attrs:
                raise TestSpecError( 'no attributes allowed here, ' + \
                                     'line ' + str(spec.lineno) )

            name,attrD = parse_test_name_value( spec.value, spec.lineno )

            if not name or not allowable_word(name):
                raise TestSpecError( 'missing or invalid test name, ' + \
                                     repr(name) + ', line ' + str(spec.lineno) )
            L.append( name )

        if len(L) == 0:
            # the name defaults to the basename of the script file
            name = self.reader.basename()
            if not name or not allowable_word(name):
                raise TestSpecError( 'the basename of the test filename is not ' + \
                                     'a valid test name: '+repr(name) )
            L.append( name )

        return L

    def parse_parameterize(self, testname):
        """
        Parses the parameter settings for a script test file.

            #VVT: parameterize : np=1 4
            #VVT: parameterize (testname=mytest_fast) : np=1 4
            #VVT: parameterize (platforms=Cray or redsky) : np=128
            #VVT: parameterize (options=not dbg) : np=32
            
            #VVT: parameterize : dt,dh = 0.1,0.2  0.01,0.02  0.001,0.002
            #VVT: parameterize : np,dt,dh = 1, 0.1  , 0.2
            #VVT::                          4, 0.01 , 0.02
            #VVT::                          8, 0.001, 0.002
        """
        pset = ParameterSet()
        tmap = {}

        for spec in self.itr_specs( testname, 'parameterize' ):

            lnum = spec.lineno

            check_allowed_attrs( spec.attrs, lnum,
                    'testname platform platforms option options '
                    'staged autotype' )

            if not self.attr_filter( spec.attrs, testname, None, lnum ):
                continue

            L = spec.value.split( '=', 1 )
            if len(L) < 2:
                raise TestSpecError( "invalid parameterize specification, " + \
                                     "line " + str(lnum) )

            namestr,valuestr = L

            if not namestr.strip():
                raise TestSpecError( "no parameter name given, " + \
                                     "line " + str(lnum) )
            if not valuestr.strip():
                raise TestSpecError( "no parameter value(s) given, " + \
                                     "line " + str(lnum) )

            nameL = [ n.strip() for n in namestr.strip().split(',') ]

            check_parameter_names( nameL, lnum )

            if len(nameL) == 1:
                valL = parse_param_values( nameL[0], valuestr, self.force )
                check_parameter_values( valL, lnum )
                check_special_parameters( nameL[0], valL, lnum )
            else:
                valL = parse_param_group_values( nameL, valuestr, lnum )
                check_forced_group_parameter( self.force, nameL, lnum )

            if spec.attrs and 'autotype' in spec.attrs:
                auto_determine_param_types( nameL, valL, tmap )

            staged = check_for_staging( spec.attrs, pset, nameL, valL, lnum )

            check_for_duplicate_parameter( valL, lnum )

            if len(nameL) == 1:
                pset.addParameter( nameL[0], valL )
            else:
                pset.addParameterGroup( nameL, valL, staged )

        pset.setParameterTypeMap( tmap )

        return pset

    def parse_analyze(self, testname):
        """
        Parse any analyze specifications.
        
            #VVT: analyze : analyze.py
            #VVT: analyze : --analyze
            #VVT: analyze (testname=not mytest_fast) : --analyze

            - if the value starts with a hyphen, then an option is assumed
            - otherwise, a script file is assumed

        Returns true if an analyze specification was found.
        """
        form = None
        specval = None
        for spec in self.itr_specs( testname, 'analyze' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                    'testname platform platforms option options' )

            if not self.attr_filter( spec.attrs, testname, None, spec.lineno ):
                continue

            sval = spec.value
            if not sval or not sval.strip():
                raise TestSpecError( 'missing or invalid analyze value, ' + \
                                     'line ' + str(spec.lineno) )

            specval = sval.strip()

        return specval

    def parse_enable(self, tspec):
        """
        Parse syntax that will filter out this test by platform or build option.
        
        Platform expressions and build options use word expressions.
        
            #VVT: enable (platforms="not SunOS and not Linux")
            #VVT: enable (options="not dbg and ( tridev or tri8 )")
            #VVT: enable (platforms="...", options="...")
            #VVT: enable = True
            #VVT: enable = False

        If both platform and option expressions are given, their results are
        ANDed together.  If more than one "enable" block is given, each must
        result in True for the test to be included.
        """
        testname = tspec.getName()

        platexprL = []
        optexprL = []

        for spec in self.itr_specs( testname, 'enable' ):

            platexpr = None
            optexpr = None

            if spec.attrs:

                check_allowed_attrs( spec.attrs, spec.lineno,
                        'testname platform platforms option options' )

                if not testname_ok( spec.attrs, testname, spec.lineno ):
                    # the "enable" does not apply to this test name
                    continue

                platexpr = spec.attrs.get( 'platforms',
                                           spec.attrs.get( 'platform', None ) )
                if platexpr is not None:
                    parse_to_word_expression( platexpr.strip(), spec.lineno )
                    platexprL.append( platexpr.strip() )

                optexpr = spec.attrs.get( 'options',
                                          spec.attrs.get( 'option', None ) )
                if optexpr and optexpr.strip():
                    # an empty option expression is ignored
                    parse_to_word_expression( optexpr.strip(), spec.lineno )
                    optexprL.append( optexpr.strip() )

            if spec.value:
                val = spec.value.lower().strip()
                if val != 'true' and val != 'false':
                    raise TestSpecError( 'invalid "enable" value, line ' + \
                                         str(spec.lineno) )
                if val == 'false' and ( platexpr != None or optexpr != None ):
                    raise TestSpecError( 'an "enable" with platforms or ' + \
                        'options attributes cannot specify "false", line ' + \
                        str(spec.lineno) )
                tspec.setEnabled( val == 'true' )

        wx = parse_to_word_expression( platexprL )
        tspec.setEnablePlatformExpression( wx )

        wx = parse_to_word_expression( optexprL )
        tspec.setEnableOptionExpression( wx )

    def parse_keywords(self, tspec):
        """
        Parse the test keywords for the test script file.
        
          keywords : key1 key2
          keywords (testname=mytest) : key3
          keywords (parameters="foo=bar") : key3
        
        Note that a test will automatically pick up the test name and the
        parameterize names as keywords.
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        keys = []

        for spec in self.itr_specs( testname, 'keywords' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                                 'testname parameter parameters' )

            if not testname_ok( spec.attrs, testname, spec.lineno ):
                continue

            if not self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                continue

            for key in spec.value.strip().split():
                if allowable_word(key):
                    keys.append( key )
                else:
                    raise TestSpecError( 'invalid keyword: '+repr(key) + \
                                         ', line ' + str(spec.lineno) )

        tspec.setKeywordList( keys )

    def parse_working_files(self, tspec):
        """
            #VVT: copy : file1 file2
            #VVT: link : file3 file4
            #VVT: copy (filters) : srcname1,copyname1 srcname2,copyname2
            #VVT: link (filters) : srcname1,linkname1 srcname2,linkname2

            #VVT: sources : file1 file2 ${NAME}_*.py
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        cpfiles = []
        lnfiles = []

        for spec in self.itr_specs( testname, 'copy' ):
            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms '
                'option options rename' )
            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                collect_filenames( spec, cpfiles, testname, params, self.platname )

        for spec in self.itr_specs( testname, 'link' ):
            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms '
                'option options rename' )
            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                collect_filenames( spec, lnfiles, testname, params, self.platname )
        
        for src,dst in lnfiles:
            tspec.addLinkFile( src, dst )

        for src,dst in cpfiles:
            tspec.addCopyFile( src, dst )

        fL = []
        for spec in self.itr_specs( testname, 'sources' ):
            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                if spec.value:
                    L = spec.value.split()
                    variable_expansion( testname, self.platname, params, L )
                    fL.extend( L )

        tspec.setSourceFiles( fL )

    def parse_timeouts(self, tspec):
        """
          #VVT: timeout : 3600
          #VVT: timeout : 2h 30m 5s
          #VVT: timeout : 2:30:05
          #VVT: timeout (testname=vvfull, platforms=Linux) : 3600
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        for spec in self.itr_specs( testname, 'timeout' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms option options' )

            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                sval = spec.value

                ival,err = timehandler.parse_timeout_value( sval )

                if err:
                    raise TestSpecError( 'invalid timeout value: '+err )

                tspec.setTimeout( ival )

    def parse_baseline(self, tspec):
        """
          #VVT: baseline : copyfrom,copyto copyfrom,copyto
          #VVT: baseline : --option-name
          #VVT: baseline : baseline.py
        
        where the existence of a comma triggers the first form
        otherwise, if the value starts with a hyphen then the second form
        otherwise, the value is the name of a filename
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        cpat = re.compile( '[\t ]*,[\t ]*' )

        for spec in self.itr_specs( testname, 'baseline' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms '
                'option options file argument' )

            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):

                sval = spec.value.strip()

                if not sval or not sval.strip():
                    raise TestSpecError( 'missing or invalid baseline value, ' + \
                                         'line ' + str(spec.lineno) )

                if spec.attrs and 'file' in spec.attrs:
                    raise TestSpecError( 'the "file" baseline attribute is ' + \
                                         'no longer supported, ' + \
                                         'line ' + str(spec.lineno) )

                if spec.attrs and 'argument' in spec.attrs:
                    raise TestSpecError( 'the "argument" baseline attribute is ' + \
                                         'no longer supported, ' + \
                                         'line ' + str(spec.lineno) )

                if ',' in sval:
                    form = 'copy'
                elif sval.startswith( '-' ):
                    form = 'arg'
                else:
                    form = 'file'

                if ',' in sval:
                    fL = []
                    for s in cpat.sub( ',', sval ).split():
                        L = s.split(',')
                        if len(L) != 2:
                            raise TestSpecError( 'malformed baseline file ' + \
                                      'list: "'+s+'", line ' + str(spec.lineno) )
                        fsrc,fdst = L
                        if os.path.isabs(fsrc) or os.path.isabs(fdst):
                            raise TestSpecError( 'file names cannot be ' + \
                                      'absolute paths, line ' + str(spec.lineno) )
                        fL.append( [fsrc,fdst] )

                    variable_expansion( testname,
                                        self.platname,
                                        params,
                                        fL )

                    for fsrc,fdst in fL:
                        tspec.addBaselineFile( fsrc, fdst )

                else:
                    tspec.setBaselineScript( sval )
                    if not sval.startswith( '-' ):
                        tspec.addLinkFile( sval )

    def parse_dependencies(self, tspec):
        """
        Parse the test names that must run before this test can run.

            #VVT: depends on : test1 test2
            #VVT: depends on : test_pattern
            #VVT: depends on (result=pass) : testname
            #VVT: depends on (result="pass or diff") : testname
            #VVT: depends on (result="*") : testname

            #VVT: testname = testA (depends on=testB, result="*")
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        for spec in self.itr_specs( testname, 'depends on' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms '
                'option options result expect' )

            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):

                wx = create_dependency_result_expression( spec.attrs, spec.lineno )
                exp = parse_expect_criterion( spec.attrs, spec.lineno )

                for val in spec.value.strip().split():
                    tspec.addDependency( val, wx, exp )

        for spec in self.itr_specs( testname, "testname", "name"):

            name,attrD = parse_test_name_value( spec.value, spec.lineno )
            if name == testname:

                check_allowed_attrs( attrD, spec.lineno,
                                     ['depends on','result','expect'] )

                wx = create_dependency_result_expression( attrD, spec.lineno )
                exp = parse_expect_criterion( attrD, spec.lineno )

                for depname in attrD.get( 'depends on', '' ).split():
                    tspec.addDependency( depname, wx, exp )

    def parse_preload_label(self, tspec):
        """
        #VVT: preload (filters) : label
        """
        testname = tspec.getName()
        params = tspec.getParameters()

        for spec in self.itr_specs( testname, 'preload' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                'testname parameter parameters platform platforms '
                'option options' )

            if self.attr_filter( spec.attrs, testname, params, spec.lineno ):
                val = ' '.join( spec.value.strip().split() )
                tspec.setPreloadLabel( val )

    def itr_specs(self, testname, *spec_names):
        ""
        return self.itr_recurse( self.reader.getSpecList(), testname, *spec_names )

    def itr_recurse(self, speclist, testname, *spec_names):
        ""
        for spec1 in speclist:
            if spec1.keyword == 'include':

                check_allowed_attrs( spec1.attrs, spec1.lineno,
                        'testname platform platforms option options' )

                if self.follow_include_directive( spec1.attrs, testname, spec1.lineno ):
                    for spec2 in self.itr_recurse( spec1.value, testname, *spec_names ):
                        yield spec2

            elif not spec_names or spec1.keyword in spec_names:
                yield spec1

    def follow_include_directive(self, spec_attrs, testname, lineno):
        ""
        if testname is None and spec_attrs and 'testname' in spec_attrs:
            return False

        return self.attr_filter( spec_attrs, testname, None, lineno )

    def attr_filter(self, attrs, testname, params, lineno):
        """
        Checks for known attribute names in the given 'attrs' dictionary.
        Returns False only if at least one attribute evaluates to false.
        """
        if attrs:

            for name,value in attrs.items():

                try:
                    if name == "testname":
                        if not evaluate_testname_expr( testname, value ):
                            return False

                    elif name in ["platform","platforms"]:
                        if not evaluate_platform_expr( self.platname, value ):
                            return False

                    elif name in ["option","options"]:
                        if not evaluate_option_expr( self.optionlist, value ):
                            return False

                    elif name in ["parameter","parameters"]:
                        if not evaluate_parameter_expr( params, value ):
                            return False

                except ValueError:
                    raise TestSpecError( 'invalid '+name+' expression, ' + \
                                         'line ' + lineno + ": " + \
                                         str(sys.exc_info()[1]) )

        return True


def parse_test_name_value( value, lineno ):
    ""
    name = value
    aD = {}

    sL = value.split( None, 1 )
    if len(sL) == 2:
        name,tail = sL

        if tail[0] == '#':
            pass

        elif tail[0] == '(':
            aD,_ = check_parse_attributes_section( tail, str(lineno) )

        else:
            raise TestSpecError( 'invalid test name: ' + repr(value) + \
                    ', line ' + str(lineno) )

    return name, aD


def check_allowed_attrs( attrD, lnum, allowed ):
    ""
    if attrD:

        if type(allowed) == type(''):
            allowed = allowed.split()

        for name in attrD.keys():
            if name not in allowed:
                raise TestSpecError( "attribute "+repr(name) + \
                        " not allowed here, line " + str(lnum) )


def auto_determine_param_types( nameL, valL, tmap ):
    ""
    if len( nameL ) == 1:
        typ = try_cast_to_int_or_float( valL )
        if typ != None:
            tmap[ nameL[0] ] = typ

    else:
        for i,name in enumerate(nameL):
            typ = try_cast_to_int_or_float( [ tup[i] for tup in valL ] )
            if typ != None:
                tmap[ name ] = typ


def try_cast_to_int_or_float( valuelist ):
    ""
    for typ in [int,float]:
        if values_cast_to_type( typ, valuelist ):
            return typ
    return None


def values_cast_to_type( typeobj, valuelist ):
    ""
    try:
        vL = [ typeobj(v) for v in valuelist ]
    except Exception:
        return False
    return True


def check_for_staging( spec_attrs, pset, nameL, valL, lineno ):
    """
    for staged parameterize, the names & values are augmented. for example,

        nameL = [ 'pname' ] would become [ 'stage', 'pname' ]
        valL = [ 'val1', 'val2' ] would become [ ['1','val1'], ['2','val2'] ]
    """
    if spec_attrs and 'staged' in spec_attrs:

        if pset.getStagedGroup() != None:
            raise TestSpecError( 'only one parameterize can be staged' + \
                                 ', line ' + str(lineno) )

        insert_staging_into_names_and_values( nameL, valL )

        return True

    return False


def insert_staging_into_names_and_values( names, values ):
    ""
    if len( names ) == 1:
        values[:] = [ [str(i),v] for i,v in enumerate(values, start=1) ]
    else:
        values[:] = [ [str(i)]+vL for i,vL in enumerate(values, start=1) ]

    names[:] = [ 'stage' ] + names


def check_parameter_names( name_list, lineno ):
    ""
    for v in name_list:
        if not allowable_variable(v):
            raise TestSpecError( 'invalid parameter name: "' + \
                                 v+'", line ' + str(lineno) )


def check_parameter_values( value_list, lineno ):
    ""
    for v in value_list:
        if not allowable_word(v):
            raise TestSpecError( 'invalid parameter value: "' + \
                                 v+'", line ' + str(lineno) )


def check_special_parameters( param_name, value_list, lineno ):
    ""
    if param_name in [ 'np', 'ndevice', 'nnode' ]:
        for val in value_list:
            try:
                ival = int(val)
            except Exception:
                ival = None

            if ival == None or ival < 0:
                raise TestSpecError( 'the parameter "'+param_name+'" '
                                     'must be a non-negative integer: "' + \
                                     val+'", line ' + str(lineno) )


def parse_param_values( param_name, value_string, force_params ):
    ""
    if force_params != None and param_name in force_params:
        vals = force_params[ param_name ]
    else:
        vals = value_string.strip().split()

    return vals


spaced_comma_pattern = re.compile( '[\t ]*,[\t ]*' )

def parse_param_group_values( name_list, value_string, lineno ):
    ""
    compressed_string = spaced_comma_pattern.sub( ',', value_string.strip() )

    vL = []
    for s in compressed_string.split():

        gL = s.split(',')
        if len(gL) != len(name_list):
            raise TestSpecError( 'malformed parameter list: "' + \
                                  s+'", line ' + str(lineno) )

        check_parameter_values( gL, lineno )
        for name,val in zip( name_list, gL ):
            check_special_parameters( name, [val], lineno )

        vL.append( gL )

    return vL


def collect_filenames( spec, flist, tname, paramD, platname ):
    """
        #VVT: copy : file1 file2
        #VVT: copy (rename) : srcname1,copyname1 srcname2,copyname2
    """
    val = spec.value.strip()

    if spec.attrs and 'rename' in spec.attrs:
        cpat = re.compile( '[\t ]*,[\t ]*' )
        fL = []
        for s in cpat.sub( ',', val ).split():
            L = s.split(',')
            if len(L) != 2:
                raise TestSpecError( 'malformed (rename) file list: "' + \
                                      s+'", line ' + str(spec.lineno) )
            fsrc,fdst = L
            if os.path.isabs(fsrc) or os.path.isabs(fdst):
                raise TestSpecError( 'file names cannot be absolute ' + \
                                     'paths, line ' + str(spec.lineno) )
            fL.append( [fsrc,fdst] )
        
        variable_expansion( tname, platname, paramD, fL )

        flist.extend( fL )

    else:
        fL = val.split()
        
        for f in fL:
            if os.path.isabs(f):
                raise TestSpecError( 'file names cannot be absolute ' + \
                                     'paths, line ' + str(spec.lineno) )
        
        variable_expansion( tname, platname, paramD, fL )

        flist.extend( [ [f,None] for f in fL ] )


def parse_expect_criterion( attrs, lineno ):
    ""
    exp = '+'

    if attrs:
        exp = attrs.get( 'expect', '+' ).strip("'")

    if exp not in ['+','*','?']:
        try:
            ival = int( exp )
            ok = True
        except Exception:
            ok = False

        if not ok or ival < 0:
            raise TestSpecError( "invalid 'expect' value, \""+str(exp) + \
                                 "\", line " + str(lineno) )

    return exp


def testname_ok( attrs, tname, lineno ):
    ""
    ok = True

    if attrs != None:
        tval = attrs.get( 'testname', None )
        if tval is not None:
            try:
                if not evaluate_testname_expr( tname, tval ):
                    ok = False
            except Exception as e:
                raise TestSpecError( 'bad testname expression, ' + \
                            repr(tval) + ': '+str(e) + \
                            ', line ' + str(lineno) )

    return ok
