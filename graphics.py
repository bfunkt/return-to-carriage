
import numpy as np
from PyQt4 import QtGui, QtCore
import vispy.visuals, vispy.scene, vispy.gloo


class SpritesVisual(vispy.visuals.Visual):
    vertex_shader = """
        #version 120

        uniform float size;

        attribute vec3 position;
        attribute vec4 fgcolor;
        attribute vec4 bgcolor;
        attribute float sprite;

        varying float v_sprite;
        varying vec4 v_fgcolor;
        varying vec4 v_bgcolor;

        void main (void) {
            v_fgcolor = fgcolor;
            v_bgcolor = bgcolor;
            v_sprite = sprite;

            gl_Position = $transform(vec4(position, 1));
            gl_PointSize = size * 1.01;  // extra 0.01 prevents gaps
        }
    """

    fragment_shader = """
        #version 120
        uniform float size;
        varying vec4 v_fgcolor;
        varying vec4 v_bgcolor;
        varying float v_sprite;
        
        uniform sampler2D atlas;
        uniform sampler1D atlas_map;
        uniform float n_sprites;
        uniform vec2 scale;
        
        void main()
        {
            gl_FragColor = vec4(0, 0, 0, 0);
            vec4 atlas_coords = texture1D(atlas_map, (v_sprite + 0.5) / n_sprites);
            vec2 pt = gl_PointCoord.xy / scale;
            if( pt.x < 0 || pt.y < 0 || pt.x > 1 || pt.y > 1 ) {
                discard;
            }
            
            // supersample sprite value
            const int ss = 2;
            float alpha = 0;
            for (int i=0; i<ss; i++) {
                for (int j=0; j<ss; j++) {
                    vec2 dx = vec2(i/(size*ss), j/(size*ss));
                    vec2 tex_coords = atlas_coords.yx + (pt + dx/scale) * atlas_coords.wz;
                    vec4 tex = texture2D(atlas, tex_coords);
                    alpha += tex.g / (ss*ss);
                }
            }
            
            gl_FragColor = v_fgcolor * alpha + v_bgcolor * (1-alpha);
        }
    """

    def __init__(self, atlas, size=16, scale=1):
        self.size = size
        self.scale = scale
        self.atlas = atlas
        self.atlas.atlas_changed.connect(self._atlas_changed)
        self.position = np.empty((0, 3), dtype='float32')
        self.sprite = np.empty((0,), dtype='uint32')
        self.fgcolor = np.empty((0, 4), dtype='float32')
        self.bgcolor = np.empty((0, 4), dtype='float32')
        
        self._atlas_tex = vispy.gloo.Texture2D(shape=(1,1,4), format='rgba', interpolation='nearest')
        self._atlas_map_tex = vispy.gloo.Texture1D(shape=(1,4), format='rgba', interpolation='nearest')
        self._need_data_upload = False
        self._need_atlas_upload = True
        
        vispy.visuals.Visual.__init__(self, self.vertex_shader, self.fragment_shader)
        self._draw_mode = 'points'
        self.shared_program['position'] = vispy.gloo.VertexBuffer()
        self.shared_program['sprite'] = vispy.gloo.VertexBuffer()
        self.shared_program['fgcolor'] = vispy.gloo.VertexBuffer()
        self.shared_program['bgcolor'] = vispy.gloo.VertexBuffer()
        
        self.update_gl_state(depth_test=True)
    
    def add_sprites(self, shape):
        """Expand to allow more sprites, return a SpriteData instance with the specified shape.
        """
        if not isinstance(shape, tuple):
            raise TypeError("shape must be a tuple")
        n = np.product(shape)
        i = self._resize(self.position.shape[0] + n)
        return SpriteData(self, i, shape)

    def _resize(self, n):
        """Resize sprite array, return old size.
        """
        n1 = self.position.shape[0]        
        self.position = np.resize(self.position, (n, 3))
        self.sprite = np.resize(self.sprite, (n,))
        self.fgcolor = np.resize(self.fgcolor, (n, 4))
        self.bgcolor = np.resize(self.bgcolor, (n, 4))        
        self._upload_data()
        return n1
    
    def _upload_data(self):
        self.shared_program['position'].set_data(self.position)
        self.shared_program['sprite'].set_data(self.sprite.astype('float32'))
        self.shared_program['fgcolor'].set_data(self.fgcolor)
        self.shared_program['bgcolor'].set_data(self.bgcolor)
        self.shared_program['size'] = self.size
        self.shared_program['scale'] = self.scale
        self._need_data_upload = False

    def _atlas_changed(self, ev):
        self._need_atlas_upload = True
        self.update()

    def _upload_atlas(self):
        self._atlas_tex.set_data(self.atlas.atlas)
        self.shared_program['atlas'] = self._atlas_tex
        self._atlas_map_tex.set_data(self.atlas.sprite_coords)
        self.shared_program['atlas_map'] = self._atlas_map_tex
        self.shared_program['n_sprites'] = self._atlas_map_tex.shape[0]
        self._need_atlas_upload = False
    
    def _prepare_transforms(self, view):
        xform = view.transforms.get_transform()
        view.view_program.vert['transform'] = xform
        
    def _prepare_draw(self, view):
        if self._need_data_upload:
            self._upload_data()
            
        if self._need_atlas_upload:
            self._upload_atlas()
        
        # set point size to match zoom
        tr = view.transforms.get_transform('visual', 'canvas')
        o = tr.map((0, 0))
        x = tr.map((self.size, 0))
        l = ((x-o)[:2]**2).sum()**0.5
        view.view_program['size'] = l

    def _compute_bounds(self, axis, view):
        p = self.position[:, axis]
        return p.min(), p.max()

        
