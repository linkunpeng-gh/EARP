"""Test plugin classes for sandbox tests — must be in a real file for inspect.getsource()."""

from earp_sdk_plugin import Plugin


class CalcPlugin(Plugin):
    name = "calc"
    extension_point = ""
    permissions = []

    def add(self, a, b):
        return {"sum": a + b}


class SlowPlugin(Plugin):
    name = "slow"
    extension_point = ""
    permissions = []

    def compute(self):
        import time
        time.sleep(10)
        return "done"


class BuggyPlugin(Plugin):
    name = "buggy"
    extension_point = ""
    permissions = []

    def crash(self):
        raise ValueError("boom")


class ListPlugin(Plugin):
    name = "list"
    extension_point = ""
    permissions = []

    def items(self):
        return [1, 2, 3]


class StrPlugin(Plugin):
    name = "str"
    extension_point = ""
    permissions = []

    def greet(self, name):
        return f"Hello, {name}"


class NonePlugin(Plugin):
    name = "none"
    extension_point = ""
    permissions = []

    def nothing(self):
        return None
