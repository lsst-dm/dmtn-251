.. default-domain:: python

##########################################
A New Approach to LSST's Image Data Models
##########################################

.. abstract::

   The ``lsst.afw.image.Exposure`` class, its nested component classes, and the ``lsst.afw.table.io`` C++ persistence library that translates them to FITS are in need of replacement.
   They make our on-disk file formats hard to document or read with external libraries, they're brittle and hard to maintain and evolve (largely because they force extensions to be written in C++).
   They rely on ``cfitsio``, which cannot perform partial reads on object stores, which will be absolutely critical in our hybrid-model Data Facility architecture.
   The types themselves suffer from numerous small problems that are hard to fix individually, such as the ``Mask`` plane dictionary singleton and the PSF "trampoline" system's reliance on poorly-supported ``pybind11`` functionality (leading in practice to a major memory leak).
   This technote will describe an approach to replacing these types that initially focuses on the serialization system and on-disk data models, while setting the stage for eventual deprecation of the ``Exposure`` and related types in the future.

Motivation
==========

The ``lsst.afw.image.Exposure`` class is currently used for almost all LSST image data products, from single-visit processed images to coadds to difference images.
In addition to the main ``image`` plane, it holds an integer ``mask`` plane of the same size (where each bit has a different interpretation) and a floating point ``variance`` plane that records the per-pixel uncertainty (assuming it is uncorrelated).
It also holds many non-image "components", such as the point-spread function model (PSF), world-coordinate system (WCS), photometric calibration, aperture corrections, and observational metadata like the exposure time and boresight pointing.

The ``image``, ``mask``, and ``variance`` planes map fairly naturally to FITS, but the same cannot be said of the component information (except for *some* - but not all - WCS types).
For these, we rely on the ``lsst.afw.table.io`` library, which provides a way for a class to convert to and from the rows of one or more FITS binary tables.
This works moderately well for a few objects, but the more common case is FITS file with a sequence of single-row table extensions with just a handful of columns each, and almost no information about how to assemble the values in those tables into a coherent whole.
This poor on-disk data model is the most pressing problem with the current system, since it is much harder to retire any format after it is first used in a data release or otherwise used to deliver real LSST data to science users.

As described in a `community.lsst.org blog post <https://community.lsst.org/t/how-the-exposure-class-and-afw-io-wrecked-the-codebase/3384>`__ a few years ago, a slower-moving but possibly bigger problem is the way this system has limited our ability to extend and improve ``Exposure``.
It's all written in C++, a language many of our developers are not fluent in, and it requires any new component types to be written in C++ as well.
And while we seemed to have found a way around that for a while, with a "trampoline" system for writing Python implementations of C++ base classes, that turns out to rely on a fundamentally broken approach to shared pointers in ``pybind11``, the library we use to provide Python bindings to our C++ classes. The result is a major memory leak that makes it very difficult to work with our data products in long-lived processes.
This system also effectively requires new component types (or at least a new abstract base class for them) to be defined in the ``lsst.afw`` package, leading that package to accumulate content that gets increasingly difficult to organize.

While it's difficult to extend ``Exposure``, it's even harder to put together an ``Exposure``-like class that's more tailored for a particular use case, and the result is that ``Exposure`` has enough components to serve any role, but so many components that many don't make sense in most roles.
Coadds do not have visit metadata, and single-visit processed images do not have coadd inputs, but ``Exposure`` always has both, and hence some have to be set to ``None`` / ``NULL`` - a practice now widely recognized as an antipattern in software engineering.
In particular, it's impossible to look at a function declaration that takes an ``Exposure`` and see what which components it actually needs, and all too easy to not document it at all.

