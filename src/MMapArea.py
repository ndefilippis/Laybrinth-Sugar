#! /usr/bin/env python
# MMapArea.py
# This file is part of Labyrinth
#
# Copyright (C) 2006 - Don Scorgie <Don@Scorgie.org>
#
# Labyrinth is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Labyrinth is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Labyrinth; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA  02110-1301  USA
#

import math
import time
import gtk
import pango
import gobject
import gettext
import copy
import cairo
import logging
_ = gettext.gettext

import xml.dom.minidom as dom

import Links
import TextThought
import LabelThought
import ImageThought
import DrawingThought
import ResourceThought
import UndoManager
import utils
from BaseThought import BaseThought
from Links import Link

RAD_UP = (- math.pi / 2.)
RAD_DOWN = (math.pi / 2.)
RAD_LEFT = (math.pi)
RAD_RIGHT = (0)

MODE_NULL 		= 0
MODE_TEXT		= 1
MODE_IMAGE		= 2
MODE_DRAW		= 3
MODE_RESOURCE	= 4
MODE_LABEL		= 5

VIEW_LINES = 0
VIEW_BEZIER = 1

# TODO: Need to expand to support popup menus
MENU_EMPTY_SPACE = 0

# UNDO actions
UNDO_MOVE = 0
UNDO_CREATE = 1
UNDO_DELETE = 2
UNDO_DELETE_SINGLE = 3
UNDO_COMBINE_DELETE_NEW = 4
UNDO_DELETE_LINK = 5
UNDO_STRENGTHEN_LINK = 6
UNDO_CREATE_LINK = 7
UNDO_ALIGN = 8

# Note: This is (atm) very broken.  It will allow you to create new canvases, but not
# create new thoughts or load existing maps.
# To get it working either fix the TODO list at the bottom of the class, implement the
# necessary features within all the thought types.  If you do, please send a patch ;)
# OR: Change this class to MMapAreaNew and MMapAreaOld to MMapArea

