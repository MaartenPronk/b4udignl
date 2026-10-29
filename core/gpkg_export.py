"""
gpkg_export (GROOTS-aanvulling op b4udignl)

Schrijft de vectorlagen van een ingelezen KLIC-levering naar een GeoPackage.
Per laag wordt de actuele QGIS-stijl als standaardstijl in de GeoPackage
opgeslagen (tabel layer_styles), zodat de lagen ook zonder deze plugin met de
juiste symbolen openen.
"""
from __future__ import absolute_import

import os
import re

import datetime

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (QgsDataProvider, QgsFeature, QgsProject,
                       QgsVectorFileWriter, QgsVectorLayer)

STIJL_OMSCHRIJVING = "KLIC-stijl (b4udignl, GROOTS, PMKL in mm)"

# tabellen zonder geometrie waarmee de plugin een bericht herstelt
TABEL_METADATA = "klic_metadata"
TABEL_LAGEN = "klic_lagen"
TABEL_BIJLAGEN = "klic_bijlagen"
TABEL_NETBEHEERDERS = "klic_netbeheerders"

# QGIS 3 en 4: enums zijn in QGIS 4 alleen nog via hun scope bereikbaar
_ACTION = getattr(QgsVectorFileWriter, "ActionOnExistingFile",
                  QgsVectorFileWriter)
_WRITER_ERROR = getattr(QgsVectorFileWriter, "WriterError",
                        QgsVectorFileWriter)


def table_name(layer_name):
    """'Maatvoering (lijn)' -> 'Maatvoering_lijn'"""
    name = re.sub(r'\W+', '_', layer_name, flags=re.UNICODE).strip('_')
    return name or 'laag'


def default_path(doc):
    """Standaardlocatie: <klicnummer>.gpkg naast de map van de levering."""
    path = os.path.normpath(doc.path)
    name = doc.klicnummer or os.path.basename(path)
    return os.path.join(os.path.dirname(path), "%s.gpkg" % name)


def _vector_layers(doc):
    layers = doc.layersSorted() or []
    result = []
    for wv_layer in layers:
        if not wv_layer.is_vector():
            continue
        q_layer = wv_layer.layer
        if q_layer is None or not q_layer.isValid():
            continue
        result.append((wv_layer, q_layer))
    return result


def _write_layer(q_layer, gpkg_path, table, first):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = table
    options.fileEncoding = "UTF-8"
    if first and os.path.exists(gpkg_path):
        options.actionOnExistingFile = \
            _ACTION.CreateOrOverwriteFile
    elif os.path.exists(gpkg_path):
        options.actionOnExistingFile = \
            _ACTION.CreateOrOverwriteLayer
    context = QgsProject.instance().transformContext()
    result = QgsVectorFileWriter.writeAsVectorFormatV3(q_layer, gpkg_path,
                                                       context, options)
    error, message = result[0], result[1]
    if error != _WRITER_ERROR.NoError:
        raise IOError("Laag '%s' niet weggeschreven: %s"
                      % (q_layer.name(), message))


def _save_style(q_layer, gpkg_path, table):
    """Kopieer de stijl van q_layer als standaardstijl naar de GeoPackage."""
    uri = "%s|layername=%s" % (gpkg_path, table)
    gpkg_layer = QgsVectorLayer(uri, q_layer.name(), "ogr")
    if not gpkg_layer.isValid():
        raise IOError("Laag '%s' niet terug te lezen uit GeoPackage" % table)
    dom = QDomDocument()
    q_layer.exportNamedStyle(dom)
    gpkg_layer.importNamedStyle(dom)
    if hasattr(gpkg_layer, "saveStyleToDatabaseV2"):
        result = gpkg_layer.saveStyleToDatabaseV2(table, STIJL_OMSCHRIJVING,
                                                  True, "")
        error = result[1] if isinstance(result, tuple) else ""
    else:
        error = gpkg_layer.saveStyleToDatabase(table, STIJL_OMSCHRIJVING,
                                               True, "")
    if error:
        raise IOError("Stijl van '%s' niet opgeslagen: %s" % (table, error))
    return uri


def _source_file(q_layer):
    return os.path.normcase(os.path.abspath(
        q_layer.source().split("|")[0]))


def is_source_of(doc, gpkg_path):
    """True als lagen van doc al uit dit bestand komen."""
    target = os.path.normcase(os.path.abspath(gpkg_path))
    for __, q_layer in _vector_layers(doc):
        if q_layer.providerType() != "memory" and \
                _source_file(q_layer) == target:
            return True
    return False