Recently one more critical limitation has come to light: ``afw.table.io`` delegates to ``CFITSIO`` to actually read and write FITS files, but ``CFITSIO`` can only work with regular POSIX filesystems [#cfitsio-posix-caveat]_, and we plan to make our image data products available to users primarily over the S3 object store protocol.
This is fine as long as a full file is being read, because we can download it to temporary storage, but it's a disaster for reading tiny subimages of much larger files, which we expect to be extremely common.
Frequently the file will be stored at SLAC/USDF, but the reading code will be running in Google Cloud, and hence doing a full-file transfer for each subimage read is even more problematic.

.. [#cfitsio-posix-caveat] ``CFITSIO`` has very limited support for reading over HTML, but it's not sufficient to solve this problem.

Overview and Transition Plan
============================

The ``Exposure`` and ``afw.table.io`` systems are so intertwined that replacing only the problematic parts is effectively impossible, and the proposal described here is an *eventual* complete replacement.
It centers around a new, largely-complete library, ShoeFits, that will replace ``afw.table.io`` and make it much easier to define ``Exposure`` replacement types in pure Python.
The details of those replacement types is left unspecified for now, but we do expect more than one - most likely one for post-ISR exposures, another for processed visit images, one for coadds, and another for difference images.
These will ultimately depend on a completely new suite of component types.
A new pure-Python `lsst.image` package will be the home of these new types.

The transition will focus first on defining the on-disk data models for the ``Exposure``-replacement types, which will take the form of `Pydantic <https://docs.pydantic.dev/latest/>`__ model classes with ShoeFits annotations for both the top-level ``Exposure`` replacement and all components (see :ref:`serialization-features-and-patterns`).
These will be used to reimplement serialization for ``Exposure`` and its current component types in pure Python.
The new on-disk data models will be invoked by new `lsst.daf.butler.Formatter` types, and we'll be able to configure them in our data repositories without changing any of the code, so this phase of the transition should be almost entirely transparent to our pipeline/task code.

The next part of the transition involves writing new pure-Python interfaces for each ``Exposure`` replacement type and all component types.
Many component implementations will continue to be backed by our current C++ code, but we'll make sure that any interfaces we define do not assume or require C++ implementations.
For some particularly simple component types, the Pydantic model may serve as the eventual in-memory type as well,
These new types should map naturally to the serialization models, and the thinking that will have gone into those models and the experience gained from working with the current ``afw`` types should combine to make this much less daunting than it might sound.
The top level types will correspond to new butler storage classes, but they'll share a `~lsst.daf.butler.Formatter` with ``Exposure``, much in the same way that ``Arrow`` and ``DataFrame`` share a formatter, allowing us to do conversions in `~lsst.daf.butler.Butler.get` and `~lsst.daf.butler.Butler.put`.
We'll want to replace the storage class of existing dataset types (or define new versions of those dataset types, if we want to change the names anyway) to ensure the new types are the ones users get by default.
At this stage individual `~lsst.pipe.base.PipelineTask` implementations can opt in to the new types by using a new storage class in their connections, but as long as they use the old storage class in their connections they won't be affected.
Evolving task code will typically proceed from a top-level `~lsst.pipe.base.PipelineTask` down to its subtasks, with calls converting between new and old types at the boundary (at worst we can use the model types to convert between them, but it will probably make sense to have direct bidirectional conversion methods).

The final code conversions will be C++ algorithms that currently take ``Exposure`` or its components.
In the vast majority of cases, I expect us to change the signatures on the C++/Python boundary to work with lower-level objects (arrays and built-in scalars).
For example, ``lsst.afw.image.Image`` is just a `numpy.ndarray` and two integers, and in all cases I can think of, we'd actually be better off only passing to C++ a PSF model image rather than a full, spatially varying PSF model object.

This means that actually dropping the ``Exposure`` class, its components, and the ``afw.table.io`` framework can only occur at the end of a very long process, and throughout that process the old classes and new classes will coexist.
``Exposure`` itself may be the first to go, and some component types that need to be passed to C++ may never be converted.
The ``afw.table.io`` library can be retired only when we decide to drop support for reading datasets written before the transition to the new data models.
There is currently no plan for implementing an alternate reader for old files - it's probably possible, but it would be easier to migrate any old processing runs we need to keep via a conversion script than support the old format indefinitely.
Keeping the old code around for a long time is not ideal, of course, but we will still reap substantial benefits from relying on it less, well before it is actually removed.

The ShoeFits File Format
========================

The way the new ShoeFits library maps Python objects to FITS files is heavily inspired by the `Advanced Scientific Data Format (ASDF) <https://asdf-standard.readthedocs.io/en/1.1.1/>`__, and especially its ASDF-in-FITS extension.
ASDF combines a YAML tree with a sequence of binary blocks, allowing most of a tree of complex objects to be represented in YAML, while allowing large arrays of floating point data to be pulled out of that tree stored naturally in binary form.
This is of course the same overall approach as FITS, but with FITS's archaic, limited header replaced by a modern hierarchical text format.
ASDF also defines a data model for common astrophysical primitives like celestial coordinates via JSON schema.
ASDF-in-FITS is a little-used extension to the ASDF embeds the YAML tree and optional binary blocks into a FITS HDU as 1-d character image or binary table column.
It also allows the YAML tree to reference binary data in other FITS HDUs, in much the same way ASDF binary blocks are referenced.

The ShoeFits approach is slightly different:

- it is always a subset of FITS, rather than a potential standalone format, and all binary storage uses FITS mechanisms;
- it embeds a JSON tree in a FITS binary table column, instead of YAML;

JSON is far simpler than YAML and much easier and faster to parse as a result, while still being able to represent the same data structures.
Even more importantly, library support for JSON in Python is in great shape, especially via the `Pydantic <https://docs.pydantic.dev/latest/>`__ library that ShoeFits builds on, and the same cannot be said for YAML.
The ShoeFits approach to data modeling is sufficiently similar to ASDF that it would be straightforward (but real work) to extend the ShoeFits library to support writing and reading ASDF files, without having to change any downstream ShoeFits-based serialization implementations.
ShoeFits explicitly adopts ASDF's JSON schemas for common astrophysical objects while using Pydantic to generate JSON schemas for custom objects, and those schemas provide the extra "tag" information that would be needed to turn a JSON tree (or an equivalent Python nested `dict`) into YAML.

ShoeFits nevertheless has a lot of FITS-specific interfaces because its goal is to map Python objects to *fully featured* FITS files, with FITS-standard WCSs and other headers that allow them to be at least mostly interpretable by third-party FITS readers that ignore the JSON tree.
These FITS header cards are *exported* from the Python object tree: they are never read when reconstructing a Python object hierarchy from the serialized form, and hence we expect to duplicate the header information in the JSON tree (where it can often be expressed more naturally anyway).
This helps keep the ShoeFits library simple: it only needs to be able to read the files it writes, not arbitrary external FITS files, and for this it only needs to be able to read JSON (which it can delegate to Pydantic) and FITS binary data.
If we add ASDF read/write support to ShoeFits in the future, the annotations used to declare FITS header exports would simply be ignored, and could be left out of any objects that would only be serialized to ASDF.

Objects serializable with ShoeFits are also by definition serializable as plain JSON, though in some cases this would be a very bad idea (e.g. a 4k x 4k image would have to be be represented as a nested JSON array or base64-encoded byte string).

ShoeFits could probably be extended to read and write HDF5 as well, though this would be harder to implement than ASDF.
While HDF5 is also hierarchical and supports the same primitive types as JSON (and then some), a lot of the type mapping that ShoeFits can currently leave to Pydantic would have to be written from scratch for HDF5.
Implementing HDF5 support would probably amount to writing code that walks a JSON-like nested `dict` (but one containing `numpy.ndarray` values as well as the standard JSON-like types) and the corresponding JSON schema simultaneously in order to translate it to HDF5.

.. _serialization-features-and-patterns:

Serialization Features and Patterns
===================================

.. note::

    This section is written with currently-hypothetical links to an `lsst.shoefits` section of ``pipelines.lsst.io``, which can't work now because ShoeFits isn't actually part of the stack yet.
    When it is, we'll set up the links to make this user-guide-like section more useful (and/or copy it into the code documentation).
    Unqualified Python type names should be assumed to be from ShoeFits.

Basics
------

Objects serializable with ShoeFits are at their core just `Pydantic model types <https://docs.pydantic.dev/latest/concepts/models/>`__, and hence the work of making an existing type serializable involves either:

- making the object itself inherit from ``pydantic.BaseModel`` (probably appropriate only for the simplest objects);
- defining a new ``class`` that inherits from ``pydantic.BaseModel`` that represents the serialized form of the type.

Pydantic itself provides support for serializing most Python standard library types, and ShoeFits extends this to `numpy.ndarray` and a few Astropy types via type aliases of `typing.Annotated`::

    import pydantic
    import lsst.shoefits as shf

    class Example(pydantic.BaseModel):
        array: shf.Array
        time: shf.Time
        instrument: str

At runtime these fields correspond to `numpy.ndarray` and `astropy.time.Time` (and `str`), respectively, and static type checkers like MyPy will see them that way as well.
When serialized to a JSON tree, this struct will use ASDF data models for representing them in JSON, and in the case of `~lsst.shoefits.Array`, the array data itself may be pulled out of the tree with a string pointer to a FITS HDU written in its place.
For this to work, the serialization needs to go through `~lsst.shoefits.FitsWriteContext` and `~lsst.shoefits.FitsReadContext`, which invoke Pydantic's JSON write/read logic with special hooks that intercept these annotations.

To control how fields appear in the FITS representation, parameterized annotations can be used::

    import pydantic
    import lsst.shoefits as shf
    from typing import Annotated

    class Example(pydantic.BaseModel):
        array: Annotated[shf.Array, shf.FitsOptions(extname="DATA")]
        time: shf.Time
        instrument: Annotated[str, shf.ExportFitsHeaderKey("INSTRUME")]

These FITS-specific annotations would be ignored by any other `~lsst.shoefits.WriteContext` or `~lsst.shoefits.ReadContext` implementation, but for the FITS implementations they result in the ``array`` field being writtend to an image extension HDU with ``EXTNAME='DATA'``, and the ``instrument`` field's value written to a FITS header ``INSTRUME`` key.
The corresponding file layout is shown below.

.. literalinclude:: example-layout.txt

For highly nested objects that map to multiple HDUs, the `~lsst.shoefits.Struct` class (a subclass of ``pydantic.BaseModel``) can be used to control whether a field's header exports are exported to the headers of HDUs created by sibling, parent, or child fields.
`~lsst.shoefits.Struct` also provides hooks for more fine-grained control over the FITS representation and ways to populate FITS headers with calculated values.


Serialization by Proxy
----------------------

In order to make a custom type serializable via a separate model class, the mapping can be defined via an `~lsst.shoefits.Adapter` subclass::

    import pydantic
    import lsst.shoefits as shf
    from typing import Annotated, TypeAlias

    class Thing:
        """An arbitrary type that isn't serializable directly."""

        def __init__(self, a: int):
            self._a = a


    class ThingModel(pydantic.BaseModel):
        """A model type representing the serializable form of `Thing`."""
        a: int

    class ThingAdapter(shf.Adapter[Thing, ThingModel]):
        """Class that declares serialization for `Thing` via `ThingModel`."""

        @property
        def model_type -> type[ThingModel]:
            return ThingModel

        def to_model(self, thing: Thing) -> ThingModel:
            return ThingModel(a=thing._a)

        def from_model(self, model: ThingModel) -> Thing:
            return Thing(model.a)

    SerializableThing: TypeAlias = Annotated[Thing, ThingAdapter]

Any parent model type can now declare a field of type ``SerializableThing``, which will be a ``Thing`` instance at runtime and in static type checkers, while being transparently serializable via ``ThingModel``.

ShoeFits Primitives
-------------------

ShoeFits defines a few new serializable classes that can be used as building blocks for higher-level models:

- `~lsst.shoefits.Box` is analogous to `lsst.geom.Box2I`, but is not limited to two dimensions.
  This is a Pydantic model and is hence directly serializable.
- `~lsst.shoefits.Interval` is analogous to `lsst.geom.IntervalI`, and exists largely to help implement `~lsst.shoefits.Box`.
  It is also a Pydantic model.
- `~lsst.shoefits.Image` is analogous to `lsst.afw.image.Image`: it combines 2-d`numpy.ndarray` with a 2-d integer offset that can be used to match a subimage's coordinate system to that of its parent image.
  It also has an optional `astropy.units.Unit`, allowing images with units to be saved via the ASDF ``Quantity`` data model.
  `~lsst.shoefits.Image` is not a Pydantic model, but it implements Pydantic's special custom-object serialization hooks in the same way the `~lsst.shoefits.Array` type alias does, allowing it to be stored in-line in the JSON tree or (usually) in a separate FITS image HDU.
  When saved to FITS HDU, a special FITS WCS is written to represent the integer offset coordinate system, just as with `lsst.afw.image.Image`.
- `~lsst.shoefits.Mask` is analogous to `lsst.afw.image.Mask`, i.e. an integer bitmask, but it delegates management of the mask planes to a separate `~lsst.shoefits.MaskSchema` object that can be shared by `~lsst.shoefits.Mask` instances without being a singleton.
  Unlike its ``afw`` counterpart, `~lsst.shoefits.Mask` is backed by a 3-d array, with the last dimension used to support dynamic number of mask planes: typically the ``dtype`` of a `~lsst.shoefits.Mask` backing array is just ``unit8``, and the shape of the last dimension is the number of mask planes divided by eight.

These types provide some convenience methods for use as first-class in-memory types (subimage slicing and mask plane interpretation), but are not a complete replacement for their C++-backed `lsst.geom` and `lsst.afw.image` counterparts.
Instead, they can be used to implement serialization for those types via the
`~lsst.shoefits.Adapter` interface, e.g.::

    from lsst.geom import Box2I, Point2I
    import lsst.shoefits as shf

    class BoxAdapter(shf.Adapter[Box2I, shf.Box]):
        @property
        def model_type(self) -> type[shf.Box]:
            return shf.Box
        def to_model(self, box: Box2I) -> shf.Box:
            return shf.Box.factory[box.getSlices()]
        def from_model(self, model: shf.Box) -> Box2I:
            return Box2I(Point2I(box.x.min, box.x.max), Point2I(box.y.min, box.y.max))

Defining these adapters will be one of the first tasks involved in implementing the ShoeFits models to replace ``Exposure``.

These adapters can be used directly as an annotation, i.e. ``Annotated[Box2I, BoxAdapter]``, but in many cases it will be easier to just call the adapter methods directly in some higher-level `~lsst.shoefits.Adapter`.

Polymorphism
------------

Some of our most important ``Exposure`` component types are instances of an abstract base class or reliant internally on one, such as `lsst.afw.detection.Psf` or `lsst.afw.math.BoundedField`.
When the set of possible subclasses can be fully enumerated when a parent model type is defined, it's often best to do just enumerate them using `typing.Union` or the equivalent ``|`` syntax::

    import pydantic

    class A(pydantic.BaseModel):
        value: int

    class B(pydantic.BaseModel):
        value: str

    class Holder(pydantic.BaseModel):
        nested: A | B

Pydantic's `discriminated union <https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions>`__ functionality can be used to make this pattern much more efficient and robus (the default implementation on read is to try all possibilities until one works).
Union types benefit fully from Pydantic's JSON schema generation and don't require any special extension hooks or import logic to work.

When the set of possible subtypes cannot be enumerated in advance, the `~lsst.shoefits.Polymorphic` annotation can be used to indicate that an `~lsst.shoefits.Adapter` can be looked up via a serialized "tag" string::

    from abc import ABC, abstractmethod
    from typing import Annotated
    import lsst.shoefits as shf

    class Base(ABC):

        @abstractmethod
        def get_value(self) -> int:
            raise NotImplementedError()

        @abstractmethod
        def _get_tag(self) -> str:
            raise NotImplementedError()

    class Holder(pydantic.BaseModel):
        nested: Annotated[Base, shf.Polymorphic(lambda x: x._get_tag())]

We can then declare an implementation downstream via an adapter::

    class Derived1(Base):
        def get_value(self) -> int:
            return 1

        def _get_tag(self) -> str:
            return "one"

    class Model1(pydantic.BaseModel):
        pass

    class Adapter1(shf.Adapter[Derived1, Model1]):

        @property
        def model_type(self) -> type[Model1]:
            return Model1

        def to_model(self, d: Derived1) -> Model1:
            return Model1()

        def from_model(self, m: Model1) -> Derived1:
            return Derived1()

And finally register it::

    registry = shf.PolymorphicAdapterRegistry()
    registry.register_adapted("one", Adapter1())

For the case where a polymorphic implementation class is itself a Pydantic model, we can skip the adapter class and register it as native::

    class Derived2(Base, pydantic.BaseModel):
        value: int

        def get_value(self) -> int:
            return self.value

        def _get_tag(self) -> str:
            return "two"

    registry.register_native("two", Derived2)

In both cases, the registration step needs to happen before reading begins, which means that it is not sufficient to declare a global `~lsst.shoefits.PolymorphicAdapterRegistry` instance in a low-level package and have downstream packages add their own types to it at import time, unless something else takes responsibility for importing them before read attempts are made.
The exact mechanism we'll use to solve this problem is TBD; ShoeFits tries to be agnostic to it, largely to avoid imposing any solution that might run afoul of security concerns (e.g. importing modules according to serialized strings).

In all the above, the definition of the ``Base`` ABC is actually unimportant: it's generally good practice, of course, as a way to clearly define an interface, and static type checkers will see ``Annotated[Base, Polymorphic(...)]`` as just ``Base``, as usual with `Annotated`.
But neither ShoeFits nor Pydantic will actually check that objects loaded via the adaper registry actually inherit from ``Base``, so it's perfectly viable for the annotation to be a `typing.Protocol` or even just `typing.Any` or `object`, if the interface isn't formalized or strongly typed.

In addition to the complexity involved in setting up an adapter registry, the major disadvantage of `~lsst.shoefits.Polymorphic` is that there is no way to emit JSON schema for polymorphic fields, since the parent model type has no information about how those fields will be serialized.

Reading Compressed Subimages
============================

ShoeFits mostly sidesteps the limitations of ``cfitsio`` in terms of reading from object stores by delegating to `astropy.io.fits` instead.
But while Astropy can read and write full files and uncompressed image sections via `fsspec <https://filesystem-spec.readthedocs.io/en/latest/?badge=latest>`__, this support doesn't include reading sections of binary tables or compressed images over object stores.

Addressing this will require a small amount of compiled-language code, as decompression, dequantization, and rescaling algorithms implemented in pure Python would be far too slow.
To make custom low-level reading code as simple and fast as possible, ShoeFits ensures enough information is written to the final JSON-tree FITS extension to allow the "index" of a tile-compressed image HDU (i.e. the fixed-size binary table data pointers, not including the "heap") to be loaded from a single byte-range read that can ignore that HDU's header.
This involves writing some additional byte addresses to the JSON-tree extension and only using a subset of the FITS tile compression standard (e.g. only 64-bit "Q" pointers and a fixed column order).

The provisional plan for the compiled-language read support is to implement this in a separate ``minimal_network_fitsio`` Python extension module that would be a dependency of ShoeFits.
At first it would support only lossless GZIP compression, since that's what we actually use today, and it would not do any FITS header parsing; it'd expect callers to use `astropy.io.fits` for that in Python (as ShoeFits will).
It also won't do any I/O itself: it will return byte range addresses for callers to fetch, and then accept those raw bytes and transform them into image data.
It would be designed to grow into something usable as the backend for a more general-purpose FITS reader like Astropy's, even if its initial focus is extremely narrow.
Keeping it separate from ShoeFits will hopefully help it pick up external contributions in this direction, in addition to keeping the complexity of a compiled extension module out of ShoeFits itself.

I would like to implement this module in Rust, and have the DM stack consume it via conda (which makes it unnecessary for the stack or ``rubin-env`` to include any Rust tooling).
I believe the interfaces and scope are simple enough that we can make that work in this case without requiring more-frequent-than-usual updates to the ``rubin-env`` metapackage.
Rust's libraries and toolchain for compiled Python extension modules will make it much easier (relative to C or C++) to set up the package and leverage third-party decompression code (for GZIP), without making it any even harder to call small bits of vendored CFITSIO code if that becomes useful.
While Rust would be a new language for DM-maintained code, we have a few developers with Rust experience already, and I believe the benefits outweigh the drawbacks.

The Long-Term Trajectory of the LSST Science Pipelines
======================================================

By proposing the replacement and eventual retirement of many of our workhorse `lsst.afw` classes, this proposal is implicitly suggesting a very different future for much of our codebase, beyond the changes it directly proposes.
And while I don't want the relatively concrete ShoeFits proposal to get tied up a long debate about competing visions, my own (still vague) vision for the future of the stack did play a role in putting this proposal together (and wanting to use Rust in part of it).

So, with the caveat that this section is *context* for the RFC, not part of the RFC itself:

- I'd like each separate git package to have its own semver releases, with dependencies between packages handled by standard packaging tools like ``pip`` and ``conda``.
  I believe we will have to merge some already-large packages to make this happen, but these are cases where the packages are already hopelessy interdependent in practice anyway (at the very least because downstream packages provide critical test coverage for upstream code).
  We may then be able to start refactoring these into packages that are genuinely lightly coupled (or at least only coupled in the right dependency direction), but we have to start by having our package structure reflect the real code dependencies that exist.

- I'd like to get rid of all of our cross-package C++ interfaces, and with them our standalone C++ shared libraries and unit tests.
  These shared libraries are *the* major impediment to distributing our code via PyPI.
  They're also a big piece of why the stack is slow to build and import, though it's not clear to what extent this is intrinsic to having a lot of shared libraries or an interaction with other atypical packaging procedures.
  This mostly involves moving data structures up to Python and passing simpler types to C++ code.
  Merging packages also helps here, because it transforms cross-package C++ interfaces into intra-package C++ interfaces.

- I'd like to write a new low-level astronomical geometry library that combines the functionality in `lsst.sphgeom`, `lsst.geom`, and `lsst.afw.geom`, while improving consistency and avoiding subtle but hard-to-fix mistakes in the current types.
  This would include our wrappers for AST (which I'd like to abstract away a bit more) and all of the mid-level data structures I envision us needing to define in a compiled language for downstream compiled-langauge modules to reuse.
  That means that it should export a Python C API, to allow those downstream modules to build against it without needing a separate shared library.
  Leaving room for this future library (without assuming it will be available anytime soon) is one reason why the geometry types in ShoeFits are as simple as possible.

- I'd like to move away from C++ wherever we can in implementations as well as interfaces.
  This mostly means preferring Python, as we already do.
  But I also think we should consider JIT-compilation tools like JAX and Numba as alternatives to C++ for algorithmic code, especially when something can be expressed via algorithmic primitives that may benefit from GPUs in the future.
  And we should consider Rust as an alternative to C++ in cases where a compiled language is needed but the problem involves complex data structures and/or systems programming rather than numerics.
  I do expect that there will be cases where C++ will remain the best choice due to either history or the availability of certain third-party libraries, but I'd like to isolate and minimize these.

- Our Python packages should move with the rest of the Python ecosystem to adopt static type checking, automatic formatting, PEP8 naming, etc.
  This is harder stance than I've taken in the past on these topics, but while I'm still not planning to make a push on them anytime soon, I do want us to adopt them now in any context where doing so is not disruptive.

I should emphasize that these are not goals I expect us to make much progress on as we make the difficult transition from construction to operations, and we may never get to something approximating the end point I have in mind by the end of the survey (and by that time other technologies will certainly change this picture at least a little).
But I believe something like this vision would make our codebase much more maintainable and usable when the *next* 10 years of Rubin Observatory start to be discussed in earnest, and the more near-term chagnes described in the rest of this technical note will represent a substantial move in what I hope is the right direction.
