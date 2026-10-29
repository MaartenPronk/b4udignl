"""
/***************************************************************************
ifaceqgis
helper class to implement actions between classes of wv and QGIS
                             -------------------
begin                : 2010-05-18
copyright            : (C) 2010 by Diethard Jansen
email                : diethard.jansen at gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from builtins import str
from builtins import object
from qgis.PyQt.QtCore import Qt 
from qgis.PyQt.QtGui import QAction

from qgis.core import QgsProject, QgsRuleBasedRenderer, QgsSingleSymbolRenderer
from qgis import core
import os
import re

try:
    _UNIT_MM = core.Qgis.RenderUnit.Millimeters
except AttributeError:
    _UNIT_MM = core.QgsUnitTypes.RenderMillimeters

try:
    # QGIS >= 3.30 en QGIS 4
    _GEOM_LINE = core.Qgis.GeometryType.Line
    _GEOM_POLYGON = core.Qgis.GeometryType.Polygon
except AttributeError:
    _GEOM_LINE = core.QgsWkbTypes.LineGeometry
    _GEOM_POLYGON = core.QgsWkbTypes.PolygonGeometry

# GROOTS: themakleuren KLIC (gelijk aan EisVoorzorgsmaatregel.qml), gebruikt
# voor afgeleide lagen zoals 'Maatvoering (lijn)' waarvoor geen QML bestaat.
THEMA_KLEUREN = (('buisleidingGevaarlijkeInhoud', '#ff7f00'),
                 ('datatransport', '#00ff00'),
                 ('gasHogeDruk', '#ffaf3c'),
                 ('gasLageDruk', '#ffd750'),
                 ('landelijkHoogspanningsnet', '#ff0000'),
                 ('hoogspanning', '#ff0000'),
                 ('middenspanning', '#c80000'),
                 ('laagspanning', '#960000'),
                 ('petrochemie', '#b64a00'),
                 ('rioolVrijverval', '#ba38a8'),
                 ('rioolOnderOverOfOnderdruk', '#800080'),
                 ('warmte', '#008080'),
                 ('water', '#0000ff'),
                 ('wees', '#918a6f'),
                 ('overig', '#6f5c10'),
                 ('Topo', '#808080'),
                 ('topo', '#808080'))

# vaste kleur en lijndikte (mm) per basislaag; None = themakleur
AFGELEIDE_STIJL = {'Maatvoering': ('#000000', 0.13),
                   'Annotatie': ('#000000', 0.13),
                   'EigenTopografie': ('#666666', 0.28)}
AFGELEIDE_STIJL_STANDAARD = (None, 0.28)

# herkent "thema" = 'x' en "thema" IN ('x','y') in filterexpressies
_THEMA_RE = re.compile(r'"thema"\s*(?:=\s*\'([^\']*)\'|IN\s*\(([^)]*)\))',
                       re.IGNORECASE)


def _rule_themes(expression):
    """Geeft de thema's (kleine letters) waarop een regel filtert."""
    themes = set()
    for match in _THEMA_RE.finditer(expression or ''):
        if match.group(1) is not None:
            themes.add(match.group(1).strip().lower())
        else:
            for item in match.group(2).split(','):
                themes.add(item.strip().strip("'").strip().lower())
    return themes

