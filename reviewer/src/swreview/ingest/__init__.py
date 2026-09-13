"""Ingest of exported design files into the evidence package IR.

`manifest.py` reads the provenance record, `bom.py` the parts list,
`dimension_grammar.py` the SOLIDWORKS dimension text grammar, `pdf_drawing.py` the
drawing PDFs, and `package_builder.py` assembles them into a `package.json`.

Nothing here guesses. A value the exported files do not state stays `None`, an unknown
unit stays `"unknown"`, an unparsed sheet or callout becomes a
`swreview.ir.models.Gap` (constitution Principle I).
"""
