import re


COUNTRY_MAP = {
    "china": "China",
    "chinese": "China",
    "prc": "China",
    "thailand": "Thailand",
    "thai": "Thailand",
    "india": "India",
    "indian": "India",
    "japan": "Japan",
    "japanese": "Japan",
    "korea": "South Korea",
    "korean": "South Korea",
    "south korea": "South Korea",
    "vietnam": "Vietnam",
    "vietnamese": "Vietnam",
    "viet nam": "Vietnam",
    "indonesia": "Indonesia",
    "philippines": "Philippines",
    "malaysia": "Malaysia",
    "singapore": "Singapore",
    "taiwan": "Taiwan",
    "hong kong": "Hong Kong",
    "brazil": "Brazil",
    "brazilian": "Brazil",
    "ecuador": "Ecuador",
    "mexico": "Mexico",
    "mexican": "Mexico",
    "usa": "United States",
    "u.s.a.": "United States",
    "united states": "United States",
    "america": "United States",
    "australia": "Australia",
    "australian": "Australia",
    "france": "France",
    "french": "France",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "british": "United Kingdom",
    "germany": "Germany",
    "german": "Germany",
    "israel": "Israel",
    "iran": "Iran",
    "madagascar": "Madagascar",
    "tanzania": "Tanzania",
    "mozambique": "Mozambique",
    "kenya": "Kenya",
    "bangladesh": "Bangladesh",
    "sri lanka": "Sri Lanka",
    "panama": "Panama",
    "peru": "Peru",
    "colombia": "Colombia",
    "honduras": "Honduras",
    "nicaragua": "Nicaragua",
    "guatemala": "Guatemala",
    "belize": "Belize",
    "venezuela": "Venezuela",
}

HOST_ALIAS_MAP = {
    "penaeus vannamei": "Litopenaeus vannamei",
    "litopenaeus vannamei": "Litopenaeus vannamei",
    "penaeus (litopenaeus) vannamei": "Litopenaeus vannamei",
    "whiteleg shrimp": "Litopenaeus vannamei",
    "pacific white shrimp": "Litopenaeus vannamei",
    "pacific whiteleg shrimp": "Litopenaeus vannamei",
    "penaeus monodon": "Penaeus monodon",
    "black tiger shrimp": "Penaeus monodon",
    "macrobrachium rosenbergii": "Macrobrachium rosenbergii",
    "giant freshwater prawn": "Macrobrachium rosenbergii",
    "macrobrachium nipponense": "Macrobrachium nipponense",
    "procambarus clarkii": "Procambarus clarkii",
    "red swamp crayfish": "Procambarus clarkii",
    "eriocheir sinensis": "Eriocheir sinensis",
    "chinese mitten crab": "Eriocheir sinensis",
    "scylla serrata": "Scylla serrata",
    "callinectes sapidus": "Callinectes sapidus",
    "carcinus maenas": "Carcinus maenas",
    "penaeus stylirostris": "Penaeus stylirostris",
    "marsupenaeus japonicus": "Marsupenaeus japonicus",
    "penaeus japonicus": "Marsupenaeus japonicus",
    "fenneropenaeus chinensis": "Fenneropenaeus chinensis",
    "shrimp": "Penaeus spp.",
    "shrimps": "Penaeus spp.",
    "prawn": "Penaeus spp.",
    "prawns": "Penaeus spp.",
    "penaeid shrimp": "Penaeus spp.",
    "crustacean": "Crustacea",
    "crustaceans": "Crustacea",
    "crab": "Brachyura",
    "crabs": "Brachyura",
    "crayfish": "Astacidea",
    "lobster": "Astacidea",
}

HOST_CN_MAP = {
    "Litopenaeus vannamei": "南美白对虾",
    "Penaeus monodon": "斑节对虾",
    "Penaeus spp.": "对虾属",
    "Macrobrachium rosenbergii": "罗氏沼虾",
    "Macrobrachium nipponense": "日本沼虾",
    "Procambarus clarkii": "克氏原螯虾",
    "Eriocheir sinensis": "中华绒螯蟹",
    "Scylla serrata": "锯缘青蟹",
    "Callinectes sapidus": "蓝蟹",
    "Carcinus maenas": "欧洲绿蟹",
    "Marsupenaeus japonicus": "日本囊对虾",
    "Fenneropenaeus chinensis": "中国对虾",
    "Penaeus stylirostris": "蓝对虾",
    "Crustacea": "甲壳动物",
    "Brachyura": "短尾类",
    "Astacidea": "螯虾类",
}


def clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return text


def first_qualifier(feature, *keys):
    if not feature:
        return ""
    for key in keys:
        values = feature.qualifiers.get(key)
        if values:
            return clean_text(values[0])
    return ""


def parse_taxonomy(taxonomy):
    if not taxonomy:
        return "", "", ""
    if isinstance(taxonomy, str):
        parts = [p.strip() for p in taxonomy.split(";")]
    else:
        parts = [clean_text(p) for p in taxonomy if clean_text(p)]

    family = ""
    genus = ""
    species = ""
    for part in parts:
        lower = part.lower()
        if lower.endswith("viridae"):
            family = part
        elif lower.endswith("virus") and " " not in part:
            genus = part
        elif "virus" in lower:
            species = part
    return family, genus, species