class MMapArea (gtk.DrawingArea):
	'''A MindMapArea Widget.  A blank canvas with a collection of child thoughts.\
	   It is responsible for processing signals and such from the whole area and \
	   passing these on to the correct child.  It also informs things when to draw'''

	__gsignals__ = dict (title_changed		= (gobject.SIGNAL_RUN_FIRST,
											   gobject.TYPE_NONE,
											   (gobject.TYPE_STRING, )),
						 change_mode        = (gobject.SIGNAL_RUN_LAST,
						 					   gobject.TYPE_NONE,
						 					   (gobject.TYPE_INT, )),					 					   
						 change_buffer      = (gobject.SIGNAL_RUN_LAST,
						 					   gobject.TYPE_NONE,
						 					   (gobject.TYPE_OBJECT, )),
						 text_selection_changed  = (gobject.SIGNAL_RUN_FIRST,
						 					   gobject.TYPE_NONE,
						 					   (gobject.TYPE_INT, gobject.TYPE_INT, gobject.TYPE_STRING)),
						 thought_selection_changed = (gobject.SIGNAL_RUN_FIRST,
						 						gobject.TYPE_NONE,
						 						(gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT)),
						 set_focus				 = (gobject.SIGNAL_RUN_FIRST,
						 							gobject.TYPE_NONE,
						 							(gobject.TYPE_PYOBJECT, gobject.TYPE_BOOLEAN)),
						 set_attrs				 = (gobject.SIGNAL_RUN_LAST,
						 							gobject.TYPE_NONE,
						 							(gobject.TYPE_BOOLEAN, gobject.TYPE_BOOLEAN, gobject.TYPE_BOOLEAN, pango.FontDescription)),
						 link_selected		= (gobject.SIGNAL_RUN_FIRST,
											   gobject.TYPE_NONE,
											   ()))

	def __init__(self, undo):
		super (MMapArea, self).__init__()

		self.thoughts = []
		self.links = []
		self.selected = []
		self.num_selected = 0
		self.primary = None
		self.pango_context = self.create_pango_context()
		self.undo = undo
		self.scale_fac = 1.0
		self.translate = False
		self.translation = [0.0,0.0]
		self.timeout = -1
		self.current_cursor = None
		self.do_filter = True
		self.is_bbox_selecting = False

		self.nthoughts = 0

		impl = dom.getDOMImplementation()
		self.save = impl.createDocument("http://www.donscorgie.blueyonder.co.uk/labns", "MMap", None)
		self.element = self.save.documentElement
		self.im_context = gtk.IMMulticontext ()

		self.mode = MODE_NULL
		self.old_mode = MODE_NULL

		self.connect ("expose_event", self.expose)
		self.connect ("button_release_event", self.button_release)
		self.connect ("button_press_event", self.button_down)
		self.connect ("motion_notify_event", self.motion)
		self.connect ("key_press_event", self.key_press)
		self.connect ("key_release_event", self.key_release)
		self.connect ("scroll_event", self.scroll)
		self.commit_handler = None
		self.title_change_handler = None
		self.moving = False
		self.move_origin = None
		self.move_origin_new = None
		self.focus = None
		self.move_action = None
		self.current_root = []
		self.rotation = 0
		self.text_attributes = {}

		self.set_events (gtk.gdk.KEY_PRESS_MASK |
						 gtk.gdk.KEY_RELEASE_MASK |
						 gtk.gdk.BUTTON_PRESS_MASK |
						 gtk.gdk.BUTTON_RELEASE_MASK |
						 gtk.gdk.POINTER_MOTION_MASK |
						 gtk.gdk.SCROLL_MASK
						)

		self.set_flags (gtk.CAN_FOCUS)
		
		# set theme colors
		w = gtk.Window()
		w.realize()
		style = w.get_style()
		self.pango_context.set_font_description(style.font_desc)
		self.font_name = style.font_desc.to_string()
		utils.default_font = self.font_name
		
		self.font_size = utils.default_font 
		
		utils.default_colors["text"] = utils.gtk_to_cairo_color(style.text[gtk.STATE_NORMAL])
		utils.default_colors["base"] = utils.gtk_to_cairo_color(style.base[gtk.STATE_NORMAL])
		# Match the fixed white canvas colour (makes thought focus visible)
		self.background_color = style.white
		self.foreground_color = style.black
		utils.default_colors["bg"] = utils.gtk_to_cairo_color(style.bg[gtk.STATE_NORMAL])
		utils.default_colors["fg"] = utils.gtk_to_cairo_color(style.fg[gtk.STATE_NORMAL])
		
		utils.selected_colors["text"] = utils.gtk_to_cairo_color(style.text[gtk.STATE_SELECTED])
		utils.selected_colors["bg"] = utils.gtk_to_cairo_color(style.bg[gtk.STATE_SELECTED])
		utils.selected_colors["fg"] = utils.gtk_to_cairo_color(style.fg[gtk.STATE_SELECTED])
		utils.selected_colors["fill"] = utils.gtk_to_cairo_color(style.base[gtk.STATE_SELECTED])

	def set_text_attributes(self, text_attributes):
		self.font_combo_box = text_attributes.props.page.fonts_combo_box.combo
		self.font_sizes_combo_box = text_attributes.props.page.font_sizes_combo_box.combo 

	def transform_coords(self, loc_x, loc_y):
		if hasattr(self, "transform"):
			return self.transform.transform_point(loc_x, loc_y)
			
	def untransform_coords(self, loc_x, loc_y):
		if hasattr(self, "untransform"):
			return self.untransform.transform_point(loc_x, loc_y)

	def button_down (self, widget, event):
		if event.button == 2 or \
		        event.button == 1 and self.translate == True:
			self.set_cursor (gtk.gdk.FLEUR)
			self.original_translation = self.translation
			self.origin_x = event.x
			self.origin_y = event.y
			return

		coords = self.transform_coords (event.get_coords()[0], event.get_coords()[1])
		obj = self.find_object_at (coords)

		if obj:
			if event.button == 3:
				self.moving = not (event.state & gtk.gdk.CONTROL_MASK)
				if self.moving:
					self.set_cursor(gtk.gdk.FLEUR)
					self.move_origin = (coords[0], coords[1])
					self.move_origin_new = self.move_origin

			if obj == self.focus:
				self.focus.enter()
			else:
				self.set_focus(obj, event.state)

			obj.process_button_down(event, coords)

		elif self.mode and event.button == 1 and widget:
			self.embody_thought(event)

		elif event.button == 1 and self.mode == MODE_NULL:
			self.bbox_origin = coords
			self.is_bbox_selecting = True

	def undo_move (self, action, mode):
		self.undo.block ()
		move_thoughts = action.args[1]
		old_coords = action.args[0]
		new_coords = action.args[2]
		move_x = old_coords[0] - new_coords[0]
		move_y = old_coords[1] - new_coords[1]
		if mode == UndoManager.REDO:
			move_x = -move_x
			move_y = -move_y
		self.unselect_all ()
		for t in move_thoughts:
			self.select_thought (t, -1)
			t.move_by (move_x, move_y)
		self.undo.unblock ()
		self.invalidate ((old_coords[0], old_coords[1], new_coords[0], new_coords[1]))

	def button_release (self, widget, event):
		coords = self.transform_coords (event.get_coords()[0], event.get_coords()[1])

		if self.is_bbox_selecting:
			self.is_bbox_selecting = False
			self.invalidate ()
			try:
				if abs(self.bbox_origin[0] - coords[0]) > 2.0:
					return True
			except AttributeError:	# no bbox_current
				pass
				
		if self.translate:
			self.translate = False
			return True

		if self.moving and self.move_action:
			self.move_action.add_arg (coords)
			self.undo.add_undo (self.move_action)
			self.move_action = None

		self.moving = False
		self.move_origin = None

		obj = self.find_object_at (coords)

		if event.button == 2:
			self.undo.add_undo (UndoManager.UndoAction (self, UndoManager.TRANSFORM_CANVAS, \
														self.undo_transform_cb,
														self.scale_fac, self.scale_fac, 
														self.original_translation,
														self.translation))
		if obj:
			if not obj.process_button_release(event, coords):
				# prolonged creation was failed
				self.undo.forget_action()
			else:
				self.update_view(obj)

			if len(self.selected) != 1:
				self.invalidate()	# does not invalidate correctly with obj.get_max_area()
				return True

		self.invalidate ()
		return True

	def undo_transform_cb (self, action, mode):
		if mode == UndoManager.UNDO:
			self.scale_fac = action.args[0]
			self.translation = action.args[2]
		else:
			self.scale_fac = action.args[1]
			self.translation = action.args[3]
		self.invalidate ()

	def scroll (self, widget, event):	
		scale = self.scale_fac

		if event.direction == gtk.gdk.SCROLL_UP:
			self.scale_fac*=1.2
		elif event.direction == gtk.gdk.SCROLL_DOWN:
			self.scale_fac/=1.2

		self.undo.add_undo (UndoManager.UndoAction (self, UndoManager.TRANSFORM_CANVAS, \
													self.undo_transform_cb,
													scale, self.scale_fac, self.translation,
													self.translation))
		self.invalidate()

	def undo_joint_cb (self, action, mode):
		delete = action.args[0]
		create = action.args[1]

		if mode == UndoManager.UNDO:
			self.undo_create_cb (create, mode)
			self.undo_deletion (delete, mode)
		else:
			self.undo_deletion (delete, mode)
			self.undo_create_cb (create, mode)
		self.invalidate ()

	def key_press (self, widget, event):
		logging.debug("Se presiono una tecla")
		# Support for canvas panning keys ('hand' on XO, 'cmd' on Macs)
		if event.hardware_keycode == 133 or event.hardware_keycode == 134:
			self.translate = True
		logging.debug("Evento: %s", str(event))
		logging.debug("do_filter %s", str(self.do_filter))
		#valor_retorno = self.im_context.filter_keypress (event)
		#logging.debug("filter_keypress me retorna %s", str(valor_retorno))
		if not self.do_filter or not self.im_context.filter_keypress (event):
			logging.debug("Antes de preguntar si tengo focus")
			if self.focus:
				if self.focus.creating or \
						not self.focus.process_key_press (event, self.mode):
					logging.debug("Me voy a global_key_handler, dento de self.focus")
					return self.global_key_handler (event)
				logging.debug("Retorno True dentro de self.focus")
				return True
			if len(self.selected) != 1 or not self.selected[0].process_key_press (event, self.mode):
				logging.debug("Me voy a global_key_handler")
				return self.global_key_handler (event)
		logging.debug("Termine la funcion y me voy")
		return True

	def key_release (self, widget, event):
		# Support for canvas panning keys ('hand' on XO, 'cmd' on Macs)
		if event.hardware_keycode == 133 or event.hardware_keycode == 134:
			self.translate = False
		self.im_context.filter_keypress (event)
		return True

	def motion (self, widget, event):
		coords = self.transform_coords (event.get_coords()[0], event.get_coords()[1])

		if event.state & gtk.gdk.BUTTON1_MASK and self.is_bbox_selecting:
			self.bbox_current = coords
			self.invalidate()
			
			ul = [ self.bbox_origin[0], self.bbox_origin[1] ]
			lr = [ coords[0], coords[1] ]
			if self.bbox_origin[0] > coords[0]:
				if self.bbox_origin[1] < coords[1]:
					ul[0] = coords[0]
					ul[1] = self.bbox_origin[1]
					lr[0] = self.bbox_origin[0]
					lr[1] = coords[1]
				else:
					ul = coords
					lr = self.bbox_origin
			elif self.bbox_origin[1] > coords[1]:
				ul[0] = self.bbox_origin[0]
				ul[1] = coords[1]
				lr[0] = coords[0]
				lr[1] = self.bbox_origin[1]
				
			# FIXME: O(n) runtime is bad
			for t in self.thoughts:
				if t.lr[0] > ul[0] and t.ul[1] < lr[1] and t.ul[0] < lr[0] and t.lr[1] > ul[1] :
					if t not in self.selected:
						self.select_thought(t, gtk.gdk.SHIFT_MASK)
				else:
					if t in self.selected:
						t.unselect()
						self.selected.remove(t)
			return True
		elif self.moving:
			self.set_cursor(gtk.gdk.FLEUR)
			if not self.move_action:
				self.move_action = UndoManager.UndoAction (self, UNDO_MOVE, self.undo_move, self.move_origin,
														   self.selected)
			for t in self.selected:
				t.move_by (coords[0] - self.move_origin_new[0], coords[1] - self.move_origin_new[1])
			self.move_origin_new = (coords[0], coords[1])
			self.invalidate ()
			return True
		elif event.state & gtk.gdk.BUTTON2_MASK or \
                event.state & gtk.gdk.BUTTON1_MASK and self.translate:
			self.translate = True
			self.translation[0] -= (self.origin_x - event.x) / self.scale_fac
			self.translation[1] -= (self.origin_y - event.y) / self.scale_fac
			self.origin_x = event.x
			self.origin_y = event.y
			self.invalidate()
			return True
			
		obj = self.find_object_at (coords)

		if obj and obj.handle_motion(event, coords):
			self.update_links_cb(obj)
			self.update_view(obj)

		return True

	def find_object_at (self, coords):
		if self.focus and self.focus.includes(coords):
			return self.focus
		for x in reversed(self.thoughts):
			if x != self.focus and not isinstance(x, Link) and x.includes (coords):
				return x
		for x in self.links:
			if x != self.focus and not isinstance(x, Link) and x.includes (coords):
				return x
		return None

	def realize_cb (self, widget):
		self.disconnect (self.realize_handle)
		if self.mode == MODE_IMAGE or self.mode == MODE_DRAW:
			self.set_cursor (gtk.gdk.CROSSHAIR)
		else:
			self.set_cursor (gtk.gdk.LEFT_PTR)
		return False

	def set_cursor(self, kind):
		new_cursor = CursorFactory().get_cursor(kind)
		if self.current_cursor != new_cursor:
			self.current_cursor = new_cursor
			self.window.set_cursor(self.current_cursor)

	def set_mode (self, mode):
		if mode == self.mode:
			return
		self.old_mode = self.mode
		self.mode = mode
		self.hookup_im_context ()

		if self.window:
			if mode == MODE_IMAGE or mode == MODE_DRAW:
				self.set_cursor (gtk.gdk.CROSSHAIR)
			else:
				self.set_cursor (gtk.gdk.LEFT_PTR)
		else:
			self.realize_handle = self.connect ("realize", self.realize_cb)
		self.mode = mode
		if self.window:
			self.invalidate ()

	def title_changed_cb (self, widget, new_title):
		self.emit ("title_changed", new_title)

	def make_primary (self, thought):
		if self.primary:
			print "Warning: Already have a primary root"
			if self.title_change_handler:
				self.primary.disconnect (self.title_change_handler)
		self.title_change_handler = thought.connect ("title_changed", self.title_changed_cb)
		self.emit ("title_changed", thought.text)
		self.primary = thought
		thought.make_primary ()

	def hookup_im_context (self, thought = None):
		if self.commit_handler:
			self.im_context.disconnect (self.commit_handler)
			self.im_context.disconnect (self.delete_handler)
			self.im_context.disconnect (self.preedit_changed_handler)
			self.im_context.disconnect (self.preedit_end_handler)
			self.im_context.disconnect (self.preedit_start_handler)
			self.im_context.disconnect (self.retrieve_handler)
			self.commit_handler = None
		if thought:
			try:
				logging.debug("Conectando con commit_text")
				self.commit_handler = self.im_context.connect ("commit", thought.commit_text, self.mode, self.font_combo_box, self.font_sizes_combo_box)
				self.delete_handler = self.im_context.connect ("delete-surrounding", thought.delete_surroundings, self.mode)
				self.preedit_changed_handler = self.im_context.connect ("preedit-changed", thought.preedit_changed, self.mode)
				self.preedit_end_handler = self.im_context.connect ("preedit-end", thought.preedit_end, self.mode)
				self.preedit_start_handler = self.im_context.connect ("preedit-start", thought.preedit_start, self.mode)
				self.retrieve_handler = self.im_context.connect ("retrieve-surrounding", thought.retrieve_surroundings, \
																 self.mode)
				self.do_filter = True
			except AttributeError:
				self.do_filter = False
		else:
			self.do_filter = False
		logging.debug("Estoy saliendo de hookup_im_context con do_filter=%s", str(self.do_filter))

	def unselect_all (self):
		self.hookup_im_context ()
		for t in self.selected:
			t.unselect ()
		self.selected = []

	def select_link (self, link, modifiers):
		if modifiers and modifiers & gtk.gdk.SHIFT_MASK and len (self.selected) > 1 and self.selected.count (link) > 0:
			self.selected.remove (link)
			link.unselect ()
			return

		self.hookup_im_context()
		self.set_focus(None, None)

		if modifiers and (modifiers & gtk.gdk.SHIFT_MASK or modifiers == -1):
			if self.selected.count (link) == 0:
				self.selected.append (link)
		else:
			map (lambda t : t.unselect(), self.selected)
			self.selected = [link]
		link.select()
		self.emit("change_buffer", None)

	def set_focus(self, thought, modifiers):
		if self.focus == thought:
			return
		if self.focus:
			self.focus.leave()
		if thought:
			self.select_thought(thought, modifiers)
		self.focus = thought

	def select_thought (self, thought, modifiers):
		self.hookup_im_context ()
			
		if thought in self.selected and self.moving:
			return

		if thought not in self.thoughts:
			self.thoughts.append(thought)

		if modifiers and (modifiers & gtk.gdk.SHIFT_MASK or modifiers == -1):
			if self.selected.count (thought) == 0:
				self.selected.append (thought)
		else:
			map(lambda x : x.unselect(), self.selected)
			self.selected = [thought]
		if thought.can_be_parent():
			self.current_root = []
		for x in self.selected:
			if x.can_be_parent():
				self.current_root.append(x)
		thought.select ()
		if len(self.selected) == 1:
			self.emit ("thought_selection_changed", thought.background_color, thought.foreground_color)
			self.background_color = thought.background_color
			self.foreground_color = thought.foreground_color
			try:
				self.emit ("change_buffer", thought.extended_buffer)
			except AttributeError:
				self.emit ("change_buffer", None)
			self.hookup_im_context (thought)
		else:
			self.emit ("change_buffer", None)

	def undo_link_action (self, action, mode):
		self.undo.block ()
		self.set_focus(None, None)
		link = action.args[0]
		if action.undo_type == UNDO_CREATE_LINK:
			if mode == UndoManager.REDO:
				self.element.appendChild (link.element)
				self.links.append (link)
			else:
				self.delete_link (link)
		elif action.undo_type == UNDO_DELETE_LINK:
			if mode == UndoManager.UNDO:
				self.element.appendChild (link.element)
				self.links.append (link)
			else:
				self.delete_link (link)
		elif action.undo_type == UNDO_STRENGTHEN_LINK:
			if mode == UndoManager.UNDO:
				link.set_strength (action.args[1])
			else:
				link.set_strength (action.args[2])

		self.undo.unblock ()
		self.invalidate ()

	def connect_link (self, link):
		link.connect ("select_link", self.select_link)
		link.connect ("update_view", self.update_view)

	def create_link (self, thought, thought_coords, child, child_coords = None, strength = 2):
		for x in self.links:
			if x.connects (thought, child):
				if x.change_strength (thought, child):
					self.delete_link (x)
				return
		link = Link (self.save, parent = thought, child = child, strength = strength)
		self.connect_link (link)
		element = link.get_save_element ()
		self.element.appendChild (element)
		self.links.append (link)

		return link

	def set_mouse_cursor_cb (self, thought, cursor_type):
		if not self.moving:
			self.set_cursor (cursor_type)

	def update_all_links(self):
		map(lambda l : l.find_ends(), self.links)

	def update_links_cb (self, thought):
		for x in self.links:
			if x.uses (thought):
				x.find_ends ()

	def update_view (self, thought):
		self.invalidate ()

	def invalidate (self, transformed_area = None):
		'''Helper function to invalidate the entire screen, forcing a redraw'''
		rect = None
		if not transformed_area:
			alloc = self.get_allocation ()
			rect = gtk.gdk.Rectangle (0, 0, alloc.width, alloc.height)
		else:
			ul = self.untransform_coords(transformed_area[0], transformed_area[1])
			lr = self.untransform_coords(transformed_area[2], transformed_area[3])
			rect = gtk.gdk.Rectangle (int(ul[0]), int(ul[1]), int(lr[0]-ul[0]), int(lr[1]-ul[1]))
		if self.window:
			self.window.invalidate_rect (rect, True)

	def expose (self, widget, event):
		'''Expose event.  Calls the draw function'''
		context = self.window.cairo_create ()
		self.draw (event, context)
		return False

	def draw (self, event, context):
		'''Draw the map and all the associated thoughts'''
		area = event.area
		context.rectangle (area.x, area.y, area.width, area.height)
		context.clip ()
		context.set_source_rgb (1.0,1.0,1.0)
		context.move_to (area.x, area.y)
		context.paint ()
		context.set_source_rgb (0.0,0.0,0.0)
		
		alloc = self.get_allocation ()
		context.translate(alloc.width/2., alloc.height/2.)
		context.scale(self.scale_fac, self.scale_fac)
		context.translate(-alloc.width/2., -alloc.height/2.)		
		context.translate(self.translation[0], self.translation[1])
		
		for l in self.links:
			l.draw (context)
			
		self.untransform = context.get_matrix()
		self.transform = context.get_matrix()
		self.transform.invert()

		ax, ay = self.transform_coords(area.x, area.y)
		width  = area.width / self.scale_fac
		height = area.height / self.scale_fac
		for t in self.thoughts:
			try:
				if t.lr[0] >= ax and t.ul[0] <= ax + width and t.lr[1] >= ay and t.ul[1] <= ay + height:
					t.draw (context)
			except:
				t.draw(context)

		if self.is_bbox_selecting:
			xs = self.bbox_origin[0]
			ys = self.bbox_origin[1]
			xe = self.bbox_current[0] - xs
			ye = self.bbox_current[1] - ys
			
			xs,ys = context.user_to_device(xs, ys)
			xe,ye = context.user_to_device_distance(xe, ye)
			xs = int(xs) + 0.5
			ys = int(ys) + 0.5
			xe = int(xe)
			ye = int(ye)
			xs,ys = context.device_to_user(xs, ys)
			xe,ye = context.device_to_user_distance(xe, ye)

			color = utils.selected_colors["border"]
			context.set_line_width(2.0)
			context.set_source_rgb(color[0], color[1], color[2])
			context.rectangle(xs, ys, xe, ye)
			context.stroke()
			
			#color = utils.selected_colors["fill"]
			#context.set_source_rgba(color[0], color[1], color[2], 0.3)
			#context.rectangle(xs, ys, xe, ye)
			#context.fill()
			#context.set_line_width(2.0)
			#context.set_source_rgba(0.0, 0.0, 0.0, 1.0)

	def undo_create_cb (self, action, mode):
		self.undo.block ()
		if mode == UndoManager.UNDO:
			self.unselect_all ()
			for t in action.args[1]:
				self.select_thought (t, -1)
			self.delete_thought (action.args[0])
			self.emit ("change_mode", action.args[3])
		else:
			self.emit ("change_mode", action.args[2])
			thought = action.args[0]
			self.thoughts.append (thought)
			for t in action.args[1]:
				self.unselect_all ()
				self.select_thought (t, -1)
			self.hookup_im_context (thought)
			self.emit ("change_buffer", thought.extended_buffer)
			self.element.appendChild (thought.element)
			for l in action.args[5:]:
				self.links.append (l)
				self.element.appendChild (l.element)

		self.emit ("set_focus", None, False)
		self.undo.unblock ()
		self.invalidate ()

	def create_new_thought (self, coords, type = None, loading = False):
		self.set_focus(None, None)

		if not type:
			type = self.mode

		if type == MODE_TEXT:
			thought = TextThought.TextThought (coords, self.pango_context, self.nthoughts, self.save, self.undo, loading, self.background_color, self.foreground_color)
		elif type == MODE_LABEL:
			thought = LabelThought.LabelThought (coords, self.pango_context, self.nthoughts, self.save, self.undo, loading, self.background_color, self.foreground_color)
		elif type == MODE_IMAGE:
			thought = ImageThought.ImageThought (coords, self.pango_context, self.nthoughts, self.save, self.undo, loading, self.background_color, self.foreground_color)
		elif type == MODE_DRAW:
			thought = DrawingThought.DrawingThought (coords, self.pango_context, self.nthoughts, self.save, self.undo,	\
													 loading,self.background_color, self.foreground_color)
		elif type == MODE_RESOURCE:
			thought = ResourceThought.ResourceThought (coords, self.pango_context, self.nthoughts, self.save, self.undo, loading, self.background_color, self.foreground_color)
		if not thought.okay ():
			return None

		if type == MODE_IMAGE:
			self.emit ("change_mode", self.old_mode)
		self.nthoughts += 1
		element = thought.element
		self.element.appendChild (thought.element)
		thought.connect ("select_thought", self.select_thought)
		thought.connect ("create_link", self.create_link)
		thought.connect ("update_view", self.update_view)
		thought.connect ("text_selection_changed", self.text_selection_cb)
		thought.connect ("change_mouse_cursor", self.set_mouse_cursor_cb)
		thought.connect ("update_links", self.update_links_cb)
		thought.connect ("grab_focus", self.regain_focus_cb)
		thought.connect ("update-attrs", self.update_attr_cb)
		self.thoughts.append (thought)
		return thought

	def regain_focus_cb (self, thought, ext):
		self.emit ("set_focus", None, ext)

	def update_attr_cb (self, widget, bold, italics, underline, pango_font):
		self.emit ("set_attrs", bold, italics, underline, pango_font)

	def delete_thought (self, thought, undo = True):
		if undo:
			action = UndoManager.UndoAction (self, UNDO_DELETE_SINGLE, self.undo_deletion, [thought])
		else:
			action = None

		if thought.element in self.element.childNodes:
			self.element.removeChild (thought.element)
		self.thoughts.remove (thought)
		try:
			self.selected.remove (thought)
		except:
			pass
		if self.focus == thought:
			self.hookup_im_context ()
			self.focus = None
		if self.primary == thought:
			thought.disconnect (self.title_change_handler)
			self.title_change_handler = None
			self.primary = None
			if self.thoughts:
				self.make_primary (self.thoughts[0])
		rem_links = []
		for l in self.links:
			if l.uses (thought):
				if action: action.add_arg (l)
				rem_links.append (l)
		for l in rem_links:
			self.delete_link (l)

		for i, obj in enumerate(self.current_root):
			if obj == thought:
				del self.current_root[i]
				break

		if action:
			self.undo.add_undo (action)

		return True

	def undo_deletion (self, action, mode):
		self.undo.block ()
		if mode == UndoManager.UNDO:
			self.unselect_all ()
			for l in action.args[1:]:
				self.links.append (l)
				self.element.appendChild (l.element)
			for t in action.args[0]:
				self.thoughts.append (t)
				self.select_thought (t, -1)
				self.element.appendChild (t.element)
				if t.am_primary and not self.primary:
					self.emit ("change_buffer", action.args[0][0].extended_buffer)
					self.make_primary(t)
		else:
			for t in action.args[0]:
				self.delete_thought (t, False)
			for l in action.args[1:]:
				self.delete_link (l)
		self.emit ("set_focus", None, False)
		self.undo.unblock ()
		self.invalidate ()

	def delete_selected_elements (self):
		if len(self.selected) == 0:
			return
		action = UndoManager.UndoAction (self, UNDO_DELETE, self.undo_deletion, copy.copy(self.selected))

		try:
			# delete_thought as a callback adds it's own undo action.  Block that here
			self.undo.block ()

			tmp = self.selected
			t = tmp.pop()
			while t:
				if t in self.thoughts:
					for l in self.links:
						if l.uses (t):
							action.add_arg (l)
					self.delete_thought (t)
				if t in self.links:
					self.delete_link (t)
				if len (tmp) == 0:
					t = None
				else:
					t = tmp.pop()
		finally:
			self.undo.unblock ()

		self.undo.add_undo (action)
		self.invalidate ()

	def delete_link (self, link):
		if link.element in self.element.childNodes:
			self.element.removeChild (link.element)
		#link.element.unlink ()
		try:
			self.links.remove (link)
		except:
			pass

	def find_related_thought (self, radians):
		# Find thought within angle
		best = None
		bestangle = 1000.
		bestdist = 10000.
		def do_find (one, two, currentangle, curdist, sensitivity):
			init_x = (one.ul[0] + one.lr[0]) / 2.
			init_y = (one.ul[1] + one.lr[1]) / 2.
			other_x = (two.ul[0] + two.lr[0]) / 2.
			other_y = (two.ul[1] + two.lr[1]) / 2.
			angle = math.atan2 ((other_y - init_y), (other_x - init_x))
			while angle > math.pi:
				angle -= math.pi
			while angle < -math.pi:
				angle += math.pi
			# We have to special-case left due to stupidity of tan's
			# We shift it by pi radians
			if radians == RAD_LEFT:
				relangle = abs((angle+math.pi) - (radians+math.pi))
				if relangle > math.pi*2.:
					relangle -= math.pi*2.
			else:
				relangle = abs(angle - radians)
			newdist = math.sqrt ((init_x - other_x)**2 + (init_y - other_y)**2)
			magicnum = newdist + (50. * relangle)
