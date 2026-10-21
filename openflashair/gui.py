"""Runnable Windows Tkinter prototype; no card write operations are exposed."""
from __future__ import annotations
import threading
import io
import json
import os
import sys
import time
import math
import re
import hashlib
import queue
from datetime import datetime, timezone
from urllib.parse import urlsplit
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from .client import FlashAirClient, FlashAirError, RemoteFile
from .engine import SyncEngine, SyncOptions
from .naming import FilenamePolicy, FilenameTemplateError
from .thumbnail import ThumbnailClient
from .queue import DownloadQueue
from .config_editor import ConfigEditor
from .history import TransferHistory
from .media import decode_image, local_image_metadata, local_capture_time
from .credentials import protect_secret, unprotect_secret
from .tray import TrayController
from .progress import TransferProgress
from .date_display import DATE_FORMATS, TIME_FORMATS, format_timestamp

GALLERY_PAGE_SIZE = 100
WINDOWS_APP_USER_MODEL_ID = 'OpenFlashAir.P3-1A'


def application_icon_path() -> Path:
    """Return the same approved icon path in source and PyInstaller layouts."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent))
    return base / 'openflashair' / 'OpenFlashAir_icon_centered.ico'


def configure_windows_taskbar_identity() -> bool:
    """Give the process its own Windows taskbar identity before creating Tk."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        return False
    return True


def flashair_mode_display(value: str | None) -> str:
    """Human-readable W-04 APPMODE display, including manual-start modes.

    Values 4 and 5 are the only modes this connection-settings dialog permits
    editing.  The remaining documented values are displayed faithfully, never
    silently converted to an editable mode.
    """
    code=str(value or '').strip()
    labels={
        '0': 'Access Point (manual start) — APPMODE=0',
        '2': 'Station / client (manual start) — APPMODE=2',
        '3': 'Internet pass-through (manual start) — APPMODE=3',
        '4': 'Access Point / hotspot (auto start) — APPMODE=4',
        '5': 'Station / client (auto start) — APPMODE=5',
        '6': 'Internet pass-through (auto start) — APPMODE=6',
    }
    return labels.get(code, f'Unsupported or missing mode — APPMODE={code or "missing"}')


def flashair_mode_presentation(value: str | None) -> tuple[str,str]:
    """Friendly mode language for the connection dialog; raw values stay diagnostic-only."""
    code=str(value or '').strip()
    if code == '4': return 'Direct Connection (Card Hotspot)', 'Creates a Wi-Fi network for this computer to join.'
    if code == '5': return 'Client Mode', 'Connects to an existing Wi-Fi network.'
    return 'Unsupported mode', 'This saved card mode is not editable in Connection Settings.'


