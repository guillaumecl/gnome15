#!/usr/bin/env python
 
#        +-----------------------------------------------------------------------------+
#        | GPL                                                                         |
#        +-----------------------------------------------------------------------------+
#        | Copyright (c) Brett Smith <tanktarta@blueyonder.co.uk>                      |
#        |                                                                             |
#        | This program is free software; you can redistribute it and/or               |
#        | modify it under the terms of the GNU General Public License                 |
#        | as published by the Free Software Foundation; either version 2              |
#        | of the License, or (at your option) any later version.                      |
#        |                                                                             |
#        | This program is distributed in the hope that it will be useful,             |
#        | but WITHOUT ANY WARRANTY; without even the implied warranty of              |
#        | MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the               |
#        | GNU General Public License for more details.                                |
#        |                                                                             |
#        | You should have received a copy of the GNU General Public License           |
#        | along with this program; if not, write to the Free Software                 |
#        | Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA. |
#        +-----------------------------------------------------------------------------+

"""
Helper classes for implementing desktop components that can monitor and control some functions
of the desktop service. It is used for Indicators, System tray icons and panel applets and
deals with all the hard work of connecting to DBus and monitoring events.
"""

import sys
import pygtk
pygtk.require('2.0')
import gtk
import gconf
import traceback
import gnome15.g15globals as g15globals
import gnome15.g15screen as g15screen
import gnome15.g15util as g15util
import dbus

# Logging
import logging
logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

from threading import RLock
                
icon_theme = gtk.icon_theme_get_default()
if g15globals.dev:
    icon_theme.prepend_search_path(g15globals.icons_dir)
    

class G15Screen():
    """
    Client side representation of a remote screen. Holds general details such
    as model name, UID and the pages that screen is currently showing.
    """
    
    def __init__(self, path, device_model_fullname, device_uid):
        self.path = path
        self.device_model_fullname = device_model_fullname
        self.device_uid = device_uid
        self.items = {}
        self.message = None

