"""Per-discovery property snapshot; no cross-run cache or partial success."""
from contextlib import contextmanager
import time
from .child_process import phase_progress


@contextmanager
def stage(name, counters=None):
    before = counters.requests if counters else 0
    started = time.monotonic()
    phase_progress(name)
    stats = {}
    try:
        yield stats
    except BaseException:
        phase_progress(name, time.monotonic()-started, failed=True,
                       requests=counters.requests-before if counters else None, **stats)
        raise
    else:
        phase_progress(name, time.monotonic()-started,
                       requests=counters.requests-before if counters else None, **stats)


class InventoryReads:
    def __init__(self, service):
        self.stub = getattr(service, '_stub', None)
        self.values = {}
        self.requests = 0

    @staticmethod
    def key(obj, name):
        return (type(obj), obj._moId, name)

    def __enter__(self):
        if self.stub is None: return self
        self.accessor = self.stub.InvokeAccessor
        self.method = self.stub.InvokeMethod
        self.old = {k:self.stub.__dict__.get(k) for k in ('InvokeAccessor','InvokeMethod')}
        def method(*args, **kwargs):
            self.requests += 1
            return self.method(*args, **kwargs)
        def accessor(obj, info):
            key = self.key(obj, info.name)
            if key not in self.values:
                self.values[key] = self.accessor(obj, info)
            return self.values[key]
        self.stub.InvokeMethod = method
        self.stub.InvokeAccessor = accessor
        return self

    def __exit__(self, *_):
        if self.stub is not None:
            for key, value in self.old.items():
                if value is None: delattr(self.stub, key)
                else: setattr(self.stub, key, value)
        self.values.clear()

    def virtual_machines(self, collector, objects):
        if self.stub is None: return
        from pyVmomi import vim, vmodl
        pc = vmodl.query.PropertyCollector
        paths = ('name','config','guest','runtime','summary')
        # Bounded request size, all continuation pages consumed, no retry/fallback
        # to an incomplete set when ESXi reports a fault or omits an object.
        objects = list({self.key(obj, ''):obj for obj in objects}.values())
        for start in range(0, len(objects), 100):
            batch = objects[start:start+100]
            pending = {self.key(obj, '') for obj in batch}
            spec = pc.FilterSpec(objectSet=[pc.ObjectSpec(obj=obj) for obj in batch],
                propSet=[pc.PropertySpec(type=vim.VirtualMachine, all=False, pathSet=list(paths))])
            page = collector.RetrievePropertiesEx(specSet=[spec], options=pc.RetrieveOptions(maxObjects=100))
            tokens = set()
            while page is not None:
                for row in page.objects:
                    key = self.key(row.obj, '')
                    if key not in pending: raise ValueError('Invalid ESXi property result')
                    pending.remove(key)
                    if row.missingSet: raise RuntimeError('ESXi property retrieval incomplete')
                    values = {prop.name:prop.val for prop in row.propSet}
                    if not set(paths).issubset(values): raise RuntimeError('ESXi property retrieval incomplete')
                    for name in paths: self.values[self.key(row.obj, name)] = values[name]
                token = page.token
                if not token: break
                if token in tokens: raise RuntimeError('ESXi property pagination repeated')
                tokens.add(token)
                page = collector.ContinueRetrievePropertiesEx(token=token)
            if pending: raise RuntimeError('ESXi inventory retrieval incomplete')