def _write_table(gpkg_path, table, fields, rows):
    """Schrijf een tabel zonder geometrie (alle velden tekst)."""
    uri = "None?" + "&".join("field=%s:string" % f for f in fields)
    layer = QgsVectorLayer(uri, table, "memory")
    features = []
    for row in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes(["" if v is None else str(v) for v in row])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    _write_layer(layer, gpkg_path, table, first=False)


def _write_metadata(doc, gpkg_path, written):
    gpkg_dir = os.path.dirname(os.path.abspath(gpkg_path))
    meta = [("klicnummer", doc.klicnummer),
            ("meldingsoort", doc.meldingsoort),
            ("versie", doc.version),
            ("bron_map", doc.path),
            ("opgeslagen_op", datetime.datetime.now().isoformat(
                timespec="seconds")),
            ("opgeslagen_met", "b4udignl (GROOTS)")]
    # kenmerken van aanvraag en levering (GROOTS)
    for key, value in sorted((getattr(doc, "aanvraagInfo", None) or {}).items()):
        meta.append(("aanvraag_" + key, value))
    _write_table(gpkg_path, TABEL_METADATA, ["sleutel", "waarde"], meta)
    lagen = [(table, name, index, count)
             for index, (name, table, count) in enumerate(written)]
    _write_table(gpkg_path, TABEL_LAGEN,
                 ["tabel", "laagnaam", "volgorde", "aantal"], lagen)
    bijlagen = []
    for pdf in (doc.pdfFiles or []):
        path = pdf.filePath or ""
        try:
            relative = os.path.relpath(path, gpkg_dir) if path else ""
        except ValueError:
            # andere schijfletter
            relative = ""
        bijlagen.append((pdf.name, pdf.type, relative, path))
    _write_table(gpkg_path, TABEL_BIJLAGEN,
                 ["naam", "soort", "pad_relatief", "pad_absoluut"], bijlagen)
    _write_table(gpkg_path, TABEL_NETBEHEERDERS,
                 ["bronhoudercode", "netbeheerder", "themas", "soort_contact",
                  "naam", "telefoon", "email"], netbeheerder_rows(doc))


def netbeheerder_rows(doc):
    """Contactgegevens per netbeheerder; een rij per soort contact."""
    rows = []
    for company in (getattr(doc, "netOwners", None) or []):
        themas = ", ".join(t.name for t in company.themes if t.name)
        contacts = company.contactRows() if hasattr(company, "contactRows") \
            else []
        if not contacts:
            contacts = [("", None, None, None)]
        for soort, naam, telefoon, email in contacts:
            rows.append((company.bronhoudercode, company.name, themas, soort,
                         naam, telefoon, email))
    return rows


def export_doc(doc, gpkg_path, replace_sources=False, progress=None):
    """Schrijf alle vectorlagen van doc naar gpkg_path, met per laag de
    stijl als standaardstijl en de tabellen klic_metadata, klic_lagen en
    klic_bijlagen.

    replace_sources: laat de lagen in het project daarna naar de GeoPackage
    wijzen. De plugin blijft het bericht beheren (thema's, sluiten).
    progress: optionele functie(index, totaal, laagnaam).
    Geeft een lijst (laagnaam, tabelnaam, aantal objecten) terug.
    """
    if is_source_of(doc, gpkg_path):
        raise IOError("Dit bericht komt al uit %s. Kies een ander bestand."
                      % gpkg_path)
    layers = _vector_layers(doc)
    written = []
    sources = []
    used_tables = set()
    for index, (wv_layer, q_layer) in enumerate(layers):
        if progress is not None:
            progress(index, len(layers) + 1, q_layer.name())
        table = table_name(q_layer.name())
        while table.lower() in used_tables:
            table += "_"
        used_tables.add(table.lower())
        _write_layer(q_layer, gpkg_path, table, first=(index == 0))
        uri = _save_style(q_layer, gpkg_path, table)
        written.append((q_layer.name(), table, q_layer.featureCount()))
        sources.append((q_layer, uri))
    if progress is not None:
        progress(len(layers), len(layers) + 1, "kenmerken en bijlagen")
    _write_metadata(doc, gpkg_path, written)
    if replace_sources:
        for q_layer, uri in sources:
            q_layer.setDataSource(uri, q_layer.name(), "ogr",
                                  QgsDataProvider.ProviderOptions())
        doc.gpkgPath = gpkg_path
    if progress is not None:
        progress(len(layers) + 1, len(layers) + 1, "")
    return written
