"""The product's name and links, read from brand.json so the backend, the
page head, and the frontend cannot drift apart."""
from importlib.resources import files
import json

BRAND = json.loads(files("waymark").joinpath("brand.json").read_text(encoding="utf-8"))
NAME = BRAND["name"]
