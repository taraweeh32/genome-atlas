"""Dataset, file, upload, import and validation domain model.

Three concepts stay deliberately distinct throughout this package:

* a **dataset** is the mutable, named resource a user manages,
* a **dataset version** is an immutable scientific input,
* a **file artifact** is object-storage metadata for one stored object.

Nothing in this package performs scientific computation. It decides file-format
recognition, declared-metadata rules, structural/tabular integrity and mapping
validity — all of which are application concerns. Normalization, reference-genome
processing, annotation and any interpretation of allele content belong to the
scientific compute subsystem behind its own versioned contract.
"""
