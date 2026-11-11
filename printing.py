"""One Pango/Cairo paginator shared by preview, PDF and physical printing."""
from collections import OrderedDict
import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Pango, PangoCairo, GdkPixbuf, Gdk, GLib, Gio
from model import (blank,decode_image,validate_document,MAX_IMAGE_PIXELS,ResourceLimitError,resolved_style,
                   DOCUMENT_DPI,POINTS_PER_PIXEL,DOCUMENT_FONT,DOCUMENT_FONT_SIZE,PARAGRAPH_SPACING_PX,RULE_HEIGHT_PX,fit_image_dimensions)
from filesystem import atomic_export
from application import register_document_fonts
register_document_fonts()
import io
_image_cache=OrderedDict()
_image_cache_bytes=0
_IMAGE_CACHE_LIMIT=24*1024*1024

def clear_image_cache():
    global _image_cache_bytes
    _image_cache.clear();_image_cache_bytes=0

def pixbuf_for(src):
    global _image_cache_bytes
    if src in _image_cache:
        pix,cost=_image_cache.pop(src);_image_cache[src]=(pix,cost)
        return pix
    raw = decode_image(src)
    loader = GdkPixbuf.PixbufLoader.new()
    oversized=[]
    def prepared(loader,width,height):
        if width*height>MAX_IMAGE_PIXELS:
            oversized.append(True);loader.set_size(1,1)
    loader.connect('size-prepared',prepared)
    loader.write(raw)
    loader.close()
    p = loader.get_pixbuf()
    if oversized or p.get_width() * p.get_height() > MAX_IMAGE_PIXELS:
        raise ResourceLimitError('The photo has too many pixels (maximum 16 megapixels).')
    cost=p.get_byte_length()+len(src)
    if cost<=_IMAGE_CACHE_LIMIT:
        while _image_cache and _image_cache_bytes+cost>_IMAGE_CACHE_LIMIT:
            _,(_,removed)=_image_cache.popitem(last=False);_image_cache_bytes-=removed
        _image_cache[src]=(p,cost);_image_cache_bytes+=cost
    return p