def gallery_page_count(item_count: int, page_size: int = GALLERY_PAGE_SIZE) -> int:
    """Return at least one gallery page, including for an empty discovery."""
    return max(1, (max(0, item_count) + page_size - 1) // page_size)


def gallery_page_slice(items, page: int, page_size: int = GALLERY_PAGE_SIZE):
    """Clamp a page number and return its items without mutating discovery data."""
    pages = gallery_page_count(len(items), page_size)
    page = min(max(0, page), pages - 1)
    return page, list(items[page * page_size:(page + 1) * page_size])


def center_popup(dialog, owner):
    """Center a popup on the owner's monitor work area after Tk calculates its size."""
    dialog.update_idletasks()
    width=max(dialog.winfo_width(),dialog.winfo_reqwidth()); height=max(dialog.winfo_height(),dialog.winfo_reqheight())
    left,top,right,bottom=owner.winfo_vrootx(),owner.winfo_vrooty(),owner.winfo_vrootx()+owner.winfo_vrootwidth(),owner.winfo_vrooty()+owner.winfo_vrootheight()
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            class RECT(ctypes.Structure): _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
            class MONITORINFO(ctypes.Structure): _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',RECT),('rcWork',RECT),('dwFlags',wintypes.DWORD)]
            point=wintypes.POINT(owner.winfo_rootx()+owner.winfo_width()//2,owner.winfo_rooty()+owner.winfo_height()//2)
            monitor=ctypes.windll.user32.MonitorFromPoint(point,2); info=MONITORINFO(); info.cbSize=ctypes.sizeof(info)
            if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
                left,top,right,bottom=info.rcWork.left,info.rcWork.top,info.rcWork.right,info.rcWork.bottom
        except Exception: pass
    width=min(width,max(1,right-left)); height=min(height,max(1,bottom-top))
    x=max(left,min(owner.winfo_rootx()+(owner.winfo_width()-width)//2,right-width)); y=max(top,min(owner.winfo_rooty()+(owner.winfo_height()-height)//2,bottom-height))
    dialog.geometry(f'{width}x{height}+{x}+{y}')


def usable_window_geometry(value, work_area):
    """Return a saved geometry only when it remains practical and on-screen."""
    match=re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)',str(value or ''))
    if not match: return None
    width,height,x,y=map(int,match.groups()); left,top,right,bottom=work_area
    if width < 800 or height < 600 or width > right-left or height > bottom-top: return None
    if x < left or y < top or x+width > right or y+height > bottom: return None
    return f'{width}x{height}+{x}+{y}'


def practical_window_geometry(saved, work_area):
    """Prefer a usable saved size, otherwise use a work-area-limited 1200×850."""
    restored=usable_window_geometry(saved,work_area)
    if restored: return restored
    left,top,right,bottom=work_area; width=min(1200,max(520,right-left-80)); height=min(850,max(600,bottom-top-80))
    return f'{width}x{height}+{left+(right-left-width)//2}+{top+(bottom-top-height)//2}'


def clamp_menu_position(x, y, width, height, work_area):
    left,top,right,bottom=work_area
    return max(left,min(x,right-width)),max(top,min(y,bottom-height))


class App(ttk.Frame):
    def _configure_compact_dashboard_styles(self):
        """Use a readable, DPI-aware type scale without adding layout-only widgets."""
        style=ttk.Style(self)
        font=('Segoe UI',12)
        style.configure('Dashboard.TLabel',font=font)
        style.configure('SectionHeading.TLabel',font=('Segoe UI',12,'bold'))
        style.configure('CounterName.TLabel',font=('Segoe UI',11))
        style.configure('CounterValue.TLabel',font=('Segoe UI',13,'bold'))
        style.configure('LastScan.TLabel',font=('Segoe UI',11))
        style.configure('Large.TButton',font=font,padding=(12,7))
        style.configure('Dashboard.TEntry',font=font,padding=(6,7))
        style.configure('Dashboard.TCombobox',font=font,padding=(4,3))
        # The mounted-card controls are ttk widgets, whereas the form fields are
        # deliberately sized Tk widgets.  Give the former their own explicit
        # typography and vertical padding so Windows' compact default ttk theme
        # cannot make this row look like a different interface.
        style.configure('ConnectionCard.TButton',font=font,padding=(12,10))
        style.configure('ConnectionCard.TCombobox',font=font,padding=(8,9))
        self.option_add('*TCombobox*Listbox.font',('Segoe UI',12))
    def __init__(self, root):
        super().__init__(root, padding=12); self.grid(sticky='nsew'); root.title('OpenFlashAir P3-1A')
        self._configure_compact_dashboard_styles()
        self._install_text_context_menus(root)
        existing_settings=self._settings_path().exists() or self._legacy_settings_path().exists()
        defaults=self._settings(); default_endpoint='http://openflashair/'; default_destination=str(Path.home()/'Pictures'/'OpenFlashAir')
        self.date_format=defaults.get('date_display_format','YYYY-MM-DD' if existing_settings else 'MM/DD/YYYY')
        self.time_format=defaults.get('time_display_format','24-hour' if existing_settings else '12-hour (AM/PM)')
        if self.date_format not in DATE_FORMATS: self.date_format='YYYY-MM-DD' if existing_settings else 'MM/DD/YYYY'
        if self.time_format not in TIME_FORMATS: self.time_format='24-hour' if existing_settings else '12-hour (AM/PM)'
        if not existing_settings: self._save_settings(date_display_format=self.date_format,time_display_format=self.time_format)
        saved_endpoint=defaults.get('endpoint',default_endpoint); saved_destination=defaults.get('destination',default_destination)
        self.endpoint=tk.StringVar(value=saved_endpoint if self._valid_endpoint(saved_endpoint) else default_endpoint); self.destination=tk.StringVar(value=saved_destination if self._valid_destination(saved_destination) else default_destination)
        self.status=tk.StringVar(value='Ready — no card connection attempted'); self.auto=False; self._auto_has_started=False; self.scanning=False; self._operation_failed=False; self._active_scan_automatic=None; self._active_engine=None
        self.auto_state=tk.StringVar(value='Paused'); self.scan_counts=tk.StringVar(value='Discovered —  Downloaded —  Skipped —  Failed —')
        self.counter_values={name:tk.StringVar(value='—') for name in ('Discovered','Downloaded','Skipped','Failed')}
        self.counter_display={name:tk.StringVar(value=f'{name}: —') for name in self.counter_values}
        self.last_scan=tk.StringVar(value='Last scan: none'); self.next_scan=tk.StringVar(value='Next scan: —'); self.operation=tk.StringVar(value='Activity: ready')
        self.connection_status=tk.StringVar(value='Not checked'); self.connection_checked=tk.StringVar(value='')
        self.transfer_text=tk.StringVar(value='Transfer: Idle'); self._transfer_events=queue.SimpleQueue(); self._transfer_progress=TransferProgress(); self._transfer_active=False; self._transfer_after=None
        def endpoint_changed(*_):
            self._connection_checked_at=None; self.connection_status.set('Not checked'); self.connection_checked.set('')
        self.endpoint.trace_add('write',endpoint_changed)
        self.manual_panel_state=tk.StringVar(value='Idle'); self._activity_indicators={}; self._activity_icon_frames={}; self._indicator_after=None; self._indicator_frame=0
        # Dialogs are keyed by canonical card path rather than the camera filename:
        # duplicate filenames are possible in different DCIM folders.
        self._metadata_dialogs={}; self._metadata_dialog=None; self._metadata_generation=0; self._metadata_after=set()
        self.interval=tk.IntVar(value=self._load_interval()); self.interval_label=tk.StringVar(value=f'{self.interval.get()}s'); self._next_scan_at=None; self._poll_after=None; self._countdown_after=None; self._last_auto_signature=None; self._auto_retry_pending=False; self._auto_pause_requested=False
        saved_template,saved_prefix=defaults.get('filename_template','{original}'),defaults.get('filename_prefix','')
        try: FilenamePolicy(saved_template,saved_prefix)
        except FilenameTemplateError: saved_template,saved_prefix='{original}',''
        self.filename_template=tk.StringVar(value=saved_template); self.filename_prefix=tk.StringVar(value=saved_prefix)
        self.log_expanded=self._load_log_expanded(); self.log_error_count=0
        ttk.Label(self,text='FlashAir endpoint',style='Dashboard.TLabel').grid(row=0,column=0,sticky='w',padx=(0,8)); endpoint_entry=tk.Entry(self,textvariable=self.endpoint,width=1,font=('Segoe UI',12),background='white',foreground='black',relief='sunken',bd=1); self.endpoint_entry=endpoint_entry; endpoint_entry.grid(row=0,column=1,sticky='ew',ipady=7); endpoint_entry.bind('<FocusOut>',lambda _event:self._save_connection_settings()); self.settings_button=self._create_settings_button(); self.settings_button.grid(row=0,column=2,padx=(8,0))
        ttk.Label(self,text='Destination',style='Dashboard.TLabel').grid(row=1,column=0,sticky='w',padx=(0,8)); destination_entry=tk.Entry(self,textvariable=self.destination,width=1,font=('Segoe UI',12),background='white',foreground='black',relief='sunken',bd=1); self.destination_entry=destination_entry; destination_entry.grid(row=1,column=1,sticky='ew',ipady=7); destination_entry.bind('<FocusOut>',lambda _event:self._save_connection_settings()); ttk.Button(self,text='Browse…',width=12,command=self.browse,style='Large.TButton').grid(row=1,column=2,sticky='e',padx=(8,0))
        sync_box=ttk.LabelFrame(self,text='Synchronization',padding=(10,5)); self.sync_box=sync_box; sync_box.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(8,5)); sync_box.columnconfigure(0,weight=1); sync_box.columnconfigure(1,weight=1)
        manual_group=ttk.Frame(sync_box); self.manual_scan_group=manual_group; manual_group.grid(row=0,column=0,sticky='nw',padx=(0,12)); manual_group.columnconfigure(3,weight=1)
        self.manual_heading=ttk.Label(manual_group,text='Manual scan',style='SectionHeading.TLabel'); self.manual_heading.grid(row=0,column=0,columnspan=4,sticky='w',pady=(0,3))
        self.scan_once_button=ttk.Button(manual_group,text='Scan Once',command=self.scan,style='Large.TButton'); self.scan_once_button.grid(row=1,column=0,sticky='w')
        self._create_activity_indicator(manual_group,'manual').grid(row=1,column=1,sticky='w',padx=(12,5)); ttk.Label(manual_group,textvariable=self.manual_panel_state,width=10,style='Dashboard.TLabel').grid(row=1,column=2,sticky='w')
        auto_group=ttk.Frame(sync_box); self.auto_scan_group=auto_group; auto_group.grid(row=0,column=1,sticky='nw',padx=(12,0)); auto_group.columnconfigure(3,weight=1)
        self.auto_heading=ttk.Label(auto_group,text='Automatic scan',style='SectionHeading.TLabel'); self.auto_heading.grid(row=0,column=0,columnspan=4,sticky='w',pady=(0,3))
        self.auto_control_button=ttk.Button(auto_group,command=self.pause,style='Large.TButton'); self.auto_control_button.grid(row=1,column=0,sticky='w')
        self.auto_indicator=self._create_activity_indicator(auto_group,'auto'); self.auto_indicator.grid(row=1,column=1,sticky='w',padx=(12,5)); self.auto_state_label=ttk.Label(auto_group,textvariable=self.auto_state,width=12,style='Dashboard.TLabel'); self.auto_state_label.grid(row=1,column=2,sticky='w')
        self.poll_every_label=ttk.Label(auto_group,text='Poll every',style='Dashboard.TLabel'); self.poll_every_label.grid(row=2,column=0,sticky='w',pady=(3,0)); interval_box=ttk.Combobox(auto_group,textvariable=self.interval_label,values=('10s','30s','60s','120s','300s','600s'),width=5,state='readonly',style='Dashboard.TCombobox'); self.interval_box=interval_box; interval_box.grid(row=2,column=1,sticky='w',padx=(8,0),pady=(3,0)); interval_box.bind('<<ComboboxSelected>>',self._interval_changed)
        self.next_scan_label=ttk.Label(auto_group,textvariable=self.next_scan,width=16,style='Dashboard.TLabel'); self.next_scan_label.grid(row=2,column=2,sticky='w',padx=(8,0),pady=(3,0))
        connection_group=ttk.Frame(sync_box); self.connection_group=connection_group; connection_group.grid(row=0,column=2,sticky='nw',padx=(12,0))
        self.connection_heading=ttk.Label(connection_group,text='Connection',style='SectionHeading.TLabel'); self.connection_heading.grid(row=0,column=0,sticky='w',pady=(0,3))
        self.connection_status_label=ttk.Label(connection_group,textvariable=self.connection_status,style='LastScan.TLabel'); self.connection_status_label.grid(row=1,column=0,sticky='w')
        self.connection_checked_label=ttk.Label(connection_group,textvariable=self.connection_checked,style='LastScan.TLabel',width=35); self.connection_checked_label.grid(row=2,column=0,sticky='w')
        connection_group.rowconfigure(2,minsize=self.connection_checked_label.winfo_reqheight())
        shared_status=ttk.Frame(sync_box); self.shared_sync_status=shared_status; shared_status.grid(row=1,column=0,columnspan=3,sticky='ew',pady=(5,0));
        self.counter_labels=[]
        for index,(name,value) in enumerate(self.counter_values.items()):
            shared_status.columnconfigure(index,weight=1,uniform='sync-counter')
            label=ttk.Label(shared_status,textvariable=self.counter_display[name],style='CounterValue.TLabel'); label.grid(row=0,column=index,sticky=('w' if index == 0 else 'e' if index == 3 else ''),padx=((0,12) if index == 3 else 0)); self.counter_labels.append(label)
        self.last_scan_label=ttk.Label(shared_status,textvariable=self.last_scan,style='LastScan.TLabel'); self.last_scan_label.grid(row=1,column=0,columnspan=3,sticky='w',pady=(2,0))
        transfer=ttk.Frame(sync_box); transfer.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(3,0)); transfer.columnconfigure(0,weight=1)
        ttk.Label(transfer,textvariable=self.transfer_text,style='LastScan.TLabel').grid(row=0,column=0,sticky='w')
        self.transfer_bar=ttk.Progressbar(transfer,mode='determinate',maximum=100); self.transfer_bar.grid(row=1,column=0,sticky='ew')
        self._update_auto_control_label()
        self._set_panel_activity('manual','idle','Idle'); self._set_panel_activity('auto','paused','Paused')
        gallery_actions=ttk.LabelFrame(self,text='Gallery actions',padding=6); self.gallery_actions=gallery_actions; gallery_actions.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(0,4)); gallery_actions.columnconfigure(4,weight=1)
        ttk.Button(gallery_actions,text='Refresh Gallery',command=self.refresh_gallery,style='Large.TButton').grid(row=0,column=0,sticky='w')
        self.select_page_button=ttk.Button(gallery_actions,text='Select Page',command=self.select_page,style='Large.TButton'); self.select_page_button.grid(row=0,column=1,sticky='w',padx=(6,0))
        self.select_all_button=ttk.Button(gallery_actions,text='Select All',command=self.select_all,style='Large.TButton'); self.select_all_button.grid(row=0,column=2,sticky='w',padx=(6,0))
        self.clear_selection_button=ttk.Button(gallery_actions,text='Clear Selection',command=self.clear_all,style='Large.TButton'); self.clear_selection_button.grid(row=0,column=3,sticky='w',padx=(6,0))
        self.open_folder_button=ttk.Button(gallery_actions,text='Open Folder',command=self.open_destination_folder,style='Large.TButton'); self.open_folder_button.grid(row=0,column=4,sticky='w',padx=(6,0))
        self.selection_text=tk.StringVar(value='0 selected'); self.gallery_selection_label=ttk.Label(gallery_actions,textvariable=self.selection_text,style='Dashboard.TLabel'); self.gallery_selection_label.grid(row=0,column=5,sticky='e',padx=(12,8))
        self.download_selected_button=ttk.Button(gallery_actions,text='Download Selected',command=self.download_selected,state='disabled',style='Large.TButton'); self.download_selected_button.grid(row=0,column=6,sticky='e')
        self.pager=ttk.Frame(self); self.pager.grid(row=4,column=0,columnspan=3,sticky='ew',pady=(4,2)); self.pager.columnconfigure(0,weight=1)
        self.gallery_summary=tk.StringVar(value='Gallery: 0 photographs'); ttk.Label(self.pager,textvariable=self.gallery_summary,font=('Segoe UI',10,'bold')).grid(row=0,column=0,sticky='w')
        pager_controls=ttk.Frame(self.pager); self.pager_controls=pager_controls; pager_controls.grid(row=0,column=1,sticky='e')
        ttk.Label(pager_controls,text='Sort order').pack(side='left',padx=(0,4))
        self.sort_order=tk.StringVar(value='Newest first'); sort_box=ttk.Combobox(pager_controls,textvariable=self.sort_order,values=('Newest first','Oldest first'),state='readonly',width=12); sort_box.pack(side='left',padx=(0,10)); sort_box.bind('<<ComboboxSelected>>',self._sort_changed)
        self.previous_page_button=ttk.Button(pager_controls,text='‹ Previous',command=lambda:self._change_page(-1),state='disabled'); self.previous_page_button.pack(side='left')
        self.page_text=tk.StringVar(value='Page 1 of 1'); ttk.Label(pager_controls,textvariable=self.page_text,font=('Segoe UI',10,'bold')).pack(side='left',padx=12)
        self.next_page_button=ttk.Button(pager_controls,text='Next ›',command=lambda:self._change_page(1),state='disabled'); self.next_page_button.pack(side='left')
        self.content_pane=tk.PanedWindow(self,orient='vertical',sashwidth=4,showhandle=False,bd=0); self.content_pane.grid(row=5,column=0,columnspan=3,sticky='nsew')
        self.gallery_container=ttk.Frame(self.content_pane); self.content_pane.add(self.gallery_container,minsize=220)
        self.gallery_canvas=tk.Canvas(self.gallery_container,highlightthickness=0); self.gallery_canvas.grid(row=0,column=0,sticky='nsew')
        # Classic tk.Scrollbar (rather than ttk) provides the native Windows arrows,
        # track and thumb with explicit, high-contrast classic-widget options.
        self.gallery_scroll=tk.Scrollbar(self.gallery_container,orient='vertical',width=18,command=self._gallery_scroll_command,relief='raised',bd=1,highlightthickness=0,background='#b8b8b8',activebackground='#969696',troughcolor='#d0d0d0',elementborderwidth=2,repeatdelay=300,repeatinterval=100)
        self.gallery_scroll.grid(row=0,column=1,sticky='ns'); self.gallery_canvas.configure(yscrollcommand=self.gallery_scroll.set); self.gallery_container.columnconfigure(0,weight=1); self.gallery_container.columnconfigure(1,minsize=20,weight=0); self.gallery_container.rowconfigure(0,weight=1)
        # Deliberately render tiles as Canvas items.  A Canvas window containing 100 native
        # Label widgets can leave stale child-window surfaces on Windows after a thumb drag.
        self.gallery_canvas.bind('<Configure>',self._gallery_resize); self.gallery_canvas.bind('<MouseWheel>',self._gallery_mousewheel)
        self._gallery_generation=0; self.selected=[]; self.loaded=[]; self._resize_after=None; self._layout_after=None
        self.gallery_files=[]; self.gallery_page=0; self._tiles_by_path={}; self._thumbnail_client=None; self._thumbnail_endpoint=None; self._pending_tile_click={}
        self.log_frame=ttk.Frame(self.content_pane); self.log=tk.Text(self.log_frame,width=76,height=7,state='disabled'); self.log_scroll=tk.Scrollbar(self.log_frame,orient='vertical',width=18,command=self.log.yview); self.log.configure(yscrollcommand=self.log_scroll.set); self.log.grid(row=0,column=0,sticky='nsew'); self.log_scroll.grid(row=0,column=1,sticky='ns'); self.log_frame.columnconfigure(0,weight=1); self.log_frame.rowconfigure(0,weight=1)
        self._log_header_hover=False
        self.log_header=tk.Canvas(self,height=30,highlightthickness=0,bd=0,cursor='hand2'); self.log_header.grid(row=6,column=0,columnspan=3,sticky='ew')
        self.log_header.bind('<Button-1>',lambda _event:self.toggle_log()); self.log_header.bind('<Enter>',self._log_header_enter); self.log_header.bind('<Leave>',self._log_header_leave); self.log_header.bind('<Configure>',lambda _event:self._render_log_header())
        self._log_height=150; self._pane_height=None; self._sash_after=None; self.content_pane.bind('<Configure>',self._pane_resized); self.content_pane.bind('<ButtonRelease-1>',self._remember_log_height)
        self.columnconfigure(1,weight=1); self.rowconfigure(5,weight=1); root.columnconfigure(0,weight=1); root.rowconfigure(0,weight=1)
        self._compact_header=None; self._compact_sync_dashboard=None; self._header_layout_after=None; self.bind('<Configure>',self._header_resize,add='+'); self.after_idle(self._apply_header_layout)
        self._main_window=root; self._last_window_state='normal'; self._geometry_after=None; self._tray=None; self._tray_actions=queue.SimpleQueue(); self._tray_hidden=False; self._tray_poll_after=None; self._restore_window_geometry(); root.bind('<Configure>',self._remember_window_geometry,add='+'); root.bind('<Unmap>',self._main_window_unmapped,add='+'); root.protocol('WM_DELETE_WINDOW',self._close_main_window)
        self._apply_log_state()
    def _create_settings_button(self):
        """A full-size Canvas button keeps the approved vector gear sharp at any DPI."""
        scale=max(1.0,float(self.tk.call('tk','scaling'))/(96/72))
        width=max(140,round(140*scale)); height=max(43,round(43*scale)); canvas=tk.Canvas(self,width=width,height=height,highlightthickness=0,bd=0,cursor='hand2',takefocus=1)
        center_y=height/2; center_x=22*scale; outer=height*.27; inner=height*.19; points=[]
        for index in range(16):
            angle=-math.pi/2+index*math.pi/8; radius=outer if index % 2 == 0 else inner
            points.extend((center_x+math.cos(angle)*radius,center_y+math.sin(angle)*radius))
        canvas.create_rectangle(1,1,width-1,height-1,fill='#f4f4f4',outline='#adadad',tags='background')
        canvas.create_polygon(points,fill='#334155',outline='#334155',tags='gear')
        canvas.create_oval(center_x-height*.09,center_y-height*.09,center_x+height*.09,center_y+height*.09,fill='#f4f4f4',outline='',tags='gear')
        canvas.create_text(center_x+outer+10*scale,center_y,text='Settings',anchor='w',fill='#111827',font=('Segoe UI',12),tags='label')
        canvas.bind('<Button-1>',self._show_settings_menu); canvas.bind('<Return>',self._show_settings_menu); canvas.bind('<space>',self._show_settings_menu)
        canvas.bind('<Enter>',self._settings_button_enter); canvas.bind('<Leave>',self._settings_button_leave)
        canvas.bind('<FocusIn>',lambda _event:canvas.itemconfigure('background',fill='#dbeafe'))
        canvas.bind('<FocusOut>',lambda _event:canvas.itemconfigure('background',fill='#f4f4f4'))
        self.settings_popup=tk.Menu(canvas,tearoff=False)
        self.settings_popup.add_command(label='Check Connection',command=self.check)
        self.settings_popup.add_command(label='Filename Settings…',command=self.filename_settings)
        self.settings_popup.add_command(label='Edit FlashAir CONFIG…',command=self.config_editor)
        self.settings_popup.add_command(label='Date & Time Display…',command=self.date_time_settings)
        self._settings_tooltip=None; self._settings_tooltip_after=None
        return canvas
    def _show_settings_menu(self,event=None):
        if event is not None and getattr(event,'num',None) == 1:
            x,y=event.x_root,event.y_root
        else:
            x=self.settings_button.winfo_rootx(); y=self.settings_button.winfo_rooty()+self.settings_button.winfo_height()
        self.settings_popup.update_idletasks(); width,height=self.settings_popup.winfo_reqwidth(),self.settings_popup.winfo_reqheight()
        x,y=clamp_menu_position(x,y,width,height,self._monitor_work_area())
        try: self.settings_popup.tk_popup(x,y)
        finally: self.settings_popup.grab_release()
        return 'break'
    def _monitor_work_area(self):
        owner=self.winfo_toplevel(); left,top,right,bottom=owner.winfo_vrootx(),owner.winfo_vrooty(),owner.winfo_vrootx()+owner.winfo_vrootwidth(),owner.winfo_vrooty()+owner.winfo_vrootheight()
        if os.name == 'nt':
            try:
                import ctypes
                from ctypes import wintypes
                class RECT(ctypes.Structure): _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
                class MONITORINFO(ctypes.Structure): _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',RECT),('rcWork',RECT),('dwFlags',wintypes.DWORD)]
                point=wintypes.POINT(owner.winfo_rootx()+owner.winfo_width()//2,owner.winfo_rooty()+owner.winfo_height()//2); monitor=ctypes.windll.user32.MonitorFromPoint(point,2); info=MONITORINFO(); info.cbSize=ctypes.sizeof(info)
                if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor,ctypes.byref(info)): left,top,right,bottom=info.rcWork.left,info.rcWork.top,info.rcWork.right,info.rcWork.bottom
            except Exception: pass
        return left,top,right,bottom
    def _restore_window_geometry(self):
        work=self._monitor_work_area(); saved=self._settings().get('window_geometry'); self._main_window.geometry(practical_window_geometry(saved,work)); self._main_window.minsize(520,600)
    def _remember_window_geometry(self,event=None):
        if getattr(self,'_closing',False): return
        if event is not None and event.widget is not self._main_window: return
        try:
            state=self._main_window.state()
            if state in ('normal','zoomed'): self._last_window_state=state
        except tk.TclError: return
        if self._geometry_after: self.after_cancel(self._geometry_after)
        self._geometry_after=self.after(500,self._save_window_geometry)
    def _save_window_geometry(self):
        self._geometry_after=None
        try:
            if self._main_window.state() == 'normal':
                value=usable_window_geometry(self._main_window.geometry(),self._monitor_work_area())
                if value: self._save_settings(window_geometry=value)
        except tk.TclError: pass
    def _close_main_window(self):
        if self.scanning:
            self._closing=True; self.auto=False
            self.status.set('Finishing the current transfer before exit…')
            return
        self._finish_close_main_window()
    def _finish_close_main_window(self):
        self._closing=True
        for attribute in ('_indicator_after','_geometry_after','_header_layout_after','_resize_after','_layout_after','_poll_after','_countdown_after','_settings_tooltip_after','_tray_poll_after','_transfer_after','_sash_after'):
            ident=getattr(self,attribute,None)
            if ident:
                try: self.after_cancel(ident)
                except tk.TclError: pass
                setattr(self,attribute,None)
        for ident in tuple(self._metadata_after):
            try: self.after_cancel(ident)
            except tk.TclError: pass
        self._metadata_after.clear()
        self._close_metadata_dialog()
        self._save_window_geometry()
        if self._tray is not None:
            self._tray.stop(); self._tray=None
        self._main_window.destroy()
    def _main_window_unmapped(self,_event=None):
        """Hide to the tray only after Windows has actually minimized the root."""
        if _event is not None and _event.widget is not self._main_window:
            return
        if getattr(self,'_closing',False) or self._tray_hidden:
            return
        self._main_window.after_idle(self._minimize_to_tray_if_iconic)
    def _minimize_to_tray_if_iconic(self):
        if getattr(self,'_closing',False) or self._tray_hidden:
            return
        try:
            if self._main_window.state() != 'iconic':
                return
        except tk.TclError:
            return
        tray=self._tray or TrayController(application_icon_path(),self._tray_actions.put,self._tray_title())
        if not tray.start():
            self.add('System tray is unavailable; application remains minimized in the taskbar.')
            return
        self._tray=tray; self._tray.set_title(self._tray_title()); self._tray.set_state(self.auto,self.scanning)
        if self._tray_poll_after is None: self._tray_poll_after=self.after(100,self._process_tray_actions)
    def _tray_title(self):
        if self._transfer_active:
            p=self._transfer_progress.snapshot()
            return f"OpenFlashAir — {p['current']}/{p['total']} – {p['mbps']:.1f} MB/s"
        return f'OpenFlashAir — {self.auto_state.get()}'
    def _transfer_event(self,event,**values):
        if event=='bytes': values['timestamp']=time.monotonic()
        self._transfer_events.put((event,values))
    def _update_transfer_display(self):
        self._transfer_after=None
        try:
            while True:
                event,values=self._transfer_events.get_nowait()
                if event=='start': self._transfer_progress.begin(**values); self._transfer_active=True
                elif event=='bytes': self._transfer_progress.update(**values)
                elif event in ('finished','idle'): self._transfer_active=False
        except queue.Empty: pass
        if self._transfer_active:
            p=self._transfer_progress.snapshot(); total=f"{p['size']:,}" if p['size'] else 'unknown'
            self.transfer_text.set(f"Transfer {p['current']}/{p['total']} · {Path(p['path']).name} · {p['received']:,}/{total} bytes · {p['mbps']:.1f} MB/s")
            self.transfer_bar.configure(value=min(100,100*p['received']/p['size']) if p['size'] else 0)
        else:
            self.transfer_text.set('Transfer: Idle'); self.transfer_bar.configure(value=0)
        if self._tray is not None: self._tray.set_title(self._tray_title())
        if self.scanning and not getattr(self,'_closing',False): self._transfer_after=self.after(250,self._update_transfer_display)
    def _process_tray_actions(self):
        self._tray_poll_after=None
        if getattr(self,'_closing',False):
            return
        try:
            while True:
                action=self._tray_actions.get_nowait()
                if action == 'tray_ready':
                    if self._main_window.state() == 'iconic':
                        self._tray_hidden=True; self._main_window.withdraw(); self.add('OpenFlashAir minimized to the system tray.')
                elif action == 'tray_failed':
                    if self._tray is not None: self._tray.stop(); self._tray=None
                    self._tray_hidden=False
                    if self._main_window.state() == 'withdrawn': self._main_window.iconify()
                    self.add('System tray is unavailable; application remains minimized in the taskbar.')
                elif action == 'restore':
                    previous_state=getattr(self,'_last_window_state','normal')
                    self._tray_hidden=False; self._main_window.deiconify(); self._main_window.state(previous_state); self._main_window.lift()
                    try: self._main_window.focus_force()
                    except tk.TclError: pass
                elif action == 'toggle_auto':
                    if self.auto or not self.scanning: self.pause()
                elif action == 'scan':
                    if not self.auto and not self.scanning: self.scan()
                elif action == 'exit':
                    self._close_main_window(); return
        except queue.Empty:
            pass
        try:
            self._tray_poll_after=self.after(100,self._process_tray_actions)
        except tk.TclError:
            self._tray_poll_after=None
    def _settings_button_enter(self,_event=None):
        self.settings_button.itemconfigure('background',fill='#e2e8f0')
    def _settings_button_leave(self,_event=None):
        self.settings_button.itemconfigure('background',fill='#f4f4f4')
    def _show_settings_tooltip(self):
        self._settings_tooltip_after=None
        if self._settings_tooltip and self._settings_tooltip.winfo_exists(): return
        tip=tk.Toplevel(self); tip.overrideredirect(True); tip.attributes('-topmost',True)
        ttk.Label(tip,text='Settings',padding=(6,3)).pack()
        tip.geometry(f'+{self.settings_button.winfo_rootx()}+{self.settings_button.winfo_rooty()+self.settings_button.winfo_height()+3}')
        self._settings_tooltip=tip
    def _install_text_context_menus(self,root):
        root.bind_all('<Button-3>',self._show_text_context_menu,add='+')
    @staticmethod
    def _editable_text_widget(widget):
        return isinstance(widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Combobox))
    @staticmethod
    def _text_selection_present(widget):
        try:
            return bool(widget.tag_ranges('sel')) if isinstance(widget,tk.Text) else bool(widget.selection_present())
        except tk.TclError: return False
    @staticmethod
    def _text_widget_is_editable(widget):
        try: return str(widget.cget('state')) == 'normal'
        except tk.TclError: return False
    @staticmethod
    def _select_all_text(widget):
        if isinstance(widget,tk.Text): widget.tag_add('sel','1.0','end-1c')
        else: widget.selection_range(0,'end')
        widget.focus_set()
    def _clipboard_has_text(self):
        try: return bool(self.clipboard_get())
        except tk.TclError: return False
    def _build_text_context_menu(self,widget):
        selected=self._text_selection_present(widget); editable=self._text_widget_is_editable(widget); has_paste=self._clipboard_has_text()
        contents=widget.get('1.0','end-1c') if isinstance(widget,tk.Text) else widget.get()
        menu=tk.Menu(widget,tearoff=False)
        menu.add_command(label='Cut',command=lambda:widget.event_generate('<<Cut>>'),state=('normal' if selected and editable else 'disabled'))
        menu.add_command(label='Copy',command=lambda:widget.event_generate('<<Copy>>'),state=('normal' if selected else 'disabled'))
        menu.add_command(label='Paste',command=lambda:widget.event_generate('<<Paste>>'),state=('normal' if editable and has_paste else 'disabled'))
        menu.add_separator(); menu.add_command(label='Select All',command=lambda:self._select_all_text(widget),state=('normal' if contents else 'disabled'))
        return menu
    def _show_text_context_menu(self,event):
        widget=event.widget
        if not self._editable_text_widget(widget): return None
        try: widget.focus_set()
        except tk.TclError: pass
        menu=self._build_text_context_menu(widget)
        try: menu.tk_popup(event.x_root,event.y_root)
        finally: menu.grab_release()
        return 'break'
    def _create_activity_indicator(self,parent,name):
        """Create a fixed-size canvas whose cached sync icon can be swapped in place."""
        scale=max(1.0,float(self.tk.call('tk','scaling'))/(96/72))
        size=min((32,48,64),key=lambda candidate:abs(candidate-32*scale))
        canvas=tk.Canvas(parent,width=size,height=size,highlightthickness=0,bd=0)
        image=canvas.create_image(size//2,size//2,anchor='center')
        self._activity_indicators[name]={'canvas':canvas,'image':image,'mode':'idle','phase':'idle','transition_step':0,'orientation':0,'size':size,'photo':None}
        return canvas
    def _sync_asset_root(self):
        """Locate the owner-supplied frames in source and PyInstaller layouts."""
        packaged=Path(getattr(sys,'_MEIPASS',Path(__file__).parent.parent))/'openflashair'/'assets'/'sync_states_v1'
        return packaged if packaged.exists() else Path(__file__).parent/'assets'/'sync_states_v1'
    def _sync_icon_frames(self,size):
        """Load approved PNG frames once; animation ticks never decode or transform them."""
        key=('sync-states-v1',size)
        if key in self._activity_icon_frames: return self._activity_icon_frames[key]
        from PIL import Image, ImageTk
        root=self._sync_asset_root()
        def photo(path):
            with Image.open(path) as source: return ImageTk.PhotoImage(source.convert('RGBA'),master=self)
        green=tuple(photo(root/'green'/f'frames_{size}px'/f'frame_{index:02d}.png') for index in range(24))
        red=tuple(photo(root/'red'/f'frames_{size}px'/f'frame_{index:02d}.png') for index in range(24))
        transition=tuple(tuple(photo(root/f'transition_{size}px'/f'angle_{angle:02d}'/f'step_{step:02d}.png') for step in range(9)) for angle in range(24))
        self._activity_icon_frames[key]={'green':green,'red':red,'transition':transition}
        return self._activity_icon_frames[key]
    def _set_panel_activity(self,name,mode,label):
        if name == 'manual': self.manual_panel_state.set(label)
        else: self.auto_state.set(label)
        indicator=self._activity_indicators.get(name)
        if indicator is None: return
        previous_phase=indicator['phase']; previous_step=indicator['transition_step']
        was_active=previous_phase in ('starting','active')
        wants_active=mode == 'active'
        indicator['mode']=mode
        if wants_active and not was_active:
            indicator['phase']='starting'
            # A stopped transition reverses from its current blend level.
            indicator['transition_step']=max(0,indicator['transition_step'])
        elif not wants_active and was_active:
            indicator['phase']='stopping'
            indicator['transition_step']=min(8,max(0,previous_step if previous_phase == 'starting' else 8))
        elif not wants_active and indicator['phase'] == 'idle':
            indicator['transition_step']=0
        self._render_activity_indicator(name); self._sync_indicator_animation()
        if getattr(self,'_tray',None) is not None:
            self._tray.set_title(self._tray_title())
    def _render_activity_indicator(self,name):
        indicator=self._activity_indicators[name]; canvas=indicator['canvas']; frames=self._sync_icon_frames(indicator['size']); orientation=indicator['orientation']; phase=indicator['phase']
        if phase == 'active': photo=frames['green'][orientation]
        elif phase in ('starting','stopping'): photo=frames['transition'][orientation][indicator['transition_step']]
        else: photo=frames['red'][orientation]
        indicator['photo']=photo  # retain the Tk image for the life of this indicator
        canvas.itemconfigure(indicator['image'],image=photo)
    def _sync_indicator_animation(self):
        animated=any(indicator['phase'] != 'idle' for indicator in self._activity_indicators.values())
        if animated and self._indicator_after is None:
            transitioning=any(indicator['phase'] in ('starting','stopping') for indicator in self._activity_indicators.values())
            self._indicator_after=self.after(35 if transitioning else 55,self._tick_activity_indicators)
        elif not animated and self._indicator_after is not None:
            self.after_cancel(self._indicator_after); self._indicator_after=None
    def _tick_activity_indicators(self):
        # The normal callback has already fired; cancelling here also makes a
        # deliberate test/manual tick unable to leave an older callback queued.
        if self._indicator_after is not None:
            try: self.after_cancel(self._indicator_after)
            except tk.TclError: pass
        self._indicator_after=None
        for name,indicator in self._activity_indicators.items():
            if indicator['phase'] == 'starting':
                indicator['transition_step']+=1
                if indicator['transition_step'] >= 8: indicator['phase']='active'
            elif indicator['phase'] == 'active': indicator['orientation']=(indicator['orientation']+1)%24
            elif indicator['phase'] == 'stopping':
                indicator['transition_step']-=1
                if indicator['transition_step'] <= 0: indicator['phase']='idle'; indicator['transition_step']=0
            if indicator['phase'] != 'idle' or indicator['mode'] != 'active': self._render_activity_indicator(name)
        self._sync_indicator_animation()
    def _cancel_indicator_animation(self):
        if self._indicator_after is not None: self.after_cancel(self._indicator_after); self._indicator_after=None
    def _update_scan_controls(self):
        if getattr(self,'_tray',None) is not None: self._tray.set_state(self.auto,self.scanning)
        if not hasattr(self,'scan_once_button'): return
        self.scan_once_button.configure(state=('disabled' if self.scanning else 'normal'))
        if not self.auto: self.auto_control_button.configure(state=('disabled' if self.scanning else 'normal'))
    def _update_auto_control_label(self):
        if not hasattr(self,'auto_control_button'): return
        text = 'Pause Auto Scan' if self.auto else ('Pausing…' if self._auto_pause_requested else ('Resume Auto Scan' if self._auto_has_started else 'Start Auto Scan'))
        self.auto_control_button.configure(text=text)
    def _header_resize(self,_event=None):
        if self._header_layout_after: self.after_cancel(self._header_layout_after)
        self._header_layout_after=self.after_idle(self._apply_header_layout)
    def _apply_header_layout(self,width=None):
        """Reflow controls before their fixed labels can force a clipped narrow window."""
        self._header_layout_after=None
        actual_width=self.winfo_width() if width is None else width
        compact=actual_width < 900
        compact_sync=actual_width < 820
        if compact_sync != self._compact_sync_dashboard:
            self._compact_sync_dashboard=compact_sync
            if compact_sync:
                self.auto_indicator.grid_configure(row=2,column=0,padx=(0,5),pady=(4,0))
                self.auto_state_label.grid_configure(row=2,column=1,columnspan=2,padx=(0,0),pady=(4,0))
                self.poll_every_label.grid_configure(row=3,column=0,pady=(3,0))
                self.interval_box.grid_configure(row=3,column=1,padx=(8,0),pady=(3,0))
                self.next_scan_label.grid_configure(row=4,column=0,columnspan=3,padx=0,pady=(2,0))
                for index,label in enumerate(self.counter_labels):
                    label.grid_configure(row=index//2,column=index%2,sticky=('w' if index % 2 == 0 else 'e'),padx=((0,12) if index % 2 else 0))
                for column in range(4): self.shared_sync_status.columnconfigure(column,weight=1 if column < 2 else 0,uniform='sync-counter-narrow' if column < 2 else '')
                self.last_scan_label.grid_configure(row=2,column=0,columnspan=2,pady=(2,0))
            else:
                self.auto_indicator.grid_configure(row=1,column=1,padx=(12,5),pady=0)
                self.auto_state_label.grid_configure(row=1,column=2,columnspan=1,padx=0,pady=0)
                self.poll_every_label.grid_configure(row=2,column=0,pady=(3,0))
                self.interval_box.grid_configure(row=2,column=1,padx=(8,0),pady=(3,0))
                self.next_scan_label.grid_configure(row=2,column=2,columnspan=1,padx=(8,0),pady=(3,0))
                for index,label in enumerate(self.counter_labels):
                    label.grid_configure(row=0,column=index,sticky=('w' if index == 0 else 'e' if index == 3 else ''),padx=((0,12) if index == 3 else 0))
                for column in range(4): self.shared_sync_status.columnconfigure(column,weight=1,minsize=112,uniform='sync-counter')
                self.last_scan_label.grid_configure(row=1,column=0,columnspan=4,pady=(2,0))
        if compact == self._compact_header: return
        self._compact_header=compact
        if compact:
            self.clear_selection_button.grid_configure(row=1,column=0,sticky='w',padx=0,pady=(5,0))
            self.open_folder_button.grid_configure(row=1,column=1,sticky='w',padx=(6,0),pady=(5,0))
            self.gallery_selection_label.grid_configure(row=1,column=2,columnspan=1,sticky='w',padx=(6,8),pady=(5,0))
            self.download_selected_button.grid_configure(row=2,column=0,columnspan=3,sticky='e',pady=(5,0))
            self.pager_controls.grid_configure(row=1,column=0,sticky='w',pady=(4,0))
        else:
            self.clear_selection_button.grid_configure(row=0,column=3,sticky='w',padx=(6,0),pady=0)
            self.open_folder_button.grid_configure(row=0,column=4,sticky='w',padx=(6,0),pady=0)
            self.gallery_selection_label.grid_configure(row=0,column=5,columnspan=1,sticky='e',padx=(12,8),pady=0)
            self.download_selected_button.grid_configure(row=0,column=6,columnspan=1,sticky='e',pady=0)
            self.pager_controls.grid_configure(row=0,column=1,sticky='e',pady=0)
    def browse(self):
        p=filedialog.askdirectory(initialdir=self.destination.get());
        if p:self.destination.set(p); self._save_connection_settings()
    def open_destination_folder(self):
        try:
            path=Path(self.destination.get())
            if not path.is_dir(): raise FileNotFoundError('Destination folder does not exist or is inaccessible')
            os.startfile(str(path))
        except (OSError,AttributeError) as exc:
            messagebox.showerror('Open Folder',f'Unable to open destination folder: {exc}',parent=self.winfo_toplevel())
    def make_engine(self):
        self._save_connection_settings()
        stage=Path(self.destination.get())/'.openflashair-staging'
        return SyncEngine(FlashAirClient(self.endpoint.get()),Path(self.destination.get()),stage,naming=FilenamePolicy(self.filename_template.get(),self.filename_prefix.get()),progress=self._transfer_event)
    @staticmethod
    def _valid_endpoint(value):
        try:
            parsed=urlsplit(str(value)); return parsed.scheme in {'http','https'} and bool(parsed.netloc)
        except Exception: return False
    @staticmethod
    def _valid_destination(value):
        try: return bool(str(value)) and Path(value).expanduser().is_absolute()
        except (TypeError,ValueError): return False
    def _save_connection_settings(self):
        endpoint=self.endpoint.get().strip(); destination=self.destination.get().strip()
        if self._valid_endpoint(endpoint) and self._valid_destination(destination):
            self._save_settings(endpoint=endpoint,destination=destination)
    @staticmethod
    def _credential_profile_key(values, config_path):
        """Keep profiles card-specific; never use an SSID or password as the key."""
        cid=str(values.get('CID','')).strip()
        if cid: return f'cid:{cid.casefold()}'
        return 'config:'+hashlib.sha256(str(config_path).encode('utf-8')).hexdigest()
    def _mode_profile(self, card_key, mode):
        profile=self._settings().get('wireless_profiles',{}).get(card_key,{}).get(str(mode),{})
        password=unprotect_secret(profile.get('password'))
        return profile.get('ssid',''),password
    def _mode_appname(self, card_key, mode):
        return self._settings().get('wireless_profiles',{}).get(card_key,{}).get(str(mode),{}).get('appname','')
    def _remember_mode_profile(self, card_key, mode, ssid, password, appname=None):
        """Persist a verified card profile only with DPAPI-protected secret material."""
        if str(mode) not in {'4','5'} or set(str(password)) == {'*'}: return
        token=protect_secret(str(password))
        if token is None: return
        settings=self._settings(); profiles=settings.get('wireless_profiles',{}); card=profiles.get(card_key,{})
        profile={'ssid':str(ssid),'password':token}
        if appname is not None: profile['appname']=str(appname)
        elif str(mode) in card and 'appname' in card[str(mode)]: profile['appname']=card[str(mode)]['appname']
        card[str(mode)]=profile; profiles[card_key]=card
        self._save_settings(wireless_profiles=profiles)
    def _mode_endpoint(self, card_key, mode):
        if str(mode) == '4': return 'http://192.168.0.1/'
        return self._settings().get('endpoint_profiles',{}).get(card_key,{}).get(str(mode),'')
    def _remember_mode_endpoint(self, card_key, mode, endpoint):
        if str(mode) != '5' or not self._valid_endpoint(endpoint): return
        settings=self._settings(); profiles=settings.get('endpoint_profiles',{}); card=profiles.get(card_key,{})
        card[str(mode)]=endpoint; profiles[card_key]=card; self._save_settings(endpoint_profiles=profiles)
    def filename_settings(self):
        dialog=tk.Toplevel(self); dialog.title('Filename Settings'); dialog.transient(self.winfo_toplevel()); dialog.resizable(False,False)
        template=tk.StringVar(value=self.filename_template.get()); prefix=tk.StringVar(value=self.filename_prefix.get()); preview=tk.StringVar()
        body=ttk.Frame(dialog,padding=12); body.grid(sticky='nsew')
        ttk.Label(body,text='Template').grid(row=0,column=0,sticky='w'); entry=ttk.Entry(body,textvariable=template,width=42); entry.grid(row=0,column=1,sticky='ew')
        ttk.Label(body,text='Prefix (optional)').grid(row=1,column=0,sticky='w',pady=(6,0)); ttk.Entry(body,textvariable=prefix,width=42).grid(row=1,column=1,sticky='ew',pady=(6,0))
        ttk.Label(body,text='Fields: {original}, {date}, {time}, {sequence}, {prefix}').grid(row=2,column=0,columnspan=2,sticky='w',pady=(8,0))
        ttk.Label(body,text='Preview').grid(row=3,column=0,sticky='nw',pady=(8,0)); ttk.Label(body,textvariable=preview,wraplength=330).grid(row=3,column=1,sticky='w',pady=(8,0))
        example=RemoteFile('/DCIM/101OLYMP/P1010001.JPG',1,datetime(2026,1,2,3,4,5,tzinfo=timezone.utc),False)
        def update_preview(*_args):
            try: preview.set(FilenamePolicy(template.get(),prefix.get()).render(example,7))
            except FilenameTemplateError as exc: preview.set(f'Invalid: {exc}')
        template.trace_add('write',update_preview); prefix.trace_add('write',update_preview); update_preview()
        def save():
            try: FilenamePolicy(template.get(),prefix.get())
            except FilenameTemplateError as exc: messagebox.showerror('Filename Settings',str(exc),parent=dialog); return
            self.filename_template.set(template.get().strip() or '{original}'); self.filename_prefix.set(prefix.get().strip())
            self._save_settings(filename_template=self.filename_template.get(),filename_prefix=self.filename_prefix.get()); dialog.destroy()
        def restore(): template.set('{original}'); prefix.set('')
        buttons=ttk.Frame(body); buttons.grid(row=4,column=0,columnspan=2,sticky='e',pady=(12,0)); ttk.Button(buttons,text='Restore Default',command=restore).pack(side='left',padx=4); ttk.Button(buttons,text='Cancel',command=dialog.destroy).pack(side='left',padx=4); ttk.Button(buttons,text='Save',command=save).pack(side='left')
        body.columnconfigure(1,weight=1); entry.focus_set(); dialog.after_idle(lambda:center_popup(dialog,self.winfo_toplevel()))
    def config_editor(self):
        """Compact, read-only connection view. Hidden CONFIG data is never displayed or changed."""
        dialog=tk.Toplevel(self.winfo_toplevel()); dialog.withdraw(); dialog.title('FlashAir Connection Settings'); dialog.transient(self.winfo_toplevel()); dialog.resizable(False,False)
        dialog_target_width=800; dialog_min_width=760; dialog.minsize(dialog_min_width,360)
        selected=tk.StringVar(); status=tk.StringVar(value='No readable FlashAir CONFIG detected.'); card_state=tk.StringVar(value='NOT INSERTED'); location=tk.StringVar(value='Card location: —'); ssid=tk.StringVar(value=''); password=tk.StringVar(value=''); appname=tk.StringVar(value=''); endpoint=tk.StringVar(value=self.endpoint.get()); firmware=tk.StringVar(value='—'); mode=tk.StringVar(value='No card selected'); saved_mode=tk.StringVar(value='—'); mode_detail=tk.StringVar(value=''); pending_mode=tk.StringVar(value='Pending changes: None'); credential_name=tk.StringVar(value='Wi-Fi network name'); credential_password=tk.StringVar(value='Wi-Fi password'); reveal=tk.BooleanVar(value=False); advanced_visible=tk.BooleanVar(value=False); loaded={}; draft_profiles={}; profile_key=None
        dialog.columnconfigure(0,weight=1); dialog.rowconfigure(0,weight=1)
        body=ttk.Frame(dialog,padding=12); body.grid(row=0,column=0,sticky='nsew'); body.columnconfigure(0,weight=1)
        top=ttk.Frame(body); top.grid(row=0,column=0,sticky='ew'); top.columnconfigure(0,weight=1)
        ttk.Label(top,text='Mounted card',style='Dashboard.TLabel').grid(row=0,column=0,columnspan=3,sticky='w')
        choices=ttk.Combobox(top,textvariable=selected,state='readonly',width=48,style='ConnectionCard.TCombobox'); choices.grid(row=1,column=0,sticky='ew',pady=(3,0))
        card_label=tk.Label(top,textvariable=card_state,font=('Segoe UI',12,'bold'),foreground='#b91c1c'); card_label.grid(row=2,column=0,columnspan=3,sticky='w',pady=(8,0))
        card_info=ttk.Frame(top); card_info.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(4,0)); card_info.columnconfigure(1,weight=1)
        ttk.Label(card_info,text='Current card mode',style='Dashboard.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Label(card_info,textvariable=saved_mode,style='Dashboard.TLabel').grid(row=0,column=1,sticky='w',padx=(8,24))
        ttk.Label(card_info,text='Installed firmware',style='Dashboard.TLabel').grid(row=0,column=2,sticky='w')
        ttk.Label(card_info,textvariable=firmware,style='Dashboard.TLabel').grid(row=0,column=3,sticky='w',padx=(8,0))
        save_button=None; mode_button=None; mode_menu=None
        mode_choices=(('Direct Connection (Card Hotspot)','4'),('Client Mode','5'))
        def selected_mode_code(): return dict(mode_choices).get(mode.get(),'')
        def apply_credential_labels(mode_code):
            if mode_code == '4':
                credential_name.set('Hotspot name (SSID)'); credential_password.set('Hotspot password')
            else:
                credential_name.set('Wi-Fi network name'); credential_password.set('Wi-Fi password')
        def choose_mode(label):
            current=selected_mode_code(); target=dict(mode_choices).get(label,'')
            if current and target != current: draft_profiles[current]=(ssid.get(),password.get())
            mode.set(label)
            apply_credential_labels(target)
            mode_detail.set(flashair_mode_presentation(target)[1])
            update_mode_detail_visibility()
            if target:
                # Never reuse fields from another wireless mode.  A first-time hotspot
                # profile starts with the safe, documented SSID preference and no key.
                next_ssid,next_password=draft_profiles.get(target,('flashair','') if target == '4' else ('',''))
                ssid.set(next_ssid); password.set(next_password)
                appname.set((self._mode_appname(profile_key,target) if target == '5' and profile_key else '') or ('openflashair' if target == '5' else ''))
                endpoint.set('http://192.168.0.1/' if target == '4' else (self._mode_endpoint(profile_key,'5') if profile_key else ''))
                endpoint_entry.configure(state='readonly' if target == '4' else 'normal')
                sync_advanced_visibility(target)
            refresh_dirty()
        def rebuild_mode_menu():
            """A Tk Menu supports a truly disabled current item; ttk.Combobox does not."""
            if mode_menu is None: return
            mode_menu.delete(0,'end'); saved_code=loaded.get('APPMODE','')
            for label,code in mode_choices:
                if code == saved_code:
                    mode_menu.add_command(label=f'{label} (Current)',state='disabled')
                else:
                    mode_menu.add_command(label=label,command=lambda value=label:choose_mode(value))
            if saved_code in {'4','5'} and selected_mode_code() != saved_code:
                mode_menu.add_separator()
                saved_label=dict((code,label) for label,code in mode_choices)[saved_code]
                mode_menu.add_command(label='Revert to saved mode',command=lambda value=saved_label:choose_mode(value))
        def refresh_dirty(*_args):
            if save_button is None: return
            mode_code=selected_mode_code()
            changed=bool(loaded and mode_code and ConfigEditor.has_connection_changes(loaded,mode_code,ssid.get(),password.get()))
            save_button.configure(state=('normal' if changed else 'disabled'))
            if not loaded: pending_mode.set('Pending changes: None')
            elif not mode_code: pending_mode.set('Pending changes: None')
            elif mode_code == loaded.get('APPMODE',''): pending_mode.set('Pending changes: None')
            else: pending_mode.set(f'Pending change: Switch to {flashair_mode_presentation(mode_code)[0]}')
            rebuild_mode_menu()
        def inspect():
            try:
                editor=ConfigEditor(selected.get()); doc=editor.inspect(); values=doc.values(); loaded.clear(); loaded.update(values); loaded['path']=str(editor.path)
                location.set(f'Card location: {editor.path}'); ssid.set(values.get('APPSSID','(not set)')); password.set(values.get('APPNETWORKKEY','')); appname.set(values.get('APPNAME','')); endpoint.set(self.endpoint.get()); firmware.set(values.get('VERSION','(not reported)'))
                actual_mode=values.get('APPMODE'); friendly_mode,description=flashair_mode_presentation(actual_mode); saved_mode.set(friendly_mode); card_state.set('READY'); card_label.configure(foreground='#15803d'); mode_detail.set(description); update_mode_detail_visibility()
                nonlocal profile_key
                profile_key=self._credential_profile_key(values,editor.path); draft_profiles.clear()
                if actual_mode in {'4','5'}:
                    self._remember_mode_profile(profile_key,actual_mode,values.get('APPSSID',''),values.get('APPNETWORKKEY',''),values.get('APPNAME',''))
                    draft_profiles[actual_mode]=(values.get('APPSSID',''),values.get('APPNETWORKKEY',''))
                    # A just-completed hotspot save still has the AP endpoint in
                    # the main window; never overwrite the saved Client profile
                    # with that value during verified readback.
                    if actual_mode == '5' and self.endpoint.get().rstrip('/') != 'http://192.168.0.1': self._remember_mode_endpoint(profile_key,'5',self.endpoint.get())
                for mode_code in ('4','5'):
                    saved_ssid,saved_password=self._mode_profile(profile_key,mode_code)
                    if saved_ssid or saved_password is not None: draft_profiles.setdefault(mode_code,(saved_ssid,saved_password if saved_password is not None else ''))
                mode.set({'4':'Direct Connection (Card Hotspot)','5':'Client Mode'}.get(actual_mode,f'Unsupported mode ({actual_mode or "not set"})'))
                sync_advanced_visibility(actual_mode)
                set_editing_enabled(True,actual_mode)
                apply_credential_labels(actual_mode)
                status.set('Settings loaded.'); refresh_dirty()
            except Exception as exc:
                loaded.clear(); location.set(f'Card location: {selected.get() or "—"}'); ssid.set(''); password.set(''); appname.set(''); endpoint.set(''); firmware.set('—'); mode.set('No card selected'); mode_detail.set(''); update_mode_detail_visibility(); card_state.set('NOT INSERTED'); card_label.configure(foreground='#b91c1c'); saved_mode.set('—'); set_editing_enabled(False); status.set(f'No readable FlashAir CONFIG: {type(exc).__name__}: {exc}'); refresh_dirty()
        def detect():
            found=[str(path) for path in ConfigEditor.detect_cards()]; choices.configure(values=found)
            if len(found)==1: selected.set(found[0]); inspect()
            elif found: status.set(f'{len(found)} CONFIG files detected; select one and inspect.')
            else:
                selected.set(''); loaded.clear(); location.set('Card location: —'); ssid.set(''); password.set(''); appname.set(''); endpoint.set(''); firmware.set('—'); mode.set('No card selected'); mode_detail.set(''); update_mode_detail_visibility(); card_state.set('NOT INSERTED'); card_label.configure(foreground='#b91c1c'); saved_mode.set('—'); set_editing_enabled(False); status.set('No readable FlashAir CONFIG detected. Use Choose drive/folder.'); refresh_dirty()
        def choose():
            path=filedialog.askdirectory(parent=dialog,title='Select FlashAir card root or SD_WLAN folder')
            if path: selected.set(path); inspect()
        ttk.Button(top,text='Detect cards',command=detect,style='ConnectionCard.TButton').grid(row=1,column=1,padx=(8,3),pady=(3,0)); ttk.Button(top,text='Choose drive/folder',command=choose,style='ConnectionCard.TButton').grid(row=1,column=2,pady=(3,0))
        choices.bind('<<ComboboxSelected>>',lambda _event:inspect())
        ttk.Label(body,text='Connection mode',style='Dashboard.TLabel').grid(row=1,column=0,sticky='w',pady=(16,0)); mode_button=tk.Menubutton(body,textvariable=mode,font=('Segoe UI',12),background='white',foreground='black',activebackground='#f8fafc',relief='sunken',bd=1,anchor='w',padx=8,pady=10,cursor='hand2'); mode_menu=tk.Menu(mode_button,tearoff=False,font=('Segoe UI',12)); mode_button.configure(menu=mode_menu); mode_button.grid(row=2,column=0,sticky='ew',pady=(3,0))
        mode_detail_label=ttk.Label(body,textvariable=mode_detail,wraplength=720,style='Dashboard.TLabel'); mode_detail_label.grid(row=3,column=0,sticky='w',pady=(4,0))
        ttk.Label(body,textvariable=pending_mode,wraplength=720,style='Dashboard.TLabel').grid(row=4,column=0,sticky='w',pady=(3,0))
        def update_mode_detail_visibility():
            """Do not reserve a blank explanatory line before Pending changes."""
            if mode_detail.get().strip(): mode_detail_label.grid()
            else: mode_detail_label.grid_remove()
        ttk.Label(body,textvariable=credential_name,style='Dashboard.TLabel').grid(row=5,column=0,sticky='w',pady=(14,0)); ssid_entry=tk.Entry(body,textvariable=ssid,background='white',foreground='black',font=('Segoe UI',12),relief='sunken',bd=1,width=42); ssid_entry.grid(row=6,column=0,sticky='ew',pady=(3,0),ipady=7)
        ttk.Label(body,textvariable=credential_password,style='Dashboard.TLabel').grid(row=7,column=0,sticky='w',pady=(14,0)); password_entry=tk.Entry(body,textvariable=password,background='white',foreground='black',font=('Segoe UI',12),relief='sunken',bd=1,show='•',width=42); password_entry.grid(row=8,column=0,sticky='ew',pady=(3,0),ipady=7)
        def toggle_password(): password_entry.configure(show='' if reveal.get() else '•')
        show_password_toggle=ttk.Checkbutton(body,text='Show password',variable=reveal,command=toggle_password); show_password_toggle.grid(row=9,column=0,sticky='w',pady=(4,0))
        advanced_toggle=ttk.Checkbutton(body,text='Advanced settings',variable=advanced_visible); advanced_toggle.grid(row=10,column=0,sticky='w',pady=(12,0))
        appname_label=ttk.Label(body,text='Client FlashAir name',style='Dashboard.TLabel'); appname_label.grid(row=11,column=0,sticky='w',pady=(10,0)); appname_entry=tk.Entry(body,textvariable=appname,background='#e9ecef',foreground='black',font=('Segoe UI',12),relief='sunken',bd=1,width=42,state='readonly'); appname_entry.grid(row=12,column=0,sticky='ew',pady=(3,0),ipady=7)
        endpoint_label=ttk.Label(body,text='FlashAir endpoint',style='Dashboard.TLabel'); endpoint_label.grid(row=13,column=0,sticky='w',pady=(10,0)); endpoint_entry=tk.Entry(body,textvariable=endpoint,background='white',foreground='black',font=('Segoe UI',12),relief='sunken',bd=1,width=42); endpoint_entry.grid(row=14,column=0,sticky='ew',pady=(3,0),ipady=7)
        def sync_advanced_visibility(mode_code=None):
            active=selected_mode_code() if mode_code is None else mode_code
            show=advanced_visible.get()
            for widget in (endpoint_label,endpoint_entry): (widget.grid if show else widget.grid_remove)()
            for widget in (appname_label,appname_entry): (widget.grid if show and active == '5' else widget.grid_remove)()
            if loaded:
                endpoint_entry.configure(state='readonly' if active == '4' else 'normal')
        def set_editing_enabled(enabled,mode_code=None):
            """A remembered path is not permission to edit: CONFIG must be readable now."""
            active=selected_mode_code() if mode_code is None else mode_code
            state='normal' if enabled else 'disabled'
            mode_button.configure(state=state)
            ssid_entry.configure(state=state)
            password_entry.configure(state=state)
            show_password_toggle.configure(state=state)
            advanced_toggle.configure(state=state)
            appname_entry.configure(state='readonly' if enabled else 'disabled')
            endpoint_entry.configure(state=('readonly' if active == '4' else 'normal') if enabled else 'disabled')
        advanced_toggle.configure(command=sync_advanced_visibility)
        ttk.Label(body,textvariable=status,wraplength=720,style='Dashboard.TLabel').grid(row=15,column=0,sticky='w',pady=(14,0))
        def save():
            if not loaded: status.set('Load a mounted card before saving.'); return
            target_mode=selected_mode_code()
            if not target_mode: status.set('Unsupported APPMODE is preserved; choose a supported mode only after reviewing the saved card mode.'); return
            original_password=loaded.get('APPNETWORKKEY',''); proposed_password=password.get()
            # FlashAir may mask a stored key with asterisks after restart. Never write that placeholder back.
            password_change=None if proposed_password==original_password and original_password and set(original_password)=={'*'} else proposed_password
            restored_appname='' if target_mode == '4' else (appname.get().strip() or self._mode_appname(profile_key,'5') or 'openflashair')
            if target_mode == '5': appname.set(restored_appname)
            detail=restored_appname if target_mode == '5' else 'removed for Hotspot mode'
            if not messagebox.askyesno('Confirm CONFIG change',f'Change connection settings on:\n{loaded["path"]}\n\nClient FlashAir name (APPNAME): {detail}\n\nThis writes the mounted card and may require reconnecting to a different Wi-Fi network. Continue?',parent=dialog): return
            try:
                result=ConfigEditor(loaded['path']).save_connection_settings(target_mode,ssid.get(),password_change,appname=restored_appname or None)
                if result['changed']:
                    inspect(); status.set(f"Verified save complete. PC backup:\n{str(result['backup']).replace('\\\\','\\\\\n')}")
                    active_endpoint='http://192.168.0.1/' if target_mode == '4' else endpoint.get().strip()
                    if target_mode == '5' and active_endpoint.rstrip('/') == 'http://192.168.0.1': active_endpoint=''
                    if target_mode == '5' and self._valid_endpoint(active_endpoint): self._remember_mode_endpoint(profile_key,'5',active_endpoint)
                    if self._valid_endpoint(active_endpoint):
                        self.endpoint.set(active_endpoint); self.endpoint_entry.configure(state='readonly' if target_mode == '4' else 'normal',readonlybackground='#e9ecef'); self._save_connection_settings()
                    elif target_mode == '5':
                        self.endpoint.set(''); self.endpoint_entry.configure(state='normal'); self._save_connection_settings()
                        status.set('Verified Client Mode save complete. Awaiting card restart and Client-network discovery; enter a manual address in Advanced settings only if discovery fails.')
                        self.status.set('Client Mode awaiting discovery — card restart and Client-network discovery required.')
                else: status.set('No changes were needed.')
                refresh_dirty()
            except ValueError as exc:
                advanced_visible.set(True); sync_advanced_visibility(target_mode); status.set(f'Cannot save Client Mode: {exc}')
            except Exception as exc: status.set(f'Save not confirmed: {type(exc).__name__}: {exc}')
        footer=ttk.Frame(body); footer.grid(row=16,column=0,sticky='ew',pady=(18,0)); footer.columnconfigure(0,weight=1)
        ttk.Button(footer,text='Cancel',command=dialog.destroy,style='Large.TButton').grid(row=0,column=0,sticky='w')
        save_button=ttk.Button(footer,text='Save connection settings…',command=save,state='disabled',style='Large.TButton'); save_button.grid(row=0,column=1,sticky='e')
        for variable in (mode,ssid,password,appname,endpoint): variable.trace_add('write',refresh_dirty)
        dialog.protocol('WM_DELETE_WINDOW',dialog.destroy)
        def center():
            dialog.update_idletasks(); owner=self.winfo_toplevel(); width,height=dialog_target_width,dialog.winfo_reqheight(); screen_w,screen_h=dialog.winfo_screenwidth(),dialog.winfo_screenheight(); width=min(width,max(dialog_min_width,screen_w-40)); height=min(780,max(640,height),max(360,screen_h-80))
            x=max(0,min(owner.winfo_rootx()+(owner.winfo_width()-width)//2,screen_w-width)); y=max(0,min(owner.winfo_rooty()+(owner.winfo_height()-height)//2,screen_h-height))
            dialog.geometry(f'{width}x{height}+{x}+{y}'); dialog.deiconify(); dialog.lift()
        # Keep every CONFIG-mutating widget inert until inspection proves that the
        # selected media contains a readable CONFIG file.
        set_editing_enabled(False)
        sync_advanced_visibility()
        update_mode_detail_visibility()
        dialog.after_idle(detect); dialog.after_idle(center)
    def _settings_path(self):
        """One canonical app-settings file; legacy destination-local settings are migrated once."""
        root=Path(os.environ.get('APPDATA',Path.home()/'AppData'/'Roaming'))
        return root/'OpenFlashAir'/'ui-settings.json'
    def _legacy_settings_path(self):
        return Path.home()/'Pictures'/'OpenFlashAir'/'.openflashair-staging'/'ui-settings.json'
    def _settings(self):
        try: return json.loads(self._settings_path().read_text(encoding='utf-8'))
        except Exception:
            try: return json.loads(self._legacy_settings_path().read_text(encoding='utf-8'))
            except Exception: return {}
    def _save_settings(self,**changes):
        try:
            settings=self._settings(); settings.update(changes); path=self._settings_path(); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(settings),encoding='utf-8'); return True
        except OSError: return False
    def _display_timestamp(self,value):
        return format_timestamp(value,self.date_format,self.time_format)
    def date_time_settings(self):
        dialog=tk.Toplevel(self); dialog.title('Date & Time Display'); dialog.transient(self.winfo_toplevel())
        body=ttk.Frame(dialog,padding=16); body.grid(sticky='nsew')
        date=tk.StringVar(value=self.date_format); clock=tk.StringVar(value=self.time_format); example=tk.StringVar()
        ttk.Label(body,text='Date format',style='Dashboard.TLabel').grid(row=0,column=0,sticky='w',pady=4)
        ttk.Combobox(body,textvariable=date,values=tuple(DATE_FORMATS),state='readonly').grid(row=0,column=1,sticky='ew',padx=10)
        ttk.Label(body,text='Time format',style='Dashboard.TLabel').grid(row=1,column=0,sticky='w',pady=4)
        ttk.Combobox(body,textvariable=clock,values=tuple(TIME_FORMATS),state='readonly').grid(row=1,column=1,sticky='ew',padx=10)
        ttk.Label(body,textvariable=example,style='Dashboard.TLabel').grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
        def preview(*_): example.set('Example: '+format_timestamp(datetime(2026,10,19,21,7,6),date.get(),clock.get()))
        date.trace_add('write',preview); clock.trace_add('write',preview); preview()
        def save():
            if not self._save_settings(date_display_format=date.get(),time_display_format=clock.get()):
                messagebox.showerror('Date & Time Display','Could not save preferences.',parent=dialog); return
            self.date_format=date.get(); self.time_format=clock.get()
            for tile in self._tiles_by_path.values():
                self.gallery_canvas.itemconfigure(tile['capture_value'],text=self._display_timestamp(tile.get('capture_raw')))
            for window in self._metadata_dialogs.values():
                for field,value in getattr(window,'_timestamp_values',{}).items(): window._metadata_values[field].set(self._display_timestamp(value))
            if getattr(self,'_connection_checked_at',None): self.connection_checked.set('Last checked: '+self._display_timestamp(self._connection_checked_at))
            dialog.destroy()
        ttk.Button(body,text='Cancel',command=dialog.destroy).grid(row=3,column=0,sticky='w')
        ttk.Button(body,text='Save',command=save).grid(row=3,column=1,sticky='e')
        dialog.after_idle(lambda:center_popup(dialog,self.winfo_toplevel()))
    def _load_interval(self):
        try:
            value=int(self._settings().get('poll_interval',60))
            return value if value in (10,30,60,120,300,600) else 60
        except Exception: return 60
    def _load_log_expanded(self): return bool(self._settings().get('log_expanded',False))
    def _interval_changed(self,_event=None):
        try: value=int(self.interval_label.get().removesuffix('s'))
        except ValueError: value=60
        self.interval.set(value); self.interval_label.set(f'{value}s')
        self._save_settings(poll_interval=value)
        self.add(f'Polling interval set to {self.interval.get()} seconds')
        if self.auto and not self.scanning: self._schedule_next()
    def toggle_log(self):
        self.log_expanded=not self.log_expanded; self._save_settings(log_expanded=self.log_expanded); self._apply_log_state()
    def _apply_log_state(self):
        self._render_log_header()
        panes={str(pane) for pane in self.content_pane.panes()}
        if self.log_expanded and str(self.log_frame) not in panes:
            self.content_pane.add(self.log_frame,minsize=150)
            self._schedule_log_sash()
        elif not self.log_expanded and str(self.log_frame) in panes:
            self.content_pane.forget(self.log_frame)
        self._schedule_gallery_layout()
    def _log_header_enter(self,_event): self._log_header_hover=True; self._render_log_header()
    def _log_header_leave(self,_event): self._log_header_hover=False; self._render_log_header()
    def _render_log_header(self):
        """A compact canvas header gives the chevron a real graphical treatment."""
        canvas=self.log_header; canvas.delete('all')
        background='#e9eef5' if self._log_header_hover else '#f0f0f0'
        canvas.configure(background=background)
        if self.log_expanded:
            points=(9,19,19,19,14,10)  # upward triangle: clicking collapses the pane
        else:
            points=(9,11,19,11,14,20)  # downward triangle: clicking expands the pane
        canvas.create_polygon(points,fill='#334155',outline='')
        canvas.create_text(29,15,text='Activity Log',anchor='w',fill='#334155',font=('Segoe UI',10,'bold'))
        if self.log_error_count:
            canvas.create_text(130,15,text=f'⚠ {self.log_error_count}',anchor='w',fill='#a16207',font=('Segoe UI',10))
    def _place_log_sash(self):
        """Give the log a predictable initial height without constraining a later drag."""
        self._sash_after=None
        if not self.content_pane.winfo_exists() or len(self.content_pane.panes()) < 2: return
        height=self.content_pane.winfo_height()
        if height > 0:
            self.content_pane.sash_place(0,0,max(220,height-self._log_height))
    def _pane_resized(self,_event=None):
        """Window height belongs to the gallery; the log keeps its current drag height."""
        height=self.content_pane.winfo_height()
        if self.log_expanded and len(self.content_pane.panes()) >= 2 and self._pane_height is not None and height != self._pane_height:
            self._schedule_log_sash()
        self._pane_height=height
    def _schedule_log_sash(self):
        if getattr(self,'_closing',False): return
        if self._sash_after: self.after_cancel(self._sash_after)
        self._sash_after=self.after_idle(self._place_log_sash)
    def _remember_log_height(self,_event=None):
        if self.log_expanded and len(self.content_pane.panes()) >= 2:
            _x,y=self.content_pane.sash_coord(0)
            self._log_height=max(150,self.content_pane.winfo_height()-y)
    def _refresh_gallery_geometry(self):
        """The pane changes canvas dimensions; recalculate both its window and scroll range."""
        self._relayout_gallery()
    def add(self,s):
        import datetime
        line=f"{datetime.datetime.now().isoformat(timespec='seconds')} {s}"
        try:
            diagnostic=self._settings_path().with_name('diagnostics.log'); diagnostic.parent.mkdir(parents=True,exist_ok=True)
            with diagnostic.open('a',encoding='utf-8') as handle: handle.write(line+'\n')
        except OSError: pass
        self.log.configure(state='normal'); self.log.insert('end',line+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 200: self.log.delete('1.0','2.0')
        self.log.see('end'); self.log.configure(state='disabled')
    def _flag_log_error(self):
        self.log_error_count+=1; self._apply_log_state()
    def work(self,fn):
        def run():
            try: self.after(0,lambda:self.status.set('Working…')); value=fn(); self.after(0,lambda:self.done(value))
            except Exception as exc:self.after(0,lambda exc=exc:self.status.set(f'Actionable error: {exc}'))
        threading.Thread(target=run,daemon=True).start()
    def done(self,v,errors=(),log_result=True):
        self.status.set('Last operation complete'); self.operation.set('Activity: ready')
        if hasattr(v,'discovered'):
            self.scan_counts.set(f'Discovered {v.discovered}  Downloaded {v.downloaded}  Skipped {v.skipped}  Failed {v.failed}')
            for name,value in zip(('Discovered','Downloaded','Skipped','Failed'),(v.discovered,v.downloaded,v.skipped,v.failed)):
                self.counter_values[name].set(str(value))
                self.counter_display[name].set(f'{name}: {value}')
        summary=str(v)
        if hasattr(v,'discovered'):
            summary=f'{v.discovered} found · {v.downloaded} downloaded · {v.skipped} already present · {v.failed} failed'
            self.last_scan.set(f'Last scan: {summary}')
        if log_result: self.add(f'Scan complete: {summary}')
        [self.add(e) for e in errors]
        if errors: self._flag_log_error()
    def check(self):
        """Check availability only; never turn the menu command into a scan."""
        self.connection_status.set('Checking')
        endpoint=self.endpoint.get()
        self.operation.set('Activity: checking connection'); self.status.set('Checking FlashAir connection…')
        def run():
            try: available=FlashAirClient(endpoint).available()
            except Exception as exc: self.after(0,lambda exc=exc:self._connection_check_result(endpoint,None,exc)); return
            self.after(0,lambda:self._connection_check_result(endpoint,available,None))
        threading.Thread(target=run,daemon=True).start()
    def _connection_check_result(self,endpoint,available,error):
        if self.endpoint.get() == endpoint: self._connection_checked(available,error)
    def _connection_checked(self,available,error):
        self._set_connection_status('Connected' if available and error is None else 'Disconnected')
        if error is not None:
            self._set_panel_activity('manual','error','Error'); self.operation.set(f'Activity: connection check failed — {type(error).__name__}'); self.status.set(f'Connection check failed: {type(error).__name__}: {error}'); self.add(f'Connection check failed: {type(error).__name__}: {error}'); self._flag_log_error(); return
        if available:
            self._set_panel_activity('manual','complete','Complete'); self.operation.set('Activity: connection available'); self.status.set('Connection available'); self.add('Connection check: FlashAir available')
        else:
            self._set_panel_activity('manual','error','Error'); self.operation.set('Activity: card unavailable'); self.status.set('Card unavailable (no settings changed)'); self.add('Connection check: FlashAir unavailable')
    def scan(self,automatic=False):
        if not self.endpoint.get().strip():
            self.status.set('Client Mode awaiting discovery — configure or verify a Client address before scanning.'); self.add('Scan not started: Client endpoint is awaiting discovery.'); return
        if self.scanning: self.add('Scan rejected: another scan is in progress'); return
        self.scanning=True; self._operation_failed=False; self._active_scan_automatic=automatic
        scan_endpoint=self.endpoint.get()
        if self._transfer_after is None: self._transfer_after=self.after(250,self._update_transfer_display)
        if automatic:
            self._auto_pause_requested=False; self._next_scan_at=None; self.next_scan.set('In progress…')
        self._set_panel_activity('auto' if automatic else 'manual','active','Scanning'); self.operation.set('Activity: automatic scan in progress' if automatic else 'Activity: manual scan in progress'); self.status.set('Scanning…'); self._update_badges(); self._update_scan_controls()
        def run():
            try:
                engine=self.make_engine()
                self._active_engine=engine
                try: value=engine.scan_now(SyncOptions.photos()); errors=tuple(engine.last_errors); inventory=tuple(engine.last_inventory); network_error=engine.last_network_error
                finally:
                    engine.close()
                    if self._active_engine is engine: self._active_engine=None
                signature=(value.discovered,value.downloaded,value.skipped,value.failed,errors)
                changed=signature != self._last_auto_signature
                if automatic: self._last_auto_signature=signature
                self.after(0,lambda value=value, errors=errors, automatic=automatic, inventory=inventory, network_error=network_error, endpoint=scan_endpoint, log_result=(not automatic or changed or value.downloaded or value.failed):self._scan_complete(value,errors,automatic,inventory,log_result,network_error,endpoint))
            except Exception as exc: self.after(0,lambda exc=exc, automatic=automatic, endpoint=scan_endpoint:self._scan_error(exc,automatic,endpoint))
            finally: self.after(0,lambda automatic=automatic:self._finish_scan(automatic))
        threading.Thread(target=run,daemon=True).start()
    def _scan_complete(self,value,errors,automatic,inventory,log_result,network_error=False,endpoint=None):
        if endpoint is None or endpoint == self.endpoint.get(): self._set_connection_status('Disconnected' if network_error else 'Connected')
        if automatic: self._auto_retry_pending=False
        self.done(value,errors,log_result)
        self._set_panel_activity('auto' if automatic else 'manual','complete','Complete')
        self._reconcile_gallery_inventory(inventory)
        self._refresh_visible_download_indicators()
    def _scan_error(self,exc,automatic=False,endpoint=None):
        if isinstance(exc,FlashAirError) and (endpoint is None or endpoint == self.endpoint.get()): self._set_connection_status('Disconnected')
        if automatic: self._auto_retry_pending=True
        self._operation_failed=True; self._set_panel_activity('auto' if automatic else 'manual','error','Error'); self.operation.set(f'Activity: scan error — {type(exc).__name__}'); self.status.set(f'Scan error: {type(exc).__name__}: {exc}'); self.add(f'Actionable scan error: {type(exc).__name__}: {exc}'); self._flag_log_error()
    def _set_connection_status(self,state):
        self._connection_checked_at=datetime.now(); self.connection_status.set(state); self.connection_checked.set('Last checked: '+self._display_timestamp(self._connection_checked_at))
    def _finish_scan(self,automatic=False):
        self.scanning=False
        if getattr(self,'_closing',False):
            self._finish_close_main_window(); return
        if self._transfer_after is not None: self.after_cancel(self._transfer_after); self._transfer_after=None
        self._update_transfer_display()
        if not self._operation_failed: self.operation.set('Activity: ready')
        self._active_scan_automatic=None; self._update_badges(); self._update_scan_controls()
        if automatic and self.auto: self._schedule_next()
        elif automatic:
            self._auto_pause_requested=False; self.next_scan.set('Next scan: —'); self._set_panel_activity('auto','paused','Paused'); self.operation.set('Activity: paused'); self.status.set('Automatic sync paused')

    def download_selected(self):
        """Download persisted selections in their displayed priority order."""
        if self.scanning:
            self.add('Download Selected rejected: another transfer is in progress'); return
        queue=DownloadQueue(Path(self.destination.get())/'.openflashair-staging'/'selection.sqlite3')
        paths=[row[0] for row in queue.pending()]
        if not paths:
            self.add('Download Selected: no queued photographs'); return
        scan_endpoint=self.endpoint.get()
        self.scanning=True; self._operation_failed=False; self._active_scan_automatic=False; self._set_panel_activity('manual','active','Downloading'); self.operation.set('Activity: downloading selected photographs'); self.status.set('Downloading selected photographs…'); self._update_badges(); self._update_scan_controls()
        if self._transfer_after is None: self._transfer_after=self.after(250,self._update_transfer_display)
        def run():
            try:
                client=FlashAirClient(scan_endpoint)
                available={item.path:item for item in client.discover()}
                remotes=[available[path] for path in paths if path in available]
                missing=[path for path in paths if path not in available]
                engine=SyncEngine(client,Path(self.destination.get()),Path(self.destination.get())/'.openflashair-staging',naming=FilenamePolicy(self.filename_template.get(),self.filename_prefix.get()),progress=self._transfer_event)
                try:
                    value=engine.download_files(remotes,SyncOptions.photos())
                    errors=tuple(engine.last_errors) + tuple(f'{path}: no longer listed on card' for path in missing); network_error=engine.last_network_error
                finally: engine.close()
                self.after(0,lambda value=value, errors=errors,network_error=network_error,endpoint=scan_endpoint:self._selected_download_complete(value,errors,network_error,endpoint))
            except Exception as exc: self.after(0,lambda exc=exc,endpoint=scan_endpoint:self._selected_error(exc,endpoint))
            finally: self.after(0,self._finish_scan)
        threading.Thread(target=run,daemon=True).start()
    def _selected_error(self,exc,endpoint=None):
        if isinstance(exc,FlashAirError) and (endpoint is None or endpoint == self.endpoint.get()): self._set_connection_status('Disconnected')
        self._operation_failed=True; self._set_panel_activity('manual','error','Error'); self.operation.set(f'Activity: download error — {type(exc).__name__}'); self.status.set(f'Download error: {type(exc).__name__}: {exc}'); self.add(f'Actionable selected-download error: {type(exc).__name__}: {exc}'); self._flag_log_error()
    def _selected_download_complete(self,value,errors,network_error=False,endpoint=None):
        if endpoint is None or endpoint == self.endpoint.get(): self._set_connection_status('Disconnected' if network_error else 'Connected')
        self.done(value,errors); self._set_panel_activity('manual','complete','Complete'); self._refresh_visible_download_indicators()
    def start_auto(self):
        if self.auto: return
        self.auto=True; self._auto_pause_requested=False; self._auto_has_started=True; self._update_auto_control_label(); self._set_panel_activity('auto','active','Scanning'); self.status.set('Auto-sync active — scanning now'); self.add('Automatic sync started'); self._begin_auto_cycle()
    def _begin_auto_cycle(self):
        if not self.auto: return
        if self.scanning:
            self._set_panel_activity('auto','waiting','Waiting'); self.operation.set('Activity: auto-sync waiting for current operation')
            self._poll_after=self.after(1000,self._begin_auto_cycle); return
        self.scan(automatic=True)
    def _schedule_next(self):
        if not self.auto: return
        self._next_scan_at=time.monotonic()+self.interval.get(); self._set_panel_activity('auto','waiting','Waiting'); self._update_countdown()
        self._poll_after=self.after(self.interval.get()*1000,self._begin_auto_cycle)
    def _update_countdown(self):
        if not self.auto or self._next_scan_at is None: return
        remaining=max(0,int(self._next_scan_at-time.monotonic()+.999)); prefix='Retry in' if self._auto_retry_pending else 'Next scan'; self.next_scan.set(f'{prefix}: {remaining}s'); self.status.set(f'Auto-sync active — {prefix.lower()} {remaining}s')
        self._countdown_after=self.after(1000,self._update_countdown)
    def pause(self):
        if self.auto:
            self.auto=False
            for ident in (self._poll_after,self._countdown_after):
                if ident: self.after_cancel(ident)
            self._poll_after=self._countdown_after=None; self._next_scan_at=None; self.next_scan.set('Next scan: —')
            if self.scanning and self._active_scan_automatic:
                self._auto_pause_requested=True
                if self._active_engine is not None: self._active_engine.pause()
                self.operation.set('Activity: pausing automatic scan'); self.status.set('Pausing automatic scan…'); self._set_panel_activity('auto','active','Pausing…'); self.add('Automatic sync pause requested')
            else:
                self.operation.set('Activity: paused'); self.status.set('Automatic sync paused'); self._set_panel_activity('auto','paused','Paused'); self.add('Automatic sync paused')
            self._update_auto_control_label(); self._update_scan_controls()
        else: self.start_auto()
    def refresh_gallery(self):
        """Discover once; page changes reuse that result and the thumbnail cache."""
        self._gallery_generation += 1; generation=self._gallery_generation
        self.operation.set('Activity: refreshing gallery'); self.status.set('Loading gallery…')
        def worker():
            try:
                files=[f for f in FlashAirClient(self.endpoint.get()).discover() if SyncOptions.jpeg_only().accepts(f)]
                self.after(0,lambda:self._set_gallery_files(generation,files))
            except Exception as exc: self.after(0,lambda exc=exc:self._gallery_error(exc))
        threading.Thread(target=worker,daemon=True).start()

    def _set_gallery_files(self,generation,files):
        if generation != self._gallery_generation: return
        self.gallery_files=list(files); self._sort_gallery_files(); self.loaded=[item.path for item in self.gallery_files]
        self.gallery_page=min(self.gallery_page,gallery_page_count(len(self.gallery_files))-1)
        self.gallery_summary.set(f'Gallery: {len(self.gallery_files)} photographs'); self.add(f'Gallery refreshed: {len(self.gallery_files)} photographs')
        if not self.scanning and not self.auto:
            self.status.set('Ready'); self.operation.set('Activity: ready')
        self._show_gallery_page()

    def _reconcile_gallery_inventory(self,inventory):
        """Use a completed scan's inventory; never scan again merely to update the gallery."""
        incoming=[item for item in inventory if SyncOptions.jpeg_only().accepts(item)]
        if not self.gallery_files:
            # Do not replace a deliberately empty, never-opened gallery until auto-sync discovers photos.
            if incoming: self.gallery_files=incoming; self._sort_gallery_files(); self.loaded=[item.path for item in self.gallery_files]; self.gallery_summary.set(f'Gallery: {len(self.gallery_files)} photographs'); self.add(f'Found {len(incoming)} photographs'); self._show_gallery_page()
            return
        old={item.path:(item.size,item.modified_utc) for item in self.gallery_files}; new={item.path:(item.size,item.modified_utc) for item in incoming}
        if old == new:
            return
        prior_page_paths=[item.path for item in gallery_page_slice(self.gallery_files,self.gallery_page)[1]]
        new_count=len(set(new)-set(old)); self.gallery_files=incoming; self._sort_gallery_files(); self.loaded=[item.path for item in self.gallery_files]
        self.gallery_page=min(self.gallery_page,gallery_page_count(len(self.gallery_files))-1); self.gallery_summary.set(f'Gallery: {len(self.gallery_files)} photographs')
        current_page_paths=[item.path for item in gallery_page_slice(self.gallery_files,self.gallery_page)[1]]
        if new_count:
            suffix='' if new_count == 1 else 's'
            self.add(f'Found {new_count} new photograph{suffix}')
        if current_page_paths != prior_page_paths: self._show_gallery_page(preserve_scroll=True)
        else: self._refresh_visible_download_indicators()

    @staticmethod
    def _gallery_timestamp(item):
        return item.modified_utc.timestamp() if item.modified_utc is not None else None

    def _sort_gallery_files(self):
        """Sort only display inventory; queue identity and priority stay path-based."""
        if self.sort_order.get() == 'Oldest first':
            self.gallery_files.sort(key=lambda item:(item.modified_utc is None,App._gallery_timestamp(item) or 0,item.path.casefold()))
        else:
            self.gallery_files.sort(key=lambda item:(item.modified_utc is None,-(App._gallery_timestamp(item) or 0),item.path.casefold()))

    def _sort_changed(self,_event=None):
        self._sort_gallery_files(); self.gallery_page=0; self._show_gallery_page()

    def _change_page(self,delta):
        pages=gallery_page_count(len(self.gallery_files))
        target=min(max(0,self.gallery_page+delta),pages-1)
        if target != self.gallery_page:
            self.gallery_page=target; self._show_gallery_page()

    def _show_gallery_page(self,preserve_scroll=False):
        """Replace page items only; discovery, selections, and thumbnail cache remain intact."""
        self._gallery_generation += 1; generation=self._gallery_generation
        page,items=gallery_page_slice(self.gallery_files,self.gallery_page)
        self.gallery_page=page; pages=gallery_page_count(len(self.gallery_files))
        self.page_text.set(f'Page {page+1} of {pages}')
        self.previous_page_button.configure(state=('normal' if page else 'disabled'))
        self.next_page_button.configure(state=('normal' if page+1 < pages else 'disabled'))
        self._tiles_by_path={}
        self.gallery_canvas.delete('all')
        for item in items: self._create_gallery_tile(item)
        self._update_badges(); self._refresh_visible_download_indicators(); self._reset_gallery_scroll=not preserve_scroll; self._schedule_gallery_layout()
        if not items: return
        local_paths={path:local for path,(local,_record) in self._verified_downloads(items).items() if local}
        endpoint=self.endpoint.get()
        if self._thumbnail_client is None or self._thumbnail_endpoint != endpoint:
            self._thumbnail_client=ThumbnailClient(endpoint,concurrency=2); self._thumbnail_endpoint=endpoint
        def worker():
            for item in items:
                if generation != self._gallery_generation: return
                if item.path in local_paths:
                    capture=local_capture_time(local_paths[item.path])
                    if capture: self.after(0,lambda path=item.path,value=capture:self._set_tile_capture_time(generation,path,value))
                thumb=self._thumbnail_client.get(item.path,item.size,item.modified_utc.isoformat() if item.modified_utc else None)
                self.after(0,lambda f=item,t=thumb:self._put_thumbnail(generation,f,t))
        threading.Thread(target=worker,daemon=True).start()
    def _gallery_error(self,exc):
        self.add(f'Gallery error: {type(exc).__name__}: {exc}'); self._flag_log_error()
    def _create_gallery_tile(self,item):
        """Create stable Canvas primitives for a tile; no embedded child widgets are used."""
        path=item.path
        tag=f'gallery-tile-{len(self._tiles_by_path)}'
        metadata_tag=f'gallery-metadata-{len(self._tiles_by_path)}'
        tile={'path':path,'item':item,'tag':tag,'photo':None,'source_image':None}
        tile['border']=self.gallery_canvas.create_rectangle(0,0,1,1,fill='#f4f4f4',outline='#f4f4f4',width=1,tags=(tag,))
        tile['placeholder']=self.gallery_canvas.create_text(0,0,text='Loading preview…',fill='#475569',font=('Segoe UI',9),tags=(tag,))
        tile['filename']=self.gallery_canvas.create_text(0,0,text=Path(path).name[:30],fill='#0f172a',font=('Segoe UI',9,'underline'),width=120,justify='center',tags=(metadata_tag,))
        tile['capture_raw']=item.modified_utc
        fallback=self._display_timestamp(item.modified_utc)
        tile['capture']=self.gallery_canvas.create_text(0,0,text='FlashAir timestamp',fill='#475569',font=('Segoe UI',8),width=120,justify='center',tags=(tag,))
        tile['capture_value']=self.gallery_canvas.create_text(0,0,text=fallback,fill='#475569',font=('Segoe UI',8),width=120,justify='center',tags=(tag,))
        # These items share the tile tag, so a click on the status badge follows
        # the same selection path as a click on the thumbnail itself.
        tile['download_check_shape']=self.gallery_canvas.create_oval(0,0,1,1,fill='#15803d',outline='#e2e8f0',width=2,state='hidden',tags=(tag,))
        # A Canvas line stays crisp at the current Tk/Windows display scale; a
        # font glyph was visibly pixelated on some Windows displays.
        tile['download_check_mark']=self.gallery_canvas.create_line(0,0,1,1,1,1,fill='white',width=3,capstyle='round',joinstyle='round',state='hidden',tags=(tag,))
        tile['badge_shape']=self.gallery_canvas.create_oval(0,0,1,1,fill='#075985',outline='',state='hidden',tags=(tag,))
        tile['badge_text']=self.gallery_canvas.create_text(0,0,text='',fill='white',font=('Segoe UI',10,'bold'),state='hidden',tags=(tag,))
        self.gallery_canvas.tag_bind(tag,'<Button-1>',lambda _event,p=path:self._tile_single_click(p))
        self.gallery_canvas.tag_bind(tag,'<Double-Button-1>',lambda _event,p=path:self._tile_double_click(p))
        self.gallery_canvas.tag_bind(metadata_tag,'<Button-1>',lambda _event,p=path:self.show_metadata(p))
        self._tiles_by_path[path]=tile

    def _set_tile_capture_time(self,generation,path,value):
        if generation != self._gallery_generation: return
        tile=self._tiles_by_path.get(path)
        if tile:
            tile['capture_raw']=value
            self.gallery_canvas.itemconfigure(tile['capture'],text='EXIF timestamp')
            self.gallery_canvas.itemconfigure(tile['capture_value'],text=self._display_timestamp(value))

    def _put_thumbnail(self,generation,item,thumb):
        if generation != self._gallery_generation: return
        tile=self._tiles_by_path.get(item.path)
        if tile is None: return
        if thumb.state == 'ok':
            try:
                from PIL import Image
                image=Image.open(io.BytesIO(thumb.data)); image.load()
                tile['source_image']=image.copy()
                if 'width' in tile: self._render_tile_image(tile)
            except Exception as exc:
                self.add(f'Preview render failed for {Path(item.path).name}: {type(exc).__name__}: {exc}')
                self.gallery_canvas.itemconfigure(tile['placeholder'],text='Preview unavailable')
        else: self.gallery_canvas.itemconfigure(tile['placeholder'],text='No preview')
    def _gallery_resize(self,event):
        if getattr(self,'_closing',False): return
        if self._resize_after: self.after_cancel(self._resize_after)
        self._resize_after=self.after(120,self._schedule_gallery_layout)
    def _gallery_mousewheel(self,event):
        """One handler owns wheel scrolling for canvas and every tile; no global binding leaks."""
        steps=-int(event.delta/120)
        if steps: self._gallery_scroll_command('scroll',steps,'units')
        return 'break'
    def _gallery_scroll_command(self,*args):
        """Handle scrollbar ``moveto``/``scroll`` commands and repaint only exposed image labels.

        The direct item renderer has no embedded native label surfaces.  ``moveto`` now
        moves only Canvas-managed primitives, with no tile rebuild or image mutation.
        """
        self.gallery_canvas.yview(*args)
    def _schedule_gallery_layout(self):
        """Coalesce geometry changes instead of rebuilding while canvas scrolling is active."""
        if getattr(self,'_closing',False): return
        if self._resize_after:
            self.after_cancel(self._resize_after); self._resize_after=None
        if self._layout_after: self.after_cancel(self._layout_after)
        self._layout_after=self.after_idle(self._relayout_gallery)
    def _relayout_gallery(self):
        self._layout_after=None
        prior_y=self.gallery_canvas.yview()[0]
        width=max(self.gallery_canvas.winfo_width(),1); columns=5 if width>=700 else (3 if width>=420 else 2)
        tile_width=max(120, (width - (columns * 4)) // columns)
        preview_height=max(80,int(tile_width*.72)); tile_height=preview_height+62
        for i,tile in enumerate(self._tiles_by_path.values()):
            col=i%columns; row=i//columns; x=col*tile_width; y=row*tile_height
            tile.update(x=x,y=y,width=tile_width,preview_height=preview_height,tile_height=tile_height)
            self.gallery_canvas.coords(tile['border'],x+2,y+2,x+tile_width-2,y+tile_height-2)
            self.gallery_canvas.coords(tile['placeholder'],x+tile_width/2,y+preview_height/2+4)
            self.gallery_canvas.itemconfigure(tile['filename'],width=tile_width-12)
            self.gallery_canvas.coords(tile['filename'],x+tile_width/2,y+preview_height+10)
            self.gallery_canvas.coords(tile['capture'],x+tile_width/2,y+preview_height+28)
            self.gallery_canvas.itemconfigure(tile['capture'],width=tile_width-12)
            self.gallery_canvas.coords(tile['capture_value'],x+tile_width/2,y+preview_height+44)
            self.gallery_canvas.itemconfigure(tile['capture_value'],width=tile_width-12)
            self.gallery_canvas.coords(tile['download_check_shape'],x+7,y+7,x+31,y+31)
            self.gallery_canvas.coords(tile['download_check_mark'],x+12,y+19,x+17,y+24,x+27,y+13)
            self.gallery_canvas.coords(tile['badge_shape'],x+tile_width-31,y+7,x+tile_width-7,y+31)
            self.gallery_canvas.coords(tile['badge_text'],x+tile_width-19,y+19)
            if tile['source_image'] is not None: self._render_tile_image(tile)
            else: self._raise_tile_overlays(tile)
        rows=(len(self._tiles_by_path)+columns-1)//columns
        self.gallery_canvas.configure(scrollregion=(0,0,width,max(self.gallery_canvas.winfo_height(),rows*tile_height)))
        self.gallery_canvas.yview_moveto(0 if getattr(self,'_reset_gallery_scroll',False) else prior_y)
        self._reset_gallery_scroll=False

    def _render_tile_image(self,tile):
        """Update one Canvas image item and keep its PhotoImage alive for its tile lifetime."""
        try:
            from PIL import ImageTk
            image=tile['source_image'].copy(); image.thumbnail((tile['width']-14,tile['preview_height']-10))
            photo=ImageTk.PhotoImage(image); tile['photo']=photo
            if 'image' not in tile:
                tile['image']=self.gallery_canvas.create_image(tile['x']+tile['width']/2,tile['y']+tile['preview_height']/2+4,image=photo,anchor='center',tags=(tile['tag'],))
            else:
                self.gallery_canvas.coords(tile['image'],tile['x']+tile['width']/2,tile['y']+tile['preview_height']/2+4)
                self.gallery_canvas.itemconfigure(tile['image'],image=photo)
            self.gallery_canvas.itemconfigure(tile['placeholder'],state='hidden')
            self._raise_tile_overlays(tile)
        except Exception as exc: self.add(f"Preview resize failed for {Path(tile['path']).name}: {type(exc).__name__}: {exc}")
    def _raise_tile_overlays(self,tile):
        """Keep status and priority overlays above a late-created Canvas image."""
        for key in ('download_check_shape','download_check_mark','badge_shape','badge_text'):
            self.gallery_canvas.tag_raise(tile[key])
    def _tile_single_click(self,path):
        """Defer a normal click briefly so a double-click never changes priority first."""
        pending=self._pending_tile_click.pop(path,None)
        if pending: self.after_cancel(pending)
        self._pending_tile_click[path]=self.after(220,lambda p=path:self._commit_tile_click(p))
    def _commit_tile_click(self,path):
        self._pending_tile_click.pop(path,None)
        if any(item.path == path for item in self.gallery_files): self.toggle(path)
    def _tile_double_click(self,path):
        pending=self._pending_tile_click.pop(path,None)
        if pending: self.after_cancel(pending)
        self.open_preview(path)
    def _remote_for_path(self,path):
        return next((item for item in self.gallery_files if item.path == path),None)
    def _completed_record(self,item):
        """Read existing history only; preview and metadata never create transfer records."""
        history_path=Path(self.destination.get())/'.openflashair-staging'/'history.sqlite3'
        if not history_path.is_file(): return None
        history=TransferHistory(history_path)
        try: return history.completed(item.path,item.size,item.modified_utc.isoformat() if item.modified_utc else None)
        finally: history.close()
    def _local_preview_path(self,item):
        return self._verified_downloads((item,)).get(item.path,(None,None))
    def _verified_downloads(self,items):
        """Authoritative history plus local-size check shared by metadata and checkmarks."""
        history_path=Path(self.destination.get())/'.openflashair-staging'/'history.sqlite3'
        if not history_path.is_file(): return {item.path:(None,None) for item in items}
        history=TransferHistory(history_path); results={}
        try:
            for item in items:
                record=history.completed(item.path,item.size,item.modified_utc.isoformat() if item.modified_utc else None); local=Path(record.destination) if record else None
                try:
                    if not local or not local.is_file() or local.stat().st_size != item.size: local=None
                except OSError: local=None
                results[item.path]=(local,record)
        finally: history.close()
        return results
    def _refresh_visible_download_indicators(self):
        verified=self._verified_downloads(tile['item'] for tile in self._tiles_by_path.values())
        if not hasattr(self, '_gallery_capture_cache'): self._gallery_capture_cache={}
        for tile in self._tiles_by_path.values():
            local,_record=verified.get(tile['path'],(None,None)); state='normal' if local else 'hidden'
            self.gallery_canvas.itemconfigure(tile['download_check_shape'],state=state)
            self.gallery_canvas.itemconfigure(tile['download_check_mark'],state=state)
            self._raise_tile_overlays(tile)
            if not local:
                stamp=tile['item'].modified_utc
                tile['capture_raw']=stamp; fallback=self._display_timestamp(stamp)
                self.gallery_canvas.itemconfigure(tile['capture'],text='FlashAir timestamp')
                self.gallery_canvas.itemconfigure(tile['capture_value'],text=fallback)
            if local:
                try: key=(str(local),local.stat().st_size,local.stat().st_mtime_ns)
                except OSError: continue
                if key not in self._gallery_capture_cache:
                    self._gallery_capture_cache[key]=None
                    generation=self._gallery_generation; path=tile['path']
                    def read_capture(local=local,key=key,path=path,generation=generation):
                        try: capture=local_capture_time(local) or ''
                        except Exception: capture=''
                        def apply():
                            self._gallery_capture_cache[key]=capture
                            if capture: self._set_tile_capture_time(generation,path,capture)
                        try: self.after(0,apply)
                        except (RuntimeError,tk.TclError): pass
                    threading.Thread(target=read_capture,daemon=True).start()
                elif self._gallery_capture_cache[key]:
                    self._set_tile_capture_time(self._gallery_generation,tile['path'],self._gallery_capture_cache[key])
        selected_items=[item for item in self.gallery_files if item.path in self.selected]
        completed={path for path,(local,_record) in self._verified_downloads(selected_items).items() if local}
        if completed:
            self.selected=[path for path in self.selected if path not in completed]
            self._persist_selection(); self._update_badges()
    def open_preview(self,path):
        item=self._remote_for_path(path)
        if item is None: return
        owner=self.winfo_toplevel(); dialog=tk.Toplevel(owner); dialog.title(f'Preview — {Path(path).name}'); dialog.geometry('900x650'); dialog.minsize(640,480); dialog.transient(owner)
        state={'path':path,'generation':0,'image':None,'photo':None,'fit':True,'card_thumbnail':False}
        body=ttk.Frame(dialog,padding=8); body.grid(sticky='nsew'); dialog.columnconfigure(0,weight=1); dialog.rowconfigure(0,weight=1); body.columnconfigure(0,weight=1); body.rowconfigure(0,weight=1)
        canvas=tk.Canvas(body,background='#111827',highlightthickness=0); canvas.grid(row=0,column=0,sticky='nsew')
        state['canvas']=canvas
        status=tk.StringVar(value='Loading preview…'); controls=ttk.Frame(body); controls.grid(row=1,column=0,sticky='ew',pady=(6,0)); controls.columnconfigure(4,weight=1)
        ttk.Button(controls,text='‹ Previous',command=lambda:self._preview_navigate(state,-1,load)).grid(row=0,column=0)
        ttk.Button(controls,text='Next ›',command=lambda:self._preview_navigate(state,1,load)).grid(row=0,column=1,padx=4)
        ttk.Label(controls,textvariable=status).grid(row=0,column=4,sticky='e')
        def render(_event=None):
            image=state['image']
            if image is None: return
            from PIL import Image, ImageTk
            width=max(1,canvas.winfo_width()-12); height=max(1,canvas.winfo_height()-12); shown=image.copy()
            if state['fit']:
                scale=min(width/shown.width,height/shown.height)
                if state['card_thumbnail'] and scale > 1:
                    shown=shown.resize((max(1,round(shown.width*scale)),max(1,round(shown.height*scale))),Image.Resampling.LANCZOS)
                else: shown.thumbnail((width,height))
            state['photo']=ImageTk.PhotoImage(shown); canvas.delete('preview'); canvas.create_image(canvas.winfo_width()/2,canvas.winfo_height()/2,image=state['photo'],anchor='center',tags='preview')
        def load(target_path=None):
            target_path=target_path or state['path']; remote=self._remote_for_path(target_path)
            if remote is None: return
            state['path']=target_path; state['generation']+=1; generation=state['generation']; status.set('Loading preview…'); dialog.title(f'Preview — {Path(target_path).name}')
            def worker():
                try:
                    local,_record=self._local_preview_path(remote)
                    if local:
                        from PIL import Image
                        image=Image.open(local); image.load(); result=(image.copy(),'Local full-resolution file')
                    else:
                        client=self._thumbnail_client if self._thumbnail_client and self._thumbnail_endpoint == self.endpoint.get() else ThumbnailClient(self.endpoint.get(),concurrency=2)
                        thumb=client.get(remote.path,remote.size,remote.modified_utc.isoformat() if remote.modified_utc else None)
                        if thumb.state != 'ok' or not thumb.data: raise IOError(f'Card preview unavailable ({thumb.state})')
                        result=(decode_image(thumb.data),'Card thumbnail preview (not downloaded)')
                    self.after(0,lambda:self._preview_loaded(dialog,state,generation,result,status,render))
                except Exception as exc: self.after(0,lambda exc=exc:self._preview_failed(dialog,state,generation,exc,status))
            threading.Thread(target=worker,daemon=True).start()
        canvas.bind('<Configure>',lambda _event:render()); dialog.after_idle(lambda:center_popup(dialog,owner)); load()
    def _preview_mode(self,state,fit,render): state['fit']=fit; render()
    def _preview_navigate(self,state,delta,load):
        paths=[item.path for item in self.gallery_files]
        if state['path'] not in paths: return
        index=paths.index(state['path'])+delta
        if 0 <= index < len(paths): load(paths[index])
    def _preview_loaded(self,dialog,state,generation,result,status,render):
        if not dialog.winfo_exists() or generation != state['generation']: return
        state['image'],source=result; state['card_thumbnail']=source.startswith('Card thumbnail'); status.set(source); render()
    def _preview_failed(self,dialog,state,generation,exc,status):
        if not dialog.winfo_exists() or generation != state['generation']: return
        state['image']=None; state['photo']=None
        if state.get('canvas') is not None: state['canvas'].delete('preview')
        status.set(f'Preview unavailable: {type(exc).__name__}: {exc}')
    def show_metadata(self,path):
        item=self._remote_for_path(path)
        if item is None: return
        identity=self._metadata_identity(item)
        dialog=self._metadata_dialogs.get(identity)
        if dialog is None or not dialog.winfo_exists():
            owner=self.winfo_toplevel(); dialog=tk.Toplevel(owner); self._metadata_dialogs[identity]=dialog; self._metadata_dialog=dialog; dialog.transient(owner); dialog.resizable(True,True); dialog.columnconfigure(0,weight=1); dialog.rowconfigure(0,weight=1)
            body=ttk.Frame(dialog,padding=12); body.grid(sticky='nsew'); body.columnconfigure(1,weight=1)
            fields=('Filename','Card path','File size','Image dimensions','FlashAir timestamp','EXIF timestamp','Camera model','ISO sensitivity','Aperture / F-stop','Shutter speed / exposure time','Focal length','Exposure compensation','Exposure mode','Flash status','Lens model','Download status','Local saved path')
            values={name:tk.StringVar(value='Loading…') for name in fields}; dialog._metadata_values=values; dialog._metadata_fields=fields
            for row,name in enumerate(fields):
                ttk.Label(body,text=name+':').grid(row=row,column=0,sticky='nw',padx=(0,10),pady=3)
                ttk.Label(body,textvariable=values[name],wraplength=560,justify='left').grid(row=row,column=1,sticky='ew',pady=3)
            dialog.minsize(620,450); dialog._metadata_identity=identity
            dialog.protocol('WM_DELETE_WINDOW',lambda i=identity,d=dialog:self._close_metadata_dialog(i,d))
            dialog._metadata_center_after=dialog.after_idle(lambda:self._position_metadata_dialog(dialog,owner,identity))
        else:
            self._metadata_dialog=dialog; dialog.deiconify(); dialog.lift()
            try: dialog.focus_force()
            except tk.TclError: pass
        self._metadata_generation+=1; generation=self._metadata_generation; dialog._metadata_generation=generation; dialog._metadata_path=item.path; dialog.title(f'Metadata — {Path(item.path).name}')
        values=dialog._metadata_values
        for name in dialog._metadata_fields: values[name].set('Loading…')
        dialog._timestamp_values={'FlashAir timestamp':item.modified_utc,'EXIF timestamp':None}
        values['Filename'].set(Path(item.path).name); values['Card path'].set(item.path); values['File size'].set(f'{item.size:,} bytes'); values['FlashAir timestamp'].set(self._display_timestamp(item.modified_utc))
        def worker():
            try:
                local,record=self._local_preview_path(item); metadata={}
                if local: metadata=local_image_metadata(local)
                capture=local_capture_time(local) if local else ''
                def apply():
                    if not self._metadata_is_current(dialog,generation,identity,item.path): return
                    values['Download status'].set('Verified downloaded' if record and local else 'Not verified as downloaded')
                    values['Local saved path'].set(str(local) if local else 'Unavailable')
                    values['Image dimensions'].set(metadata.get('dimensions','Unavailable'))
                    dialog._timestamp_values['EXIF timestamp']=capture
                    values['EXIF timestamp'].set(self._display_timestamp(capture))
                    values['Camera model'].set(metadata.get('camera_model') or 'Unavailable')
                    values['ISO sensitivity'].set(metadata.get('iso') or 'Unavailable')
                    values['Aperture / F-stop'].set(metadata.get('aperture') or 'Unavailable')
                    values['Shutter speed / exposure time'].set(metadata.get('shutter_speed') or 'Unavailable')
                    values['Focal length'].set(metadata.get('focal_length') or 'Unavailable')
                    values['Exposure compensation'].set(metadata.get('exposure_compensation') or 'Unavailable')
                    values['Exposure mode'].set(metadata.get('exposure_mode') or 'Unavailable')
                    values['Flash status'].set(metadata.get('flash_status') or 'Unavailable')
                    values['Lens model'].set(metadata.get('lens_model') or 'Unavailable')
                self._queue_metadata_callback(apply)
            except Exception as exc: self._queue_metadata_callback(lambda exc=exc:self._metadata_failed(dialog,generation,identity,item.path,exc))
        threading.Thread(target=worker,daemon=True).start()
    @staticmethod
    def _metadata_identity(item):
        """Use the canonical card path, not a potentially repeated camera filename."""
        return str(item.path).replace('\\','/').rstrip('/').casefold()
    def _queue_metadata_callback(self,callback):
        if getattr(self,'_closing',False): return
        ident=None
        def deliver():
            self._metadata_after.discard(ident)
            callback()
        try: ident=self.after(0,deliver)
        except tk.TclError: return
        self._metadata_after.add(ident)
    def _metadata_is_current(self,dialog,generation,identity,path):
        return (self._metadata_dialogs.get(identity) is dialog and dialog.winfo_exists()
                and dialog._metadata_generation == generation and dialog._metadata_path == path)
    def _position_metadata_dialog(self,dialog,owner,identity):
        dialog._metadata_center_after=None
        if not dialog.winfo_exists() or self._metadata_dialogs.get(identity) is not dialog: return
        center_popup(dialog,owner)
        # Offset concurrently opened comparison dialogs without letting one leave the
        # active monitor's work area.  The first remains centered over the app.
        order=list(self._metadata_dialogs).index(identity); offset=24 * (order % 6)
        if offset:
            dialog.update_idletasks(); left,top,right,bottom=self._monitor_work_area()
            width,height=dialog.winfo_width(),dialog.winfo_height()
            x=max(left,min(dialog.winfo_x()+offset,right-width)); y=max(top,min(dialog.winfo_y()+offset,bottom-height))
            dialog.geometry(f'{width}x{height}+{x}+{y}')
    def _metadata_failed(self,dialog,generation,identity,path,exc):
        if not self._metadata_is_current(dialog,generation,identity,path): return
        values=dialog._metadata_values
        for name in dialog._metadata_fields:
            if values[name].get() == 'Loading…': values[name].set('Unavailable')
        values['Download status'].set(f'Unavailable: {type(exc).__name__}: {exc}')
    def _close_metadata_dialog(self,identity=None,dialog=None):
        """Close one comparison dialog, or all dialogs during application shutdown."""
        if identity is None:
            for key,window in tuple(self._metadata_dialogs.items()): self._close_metadata_dialog(key,window)
            self._metadata_dialog=None
            return
        current=self._metadata_dialogs.get(identity)
        if current is not dialog: return
        self._metadata_dialogs.pop(identity,None); self._metadata_generation+=1
        if self._metadata_dialog is dialog:
            self._metadata_dialog=next(iter(self._metadata_dialogs.values()),None)
        if dialog is not None and dialog.winfo_exists():
            ident=getattr(dialog,'_metadata_center_after',None)
            if ident:
                try: dialog.after_cancel(ident)
                except tk.TclError: pass
            dialog.destroy()
    def toggle(self,path):
        if path in self.selected: self.selected.remove(path)
        else:
            item=self._remote_for_path(path)
            if item is None or self._local_preview_path(item)[0] is not None: return
            self.selected.append(path)
        self._persist_selection(); self._update_badges()
    def select_all(self):
        verified=self._verified_downloads(self.gallery_files)
        for path in self.loaded:
            if path not in self.selected and verified.get(path,(None,None))[0] is None:self.selected.append(path)
        self._persist_selection(); self._update_badges()
    def select_page(self):
        _,items=gallery_page_slice(self.gallery_files,self.gallery_page)
        verified=self._verified_downloads(items)
        for item in items:
            if item.path not in self.selected and verified.get(item.path,(None,None))[0] is None:
                self.selected.append(item.path)
        self._persist_selection(); self._update_badges()
    def clear_all(self): self.selected=[]; self._persist_selection(); self._update_badges()
    def _persist_selection(self):
        q=DownloadQueue(Path(self.destination.get())/'.openflashair-staging'/'selection.sqlite3')
        q.replace(self.selected)
    def _update_badges(self):
        self.selection_text.set(f'{len(self.selected)} selected')
        self.download_selected_button.configure(state=('normal' if self.selected and not self.scanning else 'disabled'))
        self._update_scan_controls()
        for tile in self._tiles_by_path.values():
            if tile['path'] in self.selected:
                self.gallery_canvas.itemconfigure(tile['border'],fill='#bfdbfe',outline='#0369a1',width=3)
                self.gallery_canvas.itemconfigure(tile['badge_shape'],state='normal')
                self.gallery_canvas.itemconfigure(tile['badge_text'],text=str(self.selected.index(tile['path'])+1),state='normal')
            else:
                self.gallery_canvas.itemconfigure(tile['border'],fill='#f4f4f4',outline='#f4f4f4',width=1)
                self.gallery_canvas.itemconfigure(tile['badge_shape'],state='hidden')
                self.gallery_canvas.itemconfigure(tile['badge_text'],state='hidden')
def main():
    from .single_instance import SingleInstance
    guard = SingleInstance()
    if not guard.primary:
        guard.close()
        return
    # Windows reads a taskbar identity when the top-level window is created.
    # Setting it first prevents the app from inheriting a generic Python/Tk ID.
    try:
        configure_windows_taskbar_identity()
        root=tk.Tk(); root.title('OpenFlashAir')
        try:
            root.iconbitmap(default=str(application_icon_path()))
        except tk.TclError as exc:
            root.destroy()
            raise RuntimeError(f'Could not apply the OpenFlashAir application icon: {application_icon_path()}') from exc
        app = App(root)
        def check_launch():
            if guard.restore_requested():
                app._tray_actions.put('restore')
                if app._tray_poll_after is None:
                    app._process_tray_actions()
            root.after(100, check_launch)
        root.after(100, check_launch)
        root.mainloop()
    finally:
        guard.close()
if __name__=='__main__': main()
