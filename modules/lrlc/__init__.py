"""Low-resistivity low-contrast (LRLC) pay tools.

Pure numerical code (numpy, scipy, pandas only; no Qt, no pipeline import).
"""

# Methods whose Method & Reference box ships in this release, with their reference keys
# (modules/references.py). tests/test_references.py checks every key exists.
SHIPPED_METHODS = {
    "screening": ("boyd1995", "worthington2000", "zemanek1989"),
    "pickett": ("pickett1966", "archie1942"),
    "bvw": ("buckles1965", "morris1967", "crain_handbook"),
    "buckles": ("buckles1965", "morris1967", "crain_handbook"),
    "rt_cutoff": ("liu2023", "archie1942", "simandoux1963", "poupon1971", "waxman1968", "clavier1984"),
}
