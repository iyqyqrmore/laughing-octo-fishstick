"""Bounded observe-only CUDA research cadence; independent of broker permissions.

Never calls a Coinbase client, ARM, submit, portfolio/fill mutation or trade policy.
"""
from __future__ import annotations
import time

FIRST_DELAY_S=15
RETRAIN_INTERVAL_S=6*3600
MIN_FREE_DISK_BYTES=256*1024*1024

class GPUResearchSchedule:
    def __init__(self,now=None):
        self.next_due=(time.monotonic() if now is None else float(now))+FIRST_DELAY_S
        self.active=False
        self.runs=0
        self.last_error_type=None
        self.last_finished=None

    def eligible(self,now,*,connected,real_armed,stop_latched,pending_orders,busy,shutdown,free_disk_bytes):
        return bool(float(now)>=self.next_due and not self.active
                    and connected and not real_armed and not stop_latched
                    and not pending_orders and not busy and not shutdown
                    and free_disk_bytes is not None and free_disk_bytes>=MIN_FREE_DISK_BYTES)

    def claim(self,now):
        if self.active or now<self.next_due:return False
        self.active=True
        self.next_due=float(now)+RETRAIN_INTERVAL_S
        return True

    def finish(self,now,exception_type=None):
        self.active=False
        self.runs+=1
        self.last_finished=float(now)
        self.last_error_type=exception_type
        self.next_due=max(self.next_due,float(now)+RETRAIN_INTERVAL_S)
