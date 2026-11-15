"""An upgrade does not mark existing wells out of date: the parameter hash of a well that uses no
new setting is the same as in v1.14.0.

The expected hashes were computed with v1.14.0 on the same three wells (LRLC off, LRLC on with
default settings, saturation height on, both on). A change here means wells show as out of date
after the upgrade; if that is intended, say so in the release notes and update the values.
"""
from tests.test_session_v2 import three_wells  # noqa: F401

V1_14_0 = {
    "off": ["755a2730d3760a1444248446e3b7faa55b64ab36", "104374e2e57624b3ed71b469930775354203000c",
            "af2266b49bc29100ce4cca19b259519b9d5bda46"],
    "lrlc": ["67f119a1f7894037c476f4ab158f5a4c440c1428", "cc2b686ec1c963985b10bff6454fedafe1ca0608",
             "5c3db4cb737504ead8ebc23e737cbd5d62422a73"],
    "shf": ["d0a38b459bbcf3ea76dfc3f402515a7a27f0fc6f", "597b18a75bf992cf18e35e5579e88bc5421e0277",
            "d914c22860777ea9c87d47347645d37ec18f0d9b"],
    "both": ["9f7a76c4ab2038b9c80659b65f34353f50e09c65", "f95f9b29ed706e9f3c6e419a96e7e47c849fddb2",
             "b27d435d9bcc6d757aa1f8276f9ecbb2835febe5"],
}


def test_hashes_of_existing_wells_match_v1_14_0(three_wells):  # noqa: F811
    model, keys = three_wells

    def hashes():
        return [model.well_params_hash(model.project.get(k)) for k in keys]

    assert hashes() == V1_14_0["off"]
    model.project.lrlc["enabled"] = True
    assert hashes() == V1_14_0["lrlc"]
    model.project.lrlc["enabled"] = False
    model.project.shf["enabled"] = True
    assert hashes() == V1_14_0["shf"]
    model.project.lrlc["enabled"] = True
    assert hashes() == V1_14_0["both"]


def test_confirming_the_fluids_changes_the_hash(three_wells):  # noqa: F811
    model, keys = three_wells
    model.project.shf["enabled"] = True
    ds = model.project.get(keys[0])
    model.project.shf["fluids_confirmed"] = True
    assert model.well_params_hash(ds) != V1_14_0["shf"][0]
