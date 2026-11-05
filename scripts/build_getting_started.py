"""Rebuild the editable, self-contained English introduction from bundled content."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import blank,to_html,image_data

root=Path(__file__).resolve().parent.parent
doc=blank()


def paragraph(text,style=None):
    if doc['text']:doc['text']+='\n'
    start=len(doc['text']);doc['text']+=text
    if style:doc['spans'].append({'start':start,'end':len(doc['text']),'style':{'paragraph':style}})
    return start


def heading(text,style='h1'):paragraph(text,style)


def feature(name,how):
    start=paragraph(name+' — '+how)
    doc['spans'].append({'start':start,'end':start+len(name),'style':{'weight':True}})


heading('Getting Started with Twinly','title')
paragraph('Welcome to Twinly: a local place to write, organise and connect your notes. No account or internet connection is needed for writing. This guide is a real note: you can edit it, make a copy or keep it beside your own work.')

heading('Start here')
paragraph('1. Create your own workspace. Click Workspaces in the left sidebar → More… → New workspace…. Give it a name and choose Standard — Not encrypted or Encrypted — Password protected. Starter Workspace is not encrypted; use it to explore the app.')
paragraph('2. Add a note. Click the large + below Workspaces → New note. It is created in the current workspace, inside the selected folder when applicable. Type its name and press Enter. Use the same + menu → New folder to organise your notes.')
paragraph('3. Start writing. New notes are editable immediately. An existing note opens for reading: click the pencil to the left of its title to edit it. Hover near the top of the writing area to reveal the formatting toolbar.')
paragraph('4. Save and return to reading. Click the checkmark that replaces the pencil, or use Ctrl+S to save while continuing to edit. Named notes also save automatically after about two seconds without typing.')
paragraph('Try the steps in your own workspace, then return to this guide whenever you need a reminder. Every new standard workspace includes a copy. Encrypted workspaces start empty.')

heading('Your workspaces and folders')
feature('Choose a workspace','Click Workspaces to see the existing workspaces, then choose one. It opens in the same window. More… opens the right-hand Workspaces pane, where you can create, rename, import or delete workspaces.')
feature('Recognise protection','An open padlock means Not encrypted. A closed padlock means Encrypted — Locked. An open padlock with a shield means Encrypted — Unlocked. Opening a locked workspace asks for its password.')
feature('Keep everything together','Twinly keeps your workspaces, folders, notes and Workspace Trash in its own managed data folder. You choose workspace names in the app. Import workspace makes a verified copy of an existing folder; the original stays unchanged.')
feature('Add and rename','The + menu creates a New note or New folder in the current workspace and selected folder. Ctrl+N also creates a note; Ctrl+Shift+N creates a folder. New items appear immediately with their names ready to edit. Enter confirms; Escape keeps the default name. Later, double-click an item in the sidebar, press F2 or use its context menu to rename it.')
feature('Move items','Drag a note or folder onto another folder, or right-click it → Move to…. Twinly updates internal links when you move or rename items through the app. Keep a collection together when copying it elsewhere; rearranging files outside Twinly may break relative links.')
feature('Adjust the sidebar','Drag its right edge to change its width. The sidebar icon at the left of the headerbar shows or hides the folders.')
feature('Switch safely','Each workspace remembers its open notes, pane arrangement, zoom and scroll positions. Twinly asks about unsaved standard-workspace changes when necessary. Leaving an encrypted workspace saves its notes or encrypted drafts and locks it. A failed save, wrong password or cancelled unlock keeps the current workspace available.')

heading('Reading, editing and saving')
feature('The pencil and checkmark','The pencil stays to the left of each document title. Click it to enable editing. Its checkmark saves and returns that document to reading mode. Failed or cancelled saves leave editing enabled. Reading mode still allows selection, copying, searching, following links and printing.')
feature('Rename a note from its title','Click the title in the headerbar, type a new name and press Enter. Escape cancels. Titles stay visible; a thin blue underline marks the active document.')
feature('Save As and copies','Ctrl+S saves. Ctrl+Shift+S opens Save As to choose another name. Make a copy in the document menu, or Ctrl+Shift+D, creates a separate copy. Export as… sits below Save as… in the standard document menu and creates a copy in another format.')
feature('Automatic saving and recovery','Named notes autosave after a short pause. An unnamed recovered draft needs saving first. After an unexpected exit, use Recover documents… in the sidebar menu to reopen available drafts. Recovery opens a separate draft rather than overwriting the original. Standard-workspace recovery is not encrypted; encrypted-workspace recovery stays encrypted. Recovery cannot replace regular backups.')
feature('Save warnings','If saving fails or another program changes the file, Twinly shows a warning. Resolve the warning and save your work before closing. Use the checkmark or Ctrl+S whenever you want to save explicitly.')

heading('Format your writing')
paragraph('While editing, hover near the top of the document to show the compact floating toolbar. Move back into the text to hide it. The eye icon in the headerbar toggles Always show toolbar; this is off by default and your choice is remembered. In-document search temporarily hides the toolbar to keep its controls clear.')
feature('Default document fonts','Twinly includes Noto Sans Regular, Bold, Italic and Bold Italic, so these fonts are available inside the app on every installation. New text starts with these defaults:')
paragraph('• Body — Noto Sans Regular, 12 pt.')
paragraph('• Title — Noto Sans Bold, 28 pt.')
paragraph('• Heading 1 — Noto Sans Bold, 24 pt.')
paragraph('• Heading 2 — Noto Sans Bold, 20 pt.')
paragraph('• Heading 3 — Noto Sans Bold, 17 pt.')
feature('Paragraph styles','Place the cursor in a paragraph, or select several paragraphs, and choose Body, Title, Subtitle, Heading 1–3 or Quote from the toolbar’s paragraph-style menu. Enter after a heading returns to Body. Explicit font choices and other custom formatting can override the defaults.')
feature('Choose a font or size','Select text and click the font icon in the toolbar. Choose its family, variant and size. With no selection, the choice applies to the text you type next. Zoom changes only the view; font size changes the document.')
feature('Bold, italic and underline','Use the formatting buttons or Ctrl+B, Ctrl+I and Ctrl+U. Ctrl+Shift+X toggles strikethrough. These work with Noto Sans and with your own font choices.')
feature('Colour and highlighting','Select text, then use the text-colour or highlighter controls. Custom colours are available; your recent text colours are remembered. Right-click selected text for highlight swatches. The white swatch with a red diagonal removes highlighting. Ctrl+Shift+H opens the highlight palette.')
feature('Alignment and clearing','Use left, centre, right or justified alignment, or Ctrl+L, Ctrl+E, Ctrl+R and Ctrl+J. The clear-formatting button, or Ctrl+Backslash, removes selected formatting without deleting the text.')
feature('Lists and checkboxes','Use the bullet, number or checkbox buttons. Shortcuts: Ctrl+Shift+7, Ctrl+Shift+8 and Ctrl+Shift+9. Enter continues the list; Enter on an empty item ends it. Click a checkbox while editing to change its state. Lists use simple text prefixes rather than nested levels or automatic renumbering.')
paragraph('• Try editing this bullet item.')
paragraph('1. Try continuing this numbered list.')
paragraph('☐ Click the pencil first, then check this item.')
feature('Custom styles','Choose Create style from selection in the paragraph-style menu to save your preferred font, size, colour and paragraph role. Manage styles lets you edit or remove saved definitions. An asterisk marks manual changes to a styled paragraph. Choose its style again to restore the saved appearance. Used definitions travel with the HTML note; fonts themselves are not embedded in exported HTML.')
feature('Undo and redo','Ctrl+Z undoes an edit. Ctrl+Shift+Z or Ctrl+Y redoes it. Each document pane has its own history.')

heading('Search and Trash on the right')
feature('Find a note','Click the search icon at the bottom of the sidebar, or press Ctrl+Shift+O. The right-hand Search pane filters note names in the current workspace and its subfolders; in standard workspaces it also matches folder paths. It does not search the contents of every note. Choose a result to open it.')
feature('Close or change the panel','Click the sidebar search icon again to close Search. The Trash icon works the same way: click once to open its right-hand pane, then again to close it. Each panel also has a close button. These share the Workspaces pane area; they do not create another document pane. Resizing the window keeps your open or closed choice.')
feature('Trash a note or folder','Right-click it in the sidebar → Move to Trash…. The sidebar Trash pane shows deleted items from the current workspace. Restore returns an item to its original location. Restore refuses to overwrite another item with the same name. Empty trash permanently deletes its contents after confirmation.')
feature('Workspace Trash is separate','In Workspaces → More…, use the trash button beside a workspace to move the whole workspace to Workspace Trash after a warning. Workspace Trash lets you restore it or permanently delete it after another confirmation. Lock encrypted workspaces first; they stay encrypted in Trash.')

heading('Find text and work with two notes')
feature('Find inside the active note','Click the headerbar search icon or press Ctrl+F. Matches are highlighted. Enter and Shift+Enter, the arrows, or Ctrl+G and Ctrl+Shift+G move between results. Click the icon again or press Escape to close the bar. Ctrl+F focuses an already open search.')
feature('Find and replace','Press Ctrl+H or choose Find and replace in the document menu. Choose Replace or Replace all, with optional Case sensitive and Whole words matching. Editing must be enabled to change text. Ctrl+Z undoes the replacement.')
feature('Document outline','Use the outline icon, the document menu or Ctrl+Shift+L. Click a Title or Heading 1–3 entry to jump to it. This guide’s section headings are examples you can try.')
feature('Open beside','Right-click a sidebar note → Open beside current document…, or use the document menu or an internal link’s Open Beside choice. Drag the centre divider to change the balance. Twinly keeps two document panes in the same window.')
feature('Choose the active document','Move the pointer over a document, click in it or press F6 to switch panes. Both titles stay visible, and the active title has a blue underline. The shared toolbar, navigation, search and zoom controls follow that pane. Moving the pointer does not change reading mode into editing mode.')
feature('Pin, swap and close','Use the title’s context menu or the document menu to Pin as reference, Swap panes or Close pane. A pinned document is protected from being replaced when another note is opened from the sidebar. The small close button beside a title closes that pane. Ctrl+W closes the active pane, or the window when only one remains. The window close button or Ctrl+Q quits Twinly, with save checks and encrypted-workspace locking.')
feature('Back and forward','Use the header arrows or Alt+Left and Alt+Right to revisit navigation in the active pane. This history is separate from undo and redo.')

heading('Photos, rules and links')
feature('Insert a photo','While editing, place the cursor and use the photo icon or Insert photo… in the document menu. Choose a PNG or JPEG. The image is embedded in the note, so you do not need to keep its source file beside it.')
feature('Resize or remove','Click an inserted photo to select it. Drag a corner to resize proportionally, or enter its width in the floating photo controls. Those controls also remove it. Adjacent photos share a row when they fit; a line break separates them.')
feature('Horizontal rules','Use the horizontal-line icon in the formatting toolbar to insert a separator at the cursor.')
paragraph('Sample photo: enable editing with the pencil, then select this image and try a corner handle.')
photo_offset=paragraph('\ufffc')
doc['images'].append({'offset':photo_offset,'src':image_data(root/'data'/'getting-started-photo.png'),
                      'width':660,'height':440,'alt':'Morning light on a writing desk with a notebook, pen, coffee and a plant. AI-generated sample photo.'})
feature('Link to another note','Select the link text and press Ctrl+K or use the link icon. Choose a document in the current workspace. Internal links are purple and underlined. Clicking one offers Open Here or Open Beside; an already open note receives focus instead of opening twice.')
feature('Link to a website','Use the same dialog to enter an HTTP or HTTPS address. External links are blue and underlined. Ctrl+click opens one in your browser; link actions are also available in its context menu. Visiting a website uses your internet connection.')
paragraph('Try this internal link: Open the link example.')
start=doc['text'].rindex('Open the link example.')
doc['spans'].append({'start':start,'end':start+len('Open the link example.'),
                     'style':{'link':{'kind':'document','href':'Link%20Example.html'}}})

heading('Import, print and export')
feature('Import HTML, ODT or Word','Use Open… for an HTML note or Import… for ODT and DOCX. Twinly creates a managed HTML copy and leaves the original untouched. In a standard workspace, choose the converted copy’s filename when asked. Supported formatting, lists, links and embedded photos are retained; complex layouts, tables and other unsupported content may be simplified. Macros and remote images are not loaded. Old .doc files and password-protected Office files are not supported.')
feature('Import PDF text','Choose a PDF through Import… and confirm the conversion notice. Selectable text becomes an editable note. Photos, fonts, links and page layout are not preserved. Scanned pages need OCR, which Twinly does not provide; pages without text in a mixed PDF are reported as skipped. Password-protected PDFs are not supported. PDF text can also be imported directly into an encrypted workspace.')
feature('Print preview and margins','Press Ctrl+P or choose Print preview… in the document menu. Choose A4, A5 or Letter, portrait or landscape, and the margins. The editor adapts to the window width; printing wraps text to the chosen paper width, so line breaks can differ.')
feature('Export a copy','In a standard workspace, open the document menu → Export as…, directly below Save as…. Choose HTML copy, PDF, OpenDocument (.odt) or Word (.docx). PDF opens print preview with Save PDF…. Encrypted workspaces offer export commands in their document menu. Exports leave the active note unchanged; other applications may display fonts and formatting differently.')
feature('Print on paper','Use Print… in preview or the document menu, or press Ctrl+Shift+P. Available printers depend on your Linux printing setup.')

heading('Writing in an encrypted workspace')
feature('Password and recovery key','Create an encrypted workspace from Workspaces → More…. Use a password of at least 12 characters and save the recovery key separately. Confirm that you have stored the key before opening the new workspace. Losing both password and recovery key means losing access to its data.')
feature('What stays encrypted','Notes, folder names, embedded photos, custom styles, recovery drafts, session state and document Trash are encrypted at rest. Both document panes work there. Imports of HTML, ODT, DOCX and selectable PDF text create encrypted notes directly; their original files remain outside the workspace.')
feature('Locking','Use the header lock icon, the encrypted workspace menu’s lock command, switch workspaces or close Twinly. Inactivity locks the workspace after five minutes by default. Auto-lock in its sidebar menu offers 1, 5, 15 or 30 minutes. Change password keeps the existing recovery key valid.')
feature('Copies outside the workspace','Printing and exporting require confirmation because their output is unencrypted. Clipboard history, imported originals and an unlocked app also need care. Back up the complete encrypted workspace while it is locked, and keep its recovery key separate from that backup.')

heading('Make Twinly comfortable')
feature('Appearance','Open the sidebar menu → Preferences…. The four circular previews choose System, Light, Dark or Dark + Light. Dark + Light keeps the surrounding interface dark and the document light. Search within the document follows the writing area’s colour. Your appearance choice applies to both panes and does not change exported colours.')
feature('Blur','If supported by your GTK/Wayland setup and compositor, enable Blur in Preferences and adjust its strength and background opacity. It affects surrounding surfaces such as the sidebar, right-hand panels, menus and floating toolbar; the writing surface stays opaque.')
feature('Zoom','Use the percentage pill at the bottom-right, Ctrl+Minus, Ctrl+Plus or Ctrl+Equal, and Ctrl+0 for 100%. Each document remembers its zoom. Zoom does not change its saved font size.')
feature('Shortcuts and About','Ctrl+? opens the keyboard-shortcut reference. Standard Ctrl+C, Ctrl+X, Ctrl+V and Ctrl+A copy, cut, paste and select all. The standard workspace’s sidebar menu also contains Keyboard shortcuts and About Twinly, with Paullinux attribution, the GPL-3.0-or-later licence and project links.')

heading('Keep your work safe')
paragraph('Standard workspaces store ordinary editable HTML notes with embedded photos and relative links. Keep their folder collections together when backing up. Encrypted workspaces store encrypted data; export an HTML copy only when you want an unencrypted portable note. Fonts are bundled inside Twinly, but exported HTML does not embed them for other applications.')
paragraph('For large notes, text supports up to 4 MiB UTF-8, 20,000 paragraph breaks and 16,384 characters per paragraph. Split long unbroken text into shorter paragraphs. Image and formatting limits also apply. Oversized imports and pastes are rejected rather than shortened.')
paragraph('Workspace search is designed for large collections, but only 2,000 folders are monitored for automatic filesystem updates. Encrypted workspaces support up to 10,000 items, including folders and trashed items. Keep your own regular backups: automatic saving, recovery and Trash serve different purposes and cannot protect against every disk failure or accidental change.')

(root/'data'/'getting-started.html').write_text(to_html(doc,'Getting Started — Twinly'),encoding='utf-8')
example=blank()
example['text']='Link Example\nYou opened a linked note. Try opening this page beside Getting Started, then press F6 to switch panes.\nBack to Getting Started.'
example['spans']=[{'start':0,'end':12,'style':{'paragraph':'title'}}]
start=example['text'].index('Back to Getting Started.')
example['spans'].append({'start':start,'end':len(example['text']),
                         'style':{'link':{'kind':'document','href':'Getting%20Started.html'}}})
(root/'data'/'link-example.html').write_text(to_html(example,'Link Example'),encoding='utf-8')
