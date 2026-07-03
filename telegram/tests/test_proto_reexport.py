"""
Regression test for #125: hannah_telegram.proto.__init__ patches every
scope-split *_pb2 module's public names onto hannah_pb2 (see the comment in
that file for why). This walks every *_pb2.py file next to __init__.py and
asserts nothing got left out of the patch — not just EventFilter.
"""

import pkgutil

from hannah_telegram import proto
from hannah_telegram.proto import hannah_pb2


def _scope_pb2_modules():
    for _, name, _ in pkgutil.iter_modules(proto.__path__):
        if name.endswith("_pb2") and name != "hannah_pb2":
            yield name


def test_every_scope_module_is_patched_onto_hannah_pb2():
    scope_modules = list(_scope_pb2_modules())
    assert scope_modules, "expected at least one scope-split *_pb2 module"

    missing = []
    for module_name in scope_modules:
        module = __import__(f"hannah_telegram.proto.{module_name}", fromlist=["_"])
        for name in dir(module):
            if name.startswith("_"):
                continue
            if not hasattr(hannah_pb2, name):
                missing.append(f"{module_name}.{name}")

    assert not missing, f"not re-exported onto hannah_pb2: {missing}"
