import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from openflashair.client import FlashAirClient, FlashAirError, RemoteFile
from openflashair.engine import SyncEngine, SyncOptions


class Response:
    def __init__(self, chunks): self.chunks=iter(chunks)
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size):
        value=next(self.chunks,b'')
        if isinstance(value,Exception): raise value
        return value


class ChunkTransferTests(unittest.TestCase):
    def test_interrupted_attempt_restarts_without_mixing_bytes(self):
        client=FlashAirClient('http://example.invalid/',retries=2); updates=[]
        with patch('openflashair.client.urlopen',side_effect=[Response([b'ab',URLError('reset')]),Response([b'ab',b'cd'])]), patch('openflashair.client.time.sleep'):
            data=client.fetch('/a b.JPG',lambda n,attempt: updates.append((n,attempt)))
        self.assertEqual(data,b'abcd')
        self.assertEqual(updates,[(0,1),(2,1),(0,2),(2,2),(4,2)])

    def test_exhausted_retry_does_not_create_destination(self):
        item=RemoteFile('/a.JPG',4,None,False)
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); client=FlashAirClient('http://example.invalid/',retries=2)
            with patch('openflashair.client.urlopen',side_effect=[Response([b'ab',TimeoutError()]),Response([b'c',URLError('reset')])]), patch('openflashair.client.time.sleep'):
                engine=SyncEngine(client,base/'out',base/'stage')
                result=engine.download_files([item],SyncOptions.photos()); engine.close()
            self.assertEqual(result.failed,1)
            self.assertFalse(any((base/'out').iterdir()))
            self.assertFalse(list((base/'stage').glob('*.part')))

    def test_exhausted_fetch_raises(self):
        with patch('openflashair.client.urlopen',side_effect=URLError('offline')), patch('openflashair.client.time.sleep'):
            with self.assertRaises(FlashAirError): FlashAirClient(retries=2).fetch('/a.JPG')

    def test_retry_commits_only_verified_complete_bytes_and_skips_repeat(self):
        item=RemoteFile('/a.JPG',4,None,False)
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); client=FlashAirClient('http://example.invalid/',retries=2)
            with patch('openflashair.client.urlopen',side_effect=[Response([b'bad',TimeoutError()]),Response([b'ab',b'cd'])]), patch('openflashair.client.time.sleep'):
                engine=SyncEngine(client,base/'out',base/'stage')
                self.assertEqual(engine.download_files([item],SyncOptions.photos()).downloaded,1)
                self.assertEqual((base/'out'/'a.JPG').read_bytes(),b'abcd')
                self.assertEqual(engine.download_files([item],SyncOptions.photos()).skipped,1)
                engine.close()
            self.assertFalse(list((base/'stage').glob('*.part')))
