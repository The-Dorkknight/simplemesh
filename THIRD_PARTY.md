# Third-party software

SimpleMesh's own code is released under GPL-3.0-only (see [LICENSE](LICENSE)). It runs inside, and uses the Python API of:

- **Blender** (https://www.blender.org), free software under the GNU GPL. Blender's licensing expects add-ons that use its Python API to be GPL-compatible, which is why this project is GPL rather than non-commercial-only. Blender and the Blender logo are trademarks of the Blender Foundation. SimpleMesh is not affiliated with or endorsed by the Blender Foundation.
- **NumPy** (BSD licence) is used when Blender ships it; SimpleMesh also works without it.

Design inspiration only (no code used): PrusaSlicer and Bambu Studio (place on face, cut plane), Tinkercad (shapes, handles, holes, sizes on the model), SketchUp and Fusion (push/pull a face), and the Blender add-ons listed in [docs/DESIGN.md](docs/DESIGN.md). Those names are trademarks of their owners; no affiliation.

For development only: the `bpy` module from PyPI (Blender as a Python module, GPL) is used by the tests and demo renders.

Printer names (FlashForge, Bambu Lab, Creality) appear only as bed-size presets; they are trademarks of their owners and there is no affiliation. Their licences are not reproduced here; follow the links in each project's own repository.
