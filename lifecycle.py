"""Cancelable main-loop callbacks owned by a view/controller."""
from gi.repository import GLib

class CallbackOwner:
    def defer(self,callback,*args):
        if getattr(self,'closed',False):return 0
        if not hasattr(self,'deferred_sources'):self.deferred_sources=set()
        source=[0]
        def run():
            self.deferred_sources.discard(source[0])
            if not getattr(self,'closed',False):callback(*args)
            return False
        source[0]=GLib.idle_add(run)
        self.deferred_sources.add(source[0])
        return source[0]

    def cancel_deferred(self):
        sources=getattr(self,'deferred_sources',set())
        if getattr(self,'search_pending',0) in sources:self.search_pending=0
        for source in sources:GLib.source_remove(source)
        self.deferred_sources=set()