class Iface(object):
    def __init__(self, iface):
        self.__iface = iface
        self.__path = os.path.dirname(os.path.realpath(__file__))
        # GROOTS: lagengroep waarin nieuwe lagen van dit bericht komen
        self.groupName = None

    def _iface(self):
        """return private attribute iface"""
        return self.__iface

    iface = property(fget=_iface)

    def _path(self):
        return self.__path

    path = property(fget=_path)

    def visibleLayers(self):
        """return list of current visible layer Ids"""
        mapCanvas = self.iface.mapCanvas()
        mapSettings = mapCanvas.Settings()
        layerIds = mapSettings.layers()
        return layerIds

    def doRendering(self, p_render=True):
        """
        p_render = boolean
        True do render, False = stop rendering to improve performance
        """
        mapCanvas = self.iface.mapCanvas()
        mapCanvas.setRenderFlag(p_render)

    def refreshMap(self):
        """refreshes map (render map)"""
        mapCanvas = self.iface.mapCanvas()
        mapCanvas.refreshAllLayers()

    def refreshLegend(self):
        """refreshes legend"""
        layerTreeModel = self.iface.layerTreeView().layerTreeModel()
        layerTreeModel.layerFlagsChanged()

    def loadedLayers(self):
        """return dictionary where key is layer id and element is layer"""
        #dicLayers --> key = LayerId, Value = Layer
        project = QgsProject.instance()
        dictLayers = project.mapLayers()
        return dictLayers

    def loadLayer(self, wvLayer):
        """
        load given layer, create a new layer when it does not exist
        add new features to it, return layer and new mapfeatures
        """
        layer = None
        features = []
        layer = self.layerByName(wvLayer.layerName)
        if layer is None:
            layer = self.addLayer(wvLayer)
        if layer is not None:
            features = self.addFeatures(wvLayer)
        return layer, features

    def layerByName(self, a_name):
        """return layer by name"""
        layer = None
        project = QgsProject.instance()
        layers = project.mapLayersByName(a_name)
        # GROOTS: alleen eigen tijdelijke lagen (of PNG-rasters) hergebruiken.
        # Een GeoPackage- of andere laag met dezelfde naam mag nooit gevuld
        # worden met objecten van een nieuwe levering.
        layers = [l for l in layers
                  if l.providerType() in ('memory', 'gdal')]
        if len(layers) == 1:
            layer = layers[0]
        return layer

    def isInProject(self, layer):
        """GROOTS: staat deze laag (nog) in het project?"""
        if layer is None:
            return False
        try:
            layer_id = layer.id()
        except RuntimeError:
            # onderliggend C++-object is al verwijderd
            return False
        return core.QgsProject.instance().mapLayer(layer_id) is not None

    def addLayer(self, wvLayer):
        """add layer to map and return the layer"""
        project = core.QgsProject.instance()
        if wvLayer.is_vector():
            a_layer = wvLayer.layer
            if a_layer.providerType() == 'memory':
                provider = a_layer.dataProvider()
                provider.addAttributes(wvLayer.fields)
                a_layer.updateFields()
                self.styleLayer(a_layer)
            # GeoPackage-lagen houden hun opgeslagen stijl
        else:
            layerFile = wvLayer.layerFile
            name = os.path.splitext(os.path.basename(layerFile))[0]
            a_layer = core.QgsRasterLayer(layerFile, name)
            if not a_layer.isValid():
                return None
        layer = project.addMapLayer(a_layer, False)
        if layer is None:
            return None
        self._group().insertLayer(0, layer)
        return layer

    def _group(self):
        """GROOTS: groep van het bericht (wordt bovenaan aangemaakt)"""
        root = core.QgsProject.instance().layerTreeRoot()
        if not self.groupName:
            return root
        group = root.findGroup(self.groupName)
        if group is None:
            group = root.insertGroup(0, self.groupName)
        return group

    def removeGroup(self, group_name):
        """GROOTS: verwijder de groep van een bericht als die leeg is"""
        root = core.QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if group is not None and len(group.children()) == 0:
            root.removeChildNode(group)

    def addFeatures(self, wvLayer):
        """add features to given layer"""
        features = []
        if wvLayer.is_vector() and wvLayer.features:
            a_layer = wvLayer.layer
            provider = a_layer.dataProvider()
            isAdded, features = provider.addFeatures(wvLayer.features)
            a_layer.updateExtents()
            # GROOTS: stijl opnieuw toepassen en alleen regels houden voor
            # thema's die in de laag voorkomen (ook na een tweede levering)
            self.styleLayer(a_layer)
            self.pruneThemeRules(a_layer)
        return features

    def pruneThemeRules(self, a_layer):
        """Verwijder regels uit een regelgebaseerde stijl voor thema's die
        niet in de laag voorkomen. Zo toont de legenda van bijv.
        Rioolleiding alleen de riool-thema's."""
        renderer = a_layer.renderer()
        if not isinstance(renderer, core.QgsRuleBasedRenderer):
            return
        index = a_layer.fields().indexOf('thema')
        if index < 0:
            return
        present = set()
        for value in a_layer.uniqueValues(index):
            if value is not None and str(value) != 'NULL':
                present.add(str(value).lower())
        self._pruneRule(renderer.rootRule(), present)
        a_layer.triggerRepaint()
        try:
            self.iface.layerTreeView().refreshLayerSymbology(a_layer.id())
        except AttributeError:
            pass

    def _pruneRule(self, rule, present):
        for child in list(rule.children()):
            themes = _rule_themes(child.filterExpression())
            if themes and not child.isElse() and not (themes & present):
                rule.removeChild(child)
            else:
                self._pruneRule(child, present)

    def styleLayer(self, a_layer):
        """
        Using the layersname try to style the layer
        an existing QGIS style file included with plugin
        """
        qml_path = os.path.join(self.path, 'styles', 'qml')
        qml_file = os.path.join(qml_path, a_layer.name()) + '.qml'
        name = a_layer.name()
        if os.path.exists(qml_file):
            a_layer.loadNamedStyle(qml_file)
        elif name.endswith(')') and ' (' in name:
            self._styleDerivedLayer(a_layer, name.split(' (')[0])
        # GROOTS: aanvullingen op de stijl op basis van IMKL-kenmerken
        self._addFictiefMarkers(a_layer)
        self._setLabelPositie(a_layer)

    def _addFictiefMarkers(self, a_layer):
        """PMKL: op fictief (schematisch) ingetekende leidingen een 'V' om de
        25 px (hier 7 mm), alleen voor objecten met fictief = 'true'."""
        if a_layer.geometryType() != _GEOM_LINE:
            return
        if a_layer.fields().indexOf('fictief') < 0:
            return
        renderer = a_layer.renderer()
        if renderer is None:
            return
        symbols = []
        if isinstance(renderer, core.QgsRuleBasedRenderer):
            def walk(rule):
                for child in rule.children():
                    if child.symbol() is not None:
                        symbols.append(child.symbol())
                    walk(child)
            walk(renderer.rootRule())
        else:
            symbols = renderer.symbols(core.QgsRenderContext())
        enabled = core.QgsProperty.fromExpression(
            "coalesce(attribute(@feature, 'fictief'), '') = 'true'")
        prop = getattr(getattr(core.QgsSymbolLayer, 'Property', None),
                       'LayerEnabled', None)
        if prop is None:
            prop = core.QgsSymbolLayer.PropertyLayerEnabled
        for symbol in symbols:
            color = symbol.color()
            font = core.QgsFontMarkerSymbolLayer('Arial', 'V', 3.0, color)
            font.setSizeUnit(_UNIT_MM)
            font.setStrokeWidth(0)
            marker = core.QgsMarkerSymbol()
            marker.changeSymbolLayer(0, font)
            line = core.QgsMarkerLineSymbolLayer(True, 7.0)
            line.setIntervalUnit(_UNIT_MM)
            # ook een V in het midden, zodat korte lijnen er een krijgen
            try:
                placements = core.Qgis.MarkerLinePlacements(
                    core.Qgis.MarkerLinePlacement.Interval |
                    core.Qgis.MarkerLinePlacement.CentralPoint)
                line.setPlacements(placements)
            except (AttributeError, TypeError):
                pass
            line.setSubSymbol(marker)
            line.setDataDefinedProperty(prop, enabled)
            symbol.appendSymbolLayer(line)

    def _setLabelPositie(self, a_layer):
        """Labels van annotatie en maatvoering plaatsen volgens de IMKL-
        labelpositie (aangrijpingspunt horizontaal/verticaal 0, 0.5, 1)."""
        fields = a_layer.fields()
        if fields.indexOf('labelHorizontaal') < 0 or \
                a_layer.geometryType() == _GEOM_LINE or \
                not a_layer.labelsEnabled() or a_layer.labeling() is None:
            return
        labeling = a_layer.labeling()
        if not hasattr(labeling, 'settings'):
            return
        settings = core.QgsPalLayerSettings(labeling.settings())
        # aangrijpingspunt links (0) = tekst rechts van het punt, onder (0) =
        # tekst boven het punt; QGIS-kwadrant = rij * 3 + kolom
        expression = (
            "(CASE WHEN \"labelVerticaal\" = '0' THEN 0 "
            "WHEN \"labelVerticaal\" = '1' THEN 2 ELSE 1 END) * 3 + "
            "(CASE WHEN \"labelHorizontaal\" = '0' THEN 2 "
            "WHEN \"labelHorizontaal\" = '1' THEN 0 ELSE 1 END)")
        quad = getattr(getattr(core.QgsPalLayerSettings, 'Property', None),
                       'OffsetQuad', None)
        if quad is None:
            quad = core.QgsPalLayerSettings.OffsetQuad
        settings.dataDefinedProperties().setProperty(
            quad, core.QgsProperty.fromExpression(expression))
        over_point = getattr(getattr(core.Qgis, 'LabelPlacement', None),
                             'OverPoint', None)
        settings.placement = over_point if over_point is not None \
            else core.QgsPalLayerSettings.OverPoint
        a_layer.setLabeling(core.QgsVectorLayerSimpleLabeling(settings))

    def _styleDerivedLayer(self, a_layer, base_name):
        """Stijl voor afgeleide laag (bijv. 'Maatvoering (lijn)'): een regel
        per thema, zodat aan/uitzetten per thema blijft werken. Maten in mm."""
        fixed_color, width = AFGELEIDE_STIJL.get(base_name,
                                                 AFGELEIDE_STIJL_STANDAARD)
        geom_type = a_layer.geometryType()
        root = core.QgsRuleBasedRenderer.Rule(None)
        for thema, kleur in THEMA_KLEUREN:
            symbol = self._derivedSymbol(geom_type, fixed_color or kleur, width)
            rule = core.QgsRuleBasedRenderer.Rule(
                symbol, filterExp="\"thema\" = '%s'" % thema, label=thema)
            root.appendChild(rule)
        symbol = self._derivedSymbol(geom_type, fixed_color or '#000000', width)
        else_rule = core.QgsRuleBasedRenderer.Rule(symbol, label='overig thema')
        else_rule.setIsElse(True)
        root.appendChild(else_rule)
        a_layer.setRenderer(core.QgsRuleBasedRenderer(root))

    def _derivedSymbol(self, geom_type, kleur, width):
        if geom_type == _GEOM_LINE:
            return core.QgsLineSymbol.createSimple(
                {'line_color': kleur, 'line_width': str(width),
                 'line_width_unit': 'MM', 'capstyle': 'round'})
        if geom_type == _GEOM_POLYGON:
            return core.QgsFillSymbol.createSimple(
                {'style': 'no', 'outline_color': kleur,
                 'outline_width': str(width), 'outline_width_unit': 'MM'})
        return core.QgsMarkerSymbol.createSimple(
            {'name': 'circle', 'color': kleur, 'size': '1',
             'size_unit': 'MM', 'outline_style': 'no'})

    def setVisibilityForLayer(self, wvLayer, visibility,
                              show_raster, show_vector, theme = None):
        """change the visibility for one layer"""
        layer = wvLayer.layer
        if not self.isInProject(layer):
            return
        if wvLayer.is_vector():
            if show_vector and theme is not None:
                renderer = layer.renderer()
                if isinstance(renderer, QgsRuleBasedRenderer):
                    self._set_visibility_rules_symbol(layer, theme, visibility)
                elif isinstance(renderer, QgsSingleSymbolRenderer):
                    self.setLayerVisible(layer, visibility)
        else:
            isVisible = self.isLayerVisible(layer)
            if show_raster and isVisible != visibility:
                # different so set visibility
                self.setLayerVisible(layer, visibility)

    def visibilityForLayer(self, wvLayer, theme = None):
        """returns boolean, true if layer is visible false if not"""
        visibility = None
        layer = wvLayer.layer
        if not self.isInProject(layer):
            return Qt.CheckState.Unchecked
        # check current visibility
        if wvLayer.is_vector() and theme is not None:
            visibility = self._visibility_for_layer_theme(layer, theme)
        else:
            visibility = self.isLayerVisible(layer)
        return visibility

    def isLayerVisible(self, layer):
        tree_layer = self._treeLayer(layer)
        if tree_layer is None:
            value = Qt.CheckState.Unchecked
        else:
            value = tree_layer.isVisible()
        return value

    def setLayerVisible(self, layer, visibility):
        tree_layer = self._treeLayer(layer)
        if tree_layer is None:
            return
        tree_layer.setItemVisibilityChecked(visibility)

    def _treeLayer(self, layer):
        if not self.isInProject(layer):
            return None
        root_group = self.iface.layerTreeView().layerTreeModel().rootGroup()
        return root_group.findLayer(layer.id())

    def _visibility_for_layer_theme(self, layer, theme):
        '''check visibility of all themes in layer.
        If all are visible: return 2
        If some are visible: return 1
        If none are visible: return 0
        '''
        renderer = layer.renderer()
        visibility = Qt.CheckState.Unchecked
        if isinstance(renderer, QgsRuleBasedRenderer):
            visibility = self._visibility_from_rules_symbol(layer, theme)
        elif isinstance(renderer, QgsSingleSymbolRenderer):
            visibility = self.isLayerVisible(layer)
        return visibility

    def _visibility_from_rules_symbol(self, layer, theme):
        state = Qt.CheckState.Unchecked
        renderer = layer.renderer()
        rules = renderer.rootRule().children()
        visibilities = []
        for rule in rules:
            expression = rule.filterExpression()
            expression = str(expression).lower()
            if theme in expression:
                visibilities.append(rule.active())

        if all(visibilities):
            state = Qt.CheckState.Checked
        elif any(visibilities):
            state = Qt.CheckState.PartiallyChecked
        else:
            state = Qt.CheckState.Unchecked
        return state

    def _set_visibility_rules_symbol(self, layer, theme, visibility):
        state = None
        if visibility == Qt.CheckState.Unchecked:
            state = False
        elif visibility == Qt.CheckState.PartiallyChecked:
            return
        elif visibility == Qt.CheckState.Checked:
            state = True
        renderer = layer.renderer()
        rules = renderer.rootRule().children()
        for rule in rules:
            expression = rule.filterExpression()
            expression = str(expression).lower()
            if theme in expression:
                if rule.active() != state:
                    rule.setActive(state)

    def gotoLayer(self, wvLayer):
        """ goto extent of given layer """
        # GROOTS: zelf naar de extent zoomen. iface.zoomToActiveLayer()
        # crashte QGIS direct na het sluiten en heropenen van een
        # GeoPackage-bericht (access violation).
        lyr = wvLayer.layer
        if not self.isInProject(lyr):
            return
        extent = lyr.extent()
        if extent.isNull() or extent.isEmpty():
            return
        canvas = self.iface.mapCanvas()
        transform = core.QgsCoordinateTransform(
            lyr.crs(), canvas.mapSettings().destinationCrs(),
            core.QgsProject.instance())
        try:
            extent = transform.transformBoundingBox(extent)
        except core.QgsCsException:
            return
        extent.scale(1.05)
        canvas.setExtent(extent)
        canvas.refresh()

    def removeLayer(self, wvLayer):
        """ remove layer from QGIS map registry"""
        lyr = wvLayer.layer
        if not self.isInProject(lyr):
            # al door de gebruiker verwijderd
            return
        # GROOTS: elk bericht heeft eigen lagen, dus de hele laag gaat uit
        # het project. Objecten in een GeoPackage worden nooit verwijderd.
        core.QgsProject.instance().removeMapLayer(lyr)

    def bestScale(self, wvLayer):
        """Set best scale for given layer"""
        lyr = wvLayer.layer
        self.iface.setActiveLayer(lyr)
        event = QAction.ActionEvent.Trigger
        action = self.iface.actionZoomActualSize()
        # triggers/invokes the action
        action.activate(event)

