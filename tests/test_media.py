import io
import inspect
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ExifTags

from openflashair.gui import App, center_popup
from openflashair.media import decode_image, format_exif_fields, local_image_metadata, local_capture_time


class MediaTests(unittest.TestCase):
    def test_capture_time_sub_ifd_and_missing_exif(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.jpg'; image=Image.new('RGB',(10,10))
            exif=Image.Exif(); exif[ExifTags.IFD.Exif]={36867:'2026:10:17 12:34:56'}
            image.save(path,exif=exif)
            self.assertEqual(local_capture_time(path),'2026:10:17 12:34:56')
            image.save(path)
            self.assertEqual(local_capture_time(path),'')
            self.assertEqual(local_capture_time(Path(directory)/'missing.jpg'),'')
    def test_decode_image_detaches_from_source_stream(self):
        source=Image.new('RGB',(24,16),(12,34,56)); buffer=io.BytesIO(); source.save(buffer,format='JPEG')
        decoded=decode_image(buffer.getvalue())
        self.assertEqual(decoded.size,(24,16))
        self.assertEqual(decoded.mode,'RGB')

    def test_local_metadata_reads_available_exif_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'camera.jpg'; image=Image.new('RGB',(40,30),(1,2,3)); exif=Image.Exif(); exif[36867]='2026:10:17 12:34:56'; exif[272]='Synthetic Camera'; image.save(path,format='JPEG',exif=exif)
            metadata=local_image_metadata(path)
        self.assertEqual(metadata['dimensions'],'40 × 30')
        self.assertEqual(metadata['capture_time'],'2026:10:17 12:34:56')
        self.assertEqual(metadata['camera_model'],'Synthetic Camera')

    def test_extended_exif_formats_rationals_for_readability(self):
        fields=format_exif_fields({34855:800,33437:(56,10),33434:(1,125),37386:(42,1),37380:(2,3),41986:1,37385:1,42036:'Test Lens 42mm'})
        self.assertEqual(fields['iso'],'ISO 800')
        self.assertEqual(fields['aperture'],'f/5.6')
        self.assertEqual(fields['shutter_speed'],'1/125 sec')
        self.assertEqual(fields['focal_length'],'42 mm')
        self.assertEqual(fields['exposure_compensation'],'+0.7 EV')
        self.assertEqual(fields['exposure_mode'],'Manual exposure')
        self.assertEqual(fields['flash_status'],'Flash fired')
        self.assertEqual(fields['lens_model'],'Test Lens 42mm')

    def test_extended_exif_missing_and_invalid_values_are_not_invented(self):
        fields=format_exif_fields({34855:'bad',33437:(1,0),33434:0,37386:None,37380:'bad',41986:99,37385:'bad',42036:'  '})
        self.assertEqual(fields,{'iso':'','aperture':'','focal_length':'','exposure_compensation':'','lens_model':'','shutter_speed':'','exposure_mode':'','flash_status':''})

    def test_local_metadata_reads_exposure_values_from_exif_sub_ifd(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sub-ifd.jpg'; image=Image.new('RGB',(40,30),(1,2,3)); exif=Image.Exif()
            exif[ExifTags.IFD.Exif]={34855:320,33437:(16,1),33434:(1,250),37386:(14,1),37380:(0,1),34850:1,37385:9,42036:'OLYMPUS Test Lens'}
            image.save(path,format='JPEG',exif=exif)
            metadata=local_image_metadata(path)
        self.assertEqual(metadata['iso'],'ISO 320')
        self.assertEqual(metadata['aperture'],'f/16')
        self.assertEqual(metadata['shutter_speed'],'1/250 sec')
        self.assertEqual(metadata['focal_length'],'14 mm')
        self.assertEqual(metadata['exposure_compensation'],'+0.0 EV')
        self.assertEqual(metadata['exposure_mode'],'Manual exposure')
        self.assertEqual(metadata['flash_status'],'Flash fired')
        self.assertEqual(metadata['lens_model'],'OLYMPUS Test Lens')

    def test_canvas_click_contract_keeps_selection_and_preview_distinct(self):
        create=inspect.getsource(App._create_gallery_tile)
        self.assertIn("tag_bind(tag,'<Button-1>'",create)
        self.assertIn("tag_bind(tag,'<Double-Button-1>'",create)
        self.assertIn("tag_bind(metadata_tag,'<Button-1>'",create)
        single=inspect.getsource(App._tile_single_click)
        double=inspect.getsource(App._tile_double_click)
        self.assertIn('self.after(220',single)
        self.assertIn('self.after_cancel',double)
        self.assertIn('self.open_preview(path)',double)

    def test_preview_and_metadata_are_read_only_paths(self):
        preview=inspect.getsource(App.open_preview)
        metadata=inspect.getsource(App.show_metadata)
        self.assertIn('Card thumbnail preview (not downloaded)',preview)
        self.assertNotIn('SyncEngine',preview)
        self.assertNotIn('.fetch(',preview)
        self.assertIn('local_image_metadata',metadata)

    def test_metadata_variables_and_popup_positioning_are_retained_and_applied(self):
        metadata=inspect.getsource(App.show_metadata)
        preview=inspect.getsource(App.open_preview)
        self.assertIn('dialog._metadata_values=values',metadata)
        self.assertIn('dialog.minsize(620,450)',metadata)
        self.assertIn('_position_metadata_dialog(dialog,owner,identity)',metadata)
        self.assertIn('center_popup(dialog,owner)',preview)
        helper=inspect.getsource(center_popup)
        self.assertIn('MonitorFromPoint',helper)
        self.assertIn('rcWork',helper)

    def test_card_thumbnail_fit_can_enlarge_without_claiming_full_resolution(self):
        preview=inspect.getsource(App.open_preview)
        self.assertIn("state['card_thumbnail'] and scale > 1",preview)
        self.assertIn('Card thumbnail preview (not downloaded)',preview)


if __name__ == '__main__':
    unittest.main()