def extract_virus_name(definition):
    text = clean_text(definition)
    if not text:
        return ""
    match = re.search(r"([A-Z][a-z]*(?:\s+[A-Za-z0-9().-]+){0,6}\s+virus)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"([A-Za-z][A-Za-z0-9().\s-]*virus)", text)
    if match:
        return match.group(1).strip()
    return text[:160].strip()


def normalize_host_name(raw_host):
    text = clean_text(raw_host)
    if not text:
        return ""

    normalized = re.sub(r"\s+", " ", text).strip()
    lower = normalized.lower()
    if lower in HOST_ALIAS_MAP:
        return HOST_ALIAS_MAP[lower]

    for alias, canonical in HOST_ALIAS_MAP.items():
        if alias in lower:
            return canonical

    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[a-z][a-z.-]+){1,3}", normalized):
        return normalized
    return normalized


def standardize_country(raw_country):
    text = clean_text(raw_country)
    if not text:
        return ""

    lower = text.lower()
    for key, value in COUNTRY_MAP.items():
        if key in lower:
            return value
    return text


def parse_geo_components(raw_geo):
    text = clean_text(raw_geo)
    if not text:
        return "", "", ""

    parts = [clean_text(part) for part in re.split(r":|,", text) if clean_text(part)]
    if not parts:
        return "", "", ""

    country = standardize_country(parts[0])
    province = parts[1] if len(parts) > 1 else ""
    city = parts[2] if len(parts) > 2 else ""
    return country, province, city


def parse_lat_lon(raw_lat_lon):
    text = clean_text(raw_lat_lon)
    if not text:
        return None, None

    match_lat = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([NS])", text, re.IGNORECASE)
    match_lon = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([EW])", text, re.IGNORECASE)
    if match_lat and match_lon:
        lat = float(match_lat.group(1))
        lon = float(match_lon.group(1))
        if match_lat.group(2).upper() == "S":
            lat = -lat
        if match_lon.group(2).upper() == "W":
            lon = -lon
        return round(lat, 6), round(lon, 6)

    numbers = re.findall(r"[+-]?\d+(?:\.\d+)?", text)
    if len(numbers) >= 2:
        return round(float(numbers[0]), 6), round(float(numbers[1]), 6)
    return None, None


def extract_collection_year(raw_date):
    text = clean_text(raw_date)
    if not text:
        return ""
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else ""


def extract_reference_metadata(record):
    refs = record.annotations.get("references", []) or []
    selected = None
    for ref in refs:
        if clean_text(getattr(ref, "pubmed_id", "")):
            selected = ref
            break
    if selected is None and refs:
        selected = refs[0]

    return {
        "pmid": clean_text(getattr(selected, "pubmed_id", "")) if selected else "",
        "title": clean_text(getattr(selected, "title", "")) if selected else "",
        "authors": clean_text(getattr(selected, "authors", "")) if selected else "",
        "journal": clean_text(getattr(selected, "journal", "")) if selected else "",
    }


def extract_record_metadata(record):
    source = next((feat for feat in record.features if feat.type == "source"), None)
    definition = clean_text(record.description)
    taxonomy = record.annotations.get("taxonomy", [])
    family, genus, species = parse_taxonomy(taxonomy)

    geo_raw = first_qualifier(source, "country", "geo_loc_name")
    country, province, city = parse_geo_components(geo_raw)
    collection_date = first_qualifier(source, "collection_date")
    lat, lon = parse_lat_lon(first_qualifier(source, "lat_lon"))
    host_raw = first_qualifier(source, "host", "lab_host")
    isolation_source = first_qualifier(source, "isolation_source")
    isolate_name = first_qualifier(source, "isolate")
    ref_meta = extract_reference_metadata(record)

    return {
        "accession": clean_text(record.id),
        "virus_name": extract_virus_name(definition),
        "taxon_family": family,
        "taxon_genus": genus,
        "taxon_species": species,
        "genome_length": len(record.seq),
        "genome_type": clean_text(record.annotations.get("molecule_type", "")),
        "keywords": ", ".join([clean_text(k) for k in record.annotations.get("keywords", []) if clean_text(k)]),
        "reference": ref_meta,
        "host_raw": host_raw,
        "host_name": normalize_host_name(host_raw),
        "host_common_name_cn": HOST_CN_MAP.get(normalize_host_name(host_raw), ""),
        "country": country,
        "province": province,
        "city": city,
        "latitude": lat,
        "longitude": lon,
        "collection_date": collection_date,
        "collection_year": extract_collection_year(collection_date),
        "isolation_source": isolation_source,
        "source_type": "GenBank source feature" if source else "",
        "note": isolate_name or isolation_source,
        "geo_raw": geo_raw,
        "definition": definition,
    }