Sprites = vispy.scene.visuals.create_visual_node(SpritesVisual)


class SpriteData(object):
    """For accessing a subset of sprites from a Sprites visual.
    
    This is intended to be created using SpritesVisual.add_sprites(...)
    """
    def __init__(self, sprites, start, shape):
        self.sprites = sprites
        n = np.product(shape)
        self.indices = (start, start+n)
        self.shape = shape
        
    @property
    def position(self):
        start, stop = self.indices
        return self.sprites.position[start:stop].reshape(self.shape + (3,))
    
    @position.setter
    def position(self, p):
        start, stop = self.indices
        self.position[:] = p
        self.sprites.shared_program['position'][start:stop] = self.position.view(dtype=[('position', 'float32', 3)]).reshape(stop-start)
        self.sprites.update()
        
    @property
    def sprite(self):
        start, stop = self.indices
        return self.sprites.sprite[start:stop].reshape(self.shape)
    
    @sprite.setter
    def sprite(self, p):
        start, stop = self.indices
        self.sprite[:] = p
        self.sprites.shared_program['sprite'][start:stop] = self.sprite.reshape(stop-start).astype('float32')
        self.sprites.update()

    @property
    def fgcolor(self):
        start, stop = self.indices
        return self.sprites.fgcolor[start:stop].reshape(self.shape + (4,))
    
    @fgcolor.setter
    def fgcolor(self, p):
        start, stop = self.indices
        self.fgcolor[:] = p
        self.sprites.shared_program['fgcolor'][start:stop] = self.fgcolor.view(dtype=[('fgcolor', 'float32', 4)]).reshape(stop-start)
        self.sprites.update()
        
    @property
    def bgcolor(self):
        start, stop = self.indices
        return self.sprites.bgcolor[start:stop].reshape(self.shape + (4,))
    
    @bgcolor.setter
    def bgcolor(self, p):
        start, stop = self.indices
        self.bgcolor[:] = p
        self.sprites.shared_program['bgcolor'][start:stop] = self.bgcolor.view(dtype=[('bgcolor', 'float32', 4)]).reshape(stop-start)
        self.sprites.update()
        


import pyqtgraph as pg


class CharAtlas(object):
    """Texture atlas containing rendered text characters.    
    """
    def __init__(self, size=128):
        self.atlas_changed = vispy.util.event.EventEmitter(type='atlas_changed')
        self.size = size
        self.font = QtGui.QFont('monospace', self.size)
        self.chars = {}
        self._fm = QtGui.QFontMetrics(self.font)
        char_shape = (int(self._fm.height()), int(self._fm.maxWidth()))
        self.glyphs = np.empty((0,) + char_shape + (3,), dtype='ubyte')
        self._rebuild_atlas()

    def add_chars(self, chars):
        """Add new characters to the atlas, return the first new index.
        """
        oldn = self.glyphs.shape[0]
        newglyphs = np.empty((oldn + len(chars),) + self.glyphs.shape[1:], dtype=self.glyphs.dtype)
        newglyphs[:oldn] = self.glyphs
        self.glyphs = newglyphs
        
        char_shape = self.glyphs.shape[1:3]
        
        for i,char in enumerate(chars):
            self.chars[char] = oldn + i
            
            img = QtGui.QImage(char_shape[1], char_shape[0], QtGui.QImage.Format_RGB32)
            p = QtGui.QPainter()
            p.begin(img)
            brush = QtGui.QBrush(QtGui.QColor(255, 0, 0))
            p.fillRect(0, 0, char_shape[1], char_shape[0], brush)
            pen = QtGui.QPen(QtGui.QColor(0, 255, 0))
            p.setPen(pen)
            p.setFont(self.font)
            p.drawText(0, self._fm.ascent(), char)
            p.end()
            self.glyphs[oldn+i] = pg.imageToArray(img)[..., :3].transpose(1, 0, 2)
        
        self._rebuild_atlas()
        self.atlas_changed()
        return oldn

    def _rebuild_atlas(self):
        gs = self.glyphs.shape
        self.atlas = self.glyphs.reshape((gs[0]*gs[1], gs[2], gs[3]))
        self.sprite_coords = np.empty((gs[0], 4), dtype='float32')
        self.sprite_coords[:,0] = np.arange(0, gs[0]*gs[1], gs[1])
        self.sprite_coords[:,1] = 0
        self.sprite_coords[:,2] = gs[1]
        self.sprite_coords[:,3] = gs[2]
        self.sprite_coords[:,::2] /= self.atlas.shape[0]
        self.sprite_coords[:,1::2] /= self.atlas.shape[1]

