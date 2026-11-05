"""SDK log redaction without importing an execution controller."""
import logging

class _RedactedSDKLog(logging.Filter):
    def filter(self,record):
        record.msg='Coinbase SDK operation reported a failure; private response omitted'
        record.args=();record.exc_info=None;record.exc_text=None
        return True

def protect_sdk_logs():
    logger=logging.getLogger('coinbase.RESTClient')
    if not any(isinstance(f,_RedactedSDKLog) for f in logger.filters):logger.addFilter(_RedactedSDKLog())
