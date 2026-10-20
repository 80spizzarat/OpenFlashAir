import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from openflashair.thumbnail import ThumbnailClient

class Response:
 def __init__(self,data): self.data=data
 def __enter__(self): return self
 def __exit__(self,*a): pass
 def read(self): return self.data

class ThumbnailTests(unittest.TestCase):
 def test_jpeg_url_cache_and_invalidation(self):
  c=ThumbnailClient(); calls=[]
  with patch('openflashair.thumbnail.urlopen',lambda url,timeout:(calls.append(url) or Response(b'\xff\xd8x'))):
   self.assertEqual(c.get('/DCIM/a b.JPG',1,'x').state,'ok'); c.get('/DCIM/a b.JPG',1,'x'); c.get('/DCIM/a b.JPG',2,'x')
  self.assertEqual(len(calls),2); self.assertIn('a%20b.JPG',calls[0])
 def test_missing_invalid_timeout_cancel_and_100(self):
  c=ThumbnailClient(concurrency=2)
  with patch('openflashair.thumbnail.urlopen',side_effect=HTTPError('x',404,'',None,None)): self.assertEqual(c.get('/x.JPG').state,'missing')
  with patch('openflashair.thumbnail.urlopen',return_value=Response(b'bad')): self.assertEqual(c.get('/y.JPG').state,'invalid')
  with patch('openflashair.thumbnail.urlopen',side_effect=URLError('timeout')): self.assertEqual(c.get('/z.JPG').state,'error')
  c.cancel(); self.assertEqual(c.get('/q.JPG').state,'cancelled')
  c=ThumbnailClient(concurrency=2)
  with patch('openflashair.thumbnail.urlopen',return_value=Response(b'\xff\xd8x')): self.assertEqual(len(c.fetch_many([(f'/x/{i}.JPG',i,None) for i in range(100)])),100)