class G15DesktopComponent():
    """
    Helper class for implementing desktop components that can monitor and control some functions
    of the desktop service. It is used for Indicators, System tray icons and panel applets and
    deals with all the hard work of connecting to DBus and monitoring events.
    """
    
    def __init__(self):
        self.screens = {}
        self.service = None
        self.start_service_item = None
        self.attention_item = None
        self.pages = []   
        self.lock = RLock()
        self.attention_messages = {}
        self.connected = False
        
        # Connect to DBus and GConf
        self.conf_client = gconf.client_get_default()
        self.session_bus = dbus.SessionBus()
        
        # Initialise desktop component
        self.initialise_desktop_component()     
        self.icons_changed()
        
    def start(self):
        """
        Start the desktop component. An attempt will be made to connect to Gnome15 over 
        DBus. If this fails, the component should stay active until the service becomes
        available.
        """
        
        # Try and connect to the service now
        try :
            self._connect()        
        except dbus.exceptions.DBusException:
            traceback.print_exc(file=sys.stdout)
            self._disconnect()
        
        # Start watching various events
        self.conf_client.notify_add("/apps/gnome15/indicate_only_on_error", self._indicator_options_changed)
        gtk_icon_theme = gtk.icon_theme_get_default()
        gtk_icon_theme.connect("changed", self._theme_changed)

        # Watch for Gnome15 starting and stopping
        self.session_bus.add_signal_receiver(self._name_owner_changed,
                                     dbus_interface='org.freedesktop.DBus',
                                     signal_name='NameOwnerChanged')  
        
    """
    Pulic functions
    """
    def get_icon_path(self, icon_name):
        """
        Helper function to get an icon path or it's name, given the name. 
        """
        if g15globals.dev:
            # Because the icons aren't installed in this mode, they must be provided
            # using the full filename. Unfortunately this means scaling may be a bit
            # blurry in the indicator applet
            return g15util.get_icon_path(icon_name, 128)
        else:
            return icon_name
             
    def show_configuration(self, arg = None):
        """
        Show the configuration user interface
        """        
        g15util.run_script("g15-config")
        
    def stop_desktop_service(self, arg = None):
        """
        Stop the desktop service
        """ 
        self.session_bus.get_object('org.gnome15.Gnome15', '/org/gnome15/Service').Stop()   
        
    def start_desktop_service(self, arg = None):
        """
        Start the desktop service
        """    
        g15util.run_script("g15-desktop-service", ["-f"])   
        
    def show_page(self, page_sequence_number):
        """
        Show a page, given its sequence number
        """
        self.session_bus.get_object('org.gnome15.Gnome15', '/org/gnome15/Page%s' % page_sequence_number).CycleTo()
        
    def check_attention(self):
        """
        Check the current state of attention, either clearing it or setting it and displaying
        a new message
        """
        if len(self.attention_messages) == 0:
            self.clear_attention()      
        else:
            for i in self.attention_messages:
                message = self.attention_messages[i]
                self.attention(message)
                break
        
    """
    Functions that must be implemented
    """
        
    def initialise_desktop_component(self):
        """
        This function is called during construction and should create initial desktop component
        """ 
        raise Exception("Not implemented")
    
    def rebuild_desktop_component(self):
        """
        This function is called every time the list of screens or pages changes 
        in someway. The desktop component should be rebuilt to reflect the
        new state
        """
        raise Exception("Not implemented")
    
    def clear_attention(self):
        """
        Clear any "Attention" state indicators
        """
        raise Exception("Not implemented")
        
    def attention(self, message = None):
        """
        Display an "Attention" state indicator with a message
        
        Keyword Arguments:
        message    --    message to display
        """
        raise Exception("Not implemented")
    
    def icons_changed(self):
        """
        Invoked once a start up, and then whenever the desktop icon theme changes. Implementations
        should do whatever required to change any themed icons they are displayed
        """
        raise Exception("Not implemented")
    
    def options_changed(self):
        """
        Invoked when any global desktop component options change.
        """
        raise Exception("Not implemented")
        
    '''
    DBUS Event Callbacks
    ''' 
    def _name_owner_changed(self, name, old_owner, new_owner):
        if name == "org.gnome15.Gnome15":
            if old_owner == "":
                if self.service == None:
                    self._connect()
            else:
                if self.service != None:
                    self.connected = False
                    self._disconnect()
        
    def _page_created(self, screen_path, page_sequence_number, page_title):
        logger.debug("Page created (%s) %d = %s" % ( screen_path, page_sequence_number, page_title ) )
        page = self.session_bus.get_object('org.gnome15.Gnome15', '/org/gnome15/Page%d' % page_sequence_number)
        self.lock.acquire()
        try :
            if page.GetPriority() >= g15screen.PRI_LOW:
                self._add_page(screen_path, page)
        finally :
            self.lock.release()
        
    def _page_title_changed(self, screen_path, page_sequence_number, title):
        self.lock.acquire()
        try :
            self.screens[screen_path].items[str(page_sequence_number)] = title
            self.rebuild_desktop_component()
        finally :
            self.lock.release()
    
    def _page_deleting(self, screen_path, page_sequence_number):
        self.lock.acquire()
        logger.debug("Destroying page (%s) %d" % ( screen_path, page_sequence_number ) )
        try :
            page_item_key = str(page_sequence_number)
            items = self.screens[screen_path].items
            if page_item_key in items:
                del items[page_item_key]
                self.rebuild_desktop_component()
        finally :
            self.lock.release()
        
    def _attention_cleared(self, screen_path):
        if screen_path in self.attention_messages:
            del self.attention_messages[screen_path]
            self.rebuild_desktop_component()
        
    def _attention_requested(self, screen_path, message = None):
        if not screen_path in self.attention_messages:
            self.attention_messages[screen_path] = message
            self.rebuild_desktop_component()
        
    """
    Private
    """
            
    def _enable(self, widget, device):
        device.Enable()
        
    def _disable(self, widget, device):
        device.Disable()
        
    def _cycle_screens_option_changed(self, client, connection_id, entry, args):
        self.rebuild_desktop_component()
        
    def _remove_screen(self, screen_path):
        if screen_path in self.screens:
            try :
                del self.screens[screen_path]
            except dbus.DBusException:
                pass
        self.rebuild_desktop_component()
        
    def _add_screen(self, screen_path):
        logger.debug("Screen added %s" % screen_path)
        remote_screen = self.session_bus.get_object('org.gnome15.Gnome15', screen_path)
        ( device_uid, device_model_name, device_usb_id, device_model_fullname ) = remote_screen.GetDeviceInformation()
        screen = G15Screen(screen_path, device_model_fullname, device_uid)        
        self.screens[screen_path] = screen
        if remote_screen.IsAttentionRequested():
            screen.message = remote_screen.GetMessage()                                
        
    def _connect(self):
        logger.debug("Connecting")
        self._reset_attention()
        self.service = self.session_bus.get_object('org.gnome15.Gnome15', '/org/gnome15/Service')
        self.connected = True
                
        # Load the initial screens
        self.lock.acquire()
        try : 
            for screen_path in self.service.GetScreens():
                self._add_screen(screen_path)
                remote_screen = self.session_bus.get_object('org.gnome15.Gnome15', screen_path)
                for page_sequence_number in remote_screen.GetPageSequenceNumbers(g15screen.PRI_LOW):
                    page = self.session_bus.get_object('org.gnome15.Gnome15', '/org/gnome15/Page%d' % page_sequence_number)
                    if page.GetPriority() >= g15screen.PRI_LOW:
                        self._add_page(screen_path, page)
        finally :
            self.lock.release()
        
        # Listen for events
        self.session_bus.add_signal_receiver(self._add_screen, dbus_interface = "org.gnome15.Service", signal_name = "ScreenAdded")
        self.session_bus.add_signal_receiver(self._remove_screen, dbus_interface = "org.gnome15.Service", signal_name = "ScreenRemoved")
        self.session_bus.add_signal_receiver(self._page_created, dbus_interface = "org.gnome15.Screen", signal_name = "PageCreated")
        self.session_bus.add_signal_receiver(self._page_title_changed, dbus_interface = "org.gnome15.Screen", signal_name = "PageTitleChanged")
        self.session_bus.add_signal_receiver(self._page_deleting, dbus_interface = "org.gnome15.Screen", signal_name = "PageDeleting")
        self.session_bus.add_signal_receiver(self._attention_requested, dbus_interface = "org.gnome15.Screen", signal_name = "AttentionRequested")
        self.session_bus.add_signal_receiver(self._attention_cleared, dbus_interface = "org.gnome15.Screen", signal_name = "AttentionCleared")
            
        # We are now connected, so remove the start service menu item and allow cycling
        self.rebuild_desktop_component()
        
    def _disconnect(self):
        logger.debug("Disconnecting")               
        self.session_bus.remove_signal_receiver(self._page_created, dbus_interface = "org.gnome15.Service", signal_name = "ScreenAdded")
        self.session_bus.remove_signal_receiver(self._page_title_changed, dbus_interface = "org.gnome15.Service", signal_name = "ScreenRemoved")
        self.session_bus.remove_signal_receiver(self._page_created, dbus_interface = "org.gnome15.Screen", signal_name = "PageCreated")
        self.session_bus.remove_signal_receiver(self._page_title_changed, dbus_interface = "org.gnome15.Screen", signal_name = "PageTitleChanged")
        self.session_bus.remove_signal_receiver(self._page_deleting, dbus_interface = "org.gnome15.Screen", signal_name = "PageDeleting")
        self.session_bus.remove_signal_receiver(self._attention_requested, dbus_interface = "org.gnome15.Screen", signal_name = "AttentionRequested")
        self.session_bus.remove_signal_receiver(self._attention_cleared, dbus_interface = "org.gnome15.Screen", signal_name = "AttentionCleared")
             
        if self.service != None and self.connected:
            for screen_path in dict(self.screens):
                self._remove_screen(screen_path)
        
        self._reset_attention()
        self._attention_requested("service", "g15-desktop-service is not running.")
            
        self.service = None  
        self.connected = False 
        self.rebuild_desktop_component()      
        
    def _reset_attention(self):
        self.attention_messages = {}
        self.rebuild_desktop_component()
            
    def _add_page(self, screen_path, page): 
        seq_no = str(page.GetSequenceNumber())
        logger.debug("Adding page %s to %s" % (seq_no, screen_path))
        items = self.screens[screen_path].items
        if not seq_no in items:
            items[seq_no] = page.GetTitle()
            self.rebuild_desktop_component()
        
    def _indicator_options_changed(self, client, connection_id, entry, args):
        self.options_changed()
    
    def _theme_changed(self, theme):
        self.icons_changed()