"""Scientific reference registry (pure Python, no Qt).

Every field not known from the research is None: nothing is invented. Only entries with
status "verified" have been checked against the original; the rest carry the details as
recalled and are shown as "citation details to be confirmed".

``python -m modules.references --bib [path]`` writes the BibTeX file (docs/references.bib).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VALID_STATUSES = ("verified", "to verify")
VALID_KINDS = ("article", "inproceedings", "book", "phdthesis", "patent", "misc")
UNVERIFIED_NOTE = "(citation details to be confirmed)"


@dataclass(frozen=True)
class Reference:
    key: str
    authors: Optional[str]
    year: Optional[int]
    title: Optional[str]
    venue: Optional[str]
    volume: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    status: str = "to verify"  # "verified" | "to verify"
    kind: str = "article"  # article | inproceedings | book | phdthesis | patent | misc
    groups: Tuple[str, ...] = ()
    number: Optional[str] = None  # issue number


G_SCREEN = "LRLC screening"
G_RTCUT = "Rt cutoff"
G_PICKETT = "Pickett plot"
G_BVW = "Bulk volume water"
G_SATMOD = "Saturation models"
G_SHF = "Saturation-height"
G_LAM = "Laminated sands"
G_INV = "Invasion"
G_DECON = "Deconvolution"
G_ELASTIC = "Elastic attributes"
G_ML = "Machine learning"

GROUP_ORDER = (
    G_SCREEN,
    G_RTCUT,
    G_PICKETT,
    G_BVW,
    G_SATMOD,
    G_SHF,
    G_LAM,
    G_INV,
    G_DECON,
    G_ELASTIC,
    G_ML,
)


def _r(key, authors, year, title, venue, **kw) -> Reference:
    return Reference(key=key, authors=authors, year=year, title=title, venue=venue, **kw)


_ENTRIES = [
    _r("liu2023", "Liu Chenglin et al.", 2023,
       "Resistivity cutoff of low-resistivity and low-contrast pays in sandstone reservoirs "
       "from conventional well logs",
       "Open Geosciences", volume="15", number="1", doi="10.1515/geo-2022-0520",
       status="verified", groups=(G_SCREEN, G_RTCUT)),
    _r("ashfaq_us11709287", "Ashfaq", None, None, "US 11,709,287 B2",
       url="https://patents.google.com/patent/US11709287B2",
       status="verified", kind="patent", groups=(G_ELASTIC, G_SCREEN)),
    _r("gao2022", "Gao et al.", 2022,
       "Identification of low-resistivity-low-contrast pay zones in the feature space with a "
       "multi-layer perceptron",
       "Petroleum Science", volume="19", number="2", pages="570-580",
       doi="10.1016/j.petsci.2021.12.012", groups=(G_ML, G_SCREEN)),
    _r("zhao2022", "Zhao et al.", 2022,
       "Genetic mechanisms and identification of low-resistivity pay zones, Pengyang area, "
       "Ordos Basin",
       "Geofluids", doi="10.1155/2022/3299768", status="verified", groups=(G_SCREEN,)),
    _r("boyd1995", "Boyd, Darling, Tabanou, Davis, Lyon, Flaum, Klein, Sneider, Sibbit and "
       "Singer", 1995, "The Lowdown on Low-Resistivity Pay", "Oilfield Review", volume="7",
       number="3", pages="4-18",
       url="https://www.slb.com/-/media/files/oilfield-review/08950418.pdf",
       status="verified", groups=(G_SCREEN,)),
    _r("worthington2000", "Worthington", 2000,
       "Recognition and evaluation of low-resistivity pay", "Petroleum Geoscience",
       volume="6", number="1", pages="77-92", doi="10.1144/petgeo.6.1.77",
       status="verified", groups=(G_SCREEN,)),
    _r("zemanek1989", "Zemanek", 1989, "Low-Resistivity Hydrocarbon-Bearing Sand Reservoirs",
       "SPE Formation Evaluation", volume="4", number="4", pages="515-521",
       doi="10.2118/15713-PA", status="verified", groups=(G_SCREEN,)),
    _r("pickett1966", "Pickett", 1966,
       "A Review of Current Techniques for Determination of Water Saturation From Logs",
       "Journal of Petroleum Technology", volume="18", number="11", pages="1425-1433",
       doi="10.2118/1446-PA", status="verified", groups=(G_PICKETT,)),
    _r("buckles1965", "Buckles", 1965, "Correlating and Averaging Connate Water Saturation Data",
       "Journal of Canadian Petroleum Technology", volume="4", number="1", pages="42-52",
       doi="10.2118/65-01-07", status="verified", groups=(G_BVW,)),
    _r("morris1967", "Morris and Biggs", 1967,
       "Using Log-Derived Values of Water Saturation and Porosity",
       "SPWLA 8th Annual Logging Symposium", pages="Paper X", kind="inproceedings",
       groups=(G_BVW,)),
    _r("crain_handbook", "Crain", None, "Crain's Petrophysical Handbook",
       "Accessible Petrophysics Ltd (online)", url="https://www.spec2000.net", kind="misc",
       groups=(G_BVW,)),
    _r("archie1942", "Archie", 1942,
       "The Electrical Resistivity Log as an Aid in Determining Some Reservoir "
       "Characteristics", "Transactions of the AIME", volume="146", number="1", pages="54-62",
       doi="10.2118/942054-G", status="verified", groups=(G_PICKETT, G_RTCUT, G_SATMOD)),
    _r("simandoux1963", "Simandoux", 1963,
       "Mesures dielectriques en milieu poreux, application a la mesure des saturations en "
       "eau, etude du comportement des massifs argileux",
       "Revue de l'Institut Francais du Petrole", volume="18 (supplementary issue)",
       pages="193-215", groups=(G_RTCUT, G_SATMOD)),
    _r("poupon1971", "Poupon and Leveaux", 1971,
       "Evaluation of Water Saturation in Shaly Formations",
       "SPWLA 12th Annual Logging Symposium", kind="inproceedings",
       groups=(G_RTCUT, G_SATMOD)),
    _r("waxman1968", "Waxman and Smits", 1968, "Electrical Conductivities in Oil-Bearing Shaly "
       "Sands", "Society of Petroleum Engineers Journal", volume="8", number="2",
       pages="107-122", doi="10.2118/1863-A", status="verified", groups=(G_RTCUT, G_SATMOD)),
    _r("clavier1984", "Clavier, Coates and Dumanoir", 1984,
       "Theoretical and Experimental Bases for the Dual-Water Model for Interpretation of "
       "Shaly Sands", "Society of Petroleum Engineers Journal", volume="24", number="2",
       pages="153-168", doi="10.2118/6859-PA", status="verified",
       groups=(G_RTCUT, G_SATMOD)),
    _r("ipa1998", "IPA", 1998, None, "Block A-18 JDA study", kind="misc", groups=(G_SCREEN,)),
    _r("thomas1975", "Thomas and Stieber", 1975, None, "SPWLA 16th Annual Logging Symposium",
       kind="inproceedings", groups=(G_LAM,)),
    _r("tolioe2016", "Tolioe et al.", 2016, None, "PETRONAS, Malay Basin", kind="misc",
       groups=(G_SCREEN,)),
    _r("poupon1954", "Poupon, Loy and Tixier", 1954, None, "JPT", volume="6", number="6",
       pages="27-34", groups=(G_LAM,)),
    _r("hagiwara_us4739255", "Hagiwara", None, None, "US 4,739,255", kind="patent",
       groups=(G_LAM,)),
    _r("hagiwara1997", "Hagiwara", 1997, None, "SPE Formation Evaluation", volume="12",
       number="4", pages="235-240", groups=(G_LAM,)),
    _r("clavier1976", "Clavier, Heim and Scala", 1976, None,
       "SPWLA 17th Annual Logging Symposium", kind="inproceedings", groups=(G_SATMOD,)),
    _r("ongc2025", "ONGC", 2025, None, "SPG India, Dhaman Formation", kind="misc",
       groups=(G_SCREEN,)),
    _r("hill1979", "Hill, Shirley and Klein", 1979, None, "The Log Analyst",
       groups=(G_SATMOD,)),
    _r("juhasz1981", "Juhasz", 1981, None, "SPWLA 22nd Annual Logging Symposium",
       kind="inproceedings", groups=(G_SATMOD,)),
    _r("rasmus1986", "Rasmus", 1986, None, None, kind="misc", groups=(G_SATMOD,)),
    _r("borai1987", "Borai", 1987, None, "SPE Formation Evaluation", groups=(G_SATMOD,)),
    _r("guo2023", "Guo et al.", 2023, None, "Frontiers in Earth Science", volume="11",
       pages="1223997", doi="10.3389/feart.2023.1223997", groups=(G_ML,)),
    _r("doll1949", "Doll", 1949, None, "JPT", volume="1", number="6", pages="148-162",
       groups=(G_INV,)),
    _r("anderson2001", "Anderson", 2001, None, "TU Delft", kind="phdthesis",
       groups=(G_DECON,)),
    _r("thadani1981", "Thadani and Hall", 1981, "Propagated geometric factors in induction logging",
       "SPWLA 22nd Annual Logging Symposium", kind="inproceedings", groups=(G_INV, G_DECON)),
    _r("coll1993", "Coll et al.", 1993, None, "AAPG, Ceuta field", kind="misc",
       groups=(G_LAM,)),
    _r("us6963803", None, None, None, "US 6,963,803", kind="patent", groups=(G_DECON,)),
    _r("leverett1941", "Leverett", 1941, None, "Trans. AIME", volume="142", pages="152-169",
       groups=(G_SHF,)),
    _r("skelt1995", "Skelt and Harrison", 1995, None, "SPWLA 36th Annual Logging Symposium",
       kind="inproceedings", groups=(G_SHF,)),
    _r("harrison2001", "Harrison and Jing", 2001, None, "SPE 71326", kind="inproceedings",
       groups=(G_SHF,)),
    _r("tudge2010", "Tudge", 2010, None, "University of Leicester", kind="misc",
       groups=(G_LAM,)),
]

REFERENCES: Dict[str, Reference] = {e.key: e for e in _ENTRIES}


def refs_for(*keys: str) -> List[Reference]:
    """Entries for ``keys``; an unknown key raises KeyError."""
    return [REFERENCES[k] for k in keys]


# ----------------------------------------------------------------- formatting


def _author_list(authors: str) -> List[str]:
    if authors.endswith(" et al."):
        return [authors[: -len(" et al.")]]
    return [a.strip() for a in re.split(r",\s*|\s+and\s+", authors) if a.strip()]


def _short_authors(ref: Reference) -> str:
    if not ref.authors:
        return ref.venue or ref.key
    if ref.authors.endswith(" et al."):
        return ref.authors
    names = _author_list(ref.authors)
    if len(names) == 1:
        return names[0]
    if len(names) > 3:
        return names[0] + " et al."
    return ", ".join(names[:-1]) + " and " + names[-1]


def format_short(key: str) -> str:
    """Hagiwara (1997); Boyd et al. (1995); patents without a year show the patent number."""
    ref = REFERENCES[key]
    if ref.kind == "patent":
        if ref.authors:
            return f"{ref.authors}, {ref.venue}" if ref.venue else ref.authors
        return ref.venue or key
    who = _short_authors(ref)
    return f"{who} ({ref.year})" if ref.year is not None else who


def _link(ref: Reference) -> Optional[str]:
    if ref.doi:
        return f"doi:{ref.doi}"
    return ref.url


def format_full(key: str) -> str:
    """Short citation plus the known details; unverified entries end with a notice."""
    ref = REFERENCES[key]
    parts = [format_short(key)]
    if ref.kind == "patent":
        if ref.title:
            parts.append(ref.title)
    else:
        if ref.title:
            parts.append(ref.title)
        if ref.venue:
            vol = ref.volume or ""
            if ref.number:
                vol += f"({ref.number})"
            venue = ref.venue + (f" {vol}" if vol else "")
            if ref.pages:
                venue += f", {ref.pages}"
            parts.append(venue)
    link = _link(ref)
    if link:
        parts.append(link)
    text = ". ".join(parts) + "."
    if ref.status != "verified":
        text += " " + UNVERIFIED_NOTE
    return text


# --------------------------------------------------------------------- BibTeX

_VENUE_FIELD = {
    "article": "journal",
    "inproceedings": "booktitle",
    "book": "publisher",
    "phdthesis": "school",
    "patent": "howpublished",
    "misc": "howpublished",
}


def _bib_authors(authors: str) -> str:
    names = [("{" + n + "}") if " " in n else n for n in _author_list(authors)]
    if authors.endswith(" et al."):
        names.append("others")
    return " and ".join(names)


def to_bibtex(key: str) -> str:
    ref = REFERENCES[key]
    entry_type = "misc" if ref.kind == "patent" else ref.kind
    fields: List[Tuple[str, str]] = []
    if ref.authors:
        fields.append(("author", _bib_authors(ref.authors)))
    if ref.title:
        fields.append(("title", ref.title))
    if ref.venue:
        fields.append((_VENUE_FIELD[ref.kind], ref.venue))
    if ref.year is not None:
        fields.append(("year", str(ref.year)))
    if ref.volume:
        fields.append(("volume", ref.volume))
    if ref.number:
        fields.append(("number", ref.number))
    if ref.pages:
        fields.append(("pages", ref.pages))
    if ref.doi:
        fields.append(("doi", ref.doi))
    if ref.url:
        fields.append(("url", ref.url))
    fields.append(("note", ref.status))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{entry_type}{{{ref.key},\n{body}\n}}\n"


def to_bibtex_all() -> str:
    return "\n".join(to_bibtex(k) for k in sorted(REFERENCES))


def default_bib_path() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "references.bib"


def write_bibtex(path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_bibtex_all())
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.references")
    parser.add_argument("--bib", nargs="?", const="", default=None, metavar="PATH",
                        help="write the BibTeX file (default docs/references.bib)")
    args = parser.parse_args(argv)
    if args.bib is None:
        parser.print_help()
        return 1
    out = write_bibtex(args.bib or default_bib_path())
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
