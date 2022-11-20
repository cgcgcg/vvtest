#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import dirname, normpath, join as pjoin
import platform
import re
import shlex
import subprocess

from .errors import TestSpecError
from . import timehandler
from .testspec import TestSpec
from .depend import DependencyPattern

from .ScriptReader import ScriptReader, check_parse_attributes_section

from .paramset import ParameterSet

from .wordcheck import allowable_variable, allowable_word

from .parseutil import (
        variable_expansion,
        evaluate_testname_expr,
        remove_duplicate_parameter_values,
        create_dependency_result_expression,
        check_forced_group_parameter,
        parse_to_word_expression,
        evaluate_platform_expr,
        evaluate_option_expr,
        evaluate_parameter_expr,
        raiseError,
    )

platform_windows = platform.uname()[0].lower().startswith('win')


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
                raiseError( 'no attributes allowed here', line=spec.lineno )

            name,attrD = parse_test_name_value( spec.value, spec.lineno )

            if not name:
                raiseError( 'missing test name', line=spec.lineno )
            if not allowable_word(name):
                raiseError( 'invalid test name:', repr(name), line=spec.lineno )

            L.append( name )

        if len(L) == 0:
            # the name defaults to the basename of the script file
            name = self.reader.basename()
            if not name or not allowable_word(name):
                raiseError( 'the basename of the test filename is not',
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

            #VVT: parameterize (autotype) : np = 1 8
            #VVT: parameterize (int) : np = 1 8
            #VVT: parameterize (float) : val = 2 5
            #VVT: parameterize (int,float) : foo,bar = 1,2 8,5
            #VVT: parameterize (float) : A,B = 1,2 3,4
            #VVT: parameterize (str,float,str) : X,Y,Z = 1,2,3 4,5,6
        """
        pset = ParameterSet()
        tmap = {}

        for spec in self.itr_specs( testname, 'parameterize' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                    'testname platform platforms option options '
                    'staged autotype str int float generator' )

            if not self.attr_filter( spec.attrs, testname, None, spec.lineno ):
                continue

            if spec.attrs and 'generator' in spec.attrs:

                if 'int' in spec.attrs or 'float' in spec.attrs or \
                   'str' in spec.attrs or 'autotype' in spec.attrs:
                    raiseError( 'cannot specify type specifiers with a',
                                'generator attribute', line=spec.lineno )

                fname = os.path.join( self.root, self.fpath )
                nameL,valL = generate_parameters( fname, spec.value, spec.lineno )
                valL,typmap = convert_value_types( nameL, valL )

            else:
                nameL,valL = parse_param_names_and_values( spec.value, self.force, spec.lineno )
                typmap = parse_param_type_map( spec.attr_names, nameL, valL, spec.lineno )

            tmap.update( typmap )

            staged = check_for_staging( spec.attrs, pset, nameL, valL, spec.lineno )

            valL = remove_duplicate_parameter_values( valL )

            pset.addParameters( nameL, valL, staged )

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

        Returns None or the analyze specification (a string).
        """
        specval = None
        for spec in self.itr_specs( testname, 'analyze' ):

            check_allowed_attrs( spec.attrs, spec.lineno,
                    'testname platform platforms option options' )

            if not self.attr_filter( spec.attrs, testname, None, spec.lineno ):
                continue

            sval = spec.value
            if not sval or not sval.strip():
                raiseError( 'missing analyze value', line=spec.lineno )

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
                    raiseError( 'invalid "enable" value:', repr(spec.value),
                                line=spec.lineno )
                if val == 'false' and ( platexpr is not None or optexpr is not None ):
                    raiseError( 'an "enable" with platforms or options',
                        'attributes cannot specify "false"', line=spec.lineno )
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
                    raiseError( 'invalid keyword:', repr(key), line=spec.lineno )

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
                    raiseError( 'invalid timeout value:', err, line=spec.lineno )

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
                    raiseError( 'missing or empty baseline value', line=spec.lineno )

                if spec.attrs and 'file' in spec.attrs:
                    raiseError( 'the "file" baseline attribute is no longer',
                                'supported', line=spec.lineno )
                if spec.attrs and 'argument' in spec.attrs:
                    raiseError( 'the "argument" baseline attribute is no longer',
                                'supported', line=spec.lineno )

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
                            raiseError( 'malformed baseline file list:',
                                        repr(s), line=spec.lineno )
                        fsrc,fdst = L
                        if os.path.isabs(fsrc) or os.path.isabs(fdst):
                            raiseError( 'file names cannot be absolute paths',
                                        line=spec.lineno )
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
                    dpat = DependencyPattern( val, exp, wx )
                    tspec.addDependencyPattern( dpat )

        for spec in self.itr_specs( testname, "testname", "name"):

            name,attrD = parse_test_name_value( spec.value, spec.lineno )
            if name == testname:

                check_allowed_attrs( attrD, spec.lineno,
                                     ['depends on','result','expect'] )

                wx = create_dependency_result_expression( attrD, spec.lineno )
                exp = parse_expect_criterion( attrD, spec.lineno )

                for depname in attrD.get( 'depends on', '' ).split():
                    dpat = DependencyPattern( depname, exp, wx )
                    tspec.addDependencyPattern( dpat )

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
                    raiseError( 'invalid', name, 'expression',
                                '(at line '+str(lineno)+'):', sys.exc_info()[1] )

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
            aD,_,_ = check_parse_attributes_section( tail, str(lineno) )

        else:
            raiseError( 'invalid test name:', line=lineno )

    return name, aD


def check_allowed_attrs( attrD, lineno, allowed ):
    ""
    if attrD:

        if type(allowed) == type(''):
            allowed = allowed.split()

        for name in attrD.keys():
            if name not in allowed:
                raiseError( 'attribute', repr(name), 'not allowed here',
                            line=lineno )


def generate_parameters( testfile, gencmd, lineno ):
    ""
    if not gencmd.strip():
        raiseError( 'generator specification is missing', line=lineno )

    cmdL = shlex.split( gencmd.strip() )

    if len(cmdL) == 0:
        raiseError( 'invalid generator specification', line=lineno )

    prog,xcute = get_generator_program( dirname(testfile), cmdL[0] )
    cmdL[0] = prog

    out = run_generator_prog( cmdL, gencmd, xcute )

    errmsg = None
    try:
        plist = eval( out.strip() )
    except Exception:
        errmsg = 'could not Python eval() generator output (expected a ' + \
                 'single line repr() of a list of dictionaries): '+repr(out.strip() )
    if errmsg:
        raiseError( errmsg, line=lineno )

    check_for_rectangular_matrix( plist, lineno )

    nameL, valL = make_names_and_value_lists( plist, lineno )

    return nameL,valL


def convert_value_types( nameL, valL ):
    ""
    typmap = {}
    for i,n in enumerate(nameL):
        typ = type( valL[0][i] )  # representative value
        if typ == int:
            typmap[n] = int
        elif typ == float:
            typmap[n] = float
        else:
            typmap[n] = str

    new_valL = []
    for tup in valL:
        new_valL.append( [ repr(v) for v in tup ] )

    return new_valL,typmap


def check_for_rectangular_matrix( plist, lineno ):
    ""
    errmsg = None

    if len(plist) == 0:
        errmsg = 'generator output cannot be an empty list'
    elif any( [ type(D) != type({}) for D in plist ] ):
        errmsg = 'generator output must be a list of dictionaries'
    elif any( [ len(D) == 0 for D in plist ] ):
        errmsg = 'the dictionaries in the generator list cannot be empty'
    elif min([len(D) for D in plist]) != max([len(D) for D in plist]):
        errmsg = 'the dictionaries in the generator list must ' + \
                 'all be the same size'

    if errmsg:
        raiseError( errmsg, line=lineno )


def make_names_and_value_lists( plist, lineno ):
    """
    creates and returns

        nameL = [ param_name_1, param_name_2, ... ]

        valueL = [
                   [ p1_v1, p1_v2, ... ],
                   [ p2_v1, p2_v2, ... ],
                   ...
                 ]
    """
    check_generator_instance_names( plist, lineno )

    nameL = None
    valL = None
    for D in plist:
        if nameL is None:
            nameL = sorted( D.keys() )
            valL = [ [ D[n] for n in nameL ] ]
        else:
            if sorted(D.keys()) != nameL:
                raiseError( 'all the dictionaries in the generator list'
                            'must have the same keys', line=lineno )
            valL.append( [ D[n] for n in nameL ] )

    check_parameter_names( nameL, lineno )

    for name,vals in iter_name_values( nameL, valL ):
        check_generator_value_types( name, vals, lineno )

    return nameL, valL


def check_generator_instance_names( plist, lineno ):
    ""
    for D in plist:
        for n in D.keys():
            if not allowable_variable(n):
                raiseError( 'invalid parameter name found in generator list:',
                            repr(n), line=lineno )


def check_generator_value_types( name, vals, lineno ):
    ""
    ns = ni = nf = 0
    for v in vals:
        if type(v) == type(''):
            ns += 1
        elif type(v) == int:
            ni += 1
        elif type(v) == float:
            nf += 1
        else:
            raiseError( "unsupported generator value type for",
                        repr(name)+":", type(v), line=lineno )

    if ns > 0:
        if ni > 0 or nf > 0:
            raiseError( 'not all generator value types are',
                        'the same for', repr(name), line=lineno )
    elif ni > 0:
        if nf > 0:
            raiseError( 'not all generator value types are the',
                        'same for', repr(name), line=lineno )


def run_generator_prog( cmdL, cmdstr, executable ):
    ""
    if os.path.isabs( cmdL[0] ):
        if executable:
            pop = subprocess.Popen( cmdL, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE )
        else:
            pycmdL = [sys.executable]+cmdL
            pop = subprocess.Popen( pycmdL, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE )
    else:
        pop = subprocess.Popen( cmdstr, shell=True,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE )

    mjr,mnr = sys.version_info[0],sys.version_info[1]

    if mjr < 3 or ( mjr == 3 and mnr < 3 ):
        out,err = pop.communicate( None )
        x = pop.returncode
    else:
        try:
            out,err = pop.communicate( None, 10 )  # fail after 10 seconds
            x = pop.returncode
        except subprocess.TimeoutExpired:
            pop.kill()
            x = 1

    if mjr > 2:
        out = out.decode() if out else ''
        err = err.decode() if err else ''

    if x != 0:
        raiseError( 'parameter generator command failed:',
                    repr(cmdstr), '\n'+out+'\n'+err )

    return out


def get_generator_program( srcdir, prog ):
    ""
    if os.path.isabs(prog):
        exists = os.path.exists( prog )
    else:
        fn = normpath( pjoin( srcdir, prog ) )
        if os.path.exists(fn):
            prog = fn
            exists = True
        else:
            exists = False

    if platform_windows:
        xcute = False
    else:
        xcute = ( exists and os.access( prog, os.R_OK | os.X_OK ) )

    return prog,xcute


def iter_name_values( nameL, valL ):
    """
    Given a list of names and a list of value "tuples", like

        nameL = [ param_name_1, param_name_2, ... ]

        valueL = [
                   [ p1_v1, p1_v2, ... ],
                   [ p2_v1, p2_v2, ... ],
                   ...
                 ]

    this function returns name and value list pairs, like

        param_name, [ value1, value2, ... ]
    """
    for i,name in enumerate(nameL):
        yield name, [ tup[i] for tup in valL ]


def parse_param_type_map( attr_names, nameL, valL, lineno ):
    ""
    tmap = {}

    if attr_names and 'autotype' in attr_names:

        if 'int' in attr_names or 'float' in attr_names or 'str' in attr_names:
            raiseError( 'cannot mix autotype with int, float or str', line=lineno )

        for name,vals in iter_name_values( nameL, valL ):
            typ = try_cast_to_int_or_float( vals )
            if typ is not None:
                tmap[ name ] = typ

    elif attr_names:
        tL = parse_type_array( attr_names, nameL, lineno )

        if len(tL) > 0:
            for i,nv in enumerate( iter_name_values( nameL, valL ) ):
                name,vals = nv
                typ = tL[i]
                if values_cast_to_type( typ, vals ):
                    tmap[ name ] = typ
                else:
                    raiseError( 'cannot cast all', repr(name), 'values to',
                                typ, line=lineno )

    return tmap


def parse_type_array( attr_names, nameL, lineno ):
    ""
    tL = extract_types_from_attrs( attr_names )

    if len(tL) > len(nameL):
        raiseError( 'more type specifications than parameter names', line=lineno )

    if len(tL) == 1:
        # a single type specifier is applied to all parameters
        typ = tL[0]
        tL = [ typ for _ in range(len(nameL)) ]

    elif len(tL) > 0 and len(tL) != len(nameL):
        raiseError( 'the list of types must be length one or match',
                    'the number of parameter names', line=lineno )

    return tL


def extract_types_from_attrs( attr_names ):
    ""
    tL = []
    for n in attr_names:
        if n in ['str','int','float']:
            tL.append( eval(n) )
    return tL


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

        if pset.getStagedGroup() is not None:
            raiseError( 'only one parameterize can be staged', line=lineno )

        insert_staging_into_names_and_values( nameL, valL )

        return True

    return False


def insert_staging_into_names_and_values( names, values ):
    ""
    names[:] = [ 'stage' ] + names
    values[:] = [ [str(i)]+vL for i,vL in enumerate(values, start=1) ]


def check_parameter_names( name_list, lineno ):
    ""
    for v in name_list:
        if not allowable_variable(v):
            raiseError( 'invalid parameter name:', repr(v), line=lineno )


def check_parameter_values( name_list, values, lineno ):
    ""
    for name,vals in iter_name_values( name_list, values ):
        for v in vals:
            if not allowable_word(v):
                raiseError( 'invalid parameter value for name',
                            repr(name)+':', repr(v), line=lineno )


def check_special_parameters( names, values, lineno ):
    ""
    for name, vals in iter_name_values( names, values ):
        if name in [ 'np', 'ndevice', 'nnode' ]:
            for val in vals:
                try:
                    ival = int(val)
                except Exception:
                    ival = None

                if ival is None or ival < 0:
                    raiseError( 'the parameter', repr(name),
                                'must be a non-negative integer:',
                                repr(val), line=lineno )


def param_name_and_value_strings( spec_value, lineno ):
    ""
    L = spec_value.split( '=', 1 )
    if len(L) < 2:
        raiseError( "invalid parameterize specification", line=lineno )

    namestr,valuestr = L

    if not namestr.strip():
        raiseError( "no parameter name given", line=lineno )

    if not valuestr.strip():
        raiseError( "no parameter value(s) given", line=lineno )

    return namestr, valuestr


def parse_param_names_and_values( spec_value, force_params, lineno ):
    ""
    namestr,valuestr = param_name_and_value_strings( spec_value, lineno )

    nameL = [ n.strip() for n in namestr.strip().split(',') ]

    check_parameter_names( nameL, lineno )

    if len(nameL) == 1:
        valL = parse_param_values( nameL[0], valuestr, force_params )
    else:
        valL = parse_param_group_values( nameL, valuestr, lineno )

    check_parameter_values( nameL, valL, lineno )
    check_special_parameters( nameL, valL, lineno )

    check_forced_group_parameter( force_params, nameL, lineno )

    return nameL, valL


def parse_param_values( param_name, value_string, force_params ):
    """
    The 'force_params' argument is a dictionary mapping parameter names
    to a list of values (multiple values can be forced onto a parameter).

        - np=1 2    force=5      ->  np=5 5  (dups get removed if not staged)
        - np=1 2    force=5 6    ->  np=5 6
        - np=1 2 3  force=5 6    ->  np=5 6 5 (dups get removed if not staged)
        - np=1 2    force=5 6 7  ->  np=5 6 7

    Keep same number of values as 'value_string' if less than or equal to
    the list in 'force_params'. May need to repeat the forced values.

    Increase the number of values to equal the list in 'force_params' if the
    'value_string' values has smaller length.
    """
    vals = value_string.strip().split()

    if force_params is not None and param_name in force_params:

        force_vals = force_params[ param_name ]
        new_len = max( len(vals), len(force_vals) )

        vals = []
        j = 0
        for i in range(new_len):
            vals.append( force_vals[j] )
            j = (j+1)%len(force_vals)

    return [ [v] for v in vals ]


spaced_comma_pattern = re.compile( '[\t ]*,[\t ]*' )

def parse_param_group_values( name_list, value_string, lineno ):
    ""
    compressed_string = spaced_comma_pattern.sub( ',', value_string.strip() )

    vL = []
    for s in compressed_string.split():

        gL = s.split(',')
        if len(gL) != len(name_list):
            raiseError( 'malformed parameter list', repr(s), line=lineno )

        vL.append( gL )

    check_parameter_values( name_list, vL, lineno )
    check_special_parameters( name_list, vL, lineno )

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
                raiseError( 'malformed "rename" file list:', repr(s),
                            line=spec.lineno )
            fsrc,fdst = L
            if os.path.isabs(fsrc) or os.path.isabs(fdst):
                raiseError( 'file names cannot be absolute paths',
                            line=spec.lineno )
            fL.append( [fsrc,fdst] )
        
        variable_expansion( tname, platname, paramD, fL )

        flist.extend( fL )

    else:
        fL = val.split()
        
        for f in fL:
            if os.path.isabs(f):
                raiseError( 'file names cannot be absolute paths',
                            line=spec.lineno )
        
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
            raiseError( "invalid 'expect' value", repr(exp), line=lineno )

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
                raiseError( 'bad testname expression', repr(tval)+':', str(e),
                            line=lineno )

    return ok