class Pages:
    def __init__(self, doc, width=595.276, height=841.89, margin=42.52, text_context=None):
        self.doc, self.width, self.height, self.margin = validate_document(doc), width, height, margin
        # Match the GTK renderer actually in use. In particular, older GTK
        # versions hint font metrics, while newer versions use fractional ones.
        options=PangoCairo.context_get_font_options(text_context) if text_context else None
        self.font_options=options.copy() if options else cairo.FontOptions()
        if not options:self.font_options.set_hint_metrics(cairo.HINT_METRICS_OFF)
        self.round_glyph_positions=text_context.get_round_glyph_positions() if text_context else False
        self.text_language=text_context.get_language() if text_context else None
        self.pixbufs={}
        self.sorted_spans=sorted(enumerate(self.doc['spans']),key=lambda item:item[1]['start'])
        self.span_cursor=0;self.active_spans=[];self.last_span_start=-1
        self.pages = [[]]
        self.y = margin
        # Round paper and margins separately to keep pixel-based layout stable
        # before converting back to printer points.
        self.content_width_pixels=max(1,round(width/POINTS_PER_PIXEL)-2*round(margin/POINTS_PER_PIXEL))
        self.content_height_pixels=max(1,round(height/POINTS_PER_PIXEL)-2*round(margin/POINTS_PER_PIXEL))
        self.content_width=self.content_width_pixels*POINTS_PER_PIXEL
        self.context = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        self.paginate()

    def reserve(self, height):
        if self.y + height > self.height - self.margin and self.pages[-1]:
            if len(self.pages)>=1000:raise ResourceLimitError('Print preview exceeds the 1000-page limit.')
            self.pages.append([])
            self.y = self.margin

    def spans_for(self,start,end):
        # Pagination moves forward; retain only spans overlapping the current range.
        if start<self.last_span_start:
            self.span_cursor=0;self.active_spans=[]
        self.last_span_start=start
        self.active_spans=[item for item in self.active_spans if item[1]['end']>start]
        while self.span_cursor<len(self.sorted_spans) and self.sorted_spans[self.span_cursor][1]['start']<end:
            item=self.sorted_spans[self.span_cursor];self.span_cursor+=1
            if item[1]['end']>start:self.active_spans.append(item)
        return [span for _,span in sorted(self.active_spans) if span['start']<end and span['end']>start]

    def style_at(self, offset):
        style={}
        for span in self.spans_for(offset,offset+1):style.update(span['style'])
        return style

    def text_layout(self, text, offset):
        layout = PangoCairo.create_layout(self.context)
        PangoCairo.context_set_resolution(layout.get_context(), DOCUMENT_DPI)
        PangoCairo.context_set_font_options(layout.get_context(),self.font_options)
        layout.get_context().set_round_glyph_positions(self.round_glyph_positions)
        if self.text_language:layout.get_context().set_language(self.text_language)
        layout.set_font_description(Pango.FontDescription(DOCUMENT_FONT+' '+str(DOCUMENT_FONT_SIZE)))
        layout.set_width(self.content_width_pixels * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        align = self.style_at(offset).get('align', 'left')
        layout.set_alignment({'left': Pango.Alignment.LEFT, 'center': Pango.Alignment.CENTER,
                              'right': Pango.Alignment.RIGHT}.get(align, Pango.Alignment.LEFT))
        layout.set_justify(align == 'justify')
        layout.set_text(text or ' ', -1)
        attrs = Pango.AttrList()
        spans=self.spans_for(offset,offset+len(text))
        boundaries={max(0,s['start']-offset) for s in spans}|{min(len(text),s['end']-offset) for s in spans}
        byte_offsets={};previous=total=0
        for position in sorted(boundaries):
            total+=len(text[previous:position].encode('utf-8'));byte_offsets[position]=total;previous=position
        for s in spans:
            start, end = max(offset, s['start']), min(offset + len(text), s['end'])
            if end <= start: continue
            style = resolved_style(s['style'])
            items = []
            if style.get('line_spacing') is not None:items.append(Pango.attr_line_height_new(style['line_spacing']))
            if style.get('weight'): items.append(Pango.attr_weight_new(Pango.Weight.BOLD))
            if style.get('font_weight'):
                # Numeric CSS weights include values without a Pango.Weight enum.
                # Parse a weight-only description to preserve them on strict GI.
                weight=Pango.FontDescription.from_string('weight='+str(style['font_weight']))
                items.append(Pango.attr_font_desc_new(weight))
            if style.get('italic'): items.append(Pango.attr_style_new(Pango.Style.ITALIC))
            if style.get('font_style')=='normal':items.append(Pango.attr_style_new(Pango.Style.NORMAL))
            if style.get('font_style')=='oblique':items.append(Pango.attr_style_new(Pango.Style.OBLIQUE))
            if style.get('stretch') is not None:items.append(Pango.attr_stretch_new(Pango.Stretch(style['stretch'])))
            if style.get('underline'): items.append(Pango.attr_underline_new(Pango.Underline.SINGLE))
            if style.get('strike'): items.append(Pango.attr_strikethrough_new(True))
            if style.get('family'): items.append(Pango.attr_family_new(style['family']))
            if style.get('size'): items.append(Pango.attr_size_new(int(style['size'] * Pango.SCALE)))
            if style.get('foreground') and not style.get('link'):
                colour=style['foreground'][1:]
                items.append(Pango.attr_foreground_new(*(int(colour[i:i+2],16)*257 for i in (0,2,4))))
            if style.get('link'):
                color='9141ac' if style['link']['kind']=='document' else '1c71d8'
                items.append(Pango.attr_foreground_new(*(int(color[i:i+2],16)*257 for i in (0,2,4))))
                items.append(Pango.attr_underline_new(Pango.Underline.SINGLE))
            if style.get('background'):
                color = style['background'].lstrip('#')
                rgb = [int(color[i:i+2], 16)*257 for i in (0,2,4)]
                items.append(Pango.attr_background_new(*rgb))
            for attr in items:
                attr.start_index = byte_offsets[start-offset]
                attr.end_index = byte_offsets[end-offset]
                attrs.insert(attr)
        layout.set_attributes(attrs)
        return layout

    def text(self,text,offset):
        layout=self.text_layout(text,offset)
        iterator = layout.get_iter()
        while True:
            line = iterator.get_line_readonly()
            _, logical = iterator.get_line_extents()
            baseline = iterator.get_baseline() / Pango.SCALE * POINTS_PER_PIXEL
            h = logical.height / Pango.SCALE * POINTS_PER_PIXEL
            self.reserve(h)
            self.pages[-1].append(('line', layout, line, self.y + baseline - logical.y / Pango.SCALE * POINTS_PER_PIXEL))
            self.y += h
            if not iterator.next_line(): break
        self.y += PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL

    def image_rows(self,images):
        row=[];width=0
        def flush():
            if not row:return
            height=max(item[2] for item in row)
            self.reserve(height+PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL)
            align=self.style_at(row[0][4]).get('align','left')
            x=self.margin+(self.content_width-width)*{'center':.5,'right':1}.get(align,0)
            for pix,w,h,gap,_offset in row:
                x+=gap
                self.pages[-1].append(('image',pix,x,self.y+height-h,w,h))
                x+=w
            self.y+=height+PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL
        for img,gap in images:
            src=img['src']
            pix=self.pixbufs.get(src)
            if pix is None:pix=self.pixbufs[src]=pixbuf_for(src)
            w,h=fit_image_dimensions(img['width'],img['height'],self.content_width_pixels,
                                     max(1,self.content_height_pixels-PARAGRAPH_SPACING_PX))
            w,h=w*POINTS_PER_PIXEL,h*POINTS_PER_PIXEL
            if row and width+gap+w>self.content_width:
                flush();row=[];width=0
            if not row:gap=0
            row.append((pix,w,h,gap,img['offset']));width+=gap+w
        flush()

    def table(self,table):
        widths=[self.content_width*w/sum(table['widths']) for w in table['widths']]
        for row in table['cells']:
            layouts=[]
            for value,width in zip(row,widths):
                layout=self.text_layout('',table['offset'])
                layout.set_attributes(Pango.AttrList());layout.set_alignment(Pango.Alignment.LEFT);layout.set_justify(False)
                layout.set_text(value or ' ',-1)
                layout.set_width(max(1,round((width-12)/POINTS_PER_PIXEL))*Pango.SCALE)
                layouts.append(layout)
            height=max(l.get_size()[1]/Pango.SCALE*POINTS_PER_PIXEL for l in layouts)+12
            consumed=0
            while consumed<height:
                fragment=min(height-consumed,self.height-2*self.margin)
                self.reserve(fragment)
                fragment=min(fragment,self.height-self.margin-self.y)
                self.pages[-1].append(('table-row',layouts,widths,self.y,fragment,consumed,table.get('border',1)))
                self.y+=fragment;consumed+=fragment
        self.y+=PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL

    def paginate(self):
        images={i['offset']:i for i in self.doc['images']}
        rules=set(self.doc.get('rules',[]))
        tables={t['offset']:t for t in self.doc.get('tables',[])}
        offset=0
        for line in self.doc['text'].split('\n'):
            pos=0;pending=[]
            def flush_images(pending=pending):
                if pending:self.image_rows(pending);pending.clear()
            for index,char in enumerate(line):
                absolute=offset+index
                if char!='\ufffc' or absolute not in images and absolute not in rules and absolute not in tables:continue
                segment=line[pos:index]
                gap=0
                if segment:
                    if pending and segment.isspace() and absolute in images:
                        gap=self.text_layout(segment,offset+pos).get_size()[0]/Pango.SCALE*POINTS_PER_PIXEL
                    else:
                        flush_images();self.text(segment,offset+pos)
                if absolute in tables:
                    flush_images();self.table(tables[absolute])
                elif absolute in rules:
                    flush_images()
                    height=RULE_HEIGHT_PX*POINTS_PER_PIXEL
                    self.reserve(height+PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL)
                    self.pages[-1].append(('rule',self.margin,self.y+height/2,self.content_width))
                    self.y+=height+PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL
                else:pending.append((images[absolute],gap))
                pos=index+1
            flush_images()
            if pos<len(line) or not line:self.text(line[pos:],offset+pos)
            offset+=len(line)+1

    def draw(self, cr, page):
        cr.set_source_rgb(1,1,1)
        cr.rectangle(0,0,self.width,self.height)
        cr.fill()
        cr.set_source_rgb(.08,.08,.08)
        for item in self.pages[page]:
            if item[0] == 'line':
                _, layout, line, y = item
                # LayoutLine drawing uses its baseline as origin; honor alignment via line extents.
                _, logical = line.get_extents()
                alignment = layout.get_alignment()
                width = logical.width / Pango.SCALE * POINTS_PER_PIXEL
                x = self.margin + (self.content_width-width) * ({Pango.Alignment.CENTER:.5, Pango.Alignment.RIGHT:1}.get(alignment,0))
                cr.save()
                cr.translate(x,y)
                cr.scale(POINTS_PER_PIXEL,POINTS_PER_PIXEL)
                cr.move_to(0,0)
                PangoCairo.show_layout_line(cr, line)
                cr.restore()
            elif item[0]=='table-row':
                _,layouts,widths,y,height,consumed,border=item
                x=self.margin
                for layout,width in zip(layouts,widths):
                    cr.save();cr.rectangle(x,y,width,height);cr.clip()
                    cr.set_source_rgb(.08,.08,.08);cr.translate(x+6,y+6-consumed)
                    cr.scale(POINTS_PER_PIXEL,POINTS_PER_PIXEL);PangoCairo.show_layout(cr,layout);cr.restore()
                    cr.save();cr.set_source_rgb(.5,.5,.5);cr.set_line_width(border*POINTS_PER_PIXEL)
                    if border:cr.rectangle(x,y,width,height);cr.stroke()
                    cr.restore();x+=width
            elif item[0]=='rule':
                _,x,y,width=item
                cr.save()
                cr.set_source_rgb(.45,.45,.45)
                cr.set_line_width(.75)
                cr.move_to(x,y);cr.line_to(x+width,y);cr.stroke()
                cr.restore()
            else:
                _, pix, x, y, w, h = item
                cr.save()
                cr.translate(x,y)
                cr.scale(w/pix.get_width(),h/pix.get_height())
                Gdk.cairo_set_source_pixbuf(cr,pix,0,0)
                cr.paint()
                cr.restore()

    def pdf(self, path):
        output=io.BytesIO()
        surface = cairo.PDFSurface(output, self.width, self.height)
        cr = cairo.Context(surface)
        for n in range(len(self.pages)):
            self.draw(cr,n)
            cr.show_page()
        surface.finish()
        atomic_export(path,output.getvalue())


class PrintPreview(Gtk.Window):
    def __init__(self, parent, doc):
        self.document_owner=parent
        super().__init__(title='Print preview', transient_for=parent.dialog_parent() if hasattr(parent,'dialog_parent') else parent, default_width=850, default_height=800)
        self.closed=False;self.file_dialogs=[];self.print_operation=None
        self.set_destroy_with_parent(True)
        self.connect('close-request',self.close_requested)
        self.connect('unrealize',self.cleanup)
        self.doc, self.index = doc, 0
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        controls = Gtk.Box(spacing=8)
        self.paper = Gtk.DropDown.new_from_strings(['A4','A5','Letter'])
        self.orientation = Gtk.DropDown.new_from_strings(['Portrait','Landscape'])
        self.margin = Gtk.SpinButton.new_with_range(5,40,1)
        self.margin.set_value(15)
        for label, widget in [('Paper', self.paper), ('Orientation',self.orientation), ('Margin (mm)',self.margin)]:
            controls.append(Gtk.Label(label=label))
            controls.append(widget)
        root.append(controls)
        nav = Gtk.Box(spacing=8)
        for icon,tooltip,step in [('go-previous-symbolic','Previous page',-1),
                                  ('go-next-symbolic','Next page',1)]:
            b=Gtk.Button(icon_name=icon,tooltip_text=tooltip)
            b.update_property([Gtk.AccessibleProperty.LABEL],[tooltip])
            b.connect('clicked',lambda _,direction=step:self.turn(direction))
            nav.append(b)
        for label, callback in [('Save PDF…',self.save_pdf), ('Print…',self.print_document)]:
            b=Gtk.Button(label=label)
            b.connect('clicked',callback)
            nav.append(b)
        self.label=Gtk.Label()
        nav.append(self.label)
        root.append(nav)
        self.area=Gtk.DrawingArea(vexpand=True,hexpand=True)
        self.area.set_draw_func(self.draw)
        root.append(self.area)
        self.set_child(root)
        self.paper.connect('notify::selected',self.rebuild)
        self.orientation.connect('notify::selected',self.rebuild)
        self.margin.connect('value-changed',self.rebuild)
        self.rebuild()

    def rebuild(self,*_):
        w,h={'A4':(595.276,841.89),'A5':(419.528,595.276),'Letter':(612,792)}[self.paper.get_selected_item().get_string()]
        if self.orientation.get_selected(): w,h=h,w
        parent=self.document_owner
        editor=getattr(parent,'active_editor',parent)
        view=getattr(editor,'view',None)
        self.pages=Pages(self.doc,w,h,self.margin.get_value()*72/25.4,
                         text_context=view.get_pango_context() if view else None)
        self.index=min(self.index,len(self.pages.pages)-1)
        self.refresh()

    def turn(self,step):
        self.index=max(0,min(len(self.pages.pages)-1,self.index+step))
        self.refresh()

    def refresh(self):
        self.label.set_text(f'Page {self.index+1} / {len(self.pages.pages)}')
        self.area.queue_draw()

    def draw(self,area,cr,w,h):
        cr.set_source_rgb(.25,.25,.25)
        cr.paint()
        if self.closed or not self.pages or w<=24 or h<=24:return
        scale=min((w-24)/self.pages.width,(h-24)/self.pages.height)
        cr.translate((w-self.pages.width*scale)/2,(h-self.pages.height*scale)/2)
        cr.scale(scale,scale)
        self.pages.draw(cr,self.index)

    def save_pdf(self,*_):
        if self.closed:return
        dialog=Gtk.FileDialog(title='Save PDF',modal=True,initial_name='document.pdf')
        filters=Gio.ListStore.new(Gtk.FileFilter);pdf=Gtk.FileFilter(name='PDF document (.pdf)');pdf.add_pattern('*.pdf');filters.append(pdf);dialog.set_filters(filters)
        cancellable=Gio.Cancellable();self.file_dialogs.append(cancellable)
        def finished(dialog,result):
            if cancellable in self.file_dialogs:self.file_dialogs.remove(cancellable)
            parent=self.get_transient_for()
            try:
                file=dialog.save_finish(result)
                if self.closed or not parent or getattr(parent,'closed',False) or not file:return
                path=file.get_path()
                if not path:raise ValueError('Choose a local PDF file.')
                from filesystem import vault_container
                if vault_container(path):raise ValueError('Choose a PDF location outside an encrypted vault.')
                if hasattr(parent,'validate_export_path'):path=parent.validate_export_path(path)
                self.pages.pdf(path)
            except GLib.Error as exc:
                cancelled=(exc.matches(Gtk.dialog_error_quark(),Gtk.DialogError.DISMISSED) or
                           exc.matches(Gtk.dialog_error_quark(),Gtk.DialogError.CANCELLED) or
                           exc.matches(Gio.io_error_quark(),Gio.IOErrorEnum.CANCELLED))
                if not cancelled and parent and not self.closed:parent.error(str(exc))
            except (OSError,ValueError) as exc:
                if parent and not self.closed:parent.error(str(exc))
        dialog.save(self,cancellable,finished)

    def close_requested(self,*_):
        self.cleanup();return False

    def cleanup(self,*_):
        if self.closed:return
        self.closed=True
        if self.print_operation:self.print_operation.cancel()
        for cancellable in self.file_dialogs:cancellable.cancel()
        self.file_dialogs=[]
        self.area.set_draw_func(None);self.doc=blank();self.pages=None

    def destroy(self):
        self.cleanup();super().destroy()

    def print_document(self,*_,parent=None):
        if self.closed:return
        op=Gtk.PrintOperation()
        self.print_operation=op
        op.set_unit(Gtk.Unit.POINTS)
        op.set_use_full_page(True)
        setup=Gtk.PageSetup()
        paper=Gtk.PaperSize.new_custom('twinly','Twinly',self.pages.width,self.pages.height,Gtk.Unit.POINTS)
        setup.set_paper_size(paper)
        op.set_default_page_setup(setup)
        def begin_print(operation,context):
            if self.closed or self.pages is None:operation.cancel();return
            operation.set_n_pages(len(self.pages.pages))
        op.connect('begin-print',begin_print)
        def draw_page(operation,context,page):
            if self.closed or self.pages is None:operation.cancel();return
            cr=context.get_cairo_context()
            cr.save()
            factor=min(context.get_width()/self.pages.width,context.get_height()/self.pages.height)
            cr.scale(factor,factor)
            self.pages.draw(cr,page)
            cr.restore()
        op.connect('draw-page',draw_page)
        try: op.run(Gtk.PrintOperationAction.PRINT_DIALOG,parent or self)
        except GLib.Error as exc:
            owner=self.get_transient_for()
            if owner and not self.closed:owner.error(str(exc))
        finally:self.print_operation=None
