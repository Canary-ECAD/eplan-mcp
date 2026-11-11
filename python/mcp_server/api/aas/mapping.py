"""
EPLAN <-> AAS mapping tables (pure data, no I/O).

Maps between the field names returned by the parts-DB tools in
``api/actions/scripted.py`` (``parts_db_get_part`` keys, raw ``ARTICLE_*``
property names for writes) and the submodel element idShorts / semantic IDs
of the IDTA submodel templates:

- Digital Nameplate  (IDTA 02006, ZVEI Nameplate 2/0)
- Technical Data     (IDTA 02003, ZVEI TechnicalData 1/2)
"""

# Semantic IDs of the submodel templates themselves
NAMEPLATE_SEMANTIC_ID = "https://admin-shell.io/zvei/nameplate/2/0/Nameplate"
TECHNICAL_DATA_SEMANTIC_ID = "https://admin-shell.io/ZVEI/TechnicalData/Submodel/1/2"
HANDOVER_DOC_SEMANTIC_ID = "0173-1#01-AHF578#001"  # IDTA 02004 VDI 2770

# Digital Nameplate: parts_db_get_part key -> (idShort, semantic IRDI)
PART_TO_NAMEPLATE = {
    "Manufacturer": ("ManufacturerName", "0173-1#02-AAO677#002"),
    "Description1": ("ManufacturerProductDesignation", "0173-1#02-AAW338#001"),
    "OrderNr": ("OrderCodeOfManufacturer", "0173-1#02-AAO227#002"),
    "PartNr": ("ProductArticleNumberOfManufacturer", "0173-1#02-AAO676#003"),
}

# Technical Data / GeneralInformation: parts_db_get_part key -> (idShort, semantic id)
PART_TO_TECHNICAL_DATA = {
    "Manufacturer": ("ManufacturerName", "0173-1#02-AAO677#002"),
    "PartNr": ("ManufacturerArticleNumber", "0173-1#02-AAO676#003"),
    "OrderNr": ("ManufacturerOrderCode", "0173-1#02-AAO227#002"),
    "Description1": ("ManufacturerProductDesignation", "0173-1#02-AAW338#001"),
    "ProductGroup": ("ProductClassificationProductGroup", None),
    "ProductSubGroup": ("ProductClassificationProductSubGroup", None),
    "ProductTopGroup": ("ProductClassificationProductTopGroup", None),
}

# Import direction: nameplate/technical-data idShort -> raw parts-DB
# property name usable with parts_db_update / parts_db_create.
IDSHORT_TO_PARTS_DB = {
    "ManufacturerName": "ARTICLE_MANUFACTURER",
    "ManufacturerProductDesignation": "ARTICLE_DESCR1",
    "OrderCodeOfManufacturer": "ARTICLE_ORDERNR",
    "ManufacturerOrderCode": "ARTICLE_ORDERNR",
    "ProductArticleNumberOfManufacturer": "ARTICLE_PARTNR",
    "ManufacturerArticleNumber": "ARTICLE_PARTNR",
}

# idShorts whose value identifies the part (checked in this order when
# deciding which parts-DB record an imported shell belongs to).
PART_NUMBER_IDSHORTS = (
    "ProductArticleNumberOfManufacturer",
    "ManufacturerArticleNumber",
    "OrderCodeOfManufacturer",
    "ManufacturerOrderCode",
)
