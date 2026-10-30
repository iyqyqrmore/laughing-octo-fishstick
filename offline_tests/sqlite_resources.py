"""Hold real SQLite handles strongly so GC cannot hide fixture resource leaks."""
from contextlib import contextmanager
from unittest.mock import patch
import sqlite3


@contextmanager
def held_sqlite_connections():
    """Regression probe for Windows' refusal to unlink an open database.

    Connections remain real SQLite objects. Strong references make unclosed
    connections visible on Linux too. Final cleanup releases them even when an
    assertion fails; callers must assert .closed before leaving their fixture.
    """
    original=sqlite3.connect;connections=[]
    class Connection(sqlite3.Connection):
        closed=False
        def close(self):
            super().close();self.closed=True
    def connect(*args,**kwargs):
        if 'factory' in kwargs or len(args)>5:
            raise AssertionError('Fixture probe requires the ordinary SQLite connection factory')
        value=original(*args,**kwargs,factory=Connection)
        connections.append(value)
        return value
    try:
        with patch('sqlite3.connect',side_effect=connect):yield connections
    finally:
        for connection in connections:
            if not connection.closed:connection.close()
