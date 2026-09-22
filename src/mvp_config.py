"""RESCENE-specific identity mapping for the current MVP."""

RESCENE_ARTIST_ID = "artist_rescene"

RESCENE_CHANNELS = {
    "@RESCENE_official": {
        "artist_id": RESCENE_ARTIST_ID,
        "is_official": True,
    },
    "@helloiamwoninicetomeetyou": {
        "artist_id": RESCENE_ARTIST_ID,
        "is_official": False,
    },
}
