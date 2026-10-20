import inspect
import unittest

from openflashair.gui import App


class GalleryGeometryTests(unittest.TestCase):
    def test_gallery_uses_classic_visible_scrollbar_with_reserved_column(self):
        source=inspect.getsource(App.__init__)
        self.assertIn('tk.Scrollbar(self.gallery_container',source)
        self.assertIn("width=18",source)
        self.assertIn("columnconfigure(1,minsize=20,weight=0)",source)
        self.assertIn("sticky='ns'",source)


if __name__ == '__main__':
    unittest.main()
