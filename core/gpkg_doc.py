"""
gpkg_doc (GROOTS-aanvulling op b4udignl)

Herstelt een KLIC-bericht uit een GeoPackage die met 'Opslaan als
GeoPackage' is gemaakt, zonder de XML van de levering opnieuw in te lezen.
GpkgDoc gedraagt zich voor het venster als een gewone Doc: lagen, thema's,
bijlagen, ga naar en sluiten werken hetzelfde.
"""
from __future__ import absolute_import

import os

from qgis.core import QgsVectorLayer, QgsWkbTypes

from .wv import Doc
from .wv_objects import Company, Layer, PdfFile, Person, Theme
from . import gpkg_export

try:
    from qgis.core import Qgis
    _GEOM_TYPES = {Qgis.GeometryType.Point: 'POINT',
                   Qgis.GeometryType.Line: 'MULTILINESTRING',
                   Qgis.GeometryType.Polygon: 'MULTIPOLYGON'}
except AttributeError:
    _GEOM_TYPES = {QgsWkbTypes.PointGeometry: 'POINT',
                   QgsWkbTypes.LineGeometry: 'MULTILINESTRING',
                   QgsWkbTypes.PolygonGeometry: 'MULTIPOLYGON'}


class _GpkgStorage(object):
    """Minimale vervanger van wv_storage voor een bericht uit GeoPackage."""

    def __init__(self):
        self.klicnummer = None
        self.meldingsoort = None
        self.rectangle = None
        self.graafpolygoon = None
        self.netOwners = []
        self.pdfFiles = []
        self.layers = {}


def is_klic_gpkg(gpkg_path):
    """True als het bestand een door de plugin gemaakte KLIC-GeoPackage is."""
    layer = _table(gpkg_path, gpkg_export.TABEL_METADATA)
    return layer is not None


def _table(gpkg_path, table):
    uri = "%s|layername=%s" % (gpkg_path, table)
    layer = QgsVectorLayer(uri, table, "ogr")
    return layer if layer.isValid() else None


def _rows(gpkg_path, table):
    layer = _table(gpkg_path, table)
    if layer is None:
        return []
    names = [field.name() for field in layer.fields()]
    rows = []
    for feature in layer.getFeatures():
        rows.append(dict(zip(names, feature.attributes())))
    return rows


def _text(value):
    if value is None or str(value) == 'NULL':
        return None
    return str(value)


def _theme_name(value):
    """Zelfde normalisatie als Theme.name: alleen letters, kleine letters."""
    return ''.join(c for c in value if c.isalpha()).lower()


class GpkgDoc(Doc):

    def __init__(self, gpkg_path):
        """Bouw een bericht op uit een KLIC-GeoPackage. Raises IOError."""
        # Doc.__init__ leest XML; hier vullen we dezelfde attributen zelf.
        gpkg_path = os.path.abspath(gpkg_path)
        meta = dict((_text(r.get('sleutel')), _text(r.get('waarde')))
                    for r in _rows(gpkg_path, gpkg_export.TABEL_METADATA))
        if not meta:
            raise IOError("Geen KLIC-GeoPackage (tabel %s ontbreekt): %s"
                          % (gpkg_export.TABEL_METADATA, gpkg_path))
        self._tag2function = {}
        self._Doc__path = os.path.realpath(meta.get('bron_map') or
                                           os.path.dirname(gpkg_path))
        self._Doc__iface = None
        self._init_imkls()
        self._Doc__version = meta.get('versie') or '2.0'
        self.schemaLocation = None
        self.layerGroups = {}
        self._Doc__themes = {}
        self._Doc__showVector = True
        self._Doc__showRaster = True
        self.gpkgPath = gpkg_path
        self.storage = _GpkgStorage()
        self.storage.klicnummer = meta.get('klicnummer') or \
            os.path.splitext(os.path.basename(gpkg_path))[0]
        self.storage.meldingsoort = meta.get('meldingsoort')
        self.aanvraagInfo = dict((k[len("aanvraag_"):], v)
                                 for k, v in meta.items()
                                 if k and k.startswith("aanvraag_"))
        self._load_layer_definitions(gpkg_path)
        self._load_attachments(gpkg_path)
        self._load_netbeheerders(gpkg_path)
        self._build_themes()

    def _load_netbeheerders(self, gpkg_path):
        """GROOTS: contactgegevens netbeheerders terugzetten"""
        companies = {}
        for row in _rows(gpkg_path, gpkg_export.TABEL_NETBEHEERDERS):
            code = _text(row.get('bronhoudercode')) or ''
            company = companies.get(code)
            if company is None:
                company = Company(_text(row.get('netbeheerder')))
                company.bronhoudercode = code
                for naam in (_text(row.get('themas')) or '').split(','):
                    if naam.strip():
                        company.themes.append(Theme(self, naam.strip()))
                companies[code] = company
                self.storage.netOwners.append(company)
            soort = _text(row.get('soort_contact'))
            if not soort:
                continue
            person = Person(_text(row.get('naam')))
            person.telephone = _text(row.get('telefoon'))
            person.email = _text(row.get('email'))
            if soort == 'beschadiging':
                company.damageContact = person
                company.telNrDamage = person.telephone
            elif soort == 'netinformatie':
                company.netInfoContact = person
                company.telNrProblemIT = person.telephone
            elif soort == 'aanvraag':
                company.contactPerson = person

    def _load_layer_definitions(self, gpkg_path):
        rows = _rows(gpkg_path, gpkg_export.TABEL_LAGEN)
        rows.sort(key=lambda r: int(_text(r.get('volgorde')) or 0))
        for row in rows:
            table = _text(row.get('tabel'))
            name = _text(row.get('laagnaam')) or table
            uri = "%s|layername=%s" % (gpkg_path, table)
            q_layer = QgsVectorLayer(uri, name, "ogr")
            if not q_layer.isValid():
                continue
            layer = Layer(self)
            layer.layerName = name
            layer.vectorType = _GEOM_TYPES.get(q_layer.geometryType(),
                                               'POINT')
            layer.layer = q_layer
            index = q_layer.fields().indexOf('thema')
            if index >= 0:
                for value in q_layer.uniqueValues(index):
                    value = _text(value)
                    if value:
                        layer.addVisibility(_theme_name(value))
            self.storage.layers[name] = layer
        if not self.storage.layers:
            raise IOError("Geen lagen gevonden in %s" % gpkg_path)

    def _load_attachments(self, gpkg_path):
        gpkg_dir = os.path.dirname(gpkg_path)
        for row in _rows(gpkg_path, gpkg_export.TABEL_BIJLAGEN):
            pdf = PdfFile(_text(row.get('naam')))
            pdf.type = _text(row.get('soort')) or 'bijlage'
            relative = _text(row.get('pad_relatief'))
            absolute = _text(row.get('pad_absoluut'))
            path = absolute
            if relative:
                candidate = os.path.normpath(os.path.join(gpkg_dir, relative))
                if os.path.exists(candidate) or not absolute:
                    path = candidate
            pdf.filePath = path
            self.storage.pdfFiles.append(pdf)
        self.storage.pdfFiles.sort()

    def _build_themes(self):
        themes = self.themes
        for layer in self.storage.layers.values():
            for theme_name in list(layer.themes_visible.keys()):
                if theme_name not in themes:
                    themes[theme_name] = Theme(self, theme_name)
                themes[theme_name].layers.append(layer)
        # maatvoering, annotatie, ligging en topo
        self._setLayerGroupThemes()
