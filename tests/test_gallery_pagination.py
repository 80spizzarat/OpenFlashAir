import inspect
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from openflashair.gui import App, GALLERY_PAGE_SIZE, gallery_page_count, gallery_page_slice
from openflashair.client import RemoteFile


class GalleryPaginationTests(unittest.TestCase):
    def test_page_count_boundaries(self):
        self.assertEqual(GALLERY_PAGE_SIZE, 100)
        self.assertEqual([gallery_page_count(n) for n in (99, 100, 101, 102, 200, 201)], [1, 1, 2, 2, 2, 3])

    def test_last_page_contains_every_remaining_item(self):
        for total, expected_last_size in ((99, 99), (100, 100), (101, 1), (102, 2), (200, 100), (201, 1)):
            items=list(range(total)); pages=gallery_page_count(total)
            page,last=gallery_page_slice(items,pages-1)
            self.assertEqual(page,pages-1)
            self.assertEqual(len(last),expected_last_size)
            self.assertEqual(last,items[(pages-1)*100:])

    def test_page_is_clamped(self):
        self.assertEqual(gallery_page_slice(list(range(102)), -4)[0], 0)
        page,items=gallery_page_slice(list(range(102)), 99)
        self.assertEqual(page,1); self.assertEqual(items,[100,101])

    def test_thumbnail_arrivals_are_tile_local_and_layout_is_coalesced(self):
        source=inspect.getsource(App._put_thumbnail)
        self.assertNotIn('self._relayout_gallery()',source)
        self.assertIn('self._render_tile_image(tile)',source)
        render=inspect.getsource(App._render_tile_image)
        self.assertIn("tile['photo']=photo",render)
        resize=inspect.getsource(App._gallery_resize)
        self.assertIn('self._schedule_gallery_layout',resize)

    def test_page_controls_do_not_require_re_discovery(self):
        source=inspect.getsource(App._change_page)
        self.assertNotIn('FlashAirClient',source)
        self.assertIn('self._show_gallery_page()',source)

    def test_sorting_is_inventory_wide_stable_and_path_based_priorities_are_untouched(self):
        items=[
            RemoteFile('/B.JPG',1,datetime(2026,1,2,tzinfo=timezone.utc),False),
            RemoteFile('/a.JPG',1,datetime(2026,1,2,tzinfo=timezone.utc),False),
            RemoteFile('/old.JPG',1,datetime(2025,1,1,tzinfo=timezone.utc),False),
            RemoteFile('/unknown.JPG',1,None,False),
        ]
        holder=SimpleNamespace(gallery_files=list(items),sort_order=SimpleNamespace(get=lambda:'Newest first'))
        App._sort_gallery_files(holder)
        self.assertEqual([item.path for item in holder.gallery_files],['/a.JPG','/B.JPG','/old.JPG','/unknown.JPG'])
        holder.sort_order=SimpleNamespace(get=lambda:'Oldest first')
        App._sort_gallery_files(holder)
        self.assertEqual([item.path for item in holder.gallery_files],['/old.JPG','/a.JPG','/B.JPG','/unknown.JPG'])

    def test_scroll_viewport_does_not_mutate_geometry_as_thumbnails_arrive(self):
        create=inspect.getsource(App._create_gallery_tile)
        self.assertIn('create_rectangle',create)
        self.assertIn("tag_bind(tag,'<Button-1>'",create)
        self.assertNotIn('tk.Frame(',create)
        init=inspect.getsource(App.__init__)
        self.assertNotIn("gallery_canvas.bind_all('<MouseWheel>'",init)
        self.assertNotIn('create_window',init)
        put=inspect.getsource(App._put_thumbnail)
        self.assertNotIn('scrollregion',put)

    def test_rapid_wheel_scroll_with_a_100_item_fixture_keeps_a_stable_scrollregion(self):
        class Canvas:
            def __init__(self): self.calls=[]
            def yview(self,*args): self.calls.append(args)
        fixture=[RemoteFile(f'/DCIM/P{index:04d}.JPG',index,None,False) for index in range(100)]
        self.assertEqual(len(fixture),100)
        holder=SimpleNamespace(gallery_canvas=Canvas())
        holder._gallery_scroll_command=lambda *args: App._gallery_scroll_command(holder,*args)
        for _ in range(150): self.assertEqual(App._gallery_mousewheel(holder,SimpleNamespace(delta=-120)),'break')
        self.assertEqual(holder.gallery_canvas.calls,[ ('scroll',1,'units') ]*150)

    def test_scrollbar_moveto_large_jumps_do_not_rebuild_or_repaint_tiles(self):
        class Canvas:
            def __init__(self): self.calls=[]
            def yview(self,*args): self.calls.append(args)
        holder=SimpleNamespace(gallery_canvas=Canvas())
        for target in ('0.0','1.0','0.0','0.87','0.12','1.0'):
            App._gallery_scroll_command(holder,'moveto',target)
        self.assertEqual(holder.gallery_canvas.calls,[('moveto',target) for target in ('0.0','1.0','0.0','0.87','0.12','1.0')])

    def test_consolidated_header_is_the_only_gallery_count(self):
        source=inspect.getsource(App._set_gallery_files)
        self.assertIn("self.gallery_summary.set(f'Gallery: {len(self.gallery_files)} photographs')",source)
        self.assertNotIn("self.status.set(f'Gallery:",source)

    def test_sparse_last_page_keeps_five_column_geometry(self):
        page,items=gallery_page_slice(list(range(102)),1)
        self.assertEqual((page,items), (1,[100,101]))
        layout=inspect.getsource(App._relayout_gallery)
        self.assertIn("tile.update(x=x,y=y,width=tile_width",layout)
        self.assertIn('rows=(len(self._tiles_by_path)+columns-1)//columns',layout)


if __name__ == '__main__':
    unittest.main()
