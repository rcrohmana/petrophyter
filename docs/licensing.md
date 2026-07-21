[Back to README](../README.md)

# Licensing

Petrophyter is dual-licensed. The applicable license depends on which parts of the project are used.

| License | File | Use case |
|---|---|---|
| Apache-2.0 | [LICENSE-APACHE-2.0](../LICENSE-APACHE-2.0) | Permissive reuse of core modules |
| GPL-3.0 | [LICENSE-GPL-3.0](../LICENSE-GPL-3.0) | Full application with the PyQt6 interface |

## License Summary

```text
+-----------------------------------------------------------------------+
|                      PETROPHYTER LICENSING                            |
+-----------------------------------------------------------------------+
|                                                                       |
|  +---------------------------+    +---------------------------+       |
|  |      CORE MODULES         |    |     FULL APPLICATION      |       |
|  |      (modules/*.py)       |    |     (with PyQt6 UI)       |       |
|  |                           |    |                           |       |
|  |      Apache-2.0           |    |      GPL-3.0              |       |
|  |      - Permissive         |    |      - Copyleft           |       |
|  |      - Commercial OK      |    |      - Source required    |       |
|  |      - No GPL spread      |    |      - PyQt6 compliant    |       |
|  +---------------------------+    +---------------------------+       |
|                                                                       |
+-----------------------------------------------------------------------+
```

## What This Means

- If you use only core calculation modules such as `modules/petrophysics.py`, without the PyQt6 interface, you may use the Apache-2.0 license. It is permissive and does not impose copyleft on the wider application.
- If you use the complete application, including the PyQt6 interface, GPL-3.0 applies because of PyQt6 licensing terms.
- To use PyQt6 without GPL, purchase a [commercial PyQt6 license](https://www.riverbankcomputing.com/commercial/pyqt).

## Third-Party Licenses

See [NOTICE](../NOTICE) for the complete list of third-party components and their licenses.
