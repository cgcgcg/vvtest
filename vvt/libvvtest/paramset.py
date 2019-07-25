#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os


class ParameterSet:
    """
    A set of parameter names mapped to their values.  Such as

        paramA = [ 'Aval1', 'Aval2', ... ]
        paramB = [ 'Bval1', 'Bval2', ... ]
        ...

    A set of instances is the cartesian product of the values (an instance
    is a dictionary of param_name=param_value).  Such as

        { 'paramA':'Aval1', 'paramB':'Bval1', ... }
        { 'paramA':'Aval1', 'paramB':'Bval2', ... }
        { 'paramA':'Aval2', 'paramB':'Bval1', ... }
        { 'paramA':'Aval2', 'paramB':'Bval2', ... }
        ...

    Parameter names can be grouped, such as

        paramC,paramD = [ ('Cval1','Dval1'), ('Cval2','Dval2'), ... ]

    The cartesian product does NOT apply to values within a group (the values
    are taken verbatim).
    """

    def __init__(self):
        ""
        self.params = {}
        self.staged = None
        self.instances = []

    def addParameter(self, name, value_list):
        """
        Such as 'myparam', ['value1', 'value2'].
        """
        names = (name,)
        values_list = [ [val] for val in value_list ]
        self.addParameterGroup( names, values_list )

    def addParameterGroup(self, names, values_list, staged=False):
        """
        Such as ('paramA','paramB'), [ ['A1','B1'], ['A2','B2'] ].
        """
        self.params[ tuple(names) ] = list(values_list)
        if staged:
            self.staged = list( names )
        self._constructInstances()

    def getStagedGroup(self):
        ""
        return self.staged

    def applyParamFilter(self, param_filter_function):
        """
        The param_filter_function() function is called to filter down the set
        of parameter instances.  The list returned with getInstances() will
        reflect the filtering.
        """
        self._constructInstances()

        newL = []
        for instD in self.instances:
            if param_filter_function( instD ):
                newL.append( instD )

        self.instances = newL

    def getInstances(self):
        """
        Return the list of dictionary instances, which contains all
        combinations of the parameter values (the cartesian product).
        """
        return self.instances

    def getParameters(self):
        """
        Returns the filtered parameters in a dictionary, such as
            {
              ('paramA',) : [ ['a1'], ['a2'], ... ] ],
              ('paramB', paramC') : [ ['b1','c1'], ['b2','c2'], ... ] ],
            }
        """
        instL = self.getInstances()
        filtered_params = {}
        for nameT,valuesL in self.params.items():
            L = []
            for valL in valuesL:
                if contains_parameter_name_value( instL, nameT, valL ):
                    L.append( valL )
            filtered_params[ nameT ] = L

        return filtered_params

    def _constructInstances(self):
        ""
        if len(self.params) == 0:
            self.instances = []

        else:
            instL = [ {} ]  # a seed for the accumulation algorithm
            for names,values in self.params.items():
                instL = accumulate_parameter_group_list( instL, names, values )
            self.instances = instL


###########################################################################

def contains_parameter_name_value( instances, nameT, valL ):
    """
    Returns true if the given parameter names are equal to the given values
    for at least one instance dictionary in the 'instances' list.
    """
    ok = False
    for D in instances:
        cnt = 0
        for n,v in zip( nameT, valL ):
            if D[n] == v:
                cnt += 1
        if cnt == len(nameT):
            ok = True
            break

    return ok


def accumulate_parameter_group_list( Dlist, names, values_list ):
    """
    Performs a cartesian product with an existing list of dictionaries and a
    new name=value set.  For example, if

        Dlist = [ {'A':'a1'} ]
        names = ('B',)
        values_list = [ ['b1'], ['b2'] ]

    then this list is returned

        [ {'A':'a1', 'B':'b1'},
          {'A':'a1', 'B':'b2'} ]

    An example using a group:

        Dlist = [ {'A':'a1'}, {'A':'a2'} ]
        names = ('B','C')
        values_list = [ ['b1','c1'], ['b2','c2'] ]

    would yield

        [ {'A':'a1', 'B':'b1', 'C':'c1'},
          {'A':'a1', 'B':'b2', 'C':'c2'},
          {'A':'a2', 'B':'b1', 'C':'c1'},
          {'A':'a2', 'B':'b2', 'C':'c2'} ]
    """
    newL = []
    for values in values_list:
        L = add_parameter_group_to_list_of_dicts( Dlist, names, values )
        newL.extend( L )
    return newL


def add_parameter_group_to_list_of_dicts( Dlist, names, values ):
    """
    Copies and returns the given list of dictionaries but with
    names[0]=values[0] and names[1]=values[1] etc added to each.
    """
    assert len(names) == len(values)
    N = len(names)

    new_Dlist = []

    for D in Dlist:
        newD = D.copy()
        for i in range(N):
            newD[ names[i] ] = values[i]
        new_Dlist.append( newD )

    return new_Dlist