# Used for debugging.  Spits out lots of useful info
# to determine interesting things about the thought relations
#print "angle: "+str(angle)+" rel: "+str(magicnum)+" rads: "+str(radians),
#print " , "+str(math.pi / 3.0)+" , "+str(currentangle)+"\n: "+str(relangle)
			if (relangle < sensitivity) and \
			   (magicnum < currentangle):
				return (magicnum, newdist)
			return (currentangle, curdist)

		if len(self.selected) != 1:
			return None
		initial = self.selected[0]
		for x in self.links:
			if x.parent == initial:
				other = x.child
			elif x.child == initial:
				other = x.parent
			else:
				continue
			(curr, dist) = do_find (initial, other, bestangle, bestdist, math.pi/3.)
			if curr < bestangle:
				bestangle = curr
				best = other
				bestdist = dist
		if not best:
			for x in self.thoughts:
				if x == self.selected[0]:
					continue
				(curr, dist) = do_find (initial, x, bestangle, bestdist, math.pi/4.)
				if curr < bestangle:
					best = x
					bestangle = curr
					bestdist = dist
		return best
	
	def undo_align(self, action, mode):
		self.undo.block ()
		dic = action.args[0]
		if mode == UndoManager.UNDO:
			for t in dic:
				t.move_by(-dic[t][0], -dic[t][1])
		else:
			for t in dic:
				t.move_by(dic[t][0], dic[t][1])
		self.undo.unblock ()

	def align_top_left(self, vertical=True):
		dic = {}
		if len(self.selected) != 0:
			x = self.selected[0].ul[0]
			y = self.selected[0].ul[1]
			for t in self.selected:
				if vertical:
					vec = (-(t.ul[0]-x), 0)
				else:
					vec = (0, -(t.ul[1]-y))
				t.move_by(vec[0], vec[1])
				dic[t] = vec
		self.undo.add_undo (UndoManager.UndoAction (self, UNDO_ALIGN, self.undo_align, dic))

	def align_bottom_right(self, vertical=True):
		dic = {}
		if len(self.selected) != 0:
			x = self.selected[0].lr[0]
			y = self.selected[0].lr[1]
			for t in self.selected:
				if vertical:
					vec = (-(t.lr[0]-x), 0)
				else:
					vec = (0, -(t.lr[1]-y))
				t.move_by(vec[0], vec[1])
				dic[t] = vec
		self.undo.add_undo (UndoManager.UndoAction (self, UNDO_ALIGN, self.undo_align, dic))
		
	def align_centered(self, vertical=True):
		dic = {}
		if len(self.selected) != 0:
			x = self.selected[0].ul[0] + (self.selected[0].lr[0] - self.selected[0].ul[0]) / 2.0
			y = self.selected[0].ul[1] + (self.selected[0].lr[1] - self.selected[0].ul[1]) / 2.0
			for t in self.selected:
				if vertical:
					vec = (-((t.ul[0] + (t.lr[0]-t.ul[0])/2.0)-x), 0)
				else:
					vec = (0, -((t.ul[1] + (t.lr[1]-t.ul[1])/2.0)-y))
				t.move_by(vec[0], vec[1])
				dic[t] = vec
		self.undo.add_undo (UndoManager.UndoAction (self, UNDO_ALIGN, self.undo_align, dic))
		
	def global_key_handler (self, event):
		thought = None
		if event.keyval == gtk.keysyms.Up:
			thought = self.find_related_thought (RAD_UP)
		elif event.keyval == gtk.keysyms.Down:
			thought = self.find_related_thought (RAD_DOWN)
		elif event.keyval == gtk.keysyms.Left:
			thought = self.find_related_thought (RAD_LEFT)
		elif event.keyval == gtk.keysyms.Right:
			thought = self.find_related_thought (RAD_RIGHT)			
		elif event.keyval == gtk.keysyms.Delete:
			self.delete_selected_elements ()
		elif event.keyval == gtk.keysyms.BackSpace:
			self.delete_selected_elements ()
		elif event.keyval == gtk.keysyms.Return:
			if self.focus:
				self.focus.enter()
		elif event.keyval == gtk.keysyms.Escape:
			if self.focus and self.focus.creating:
				self.undo.forget_action()
			self.unselect_all ()
			self.focus = None
		elif event.keyval == gtk.keysyms.a and event.state & gtk.gdk.CONTROL_MASK:
			self.unselect_all ()
			for t in self.thoughts:
				t.select ()
				self.selected.append (t)

		else:
			return False

		if thought:
			self.set_focus(thought, None)
		self.invalidate ()
		return True

	def load_thought (self, node, type, tar):
		thought = self.create_new_thought (None, type, loading = True)
		thought.creating = False
		thought.load (node, tar)

	def load_link (self, node):
		link = Link (self.save)
		self.connect_link (link)
		link.load (node)
		self.links.append (link)
		element = link.get_save_element ()
		self.element.appendChild (element)

	def load_thyself (self, top_element, doc, tar):
		for node in top_element.childNodes:
			if node.nodeName == "thought":
				self.load_thought (node, MODE_TEXT, tar)
			elif node.nodeName == "label_thought":
				self.load_thought (node, MODE_LABEL, tar)
			elif node.nodeName == "image_thought":
				self.load_thought (node, MODE_IMAGE, tar)
			elif node.nodeName == "drawing_thought":
				self.load_thought (node, MODE_DRAW, tar)
			elif node.nodeName == "res_thought":
				self.load_thought (node, MODE_RESOURCE, tar)
			elif node.nodeName == "link":
				self.load_link (node)
			else:
				print "Warning: Unknown element type.  Ignoring: "+node.nodeName

		self.finish_loading ()

	def finish_loading (self):
		# Possible TODO: This all assumes we've been given a proper,
		# consistant file.  It should fallback nicely, but...
		# First, find the primary root:
		for t in self.thoughts:
			if t.am_primary:
				self.make_primary (t)
			if t.am_selected:
				self.selected.append (t)
				t.select ()
			if t.identity >= self.nthoughts:
				self.nthoughts = t.identity + 1
		if self.selected:
			self.current_root = self.selected
		else:
			self.current_root = [self.primary]
		if len(self.selected) == 1:
			self.emit ("change_buffer", self.selected[0].extended_buffer)
			self.hookup_im_context (self.selected[0])
			self.emit ("thought_selection_changed", self.selected[0].background_color, \
				   self.selected[0].foreground_color)
		else:
			self.emit ("change_buffer", None)
		del_links = []
		for l in self.links:
			if (l.parent_number == -1 and l.child_number == -1) or \
			   (l.parent_number == l.child_number):
				del_links.append (l)
				continue
			parent = child = None
			for t in self.thoughts:
				if t.identity == l.parent_number:
					parent = t
				elif t.identity == l.child_number:
					child = t
				if parent and child:
					break
			l.set_parent_child (parent, child)
			if not l.parent or not l.child:
				del_links.append (l)
		for l in del_links:
			self.delete_link (l)

	def update_save(self):
		for t in self.thoughts:
			t.update_save ()
		for l in self.links:
			l.update_save ()

	def save_thyself(self, tar):
		for t in self.thoughts:
			t.save(tar)

	def text_selection_cb (self, thought, start, end, text):
		self.emit ("text_selection_changed", start, end, text)

	def copy_clipboard (self, clip):
		if len (self.selected) != 1:
			return
		self.selected[0].copy_text (clip)

	def cut_clipboard (self, clip):
		if len (self.selected) != 1:
			return
		self.selected[0].cut_text (clip)

	def paste_clipboard (self, clip):
		if len (self.selected) != 1:
			return
		self.selected[0].paste_text (clip)

	def export (self, context, width, height, native):
		context.rectangle (0, 0, width, height)
		context.clip ()
		context.set_source_rgb (1.0,1.0,1.0)
		context.move_to (0,0)
		context.paint ()
		context.set_source_rgb (0.0,0.0,0.0)
		if not native:
			move_x = self.move_x
			move_y = self.move_y
		else:
			move_x = 0
			move_y = 0
		for l in self.links:
			l.export (context, move_x, move_y)
		for t in self.thoughts:
			t.export (context, move_x, move_y)

	def get_max_area (self):
		minx = 999
		maxx = -999
		miny = 999
		maxy = -999

		for t in self.thoughts:
			mx,my,mmx,mmy = t.get_max_area ()
			if mx < minx:
				minx = mx
			if my < miny:
				miny = my
			if mmx > maxx:
				maxx = mmx
			if mmy > maxy:
				maxy = mmy
		# Add a 10px border around all
		self.move_x = 10-minx
		self.move_y = 10-miny
		maxx = maxx-minx+20
		maxy = maxy-miny+20
		return (maxx,maxy)

	def get_selection_bounds (self):
		if len (self.selected) == 1:
			try:
				return self.selected[0].index, self.selected[0].end_index
			except AttributeError:
				return None, None
		else:
			return None, None

	def thoughts_are_linked (self):
		if len (self.selected) != 2:
			return False
		for l in self.links:
			if l.connects (self.selected[0], self.selected[1]):
				return True
		return False

	def link_menu_cb (self):
		if len (self.selected) != 2:
			return
		if not self.selected[0].can_be_parent() or \
			not self.selected[1].can_be_parent():
				return
		lnk = None
		for l in self.links:
			if l.connects (self.selected[0], self.selected[1]):
				lnk = l
				break
		if lnk:
			self.undo.add_undo (UndoManager.UndoAction (self, UNDO_DELETE_LINK, self.undo_link_action, lnk))
			self.delete_link (lnk)
		else:
			lnk = self.create_link (self.selected[0], None, self.selected[1])
			self.undo.add_undo (UndoManager.UndoAction (self, UNDO_CREATE_LINK, self.undo_link_action, lnk))
		self.invalidate ()

	def set_bold (self, active):
		if len(self.selected) != 1:
			return
		self.selected[0].set_bold (active)
		self.invalidate()
		
	def set_italics (self, active):
		if len(self.selected) != 1:
			return
		self.selected[0].set_italics (active)
		self.invalidate()
		
	def set_underline (self, active):
		if len(self.selected) != 1:
			return
		self.selected[0].set_underline (active)
		self.invalidate()
	
	def set_background_color(self, color):
		for s in self.selected:
			s.background_color = color
			self.background_color = color
		if len(self.selected) > 1:
			self.invalidate()

	def set_foreground_color(self, color):
		for s in self.selected:
			s.foreground_color = color
			self.foreground_color = color
		if len(self.selected) > 1:
			self.invalidate()

	def set_font(self, font_name, font_size):
		if len (self.selected) == 1 and hasattr(self.selected[0], "set_font"):
			self.selected[0].set_font(font_name, font_size)
			self.font_name = font_name
			self.font_size = font_size
			self.invalidate()

	def embody_thought(self, event):
		coords = self.transform_coords (event.get_coords()[0], event.get_coords()[1])
		thought = self.create_new_thought(coords)
		sel = self.selected

		if not thought:
			return True
		if not self.primary and \
			thought.can_be_parent():
				self.make_primary (thought)
				self.select_thought (thought, None)
		else:
			self.emit ("change_buffer", thought.extended_buffer)
			self.hookup_im_context (thought)
			# Creating links adds an undo action.  Block it here
			self.undo.block ()
			if not self.current_root:
				self.current_root.append(self.primary)
			if thought.can_be_parent():
				for x in self.current_root:
					if x.can_be_parent():
						self.create_link (x, None, thought)
			for x in self.selected:
				x.unselect ()
			self.selected = [thought]
			thought.select ()

		self.undo.unblock ()
		thought.foreground_color = self.foreground_color
		thought.background_color = self.background_color
		act = UndoManager.UndoAction (self, UNDO_CREATE, self.undo_create_cb, thought, sel, \
									  self.mode, self.old_mode, event.get_coords())
		for l in self.links:
			if l.uses (thought):
				act.add_arg (l)
		"""
		if self.undo.peak ().undo_type == UNDO_DELETE_SINGLE:
			last_action = self.undo.pop ()
			action = UndoManager.UndoAction (self, UNDO_COMBINE_DELETE_NEW, self.undo_joint_cb, \
											 last_action, act)
			self.undo.add_undo (action)
		else:
		"""
		self.undo.add_undo (act)

		thought.enter()
		thought.includes(coords)
		event.button = 1
		thought.process_button_down(event, coords)
		self.focus = thought

class CursorFactory:
	__shared_state = {"cursors": {}}

	def __init__(self):
		self.__dict__ = self.__shared_state

	def get_cursor(self, cur_type):
		if not self.cursors.has_key(cur_type):
			cur = gtk.gdk.Cursor(cur_type)
			self.cursors[cur_type] = cur
		return self.cursors[cur_type]

