# -*- coding: utf-8 -*-
# This file is part of Dyko
# Copyright © 2008-2010 Kozea
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kalamar.  If not, see <http://www.gnu.org/licenses/>.

"""
Request
=======

Kalamar request objects and operator helpers.

"""

from operator import eq, ne, gt, ge, lt, le
from abc import ABCMeta, abstractmethod


OPERATORS = {"=": eq, "!=": ne, ">": gt, ">=": ge, "<": lt, "<=": le}
REVERSE_OPERATORS = dict((value, key) for key, value in OPERATORS.items())


class OperatorNotAvailable(KeyError):
    """Operator is unknown or not managed."""


def make_request_property(property_name):
    """Return an instance of RequestProperty
    
    >>> make_request_property("a")
    a
    >>> make_request_property("a.id")
    a.id
    
    """
    properties = property_name.split(".")
    properties.reverse()
    req_prop = RequestProperty(properties[0])
    for prop in properties[1:]:
        req_prop = ComposedRequestProperty(prop, req_prop)
    return req_prop


def make_request(request):
    """Convert a ``request`` to a Request object.

    TODO: describe syntaxic sugar.

    """
    if not request:
        # Empty request: always true.
        return And()
    elif isinstance(request, Request):
        return request
    elif hasattr(request, "items") and callable(request.items):
        # If it looks like a dict and smells like a dict, it is a dict.
        return And(*(Condition(key, "=", value) 
                     for key, value in request.items()))


def normalize(properties, request):
    """Convert the condition values.
    
    Raises an exception if the property is not supplied or if it can't be cast.

    """
    def _inner_normalize(request):
        """Recursively normalize ``request``."""
        if isinstance(request, (And, Or)):
            requests = (_inner_normalize(sub_request)
                        for sub_request in request.sub_requests)
            return request.__class__(*requests)
        elif isinstance(request, Not):
            return Not(_inner_normalize(request.sub_request))
        elif isinstance(request, Condition):
            root = request.property.name
            if root not in properties:
                raise KeyError(
                    "This access point has no %r property." % root)
            if request.property.child_property:
                return request
            else:
                value = properties[root].cast((request.value,))[0]
                return Condition(request.property.name, request.operator, value)
    return _inner_normalize(make_request(request)).simplify()


class Request(object):
    """Abstract class for kalamar requests."""
    __metaclass__ = ABCMeta
    _hash_attributes = ""
    
    @abstractmethod
    def test(self, item):
        """Return if ``item`` matches the request."""
        raise NotImplementedError

    def __eq__(self, other):
        return isinstance(other, self.__class__) and \
            self.__hash__() == other.__hash__()

    def __hash__(self):
        return hash(tuple(
                getattr(self, attr) for attr in self._hash_attributes.split()))

    @property
    @abstractmethod
    def properties_tree(self):
        """Tree of properties concerned by this request.
        
        >>> cond1 = Condition("test.foo", "=", "a")
        >>> cond2 = Condition("test.bar.baz", "=", "b")
        >>> cond3 = Condition("test.bar.bazbaz", "=", "b")
        >>> And(cond1, cond2, cond3).properties_tree
        {'test': {'foo': foo, 'bar': {'bazbaz': bazbaz, 'baz': baz}}}

        """
        raise NotImplementedError

    def simplify(self):
        """Return a simplified equivalent request."""
        return self


class Condition(Request):
    """Container for ``(property_name, operator, value)``."""
    _hash_attributes = "property operator value"

    def __init__(self, property_name=None, operator="=", value=True):
        super(Condition, self).__init__()
        self.operator_func = OPERATORS[operator]
        self.property = make_request_property(property_name)
        self.operator = operator
        self.value = value

    def __repr__(self):
        return "%s(%r, %r, %r)" % (
            self.__class__.__name__, self.property, self.operator, self.value)
    
    def test(self, item):
        """Return if ``item`` matches the request."""
        return self.operator_func(self.property.get_value(item), self.value)

    @property
    def properties_tree(self):
        def inner_properties(prop):
            """Recursively get children properties of ``prop``."""
            if prop.child_property:
                return {prop.name: inner_properties(prop.child_property)}
            else:
                return {prop.name: prop}
        return inner_properties(self.property)


class RequestProperty(object):
    """Property from an item.

    This object should be used to retrieve a property value from an item.

    """
    def __init__(self, name):
        self.name = name
        self.child_property = None

    def get_value(self, item):
        """Retrieve the value from this property from an item."""
        return item[self.name] if item else None

    def __repr__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and \
            self.__hash__() == other.__hash__()




class ComposedRequestProperty(RequestProperty):
    """Nested property from an item.

    A nested property is of the form ``foo.bar.baz``.
    
    """
    def __init__(self, name, child_property, inner=True):
        super(ComposedRequestProperty, self).__init__(name)
        self.name = name
        self.child_property = child_property
        self.inner = inner

    def get_value(self, item):
        return self.child_property.get_value(item[self.name])

    def __repr__(self):
        return "%s.%r" % (self.name, self.child_property)

    def __hash__(self):
        return hash((hash(self.name), hash(self.child_property)))


class _AndOr(Request):
    """Super class for And and Or that holds identical behavior."""
    __metaclass__ = ABCMeta
    _hash_attributes = "sub_requests __class__"

    def __init__(self, *sub_requests):
        super(_AndOr, self).__init__()
        # A frozenset in unordered: And(a, b) == And(b, a)
        # and its elements are unique: And(a, a) = And(a)
        self.sub_requests = frozenset(sub_requests)
    
    def __repr__(self):
        return "%s(%s)" % (
            self.__class__.__name__,
            ", ".join(repr(request) for request in self.sub_requests))
    
    @abstractmethod
    def test(self, item):
        raise NotImplementedError

    @property
    def properties_tree(self):
        def merge_properties(tree_a, tree_b):
            """Merge two properties trees into one."""
            for name, tree_a_values in tree_a.items():
                tree_b_values = tree_b.setdefault(name, {})
                if isinstance(tree_b_values, dict):
                    tree_b[name] = merge_properties(tree_b_values, tree_a_values)
            return tree_b
        return reduce(merge_properties, [
                sub.properties_tree for sub in self.sub_requests] or [{}])

    def flatten(self):
        """Return a generator of flat sub requests."""
        for sub_request in self.sub_requests:
            if type(sub_request) is type(self):
                for sub_sub in sub_request.flatten():
                    yield sub_sub
            else:
                yield sub_request

    def simplify(self):
        new_sub_requests = set(request.simplify() for request in self.flatten())
        if len(new_sub_requests) == 1:
            # And(a) == a
            return new_sub_requests.pop()
        return type(self)(*new_sub_requests)


class And(_AndOr):
    """True if all given requests are true."""
    def test(self, item):
        return all(request.test(item) for request in self.sub_requests)


class Or(_AndOr):
    """True if at least one given requests is true."""
    def test(self, item):
        return any(request.test(item) for request in self.sub_requests)


class Not(Request):
    """Negate a request."""
    _hash_attributes = "sub_request __class__"

    def __init__(self, sub_request):
        super(Not, self).__init__()
        self.sub_request = sub_request
    
    def __repr__(self):
        return "Not(%r)" % self.sub_request

    def test(self, item):
        return not self.sub_request.test(item)

    @property
    def properties_tree(self):
        return self.sub_request.properties_tree

    def simplify(self):
        if isinstance(self.sub_request, Not):
            # Not(Not(a)) == a
            return self.sub_request.sub_request.simplify()
        else:
            return Not(self.sub_request.simplify())
