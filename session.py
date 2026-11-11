"""Document-owned state; never contains a window, sidebar or file monitor."""
from dataclasses import dataclass,field
from pathlib import Path
from model import blank

@dataclass
class DocumentSession:
    path: Path | None=None
    saved_stamp: tuple | None=None
    saved_doc: dict=field(default_factory=blank)
    save_problem: str | None=None
    history: list=field(default_factory=list)
    history_index: int=-1
    navigation: list=field(default_factory=list)
    navigation_index: int=-1
    zoom: float=1.0
    pinned: bool=False
    editing: bool=True

    def append_history(self,document,max_entries=60,max_bytes=32*1024*1024):
        """Bound structural history; immutable embedded image strings remain shared."""
        self.history=self.history[:self.history_index+1]+[document]
        def cost(doc):
            return len(doc['text'])*4+len(doc['spans'])*256+len(doc['images'])*256+sum(len(v)*4+64 for t in doc.get('tables',[]) for row in t['cells'] for v in row)
        def total_cost():
            images={id(image['src']):image['src'] for doc in self.history for image in doc['images']}
            return sum(cost(doc) for doc in self.history)+sum(len(src) for src in images.values())
        while len(self.history)>1 and (len(self.history)>max_entries or total_cost()>max_bytes):
            self.history.pop(0)
        self.history_index=len(self.history)-1
