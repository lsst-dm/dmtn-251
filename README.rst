.. image:: https://img.shields.io/badge/dmtn--251-lsst.io-brightgreen.svg
   :target: https://dmtn-251.lsst.io
.. image:: https://github.com/lsst-dm/dmtn-251/workflows/CI/badge.svg
   :target: https://github.com/lsst-dm/dmtn-251/actions/

##########################################
A New Approach to LSST's Image Data Models
##########################################

DMTN-251
========

The ``lsst.afw.image.Exposure`` class, its nested component classes, and the ``lsst.afw.table.io`` C++ persistence library that translates them to FITS are in need of replacement.  They make our on-disk file formats hard to document or read with external libraries, they're brittle and hard to maintain and evolve (largely because they force extensions to be written in C++).  They rely on ``cfitsio``, which cannot perform partial reads on object stores, which will be absolutely critical in our hybrid-model Data Facility architecture.  The types themselves suffer from numerous small problems that are hard to fix individually, such as the ``Mask`` plane dictionary singleton and the PSF "trampoline" system's reliance on poorly-supported ``pybind11`` functionality (leading in practice to a major memory leak).  This technote will describe an approach to replacing these types that initially focuses on the serialization system and on-disk data models, while setting the stage for eventual deprecation of the ``Exposure`` and related types in the future.

**Links:**

- Publication URL: https://dmtn-251.lsst.io
- Alternative editions: https://dmtn-251.lsst.io/v
- GitHub repository: https://github.com/lsst-dm/dmtn-251
- Build system: https://github.com/lsst-dm/dmtn-251/actions/


Build this technical note
=========================

You can clone this repository and build the technote locally if your system has Python 3.11 or later:

.. code-block:: bash

   git clone https://github.com/lsst-dm/dmtn-251
   cd dmtn-251
   make init
   make html

Repeat the ``make html`` command to rebuild the technote after making changes.
If you need to delete any intermediate files for a clean build, run ``make clean``.

The built technote is located at ``_build/html/index.html``.

Publishing changes to the web
=============================

This technote is published to https://dmtn-251.lsst.io whenever you push changes to the ``main`` branch on GitHub.
When you push changes to a another branch, a preview of the technote is published to https://dmtn-251.lsst.io/v.

Editing this technical note
===========================

The main content of this technote is in ``index.rst`` (a reStructuredText file).
Metadata and configuration is in the ``technote.toml`` file.
For guidance on creating content and information about specifying metadata and configuration, see the Documenteer documentation: https://documenteer.lsst.io/technotes.
